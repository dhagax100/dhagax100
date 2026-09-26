#!/usr/bin/env python3
"""Weekly FXCM EURUSD VI (Volume Imbalance) reference generator.

VI counterpart of weekly_ob_generator.py / weekly_rb_generator.py /
weekly_fvg_generator.py. Same EURUSD 1-minute Bid/Ask CSV, same Weekly
aggregation, and the swing/MSS detection below is copied VERBATIM from
weekly_ob_generator.py's WeeklyOBEngine. Only the POI-construction logic
differs, per the VI spec confirmed against VI_Indicator_v1.txt (the
standalone Pine diagnostic the user supplied):

  - A VI zone is a 2-candle gap: between candle1's CLOSE and candle2's
    OPEN -- NOT wicks, unlike FVG's 3-candle wick-to-wick gap. If candle2
    opens away from where candle1 closed, that gap never traded during
    the session transition -- that's the "volume imbalance." Bullish VI:
    open[2] above close[1]. Bearish VI: open[2] below close[1].
  - Two built-in guards, both already implied by translating the pine's
    own boolean condition literally (no separate check needed):
      - SAME-CANDLE FILL GUARD: candle2's own close must not round-trip
        back through candle1's close (cl2 > cl1 for bullish, cl2 < cl1
        for bearish) -- otherwise the gap got filled within the same
        candle that created it, disqualified from ever being marked.
      - CANDLE1-DIRECTION GUARD: the gap must continue candle1's own
        momentum (bullish candle1 for a rising gap, bearish candle1 for
        a falling gap) -- a candle contradicting its own gap shape is
        not a VI at all.
  - IVI (continuation-only, mirrors IFVG/IFOB): delayed eligibility,
    armed on the NEXT same-direction swing. Created (a) at the same
    break-confirmation range IFVG/IRB use, and (b) continuously, one more
    week at a time, for as long as the current regime persists.
  - AVI (Anticipatory, mirrors AFVG/AOB): created at MID-ARM, immediate
    eligibility, gated by a per-gap near-side straddle guard -- checks
    WICKS of both candles against the armed swing's price (confirmed with
    the user: keep wicks, not close/open).
  - **Stranding: ONE UNIVERSAL CONDITION for every zone type (IVI and AVI
    alike)** -- `(bullish and a swing LOW confirms above zt) or (bearish
    and a swing HIGH confirms below zb)`. The supplied VI_Indicator_v1.txt
    DOES branch by origin and claims its AVI branch "safely mirrors
    AFVG's formula" -- true, but AFVG's own formula was itself the exact
    same invented, swapped bug already found and fixed in RB and FVG. This
    is the THIRD time this identical mistake has appeared in a supplied
    pine source. Not ported; the single unified condition is used for
    both IVI and AVI from the start.
  - **Close-through invalidation, IVI only** (origin 0, still state 0,
    far edge): matches FVG's own corrected form exactly -- the supplied
    pine source already has this right (built in from day one, per its
    own header, learning from FVG's own mid-build correction).
  - **STRUCTURAL_BREACH, added per the same standing rule used for FVG**
    (not in the supplied pine source at all, which predates this rule): a
    POI stops being used the instant its supporting swing point is
    exceeded, in real time, full stop. Same `protect_level` mechanism as
    FVG.
  - Same-week ordering when impact, stranding, close-through and
    structural-breach could all apply: resolved by exact M1/event
    timestamp, earliest wins -- same four-candidate discipline as FVG.
  - No promotion machinery, same as FVG (no AIFOB/AIRB-style pending
    object).
  - A `claimed()` dedupe guard (same purpose as RB/FVG's own) prevents the
    same physical (leftIdx, bullish) gap from being stamped twice.

The program writes, next to its own file:
  weekly_vi_ledger.csv       all Weekly VI records and lifecycle timestamps
  weekly_vi_swings.csv       Weekly swings and MSS records (identical facts
                              to weekly_ob_swings.csv/weekly_rb_swings.csv/
                              weekly_fvg_swings.csv -- same engine)
  weekly_vi_viewer.pine      static TradingView viewer for Weekly structure and VIs
  weekly_vi_report.txt       coverage, gaps and lifecycle counts

No third-party Python packages are required. Python 3.9+ is sufficient.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))
import weekly_ob_generator as wob  # noqa: E402 -- reused for Minute/Week/Event/MSS,
                                    # load_minutes, aggregate_weeks, iso helpers, pine helpers

UTC = timezone.utc
STATE = {0: "IVI", 1: "AVI", 2: "OVI", 3: "SPENT"}


@dataclass
class VIZone:
    id: int
    left: int             # leftIdx: candle1 of the 2-candle gap (week index)
    zb: float
    zt: float
    bullish: bool
    trigger: int           # the hunt's firing week index (break moment for IVI, mid-arm for AVI)
    eligible: int           # -1 = not yet eligible (IVI only, until its arming swing confirms)
    stop: int               # -1 = extending
    state: int              # 0=IVI, 1=AVI, 2=OVI, 3=SPENT
    origin: int              # 0=IVI-style, 1=AVI-style -- IMMUTABLE, decides close-through eligibility
    pre_spent_state: int
    eligible_time: Optional[datetime] = None
    impact_time: Optional[datetime] = None
    trigger_time: Optional[datetime] = None
    protect_level: Optional[float] = None  # supporting swing's own price, see STRUCTURAL_BREACH
    stop_reason: str = ""    # "IMPACT" | "CLOSE_THROUGH" | "STRAND" | "STRUCTURAL_BREACH" | ""


class WeeklyVIEngine:
    """VI counterpart of WeeklyOBEngine/WeeklyRBEngine/WeeklyFVGEngine.
    Swing/MSS block is a verbatim copy; everything below that is
    VI-specific POI construction/lifecycle."""

    def __init__(self, minutes: List["wob.Minute"], weeks: List["wob.Week"]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]
        self.events: List["wob.Event"] = []
        self.msses: List["wob.MSS"] = []
        self.zones: List[VIZone] = []
        self.active: List[int] = []
        self._claimed_pairs: set = set()
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0
        self.ei = 0
        self.last_h = self.last_l = -1
        self.vi_bull_scan_upto = -1
        self.vi_bear_scan_upto = -1

    # ===================================================================
    # SWING/MSS DETECTION -- COPIED VERBATIM FROM weekly_ob_generator.py's
    # WeeklyOBEngine. DO NOT DIVERGE from that file's version.
    # ===================================================================

    def event_time(self, kind: int, k: int) -> Optional[datetime]:
        if k <= 0:
            return None
        wk = self.w[k]
        threshold = self.w[k - 1].l if kind == 0 else self.w[k - 1].h
        for m in self.m[wk.first:wk.last]:
            if (m.l < threshold) if kind == 0 else (m.h > threshold):
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
        self.events.append(wob.Event(confirm, kind, swing, price, self.event_time(kind, confirm)))
        dest = self.sw_highs if kind == 0 else self.sw_lows
        if not dest or dest[-1] != swing:
            dest.append(swing)

    def first_touch(self, start: datetime, k: int, bull: bool, zb: float, zt: float) -> Optional[datetime]:
        wk = self.w[k]
        a = max(wk.first, bisect_left(self.mt, start))
        for m in self.m[a:wk.last]:
            if (m.l < zt) if bull else (m.h > zb):
                return m.t
        return None

    def break_time(self, k: int, bull: bool, level: float) -> Optional[datetime]:
        """Exact M1 minute price first breaks the given armed level within week k."""
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > level) if bull else (m.l < level):
                return m.t
        return None

    def week_open_time(self, k: int) -> datetime:
        """Exact M1 minute week k's own OPEN actually printed -- the first
        observed row in that week, not the scheduled boundary (which can
        differ if the export has a small gap right at the open). This is
        the real trigger moment for a continuous-scan IVI: the gap becomes
        real the instant week k's own open prints on the tape."""
        wk = self.w[k]
        return self.m[wk.first].t

    # ===================================================================
    # VI-SPECIFIC: zone construction (2-candle close/open gap, per the
    # confirmed pine spec).
    # ===================================================================

    def claimed(self, left: int, bull: bool) -> bool:
        return (left, bull) in self._claimed_pairs

    def add_vi(self, left: int, zb: float, zt: float, bull: bool, trigger_k: int,
               origin: int, trigger_time: Optional[datetime], protect_idx: int = -1) -> int:
        if self.claimed(left, bull):
            return -1
        eligible = trigger_k if origin == 1 else -1
        eligible_time = trigger_time if origin == 1 else None
        protect_level = None
        if 0 <= protect_idx < len(self.w):
            protect_level = self.w[protect_idx].l if bull else self.w[protect_idx].h
        z = VIZone(len(self.zones) + 1, left, zb, zt, bull, trigger_k, eligible, -1,
                   origin, origin, origin, trigger_time=trigger_time, eligible_time=eligible_time,
                   protect_level=protect_level)
        self.zones.append(z)
        self.active.append(len(self.zones) - 1)
        self._claimed_pairs.add((left, bull))
        return len(self.zones) - 1

    def try_create_ivis(self, lo: int, hi: int, bullish: bool, trigger_k: int,
                        trigger_time: Optional[datetime], protect_idx: int) -> None:
        if hi < lo + 1:
            return
        for c2 in range(lo + 1, hi + 1):
            c1 = c2 - 1
            op1, cl1 = self.w[c1].o, self.w[c1].c
            op2, cl2 = self.w[c2].o, self.w[c2].c
            is_bull1 = cl1 >= op1
            if bullish:
                if cl1 < op2 and cl2 > cl1 and is_bull1:
                    self.add_vi(c1, cl1, op2, True, trigger_k, 0, trigger_time, protect_idx)
            else:
                if cl1 > op2 and cl2 < cl1 and not is_bull1:
                    self.add_vi(c1, op2, cl1, False, trigger_k, 0, trigger_time, protect_idx)

    def try_create_avis(self, lo: int, hi: int, bullish: bool, trigger_k: int,
                        guard_price: float, trigger_time: Optional[datetime], protect_idx: int) -> None:
        if hi < lo + 1:
            return
        for c2 in range(lo + 1, hi + 1):
            c1 = c2 - 1
            op1, cl1 = self.w[c1].o, self.w[c1].c
            op2, cl2 = self.w[c2].o, self.w[c2].c
            is_bull1 = cl1 >= op1
            if bullish:
                if cl1 > op2 and cl2 < cl1 and not is_bull1:
                    l1, l2 = self.w[c1].l, self.w[c2].l
                    if l1 > guard_price and l2 > guard_price:
                        self.add_vi(c1, op2, cl1, True, trigger_k, 1, trigger_time, protect_idx)
            else:
                if cl1 < op2 and cl2 > cl1 and is_bull1:
                    h1, h2 = self.w[c1].h, self.w[c2].h
                    if h1 < guard_price and h2 < guard_price:
                        self.add_vi(c1, cl1, op2, False, trigger_k, 1, trigger_time, protect_idx)

    def try_bull_avi(self, preg: int, armed_swh: int, new_swl_i: int, new_swl_p: float, k: int, at: Optional[datetime]) -> None:
        if preg != 1 or armed_swh < 0:
            return
        if any(self.w[v].h >= self.w[armed_swh].h for v in range(armed_swh + 1, new_swl_i + 1)):
            return
        swl_ext = new_swl_i + 1 if new_swl_i + 1 <= k - 1 else new_swl_i
        lo = max(0, min(armed_swh - 1, swl_ext))
        hi = max(armed_swh - 1, swl_ext)
        self.try_create_avis(lo, hi, True, k, new_swl_p, at, self.last_l)

    def try_bear_avi(self, preg: int, armed_swl: int, new_swh_i: int, new_swh_p: float, k: int, at: Optional[datetime]) -> None:
        if preg != 2 or armed_swl < 0:
            return
        if any(self.w[v].l <= self.w[armed_swl].l for v in range(armed_swl + 1, new_swh_i + 1)):
            return
        swh_ext = new_swh_i + 1 if new_swh_i + 1 <= k - 1 else new_swh_i
        lo = max(0, min(armed_swl - 1, swh_ext))
        hi = max(armed_swl - 1, swh_ext)
        self.try_create_avis(lo, hi, False, k, new_swh_p, at, self.last_h)

    def consume_break(self, bull: bool, k: int) -> bool:
        if bull:
            if not self.have_h or self.w[k].h <= self.h_price:
                return False
            if self.regime == 2:
                self.msses.append(wob.MSS(k, self.h_idx, self.h_price, True))
            self.regime = 1
            if self.last_l >= 0:
                lo, hi = min(self.last_l, k, self.h_idx), max(self.last_l, k, self.h_idx)
                bt = self.break_time(k, True, self.h_price)
                self.try_create_ivis(lo, hi, True, k, bt, self.last_l)
                self.vi_bull_scan_upto = hi
            self.have_h = False
            return True
        if not self.have_l or self.w[k].l >= self.l_price:
            return False
        if self.regime == 1:
            self.msses.append(wob.MSS(k, self.l_idx, self.l_price, False))
        self.regime = 2
        if self.last_h >= 0:
            lo, hi = min(self.last_h, k, self.l_idx), max(self.last_h, k, self.l_idx)
            bt = self.break_time(k, False, self.l_price)
            self.try_create_ivis(lo, hi, False, k, bt, self.last_h)
            self.vi_bear_scan_upto = hi
        self.have_l = False
        return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True
                self.h_price = ev.price
                self.h_idx = ev.swing
                self.try_bear_avi(preg, armed_l, ev.swing, ev.price, k, ev.at)
            else:
                self.have_l = True
                self.l_price = ev.price
                self.l_idx = ev.swing
                self.try_bull_avi(preg, armed_h, ev.swing, ev.price, k, ev.at)

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        while self.ei < total and self.events[self.ei].confirm == k:
            ev = self.events[self.ei]
            if ev.kind == 0:
                if not consumed_h:
                    self.have_h = True
                    self.h_price = ev.price
                    self.h_idx = ev.swing
                self.last_h = ev.swing
                for zidx in self.active:
                    z = self.zones[zidx]
                    if z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            else:
                if not consumed_l:
                    self.have_l = True
                    self.l_price = ev.price
                    self.l_idx = ev.swing
                self.last_l = ev.swing
                for zidx in self.active:
                    z = self.zones[zidx]
                    if not z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            self.ei += 1

        for zidx in self.active:
            z = self.zones[zidx]
            if z.state == 3:
                continue
            touch = None
            if z.eligible >= 0 and k >= z.eligible:
                touch = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
            strand_ev = None
            if z.state in (0, 1) and z.eligible != -1:
                for ev in self.events[before:total]:
                    if ev.confirm != k:
                        continue
                    stranded = (z.bullish and ev.kind == 1 and ev.price > z.zt) or \
                               (not z.bullish and ev.kind == 0 and ev.price < z.zb)
                    if stranded:
                        strand_ev = ev
                        break
            close_through_at = None
            if z.origin == 0 and z.state == 0 and z.eligible != -1 and k >= z.eligible:
                c = self.w[k].c
                closed_through = (c < z.zb) if z.bullish else (c > z.zt)
                if closed_through:
                    close_through_at = self.w[k].end
            breach_at = None
            if z.state in (0, 1) and z.protect_level is not None:
                breach_at = self.break_time(k, not z.bullish, z.protect_level)
            candidates = []
            if touch is not None:
                candidates.append(("IMPACT", touch))
            if strand_ev is not None and strand_ev.at is not None:
                candidates.append(("STRAND", strand_ev.at))
            if close_through_at is not None:
                candidates.append(("CLOSE_THROUGH", close_through_at))
            if breach_at is not None:
                candidates.append(("STRUCTURAL_BREACH", breach_at))
            if candidates:
                candidates.sort(key=lambda pair: pair[1])
                reason, at = candidates[0]
                if reason in ("STRAND", "STRUCTURAL_BREACH"):
                    z.state = 2
                    z.stop_reason = reason
                else:
                    z.pre_spent_state = z.state
                    z.state = 3
                    z.stop = k
                    z.impact_time = at
                    z.stop_reason = reason
            elif touch is None and strand_ev is not None:
                z.state = 2
                z.stop_reason = "STRAND"

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
            c_h = self.consume_break(True, k); self.mid_arm(k, preg, armed_h, armed_l); c_l = self.consume_break(False, k)
        else:
            c_l = self.consume_break(False, k); self.mid_arm(k, preg, armed_h, armed_l); c_h = self.consume_break(True, k)

        # STEP 1b: continuous IVI scan -- 2-candle version of FVG's own
        # STEP 1b (close[k-1] vs open[k], not high[k-2] vs low[k]).
        if self.regime == 1 and k >= 1 and k > self.vi_bull_scan_upto:
            op1, cl1 = self.w[k - 1].o, self.w[k - 1].c
            op2, cl2 = self.w[k].o, self.w[k].c
            is_bull1 = cl1 >= op1
            if cl1 < op2 and cl2 > cl1 and is_bull1:
                self.add_vi(k - 1, cl1, op2, True, k, 0, self.week_open_time(k), self.last_l)
            self.vi_bull_scan_upto = k
        if self.regime == 2 and k >= 1 and k > self.vi_bear_scan_upto:
            op1, cl1 = self.w[k - 1].o, self.w[k - 1].c
            op2, cl2 = self.w[k].o, self.w[k].c
            is_bull1 = cl1 >= op1
            if cl1 > op2 and cl2 < cl1 and not is_bull1:
                self.add_vi(k - 1, op2, cl1, False, k, 0, self.week_open_time(k), self.last_h)
            self.vi_bear_scan_upto = k

        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)):
            self.process(k)


