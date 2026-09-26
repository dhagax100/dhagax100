#!/usr/bin/env python3
"""Weekly FXCM EURUSD OB+RB+FVG combined (single-pass) reference generator.

Stage 1 of the "combination of the other POIs" work. Every prior generator
(weekly_ob_generator.py, weekly_rb_generator.py, weekly_fvg_generator.py)
independently recomputes the exact same swing-high/swing-low/regime/MSS
timeline from the same price data -- that part is pure price math, so all
three always land on identical answers, just three times over. The pine
source the user supplied (Main_Indicator_v1.pine) does it the other way:
ONE swing/regime/MSS loop, with OB, RB and FVG zones all created and
checked for death off that SAME shared clock in the SAME pass, sharing
`self.last_h`/`self.last_l`/`self.regime`/`self.have_h`/`self.have_l`/etc.
directly instead of three separate copies of the same state.

This module is that: one `WeeklyCombinedEngine` class, one `process(k)`
per week, producing OB zones, RB zones and FVG zones together. It is NOT a
rewrite of the construction/lifecycle rules themselves -- every POI-specific
method here is ported verbatim from its own already-verified engine
(reference/weekly_ob_generator.py's WeeklyOBEngine, reference_rb's
WeeklyRBEngine, reference_fvg's WeeklyFVGEngine), including the 2026-09-26
STRUCTURAL_BREACH addition now shared by all three. The only thing that
changes is WHERE the shared swing/regime state lives: one copy instead of
three, so the three POI types can never drift out of sync with each other.

Per the user's explicit direction (2026-09-26): "do whatever RB, OB and FVG
had before. here [structural breach], yes, is a must." So:
  - OB: IMPACT + STRAND + STRUCTURAL_BREACH (no close-through -- unchanged).
  - RB: IMPACT + STRAND + STRUCTURAL_BREACH (no close-through -- unchanged).
  - FVG: IMPACT + STRAND + CLOSE_THROUGH (IFVG only) + STRUCTURAL_BREACH
    (unchanged -- FVG already had all four).
VI is explicitly left out of this pass (put on hold by the user, unresolved
raw-data weekend-gap defect).

CORRECTNESS CHECK (this file's own responsibility, not a separate task):
running this single shared pass must produce EXACTLY the same OB/RB/FVG
zones (same count, same fields) as running the three original separate
engines on the same input. See verify_against_separate_engines() at the
bottom -- run as `python3 weekly_combined_generator.py --verify <csv>`.

The program writes, next to its own file:
  weekly_combined_report.txt   combined lifecycle counts for all three POI
                                types plus the cross-engine regression check
No third-party Python packages are required. Python 3.9+ is sufficient.
"""
from __future__ import annotations

import argparse
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

# Two supported layouts: (1) this repo's own folder structure -- separate
# reference/, reference_rb/, reference_fvg/ siblings -- and (2) copying all
# four .py files (this one plus weekly_ob_generator.py, weekly_rb_generator.py,
# weekly_fvg_generator.py) flat into the SAME working folder together with
# the CSV, same convention already used for weekly_rb_generator.py/
# weekly_fvg_generator.py. Both are tried; the flat same-folder case is
# checked first since that is the actual local workflow.
_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference", _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob        # noqa: E402 -- Minute/Week/Event/MSS/Zone,
                                          # load_minutes, aggregate_weeks, iso helpers
import weekly_rb_generator as wrb        # noqa: E402 -- RBZone
import weekly_fvg_generator as wfvg      # noqa: E402 -- FVGZone

UTC = timezone.utc
OB_STATE = {0: "IFOB", 1: "AOB", 2: "OOB", 3: "SPENT", 4: "AIFOB"}
RB_STATE = {0: "IRB", 1: "ARB", 2: "ORB", 3: "SPENT", 4: "AIRB"}
FVG_STATE = {0: "IFVG", 1: "AFVG", 2: "OFVG", 3: "SPENT"}


