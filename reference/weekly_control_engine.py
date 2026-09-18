#!/usr/bin/env python3
"""Weekly direction-control state machine (SPEC.md SS9-16).

Stage 4 of the build order. This module NEVER recomputes swing/MSS/OB facts.
It imports weekly_ob_generator.py unmodified, drives its WeeklyOBEngine one
week at a time (instead of calling .run(), which only exposes final state),
and layers the Weekly trend/control state machine on top of the already
-computed zone and event facts. If a zone's type, boundary, trigger,
eligibility or impact looks wrong, that is a Stage 1-3 (OB engine) bug, not a
Stage 4 (control) bug -- report it against weekly_ob_generator.py instead.

Outputs, next to the input CSV:
  weekly_control_ledger.csv   one row per week: trend, control, and the
                               zone IDs currently responsible for that state
  weekly_control_events.csv   one row per control-relevant event in causal
                               order: trend flips, campaign start/stop,
                               opposing-POI encounter/gain/lose control,
                               no-control transitions
  weekly_control_report.txt   plain-English summary + explicit list of every
                               interpretive rule this module had to choose,
                               so it can be checked against the chart before
                               being trusted

This is a FIRST PASS. Treat every control-state value as unverified until
checked week-by-week against the TradingView chart, the same way every OB
lifecycle fact was verified before being locked.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_ob_generator as wob  # noqa: E402  (locked engine, unmodified)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly direction-control state machine (additive layer)")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--reset-to-none-at-week", type=int, default=None,
                    help="Force control to NONE (and clear any opposing/controlling zone) immediately "
                         "before this week index is processed, then let the normal state machine run "
                         "from there. Deliberate override for a period whose pre-history is not yet "
                         "trusted -- see the 2026-09-16 handoff entry on zone #1/#2 (pre-zone-3): the "
                         "user's own chart read (zone #1's supporting swing breached the same week it "
                         "reacted; zone #2 rejected as an OB) says no real campaign existed before zone "
                         "#3, but the locked OB engine's own state classification doesn't capture "
                         "'reacted AND then immediately invalidated' as distinct from plain SPENT, so "
                         "the control state machine can't yet derive that on its own. Not a fix for the "
                         "underlying question -- an explicit, visible reset so verified work from a "
                         "known-good point can continue without being distorted by an unresolved one.")
    return p.parse_args()


TREND = {0: "UNDEFINED", 1: "BULLISH", 2: "BEARISH"}


@dataclass
class ControlEvent:
    week: int
    at_utc: Optional[datetime]
    kind: str          # see EVENT KINDS below
    detail: str
    zone_id: Optional[int]
    trend: str
    control: str


# EVENT KINDS
# TREND_FLIP, CAMPAIGN_START, OPPOSING_ENCOUNTER, OPPOSING_GAINS_CONTROL,
# OPPOSING_LOSES_CONTROL, RETURN_TO_PRO_TREND, NO_CONTROL, RESET_TO_NONE


def is_pro(z: "wob.Zone", trend: int) -> bool:
    """Direction-vs-current-trend classification (SPEC.md SS15 wording: 'old'
    and 'aggressive' POIs become opposing purely by direction after a trend
    flip -- not by their orig_state family)."""
    if trend == 1:
        return z.bullish
    if trend == 2:
        return not z.bullish
    return False


def is_alive_state(state: Optional[int], rejected: bool) -> bool:
    """Not rejected, not OOB (stranded), not yet spent -- i.e. still capable
    of forcing or contributing to control.

    Takes a (state, rejected) SNAPSHOT, never a live Zone object -- see
    `state_by_week` below for why. A zone not yet created as of the week in
    question (state is None) is not alive."""
    return state is not None and not rejected and state in (0, 1, 4)


def is_spent_state(state: Optional[int], rejected: bool) -> bool:
    """Reached its own impact reaction (SPENT) and isn't rejected, as of a
    given week snapshot -- see `state_by_week` below."""
    return state == 3 and not rejected


def body_close_dead(z: "wob.Zone", week) -> bool:
    """SPEC.md SS14's Weekly-close POI breach, ported 2026-09-18 from this
    session's own chart-verified findings (zones #8/#9 in the 04-14..09-11
    control-gate walkthrough) -- previously NOT implemented anywhere in this
    module (see the old, now-superseded decision #5 in write_outputs below).

    A zone's own thesis dies the moment a Weekly candle's body closes at or
    beyond its NEAR boundary -- a body close merely INSIDE the zone (no
    clean wick-reject) is enough on its own, exactly like a full close
    THROUGH it; both are the same underlying condition, checked the same
    way. For a SELL zone (approached from below), that's `close >= zb`. For
    a BUY zone (approached from above), that's `close <= zt`. This is
    distinct from -- and in addition to -- the locked engine's own
    stranding-to-OOB rule (a fresh opposing swing forming beyond the zone),
    which is a different, already-implemented mechanism."""
    return (week.c >= z.zb) if not z.bullish else (week.c <= z.zt)


def run(args: argparse.Namespace) -> int:
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    engine = wob.WeeklyOBEngine(minutes, weeks)

    # Drive the locked engine week-by-week (instead of engine.run()) purely to
    # capture its regime AFTER each week, since WeeklyOBEngine only exposes
    # final state. This changes nothing about how each week is processed.
    #
    # Real bug fixed 2026-09-16 (user-caught): an earlier version ran this
    # loop to completion (processing the ENTIRE dataset) before the control
    # loop below even started, then had every is_alive()/newly_oob check in
    # that control loop read live z.state/z.rejected off the SAME mutable
    # Zone objects -- which by then already reflected each zone's FINAL,
    # end-of-dataset outcome, not its state as of the week actually being
    # examined. Concretely: at the week zone #5 (BUY) got impacted, zone #8
    # (SELL) was genuinely still alive (only triggered, not yet spent) -- but
    # the old code saw zone #8's eventual SPENT state from two and a half
    # months later, and wrongly answered "no live sell zone" (a direct
    # switch to BUY_ONLY) instead of "yes" (BOTH, per SS12). Every
    # is_alive()-style check in this module was equally exposed to this,
    # not just that one case.
    #
    # Fixed by snapshotting each zone's own (state, rejected) immediately
    # after processing each week -- before any later week's processing can
    # move that zone further -- and having every later check read from that
    # week's snapshot (`state_by_week[k]`) instead of the live, ever-mutating
    # Zone object. `bullish`/`candle`/`created_state`/`id` are set once at a
    # zone's creation and never mutated afterward by the locked engine, so
    # those remain safe to read straight off the live object at any point --
    # only `state` and `rejected` (the two fields the locked engine keeps
    # advancing as later weeks are processed) needed this treatment.
    trend_at: List[int] = []
    state_by_week: List[Dict[int, Tuple[int, bool]]] = []
    for k in range(len(weeks)):
        engine.process(k)
        trend_at.append(engine.regime)
        state_by_week.append({z.id: (z.state, z.rejected) for z in engine.zones})

    n = len(weeks)
    # Week -> zones impacted that week. Safe to index post-hoc off the FINAL
    # zone list: a zone's impact week (`z.stop`) and its ever having reached
    # SPENT are both facts fixed permanently at the exact moment they
    # happen, not "current state as of week k" -- unlike is_alive(), there is
    # no lookahead risk in bucketing by them.
    impacts_by_week: Dict[int, List["wob.Zone"]] = {}
    for z in engine.zones:
        if z.state == 3 and 0 <= z.stop < n:
            impacts_by_week.setdefault(z.stop, []).append(z)
    swing_high_weeks = sorted({e.confirm for e in engine.events if e.kind == 0})
    swing_low_weeks = sorted({e.confirm for e in engine.events if e.kind == 1})
    # Earliest confirm timestamp per (kind, week), for ordering a same-week
    # swing-resume against a same-week zone impact by REAL time (see the
    # combined resume-from-NONE step below) -- week-bucket order alone isn't
    # enough, and defaulting to "whichever check runs first in the code"
    # silently picked the wrong one for this session's own gate 3->4
    # (zone 5's impact and the swing-high resume both land in week 22; the
    # swing fires first in real time, at 16:51, then zone 5 at 18:37 -- BOTH,
    # not a direct switch to BUY_ONLY).
    earliest_swing_at: Dict[Tuple[int, int], datetime] = {}
    for e in engine.events:
        if e.at is None:
            continue
        key = (e.kind, e.confirm)
        if key not in earliest_swing_at or e.at < earliest_swing_at[key]:
            earliest_swing_at[key] = e.at

    # Track OOB/rejected transitions week-by-week for "loses control", from
    # the per-week snapshot -- not live z.state, for the same reason as above.
    prev_state: Dict[int, int] = {}
    prev_rejected: Dict[int, bool] = {}

    trend = "UNDEFINED"
    control = "NONE"
    controlling_opp: Optional[int] = None  # zone id currently holding full opposing control
    controlling_zone_id: Optional[int] = None  # the single Weekly zone responsible for the
    # ACTIVE single-direction control (BUY_ONLY/SELL_ONLY), for H4 parent-zone linkage.
    # None while control is NONE or BOTH (BOTH has two sides, no single "the" zone).
    # `paused_bull`: set ONLY when a same-direction swing confirms and pauses
    # an otherwise-still-alive campaign to NONE (SPEC.md SS16, ported
    # 2026-09-18 -- see the SWING_PAUSE/SWING_RESUME checks below). None
    # means either not currently paused, or NONE was reached some other way
    # (a zone's own body-close death, or the very start) -- those exits only
    # resume via a fresh zone impact (the existing CAMPAIGN_START check),
    # never via a swing confirming, per this session's own gates 11-14.
    paused_bull: Optional[bool] = None
    # Zones already known dead by their own Weekly-close body-inside/through
    # rule (`body_close_dead`), so each zone is only ever logged once.
    body_dead_ids: set = set()
    events: List[ControlEvent] = []
    weekly_rows = []

    def log(k: int, kind: str, detail: str, zone_id: Optional[int]) -> None:
        at = weeks[k].start
        events.append(ControlEvent(k, at, kind, detail, zone_id, trend, control))

    for k in range(n):
        if args.reset_to_none_at_week is not None and k == args.reset_to_none_at_week:
            control = "NONE"
            controlling_opp = None
            controlling_zone_id = None
            log(k, "RESET_TO_NONE", "Explicit --reset-to-none-at-week override", None)

        new_trend = TREND[trend_at[k]]
        if new_trend != trend:
            trend = new_trend
            # Trend is a separate, structural fact (SPEC.md SS9). A flip does
            # NOT by itself change control -- control only changes through the
            # explicit transfer rules below (campaign start/stop, opposing
            # encounter/gain/lose, no-control). An active campaign carries
            # straight through a trend flip until one of those rules fires.
            log(k, "TREND_FLIP", f"Weekly trend -> {trend}", None)

        snapshot_k = state_by_week[k]
        zones_this_week = [z for z in engine.zones if z.id in snapshot_k]
        impacts_this_week = impacts_by_week.get(k, [])

        # OOB / rejection transitions this week, for "loses control". Reads
        # this week's snapshot, not live z.state -- see the fix note above.
        newly_oob_ids, newly_rejected_ids = set(), set()
        for z in zones_this_week:
            state_now, rejected_now = snapshot_k[z.id]
            was_state = prev_state.get(z.id, z.created_state)
            was_rej = prev_rejected.get(z.id, False)
            if state_now == 2 and was_state != 2:
                newly_oob_ids.add(z.id)
            if rejected_now and not was_rej:
                newly_rejected_ids.add(z.id)
            prev_state[z.id] = state_now
            prev_rejected[z.id] = rejected_now

        if trend == "UNDEFINED":
            weekly_rows.append((k, trend, control, "", ""))
            continue

        # From here on, "pro"/"opposing" for control-escalation purposes are
        # relative to the ESTABLISHED CONTROL DIRECTION, not structural trend
        # (SPEC.md SS9: trend and control are independent states; a control
        # campaign can start opposite of trend -- see decision #6 below).
        control_bull = control == "BUY_ONLY"

        # 0/1/5 combined, ported 2026-09-18: zone-death (SS14), campaign
        # start/resume from NONE, and the swing-confirm pause (SS16) all
        # interact within a single week and must be resolved in REAL
        # chronological order, not as separate sequential checks -- two
        # concrete cases this session's own gates exposed by testing:
        #   - gate 3->4 (week 22): a swing-high resume (16:51) and zone 5's
        #     impact (18:37) land in the SAME week. Applying the impact
        #     check first (as an earlier version of this code did) wrongly
        #     jumps straight to BUY_ONLY instead of SELL_ONLY -> BOTH.
        #   - gate 6->7 (week 24): the pausing swing low AND the resuming
        #     swing high land in the SAME week (00:29 and 22:24
        #     respectively). Checking pause and resume as two separate,
        #     non-interacting passes over the week misses the resume
        #     entirely, since `paused_bull` isn't set until after the
        #     resume check has already run for that week.
        #   - gates 11->12, 13->14: a zone can be impacted AND die to its
        #     own Weekly-close body rule in the SAME week (its own
        #     containing week is also its impact week) -- zone-death must
        #     therefore be ordered relative to that week's own impact, not
        #     unconditionally before it.
        # Built as a small sorted list of this week's real candidate
        # triggers, then walked in time order, each one acting on whatever
        # control state the PRIOR trigger in the same week left behind.
        week_triggers: List[Tuple[datetime, str, object]] = []
        if control in ("BUY_ONLY", "SELL_ONLY") and controlling_zone_id is not None:
            z = next((zz for zz in engine.zones if zz.id == controlling_zone_id), None)
            if z is not None and controlling_zone_id not in body_dead_ids and body_close_dead(z, weeks[k]):
                week_triggers.append((weeks[k].end, "zone_death", z))
        for z in impacts_this_week:
            week_triggers.append((z.impact_time, "impact", z))
        if (0, k) in earliest_swing_at:
            week_triggers.append((earliest_swing_at[(0, k)], "swing_high", None))
        if (1, k) in earliest_swing_at:
            week_triggers.append((earliest_swing_at[(1, k)], "swing_low", None))
        week_triggers.sort(key=lambda t: t[0])

        for at, kind_, payload in week_triggers:
            if kind_ == "zone_death":
                z = payload
                if control in ("BUY_ONLY", "SELL_ONLY") and controlling_zone_id == z.id and z.id not in body_dead_ids:
                    body_dead_ids.add(z.id)
                    log(k, "ZONE_DEATH", f"Zone {z.id} (providing {control}) closes body inside/through its own box -> NONE", z.id)
                    control = "NONE"
                    control_bull = False
                    controlling_zone_id = None
                    paused_bull = None  # zone-death only resumes via a fresh impact, never a swing (gates 12->13)
            elif kind_ == "impact":
                z = payload
                if control == "NONE":
                    control = "BUY_ONLY" if z.bullish else "SELL_ONLY"
                    control_bull = z.bullish
                    controlling_zone_id = z.id
                    log_kind = "CAMPAIGN_START" if is_pro(z, trend_at[k]) else "CAMPAIGN_START_COUNTERTREND"
                    log(k, log_kind, f"Zone {z.id} impacted (direction={'BUY' if z.bullish else 'SELL'}, trend={trend})", z.id)
                # An impact while already BUY_ONLY/SELL_ONLY/BOTH is handled
                # by check 2 below (same-side: a new entry, no control
                # change; opposite-side: opposing encounter), using
                # `impacts_this_week` directly -- not re-litigated here.
            elif kind_ in ("swing_high", "swing_low"):
                # Same-direction pause: a swing LOW pauses SELL_ONLY (this
                # session's whole basis -- "we stopped selling because
                # price confirmed swing low"); a swing HIGH pauses
                # BUY_ONLY, its mirror. Real bug fixed while porting this:
                # an earlier version of this exact block had the polarity
                # backwards (swing HIGH pausing SELL_ONLY), caught by
                # testing against gate 1->2 -- the pause fired at the wrong
                # week (19, on a swing HIGH) instead of the right one (21,
                # on the real swing LOW).
                pauses_sell = kind_ == "swing_low"
                pauses_buy = kind_ == "swing_high"
                if control == "SELL_ONLY" and pauses_sell or control == "BUY_ONLY" and pauses_buy:
                    # "No opposing zone IN CONTROL" -- not merely alive/armed
                    # on the chart. A zone only gains control by being
                    # impacted (that's how checks 2-4 already work: BOTH
                    # happens on an opposing IMPACT, not on an opposing zone
                    # merely existing untouched). An armed-but-never-touched
                    # opposing zone (state in 0,1,4, impact_time=None) does
                    # not block this pause -- only a zone that has actually
                    # been impacted (SPENT, state==3, not rejected) does.
                    opposing_in_control = any(
                        zz.bullish != control_bull and is_spent_state(*snapshot_k[zz.id])
                        for zz in engine.zones if zz.id in snapshot_k
                    )
                    if not opposing_in_control:
                        log(k, "SWING_PAUSE", f"{'Swing low' if not control_bull else 'Swing high'} confirms, no opposing POI in control -> NONE", None)
                        paused_bull = control_bull
                        control = "NONE"
                        control_bull = False
                        controlling_zone_id = None
                elif control == "NONE" and paused_bull is False and kind_ == "swing_high":
                    # SELL was paused; a swing HIGH (opposite kind) resumes it.
                    control = "SELL_ONLY"
                    control_bull = False
                    log(k, "SWING_RESUME", "Swing high confirms -> SELL_ONLY", None)
                    paused_bull = None
                elif control == "NONE" and paused_bull is True and kind_ == "swing_low":
                    # BUY was paused; a swing LOW (opposite kind) resumes it.
                    control = "BUY_ONLY"
                    control_bull = True
                    log(k, "SWING_RESUME", f"{'Swing high' if not paused_bull else 'Swing low'} confirms -> {control}", None)
                    paused_bull = None

        # 2) A zone opposite the CONTROLLING direction gets impacted. Only
        #    escalate to BOTH if the CURRENT controlling side still has a
        #    live, unspent zone (a genuine concurrent thesis). If the old
        #    side already delivered its reaction and is spent, there is
        #    nothing to run concurrently with -- switch control straight to
        #    the new zone's direction instead.
        if control in ("BUY_ONLY", "SELL_ONLY"):
            opp_impacts = [z for z in impacts_this_week if z.bullish != control_bull]
            if opp_impacts:
                old_side_alive = any(
                    z.bullish == control_bull and is_alive_state(*snapshot_k[z.id])
                    for z in engine.zones if z.id in snapshot_k
                )
                if old_side_alive:
                    control = "BOTH"
                    controlling_zone_id = None
                    for z in opp_impacts:
                        log(k, "OPPOSING_ENCOUNTER", f"Opposing zone {z.id} impacted, old side still active -> BOTH", z.id)
                else:
                    new_zone = opp_impacts[0]
                    control = "BUY_ONLY" if new_zone.bullish else "SELL_ONLY"
                    control_bull = new_zone.bullish
                    controlling_zone_id = new_zone.id
                    log(k, "CONTROL_SWITCHED", f"Old side exhausted; zone {new_zone.id} impacted -> {control}", new_zone.id)

        # 3) Opposing gains control: survives, and a same-direction-as-opposing
        #    swing confirms after its impact, and no same-direction-as-original
        #    -control zone is still alive to keep forcing that side.
        if control == "BOTH" and controlling_opp is None:
            # We don't retain which side started the campaign once in BOTH, so
            # try both directions as "the opposing side that could take over."
            for candidate_bull in (True, False):
                need_kind_weeks = swing_high_weeks if candidate_bull else swing_low_weeks
                candidates = [
                    z for z in engine.zones
                    if z.bullish == candidate_bull and z.id in snapshot_k and is_spent_state(*snapshot_k[z.id])
                ]
                other_side_alive = any(
                    z.bullish != candidate_bull and is_alive_state(*snapshot_k[z.id])
                    for z in engine.zones if z.id in snapshot_k
                )
                if other_side_alive:
                    continue
                for z in candidates:
                    if z.stop is None or z.stop > k:
                        continue
                    confirmed_after = [w for w in need_kind_weeks if z.stop <= w <= k]
                    if not confirmed_after:
                        continue
                    controlling_opp = z.id
                    control = "BUY_ONLY" if candidate_bull else "SELL_ONLY"
                    control_bull = candidate_bull
                    controlling_zone_id = z.id
                    log(k, "OPPOSING_GAINS_CONTROL", f"Zone {z.id} confirmed swing at week {confirmed_after[0]}, other side exhausted", z.id)
                    break
                if controlling_opp is not None:
                    break

        # 4) Opposing loses control: the controlling zone breaches.
        if controlling_opp is not None:
            opp_zone = next((z for z in engine.zones if z.id == controlling_opp), None)
            if opp_zone is not None and (controlling_opp in newly_oob_ids or controlling_opp in newly_rejected_ids):
                log(k, "OPPOSING_LOSES_CONTROL", f"Zone {controlling_opp} breached", controlling_opp)
                controlling_opp = None
                controlling_zone_id = None
                other_opp_alive = any(
                    z.bullish != control_bull and is_alive_state(*snapshot_k[z.id])
                    for z in engine.zones if z.id in snapshot_k
                )
                pro_alive = any(
                    z.bullish == control_bull and is_alive_state(*snapshot_k[z.id])
                    for z in engine.zones if z.id in snapshot_k
                )
                if other_opp_alive:
                    control = "BOTH"
                elif pro_alive:
                    control = "BUY_ONLY" if control_bull else "SELL_ONLY"
                    log(k, "RETURN_TO_PRO_TREND", f"No opposing POI remains active -> {control}", None)
                    # NOTE: controlling_zone_id stays None here -- there may be
                    # several alive pro-side zones and no single one is "the"
                    # authority. Audit gap: h4_ob_engine's parent-zone linkage
                    # will show blank for OBs impacted during this state.
                else:
                    control = "NONE"
                    log(k, "NO_CONTROL", "No active POI on either side", None)

        # (SPEC.md SS16's no-control pause, and its opposite-swing resume,
        # are both handled inside the time-ordered week_triggers walk above
        # -- not as separate sequential checks; see that block's own
        # comment for why. The old swing-taken-out resume rule is abandoned
        # per the user's explicit instruction 2026-09-17/18 -- do not
        # reintroduce it.)

        weekly_rows.append((k, trend, control, str(controlling_opp) if controlling_opp else "", str(controlling_zone_id) if controlling_zone_id else ""))

    write_outputs(base, weeks, weekly_rows, events, display_tz)
    print("Created:")
    print("  weekly_control_ledger.csv")
    print("  weekly_control_events.csv")
    print("  weekly_control_report.txt")
    print(f"Processed {n} weeks. {len(events)} control-relevant events logged.")
    return 0


def write_outputs(base: Path, weeks, weekly_rows, events: List[ControlEvent], display_tz: ZoneInfo) -> None:
    with (base / "weekly_control_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["week_index", "week_start_utc", "week_start_riyadh", "trend", "control", "controlling_opposing_zone_id", "controlling_zone_id"])
        for k, trend, control, opp_id, controlling_zone_id in weekly_rows:
            wk = weeks[k]
            wr.writerow([k, wob.iso(wk.start), wob.display_iso(wk.start, display_tz), trend, control, opp_id, controlling_zone_id])

    with (base / "weekly_control_events.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["week_index", "week_start_utc", "week_start_riyadh", "event", "detail", "zone_id", "trend_after", "control_after"])
        for e in events:
            wr.writerow([e.week, wob.iso(e.at_utc), wob.display_iso(e.at_utc, display_tz), e.kind, e.detail, e.zone_id or "", e.trend, e.control])

    lines = [
        "WEEKLY DIRECTION-CONTROL STATE MACHINE -- FIRST PASS, UNVERIFIED",
        "",
        "This is an additive layer over the locked weekly_ob_generator.py engine.",
        "It does not change any OB/swing/MSS fact. Every row below is a candidate",
        "answer that still needs chart-by-chart verification, same as every OB",
        "lifecycle fact was verified before being locked.",
        "",
        "INTERPRETIVE DECISIONS THIS MODULE MADE (verify these against SPEC.md):",
        "1. Trend state is read directly from the locked engine's internal",
        "   swing regime (0=UNDEFINED,1=BULLISH/up,2=BEARISH/down). This assumes",
        "   the engine's regime flip IS the SPEC.md SS15 'protected swing broken'",
        "   trend reversal event -- they are the same MSS in this engine.",
        "2. Pro-trend vs opposing is classified purely by zone direction vs",
        "   current trend (SPEC.md SS15: 'old' and 'aggressive' POIs become",
        "   opposing after a flip), not by the zone's AOB/IFOB/AIFOB origin type.",
        "3. 'Active/alive' POI (forcing continued control) = not rejected, not",
        "   OOB, not yet SPENT (state in IFOB/AOB/AIFOB). A SPENT zone is",
        "   treated as having already done its job, not as still forcing control.",
        "   Fixed 2026-09-16 (real lookahead bug, user-caught): this check used",
        "   to read each zone's FINAL end-of-dataset state, not its state as of",
        "   the week being examined, because the whole dataset was processed",
        "   before the control loop below ever started. Every alive/spent check",
        "   now reads a per-week snapshot instead -- see state_by_week in the",
        "   source. This can change past BOTH-vs-direct-switch answers; treat",
        "   every one as unverified again until re-checked against the chart.",
        "4a. An opposing-direction impact only escalates to BOTH if the",
        "   currently-controlling side still has a live (unspent) zone. If",
        "   the old side already delivered its reaction and is spent, control",
        "   SWITCHES straight to the new zone's direction (CONTROL_SWITCHED)",
        "   instead of passing through BOTH. Chart-confirmed 2026-04-14",
        "   (zone 3 SELL): zone 1 (BUY) had already delivered its reaction and",
        "   was spent, so this should switch straight to SELL_ONLY and hold",
        "   through every 4H sell impact until price reaches the next Weekly",
        "   zone, not oscillate through BOTH/BUY_ONLY.",
        "4. Opposing-gains-control's 'reaction produces a confirmed Weekly",
        "   swing' is matched to ANY same-direction swing confirmation between",
        "   the opposing zone's impact week and the current week -- not proven",
        "   to be caused BY that specific zone's reaction. If a chart case shows",
        "   the wrong opposing zone credited, this matching rule is the first",
        "   suspect.",
        "5. Opposing-loses-control is detected only via the engine's own",
        "   stranding-to-OOB rule or rejection. SPEC.md SS14's separate",
        "   'Weekly-close POI breach' mechanism is NOT implemented (see",
        "   docs/BUILD_ORDER.md audit -- the locked engine itself only has one",
        "   breach mechanism, not two).",
        "6. From NONE, whichever zone (either direction) is impacted FIRST",
        "   starts control in ITS OWN direction, even if that is opposite the",
        "   current structural trend (SPEC.md SS9 explicitly allows trend and",
        "   control to diverge; SS16 says a no-control state waits for 'a",
        "   valid Weekly POI of either direction' and then processes it",
        "   normally). All later BOTH/opposing-gains/opposing-loses/no-control",
        "   logic is therefore relative to the ESTABLISHED CONTROL direction,",
        "   not to structural trend. A trend flip does NOT reset control by",
        "   itself (SPEC.md SS9: trend and control are independent) -- an",
        "   active campaign carries straight through a flip until one of the",
        "   explicit transfer rules fires (encounter/gain/lose/no-control).",
        "",
        f"Weeks processed: {len(weeks)}",
        f"Control-relevant events: {len(events)}",
    ]
    (base / "weekly_control_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
