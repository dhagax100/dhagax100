#!/usr/bin/env python3
"""Weekly FXCM EURUSD OB reference generator.

Stage 1 of the agreed project.  It consumes your exported 1-minute Bid/Ask
CSV and calculates the locked *Weekly* swing/MSS process from the Bid series.
Ask prices are retained for later execution work.

The program writes, next to its own file:
  weekly_ob_ledger.csv       all Weekly OB records and lifecycle timestamps
  weekly_ob_swings.csv       Weekly swings and MSS records
  weekly_ob_viewer.pine      static TradingView viewer for Weekly structure and OBs
  weekly_ob_report.txt       coverage, gaps and lifecycle counts

No third-party Python packages are required.  Python 3.9+ is sufficient.
The TradingView output uses that proven structure to draw the locked Weekly
OB lifecycle: IFOB, AOB, AIFOB, OOB, SPENT and rejected records.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
STATE = {0: "IFOB", 1: "AOB", 2: "OOB", 3: "SPENT", 4: "AIFOB"}

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
    at: Optional[datetime]  # exact M1 confirmation selected when this event is created


@dataclass
class MSS:
    at: int
    broken: int
    price: float
    up: bool


@dataclass
class Zone:
    id: int
    candle: int
    zb: float
    zt: float
    bullish: bool
    trigger: int
    eligible: int
    stop: int
    eligible_time: Optional[datetime]
    impact_time: Optional[datetime]
    eligible_kind: int
    state: int
    orig_state: int
    pre_spent_state: int
    rejected: bool = False
    # Facts are captured at the lifecycle transition.  They must never later
    # be reconstructed by a broad `(week, event kind)` lookup.
    trigger_time: Optional[datetime] = None
    trigger_price: Optional[float] = None
    trigger_swing_price: Optional[float] = None
    trigger_level_role: Optional[str] = None
    trigger_swing_week: int = -1
    trigger_confirm_week: int = -1
    trigger_path: str = ""
    eligible_price: Optional[float] = None
    eligible_swing_price: Optional[float] = None
    # Immutable lifecycle provenance.  `orig_state` is the current display
    # lineage and can change on promotion, so it cannot prove where a zone
    # began.
    created_state: int = -1
    promotion_from_state: int = -1
    promotion_time: Optional[datetime] = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locked Weekly structure reference generator")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC", help="timezone represented by Date/Time in CSV, default UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York", help="Forex week close timezone")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161), help="maximum recent records of each structure type to draw")
    p.add_argument("--pine-obs", type=int, default=120, choices=range(1, 451), help="maximum recent OBs to draw")
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21), help="maximum recent OBs shown in the ledger table")
    p.add_argument("--box-body-minutes", type=int, default=60, choices=(1, 5, 15, 30, 60), help="draw each OB using the first/last observed N-minute candle body assembled from M1 data (60=H1 audit convention)")
    p.add_argument("--origin-first-price", choices=("open", "close"), default="close", help="origin-body first M1 price; close is the locked default, open remains an audit fallback")
    p.add_argument("--origin-body-offset-minutes", type=int, default=0, choices=range(-240, 241), help="diagnostic display-only start offset; default 0 uses the scheduled Weekly open")
    p.add_argument("--display-tz", default="Asia/Riyadh", help="timezone used only for displayed diagnostics, default Asia/Riyadh")
    return p.parse_args()


def parse_stamp(d: str, t: str, tz: ZoneInfo) -> datetime:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(d.strip() + " " + t.strip(), fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            pass
    raise ValueError(f"unsupported Date/Time: {d!r} {t!r}")


def load_minutes(path: Path, input_tz: ZoneInfo, side: str) -> Tuple[List[Minute], List[str]]:
    # Tick count is useful later for diagnostics, but it is not required for
    # the locked Weekly OB calculation.  Exports name it differently or omit
    # it altogether, so accept either form without blocking the run.
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
    """Sunday 17:00 New York convention, including DST automatically."""
    local = t.astimezone(close_zone)
    # Monday=0; the latest Sunday close in local wall time.
    days_since_sunday = (local.weekday() + 1) % 7
    candidate_date = local.date() - timedelta(days=days_since_sunday)
    start = datetime(candidate_date.year, candidate_date.month, candidate_date.day, close_hour, tzinfo=close_zone)
    if local < start:
        start -= timedelta(days=7)
    return start.astimezone(UTC)


def aggregate_weeks(minutes: List[Minute], close_zone: ZoneInfo, close_hour: int) -> List[Week]:
    """Aggregate the original scheduled FXCM Weekly bars for OB-origin testing."""
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


class WeeklyOBEngine:
    """Direct Python transcription of the locked Weekly swing/MSS/OB process."""
    def __init__(self, minutes: List[Minute], weeks: List[Week]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]
        self.events: List[Event] = []
        self.msses: List[MSS] = []
        self.zones: List[Zone] = []
        self.active: List[int] = []
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0; self.ei = 0
        self.last_h = self.last_l = -1
        self.pend_bull_aifob = self.pend_bear_aifob = -1
        self.pend_bull_aob = self.pend_bear_aob = -1

    def event_time(self, kind: int, k: int) -> Optional[datetime]:
        if k <= 0: return None
        wk = self.w[k]; threshold = self.w[k - 1].l if kind == 0 else self.w[k - 1].h
        for m in self.m[wk.first:wk.last]:
            if (m.l < threshold) if kind == 0 else (m.h > threshold): return m.t
        return None

    def first_touch(self, start: datetime, k: int, bull: bool, zb: float, zt: float) -> Optional[datetime]:
        wk = self.w[k]
        a = max(wk.first, bisect_left(self.mt, start))
        for m in self.m[a:wk.last]:
            # Locked Weekly impact: a buy zone is touched by a strict M1 low
            # below its top; a sell zone by a strict M1 high above its bottom.
            if (m.l < zt) if bull else (m.h > zb): return m.t
        return None

    def high_first(self, k: int) -> bool:
        wk = self.w[k]; hi = lo = None
        for x in self.m[wk.first:wk.last]:
            if hi is None and x.h >= wk.h: hi = x
            if lo is None and x.l <= wk.l: lo = x
            if hi and lo: break
        if hi and lo:
            if hi.t != lo.t: return hi.t < lo.t
            return hi.c < hi.o
        return wk.c < wk.o

    def add_event(self, confirm: int, kind: int, swing: int, price: float) -> None:
        self.events.append(Event(confirm, kind, swing, price, self.event_time(kind, confirm)))
        dest = self.sw_highs if kind == 0 else self.sw_lows
        if not dest or dest[-1] != swing: dest.append(swing)

    def add_zone(self, candle: int, bull: bool, trigger: int, state: int) -> int:
        wk = self.w[candle]
        z = Zone(len(self.zones) + 1, candle, min(wk.o, wk.c), max(wk.o, wk.c), bull, trigger, -1, -1, None, None, -1, state, state, state)
        # AOB/AIFOB triggers are the specific event that already exists at
        # creation.  Persist it now so later rows cannot select another event
        # with the same weekly index and kind.
        if state in (1, 4):
            kind = (0 if bull else 1) if state == 1 else (1 if bull else 0)
            event = next((e for e in reversed(self.events) if e.confirm == trigger and e.kind == kind), None)
            if event is not None:
                z.trigger_time, z.trigger_price = event.at, event.price
                z.trigger_swing_price = event.price
                z.trigger_level_role = "event swing level"
                z.trigger_swing_week, z.trigger_confirm_week, z.trigger_path = event.swing, event.confirm, "created event"
        z.created_state = state
        self.zones.append(z); self.active.append(len(self.zones) - 1); return len(self.zones) - 1

    def claimed(self, candle: int, bull: bool) -> bool:
        return any(z.candle == candle and z.bullish == bull for z in self.zones)

    def aifob_in_range(self, lo: int, hi: int, bull: bool) -> bool:
        return any(z.orig_state == 4 and z.bullish == bull and lo <= z.candle <= hi for z in self.zones)

    def promote_aob(self, idx: int, bull: bool, k: int, armed_level: float, armed_swing: int) -> bool:
        if not (0 <= idx < len(self.zones)): return False
        z = self.zones[idx]
        if z.state == 1 and z.orig_state == 1 and z.bullish == bull and z.eligible < 0 and not z.rejected:
            z.promotion_from_state = z.state
            z.promotion_time = self.w[k].start
            z.state = z.orig_state = 0; z.eligible_time = None; z.eligible_kind = -1; z.eligible_price = None; z.eligible_swing_price = None; z.stop = -1
            self.set_promoted_ifob_trigger(z, bull, k, armed_level, armed_swing)
            return True
        return False

    def best(self, lo: int, hi: int, bullish_zone: bool, skip: int = -1) -> int:
        # Bullish zone: most bearish close. Bearish zone: most bullish close.
        chosen = -1
        for x in range(max(0, lo), min(len(self.w) - 1, hi) + 1):
            if x == skip: continue
            wk = self.w[x]
            if bullish_zone and wk.c < wk.o and (chosen < 0 or wk.c < self.w[chosen].c): chosen = x
            if not bullish_zone and wk.c > wk.o and (chosen < 0 or wk.c > self.w[chosen].c): chosen = x
        return chosen

    def best_ifob_origin(self, lo: int, hi: int, bullish_zone: bool, skip: int = -1) -> int:
        """Choose a direct-IFOB origin from real tradable weekly bodies only.

        Unlike the locked structural Weekly aggregation, this candidate rule
        ends each origin body at Friday close.  It therefore retains a genuine
        Friday-close/Monday-open gap and ignores Sunday pre-open quotes.
        """
        chosen = -1
        for x in range(max(0, lo), min(len(self.w) - 1, hi) + 1):
            if x == skip:
                continue
            body = self.ifob_origin_body(x)
            if body is None:
                continue
            o, c = body
            chosen_body = self.ifob_origin_body(chosen) if chosen >= 0 else None
            chosen_c = chosen_body[1] if chosen_body is not None else 0.0
            if bullish_zone and c < o and (chosen < 0 or c < chosen_c):
                chosen = x
            if not bullish_zone and c > o and (chosen < 0 or c > chosen_c):
                chosen = x
        return chosen

    def ifob_origin_body(self, k: int) -> Optional[Tuple[float, float]]:
        """First tradable M1 open and Friday's final tradable M1 close."""
        if not (0 <= k < len(self.w)):
            return None
        wk = self.w[k]
        last = bisect_left(self.mt, wk.start + timedelta(days=5)) - 1
        return None if last < wk.first else (self.m[wk.first].o, self.m[last].c)

    def try_bull_aob(self, preg: int, armed_h: int, new_low: int, price: float, k: int) -> None:
        if preg != 1 or armed_h < 0: return
        if any(self.w[v].h >= self.w[armed_h].h for v in range(armed_h + 1, new_low + 1)): return
        best = self.best(min(armed_h - 1, new_low), max(armed_h - 1, new_low), False)
        if best >= 0 and self.w[best].l > price:
            z = self.zones[self.add_zone(best, False, k, 1)]
            if k > 0 and self.w[k - 1].h > z.zt: z.rejected = True
            elif k > 0: z.eligible = k; z.eligible_kind = 1; z.eligible_time = self.event_time(1, k); z.eligible_price = self.w[k - 1].h; z.eligible_swing_price = price

    def try_bear_aob(self, preg: int, armed_l: int, new_high: int, price: float, k: int) -> None:
        if preg != 2 or armed_l < 0: return
        if any(self.w[v].l <= self.w[armed_l].l for v in range(armed_l + 1, new_high + 1)): return
        best = self.best(min(armed_l - 1, new_high), max(armed_l - 1, new_high), True)
        if best >= 0 and self.w[best].h < price:
            z = self.zones[self.add_zone(best, True, k, 1)]
            if k > 0 and self.w[k - 1].l < z.zb: z.rejected = True
            elif k > 0: z.eligible = k; z.eligible_kind = 0; z.eligible_time = self.event_time(0, k); z.eligible_price = self.w[k - 1].l; z.eligible_swing_price = price

    def try_bull_aifob(self, preg: int, had_h: bool, armed_h: int, last_low: int, new_low: int, k: int) -> int:
        if preg != 1 or not had_h or armed_h < 0 or last_low < 0 or self.w[k].l < self.w[new_low].l: return -1
        best = self.best(min(last_low, new_low, armed_h - 1), max(last_low, new_low, armed_h - 1), True)
        return self.add_zone(best, True, k, 4) if best >= 0 and not self.claimed(best, True) else -1

    def try_bear_aifob(self, preg: int, had_l: bool, armed_l: int, last_high: int, new_high: int, k: int) -> int:
        if preg != 2 or not had_l or armed_l < 0 or last_high < 0 or self.w[k].h > self.w[new_high].h: return -1
        best = self.best(min(last_high, new_high, armed_l - 1), max(last_high, new_high, armed_l - 1), False)
        return self.add_zone(best, False, k, 4) if best >= 0 and not self.claimed(best, False) else -1

    def add_ifob(self, bull: bool, k: int, swing: int, last_opposite: int) -> None:
        lo, hi = min(last_opposite, k, swing), max(last_opposite, k, swing)
        if self.aifob_in_range(lo, hi, bull): return
        locked_best = self.best(lo, hi, bull, skip=k)
        best = self.best_ifob_origin(lo, hi, bull, skip=k)
        if best >= 0 and not self.claimed(best, bull):
            idx = self.add_zone(best, bull, k, 0)
            z = self.zones[idx]
            # Preserve all established direct-IFOB bodies.  Only when an
            # opening gap makes the real tradable-session candidate differ
            # from the old pre-open-based candidate do we replace its body.
            body = self.ifob_origin_body(best) if best != locked_best else None
            if body is not None:
                z.zb, z.zt = min(body), max(body)
            relevant_kind = 0 if bull else 1
            # `swing` is the armed event consumed by this exact IFOB.  A
            # broad latest-event lookup can attach an unrelated same-kind
            # swing when multiple events occur before the break.
            event = next((e for e in reversed(self.events) if e.kind == relevant_kind and e.swing == swing and e.confirm <= k), None)
            if event is not None and k > 0:
                # The prior Weekly extreme establishes the IFOB's structural
                # condition, but the trigger fact is the first exact M1 break
                # of the stored enabling swing.  Keep the former as audit
                # evidence; do not let it replace the trigger's time/price.
                z.trigger_swing_price = event.price
                z.trigger_price = self.w[k - 1].h if bull else self.w[k - 1].l
                z.trigger_level_role = "prior-week high break level" if bull else "prior-week low break level"
                z.trigger_swing_week, z.trigger_confirm_week, z.trigger_path = event.swing, event.confirm, "direct IFOB armed event"
                wk = self.w[k]
                for m in self.m[bisect_left(self.mt, wk.start):bisect_left(self.mt, wk.end)]:
                    if (m.h > z.trigger_swing_price) if bull else (m.l < z.trigger_swing_price):
                        z.trigger_time = m.t
                        break

    def set_promoted_ifob_trigger(self, z: Zone, bull: bool, k: int, armed_level: float, armed_swing: int) -> None:
        """Replace inherited AIFOB facts when it becomes an IFOB.

        The promotion is caused by the armed opposite swing being broken. That
        exact swing—not the earlier AIFOB event—is the new IFOB trigger level.
        """
        z.trigger = k
        z.trigger_price = armed_level
        z.trigger_swing_price = armed_level
        z.trigger_level_role = "armed swing-high break level" if bull else "armed swing-low break level"
        z.trigger_swing_week, z.trigger_confirm_week, z.trigger_path = armed_swing, k, "promoted IFOB armed event"
        z.trigger_time = None
        if z.promotion_from_state < 0:
            z.promotion_from_state = z.state
        z.promotion_time = self.w[k].start
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > armed_level) if bull else (m.l < armed_level):
                z.trigger_time = m.t
                break

    def consume_break(self, bull: bool, k: int) -> bool:
        # Bull break consumes armed high, bear break consumes armed low.
        if bull:
            if not self.have_h or self.w[k].h <= self.h_price: return False
            if self.regime == 2: self.msses.append(MSS(k, self.h_idx, self.h_price, True))
            self.regime = 1
            promoted = self.promote_aob(self.pend_bull_aob, True, k, self.h_price, self.h_idx); self.pend_bull_aob = -1
            alive = 0 <= self.pend_bull_aifob < len(self.zones) and self.zones[self.pend_bull_aifob].state == 4
            if alive:
                z = self.zones[self.pend_bull_aifob]; z.promotion_from_state = z.state; z.state = z.orig_state = 0; z.eligible = -1; z.eligible_time = None; z.eligible_kind = -1; z.eligible_price = None; z.eligible_swing_price = None; self.set_promoted_ifob_trigger(z, True, k, self.h_price, self.h_idx)
            elif self.last_l >= 0 and not promoted: self.add_ifob(True, k, self.h_idx, self.last_l)
            self.pend_bull_aifob = -1; self.have_h = False; return True
        if not self.have_l or self.w[k].l >= self.l_price: return False
        if self.regime == 1: self.msses.append(MSS(k, self.l_idx, self.l_price, False))
        self.regime = 2
        promoted = self.promote_aob(self.pend_bear_aob, False, k, self.l_price, self.l_idx); self.pend_bear_aob = -1
        alive = 0 <= self.pend_bear_aifob < len(self.zones) and self.zones[self.pend_bear_aifob].state == 4
        if alive:
            z = self.zones[self.pend_bear_aifob]; z.promotion_from_state = z.state; z.state = z.orig_state = 0; z.eligible = -1; z.eligible_time = None; z.eligible_kind = -1; z.eligible_price = None; z.eligible_swing_price = None; self.set_promoted_ifob_trigger(z, False, k, self.l_price, self.l_idx)
        elif self.last_h >= 0 and not promoted: self.add_ifob(False, k, self.l_idx, self.last_h)
        self.pend_bear_aifob = -1; self.have_l = False; return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True; self.h_price = ev.price; self.h_idx = ev.swing
                self.pend_bull_aifob = self.pend_bull_aob = -1
                self.try_bear_aob(preg, armed_l, ev.swing, ev.price, k)
                if self.pend_bear_aifob < 0: self.pend_bear_aifob = self.try_bear_aifob(preg, self.have_l, armed_l, self.last_h, ev.swing, k)
            else:
                self.have_l = True; self.l_price = ev.price; self.l_idx = ev.swing
                self.pend_bear_aifob = self.pend_bear_aob = -1
                self.try_bull_aob(preg, armed_h, ev.swing, ev.price, k)
                if self.pend_bull_aifob < 0: self.pend_bull_aifob = self.try_bull_aifob(preg, self.have_h, armed_h, self.last_l, ev.swing, k)

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        while self.ei < total and self.events[self.ei].confirm == k:
            ev = self.events[self.ei]
            if ev.kind == 0:
                if not consumed_h: self.have_h = True; self.h_price = ev.price; self.h_idx = ev.swing
                self.last_h = ev.swing
                for zidx in self.active[:]:
                    z = self.zones[zidx]
                    if z.bullish and z.state in (0,1,4) and z.eligible < 0 and not z.rejected and k > z.trigger:
                        ok = z.orig_state not in (1,4) or z.zt < ev.price
                        if not ok or (k > 0 and self.w[k-1].l < z.zb): z.rejected = True
                        else: z.eligible = k; z.eligible_kind = 0; z.eligible_time = ev.at; z.eligible_price = self.w[k - 1].l; z.eligible_swing_price = ev.price
            else:
                if not consumed_l: self.have_l = True; self.l_price = ev.price; self.l_idx = ev.swing
                self.last_l = ev.swing
                for zidx in self.active[:]:
                    z = self.zones[zidx]
                    if not z.bullish and z.state in (0,1,4) and z.eligible < 0 and not z.rejected and k > z.trigger:
                        ok = z.orig_state not in (1,4) or z.zb > ev.price
                        if not ok or (k > 0 and self.w[k-1].h > z.zt): z.rejected = True
                        else: z.eligible = k; z.eligible_kind = 1; z.eligible_time = ev.at; z.eligible_price = self.w[k - 1].h; z.eligible_swing_price = ev.price
            self.ei += 1
        for zidx in self.active[:]:
            z = self.zones[zidx]
            if z.rejected or z.state == 3: continue
            if z.eligible >= 0 and k >= z.eligible:
                touch = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
                if touch:
                    z.pre_spent_state = z.state; z.state = 3; z.stop = k; z.impact_time = touch; continue
            if z.state in (0,1,4) and z.eligible >= 0:
                for ev in self.events[before:total]:
                    if ev.confirm == k and ((z.bullish and ev.kind == 1 and ev.price > z.zt) or (not z.bullish and ev.kind == 0 and ev.price < z.zb)):
                        z.state = 2; break
        self.active = [i for i in self.active if not self.zones[i].rejected and self.zones[i].state != 3]

    def process(self, k: int) -> None:
        if k == 0: return
        wh, wl = self.w[k].h, self.w[k].l
        high_first = self.high_first(k); low_first = not high_first
        br_h, br_l = wh > self.w[k-1].h, wl < self.w[k-1].l
        dual = br_h and br_l; n = len(self.events)
        previous_dual = n >= 2 and self.events[-1].kind != self.events[-2].kind and self.events[-1].confirm == self.events[-2].confirm == k-1
        pairs = {(self.events[-1].kind,self.events[-1].swing),(self.events[-2].kind,self.events[-2].swing)} if previous_dual else set()
        before = len(self.events)
        def h_action():
            if self.w[k].h > self.w[self.peak].h: self.peak = k
            if br_h and (not self.events or self.events[-1].kind != 1) and not (previous_dual and not dual and (1,self.trough) in pairs):
                self.add_event(k, 1, self.trough, self.w[self.trough].l); self.peak = k
        def l_action():
            if self.w[k].l < self.w[self.trough].l: self.trough = k
            if br_l and (not self.events or self.events[-1].kind != 0) and not (previous_dual and not dual and (0,self.peak) in pairs):
                self.add_event(k, 0, self.peak, self.w[self.peak].h); self.trough = k
        if high_first: h_action(); l_action()
        else: l_action(); h_action()
        total = len(self.events)
        for ev in self.events[self.ei:total]:
            if ev.confirm != k: break
            if ev.kind == 0: self.last_h = ev.swing
            else: self.last_l = ev.swing
        preg, armed_h, armed_l = self.regime, self.h_idx, self.l_idx
        if high_first:
            c_h = self.consume_break(True,k); self.mid_arm(k,preg,armed_h,armed_l); c_l = self.consume_break(False,k)
        else:
            c_l = self.consume_break(False,k); self.mid_arm(k,preg,armed_h,armed_l); c_h = self.consume_break(True,k)
        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)): self.process(k)


