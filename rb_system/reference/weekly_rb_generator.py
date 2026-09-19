#!/usr/bin/env python3
"""Weekly FXCM EURUSD RB (Rejection Block) reference generator.

Parallel to `rb_system/ob_reference/weekly_ob_generator.py`, but builds
Rejection Blocks instead of Order Blocks, per the confirmed spec in
`rb_system/RB_Indicator_v1.pine` (header comment + addRBFromSwing /
tryBullARB / tryBearARB / STEP2 / STEP3).

Swing/MSS detection is REUSED VERBATIM from `weekly_ob_generator.py`'s
`WeeklyOBEngine`: the CSV loading, minute-of-week aggregation, forex-week
boundary convention, and the peak/trough/high_first/regime/MSS state
machine are byte-identical in structure to that file (copied, not
re-derived) so that the two engines' swing/MSS output can be diffed and
MUST match exactly. Only the zone-construction/lifecycle layer differs:
where the OB engine calls add_ifob/try_bull_aob/try_bear_aob/AIFOB and runs
OB eligibility+impact+close-through lifecycle, this engine instead builds
IRB/ARB zones directly from swing-pivot wicks and runs RB's simpler
impact+stranding-only lifecycle (RB_Indicator_v1.pine STEP2/STEP3).

No third-party Python packages required. Python 3.9+.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
RB_STATE = {0: "IRB", 1: "ARB", 2: "ORB", 3: "SPENT"}


@dataclass(frozen=True)
class Minute:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    ao: float
    ah: float
    al: float
    ac: float
    ticks: int


@dataclass
class Week:
    start: datetime
    end: datetime
    o: float
    h: float
    l: float
    c: float
    first: int
    last: int  # exclusive minute index


@dataclass
class Event:
    confirm: int
    kind: int  # 0 high, 1 low
    swing: int
    price: float
    at: Optional[datetime]


@dataclass
class MSS:
    at: int
    broken: int
    price: float
    up: bool


@dataclass
class RbZone:
    id: int
    candle: int          # anchor swing-pivot's own week index (leftIdx in pine)
    zb: float
    zt: float
    bullish: bool         # by RAW WICK TYPE: swing-low wick=True, swing-high wick=False
    trigger: int           # week index the hunt fired (IFOB/AOB-equivalent moment)
    eligible: int           # -1 = not yet eligible; else week index eligibility was set
    stop: int                # -1 = extending; else week index of impact
    state: int                 # 0=IRB,1=ARB,2=ORB,3=SPENT
    origin: int                 # creation-type marker, permanent: 0=IRB-style,1=ARB-style
    pre_spent_state: int
    trigger_time: Optional[datetime] = None
    eligible_time: Optional[datetime] = None
    impact_time: Optional[datetime] = None


# ---------------------------------------------------------------------------
# CSV loading / week aggregation -- copied verbatim in structure from
# weekly_ob_generator.py (same rules must apply so results are comparable).
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly RB reference generator (parallel to weekly_ob_generator.py)")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2", help="timezone represented by Date/Time in CSV")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--out-dir", default=None, help="output directory, default: alongside this script's ../data")
    return p.parse_args()


def parse_stamp(d: str, t: str, tz: ZoneInfo) -> datetime:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(d.strip() + " " + t.strip(), fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            pass
    raise ValueError(f"unsupported Date/Time: {d!r} {t!r}")


def load_minutes(path: Path, input_tz: ZoneInfo, side: str) -> Tuple[List[Minute], List[str]]:
    need = {"Date", "Time", "OpenBid", "HighBid", "LowBid", "CloseBid", "OpenAsk", "HighAsk", "LowAsk", "CloseAsk"}
    out: List[Minute] = []
    warnings: List[str] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        missing = need - set(rd.fieldnames or [])
        if missing:
            raise ValueError("CSV is missing columns: " + ", ".join(sorted(missing)))
        for row_no, r in enumerate(rd, 2):
            try:
                t = parse_stamp(r["Date"], r["Time"], input_tz)
                values = [float(r[x]) for x in ("OpenBid", "HighBid", "LowBid", "CloseBid", "OpenAsk", "HighAsk", "LowAsk", "CloseAsk")]
                tick_text = r.get("TotalTicks") or r.get("Total Ticks") or "0"
                out.append(Minute(t, *values, int(float(tick_text))))
            except Exception as exc:
                raise ValueError(f"row {row_no}: {exc}") from exc
    if not out:
        raise ValueError("CSV has no rows")
    out.sort(key=lambda x: x.t)
    unique: List[Minute] = []
    for m in out:
        if unique and m.t == unique[-1].t:
            warnings.append("duplicate minute removed: " + m.t.isoformat())
            continue
        unique.append(m)
    if side == "ask":
        unique = [Minute(m.t, m.ao, m.ah, m.al, m.ac, m.ao, m.ah, m.al, m.ac, m.ticks) for m in unique]
    return unique, warnings


def forex_week_start(t: datetime, close_zone: ZoneInfo, close_hour: int) -> datetime:
    local = t.astimezone(close_zone)
    days_since_sunday = (local.weekday() + 1) % 7
    candidate_date = local.date() - timedelta(days=days_since_sunday)
    start = datetime(candidate_date.year, candidate_date.month, candidate_date.day, close_hour, tzinfo=close_zone)
    if local < start:
        start -= timedelta(days=7)
    return start.astimezone(UTC)


def aggregate_weeks(minutes: List[Minute], close_zone: ZoneInfo, close_hour: int) -> List[Week]:
    weeks: List[Week] = []
    i = 0
    while i < len(minutes):
        start = forex_week_start(minutes[i].t, close_zone, close_hour)
        end = (start.astimezone(close_zone) + timedelta(days=7)).astimezone(UTC)
        j = i + 1
        high, low = minutes[i].h, minutes[i].l
        while j < len(minutes) and minutes[j].t < end:
            high = max(high, minutes[j].h)
            low = min(low, minutes[j].l)
            j += 1
        weeks.append(Week(start, end, minutes[i].o, high, low, minutes[j - 1].c, i, j))
        i = j
    return weeks


# ---------------------------------------------------------------------------
# Weekly RB engine
# ---------------------------------------------------------------------------

class WeeklyRBEngine:
    """Swing/MSS state machine reused verbatim from WeeklyOBEngine.  RB zone
    construction/lifecycle follows RB_Indicator_v1.pine (addRBFromSwing,
    tryBullARB, tryBearARB, STEP2, STEP3) instead of OB's add_ifob/try_*_aob.
    """

    def __init__(self, minutes: List[Minute], weeks: List[Week]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]
        self.events: List[Event] = []
        self.msses: List[MSS] = []
        self.rbs: List[RbZone] = []
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0
        self.ei = 0
        self.last_h = self.last_l = -1

    # -- exact-1m helpers, copied verbatim from weekly_ob_generator.py --
    def event_time(self, kind: int, k: int) -> Optional[datetime]:
        if k <= 0:
            return None
        wk = self.w[k]
        threshold = self.w[k - 1].l if kind == 0 else self.w[k - 1].h
        for m in self.m[wk.first:wk.last]:
            if (m.l < threshold) if kind == 0 else (m.h > threshold):
                return m.t
        return None

    def first_touch(self, start: datetime, k: int, bull: bool, zb: float, zt: float) -> Optional[datetime]:
        wk = self.w[k]
        a = max(wk.first, bisect_left(self.mt, start))
        for m in self.m[a:wk.last]:
            if (m.l <= zt and m.h >= zb):
                return m.t
        return None

    def high_first(self, k: int) -> bool:
        wk = self.w[k]
        hi = lo = None
        for x in self.m[wk.first:wk.last]:
            if hi is None and x.h >= wk.h:
                hi = x
            if lo is None and x.l <= wk.l:
                lo = x
            if hi and lo:
                break
        if hi and lo:
            if hi.t != lo.t:
                return hi.t < lo.t
            return hi.c < hi.o
        return wk.c < wk.o

    def add_event(self, confirm: int, kind: int, swing: int, price: float) -> None:
        self.events.append(Event(confirm, kind, swing, price, self.event_time(kind, confirm)))
        dest = self.sw_highs if kind == 0 else self.sw_lows
        if not dest or dest[-1] != swing:
            dest.append(swing)

    # -- RB construction, translated from RB_Indicator_v1.pine --
    def cross_time(self, k: int, level: float, above: bool) -> Optional[datetime]:
        """Exact M1 minute, within week k, that price first crosses `level`.

        `above`=True looks for the first minute whose HIGH exceeds `level`
        (a bullish break); False looks for the first minute whose LOW falls
        below `level` (a bearish break). Mirrors the inline scan
        `weekly_ob_generator.py`'s `add_ifob`/`set_promoted_ifob_trigger`
        use to find the real trigger minute (lines ~429-433/450-454) --
        NOT `event_time()`, whose threshold is hard-coded to the PREVIOUS
        week's high/low and is only equivalent when the armed swing's own
        price happens to equal that boundary.
        """
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > level) if above else (m.l < level):
                return m.t
        return None

    def add_rb_from_swing(self, idx: int, is_high: bool, trigger_k: int, st: int, trigger_time: Optional[datetime]) -> int:
        wk = self.w[idx]
        if is_high:
            zb, zt, bull = max(wk.o, wk.c), wk.h, False
        else:
            zb, zt, bull = wk.l, min(wk.o, wk.c), True
        eligible = trigger_k if st == 1 else -1
        z = RbZone(len(self.rbs) + 1, idx, zb, zt, bull, trigger_k, eligible, -1, st, st, st)
        z.trigger_time = trigger_time
        if eligible >= 0:
            # ARB: eligibility is immediate, the same real moment as the
            # trigger itself (per the RB spec) -- not a copy of the week
            # boundary this used to be derived from.
            z.eligible_time = trigger_time
        self.rbs.append(z)
        return len(self.rbs) - 1

    def try_bull_arb(self, preg: int, aob_swh_i: int, new_swl_i: int, k: int, ev_at: Optional[datetime]) -> None:
        # mirrors tryBullAOB's guard exactly (RB_Indicator_v1.pine tryBullARB)
        if preg != 1 or aob_swh_i < 0:
            return
        armed_h_price = self.w[aob_swh_i].h
        if any(self.w[v].h >= armed_h_price for v in range(aob_swh_i + 1, new_swl_i + 1)):
            return
        self.add_rb_from_swing(aob_swh_i, True, k, 1, ev_at)

    def try_bear_arb(self, preg: int, aob_swl_i: int, new_swh_i: int, k: int, ev_at: Optional[datetime]) -> None:
        if preg != 2 or aob_swl_i < 0:
            return
        armed_l_price = self.w[aob_swl_i].l
        if any(self.w[v].l <= armed_l_price for v in range(aob_swl_i + 1, new_swh_i + 1)):
            return
        self.add_rb_from_swing(aob_swl_i, False, k, 1, ev_at)

    def consume_break(self, bull: bool, k: int) -> bool:
        if bull:
            if not self.have_h or self.w[k].h <= self.h_price:
                return False
            if self.regime == 2:
                self.msses.append(MSS(k, self.h_idx, self.h_price, True))
            self.regime = 1
            if self.last_l >= 0:
                # IRB trigger = exact M1 minute this break (of the armed
                # swing-high price self.h_price) actually happens, not
                # week k's own open (RB_Indicator_v1.pine: IFOB's break-
                # confirmation moment).
                self.add_rb_from_swing(self.last_l, False, k, 0, self.cross_time(k, self.h_price, True))  # IRB, bullish (swing-low wick)
            self.have_h = False
            return True
        if not self.have_l or self.w[k].l >= self.l_price:
            return False
        if self.regime == 1:
            self.msses.append(MSS(k, self.l_idx, self.l_price, False))
        self.regime = 2
        if self.last_h >= 0:
            self.add_rb_from_swing(self.last_h, True, k, 0, self.cross_time(k, self.l_price, False))  # IRB, bearish (swing-high wick)
        self.have_l = False
        return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True
                self.h_price = ev.price
                self.h_idx = ev.swing
                self.try_bear_arb(preg, armed_l, ev.swing, k, ev.at)
            else:
                self.have_l = True
                self.l_price = ev.price
                self.l_idx = ev.swing
                self.try_bull_arb(preg, armed_h, ev.swing, k, ev.at)

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        # STEP 2: arm swings + IRB delayed eligibility (k > triggerK).
        while self.ei < total and self.events[self.ei].confirm == k:
            ev = self.events[self.ei]
            if ev.kind == 0:
                if not consumed_h:
                    self.have_h = True
                    self.h_price = ev.price
                    self.h_idx = ev.swing
                self.last_h = ev.swing
                for z in self.rbs:
                    if z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            else:
                if not consumed_l:
                    self.have_l = True
                    self.l_price = ev.price
                    self.l_idx = ev.swing
                self.last_l = ev.swing
                for z in self.rbs:
                    if not z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            self.ei += 1

        # STEP 3: RB lifecycle -- IMPACT + STRANDING only, no close-through.
        hk, lk = self.w[k].h, self.w[k].l
        for z in self.rbs:
            if z.state == 3:
                continue
            if z.eligible != -1 and k >= z.eligible:
                if hk >= z.zb and lk <= z.zt:
                    z.pre_spent_state = z.state
                    z.state = 3
                    z.stop = k
                    z.impact_time = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
                    continue
            if z.state in (0, 1) and z.eligible != -1:
                is_irb = z.origin != 1
                stranded = False
                for ev in self.events[before:total]:
                    if ev.confirm != k:
                        continue
                    if is_irb:
                        if z.bullish and ev.kind == 1 and ev.price > z.zt:
                            stranded = True
                        if not z.bullish and ev.kind == 0 and ev.price < z.zb:
                            stranded = True
                    else:
                        if z.bullish and ev.kind == 0 and ev.price < z.zb:
                            stranded = True
                        if not z.bullish and ev.kind == 1 and ev.price > z.zt:
                            stranded = True
                    if stranded:
                        break
                if stranded:
                    z.state = 2

    # -- main loop: swing detection copied verbatim from weekly_ob_generator.py --
    def process(self, k: int) -> None:
        if k == 0:
            return
        wh, wl = self.w[k].h, self.w[k].l
        high_first = self.high_first(k)
        br_h, br_l = wh > self.w[k - 1].h, wl < self.w[k - 1].l
        dual = br_h and br_l
        n = len(self.events)
        previous_dual = n >= 2 and self.events[-1].kind != self.events[-2].kind and self.events[-1].confirm == self.events[-2].confirm == k - 1
        pairs = {(self.events[-1].kind, self.events[-1].swing), (self.events[-2].kind, self.events[-2].swing)} if previous_dual else set()
        before = len(self.events)

        def h_action():
            if self.w[k].h > self.w[self.peak].h:
                self.peak = k
            if br_h and (not self.events or self.events[-1].kind != 1) and not (previous_dual and not dual and (1, self.trough) in pairs):
                self.add_event(k, 1, self.trough, self.w[self.trough].l)
                self.peak = k

        def l_action():
            if self.w[k].l < self.w[self.trough].l:
                self.trough = k
            if br_l and (not self.events or self.events[-1].kind != 0) and not (previous_dual and not dual and (0, self.peak) in pairs):
                self.add_event(k, 0, self.peak, self.w[self.peak].h)
                self.trough = k

        if high_first:
            h_action(); l_action()
        else:
            l_action(); h_action()

        total = len(self.events)
        for ev in self.events[self.ei:total]:
            if ev.confirm != k:
                break
            if ev.kind == 0:
                self.last_h = ev.swing
            else:
                self.last_l = ev.swing

        preg, armed_h, armed_l = self.regime, self.h_idx, self.l_idx
        if high_first:
            c_h = self.consume_break(True, k)
            self.mid_arm(k, preg, armed_h, armed_l)
            c_l = self.consume_break(False, k)
        else:
            c_l = self.consume_break(False, k)
            self.mid_arm(k, preg, armed_h, armed_l)
            c_h = self.consume_break(True, k)
        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)):
            self.process(k)


def iso(t: Optional[datetime]) -> str:
    return "" if t is None else t.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def display_iso(t: Optional[datetime], zone: ZoneInfo) -> str:
    return "" if t is None else t.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")


def status(z: RbZone) -> str:
    return RB_STATE[z.pre_spent_state if z.state == 3 else z.state]


def write_outputs(out_dir: Path, engine: WeeklyRBEngine, display_zone: ZoneInfo) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "weekly_rb_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["record", "kind", "origin", "confirm", "price"])
        for ev in engine.events:
            wr.writerow(["SWING", "HIGH" if ev.kind == 0 else "LOW", iso(engine.w[ev.swing].start), iso(engine.w[ev.confirm].start), f"{ev.price:.5f}"])
        for mss in engine.msses:
            wr.writerow(["MSS_UP" if mss.up else "MSS_DOWN", "", iso(engine.w[mss.broken].start), iso(engine.w[mss.at].start), f"{mss.price:.5f}"])

    with (out_dir / "weekly_rb_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "type", "side", "origin_week_idx", "origin_start_utc", "origin_start_display",
                   "bottom", "top", "trigger_week_idx", "trigger_time_utc", "trigger_time_display",
                   "eligible_week_idx", "eligible_time_utc", "eligible_time_display",
                   "status", "stop_week_idx", "impact_time_utc", "impact_time_display"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for z in engine.rbs:
            wr.writerow({
                "id": z.id,
                "type": RB_STATE[z.origin],
                "side": "BUY" if z.bullish else "SELL",
                "origin_week_idx": z.candle,
                "origin_start_utc": iso(engine.w[z.candle].start),
                "origin_start_display": display_iso(engine.w[z.candle].start, display_zone),
                "bottom": f"{z.zb:.5f}",
                "top": f"{z.zt:.5f}",
                "trigger_week_idx": z.trigger,
                "trigger_time_utc": iso(z.trigger_time),
                "trigger_time_display": display_iso(z.trigger_time, display_zone),
                "eligible_week_idx": z.eligible,
                "eligible_time_utc": iso(z.eligible_time),
                "eligible_time_display": display_iso(z.eligible_time, display_zone),
                "status": status(z),
                "stop_week_idx": z.stop,
                "impact_time_utc": iso(z.impact_time),
                "impact_time_display": display_iso(z.impact_time, display_zone),
            })

    counts = {}
    for z in engine.rbs:
        counts[status(z)] = counts.get(status(z), 0) + 1
    with (out_dir / "weekly_rb_report.txt").open("w", encoding="utf-8") as f:
        f.write(f"Weeks processed: {len(engine.w)}\n")
        f.write(f"Swing events: {len(engine.events)} (highs {len(engine.sw_highs)}, lows {len(engine.sw_lows)})\n")
        f.write(f"MSS events: {len(engine.msses)}\n")
        f.write(f"RB zones: {len(engine.rbs)}\n")
        for k, v in sorted(counts.items()):
            f.write(f"  {k}: {v}\n")


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    close_zone = ZoneInfo(args.week_close_zone)
    display_zone = ZoneInfo(args.display_tz)
    minutes, warnings = load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    weeks = aggregate_weeks(minutes, close_zone, args.week_close_hour)
    engine = WeeklyRBEngine(minutes, weeks)
    engine.run()
    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    write_outputs(out_dir, engine, display_zone)
    print(f"Weeks: {len(weeks)}  Swings: {len(engine.events)}  MSS: {len(engine.msses)}  RB zones: {len(engine.rbs)}")
    print(f"Output written to {out_dir}")


if __name__ == "__main__":
    main()
