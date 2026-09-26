#!/usr/bin/env python3
"""Weekly FXCM EURUSD FVG (Fair Value Gap) reference generator.

FVG counterpart of weekly_ob_generator.py / weekly_rb_generator.py. Same
EURUSD 1-minute Bid/Ask CSV, same Weekly aggregation, and the swing/MSS
detection below is copied VERBATIM from weekly_ob_generator.py's
WeeklyOBEngine -- see the block marked "SWING/MSS DETECTION -- COPIED
VERBATIM" below. Only the POI-construction logic differs, per the FVG spec
confirmed against FVG_Indicator_v1.pine (the standalone Pine diagnostic the
user supplied):

  - An FVG zone is a classic 3-candle gap: candle1 and candle3 either side
    of a middle candle, where candle1's high sits below candle3's low
    (bullish gap: zb=high[c1], zt=low[c3]) or candle1's low sits above
    candle3's high (bearish gap: zb=high[c3], zt=low[c1]). Unlike RB
    (a single anchor candle's wick), THIS is a genuine range scan: every
    qualifying 3-candle window in the relevant range becomes its own zone,
    not just one "best" pick.
  - Two types: IFVG (continuation-only, mirrors IFOB/IRB's delayed
    eligibility -- armed on the NEXT same-direction swing) is created (a)
    at the same break-confirmation moment IFOB/IRB fire from, scanning the
    exact same lo/hi range OB's own add_ifob uses (min/max of the opposite
    reference swing, the break bar, and the just-broken swing), AND (b)
    continuously, one more candle at a time, for as long as the current
    regime persists (the pine source's own "STEP 1b" continuous scan --
    genuinely new, no OB/RB analog, confirmed against the pine source as
    the ground truth). AFVG (Anticipatory, mirrors AOB) is created at
    MID-ARM, scanning the SAME range an AOB/ARB is picked from, but for the
    gap the retracement leg ITSELF leaves behind (its own direction, not a
    counter-trend wiggle) -- immediate eligibility, gated by a per-gap
    near-side straddle guard (both boundary candles' wicks must clear the
    armed swing's price).
  - Bull/bear label is by gap SHAPE (which side the 3 candles opened the
    gap on), not by a fixed wick-type convention like RB.
  - **Stranding: ONE UNIVERSAL CONDITION for every zone type (IFVG and
    AFVG alike)** -- `(bullish and a swing LOW confirms above zt) or
    (bearish and a swing HIGH confirms below zb)`. This is deliberately
    NOT origin-branched. The supplied FVG_Indicator_v1.pine DOES branch by
    origin (an `isIfvgLike` check with a separate, swapped condition for
    AFVG) -- this is the EXACT SAME invented/wrong condition RB had before
    the 2026-09-24 fix (see docs_rb/RB_RULES_LEARNED.md: "ARB/ORB stranding
    used the wrong (near-side) condition"). Confirmed directly: OB's own
    strand check (weekly_ob_generator.py) uses one single condition for
    every OB type, no origin branching at all -- the pine source's AFVG
    branch never matches that reference. Not ported here; the single
    unified condition is used for both IFVG and AFVG from the start, per
    explicit user direction: "we had wrong stranding rules in RB. I do not
    want that mistake now."
  - **Close-through invalidation, IFVG only** (origin 0, still state 0):
    a genuinely NEW rule, absent from both OB and RB, confirmed directly
    against the pine source and accepted by the user before porting. Once
    eligible, if the containing week's own CLOSE lands back through the
    gap's far edge (bullish: close < zb; bearish: close > zt), the zone is
    immediately SPENT -- a real continuation failure, not a POI-breach
    rule salvage. AFVG is explicitly exempt (it starts on the "wrong" side
    of price by design; this check would fire immediately on eligibility
    every time otherwise -- AFVG's only "left behind for good" signal is
    stranding, same as AOB/ARB).
  - Impact is a plain wick touch, eligibility-gated (any wick reaching
    into the gap ends it, regardless of state -- matches the pine source:
    an already-OFVG zone can still later be impacted, it can never
    re-strand).
  - Same-week ordering when impact, stranding and close-through could all
    apply: resolved by exact M1/event timestamp, earliest wins -- the same
    discipline already used throughout OB/RB, extended to a third
    candidate. A close-through's own "timestamp" is inherently the week's
    own scheduled close (the LATEST possible moment in that week), so it
    can only ever win when no impact or stranding happened earlier that
    same week -- not a new rule, just the existing ordering discipline
    applied one more time.
  - No promotion machinery at all (no AIFOB/AIRB-style pending object):
    the pine source has no such state for FVG. `origin` is stamped once,
    forever, at creation.
  - A `claimed()` dedupe guard (same purpose as RB's own, see
    docs_rb/RB_RULES_LEARNED.md) prevents the same physical (leftIdx,
    bullish) gap from being stamped with two zone IDs if it's reachable by
    more than one scan (e.g. the continuous per-week scan re-finding a
    window a break-triggered range scan already created).
  - Deliberate precision upgrade, flagged not hidden, continuing the SAME
    upgrade already applied throughout OB and RB: the standalone pine
    diagnostic orders same-bar break-processing by the bar's own
    open/close direction (`kBull`) and has no sub-bar M1 precision at all
    (any timeframe it runs on is its only clock). This engine uses the
    same `high_first()` exact-M1-ordering already used for swing/MSS
    detection to also order break-processing here, and resolves
    impact/strand/close-through by exact M1/event timestamp rather than
    fixed code-order priority. The FVG *construction* rules themselves
    (which candles, which shape, which side strands, the close-through
    rule) are unchanged from the pine spec -- only timing precision is
    upgraded, exactly as already documented for RB.

The program writes, next to its own file:
  weekly_fvg_ledger.csv       all Weekly FVG records and lifecycle timestamps
  weekly_fvg_swings.csv       Weekly swings and MSS records (identical facts
                               to weekly_ob_swings.csv / weekly_rb_swings.csv
                               -- same engine)
  weekly_fvg_viewer.pine      static TradingView viewer for Weekly structure and FVGs
  weekly_fvg_report.txt       coverage, gaps and lifecycle counts

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
STATE = {0: "IFVG", 1: "AFVG", 2: "OFVG", 3: "SPENT"}


@dataclass
class FVGZone:
    id: int
    left: int             # leftIdx: candle1 of the 3-candle gap (week index)
    zb: float
    zt: float
    bullish: bool
    trigger: int           # the hunt's firing week index (break moment for IFVG, mid-arm for AFVG)
    eligible: int           # -1 = not yet eligible (IFVG only, until its arming swing confirms)
    stop: int               # -1 = extending
    state: int              # 0=IFVG, 1=AFVG, 2=OFVG, 3=SPENT
    origin: int              # 0=IFVG-style, 1=AFVG-style -- IMMUTABLE, decides close-through eligibility
    pre_spent_state: int
    eligible_time: Optional[datetime] = None
    impact_time: Optional[datetime] = None
    trigger_time: Optional[datetime] = None
    stop_reason: str = ""    # "IMPACT" | "CLOSE_THROUGH" | "" (still open, or stranded -- see `state`)


class WeeklyFVGEngine:
    """FVG counterpart of WeeklyOBEngine/WeeklyRBEngine. Swing/MSS block is a
    verbatim copy; everything below that is FVG-specific POI construction/
    lifecycle."""

    def __init__(self, minutes: List["wob.Minute"], weeks: List["wob.Week"]):
        self.m, self.w = minutes, weeks
        self.mt = [x.t for x in minutes]
        self.events: List["wob.Event"] = []
        self.msses: List["wob.MSS"] = []
        self.zones: List[FVGZone] = []
        self.active: List[int] = []
        self._claimed_pairs: set = set()  # (left, bull) -- see claimed()
        self.sw_highs: List[int] = []
        self.sw_lows: List[int] = []
        self.peak = self.trough = 0
        self.have_h = self.have_l = False
        self.h_price = self.l_price = 0.0
        self.h_idx = self.l_idx = 0
        self.regime = 0
        self.ei = 0
        self.last_h = self.last_l = -1
        self.fvg_bull_scan_upto = -1
        self.fvg_bear_scan_upto = -1

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
        week k -- an IFVG's real trigger moment (mirrors OB's/RB's own
        break-time resolvers)."""
        wk = self.w[k]
        for m in self.m[wk.first:wk.last]:
            if (m.h > level) if bull else (m.l < level):
                return m.t
        return None

    # ===================================================================
    # FVG-SPECIFIC: zone construction (genuine 3-candle range scan, per the
    # confirmed pine spec -- unlike RB's single-wick anchor).
    # ===================================================================

    def claimed(self, left: int, bull: bool) -> bool:
        """Same purpose as RB's own claimed() guard: prevents the same
        physical (leftIdx, direction) gap from being stamped with two
        separate zone IDs if more than one scan can reach it (e.g. the
        continuous per-week scan re-finding a window a break-triggered
        range scan already created)."""
        return (left, bull) in self._claimed_pairs

    def add_fvg(self, left: int, zb: float, zt: float, bull: bool, trigger_k: int,
                origin: int, trigger_time: Optional[datetime]) -> int:
        if self.claimed(left, bull):
            return -1
        eligible = trigger_k if origin == 1 else -1
        eligible_time = trigger_time if origin == 1 else None
        z = FVGZone(len(self.zones) + 1, left, zb, zt, bull, trigger_k, eligible, -1,
                    origin, origin, origin, trigger_time=trigger_time, eligible_time=eligible_time)
        self.zones.append(z)
        self.active.append(len(self.zones) - 1)
        self._claimed_pairs.add((left, bull))
        return len(self.zones) - 1

    def try_create_ifvgs(self, lo: int, hi: int, bullish: bool, trigger_k: int, trigger_time: Optional[datetime]) -> None:
        if hi < lo + 2:
            return
        for c3 in range(lo + 2, hi + 1):
            c1 = c3 - 2
            if bullish:
                h1, l3 = self.w[c1].h, self.w[c3].l
                if h1 < l3:
                    self.add_fvg(c1, h1, l3, True, trigger_k, 0, trigger_time)
            else:
                l1, h3 = self.w[c1].l, self.w[c3].h
                if l1 > h3:
                    self.add_fvg(c1, h3, l1, False, trigger_k, 0, trigger_time)

    def try_create_afvgs(self, lo: int, hi: int, bullish: bool, trigger_k: int,
                         guard_price: float, trigger_time: Optional[datetime]) -> None:
        if hi < lo + 2:
            return
        for c3 in range(lo + 2, hi + 1):
            c1 = c3 - 2
            if bullish:
                l1, h3 = self.w[c1].l, self.w[c3].h
                if l1 > h3:
                    l3 = self.w[c3].l
                    if l1 > guard_price and l3 > guard_price:
                        self.add_fvg(c1, h3, l1, True, trigger_k, 1, trigger_time)
            else:
                h1, l3 = self.w[c1].h, self.w[c3].l
                if h1 < l3:
                    h3 = self.w[c3].h
                    if h1 < guard_price and h3 < guard_price:
                        self.add_fvg(c1, h1, l3, False, trigger_k, 1, trigger_time)

    def try_bull_afvg(self, preg: int, armed_swh: int, new_swl_i: int, new_swl_p: float, k: int, at: Optional[datetime]) -> None:
        # Mirrors tryBullAFVG's range + reference-validity gate one-for-one.
        if preg != 1 or armed_swh < 0:
            return
        if any(self.w[v].h >= self.w[armed_swh].h for v in range(armed_swh + 1, new_swl_i + 1)):
            return
        swl_ext = new_swl_i + 1 if new_swl_i + 1 <= k - 1 else new_swl_i
        lo = max(0, min(armed_swh - 1, swl_ext))
        hi = max(armed_swh - 1, swl_ext)
        self.try_create_afvgs(lo, hi, True, k, new_swl_p, at)

    def try_bear_afvg(self, preg: int, armed_swl: int, new_swh_i: int, new_swh_p: float, k: int, at: Optional[datetime]) -> None:
        if preg != 2 or armed_swl < 0:
            return
        if any(self.w[v].l <= self.w[armed_swl].l for v in range(armed_swl + 1, new_swh_i + 1)):
            return
        swh_ext = new_swh_i + 1 if new_swh_i + 1 <= k - 1 else new_swh_i
        lo = max(0, min(armed_swl - 1, swh_ext))
        hi = max(armed_swl - 1, swh_ext)
        self.try_create_afvgs(lo, hi, False, k, new_swh_p, at)

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
                self.try_create_ifvgs(lo, hi, True, k, bt)
                self.fvg_bull_scan_upto = hi
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
            self.try_create_ifvgs(lo, hi, False, k, bt)
            self.fvg_bear_scan_upto = hi
        self.have_l = False
        return True

    def mid_arm(self, k: int, preg: int, armed_h: int, armed_l: int) -> None:
        for ev in [e for e in self.events[self.ei:] if e.confirm == k]:
            if ev.kind == 0:
                self.have_h = True
                self.h_price = ev.price
                self.h_idx = ev.swing
                self.try_bear_afvg(preg, armed_l, ev.swing, ev.price, k, ev.at)
            else:
                self.have_l = True
                self.l_price = ev.price
                self.l_idx = ev.swing
                self.try_bull_afvg(preg, armed_h, ev.swing, ev.price, k, ev.at)

    def finish_events_and_lifecycle(self, k: int, before: int, total: int, consumed_h: bool, consumed_l: bool) -> None:
        # STEP 2: arm IFVG eligibility. Bullish IFVG zones (anchored on a
        # bullish gap) become eligible the moment the NEXT swing HIGH
        # confirms -- identical direction convention to OB/RB's own
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

        # STEP 3: lifecycle -- IMPACT, CLOSE-THROUGH (IFVG only), STRANDING
        # (one universal condition, both types). Same-week ordering
        # resolved by exact M1/event timestamp, earliest wins -- close-
        # through's own timestamp (the week's own scheduled close) can only
        # win when no impact or stranding happened earlier the same week,
        # so checking it last is not just convenient, it's the objectively
        # correct order.
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
            if touch and strand_ev is not None and strand_ev.at is not None and strand_ev.at < touch:
                z.state = 2
            elif touch:
                z.pre_spent_state = z.state
                z.state = 3
                z.stop = k
                z.impact_time = touch
                z.stop_reason = "IMPACT"
            elif strand_ev is not None:
                z.state = 2
            elif z.origin == 0 and z.state == 0 and z.eligible != -1 and k >= z.eligible:
                c = self.w[k].c
                closed_through = (c < z.zb) if z.bullish else (c > z.zt)
                if closed_through:
                    z.pre_spent_state = z.state
                    z.state = 3
                    z.stop = k
                    z.impact_time = self.w[k].end
                    z.stop_reason = "CLOSE_THROUGH"

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

        # STEP 1b: continuous IFVG scan -- keeps checking the newest
        # 3-candle window every week for as long as the current regime
        # persists, not just once at the break moment. Genuinely new, no
        # OB/RB analog -- confirmed against the pine source.
        if self.regime == 1 and k >= 2 and k > self.fvg_bull_scan_upto:
            h1c, l3c = self.w[k - 2].h, self.w[k].l
            if h1c < l3c:
                self.add_fvg(k - 2, h1c, l3c, True, k, 0, self.w[k].start)
            self.fvg_bull_scan_upto = k
        if self.regime == 2 and k >= 2 and k > self.fvg_bear_scan_upto:
            l1c, h3c = self.w[k - 2].l, self.w[k].h
            if l1c > h3c:
                self.add_fvg(k - 2, h3c, l1c, False, k, 0, self.w[k].start)
            self.fvg_bear_scan_upto = k

        self.finish_events_and_lifecycle(k, before, total, c_h, c_l)

    def run(self) -> None:
        for k in range(len(self.w)):
            self.process(k)