def iso(t: Optional[datetime]) -> str: return "" if t is None else t.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def display_iso(t: Optional[datetime], zone: ZoneInfo) -> str:
    """Human display clock only. Calculation timestamps remain UTC."""
    return "" if t is None else t.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")


def first_swing_confirm(engine: WeeklyOBEngine, start: datetime, end: datetime, kind: int) -> Optional[datetime]:
    """Locked Pine's confirmed-1m resolver for a swing event inside a week."""
    a = max(1, bisect_left(engine.mt, start))
    b = bisect_left(engine.mt, end)
    for i in range(a, b):
        m, p = engine.m[i], engine.m[i - 1]
        if (kind == 0 and m.h > p.h) or (kind == 1 and m.l < p.l):
            return m.t
    return None


def trigger_detail(engine: WeeklyOBEngine, z: Zone) -> Tuple[Optional[datetime], Optional[float]]:
    """Resolve the trigger time and its structural break level (not candle price)."""
    if z.trigger_time is not None or z.trigger_price is not None:
        return z.trigger_time, z.trigger_price
    if not (0 <= z.trigger < len(engine.w)):
        return None, None
    wk = engine.w[z.trigger]
    if z.orig_state in (1, 4):
        # AOB is confirmed by the directional break; AIFOB by the opposite swing.
        kind = (0 if z.bullish else 1) if z.orig_state == 1 else (1 if z.bullish else 0)
        price = next((e.price for e in engine.events if e.confirm == z.trigger and e.kind == kind), None)
        return first_swing_confirm(engine, wk.start, wk.end, kind), price
    # IFOB: the swing is confirmed by a strict break of the immediately prior
    # Weekly opposite extreme. Return that broken level, not the swing price.
    relevant_kind = 0 if z.bullish else 1
    event: Optional[Event] = None
    for e in engine.events:
        if e.kind == relevant_kind and e.confirm <= z.trigger:
            event = e
    if event is None or event.confirm <= 0:
        return None, None
    level = engine.w[event.confirm - 1].h if z.bullish else engine.w[event.confirm - 1].l
    for m in engine.m[wk.first:wk.last]:
        if (m.h > level) if z.bullish else (m.l < level):
            return m.t, level
    return None, level