class WeeklyCombinedEngine:
    """One shared swing/regime/MSS pass driving OB, RB and FVG together.

    Shared state (ONE copy, used by all three POI types): self.events,
    self.msses, self.regime, self.ei, self.peak/self.trough, self.have_h/
    self.have_l, self.h_price/self.l_price, self.h_idx/self.l_idx,
    self.last_h/self.last_l, self.sw_highs/self.sw_lows.

    Per-POI-type state (separate lists/trackers, same as each POI's own
    standalone engine): self.ob_zones/self.ob_active/self.pend_bull_aifob/
    self.pend_bull_aob/etc.; self.rb_zones/self.rb_active/
    self.pend_bull_airb/etc.; self.fvg_zones/self.fvg_active/
    self.fvg_bull_scan_upto/etc.
    """

    def __init__(self, minutes: List["wob.Minute"], weeks: List["wob.Week"]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]

        # ---- SHARED swing/regime/MSS state (one copy) ----
        self.events: List["wob.Event"] = []
        self.msses: List["wob.MSS"] = []
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0
        self.ei = 0
        self.last_h = self.last_l = -1

        # ---- OB-specific state (mirrors WeeklyOBEngine) ----
        self.ob_zones: List["wob.Zone"] = []
        self.ob_active: List[int] = []
        self.pend_bull_aifob = self.pend_bear_aifob = -1
        self.pend_bull_aob = self.pend_bear_aob = -1
        self.origin_gap_window = wob.timedelta(days=5)

        # ---- RB-specific state (mirrors WeeklyRBEngine) ----
        self.rb_zones: List["wrb.RBZone"] = []
        self.rb_active: List[int] = []
        self._rb_claimed_pairs: set = set()
        self.pend_bull_airb = self.pend_bear_airb = -1

        # ---- FVG-specific state (mirrors WeeklyFVGEngine) ----
        self.fvg_zones: List["wfvg.FVGZone"] = []
        self.fvg_active: List[int] = []
        self._fvg_claimed_pairs: set = set()
        self.fvg_bull_scan_upto = -1
        self.fvg_bear_scan_upto = -1

    # =====================================================================
    # SHARED HELPERS -- copied verbatim from weekly_ob_generator.py's
    # WeeklyOBEngine (event_time, high_first, add_event, first_touch,
    # break_time). DO NOT DIVERGE; if a swing/MSS bug is ever found, fix it
    # in weekly_ob_generator.py first, then re-copy here.
    # =====================================================================

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
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > level) if bull else (m.l < level):
                return m.t
        return None

    # =====================================================================
    # OB -- ported verbatim from WeeklyOBEngine (reference/weekly_ob_generator.py)
    # =====================================================================

    def ob_claimed(self, candle: int, bull: bool) -> bool:
        return any(z.candle == candle and z.bullish == bull for z in self.ob_zones)

    def ob_aifob_in_range(self, lo: int, hi: int, bull: bool) -> bool:
        return any(z.orig_state == 4 and z.bullish == bull and lo <= z.candle <= hi for z in self.ob_zones)

    def ob_add_zone(self, candle: int, bull: bool, trigger: int, state: int, protect_idx: int = -1) -> int:
        wk = self.w[candle]
        z = wob.Zone(len(self.ob_zones) + 1, candle, min(wk.o, wk.c), max(wk.o, wk.c), bull,
                     trigger, -1, -1, None, None, -1, state, state, state)
        if 0 <= protect_idx < len(self.w):
            z.protect_level = self.w[protect_idx].l if bull else self.w[protect_idx].h
        # AOB/AIFOB triggers are the specific event that already exists at
        # creation. Persist it now so later rows cannot select another event
        # with the same weekly index and kind. (Real bug fixed 2026-09-26:
        # this block was dropped when ob_add_zone was first ported here --
        # missed because the initial regression check compared candle/zb/zt/
        # bullish/trigger/eligible/stop/state/rejected/protect_level/
        # stop_reason only, not these audit-only trigger_* fields. Caught by
        # a full ledger diff against the standalone engine, not by that
        # first check -- see reference_combined's own commit history.)
        if state in (1, 4):
            kind = (0 if bull else 1) if state == 1 else (1 if bull else 0)
            event = next((e for e in reversed(self.events) if e.confirm == trigger and e.kind == kind), None)
            if event is not None:
                z.trigger_time, z.trigger_price = event.at, event.price
                z.trigger_swing_price = event.price
                z.trigger_level_role = "event swing level"
                z.trigger_swing_week, z.trigger_confirm_week, z.trigger_path = event.swing, event.confirm, "created event"
        z.created_state = state
        self.ob_zones.append(z)
        self.ob_active.append(len(self.ob_zones) - 1)
        return len(self.ob_zones) - 1

    def ob_promote_aob(self, idx: int, bull: bool, k: int, armed_level: float, armed_swing: int) -> bool:
        if not (0 <= idx < len(self.ob_zones)):
            return False
        z = self.ob_zones[idx]
        if z.state == 1 and z.orig_state == 1 and z.bullish == bull and z.eligible < 0 and not z.rejected:
            z.promotion_from_state = z.state
            z.promotion_time = self.w[k].start
            z.state = z.orig_state = 0
            z.eligible_time = None
            z.eligible_kind = -1
            z.eligible_price = None
            z.eligible_swing_price = None
            z.stop = -1
            self.ob_set_promoted_ifob_trigger(z, bull, k, armed_level, armed_swing)
            return True
        return False

    def ob_best(self, lo: int, hi: int, bullish_zone: bool, skip: int = -1) -> int:
        chosen = -1
        for x in range(max(0, lo), min(len(self.w) - 1, hi) + 1):
            if x == skip:
                continue
            wk = self.w[x]
            if bullish_zone and wk.c < wk.o and (chosen < 0 or wk.c < self.w[chosen].c):
                chosen = x
            if not bullish_zone and wk.c > wk.o and (chosen < 0 or wk.c > self.w[chosen].c):
                chosen = x
        return chosen

    def ob_best_ifob_origin(self, lo: int, hi: int, bullish_zone: bool, skip: int = -1) -> int:
        chosen = -1
        for x in range(max(0, lo), min(len(self.w) - 1, hi) + 1):
            if x == skip:
                continue
            body = self.ob_ifob_origin_body(x)
            if body is None:
                continue
            o, c = body
            chosen_body = self.ob_ifob_origin_body(chosen) if chosen >= 0 else None
            chosen_c = chosen_body[1] if chosen_body is not None else 0.0
            if bullish_zone and c < o and (chosen < 0 or c < chosen_c):
                chosen = x
            if not bullish_zone and c > o and (chosen < 0 or c > chosen_c):
                chosen = x
        return chosen

    def ob_ifob_origin_body(self, k: int):
        if not (0 <= k < len(self.w)):
            return None
        wk = self.w[k]
        if self.origin_gap_window is None:
            return (wk.o, wk.c)
        last = bisect_left(self.mt, wk.start + self.origin_gap_window) - 1
        return None if last < wk.first else (self.m[wk.first].o, self.m[last].c)

    def ob_try_bull_aob(self, preg: int, armed_h: int, new_low: int, price: float, k: int) -> None:
        if preg != 1 or armed_h < 0:
            return
        if any(self.w[v].h >= self.w[armed_h].h for v in range(armed_h + 1, new_low + 1)):
            return
        best = self.ob_best(min(armed_h - 1, new_low), max(armed_h - 1, new_low), False)
        if best >= 0 and self.w[best].l > price and not self.ob_claimed(best, False):
            idx = self.ob_add_zone(best, False, k, 1, self.last_h)
            z = self.ob_zones[idx]
            if k > 0 and self.w[k - 1].h > z.zt:
                z.rejected = True
            elif k > 0:
                z.eligible = k
                z.eligible_kind = 1
                z.eligible_time = self.event_time(1, k)
                z.eligible_price = self.w[k - 1].h
                z.eligible_swing_price = price

    def ob_try_bear_aob(self, preg: int, armed_l: int, new_high: int, price: float, k: int) -> None:
        if preg != 2 or armed_l < 0:
            return
        if any(self.w[v].l <= self.w[armed_l].l for v in range(armed_l + 1, new_high + 1)):
            return
        best = self.ob_best(min(armed_l - 1, new_high), max(armed_l - 1, new_high), True)
        if best >= 0 and self.w[best].h < price and not self.ob_claimed(best, True):
            idx = self.ob_add_zone(best, True, k, 1, self.last_l)
            z = self.ob_zones[idx]
            if k > 0 and self.w[k - 1].l < z.zb:
                z.rejected = True
            elif k > 0:
                z.eligible = k
                z.eligible_kind = 0
                z.eligible_time = self.event_time(0, k)
                z.eligible_price = self.w[k - 1].l
                z.eligible_swing_price = price

    def ob_try_bull_aifob(self, preg: int, had_h: bool, armed_h: int, last_low: int, new_low: int, k: int) -> int:
        if preg != 1 or not had_h or armed_h < 0 or last_low < 0 or self.w[k].l < self.w[new_low].l:
            return -1
        best = self.ob_best(min(last_low, new_low, armed_h - 1), max(last_low, new_low, armed_h - 1), True)
        return self.ob_add_zone(best, True, k, 4, self.last_l) if best >= 0 and not self.ob_claimed(best, True) else -1

    def ob_try_bear_aifob(self, preg: int, had_l: bool, armed_l: int, last_high: int, new_high: int, k: int) -> int:
        if preg != 2 or not had_l or armed_l < 0 or last_high < 0 or self.w[k].h > self.w[new_high].h:
            return -1
        best = self.ob_best(min(last_high, new_high, armed_l - 1), max(last_high, new_high, armed_l - 1), False)
        return self.ob_add_zone(best, False, k, 4, self.last_h) if best >= 0 and not self.ob_claimed(best, False) else -1

    def ob_add_ifob(self, bull: bool, k: int, swing: int, last_opposite: int) -> None:
        lo, hi = min(last_opposite, k, swing), max(last_opposite, k, swing)
        if self.ob_aifob_in_range(lo, hi, bull):
            return
        locked_best = self.ob_best(lo, hi, bull)
        best = self.ob_best_ifob_origin(lo, hi, bull)
        if best >= 0 and not self.ob_claimed(best, bull):
            idx = self.ob_add_zone(best, bull, k, 0, self.last_l if bull else self.last_h)
            z = self.ob_zones[idx]
            if best == k:
                z.same_bar_origin_guard = last_opposite
            body = self.ob_ifob_origin_body(best) if best != locked_best else None
            if body is not None:
                z.zb, z.zt = min(body), max(body)
            relevant_kind = 0 if bull else 1
            event = next((e for e in reversed(self.events) if e.kind == relevant_kind and e.swing == swing and e.confirm <= k), None)
            if event is not None and k > 0:
                z.trigger_swing_price = event.price
                z.trigger_price = self.w[k - 1].h if bull else self.w[k - 1].l
                z.trigger_level_role = "prior-week high break level" if bull else "prior-week low break level"
                z.trigger_swing_week, z.trigger_confirm_week, z.trigger_path = event.swing, event.confirm, "direct IFOB armed event"
                wk = self.w[k]
                for m in self.m[bisect_left(self.mt, wk.start):bisect_left(self.mt, wk.end)]:
                    if (m.h > z.trigger_swing_price) if bull else (m.l < z.trigger_swing_price):
                        z.trigger_time = m.t
                        break

    def ob_set_promoted_ifob_trigger(self, z, bull: bool, k: int, armed_level: float, armed_swing: int) -> None:
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

    # =====================================================================
    # RB -- ported verbatim from WeeklyRBEngine (reference_rb/weekly_rb_generator.py)
    # =====================================================================

    def rb_claimed(self, candle: int, bull: bool) -> bool:
        return (candle, bull) in self._rb_claimed_pairs

    def rb_add_from_swing(self, idx: int, is_high: bool, trigger_k: int, origin_type: int,
                           trigger_time: Optional[datetime], state: Optional[int] = None,
                           protect_idx: int = -1) -> int:
        bull_of_this = not is_high
        if self.rb_claimed(idx, bull_of_this):
            return -1
        wk = self.w[idx]
        if is_high:
            zb, zt, bull = max(wk.o, wk.c), wk.h, False
        else:
            zb, zt, bull = wk.l, min(wk.o, wk.c), True
        actual_state = state if state is not None else origin_type
        eligible = trigger_k if origin_type == 1 and actual_state != 4 else -1
        eligible_time = trigger_time if origin_type == 1 and actual_state != 4 else None
        z = wrb.RBZone(len(self.rb_zones) + 1, idx, zb, zt, bull, trigger_k, eligible, -1,
                       actual_state, origin_type, actual_state, trigger_time=trigger_time,
                       eligible_time=eligible_time, created_state=actual_state)
        if 0 <= protect_idx < len(self.w):
            z.protect_level = self.w[protect_idx].l if bull else self.w[protect_idx].h
        self.rb_zones.append(z)
        self.rb_active.append(len(self.rb_zones) - 1)
        self._rb_claimed_pairs.add((idx, bull_of_this))
        return len(self.rb_zones) - 1

    def rb_try_bull_arb(self, preg: int, armed_swh: int, new_swl_i: int, k: int, at: Optional[datetime]) -> None:
        if preg != 1 or armed_swh < 0:
            return
        if any(self.w[v].h >= self.w[armed_swh].h for v in range(armed_swh + 1, new_swl_i + 1)):
            return
        self.rb_add_from_swing(armed_swh, True, k, 1, at, protect_idx=self.last_h)

    def rb_try_bear_arb(self, preg: int, armed_swl: int, new_swh_i: int, k: int, at: Optional[datetime]) -> None:
        if preg != 2 or armed_swl < 0:
            return
        if any(self.w[v].l <= self.w[armed_swl].l for v in range(armed_swl + 1, new_swh_i + 1)):
            return
        self.rb_add_from_swing(armed_swl, False, k, 1, at, protect_idx=self.last_l)

    def rb_try_bull_airb(self, preg: int, had_h: bool, armed_h: int, last_low: int, new_low: int, k: int, at: Optional[datetime]) -> int:
        if preg != 1 or not had_h or armed_h < 0 or last_low < 0 or self.w[k].l < self.w[new_low].l:
            return -1
        return self.rb_add_from_swing(new_low, False, k, 0, at, state=4, protect_idx=self.last_l)

    def rb_try_bear_airb(self, preg: int, had_l: bool, armed_l: int, last_high: int, new_high: int, k: int, at: Optional[datetime]) -> int:
        if preg != 2 or not had_l or armed_l < 0 or last_high < 0 or self.w[k].h > self.w[new_high].h:
            return -1
        return self.rb_add_from_swing(new_high, True, k, 0, at, state=4, protect_idx=self.last_h)

    # =====================================================================
    # FVG -- ported verbatim from WeeklyFVGEngine (reference_fvg/weekly_fvg_generator.py)
    # =====================================================================

    def fvg_claimed(self, left: int, bull: bool) -> bool:
        return (left, bull) in self._fvg_claimed_pairs

    def fvg_add(self, left: int, zb: float, zt: float, bull: bool, trigger_k: int,
                origin: int, trigger_time: Optional[datetime], protect_idx: int = -1) -> int:
        if self.fvg_claimed(left, bull):
            return -1
        eligible = trigger_k if origin == 1 else -1
        eligible_time = trigger_time if origin == 1 else None
        protect_level = None
        if 0 <= protect_idx < len(self.w):
            protect_level = self.w[protect_idx].l if bull else self.w[protect_idx].h
        z = wfvg.FVGZone(len(self.fvg_zones) + 1, left, zb, zt, bull, trigger_k, eligible, -1,
                          origin, origin, origin, trigger_time=trigger_time, eligible_time=eligible_time,
                          protect_level=protect_level)
        self.fvg_zones.append(z)
        self.fvg_active.append(len(self.fvg_zones) - 1)
        self._fvg_claimed_pairs.add((left, bull))
        return len(self.fvg_zones) - 1

    def fvg_try_create_ifvgs(self, lo: int, hi: int, bullish: bool, trigger_k: int,
                              trigger_time: Optional[datetime], protect_idx: int) -> None:
        if hi < lo + 2:
            return
        for c3 in range(lo + 2, hi + 1):
            c1 = c3 - 2
            if bullish:
                h1, l3 = self.w[c1].h, self.w[c3].l
                if h1 < l3:
                    self.fvg_add(c1, h1, l3, True, trigger_k, 0, trigger_time, protect_idx)
            else:
                l1, h3 = self.w[c1].l, self.w[c3].h
                if l1 > h3:
                    self.fvg_add(c1, h3, l1, False, trigger_k, 0, trigger_time, protect_idx)

    def fvg_try_create_afvgs(self, lo: int, hi: int, bullish: bool, trigger_k: int,
                              guard_price: float, trigger_time: Optional[datetime], protect_idx: int) -> None:
        if hi < lo + 2:
            return
        for c3 in range(lo + 2, hi + 1):
            c1 = c3 - 2
            if bullish:
                l1, h3 = self.w[c1].l, self.w[c3].h
                if l1 > h3:
                    l3 = self.w[c3].l
                    if l1 > guard_price and l3 > guard_price:
                        self.fvg_add(c1, h3, l1, True, trigger_k, 1, trigger_time, protect_idx)
            else:
                h1, l3 = self.w[c1].h, self.w[c3].l
                if h1 < l3:
                    h3 = self.w[c3].h
                    if h1 < guard_price and h3 < guard_price:
                        self.fvg_add(c1, h1, l3, False, trigger_k, 1, trigger_time, protect_idx)

    def fvg_try_bull_afvg(self, preg: int, armed_swh: int, new_swl_i: int, new_swl_p: float, k: int, at: Optional[datetime]) -> None:
        if preg != 1 or armed_swh < 0:
            return
        if any(self.w[v].h >= self.w[armed_swh].h for v in range(armed_swh + 1, new_swl_i + 1)):
            return
        swl_ext = new_swl_i + 1 if new_swl_i + 1 <= k - 1 else new_swl_i
        lo = max(0, min(armed_swh - 1, swl_ext))
        hi = max(armed_swh - 1, swl_ext)
        self.fvg_try_create_afvgs(lo, hi, True, k, new_swl_p, at, self.last_l)

    def fvg_try_bear_afvg(self, preg: int, armed_swl: int, new_swh_i: int, new_swh_p: float, k: int, at: Optional[datetime]) -> None:
        if preg != 2 or armed_swl < 0:
            return
        if any(self.w[v].l <= self.w[armed_swl].l for v in range(armed_swl + 1, new_swh_i + 1)):
            return
        swh_ext = new_swh_i + 1 if new_swh_i + 1 <= k - 1 else new_swh_i
        lo = max(0, min(armed_swl - 1, swh_ext))
        hi = max(armed_swl - 1, swh_ext)
        self.fvg_try_create_afvgs(lo, hi, False, k, new_swh_p, at, self.last_h)

    def week_extreme_time(self, k: int, want_low: bool) -> Optional[datetime]:
        wk = self.w[k]
        target = wk.l if want_low else wk.h
        for m in self.m[wk.first:wk.last]:
            if (m.l <= target) if want_low else (m.h >= target):
                return m.t
        return None

    # =====================================================================
    # SHARED consume_break / mid_arm / finish_events_and_lifecycle -- calls
    # each POI type's own creation methods off the SAME break/mid-arm event,
    # sharing preg/armed_h/armed_l/last_h/last_l/k. This is the actual
    # "single-pass" merge: OB's promotion+add_ifob, RB's promotion+
    # add_from_swing, and FVG's range-scan all fire from the SAME regime
    # flip/MSS/swing-confirm moment instead of three separate re-derivations.
    # =====================================================================

    def consume_break(self, bull: bool, k: int) -> bool:
        if bull:
            if not self.have_h or self.w[k].h <= self.h_price:
                return False
            if self.regime == 2:
                self.msses.append(wob.MSS(k, self.h_idx, self.h_price, True))
            self.regime = 1

            # OB: promote AOB, or promote pending-alive AIFOB, or fresh IFOB.
            ob_promoted = self.ob_promote_aob(self.pend_bull_aob, True, k, self.h_price, self.h_idx)
            self.pend_bull_aob = -1
            ob_alive = 0 <= self.pend_bull_aifob < len(self.ob_zones) and self.ob_zones[self.pend_bull_aifob].state == 4
            if ob_alive:
                z = self.ob_zones[self.pend_bull_aifob]
                z.promotion_from_state = z.state
                z.state = z.orig_state = 0
                z.eligible = -1
                z.eligible_time = None
                z.eligible_kind = -1
                z.eligible_price = None
                z.eligible_swing_price = None
                self.ob_set_promoted_ifob_trigger(z, True, k, self.h_price, self.h_idx)
            elif self.last_l >= 0 and not ob_promoted:
                self.ob_add_ifob(True, k, self.h_idx, self.last_l)
            self.pend_bull_aifob = -1

            # FVG: same lo/hi window OB's add_ifob would have used for a
            # fresh IFOB, whether or not OB itself actually created one this
            # time (promotion/AIFOB-alive cases still leave a real gap
            # behind for FVG to find).
            if self.last_l >= 0:
                lo, hi = min(self.last_l, k, self.h_idx), max(self.last_l, k, self.h_idx)
                bt = self.break_time(k, True, self.h_price)
                self.fvg_try_create_ifvgs(lo, hi, True, k, bt, self.last_l)
                self.fvg_bull_scan_upto = hi

            # RB: promote pending-alive AIRB, or fresh IRB anchored on the
            # opposite reference swing (self.last_l) -- no range scan needed,
            # RB anchors directly on the swing's own wick.
            rb_promoted = False
            if 0 <= self.pend_bull_airb < len(self.rb_zones) and self.rb_zones[self.pend_bull_airb].state == 4:
                z = self.rb_zones[self.pend_bull_airb]
                z.promotion_from_state = z.state
                z.state = 0
                z.trigger = k
                z.trigger_time = self.break_time(k, True, self.h_price)
                z.promotion_time = self.w[k].start
                z.eligible = -1
                z.eligible_time = None
                rb_promoted = True
            self.pend_bull_airb = -1
            if not rb_promoted and self.last_l >= 0:
                self.rb_add_from_swing(self.last_l, False, k, 0, self.break_time(k, True, self.h_price), protect_idx=self.last_l)

            self.have_h = False
            return True

        if not self.have_l or self.w[k].l >= self.l_price:
            return False
        if self.regime == 1:
            self.msses.append(wob.MSS(k, self.l_idx, self.l_price, False))
        self.regime = 2

        ob_promoted = self.ob_promote_aob(self.pend_bear_aob, False, k, self.l_price, self.l_idx)
        self.pend_bear_aob = -1
        ob_alive = 0 <= self.pend_bear_aifob < len(self.ob_zones) and self.ob_zones[self.pend_bear_aifob].state == 4
        if ob_alive:
            z = self.ob_zones[self.pend_bear_aifob]
            z.promotion_from_state = z.state
            z.state = z.orig_state = 0
            z.eligible = -1
            z.eligible_time = None
            z.eligible_kind = -1
            z.eligible_price = None
            z.eligible_swing_price = None
            self.ob_set_promoted_ifob_trigger(z, False, k, self.l_price, self.l_idx)
        elif self.last_h >= 0 and not ob_promoted:
            self.ob_add_ifob(False, k, self.l_idx, self.last_h)
        self.pend_bear_aifob = -1

        if self.last_h >= 0:
            lo, hi = min(self.last_h, k, self.l_idx), max(self.last_h, k, self.l_idx)
            bt = self.break_time(k, False, self.l_price)
            self.fvg_try_create_ifvgs(lo, hi, False, k, bt, self.last_h)
            self.fvg_bear_scan_upto = hi

        rb_promoted = False
        if 0 <= self.pend_bear_airb < len(self.rb_zones) and self.rb_zones[self.pend_bear_airb].state == 4:
            z = self.rb_zones[self.pend_bear_airb]
            z.promotion_from_state = z.state
            z.state = 0
            z.trigger = k
            z.trigger_time = self.break_time(k, False, self.l_price)
            z.promotion_time = self.w[k].start
            z.eligible = -1
            z.eligible_time = None
            rb_promoted = True
        self.pend_bear_airb = -1
        if not rb_promoted and self.last_h >= 0:
            self.rb_add_from_swing(self.last_h, True, k, 0, self.break_time(k, False, self.l_price), protect_idx=self.last_h)

        self.have_l = False
        return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True
                self.h_price = ev.price
                self.h_idx = ev.swing
                self.pend_bull_aifob = self.pend_bull_aob = -1
                self.pend_bull_airb = -1
                self.ob_try_bear_aob(preg, armed_l, ev.swing, ev.price, k)
                self.fvg_try_bear_afvg(preg, armed_l, ev.swing, ev.price, k, ev.at)
                self.rb_try_bear_arb(preg, armed_l, ev.swing, k, ev.at)
                if self.pend_bear_aifob < 0:
                    self.pend_bear_aifob = self.ob_try_bear_aifob(preg, self.have_l, armed_l, self.last_h, ev.swing, k)
                if self.pend_bear_airb < 0:
                    self.pend_bear_airb = self.rb_try_bear_airb(preg, self.have_l, armed_l, self.last_h, ev.swing, k, ev.at)
            else:
                self.have_l = True
                self.l_price = ev.price
                self.l_idx = ev.swing
                self.pend_bear_aifob = self.pend_bear_aob = -1
                self.pend_bear_airb = -1
                self.ob_try_bull_aob(preg, armed_h, ev.swing, ev.price, k)
                self.fvg_try_bull_afvg(preg, armed_h, ev.swing, ev.price, k, ev.at)
                self.rb_try_bull_arb(preg, armed_h, ev.swing, k, ev.at)
                if self.pend_bull_aifob < 0:
                    self.pend_bull_aifob = self.ob_try_bull_aifob(preg, self.have_h, armed_h, self.last_l, ev.swing, k)
                if self.pend_bull_airb < 0:
                    self.pend_bull_airb = self.rb_try_bull_airb(preg, self.have_h, armed_h, self.last_l, ev.swing, k, ev.at)

    def ob_try_bear_aifob(self, preg: int, had_l: bool, armed_l: int, last_high: int, new_high: int, k: int) -> int:
        result = -1
        already_broke = self.w[k].h > self.w[new_high].h
        if preg == 2 and had_l and armed_l >= 0 and last_high >= 0 and not already_broke:
            best = self.ob_best(min(last_high, new_high, armed_l - 1), max(last_high, new_high, armed_l - 1), False)
            if best != -1 and not self.ob_claimed(best, False):
                result = self.ob_add_zone(best, False, k, 4, self.last_h)
        return result

    def ob_try_bull_aifob(self, preg: int, had_h: bool, armed_h: int, last_low: int, new_low: int, k: int) -> int:
        result = -1
        already_broke = self.w[k].l < self.w[new_low].l
        if preg == 1 and had_h and armed_h >= 0 and last_low >= 0 and not already_broke:
            best = self.ob_best(min(last_low, new_low, armed_h - 1), max(last_low, new_low, armed_h - 1), True)
            if best != -1 and not self.ob_claimed(best, True):
                result = self.ob_add_zone(best, True, k, 4, self.last_l)
        return result

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        # Same-bar-origin guard (OB only) -- mirrors WeeklyOBEngine exactly.
        for zidx in self.ob_active[:]:
            z = self.ob_zones[zidx]
            if z.same_bar_origin_guard >= 0 and z.candle + 1 == k:
                swing_idx = z.same_bar_origin_guard
                breached = (self.w[k].l < self.w[swing_idx].l) if z.bullish else (self.w[k].h > self.w[swing_idx].h)
                if breached:
                    z.rejected = True
                z.same_bar_origin_guard = -1

        while self.ei < total and self.events[self.ei].confirm == k:
            ev = self.events[self.ei]
            if ev.kind == 0:
                if not consumed_h:
                    self.have_h = True
                    self.h_price = ev.price
                    self.h_idx = ev.swing
                self.last_h = ev.swing
                for zidx in self.ob_active[:]:
                    z = self.ob_zones[zidx]
                    if z.bullish and z.state in (0, 1, 4) and z.eligible < 0 and not z.rejected and k > z.trigger:
                        ok = z.orig_state not in (1, 4) or z.zt < ev.price
                        if not ok or (k > 0 and self.w[k - 1].l < z.zb):
                            z.rejected = True
                        else:
                            z.eligible = k
                            z.eligible_kind = 0
                            z.eligible_time = ev.at
                            z.eligible_price = self.w[k - 1].l
                            z.eligible_swing_price = ev.price
                for zidx in self.fvg_active:
                    z = self.fvg_zones[zidx]
                    if z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
                for zidx in self.rb_active:
                    z = self.rb_zones[zidx]
                    if z.bullish and z.state in (0, 4) and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            else:
                if not consumed_l:
                    self.have_l = True
                    self.l_price = ev.price
                    self.l_idx = ev.swing
                self.last_l = ev.swing
                for zidx in self.ob_active[:]:
                    z = self.ob_zones[zidx]
                    if not z.bullish and z.state in (0, 1, 4) and z.eligible < 0 and not z.rejected and k > z.trigger:
                        ok = z.orig_state not in (1, 4) or z.zb > ev.price
                        if not ok or (k > 0 and self.w[k - 1].h > z.zt):
                            z.rejected = True
                        else:
                            z.eligible = k
                            z.eligible_kind = 1
                            z.eligible_time = ev.at
                            z.eligible_price = self.w[k - 1].h
                            z.eligible_swing_price = ev.price
                for zidx in self.fvg_active:
                    z = self.fvg_zones[zidx]
                    if not z.bullish and z.state == 0 and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
                for zidx in self.rb_active:
                    z = self.rb_zones[zidx]
                    if not z.bullish and z.state in (0, 4) and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            self.ei += 1

        # ---- OB lifecycle: IMPACT + STRAND + STRUCTURAL_BREACH ----
        for zidx in self.ob_active[:]:
            z = self.ob_zones[zidx]
            if z.rejected or z.state == 3:
                continue
            touch = None
            if z.eligible >= 0 and k >= z.eligible:
                touch = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
            strand_ev = None
            if z.state in (0, 1, 4) and z.eligible >= 0:
                for ev in self.events[before:total]:
                    if ev.confirm == k and ((z.bullish and ev.kind == 1 and ev.price > z.zt) or (not z.bullish and ev.kind == 0 and ev.price < z.zb)):
                        strand_ev = ev
                        break
            breach_at = None
            if z.state in (0, 1, 4) and z.protect_level is not None:
                breach_at = self.break_time(k, not z.bullish, z.protect_level)
            candidates = []
            if touch is not None:
                candidates.append(("IMPACT", touch))
            if strand_ev is not None and strand_ev.at is not None:
                candidates.append(("STRAND", strand_ev.at))
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
        self.ob_active = [i for i in self.ob_active if not self.ob_zones[i].rejected and self.ob_zones[i].state != 3]

        # ---- RB lifecycle: IMPACT + STRAND + STRUCTURAL_BREACH ----
        for zidx in self.rb_active:
            z = self.rb_zones[zidx]
            if z.state == 3:
                continue
            touch = None
            if z.eligible >= 0 and k >= z.eligible:
                touch = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
            strand_ev = None
            if z.state in (0, 1, 4) and z.eligible != -1:
                for ev in self.events[before:total]:
                    if ev.confirm != k:
                        continue
                    stranded = (z.bullish and ev.kind == 1 and ev.price > z.zt) or (not z.bullish and ev.kind == 0 and ev.price < z.zb)
                    if stranded:
                        strand_ev = ev
                        break
            breach_at = None
            if z.state in (0, 1, 4) and z.protect_level is not None:
                breach_at = self.break_time(k, not z.bullish, z.protect_level)
            candidates = []
            if touch is not None:
                candidates.append(("IMPACT", touch))
            if strand_ev is not None and strand_ev.at is not None:
                candidates.append(("STRAND", strand_ev.at))
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

        # ---- FVG lifecycle: IMPACT + STRAND + CLOSE_THROUGH (IFVG only) + STRUCTURAL_BREACH ----
        for zidx in self.fvg_active:
            z = self.fvg_zones[zidx]
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
                    stranded = (z.bullish and ev.kind == 1 and ev.price > z.zt) or (not z.bullish and ev.kind == 0 and ev.price < z.zb)
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

        # STEP 1b: continuous IFVG scan (FVG-only, no OB/RB analog).
        if self.regime == 1 and k >= 2 and k > self.fvg_bull_scan_upto:
            h1c, l3c = self.w[k - 2].h, self.w[k].l
            if h1c < l3c:
                trig_at = self.week_extreme_time(k, True) or self.w[k].start
                self.fvg_add(k - 2, h1c, l3c, True, k, 0, trig_at, self.last_l)
            self.fvg_bull_scan_upto = k
        if self.regime == 2 and k >= 2 and k > self.fvg_bear_scan_upto:
            l1c, h3c = self.w[k - 2].l, self.w[k].h
            if l1c > h3c:
                trig_at = self.week_extreme_time(k, False) or self.w[k].start
                self.fvg_add(k - 2, h3c, l1c, False, k, 0, trig_at, self.last_h)
            self.fvg_bear_scan_upto = k

        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)):
            self.process(k)


