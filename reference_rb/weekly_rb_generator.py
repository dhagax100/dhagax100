#!/usr/bin/env python3
"""Weekly FXCM EURUSD RB (Rejection Block) reference generator.

RB counterpart of weekly_ob_generator.py. Same EURUSD 1-minute Bid/Ask CSV,
same Weekly aggregation, and the swing/MSS detection below is copied
VERBATIM from weekly_ob_generator.py's WeeklyOBEngine -- see the block
marked "SWING/MSS DETECTION -- COPIED VERBATIM FROM weekly_ob_generator.py,
DO NOT DIVERGE" below. Only the POI-construction logic differs, per the
RB spec confirmed against RB_Indicator_v1.pine (the standalone Pine
diagnostic the user supplied):

  - An RB zone is the WICK of a single swing-pivot candle, not a scanned
    pick. For a swing high: top=the high (wick tip), bottom=whichever of
    open/close is closer to the high. Mirrored for a swing low.
  - Two types, same trigger MOMENTS as OB: IRB fires at the break-
    confirmation moment (mirrors IFOB -- delayed eligibility, armed on the
    NEXT same-direction swing). ARB fires at MID-ARM (mirrors AOB --
    immediate eligibility, no separate promotion step needed since nothing
    is picked from a range).
  - Anchor candle is always the FAR swing, never the one that directly
    caused the trigger: ARB uses the armed/older swing; IRB uses the
    opposite reference swing (self.last_h / self.last_l, exactly OB's own
    "last_opposite" concept).
  - Bull/bear label is by RAW WICK TYPE, not by which hunt fired it:
    swing-high wick -> always bearish. swing-low wick -> always bullish.
  - Stranding: IRB strands far-side (mirrors IFOB). ARB strands near-side
    (mirrors AOB). Impact is a plain wick touch, eligibility-gated, once
    eligible -- no close-through rule (that's FVG-only, not ported here).
  - Unlike OB, RB has NO promotion machinery (no AIFOB-style pending
    object): ARB is created complete and immediately eligible in one call,
    so there is nothing to track between mid-arm and a later break.
  - Impact/stranding here run at exact M1 precision (first_touch, and the
    earlier-of-touch-vs-strand-event ordering), upgrading the standalone
    Pine diagnostic's week-bar-only check to the same "exact 1m event
    clock" standard already used throughout the OB side of this project.
    This is a deliberate, flagged precision upgrade, not a silent
    reinterpretation of the RB construction rules themselves.

The program writes, next to its own file:
  weekly_rb_ledger.csv       all Weekly RB records and lifecycle timestamps
  weekly_rb_swings.csv       Weekly swings and MSS records (identical facts
                              to weekly_ob_swings.csv -- same engine)
  weekly_rb_viewer.pine      static TradingView viewer for Weekly structure and RBs
  weekly_rb_report.txt       coverage, gaps and lifecycle counts

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
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))
import weekly_ob_generator as wob  # noqa: E402 -- reused for Minute/Week/Event/MSS,
                                    # load_minutes, aggregate_weeks, iso helpers, pine helpers

UTC = timezone.utc
STATE = {0: "IRB", 1: "ARB", 2: "ORB", 3: "SPENT", 4: "AIRB"}


@dataclass
class RBZone:
    id: int
    candle: int          # anchor swing-pivot week index (leftIdx)
    zb: float
    zt: float
    bullish: bool         # by RAW WICK TYPE: swing-low wick=True, swing-high wick=False
    trigger: int          # the hunt's firing week index (break moment for IRB/promoted AIRB, mid-arm for ARB)
    eligible: int          # -1 = not yet eligible (IRB/AIRB only, until its arming swing confirms)
    stop: int              # -1 = extending
    state: int             # 0=IRB, 1=ARB, 2=ORB, 3=SPENT, 4=AIRB (dynamic -- 4 becomes 0 on promotion)
    origin_type: int       # 0=IRB-style (far-side stranding), 1=ARB-style (near-side stranding) --
                            # IMMUTABLE, governs which side strands. AIRB is IRB-style (0) and stays 0
                            # through promotion, unlike `state` which does change.
    pre_spent_state: int
    eligible_time: Optional[datetime] = None
    impact_time: Optional[datetime] = None
    trigger_time: Optional[datetime] = None
    created_state: int = -1              # immutable creation type, for audit (mirrors OB's created_state)
    promotion_from_state: int = -1       # mirrors OB's promotion_from_state; -1 = never promoted
    promotion_time: Optional[datetime] = None


class WeeklyRBEngine:
    """RB counterpart of WeeklyOBEngine. Swing/MSS block is a verbatim copy;
    everything below that is RB-specific POI construction/lifecycle."""

    def __init__(self, minutes: List["wob.Minute"], weeks: List["wob.Week"]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]
        self.events: List["wob.Event"] = []
        self.msses: List["wob.MSS"] = []
        self.zones: List[RBZone] = []
        self.active: List[int] = []
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0
        self.ei = 0
        self.last_h = self.last_l = -1
        # Pending-AIRB trackers, mirroring OB's pend_bull_aifob/pend_bear_aifob:
        # only the LATEST candidate is ever tracked -- an older pending AIRB
        # is abandoned (not deleted, just untracked) the moment a newer
        # same-direction swing confirms and creates a fresh candidate.
        self.pend_bull_airb = self.pend_bear_airb = -1

    # ===================================================================
    # SWING/MSS DETECTION -- COPIED VERBATIM FROM weekly_ob_generator.py's
    # WeeklyOBEngine (event_time, high_first, add_event, and process()'s own
    # swing-detection body below). DO NOT DIVERGE from that file's version;
    # if a swing/MSS bug is ever found, fix it there first, then re-copy.
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
        """Exact M1 minute price first breaks the given armed level within
        week k -- an IRB's real trigger moment (mirrors OB's own
        set_promoted_ifob_trigger crossing search)."""
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > level) if bull else (m.l < level):
                return m.t
        return None

    # ===================================================================
    # RB-SPECIFIC: zone construction (no scanning -- the wick of a known
    # swing-pivot candle, per the confirmed spec).
    # ===================================================================

    def claimed(self, candle: int, bull: bool) -> bool:
        """Mirrors OB's own claimed() guard (every OB zone-creation path
        checks it) -- prevents the same physical candle/direction from
        being stamped with two separate RB zone IDs. Added specifically
        because AIRB raises real collision odds: if an AIRB anchored on
        candle X never gets promoted (stranded/impacted first) and the
        armed extreme later still breaks with self.last_l/last_h still
        unchanged (== X), the normal IRB fallback would otherwise anchor
        on that exact same candle again."""
        return any(z.candle == candle and z.bullish == bull for z in self.zones)

    def add_rb_from_swing(self, idx: int, is_high: bool, trigger_k: int, origin_type: int,
                           trigger_time: Optional[datetime], state: Optional[int] = None) -> int:
        bull_of_this = not is_high
        if self.claimed(idx, bull_of_this):
            return -1
        wk = self.w[idx]
        if is_high:
            zb, zt, bull = max(wk.o, wk.c), wk.h, False
        else:
            zb, zt, bull = wk.l, min(wk.o, wk.c), True
        # ARB: immediate eligibility -- eligible_time MUST be the exact
        # trigger minute (not left blank/defaulting to the week's start),
        # otherwise the impact-touch search below starts from the whole
        # week's open instead of the real trigger moment and can find an
        # "impact" that predates its own trigger. Real bug, caught by
        # exactly that symptom (zone #2: impact 11:04 before trigger
        # 15:07, both same day) -- fixed by always setting eligible_time
        # here at creation, mirroring OB's own AOB convention
        # (try_bull_aob/try_bear_aob always set an exact eligible_time,
        # never leave it to a fallback). IRB/AIRB: armed later (STEP 2).
        actual_state = state if state is not None else origin_type
        eligible = trigger_k if origin_type == 1 and actual_state != 4 else -1
        eligible_time = trigger_time if origin_type == 1 and actual_state != 4 else None
        z = RBZone(len(self.zones) + 1, idx, zb, zt, bull, trigger_k, eligible, -1,
                   actual_state, origin_type, actual_state, trigger_time=trigger_time,
                   eligible_time=eligible_time, created_state=actual_state)
        self.zones.append(z)
        self.active.append(len(self.zones) - 1)
        return len(self.zones) - 1

    def try_bull_arb(self, preg: int, armed_swh: int, new_swl_i: int, k: int, at: Optional[datetime]) -> None:
        # Mirrors try_bull_aob's range + reference-validity gate one-for-one:
        # the armed swing HIGH (the far swing relative to the new swing low
        # that triggered this hunt) must not have been violated since.
        # ARB's trigger MOMENT is MID-ARM itself -- the exact M1 minute the
        # confirming swing event fired (`at`, straight from the Event's own
        # .at field), not the week boundary.
        if preg != 1 or armed_swh < 0:
            return
        if any(self.w[v].h >= self.w[armed_swh].h for v in range(armed_swh + 1, new_swl_i + 1)):
            return
        self.add_rb_from_swing(armed_swh, True, k, 1, at)

    def try_bear_arb(self, preg: int, armed_swl: int, new_swh_i: int, k: int, at: Optional[datetime]) -> None:
        if preg != 2 or armed_swl < 0:
            return
        if any(self.w[v].l <= self.w[armed_swl].l for v in range(armed_swl + 1, new_swh_i + 1)):
            return
        self.add_rb_from_swing(armed_swl, False, k, 1, at)

    # ===================================================================
    # AIRB (Aggressive-InFavor RB) -- mirrors OB's AIFOB exactly, adapted
    # for RB's direct-anchor construction (no scanning needed). AIFOB is a
    # PRE-ARMED, early IFOB candidate created at the same MID-ARM moment an
    # AOB would be tried (while the eventual trigger swing is only ARMED,
    # not yet broken); if that swing later actually breaks, the candidate
    # is PROMOTED in place (same zone ID, trigger facts overwritten with
    # the real break); if a newer same-direction swing confirms first, the
    # old candidate is abandoned (untracked, not deleted) and a fresh one
    # replaces it; if the break never happens, it stays AIRB forever, but
    # is tradable (eligible/impactable) throughout, exactly like AIFOB.
    #
    # RB's IRB anchor is never searched -- it's always the literal
    # opposite-reference swing (self.last_l/self.last_h) at whatever
    # moment that gets evaluated. So AIRB's anchor is simply the swing
    # that JUST confirmed now (new_low/new_high): if no NEWER one forms
    # before the eventual break, that is exactly what self.last_l/last_h
    # will still be when the break happens, so promoting it in place is
    # correct. Gating conditions mirror try_bull_aifob/try_bear_aifob's
    # preconditions one-for-one (translated: no range-search terms needed).
    # ===================================================================

    def try_bull_airb(self, preg: int, had_h: bool, armed_h: int, last_low: int, new_low: int, k: int, at: Optional[datetime]) -> int:
        if preg != 1 or not had_h or armed_h < 0 or last_low < 0 or self.w[k].l < self.w[new_low].l:
            return -1
        return self.add_rb_from_swing(new_low, False, k, 0, at, state=4)

    def try_bear_airb(self, preg: int, had_l: bool, armed_l: int, last_high: int, new_high: int, k: int, at: Optional[datetime]) -> int:
        if preg != 2 or not had_l or armed_l < 0 or last_high < 0 or self.w[k].h > self.w[new_high].h:
            return -1
        return self.add_rb_from_swing(new_high, True, k, 0, at, state=4)

    def consume_break(self, bull: bool, k: int) -> bool:
        # Bull break consumes armed high (regime -> up). If a pending AIRB
        # is still alive (state==4, i.e. not already stranded/impacted),
        # PROMOTE it in place -- same zone, trigger facts overwritten with
        # this real break, eligible reset to re-arm under the new (later)
        # trigger week, mirroring OB's own promotion block exactly
        # (including resetting eligible/eligible_time, since the officially
        # recognized trigger week just changed). Otherwise fall back to
        # the plain IRB creation, exactly OB's own fallback branch
        # (`elif self.last_l >= 0 and not promoted: self.add_ifob(...)`).
        if bull:
            if not self.have_h or self.w[k].h <= self.h_price:
                return False
            if self.regime == 2:
                self.msses.append(wob.MSS(k, self.h_idx, self.h_price, True))
            self.regime = 1
            promoted = False
            if 0 <= self.pend_bull_airb < len(self.zones) and self.zones[self.pend_bull_airb].state == 4:
                z = self.zones[self.pend_bull_airb]
                z.promotion_from_state = z.state
                z.state = 0
                z.trigger = k
                z.trigger_time = self.break_time(k, True, self.h_price)
                z.promotion_time = self.w[k].start
                z.eligible = -1
                z.eligible_time = None
                promoted = True
            self.pend_bull_airb = -1
            if not promoted and self.last_l >= 0:
                self.add_rb_from_swing(self.last_l, False, k, 0, self.break_time(k, True, self.h_price))  # IRB, bullish (low wick)
            self.have_h = False
            return True
        if not self.have_l or self.w[k].l >= self.l_price:
            return False
        if self.regime == 1:
            self.msses.append(wob.MSS(k, self.l_idx, self.l_price, False))
        self.regime = 2
        promoted = False
        if 0 <= self.pend_bear_airb < len(self.zones) and self.zones[self.pend_bear_airb].state == 4:
            z = self.zones[self.pend_bear_airb]
            z.promotion_from_state = z.state
            z.state = 0
            z.trigger = k
            z.trigger_time = self.break_time(k, False, self.l_price)
            z.promotion_time = self.w[k].start
            z.eligible = -1
            z.eligible_time = None
            promoted = True
        self.pend_bear_airb = -1
        if not promoted and self.last_h >= 0:
            self.add_rb_from_swing(self.last_h, True, k, 0, self.break_time(k, False, self.l_price))  # IRB, bearish (high wick)
        self.have_l = False
        return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True
                self.h_price = ev.price
                self.h_idx = ev.swing
                self.pend_bull_airb = -1
                self.try_bear_arb(preg, armed_l, ev.swing, k, ev.at)
                if self.pend_bear_airb < 0:
                    self.pend_bear_airb = self.try_bear_airb(preg, self.have_l, armed_l, self.last_h, ev.swing, k, ev.at)
            else:
                self.have_l = True
                self.l_price = ev.price
                self.l_idx = ev.swing
                self.pend_bear_airb = -1
                self.try_bull_arb(preg, armed_h, ev.swing, k, ev.at)
                if self.pend_bull_airb < 0:
                    self.pend_bull_airb = self.try_bull_airb(preg, self.have_h, armed_h, self.last_l, ev.swing, k, ev.at)

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        # STEP 2: arm swings + IRB eligibility. Bullish IRB zones (anchored
        # on a swing LOW) become eligible the moment the NEXT swing HIGH
        # confirms -- identical direction convention to OB's own
        # finish_events_and_lifecycle (z.bullish zones arm on kind==0).
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
                    if z.bullish and z.state in (0, 4) and z.eligible < 0 and k > z.trigger:
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
                    if not z.bullish and z.state in (0, 4) and z.eligible < 0 and k > z.trigger:
                        z.eligible = k
                        z.eligible_time = ev.at
            self.ei += 1

        # STEP 3: lifecycle -- IMPACT + STRANDING only (no close-through
        # rule, that's FVG-only). An already-ORB zone can still later be
        # impacted (price wicks back in); it can never re-strand. Same
        # "resolve by exact M1 timestamp, earlier wins" ordering already
        # used by OB's own finish_events_and_lifecycle.
        for zidx in self.active:
            z = self.zones[zidx]
            if z.state == 3:
                continue
            touch = None
            if z.eligible >= 0 and k >= z.eligible:
                touch = self.first_touch(z.eligible_time or self.w[k].start, k, z.bullish, z.zb, z.zt)
            strand_ev = None
            if z.state in (0, 1, 4) and z.eligible != -1:
                is_irb = z.origin_type != 1
                for ev in self.events[before:total]:
                    if ev.confirm != k:
                        continue
                    stranded = False
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
                        strand_ev = ev
                        break
            if touch and strand_ev is not None and strand_ev.at is not None and strand_ev.at < touch:
                z.state = 2
            elif touch:
                z.pre_spent_state = z.state
                z.state = 3
                z.stop = k
                z.impact_time = touch
            elif strand_ev is not None:
                z.state = 2

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
        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)):
            self.process(k)


def status(z: RBZone) -> str:
    return STATE[z.pre_spent_state if z.state == 3 else z.state]


def write_ledger(base: Path, engine: WeeklyRBEngine, display_zone: ZoneInfo) -> None:
    with (base / "weekly_rb_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "type", "side", "zb", "zt", "origin_type", "origin_week_utc", "origin_week_riyadh",
                   "origin_open", "origin_high", "origin_low", "origin_close",
                   "trigger_week_utc", "trigger_week_riyadh",
                   "trigger_time_utc", "trigger_time_riyadh",
                   "eligible_time_utc", "eligible_time_riyadh",
                   "impact_time_utc", "impact_time_riyadh", "status",
                   "created_type", "promotion_from_type", "promotion_time_utc", "promotion_time_riyadh"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for z in engine.zones:
            wk = engine.w[z.candle]
            trig_wk = engine.w[z.trigger] if 0 <= z.trigger < len(engine.w) else None
            wr.writerow(dict(
                id=z.id, type=status(z), side="BUY" if z.bullish else "SELL",
                zb=f"{z.zb:.5f}", zt=f"{z.zt:.5f}",
                origin_type="IRB-style (far-side stranding)" if z.origin_type == 0 else "ARB-style (near-side stranding)",
                origin_week_utc=wob.iso(wk.start), origin_week_riyadh=wob.display_iso(wk.start, display_zone),
                origin_open=f"{wk.o:.5f}", origin_high=f"{wk.h:.5f}", origin_low=f"{wk.l:.5f}", origin_close=f"{wk.c:.5f}",
                trigger_week_utc=wob.iso(trig_wk.start) if trig_wk else "", trigger_week_riyadh=wob.display_iso(trig_wk.start, display_zone) if trig_wk else "",
                trigger_time_utc=wob.iso(z.trigger_time), trigger_time_riyadh=wob.display_iso(z.trigger_time, display_zone),
                eligible_time_utc=wob.iso(z.eligible_time), eligible_time_riyadh=wob.display_iso(z.eligible_time, display_zone),
                impact_time_utc=wob.iso(z.impact_time), impact_time_riyadh=wob.display_iso(z.impact_time, display_zone),
                status=status(z),
                created_type=STATE[z.created_state] if z.created_state >= 0 else "",
                promotion_from_type=STATE[z.promotion_from_state] if z.promotion_from_state >= 0 else "",
                promotion_time_utc=wob.iso(z.promotion_time), promotion_time_riyadh=wob.display_iso(z.promotion_time, display_zone),
            ))
    with (base / "weekly_rb_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["record", "kind", "origin_utc", "origin_riyadh", "confirm_utc", "confirm_riyadh", "price"])
        for e in engine.events:
            wr.writerow(["SWING", "HIGH" if e.kind == 0 else "LOW",
                         wob.iso(engine.w[e.swing].start), wob.display_iso(engine.w[e.swing].start, display_zone),
                         wob.iso(engine.w[e.confirm].start), wob.display_iso(engine.w[e.confirm].start, display_zone),
                         f"{e.price:.5f}"])
        for x in engine.msses:
            wr.writerow(["MSS_UP" if x.up else "MSS_DOWN", "",
                         wob.iso(engine.w[x.broken].start), wob.display_iso(engine.w[x.broken].start, display_zone),
                         wob.iso(engine.w[x.at].start), wob.display_iso(engine.w[x.at].start, display_zone),
                         f"{x.price:.5f}"])


def rb_colour(z: RBZone) -> str:
    d = z.pre_spent_state if z.state == 3 else z.state
    if d == 2:
        return "color.red"
    if d == 1:
        return "color.green"
    if d == 4:
        return "color.orange"  # AIRB, mirrors OB's AIFOB=orange convention
    return "color.blue" if z.bullish else "color.black"


def write_rb_pine(base: Path, engine: WeeklyRBEngine, label_cap: int, rb_cap: int, table_cap: int,
                   display_zone: ZoneInfo, extra_lines: Optional[List[str]] = None, out_name: str = "weekly_rb_viewer.pine") -> None:
    """Array-packed from the start (see the CE10295/CE10205/CE10013 lesson
    already recorded in docs/TRADING_SYSTEM_HANDOFF.md's OB history): one
    statement per FIELD, one runtime for-loop to draw, regardless of how
    many RB zones exist. Never unroll one label.new/box.new per item."""
    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    shown = engine.zones[-rb_cap:]
    table_zones = engine.zones[-table_cap:][::-1]
    max_rb_offset = max(1, len(engine.zones))

    def arr(kind: str, values: List[str]) -> str:
        return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"

    lines = [
        "//@version=6",
        "indicator(\"FXCM Weekly RB - Python Reference\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. Swing/MSS detection is identical to the OB reference engine.",
        "// RB zone = the wick of a single swing-pivot candle (IRB/ARB per the confirmed spec).",
        "float lowGap = ta.atr(14) * 0.08",
        "bool inspectOneRB = input.bool(false, \"Inspect one RB only\", group=\"RB inspection\")",
        f"int rbFromLast = input.int(1, \"RB from last\", minval=1, maxval={max_rb_offset}, group=\"RB inspection\", tooltip=\"1 = latest RB, 2 = the RB before it, and so on.\")",
        "var table ledger = table.new(position.top_right, 10, 21, border_width=1)",
        "bool onWeekly = timeframe.period == \"1W\"",
    ]

    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(wob.pine_time(engine.w[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▲\""); struct_col.append("color.blue"); struct_low.append("false")
    for e in sl:
        struct_x.append(wob.pine_time(engine.w[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▼\""); struct_col.append("color.black"); struct_low.append("true")
    for m in ms:
        struct_x.append(wob.pine_time(engine.w[m.broken].start))
        struct_y.append(f"{m.price:.5f}")
        struct_txt.append("\"✕\""); struct_col.append("color.blue" if m.up else "color.black")
        struct_low.append("false" if m.up else "true")

    # Resolve each static M1 impact into the opening time of whichever
    # Weekly bar actually CONTAINS it -- exactly OB's impact_x_<id> watcher
    # mechanism (write_ob_pine in weekly_ob_generator.py), ported here after
    # a real bug: passing a raw, bar-unaligned M1 timestamp straight to
    # box.new/line.new's xloc.bar_time lets Pine snap it to the NEXT bar's
    # open instead of the bar the impact actually happened in -- confirmed
    # by the user on the real chart (box/impact-line stopping one candle
    # late). `impact_x_<id>` is a `var int`, updated once time actually
    # reaches the impact stamp's own containing bar, so it always resolves
    # to that bar's own open -- never a lookahead, never the next bar.
    right_edge = engine.m[-1].t + timedelta(days=365)
    impact_vars: Dict[int, str] = {}
    impact_watchers: List[str] = []
    for z in shown:
        if z.impact_time is not None:
            name = f"impact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = wob.pine_time(z.impact_time)
            impact_watchers += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]

    rb_left, rb_top, rb_bottom, rb_right_expr, rb_col, rb_rank, rb_audit = [], [], [], [], [], [], []
    for z in shown:
        wk = engine.w[z.candle]
        fallback_right = z.impact_time or (engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else right_edge)
        right = f"(na({impact_vars[z.id]}) ? {wob.pine_time(fallback_right)} : {impact_vars[z.id]})" if z.impact_time is not None else wob.pine_time(fallback_right)
        rank_from_last = len(engine.zones) - z.id + 1
        rb_left.append(wob.pine_time(wk.start)); rb_top.append(f"{z.zt:.5f}"); rb_bottom.append(f"{z.zb:.5f}")
        rb_right_expr.append(right); rb_col.append(rb_colour(z)); rb_rank.append(str(rank_from_last))
        rb_audit.append(f"\"#{z.id} {status(z)} {'BUY' if z.bullish else 'SELL'}\"")

    t_id, t_type, t_side, t_bottom, t_top, t_origin, t_trigger, t_eligible, t_impact, t_status, t_bg = ([] for _ in range(11))
    for z in table_zones:
        wk = engine.w[z.candle]
        t_id.append(f"\"#{z.id}\""); t_type.append(f"\"{status(z)}\"")
        t_side.append(f"\"{'BUY' if z.bullish else 'SELL'}\"")
        t_bottom.append(f"\"{z.zb:.5f}\""); t_top.append(f"\"{z.zt:.5f}\"")
        t_origin.append(f"\"{wob.pine_text(wob.display_iso(wk.start, display_zone))}\"")
        t_trigger.append(f"\"{wob.pine_text(wob.display_iso(z.trigger_time, display_zone))}\"")
        t_eligible.append(f"\"{wob.pine_text(wob.display_iso(z.eligible_time, display_zone))}\"")
        t_impact.append(f"\"{wob.pine_text(wob.display_iso(z.impact_time, display_zone))}\"")
        t_status.append(f"\"{status(z)}\"")
        t_bg.append(f"color.new({rb_colour(z)}, 80)")

    lines += [
        f"var array<int> structX = {arr('int', struct_x)}",
        f"var array<float> structY = {arr('float', struct_y)}",
        f"var array<string> structTxt = {arr('string', struct_txt)}",
        f"var array<color> structCol = {arr('color', struct_col)}",
        f"var array<bool> structLow = {arr('bool', struct_low)}",
        f"var array<int> rbLeft = {arr('int', rb_left)}",
        f"var array<float> rbTop = {arr('float', rb_top)}",
        f"var array<float> rbBottom = {arr('float', rb_bottom)}",
        f"var array<color> rbCol = {arr('color', rb_col)}",
        f"var array<int> rbRank = {arr('int', rb_rank)}",
        f"var array<string> rbAudit = {arr('string', rb_audit)}",
        f"var array<string> tId = {arr('string', t_id)}",
        f"var array<string> tType = {arr('string', t_type)}",
        f"var array<string> tSide = {arr('string', t_side)}",
        f"var array<string> tBottom = {arr('string', t_bottom)}",
        f"var array<string> tTop = {arr('string', t_top)}",
        f"var array<string> tOrigin = {arr('string', t_origin)}",
        f"var array<string> tTrigger = {arr('string', t_trigger)}",
        f"var array<string> tEligible = {arr('string', t_eligible)}",
        f"var array<string> tImpact = {arr('string', t_impact)}",
        f"var array<string> tStatus = {arr('string', t_status)}",
        f"var array<color> tBg = {arr('color', t_bg)}",
        *impact_watchers,
        "if barstate.islast",
        "    if onWeekly",
        "        for i = 0 to array.size(structX) - 1",
        "            structYY = array.get(structLow, i) ? array.get(structY, i) - lowGap : array.get(structY, i)",
        "            label.new(array.get(structX, i), structYY, array.get(structTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=array.get(structCol, i), size=size.small)",
        f"        array<int> rbRight = {arr('int', rb_right_expr)}",
        "        for i = 0 to array.size(rbLeft) - 1",
        "            if not inspectOneRB or rbFromLast == array.get(rbRank, i)",
        "                box.new(array.get(rbLeft, i), array.get(rbTop, i), array.get(rbRight, i), array.get(rbBottom, i), border_color=array.get(rbCol, i), border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "        table.clear(ledger, 0, 0, 9, 20)",
        "        table.cell(ledger, 0, 0, \"W RB\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 1, 0, \"Type\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 5, 0, \"Origin (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 6, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 7, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 8, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 9, 0, \"Status\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        for i = 0 to array.size(tId) - 1",
        "            table.cell(ledger, 0, i + 1, array.get(tId, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 1, i + 1, array.get(tType, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 2, i + 1, array.get(tSide, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 3, i + 1, array.get(tBottom, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 4, i + 1, array.get(tTop, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 5, i + 1, array.get(tOrigin, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 6, i + 1, array.get(tTrigger, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 7, i + 1, array.get(tEligible, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 8, i + 1, array.get(tImpact, i), text_color=color.black, bgcolor=na)",
        "            table.cell(ledger, 9, i + 1, array.get(tStatus, i), text_color=color.black, bgcolor=array.get(tBg, i))",
    ]
    if extra_lines:
        lines += extra_lines
    lines.append("")
    (base / out_name).write_text("\n".join(lines), encoding="utf-8")


def write_report(base: Path, minutes: List["wob.Minute"], weeks: List["wob.Week"], warnings: List[str], e: WeeklyRBEngine, args: argparse.Namespace, display_zone: ZoneInfo) -> None:
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)
    counts = {name: 0 for name in ("IRB", "ARB", "ORB", "SPENT", "AIRB")}
    for z in e.zones:
        counts[status(z)] += 1
    rows = [
        "WEEKLY RB REFERENCE RUN", f"input={args.csv_file}", f"price_side={args.price_side}",
        f"weekly_aggregation=Sunday {args.week_close_hour:02d}:00 {args.week_close_zone}",
        f"minute_coverage_utc={wob.iso(minutes[0].t)} to {wob.iso(minutes[-1].t)}",
        f"minute_coverage_riyadh={wob.display_iso(minutes[0].t, display_zone)} to {wob.display_iso(minutes[-1].t, display_zone)}",
        f"minutes={len(minutes):,}; weeks={len(weeks):,}; swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}",
        "", "RB LIFECYCLE COUNTS", *[f"{name}={counts[name]}" for name in counts],
        "", "Colors: IRB BUY=blue; IRB SELL=black; ARB=green (fixed); ORB=red (fixed).",
    ]
    if warnings:
        rows += ["", "WARNINGS"] + warnings[:50]
    (base / "weekly_rb_report.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locked Weekly structure RB reference generator")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-rbs", type=int, default=150, choices=range(1, 451))
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
        engine = WeeklyRBEngine(minutes, weeks)
        engine.run()
        write_ledger(base, engine, display_tz)
        write_rb_pine(base, engine, args.pine_labels, args.pine_rbs, args.pine_table, display_tz)
        write_report(base, minutes, weeks, warnings, engine, args, display_tz)
        print("Created:")
        print("  weekly_rb_ledger.csv")
        print("  weekly_rb_swings.csv")
        print("  weekly_rb_viewer.pine")
        print("  weekly_rb_report.txt")
        print(f"Processed {len(minutes):,} minutes and {len(weeks)} weeks. The Pine viewer contains Weekly structure and the RB lifecycle.")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