def minute_at(engine: WeeklyOBEngine, at: Optional[datetime]) -> Optional[Minute]:
    """Return the exact source M1 candle used by a stored timestamp, if present."""
    if at is None:
        return None
    i = bisect_left(engine.mt, at)
    return engine.m[i] if i < len(engine.m) and engine.m[i].t == at else None


def stored_trigger_trace(engine: WeeklyOBEngine, z: Zone) -> Tuple[Optional[Event], Optional[datetime], Optional[Minute]]:
    """Trace the exact stored swing and its first strict M1 crossing.

    This is diagnostic only: it reads the same stored facts used by the
    engine and never changes a zone.  The ledger exposes the result so an
    incorrect trigger can be investigated without drawing every OB.
    """
    if z.trigger_path not in ("direct IFOB armed event", "promoted IFOB armed event"):
        return None, None, None
    kind = 0 if z.bullish else 1
    event = next((e for e in reversed(engine.events)
                  if e.kind == kind and e.swing == z.trigger_swing_week
                  and e.confirm == z.trigger_confirm_week), None)
    if event is None or z.trigger_swing_price is None or not (0 <= z.trigger < len(engine.w)):
        return event, None, None
    wk = engine.w[z.trigger]
    for m in engine.m[wk.first:wk.last]:
        if (m.h > z.trigger_swing_price) if z.bullish else (m.l < z.trigger_swing_price):
            return event, m.t, m
    return event, None, None