class _OBEngineView:
    """Thin duck-typed adapter so wob.write_ledger/write_ob_pine/write_report
    (written against a standalone WeeklyOBEngine) can run unchanged against
    this combined engine's shared state + self.ob_zones. Only the attribute
    surface those functions actually touch (checked directly: zones, events,
    msses, m, w, mt, first_touch) is exposed -- nothing is re-implemented."""

    def __init__(self, combo: "WeeklyCombinedEngine"):
        self._c = combo
        self.zones = combo.ob_zones
        self.events = combo.events
        self.msses = combo.msses
        self.m = combo.m
        self.w = combo.w
        self.mt = combo.mt

    def first_touch(self, start, k, bull, zb, zt):
        return self._c.first_touch(start, k, bull, zb, zt)


class _RBEngineView:
    def __init__(self, combo: "WeeklyCombinedEngine"):
        self._c = combo
        self.zones = combo.rb_zones
        self.events = combo.events
        self.msses = combo.msses
        self.m = combo.m
        self.w = combo.w
        self.mt = combo.mt

    def first_touch(self, start, k, bull, zb, zt):
        return self._c.first_touch(start, k, bull, zb, zt)

    def break_time(self, k, bull, level):
        return self._c.break_time(k, bull, level)


class _FVGEngineView:
    def __init__(self, combo: "WeeklyCombinedEngine"):
        self._c = combo
        self.zones = combo.fvg_zones
        self.events = combo.events
        self.msses = combo.msses
        self.m = combo.m
        self.w = combo.w
        self.mt = combo.mt

    def first_touch(self, start, k, bull, zb, zt):
        return self._c.first_touch(start, k, bull, zb, zt)

    def break_time(self, k, bull, level):
        return self._c.break_time(k, bull, level)