def status(z: FVGZone) -> str:
    return STATE[z.pre_spent_state if z.state == 3 else z.state]


def write_ledger(base: Path, engine: WeeklyFVGEngine, display_zone: ZoneInfo) -> None:
    with (base / "weekly_fvg_ledger.csv").open("w", newline="", encoding="utf-8") as f:
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
                origin_type="IFVG-style (close-through eligible)" if z.origin == 0 else "AFVG-style",
                left_week_utc=wob.iso(wk.start), left_week_riyadh=wob.display_iso(wk.start, display_zone),
                trigger_time_utc=wob.iso(z.trigger_time), trigger_time_riyadh=wob.display_iso(z.trigger_time, display_zone),
                eligible_time_utc=wob.iso(z.eligible_time), eligible_time_riyadh=wob.display_iso(z.eligible_time, display_zone),
                impact_time_utc=wob.iso(z.impact_time), impact_time_riyadh=wob.display_iso(z.impact_time, display_zone),
                stop_reason=z.stop_reason,
                status=status(z),
            ))
    with (base / "weekly_fvg_swings.csv").open("w", newline="", encoding="utf-8") as f:
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


def fvg_colour(z: FVGZone) -> str:
    d = z.pre_spent_state if z.state == 3 else z.state
    if d == 2:
        return "color.red"
    if d == 1:
        return "color.green"
    return "color.blue" if z.bullish else "color.black"