def trigger_time(engine: WeeklyOBEngine, z: Zone) -> Optional[datetime]:
    return trigger_detail(engine, z)[0]


def eligibility_detail(engine: WeeklyOBEngine, z: Zone) -> Tuple[Optional[datetime], Optional[float]]:
    if z.eligible_time is not None or z.eligible_price is not None:
        return z.eligible_time, z.eligible_price
    kind = z.eligible_kind if z.eligible_kind in (0, 1) else (0 if z.bullish else 1)
    price = next((e.price for e in engine.events if e.confirm == z.eligible and e.kind == kind), None)
    if z.eligible_time is not None:
        return z.eligible_time, price
    if not (0 <= z.eligible < len(engine.w)):
        return None, None
    wk = engine.w[z.eligible]
    # Locked fallback: BUY needs a high swing; SELL needs a low swing.
    return first_swing_confirm(engine, wk.start, wk.end, kind), price


def trigger_display_detail(engine: WeeklyOBEngine, z: Zone) -> Tuple[Optional[datetime], Optional[float], Optional[float]]:
    """Return trigger time, user-facing swing price, and break level for audit.

    A trigger's time is the M1 confirmation/break event, while the price the
    user wants to record is the stored swing that enabled OB creation.  These
    may differ for a direct IFOB and must not be mixed in one table field.
    """
    when, break_level = trigger_detail(engine, z)
    return when, z.trigger_swing_price if z.trigger_swing_price is not None else break_level, break_level