def ob_status(z) -> str:
    return OB_STATE[z.pre_spent_state if z.state == 3 else z.state]


def rb_status(z) -> str:
    return RB_STATE[z.pre_spent_state if z.state == 3 else z.state]


def fvg_status(z) -> str:
    return FVG_STATE[z.pre_spent_state if z.state == 3 else z.state]


def write_combined_pine(base: Path, engine: WeeklyCombinedEngine, label_cap: int, ob_cap: int, rb_cap: int,
                         fvg_cap: int, table_cap: int, display_zone: ZoneInfo, out_name: str = "weekly_combined_viewer.pine") -> None:
    """ONE pine file: the shared swing/regime/MSS structure drawn ONCE, with
    OB, RB and FVG zones all overlaid on top of it -- mirrors
    Main_Indicator_v1.pine's own single-chart layout, instead of three
    separate viewer files each redrawing the identical swing/MSS labels on
    their own. Array-packed throughout (pack_array/pine_epoch/colour_ternary,
    reused unchanged from weekly_rb_generator.py -- same CE10295 avoidance
    discipline as every other pine writer in this project).

    Visual convention per POI type (matches each one's own standalone
    viewer, so a zone looks the same whether you're looking at this combined
    chart or its own individual one): OB = hollow box, solid border. RB =
    hollow box, dashed border. FVG = filled box (85% transparency), solid
    border. All three still use each POI's own established colour rule
    (state 0=blue/black by side, 1=green, 2=red, 4=orange)."""
    pack_array = wrb.pack_array
    pine_epoch = wrb.pine_epoch
    colour_ternary = wrb.colour_ternary
    COLOUR_CODE = wrb._COLOUR_CODE

    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    right_edge = engine.m[-1].t + timedelta(days=365)

    lines = [
        "//@version=6",
        "indicator(\"FXCM Weekly OB+RB+FVG Combined - Python Reference\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. ONE shared swing/regime/MSS pass",
        "// drives OB, RB and FVG together (mirrors Main_Indicator_v1.pine's own",
        "// single-chart structure) -- not three separate re-derivations merged after.",
        "float lowGap = ta.atr(14) * 0.08",
        "string focusPoi = input.string(\"ALL\", \"Focus POI\", options=[\"ALL\", \"OB\", \"RB\", \"FVG\"], group=\"Combined settings\", tooltip=\"ALL draws every POI type and shows every row in the table. Choosing one shows only that type's boxes and table rows.\")",
        f"var table ledger = table.new(position.top_right, 11, {table_cap + 1}, border_width=1)",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
        "bool onFive = timeframe.period == \"5\"",
        "bool on1m = timeframe.period == \"1\"",
    ]

    # ---- shared swing/MSS labels, drawn ONCE ----
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

    def _box_arrays(zones, left_of, prefix_label):
        left, top, bottom, fallback_right, impact_stamp, has_impact, col, audit = ([] for _ in range(8))
        for z in zones:
            if getattr(z, "rejected", False):
                continue
            wk = engine.w[left_of(z)]
            fb_right = z.impact_time or (engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else right_edge)
            left.append(pine_epoch(wk.start)); top.append(z.zt); bottom.append(z.zb)
            fallback_right.append(pine_epoch(fb_right))
            impact_stamp.append(pine_epoch(z.impact_time) if z.impact_time is not None else None)
            has_impact.append(z.impact_time is not None)
            audit.append(f"{prefix_label} #{z.id} {'BUY' if z.bullish else 'SELL'}")
        return left, top, bottom, fallback_right, impact_stamp, has_impact, col, audit

    ob_shown = engine.ob_zones[-ob_cap:]
    ob_left, ob_top, ob_bottom, ob_fallback_right, ob_impact_stamp, ob_has_impact, ob_col, ob_audit = _box_arrays(ob_shown, lambda z: z.candle, "OB")
    for z in ob_shown:
        if not z.rejected:
            ob_col.append(COLOUR_CODE[wob.pine_colour(z)])

    rb_shown = engine.rb_zones[-rb_cap:]
    rb_left, rb_top, rb_bottom, rb_fallback_right, rb_impact_stamp, rb_has_impact, rb_col, rb_audit = _box_arrays(rb_shown, lambda z: z.candle, "RB")
    for z in rb_shown:
        rb_col.append(COLOUR_CODE[wrb.rb_colour(z)])

    fvg_shown = engine.fvg_zones[-fvg_cap:]
    fvg_left, fvg_top, fvg_bottom, fvg_fallback_right, fvg_impact_stamp, fvg_has_impact, fvg_col, fvg_audit = _box_arrays(fvg_shown, lambda z: z.left, "FVG")
    for z in fvg_shown:
        fvg_col.append(COLOUR_CODE[wfvg.fvg_colour(z)])

    # ---- combined ledger table rows: OB+RB+FVG merged, newest (by origin
    # week) first, capped to table_cap TOTAL rows across all three types.
    # The "Focus POI" toggle filters which rows actually render at draw
    # time (Pine can't know the runtime input value in Python), so every
    # row is packed regardless, tagged with its own POI type.
    def _table_rows(zones, left_of, status_fn, colour_fn, poi_label):
        rows = []
        for z in zones:
            if getattr(z, "rejected", False):
                continue
            wk = engine.w[left_of(z)]
            rows.append((wk.start, dict(
                poi=poi_label, id=f"#{z.id}", type=status_fn(z), side="BUY" if z.bullish else "SELL",
                bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
                origin=wob.display_iso(wk.start, display_zone),
                trigger=wob.display_iso(z.trigger_time, display_zone),
                eligible=wob.display_iso(z.eligible_time, display_zone),
                impact=wob.display_iso(z.impact_time, display_zone),
                status=status_fn(z), bg=COLOUR_CODE[colour_fn(z)],
            )))
        return rows

    all_rows = (
        _table_rows(engine.ob_zones, lambda z: z.candle, ob_status, wob.pine_colour, "OB")
        + _table_rows(engine.rb_zones, lambda z: z.candle, rb_status, wrb.rb_colour, "RB")
        + _table_rows(engine.fvg_zones, lambda z: z.left, fvg_status, wfvg.fvg_colour, "FVG")
    )
    all_rows.sort(key=lambda pair: pair[0], reverse=True)
    table_rows = [r for _, r in all_rows[:table_cap]]

    t_poi, t_id, t_type, t_side, t_bottom, t_top, t_origin, t_trigger, t_eligible, t_impact, t_status, t_bg = ([] for _ in range(12))
    for r in table_rows:
        t_poi.append(r["poi"]); t_id.append(r["id"]); t_type.append(r["type"]); t_side.append(r["side"])
        t_bottom.append(r["bottom"]); t_top.append(r["top"]); t_origin.append(r["origin"])
        t_trigger.append(r["trigger"]); t_eligible.append(r["eligible"]); t_impact.append(r["impact"])
        t_status.append(r["status"]); t_bg.append(r["bg"])

    lines += [
        *pack_array("structX", "int", struct_x),
        *pack_array("structY", "float", struct_y),
        *pack_array("structTxt", "string", struct_txt),
        *pack_array("structColCode", "string", struct_col),
        *pack_array("structLow", "bool", struct_low),
        *pack_array("obLeft", "int", ob_left), *pack_array("obTop", "float", ob_top), *pack_array("obBottom", "float", ob_bottom),
        *pack_array("obFallbackRight", "int", ob_fallback_right), *pack_array("obImpactStamp", "int", ob_impact_stamp),
        *pack_array("obHasImpact", "bool", ob_has_impact), *pack_array("obColCode", "string", ob_col), *pack_array("obAudit", "string", ob_audit),
        *pack_array("rbLeft", "int", rb_left), *pack_array("rbTop", "float", rb_top), *pack_array("rbBottom", "float", rb_bottom),
        *pack_array("rbFallbackRight", "int", rb_fallback_right), *pack_array("rbImpactStamp", "int", rb_impact_stamp),
        *pack_array("rbHasImpact", "bool", rb_has_impact), *pack_array("rbColCode", "string", rb_col), *pack_array("rbAudit", "string", rb_audit),
        *pack_array("fvgLeft", "int", fvg_left), *pack_array("fvgTop", "float", fvg_top), *pack_array("fvgBottom", "float", fvg_bottom),
        *pack_array("fvgFallbackRight", "int", fvg_fallback_right), *pack_array("fvgImpactStamp", "int", fvg_impact_stamp),
        *pack_array("fvgHasImpact", "bool", fvg_has_impact), *pack_array("fvgColCode", "string", fvg_col), *pack_array("fvgAudit", "string", fvg_audit),
        *pack_array("tPoi", "string", t_poi), *pack_array("tId", "string", t_id), *pack_array("tType", "string", t_type),
        *pack_array("tSide", "string", t_side), *pack_array("tBottom", "string", t_bottom), *pack_array("tTop", "string", t_top),
        *pack_array("tOrigin", "string", t_origin), *pack_array("tTrigger", "string", t_trigger), *pack_array("tEligible", "string", t_eligible),
        *pack_array("tImpact", "string", t_impact), *pack_array("tStatus", "string", t_status), *pack_array("tBgCode", "string", t_bg),
        f"var array<int> obImpactX = array.new<int>({len(ob_left)}, na)",
        "for hi = 0 to array.size(obImpactStamp) - 1",
        "    if array.get(obHasImpact, hi)",
        "        hiStamp = array.get(obImpactStamp, hi)",
        "        if na(array.get(obImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "            array.set(obImpactX, hi, time)",
        f"var array<int> rbImpactX = array.new<int>({len(rb_left)}, na)",
        "for hi = 0 to array.size(rbImpactStamp) - 1",
        "    if array.get(rbHasImpact, hi)",
        "        hiStamp = array.get(rbImpactStamp, hi)",
        "        if na(array.get(rbImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "            array.set(rbImpactX, hi, time)",
        f"var array<int> fvgImpactX = array.new<int>({len(fvg_left)}, na)",
        "for hi = 0 to array.size(fvgImpactStamp) - 1",
        "    if array.get(fvgHasImpact, hi)",
        "        hiStamp = array.get(fvgImpactStamp, hi)",
        "        if na(array.get(fvgImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "            array.set(fvgImpactX, hi, time)",
        "if barstate.islast",
        "    if onWeekly",
        "        for i = 0 to array.size(structX) - 1",
        f"            structCol = {colour_ternary('array.get(structColCode, i)')}",
        "            structYY = array.get(structLow, i) ? array.get(structY, i) - lowGap : array.get(structY, i)",
        "            label.new(array.get(structX, i), structYY, array.get(structTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=structCol, size=size.small)",
        "    if onWeekly or onH4 or onFive",
        "        if focusPoi == \"ALL\" or focusPoi == \"OB\"",
        "            for i = 0 to array.size(obLeft) - 1",
        "                obRight = array.get(obHasImpact, i) and not na(array.get(obImpactX, i)) ? array.get(obImpactX, i) : array.get(obFallbackRight, i)",
        f"                obCol = {colour_ternary('array.get(obColCode, i)')}",
        "                box.new(array.get(obLeft, i), array.get(obTop, i), obRight, array.get(obBottom, i), border_color=obCol, border_width=1, bgcolor=na, xloc=xloc.bar_time)",
        "                if array.get(obHasImpact, i)",
        "                    line.new(obRight, array.get(obBottom, i), obRight, array.get(obTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)",
        "        if focusPoi == \"ALL\" or focusPoi == \"RB\"",
        "            for i = 0 to array.size(rbLeft) - 1",
        "                rbRight = array.get(rbHasImpact, i) and not na(array.get(rbImpactX, i)) ? array.get(rbImpactX, i) : array.get(rbFallbackRight, i)",
        f"                rbCol = {colour_ternary('array.get(rbColCode, i)')}",
        "                box.new(array.get(rbLeft, i), array.get(rbTop, i), rbRight, array.get(rbBottom, i), border_color=rbCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "                if array.get(rbHasImpact, i)",
        "                    line.new(rbRight, array.get(rbBottom, i), rbRight, array.get(rbTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)",
        "        if focusPoi == \"ALL\" or focusPoi == \"FVG\"",
        "            for i = 0 to array.size(fvgLeft) - 1",
        "                fvgRight = array.get(fvgHasImpact, i) and not na(array.get(fvgImpactX, i)) ? array.get(fvgImpactX, i) : array.get(fvgFallbackRight, i)",
        f"                fvgCol = {colour_ternary('array.get(fvgColCode, i)')}",
        "                box.new(array.get(fvgLeft, i), array.get(fvgTop, i), fvgRight, array.get(fvgBottom, i), border_color=fvgCol, border_width=1, bgcolor=color.new(fvgCol, 85), xloc=xloc.bar_time)",
        "                fvgMidY = (array.get(fvgTop, i) + array.get(fvgBottom, i)) / 2",
        "                line.new(array.get(fvgLeft, i), fvgMidY, fvgRight, fvgMidY, xloc=xloc.bar_time, color=color.gray, style=line.style_dotted, width=1)",
        "                if array.get(fvgHasImpact, i)",
        "                    line.new(fvgRight, array.get(fvgBottom, i), fvgRight, array.get(fvgTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)",
        "    if onWeekly",
        f"        table.clear(ledger, 0, 0, 10, {table_cap})",
        "        headers = array.from(\"POI\", \"ID\", \"Type\", \"Side\", \"Bottom\", \"Top\", \"Origin (RYD)\", \"Trigger (RYD)\", \"Eligible (RYD)\", \"Impact (RYD)\", \"Status\")",
        "        for c = 0 to array.size(headers) - 1",
        "            table.cell(ledger, c, 0, array.get(headers, c), text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        rowN = 0",
        "        for i = 0 to array.size(tId) - 1",
        f"            if rowN < {table_cap} and (focusPoi == \"ALL\" or array.get(tPoi, i) == focusPoi)",
        "                rowN += 1",
        "                table.cell(ledger, 0, rowN, array.get(tPoi, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 1, rowN, array.get(tId, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 2, rowN, array.get(tType, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 3, rowN, array.get(tSide, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 4, rowN, array.get(tBottom, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 5, rowN, array.get(tTop, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 6, rowN, array.get(tOrigin, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 7, rowN, array.get(tTrigger, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 8, rowN, array.get(tEligible, i), text_color=color.black, bgcolor=na)",
        "                table.cell(ledger, 9, rowN, array.get(tImpact, i), text_color=color.black, bgcolor=na)",
        f"                table.cell(ledger, 10, rowN, array.get(tStatus, i), text_color=color.black, bgcolor=color.new({colour_ternary('array.get(tBgCode, i)')}, 80))",
    ]
    (base / out_name).write_text("\n".join(lines), encoding="utf-8")