def status(z: VIZone) -> str:
    return STATE[z.pre_spent_state if z.state == 3 else z.state]


def write_ledger(base: Path, engine: WeeklyVIEngine, display_zone: ZoneInfo) -> None:
    with (base / "weekly_vi_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "type", "side", "zb", "zt", "origin_type",
                   "left_week_utc", "left_week_riyadh",
                   "trigger_time_utc", "trigger_time_riyadh",
                   "eligible_time_utc", "eligible_time_riyadh",
                   "impact_time_utc", "impact_time_riyadh", "stop_reason", "status"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for z in engine.zones:
            wk = engine.w[z.left]
            wr.writerow(dict(
                id=z.id, type=status(z), side="BUY" if z.bullish else "SELL",
                zb=f"{z.zb:.5f}", zt=f"{z.zt:.5f}",
                origin_type="IVI-style (close-through eligible)" if z.origin == 0 else "AVI-style",
                left_week_utc=wob.iso(wk.start), left_week_riyadh=wob.display_iso(wk.start, display_zone),
                trigger_time_utc=wob.iso(z.trigger_time), trigger_time_riyadh=wob.display_iso(z.trigger_time, display_zone),
                eligible_time_utc=wob.iso(z.eligible_time), eligible_time_riyadh=wob.display_iso(z.eligible_time, display_zone),
                impact_time_utc=wob.iso(z.impact_time), impact_time_riyadh=wob.display_iso(z.impact_time, display_zone),
                stop_reason=z.stop_reason,
                status=status(z),
            ))
    with (base / "weekly_vi_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["record", "kind", "origin_utc", "origin_riyadh", "confirm_utc", "confirm_riyadh", "price"])
        for e in engine.events:
            confirm_at = e.at if e.at is not None else engine.w[e.confirm].start
            wr.writerow(["SWING", "HIGH" if e.kind == 0 else "LOW",
                         wob.iso(engine.w[e.swing].start), wob.display_iso(engine.w[e.swing].start, display_zone),
                         wob.iso(confirm_at), wob.display_iso(confirm_at, display_zone),
                         f"{e.price:.5f}"])
        for x in engine.msses:
            confirm_at = engine.break_time(x.at, x.up, x.price) or engine.w[x.at].start
            wr.writerow(["MSS_UP" if x.up else "MSS_DOWN", "",
                         wob.iso(engine.w[x.broken].start), wob.display_iso(engine.w[x.broken].start, display_zone),
                         wob.iso(confirm_at), wob.display_iso(confirm_at, display_zone),
                         f"{x.price:.5f}"])


def vi_colour(z: VIZone) -> str:
    d = z.pre_spent_state if z.state == 3 else z.state
    if d == 2:
        return "color.red"
    if d == 1:
        return "color.green"
    return "color.blue" if z.bullish else "color.black"


def pine_epoch(t: datetime) -> str:
    return str(int(t.astimezone(timezone.utc).timestamp() * 1000))


_PACK_NA = "§NA§"
_PACK_SEP = "|"


def pack_array(var_name: str, kind: str, values: list) -> List[str]:
    if not values:
        return [f"var array<{kind}> {var_name} = array.new<{kind}>()"]

    def fmt(v):
        if v is None:
            return _PACK_NA
        if kind == "bool":
            return "true" if v else "false"
        return str(v)

    packed = _PACK_SEP.join(fmt(v) for v in values)
    esc = packed.replace("\\", "\\\\").replace('"', '\\"')
    conv = {
        "string": "p",
        "int": "int(str.tonumber(p))",
        "float": "str.tonumber(p)",
        "bool": 'p == "true"',
    }[kind]
    return [
        f"var array<{kind}> {var_name} = array.new<{kind}>()",
        "if barstate.isfirst",
        f"    for p in str.split(\"{esc}\", \"{_PACK_SEP}\")",
        f"        array.push({var_name}, p == \"{_PACK_NA}\" ? {kind}(na) : {conv})",
    ]


_COLOUR_CODE = {"color.red": "R", "color.green": "G", "color.blue": "B", "color.black": "K"}


def colour_ternary(get_expr: str) -> str:
    return (f'{get_expr} == "R" ? color.red : {get_expr} == "G" ? color.green : '
            f'{get_expr} == "B" ? color.blue : color.black')


def write_vi_pine(base: Path, engine: WeeklyVIEngine, label_cap: int, vi_cap: int, table_cap: int,
                   display_zone: ZoneInfo, extra_lines: Optional[List[str]] = None, out_name: str = "weekly_vi_viewer.pine") -> None:
    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    shown = engine.zones[-vi_cap:]
    table_zones = engine.zones[-table_cap:][::-1]
    max_vi_offset = max(1, len(engine.zones))

    lines = [
        "//@version=6",
        "indicator(\"FXCM Weekly VI - Python Reference\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. Swing/MSS detection is identical to the OB/RB/FVG reference engines.",
        "// VI zone = a 2-candle close/open gap (IVI/AVI per the confirmed spec).",
        "float lowGap = ta.atr(14) * 0.08",
        "bool inspectOneVI = input.bool(false, \"Inspect one VI only\", group=\"VI inspection\")",
        f"int viFromLast = input.int(1, \"VI from last\", minval=1, maxval={max_vi_offset}, group=\"VI inspection\", tooltip=\"1 = latest VI, 2 = the VI before it, and so on.\")",
        "var table ledger = table.new(position.top_right, 10, 21, border_width=1)",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
        "bool on1m = timeframe.period == \"1\"",
        "bool onFive = timeframe.period == \"5\"",
    ]

    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(pine_epoch(engine.w[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▲"); struct_col.append("B"); struct_low.append(False)
    for e in sl:
        struct_x.append(pine_epoch(engine.w[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▼"); struct_col.append("K"); struct_low.append(True)
    for m in ms:
        struct_x.append(pine_epoch(engine.w[m.broken].start))
        struct_y.append(m.price)
        struct_txt.append("✕"); struct_col.append("B" if m.up else "K")
        struct_low.append(not m.up)

    right_edge = engine.m[-1].t + timedelta(days=365)
    vi_left, vi_top, vi_bottom, vi_fallback_right, vi_impact_stamp, vi_has_impact, vi_col, vi_rank, vi_audit, vi_has_line = ([] for _ in range(10))
    for z in shown:
        wk = engine.w[z.left]
        fallback_right = z.impact_time or (engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else right_edge)
        rank_from_last = len(engine.zones) - z.id + 1
        vi_left.append(pine_epoch(wk.start)); vi_top.append(z.zt); vi_bottom.append(z.zb)
        vi_fallback_right.append(pine_epoch(fallback_right))
        vi_impact_stamp.append(pine_epoch(z.impact_time) if z.impact_time is not None else None)
        vi_has_impact.append(z.impact_time is not None)
        vi_col.append(_COLOUR_CODE[vi_colour(z)]); vi_rank.append(rank_from_last)
        vi_audit.append(f"#{z.id} {status(z)} {'BUY' if z.bullish else 'SELL'}")
        vi_has_line.append(z.impact_time is not None)

    t_id, t_type, t_side, t_bottom, t_top, t_origin, t_trigger, t_eligible, t_impact, t_status, t_bg, t_reason = ([] for _ in range(12))
    for z in table_zones:
        wk = engine.w[z.left]
        t_id.append(f"#{z.id}"); t_type.append(status(z))
        t_side.append('BUY' if z.bullish else 'SELL')
        t_bottom.append(f"{z.zb:.5f}"); t_top.append(f"{z.zt:.5f}")
        t_origin.append(wob.display_iso(wk.start, display_zone))
        t_trigger.append(wob.display_iso(z.trigger_time, display_zone))
        t_eligible.append(wob.display_iso(z.eligible_time, display_zone))
        t_impact.append(wob.display_iso(z.impact_time, display_zone))
        t_status.append(status(z))
        t_bg.append(_COLOUR_CODE[vi_colour(z)])
        t_reason.append(z.stop_reason)

    i_id, i_type, i_side, i_bottom, i_top, i_origin, i_trigger, i_eligible, i_impact, i_status, i_bg, i_rank, i_reason = ([] for _ in range(13))
    for z in engine.zones[::-1]:
        rank_from_last = len(engine.zones) - z.id + 1
        wk = engine.w[z.left]
        i_id.append(f"#{z.id}"); i_type.append(status(z))
        i_side.append('BUY' if z.bullish else 'SELL')
        i_bottom.append(f"{z.zb:.5f}"); i_top.append(f"{z.zt:.5f}")
        i_origin.append(wob.display_iso(wk.start, display_zone))
        i_trigger.append(wob.display_iso(z.trigger_time, display_zone))
        i_eligible.append(wob.display_iso(z.eligible_time, display_zone))
        i_impact.append(wob.display_iso(z.impact_time, display_zone))
        i_status.append(status(z))
        i_bg.append(_COLOUR_CODE[vi_colour(z)]); i_rank.append(rank_from_last)
        i_reason.append(z.stop_reason)

    lines += [
        *pack_array("structX", "int", struct_x),
        *pack_array("structY", "float", struct_y),
        *pack_array("structTxt", "string", struct_txt),
        *pack_array("structColCode", "string", struct_col),
        *pack_array("structLow", "bool", struct_low),
        *pack_array("viLeft", "int", vi_left),
        *pack_array("viTop", "float", vi_top),
        *pack_array("viBottom", "float", vi_bottom),
        *pack_array("viFallbackRight", "int", vi_fallback_right),
        *pack_array("viImpactStamp", "int", vi_impact_stamp),
        *pack_array("viHasImpact", "bool", vi_has_impact),
        *pack_array("viColCode", "string", vi_col),
        *pack_array("viRank", "int", vi_rank),
        *pack_array("viAudit", "string", vi_audit),
        *pack_array("viHasLine", "bool", vi_has_line),
        *pack_array("tId", "string", t_id),
        *pack_array("tType", "string", t_type),
        *pack_array("tSide", "string", t_side),
        *pack_array("tBottom", "string", t_bottom),
        *pack_array("tTop", "string", t_top),
        *pack_array("tOrigin", "string", t_origin),
        *pack_array("tTrigger", "string", t_trigger),
        *pack_array("tEligible", "string", t_eligible),
        *pack_array("tImpact", "string", t_impact),
        *pack_array("tStatus", "string", t_status),
        *pack_array("tBgCode", "string", t_bg),
        *pack_array("tReason", "string", t_reason),
        *pack_array("iId", "string", i_id),
        *pack_array("iType", "string", i_type),
        *pack_array("iSide", "string", i_side),
        *pack_array("iBottom", "string", i_bottom),
        *pack_array("iTop", "string", i_top),
        *pack_array("iOrigin", "string", i_origin),
        *pack_array("iTrigger", "string", i_trigger),
        *pack_array("iEligible", "string", i_eligible),
        *pack_array("iImpact", "string", i_impact),
        *pack_array("iStatus", "string", i_status),
        *pack_array("iBgCode", "string", i_bg),
        *pack_array("iRank", "int", i_rank),
        *pack_array("iReason", "string", i_reason),
        f"var array<int> viImpactX = array.new<int>({len(shown)}, na)",
        "for hi = 0 to array.size(viImpactStamp) - 1",
        "    if array.get(viHasImpact, hi)",
        "        hiStamp = array.get(viImpactStamp, hi)",
        "        if na(array.get(viImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "            array.set(viImpactX, hi, time)",
        "if barstate.islast",
        "    if onWeekly",
        "        for i = 0 to array.size(structX) - 1",
        f"            structCol = {colour_ternary('array.get(structColCode, i)')}",
        "            structYY = array.get(structLow, i) ? array.get(structY, i) - lowGap : array.get(structY, i)",
        "            label.new(array.get(structX, i), structYY, array.get(structTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=structCol, size=size.small)",
        "    if onWeekly or onH4 or on1m or onFive",
        "        for i = 0 to array.size(viLeft) - 1",
        "            if not inspectOneVI or viFromLast == array.get(viRank, i)",
        "                viRight = array.get(viHasImpact, i) and not na(array.get(viImpactX, i)) ? array.get(viImpactX, i) : array.get(viFallbackRight, i)",
        f"                viCol = {colour_ternary('array.get(viColCode, i)')}",
        "                box.new(array.get(viLeft, i), array.get(viTop, i), viRight, array.get(viBottom, i), border_color=viCol, border_width=1, bgcolor=color.new(viCol, 85), xloc=xloc.bar_time)",
        "                if array.get(viHasLine, i)",
        "                    line.new(viRight, array.get(viBottom, i), viRight, array.get(viTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)",
        "    if onWeekly",
        "        table.clear(ledger, 0, 0, 9, 20)",
        "        table.cell(ledger, 0, 0, \"W VI\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 1, 0, \"Type\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 5, 0, \"Left (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 6, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 7, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 8, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 9, 0, \"Status\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        if not inspectOneVI",
        "            for i = 0 to array.size(tId) - 1",
        "                table.cell(ledger, 0, i + 1, array.get(tId, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 1, i + 1, array.get(tType, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 2, i + 1, array.get(tSide, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 3, i + 1, array.get(tBottom, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 4, i + 1, array.get(tTop, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 5, i + 1, array.get(tOrigin, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 6, i + 1, array.get(tTrigger, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 7, i + 1, array.get(tEligible, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 8, i + 1, array.get(tImpact, i), text_color=color.black, bgcolor=na)",
        f"                table.cell(ledger, 9, i + 1, array.get(tStatus, i), text_color=color.black, bgcolor=color.new({colour_ternary('array.get(tBgCode, i)')}, 80))",
        "        for i = 0 to array.size(iId) - 1",
        "            if inspectOneVI and viFromLast == array.get(iRank, i)",
        "                table.cell(ledger, 0, 1, array.get(iId, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 1, 1, array.get(iType, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 2, 1, array.get(iSide, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 3, 1, array.get(iBottom, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 4, 1, array.get(iTop, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 5, 1, array.get(iOrigin, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 6, 1, array.get(iTrigger, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 7, 1, array.get(iEligible, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 8, 1, array.get(iImpact, i), text_color=color.black, bgcolor=na)",
        f"                table.cell(ledger, 9, 1, array.get(iStatus, i), text_color=color.black, bgcolor=color.new({colour_ternary('array.get(iBgCode, i)')}, 80))",
    ]
    if extra_lines:
        lines += extra_lines
    lines.append("")
    (base / out_name).write_text("\n".join(lines), encoding="utf-8")


def write_report(base: Path, minutes: List["wob.Minute"], weeks: List["wob.Week"], warnings: List[str], e: WeeklyVIEngine, args: argparse.Namespace, display_zone: ZoneInfo) -> None:
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)
    counts = {name: 0 for name in ("IVI", "AVI", "OVI", "SPENT")}
    reasons = {"IMPACT": 0, "CLOSE_THROUGH": 0, "STRAND": 0, "STRUCTURAL_BREACH": 0}
    for z in e.zones:
        counts[status(z)] += 1
        if z.stop_reason in reasons:
            reasons[z.stop_reason] += 1
    rows = [
        "WEEKLY VI REFERENCE RUN", f"input={args.csv_file}", f"price_side={args.price_side}",
        f"weekly_aggregation=Sunday {args.week_close_hour:02d}:00 {args.week_close_zone}",
        f"minute_coverage_utc={wob.iso(minutes[0].t)} to {wob.iso(minutes[-1].t)}",
        f"minute_coverage_riyadh={wob.display_iso(minutes[0].t, display_zone)} to {wob.display_iso(minutes[-1].t, display_zone)}",
        f"minutes={len(minutes):,}; weeks={len(weeks):,}; swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}",
        "", "VI LIFECYCLE COUNTS", *[f"{name}={counts[name]}" for name in counts],
        "", "DEATH-CAUSE BREAKDOWN (final stop_reason)", *[f"{name}={reasons[name]}" for name in reasons],
        "", "Colors: IVI BUY=blue; IVI SELL=black; AVI=green (fixed); OVI=red (fixed).",
    ]
    if warnings:
        rows += ["", "WARNINGS"] + warnings[:50]
    (base / "weekly_vi_report.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locked Weekly structure VI reference generator")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-vis", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    try:
        input_tz = ZoneInfo(args.input_tz)
        close_tz = ZoneInfo(args.week_close_zone)
        display_tz = ZoneInfo(args.display_tz)
        minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
        weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
        engine = WeeklyVIEngine(minutes, weeks)
        engine.run()
        write_ledger(base, engine, display_tz)
        write_vi_pine(base, engine, args.pine_labels, args.pine_vis, args.pine_table, display_tz)
        write_report(base, minutes, weeks, warnings, engine, args, display_tz)
        print("Created:")
        print("  weekly_vi_ledger.csv")
        print("  weekly_vi_swings.csv")
        print("  weekly_vi_viewer.pine")
        print("  weekly_vi_report.txt")
        print(f"Processed {len(minutes):,} minutes and {len(weeks)} weeks. The Pine viewer contains Weekly structure and the VI lifecycle.")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