def eligibility_time(engine: WeeklyOBEngine, z: Zone) -> Optional[datetime]:
    return eligibility_detail(engine, z)[0]


def impact_time(engine: WeeklyOBEngine, z: Zone, eligible_at: Optional[datetime]) -> Optional[datetime]:
    # `finish_events_and_lifecycle()` records the exact M1 touch at the moment
    # the lifecycle changes.  That is the authoritative impact time.  Do not
    # recompute it while writing Pine/CSV: recomputation can start from a
    # derived eligibility time and incorrectly fall through to the next week.
    if z.impact_time is not None:
        return z.impact_time
    if not (0 <= z.stop < len(engine.w)):
        return None
    wk = engine.w[z.stop]
    start = max(wk.start, eligible_at) if eligible_at else wk.start
    return engine.first_touch(start, z.stop, z.bullish, z.zb, z.zt)


def display_bucket_time(at: Optional[datetime], minutes: int) -> Optional[datetime]:
    """Return the opening time of the visual candle containing an M1 event."""
    if at is None:
        return None
    return at.replace(second=0, microsecond=0) - timedelta(minutes=at.minute % minutes)


def scheduled_window_endpoints(engine: WeeklyOBEngine, candle: int) -> tuple[Optional[M1], Optional[M1]]:
    """Raw M1 endpoints from the actual scheduled Weekly interval, for audit.

    They are deliberately separate from the selectable display-source window:
    a comparison can then prove whether an offset helped or harmed one OB.
    """
    wk = engine.w[candle]
    lo = bisect_left(engine.mt, wk.start)
    # Friday close is the final tradable part of the Week. `wk.end` is the
    # following Sunday boundary and can contain next-Week pre-session quotes.
    hi = bisect_left(engine.mt, min(wk.end, wk.start + timedelta(days=5)))
    return (engine.m[lo] if lo < hi else None, engine.m[hi - 1] if lo < hi else None)


def status(z: Zone) -> str:
    if z.rejected:
        return "REJECTED"
    return STATE[z.pre_spent_state if z.state == 3 else z.state]


@dataclass(frozen=True)
class ObservedBoxBody:
    """A display range only; no absent M1 bar is manufactured here."""
    bottom: float
    top: float
    first_bucket: datetime
    first_open_time: datetime
    first_open: float
    first_close: float
    first_selected: float
    first_selected_source: str
    first_minutes: int
    source_window_start: datetime
    source_window_end: datetime
    last_bucket: datetime
    last_close_time: datetime
    last_close: float
    last_minutes: int