def write_report(base: Path, minutes, weeks, e: WeeklyCombinedEngine, args, display_zone: ZoneInfo) -> None:
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)

    ob_counts = {name: 0 for name in ("IFOB", "AOB", "AIFOB", "OOB", "SPENT")}
    for z in e.ob_zones:
        if not z.rejected:
            ob_counts[ob_status(z)] += 1
    ob_reasons = {"IMPACT": 0, "STRAND": 0, "STRUCTURAL_BREACH": 0}
    for z in e.ob_zones:
        if z.stop_reason in ob_reasons:
            ob_reasons[z.stop_reason] += 1

    rb_counts = {name: 0 for name in ("IRB", "ARB", "ORB", "SPENT", "AIRB")}
    for z in e.rb_zones:
        rb_counts[rb_status(z)] += 1
    rb_reasons = {"IMPACT": 0, "STRAND": 0, "STRUCTURAL_BREACH": 0}
    for z in e.rb_zones:
        if z.stop_reason in rb_reasons:
            rb_reasons[z.stop_reason] += 1

    fvg_counts = {name: 0 for name in ("IFVG", "AFVG", "OFVG", "SPENT")}
    for z in e.fvg_zones:
        fvg_counts[fvg_status(z)] += 1
    fvg_reasons = {"IMPACT": 0, "STRAND": 0, "CLOSE_THROUGH": 0, "STRUCTURAL_BREACH": 0}
    for z in e.fvg_zones:
        if z.stop_reason in fvg_reasons:
            fvg_reasons[z.stop_reason] += 1

    rows = [
        "WEEKLY COMBINED (OB+RB+FVG, single-pass) REFERENCE RUN",
        f"input={args.csv_file}", f"price_side={args.price_side}",
        f"weekly_aggregation=Sunday {args.week_close_hour:02d}:00 {args.week_close_zone}",
        f"minute_coverage_utc={wob.iso(minutes[0].t)} to {wob.iso(minutes[-1].t)}",
        f"minutes={len(minutes):,}; weeks={len(weeks):,}; swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}",
        "",
        "OB LIFECYCLE COUNTS", *[f"{k}={v}" for k, v in ob_counts.items()],
        "OB DEATH-CAUSE BREAKDOWN", *[f"{k}={v}" for k, v in ob_reasons.items()],
        "",
        "RB LIFECYCLE COUNTS", *[f"{k}={v}" for k, v in rb_counts.items()],
        "RB DEATH-CAUSE BREAKDOWN", *[f"{k}={v}" for k, v in rb_reasons.items()],
        "",
        "FVG LIFECYCLE COUNTS", *[f"{k}={v}" for k, v in fvg_counts.items()],
        "FVG DEATH-CAUSE BREAKDOWN", *[f"{k}={v}" for k, v in fvg_reasons.items()],
    ]
    (base / "weekly_combined_report.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly OB+RB+FVG single-pass combined reference generator")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=120, choices=range(1, 451))
    p.add_argument("--pine-rbs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-fvgs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--box-body-minutes", type=int, default=60, choices=(1, 5, 15, 30, 60))
    p.add_argument("--origin-first-price", choices=("open", "close"), default="close")
    p.add_argument("--origin-body-offset-minutes", type=int, default=0, choices=range(-240, 241))
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
        engine = WeeklyCombinedEngine(minutes, weeks)
        engine.run()

        # Reuse each POI type's own already-verified ledger/pine writers,
        # unchanged, against this single shared pass's zones -- proves the
        # combined engine's output is visually inspectable exactly like the
        # three standalone generators, not a new drawing path to re-verify.
        ob_view = _OBEngineView(engine)
        wob.write_ledger(base, ob_view, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes)
        wob.write_ob_pine(base, ob_view, args.pine_labels, args.pine_obs, args.pine_table, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes)

        rb_view = _RBEngineView(engine)
        wrb.write_ledger(base, rb_view, display_tz)
        wrb.write_rb_pine(base, rb_view, args.pine_labels, args.pine_rbs, args.pine_table, display_tz)

        fvg_view = _FVGEngineView(engine)
        wfvg.write_ledger(base, fvg_view, display_tz)
        wfvg.write_fvg_pine(base, fvg_view, args.pine_labels, args.pine_fvgs, args.pine_table, display_tz)

        write_combined_pine(base, engine, args.pine_labels, args.pine_obs, args.pine_rbs, args.pine_fvgs, args.pine_table, display_tz)

        write_report(base, minutes, weeks, engine, args, display_tz)
        print("Created:")
        print("  weekly_ob_ledger.csv / weekly_ob_swings.csv / weekly_ob_viewer.pine")
        print("  weekly_rb_ledger.csv / weekly_rb_swings.csv / weekly_rb_viewer.pine")
        print("  weekly_fvg_ledger.csv / weekly_fvg_swings.csv / weekly_fvg_viewer.pine")
        print("  weekly_combined_viewer.pine  <-- ONE chart: shared swings/MSS + all three POI types")
        print("  weekly_combined_report.txt")
        print(f"Processed {len(minutes):,} minutes and {len(weeks)} weeks (single shared pass).")
        print(f"OB zones={len(engine.ob_zones)}  RB zones={len(engine.rb_zones)}  FVG zones={len(engine.fvg_zones)}")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