def pine_epoch(t: datetime) -> str:
    """Bare UTC epoch-millisecond integer literal -- see weekly_rb_generator.py's
    own pine_epoch docstring for the full CE10295 reasoning; duplicated here
    unchanged."""
    return str(int(t.astimezone(timezone.utc).timestamp() * 1000))


_PACK_NA = "§NA§"
_PACK_SEP = "|"


def pack_array(var_name: str, kind: str, values: list) -> List[str]:
    """Duplicated unchanged from weekly_rb_generator.py's own pack_array --
    see its docstring for the full CE10295/CE10123 reasoning."""
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


def write_fvg_pine(base: Path, engine: WeeklyFVGEngine, label_cap: int, fvg_cap: int, table_cap: int,
                    display_zone: ZoneInfo, extra_lines: Optional[List[str]] = None, out_name: str = "weekly_fvg_viewer.pine") -> None:
    """Array-packed from the start -- same CE10295/CE10205/CE10013 avoidance
    discipline as every other layer in this project (see weekly_rb_generator.py)."""
    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    shown = engine.zones[-fvg_cap:]
    table_zones = engine.zones[-table_cap:][::-1]
    max_fvg_offset = max(1, len(engine.zones))

    lines = [
        "//@version=6",
        "indicator(\"FXCM Weekly FVG - Python Reference\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. Swing/MSS detection is identical to the OB/RB reference engines.",
        "// FVG zone = a classic 3-candle gap (IFVG/AFVG per the confirmed spec).",
        "float lowGap = ta.atr(14) * 0.08",
        "bool inspectOneFVG = input.bool(false, \"Inspect one FVG only\", group=\"FVG inspection\")",
        f"int fvgFromLast = input.int(1, \"FVG from last\", minval=1, maxval={max_fvg_offset}, group=\"FVG inspection\", tooltip=\"1 = latest FVG, 2 = the FVG before it, and so on.\")",
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
    fvg_left, fvg_top, fvg_bottom, fvg_fallback_right, fvg_impact_stamp, fvg_has_impact, fvg_col, fvg_rank, fvg_audit, fvg_has_line = ([] for _ in range(10))
    for z in shown:
        wk = engine.w[z.left]
        fallback_right = z.impact_time or (engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else right_edge)
        rank_from_last = len(engine.zones) - z.id + 1
        fvg_left.append(pine_epoch(wk.start)); fvg_top.append(z.zt); fvg_bottom.append(z.zb)
        fvg_fallback_right.append(pine_epoch(fallback_right))
        fvg_impact_stamp.append(pine_epoch(z.impact_time) if z.impact_time is not None else None)
        fvg_has_impact.append(z.impact_time is not None)
        fvg_col.append(_COLOUR_CODE[fvg_colour(z)]); fvg_rank.append(rank_from_last)
        fvg_audit.append(f"#{z.id} {status(z)} {'BUY' if z.bullish else 'SELL'}")
        fvg_has_line.append(z.impact_time is not None)

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
        t_bg.append(_COLOUR_CODE[fvg_colour(z)])
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
        i_bg.append(_COLOUR_CODE[fvg_colour(z)]); i_rank.append(rank_from_last)
        i_reason.append(z.stop_reason)

    lines += [
        *pack_array("structX", "int", struct_x),
        *pack_array("structY", "float", struct_y),
        *pack_array("structTxt", "string", struct_txt),
        *pack_array("structColCode", "string", struct_col),
        *pack_array("structLow", "bool", struct_low),
        *pack_array("fvgLeft", "int", fvg_left),
        *pack_array("fvgTop", "float", fvg_top),
        *pack_array("fvgBottom", "float", fvg_bottom),
        *pack_array("fvgFallbackRight", "int", fvg_fallback_right),
        *pack_array("fvgImpactStamp", "int", fvg_impact_stamp),
        *pack_array("fvgHasImpact", "bool", fvg_has_impact),
        *pack_array("fvgColCode", "string", fvg_col),
        *pack_array("fvgRank", "int", fvg_rank),
        *pack_array("fvgAudit", "string", fvg_audit),
        *pack_array("fvgHasLine", "bool", fvg_has_line),
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
        f"var array<int> fvgImpactX = array.new<int>({len(shown)}, na)",
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
        "    if onWeekly or onH4 or on1m or onFive",
        "        for i = 0 to array.size(fvgLeft) - 1",
        "            if not inspectOneFVG or fvgFromLast == array.get(fvgRank, i)",
        "                fvgRight = array.get(fvgHasImpact, i) and not na(array.get(fvgImpactX, i)) ? array.get(fvgImpactX, i) : array.get(fvgFallbackRight, i)",
        f"                fvgCol = {colour_ternary('array.get(fvgColCode, i)')}",
        "                box.new(array.get(fvgLeft, i), array.get(fvgTop, i), fvgRight, array.get(fvgBottom, i), border_color=fvgCol, border_width=1, bgcolor=color.new(fvgCol, 85), xloc=xloc.bar_time)",
        "                if array.get(fvgHasLine, i)",
        "                    line.new(fvgRight, array.get(fvgBottom, i), fvgRight, array.get(fvgTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)",
        "    if onWeekly",
        "        table.clear(ledger, 0, 0, 9, 20)",
        "        table.cell(ledger, 0, 0, \"W FVG\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 1, 0, \"Type\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 5, 0, \"Left (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 6, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 7, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 8, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        table.cell(ledger, 9, 0, \"Status\", text_color=color.white, bgcolor=color.new(color.green, 15))",
        "        if not inspectOneFVG",
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
        "            if inspectOneFVG and fvgFromLast == array.get(iRank, i)",
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


def write_report(base: Path, minutes: List["wob.Minute"], weeks: List["wob.Week"], warnings: List[str], e: WeeklyFVGEngine, args: argparse.Namespace, display_zone: ZoneInfo) -> None:
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)
    counts = {name: 0 for name in ("IFVG", "AFVG", "OFVG", "SPENT")}
    reasons = {"IMPACT": 0, "CLOSE_THROUGH": 0}
    for z in e.zones:
        counts[status(z)] += 1
        if z.stop_reason in reasons:
            reasons[z.stop_reason] += 1
    rows = [
        "WEEKLY FVG REFERENCE RUN", f"input={args.csv_file}", f"price_side={args.price_side}",
        f"weekly_aggregation=Sunday {args.week_close_hour:02d}:00 {args.week_close_zone}",
        f"minute_coverage_utc={wob.iso(minutes[0].t)} to {wob.iso(minutes[-1].t)}",
        f"minute_coverage_riyadh={wob.display_iso(minutes[0].t, display_zone)} to {wob.display_iso(minutes[-1].t, display_zone)}",
        f"minutes={len(minutes):,}; weeks={len(weeks):,}; swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}",
        "", "FVG LIFECYCLE COUNTS", *[f"{name}={counts[name]}" for name in counts],
        "", "SPENT REASON BREAKDOWN", *[f"{name}={reasons[name]}" for name in reasons],
        "", "Colors: IFVG BUY=blue; IFVG SELL=black; AFVG=green (fixed); OFVG=red (fixed).",
    ]
    if warnings:
        rows += ["", "WARNINGS"] + warnings[:50]
    (base / "weekly_fvg_report.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locked Weekly structure FVG reference generator")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-fvgs", type=int, default=150, choices=range(1, 451))
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
        engine = WeeklyFVGEngine(minutes, weeks)
        engine.run()
        write_ledger(base, engine, display_tz)
        write_fvg_pine(base, engine, args.pine_labels, args.pine_fvgs, args.pine_table, display_tz)
        write_report(base, minutes, weeks, warnings, engine, args, display_tz)
        print("Created:")
        print("  weekly_fvg_ledger.csv")
        print("  weekly_fvg_swings.csv")
        print("  weekly_fvg_viewer.pine")
        print("  weekly_fvg_report.txt")
        print(f"Processed {len(minutes):,} minutes and {len(weeks)} weeks. The Pine viewer contains Weekly structure and the FVG lifecycle.")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