def observed_box_body(engine: WeeklyOBEngine, candle: int, minutes_per_bar: int, first_price_source: str = "close", source_offset_minutes: int = 0) -> ObservedBoxBody:
    """Build first/last *observed* N-minute bodies from the source M1 rows.

    This deliberately does not fill a weekend or export gap.  If the first
    available row is 19:08, the 19:00 15-minute bucket opens at that observed
    19:08 price and its count records how many M1 rows were actually present.
    """
    wk = engine.w[candle]
    # The body spans the tradable session: scheduled Sunday start through
    # Friday close. The optional offset is an audit tool for the *start* only;
    # it never pulls the final close from next-Week Sunday pre-session quotes.
    # Event timing and all Weekly structure remain unshifted.
    source_window_start = wk.start + timedelta(minutes=source_offset_minutes)
    source_window_end = min(wk.end, wk.start + timedelta(days=5))
    rows = engine.m[bisect_left(engine.mt, source_window_start):bisect_left(engine.mt, source_window_end)]
    if not rows:
        raise ValueError(f"weekly candle {candle} has no M1 rows")
    seconds = minutes_per_bar * 60
    buckets = {}
    for m in rows:
        bucket = datetime.fromtimestamp((int(m.t.timestamp()) // seconds) * seconds, tz=UTC)
        buckets.setdefault(bucket, []).append(m)
    first_bucket = min(buckets)
    last_bucket = max(buckets)
    first_rows, last_rows = buckets[first_bucket], buckets[last_bucket]
    first_open, first_close, last_close = first_rows[0].o, first_rows[0].c, last_rows[-1].c
    first_selected = first_open if first_price_source == "open" else first_close
    return ObservedBoxBody(
        min(first_selected, last_close), max(first_selected, last_close),
        first_bucket, first_rows[0].t, first_open, first_close, first_selected, first_price_source, len(first_rows), source_window_start, source_window_end,
        last_bucket, last_rows[-1].t, last_close, len(last_rows),
    )


def write_ledger(base: Path, engine: WeeklyOBEngine, box_body_minutes: int, display_zone: ZoneInfo, origin_first_price: str, origin_body_offset_minutes: int) -> None:
    with (base / "weekly_ob_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id","type","side","engine_bottom","engine_top","display_bottom","display_top","origin_window_start_utc","origin_window_end_utc","origin_body_source_offset_minutes","origin_body_source_window_start_utc","origin_body_source_window_end_utc","scheduled_first_m1_time_utc","scheduled_first_m1_open","scheduled_first_m1_close","scheduled_last_m1_time_utc","scheduled_last_m1_close","origin_utc","origin_riyadh","first_h1_bucket_utc","first_h1_open_time_utc","first_h1_open","first_h1_close","origin_first_price_source","origin_first_selected_price","first_h1_minutes","last_h1_bucket_utc","last_h1_close_time_utc","last_h1_close","last_h1_minutes","trigger_fact_source","trigger_path","trigger_swing_week_utc","trigger_swing_week_riyadh","trigger_confirm_week_utc","trigger_confirm_week_riyadh","trigger_swing_confirm_m1_utc","trigger_swing_confirm_m1_riyadh","trigger_first_cross_stored_swing_utc","trigger_first_cross_stored_swing_riyadh","trigger_first_cross_m1_open","trigger_first_cross_m1_high","trigger_first_cross_m1_low","trigger_first_cross_m1_close","trigger_time_utc","trigger_time_riyadh","trigger_price","trigger_price_role","trigger_break_level_price","trigger_break_level_role","trigger_m1_open","trigger_m1_high","trigger_m1_low","trigger_m1_close","eligible_fact_source","eligible_time_utc","eligible_time_riyadh","eligible_price","eligible_swing_price","impact_time_utc","impact_time_riyadh","impact_draw_time_utc","impact_draw_time_riyadh","impact_draw_bucket_minutes","status","created_type","promotion_from_type","promotion_time_utc","promotion_time_riyadh","original_type","rejected"]
        wr = csv.DictWriter(f, fieldnames=fields); wr.writeheader()
        for z in engine.zones:
            body = observed_box_body(engine, z.candle, box_body_minutes, origin_first_price, origin_body_offset_minutes)
            tt, tp, break_level = trigger_display_detail(engine, z)
            trigger_m1 = minute_at(engine, tt)
            et, ep = eligibility_detail(engine, z)
            it = impact_time(engine, z, et)
            origin = engine.w[z.candle].start
            scheduled_first, scheduled_last = scheduled_window_endpoints(engine, z.candle)
            impact_draw = display_bucket_time(it, box_body_minutes)
            break_role = z.trigger_level_role or (("prior-week high break level" if z.bullish else "prior-week low break level") if z.orig_state == 0 else ("swing-low break level" if z.bullish else "swing-high break level"))
            swing_week = engine.w[z.trigger_swing_week].start if 0 <= z.trigger_swing_week < len(engine.w) else None
            confirm_week = engine.w[z.trigger_confirm_week].start if 0 <= z.trigger_confirm_week < len(engine.w) else None
            swing_event, first_cross, first_cross_m1 = stored_trigger_trace(engine, z)
            wr.writerow(dict(id=z.id, type=STATE[z.pre_spent_state if z.state == 3 else z.state], side="BUY" if z.bullish else "SELL", engine_bottom=f"{z.zb:.5f}", engine_top=f"{z.zt:.5f}", display_bottom=f"{body.bottom:.5f}", display_top=f"{body.top:.5f}", origin_window_start_utc=iso(engine.w[z.candle].start), origin_window_end_utc=iso(engine.w[z.candle].end), origin_body_source_offset_minutes=origin_body_offset_minutes, origin_body_source_window_start_utc=iso(body.source_window_start), origin_body_source_window_end_utc=iso(body.source_window_end), scheduled_first_m1_time_utc=iso(scheduled_first.t if scheduled_first else None), scheduled_first_m1_open="" if scheduled_first is None else f"{scheduled_first.o:.5f}", scheduled_first_m1_close="" if scheduled_first is None else f"{scheduled_first.c:.5f}", scheduled_last_m1_time_utc=iso(scheduled_last.t if scheduled_last else None), scheduled_last_m1_close="" if scheduled_last is None else f"{scheduled_last.c:.5f}", origin_utc=iso(origin), origin_riyadh=display_iso(origin, display_zone), first_h1_bucket_utc=iso(body.first_bucket), first_h1_open_time_utc=iso(body.first_open_time), first_h1_open=f"{body.first_open:.5f}", first_h1_close=f"{body.first_close:.5f}", origin_first_price_source=body.first_selected_source, origin_first_selected_price=f"{body.first_selected:.5f}", first_h1_minutes=body.first_minutes, last_h1_bucket_utc=iso(body.last_bucket), last_h1_close_time_utc=iso(body.last_close_time), last_h1_close=f"{body.last_close:.5f}", last_h1_minutes=body.last_minutes, trigger_fact_source="stored" if z.trigger_time is not None or z.trigger_price is not None else "fallback", trigger_path=z.trigger_path, trigger_swing_week_utc=iso(swing_week), trigger_swing_week_riyadh=display_iso(swing_week, display_zone), trigger_confirm_week_utc=iso(confirm_week), trigger_confirm_week_riyadh=display_iso(confirm_week, display_zone), trigger_swing_confirm_m1_utc=iso(swing_event.at if swing_event else None), trigger_swing_confirm_m1_riyadh=display_iso(swing_event.at if swing_event else None, display_zone), trigger_first_cross_stored_swing_utc=iso(first_cross), trigger_first_cross_stored_swing_riyadh=display_iso(first_cross, display_zone), trigger_first_cross_m1_open="" if first_cross_m1 is None else f"{first_cross_m1.o:.5f}", trigger_first_cross_m1_high="" if first_cross_m1 is None else f"{first_cross_m1.h:.5f}", trigger_first_cross_m1_low="" if first_cross_m1 is None else f"{first_cross_m1.l:.5f}", trigger_first_cross_m1_close="" if first_cross_m1 is None else f"{first_cross_m1.c:.5f}", trigger_time_utc=iso(tt), trigger_time_riyadh=display_iso(tt, display_zone), trigger_price="" if tp is None else f"{tp:.5f}", trigger_price_role="stored swing price", trigger_break_level_price="" if break_level is None else f"{break_level:.5f}", trigger_break_level_role=break_role, trigger_m1_open="" if trigger_m1 is None else f"{trigger_m1.o:.5f}", trigger_m1_high="" if trigger_m1 is None else f"{trigger_m1.h:.5f}", trigger_m1_low="" if trigger_m1 is None else f"{trigger_m1.l:.5f}", trigger_m1_close="" if trigger_m1 is None else f"{trigger_m1.c:.5f}", eligible_fact_source="stored" if z.eligible_time is not None or z.eligible_price is not None else "fallback", eligible_time_utc=iso(et), eligible_time_riyadh=display_iso(et, display_zone), eligible_price="" if ep is None else f"{ep:.5f}", eligible_swing_price="" if z.eligible_swing_price is None else f"{z.eligible_swing_price:.5f}", impact_time_utc=iso(it), impact_time_riyadh=display_iso(it, display_zone), impact_draw_time_utc=iso(impact_draw), impact_draw_time_riyadh=display_iso(impact_draw, display_zone), impact_draw_bucket_minutes=box_body_minutes, status=status(z), created_type=STATE[z.created_state], promotion_from_type="" if z.promotion_from_state < 0 else STATE[z.promotion_from_state], promotion_time_utc=iso(z.promotion_time), promotion_time_riyadh=display_iso(z.promotion_time, display_zone), original_type=STATE[z.orig_state], rejected=str(z.rejected).upper()))
    with (base / "weekly_ob_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f); wr.writerow(["record","kind","origin","confirm","price"])
        for e in engine.events: wr.writerow(["SWING","HIGH" if e.kind == 0 else "LOW",iso(engine.w[e.swing].start),iso(engine.w[e.confirm].start),f"{e.price:.5f}"])
        for x in engine.msses: wr.writerow(["MSS_UP" if x.up else "MSS_DOWN","",iso(engine.w[x.broken].start),iso(engine.w[x.at].start),f"{x.price:.5f}"])


def pine_time(t: datetime) -> str:
    u = t.astimezone(UTC); return f"timestamp(\"GMT+0\", {u.year}, {u.month}, {u.day}, {u.hour}, {u.minute})"


def pine_colour(z: Zone) -> str:
    display_state = z.pre_spent_state if z.state == 3 else z.state
    if display_state == 0:
        return "color.blue" if z.bullish else "color.black"
    if display_state == 1:
        return "color.green"
    if display_state == 2:
        return "color.red"
    if display_state == 4:
        return "color.orange"
    return "color.blue" if z.bullish else "color.black"


def pine_text(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def write_ob_pine(base: Path, engine: WeeklyOBEngine, label_cap: int, ob_cap: int, table_cap: int, box_body_minutes: int, display_zone: ZoneInfo, origin_first_price: str, origin_body_offset_minutes: int) -> None:
    """Static, low-memory rendering of the locked Weekly structure and OB lifecycle."""
    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    shown = engine.zones[-ob_cap:]
    table_zones = engine.zones[-table_cap:][::-1]
    max_ob_offset = max(1, len(engine.zones))
    lines = [
        "//@version=6",
        "indicator(\"FXCM Weekly OB - Python Reference\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        f"// GENERATED FROM 1-MINUTE FXCM BID DATA. OB decisions use locked Weekly swing/MSS; displayed body uses observed first/last {box_body_minutes}m candles; first source is {origin_first_price}; body source offset is {origin_body_offset_minutes}m.",
        "// Attach to EURUSD, FXCM. Weekly chart: swings/MSS/OB boxes/table. 4H chart:",
        "// only the Weekly OB boxes + impact lines are carried over (no table, no",
        "// swing/MSS labels). Every other timeframe draws nothing -- a plain chart.",
        "float lowGap = ta.atr(14) * 0.08",
        "bool showOriginAudit = input.bool(true, \"Show OB origin-candle audit labels\")",
        "bool inspectOneOB = input.bool(false, \"Inspect one OB only\", group=\"OB inspection\")",
        f"int obFromLast = input.int(1, \"OB from last\", minval=1, maxval={max_ob_offset}, group=\"OB inspection\", tooltip=\"1 = latest OB, 2 = the OB before it, and so on.\")",
        "var table ledger = table.new(position.top_right, 10, 21, border_width=1)",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
    ]
    # Resolve each static M1 impact into the opening time of whichever chart
    # candle contains it. This is deliberately evaluated on every chart bar,
    # so 5m, 15m, H1, Daily and Weekly all anchor to their own containing bar.
    impact_vars: dict[int, str] = {}
    for z in shown:
        if z.rejected:
            continue
        it = impact_time(engine, z, eligibility_time(engine, z))
        if it is not None:
            name = f"impact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = pine_time(it)
            lines += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]
    lines.append("if barstate.islast")
    # Weekly-only: swings, MSS, table. Weekly+H4: OB boxes and impact lines
    # only (SPEC.md SS17: "Display Weekly POIs on Weekly and 4H charts").
    # Every other timeframe draws nothing here -- a plain, error-free chart.
    lines.append("    if onWeekly")
    # Exact locked visual convention: blue ▲ high, black ▼ low, and ✕ MSS.
    for e in sh:
        lines.append(f"        label.new({pine_time(engine.w[e.swing].start)}, {e.price:.5f}, \"▲\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=color.blue, size=size.small)")
    for e in sl:
        lines.append(f"        label.new({pine_time(engine.w[e.swing].start)}, {e.price:.5f} - lowGap, \"▼\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=color.black, size=size.small)")
    for m in ms:
        y = f"{m.price:.5f}" if m.up else f"{m.price:.5f} - lowGap"
        colour = "color.blue" if m.up else "color.black"
        lines.append(f"        label.new({pine_time(engine.w[m.broken].start)}, {y}, \"✕\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor={colour}, size=size.small)")
    # Match the locked visual convention: hollow color box, red vertical impact line,
    # rejected zones not drawn, and SPENT shown in its pre-spent colour.
    right_edge = engine.m[-1].t + timedelta(days=365)
    lines.append("    if onWeekly or onH4")
    for z in shown:
        if z.rejected:
            continue
        rank_from_last = len(engine.zones) - z.id + 1
        # The engine remains locked to the Weekly origin body.  The requested
        # visual body comes only from observed M1 data grouped into N-minute bars.
        origin = engine.w[z.candle]
        left = origin.start
        body = observed_box_body(engine, z.candle, box_body_minutes, origin_first_price, origin_body_offset_minutes)
        body_bottom, body_top = body.bottom, body.top
        et = eligibility_time(engine, z)
        it = impact_time(engine, z, et)
        fallback_right = it or (engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else right_edge)
        right = f"(na({impact_vars[z.id]}) ? {pine_time(fallback_right)} : {impact_vars[z.id]})" if it is not None else pine_time(fallback_right)
        col = pine_colour(z)
        lines.append(f"        if not inspectOneOB or obFromLast == {rank_from_last}")
        lines.append(f"            box.new({pine_time(left)}, {body_top:.5f}, {right}, {body_bottom:.5f}, border_color={col}, border_width=1, bgcolor=na, xloc=xloc.bar_time)")
        audit_text = f"#{z.id} {STATE[z.pre_spent_state if z.state == 3 else z.state]} {'BUY' if z.bullish else 'SELL'}"
        lines.append(f"            if showOriginAudit\n                label.new({pine_time(left)}, {origin.h:.5f}, \"{audit_text}\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new({col}, 85), textcolor={col}, size=size.tiny)")
        if it is not None:
            lines.append(f"            line.new({right}, {body_bottom:.5f}, {right}, {body_top:.5f}, xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)")
    lines.append("    if onWeekly")
    lines += [
        "        table.clear(ledger, 0, 0, 9, 20)",
        "        table.cell(ledger, 0, 0, \"W OB\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 1, 0, \"Type\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 5, 0, \"Origin (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 6, 0, \"Trigger (RYD / swing)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 7, 0, \"Eligible (RYD / px)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 8, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 9, 0, \"Status\", text_color=color.white, bgcolor=color.new(color.green, 15))",
    ]
    for row, z in enumerate(table_zones, 1):
        origin = engine.w[z.candle]
        body = observed_box_body(engine, z.candle, box_body_minutes, origin_first_price, origin_body_offset_minutes)
        body_bottom, body_top = body.bottom, body.top
        tt, tp, _ = trigger_display_detail(engine, z)
        et, ep = eligibility_detail(engine, z)
        it = impact_time(engine, z, et)
        trigger_text = display_iso(tt, display_zone) + (" @ " + f"{tp:.5f}" if tp is not None else "")
        eligible_text = display_iso(et, display_zone) + (" @ " + f"{ep:.5f}" if ep is not None else "")
        values = [f"#{z.id}", STATE[z.pre_spent_state if z.state == 3 else z.state], "BUY" if z.bullish else "SELL", f"{body_bottom:.5f}", f"{body_top:.5f}", display_iso(engine.w[z.candle].start, display_zone), trigger_text, eligible_text, display_iso(it, display_zone), status(z)]
        lines.append("        if not inspectOneOB")
        for col, value in enumerate(values):
            bg = f"color.new({pine_colour(z)}, 80)" if col == 9 else "na"
            lines.append(f"            table.cell(ledger, {col}, {row}, \"{pine_text(value)}\", text_color=color.black, bgcolor={bg})")
    # Inspection mode always uses row 1 so the selected record is easy to read.
    for z in engine.zones[::-1]:
        rank_from_last = len(engine.zones) - z.id + 1
        origin = engine.w[z.candle]
        body = observed_box_body(engine, z.candle, box_body_minutes, origin_first_price, origin_body_offset_minutes)
        tt, tp, _ = trigger_display_detail(engine, z)
        et, ep = eligibility_detail(engine, z)
        it = impact_time(engine, z, et)
        trigger_text = display_iso(tt, display_zone) + (" @ " + f"{tp:.5f}" if tp is not None else "")
        eligible_text = display_iso(et, display_zone) + (" @ " + f"{ep:.5f}" if ep is not None else "")
        values = [f"#{z.id}", STATE[z.pre_spent_state if z.state == 3 else z.state], "BUY" if z.bullish else "SELL", f"{body.bottom:.5f}", f"{body.top:.5f}", display_iso(origin.start, display_zone), trigger_text, eligible_text, display_iso(it, display_zone), status(z)]
        lines.append(f"        if inspectOneOB and obFromLast == {rank_from_last}")
        for col, value in enumerate(values):
            bg = f"color.new({pine_colour(z)}, 80)" if col == 9 else "na"
            lines.append(f"            table.cell(ledger, {col}, 1, \"{pine_text(value)}\", text_color=color.black, bgcolor={bg})")
    lines.append("")
    (base / "weekly_ob_viewer.pine").write_text("\n".join(lines), encoding="utf-8")


def write_report(base: Path, minutes: List[Minute], weeks: List[Week], warnings: List[str], e: WeeklyOBEngine, args: argparse.Namespace) -> None:
    gaps = sum(1 for a,b in zip(minutes,minutes[1:]) if b.t-a.t > timedelta(minutes=1) and a.t.weekday() < 5)
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)
    counts = {name: 0 for name in ("IFOB", "AOB", "AIFOB", "OOB", "SPENT", "REJECTED")}
    for z in e.zones:
        counts[status(z)] += 1
    rows = ["WEEKLY OB REFERENCE RUN", f"input={args.csv_file}", f"price_side={args.price_side}", f"input_timezone={args.input_tz}", f"display_timezone={args.display_tz} (display only; internal calculation remains UTC)", f"weekly_aggregation=Sunday {args.week_close_hour:02d}:00 {args.week_close_zone}", f"display_body=first/last observed {args.box_body_minutes}-minute candle bodies assembled from the explicit source window offset {args.origin_body_offset_minutes}m; first origin price={args.origin_first_price}; missing minutes are neither filled nor used as a blocker", "event_facts=trigger and eligibility facts are captured at their lifecycle transition; ledger reports stored or fallback provenance", f"minute_coverage={iso(minutes[0].t)} to {iso(minutes[-1].t)}", f"minutes={len(minutes):,}; weeks={len(weeks):,}; swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}; gaps_outside_weekend={gaps}", "", "OB LIFECYCLE COUNTS", *[f"{name}={counts[name]}" for name in counts], "", "Colors: IFOB BUY=blue; IFOB SELL=black; AOB=green; AIFOB=orange; OOB=red; SPENT keeps its preceding color; REJECTED is ledger-only."]
    if warnings: rows += ["", "WARNINGS"] + warnings[:50]
    (base / "weekly_ob_report.txt").write_text("\n".join(rows)+"\n", encoding="utf-8")


def main() -> int:
    args = parse_args(); path = Path(args.csv_file).expanduser().resolve(); base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr); return 2
    try:
        input_tz = ZoneInfo(args.input_tz); close_tz = ZoneInfo(args.week_close_zone); display_tz = ZoneInfo(args.display_tz)
        minutes, warnings = load_minutes(path, input_tz, args.price_side)
        weeks = aggregate_weeks(minutes, close_tz, args.week_close_hour)
        engine = WeeklyOBEngine(minutes, weeks); engine.run()
        write_ledger(base, engine, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes); write_ob_pine(base, engine, args.pine_labels, args.pine_obs, args.pine_table, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes); write_report(base, minutes, weeks, warnings, engine, args)
        print("Created:"); print("  weekly_ob_ledger.csv"); print("  weekly_ob_swings.csv"); print("  weekly_ob_viewer.pine"); print("  weekly_ob_report.txt")
        print(f"Processed {len(minutes):,} minutes and {len(weeks)} weeks. The Pine viewer contains Weekly structure and the OB lifecycle.")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
