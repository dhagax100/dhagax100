#!/usr/bin/env python3
"""RB-native weekly direction-control state machine.

Rule-for-rule port of `rb_system/ob_reference/weekly_control_engine.py`, but
driven on RB's OWN zone/event timeline (`weekly_rb_generator.WeeklyRBEngine`
-- IRB/ARB/ORB/SPENT zones and their impact events) instead of OB's
IFOB/AOB/OOB and rejection events.

WHY THIS MODULE EXISTS (correction, 2026-09-18): an earlier session wired
`h4_rb_engine.py`/`five_rb_bso_engine.py` to gate RB opportunities against
OB's own precomputed `weekly_control_ledger.csv`. That is wrong: the STATE
MACHINE RULE ("a zone impacts while control==NONE -> control flips to that
zone's side", swing-pause, BOTH-escalation, etc, see
`weekly_control_engine.py` ~line 331 onward) is shared/analogous logic, but
WHICH zone reaches impact and WHEN is specific to each system's own
construction -- IRB/ARB/ORB fire and impact on a completely different
schedule than IFOB/AOB/OOB. So the control state machine must be re-run on
RB's OWN zone timeline, producing its OWN control ledger
(`weekly_control_ledger_rb.csv`), not read off OB's.

SUBSTITUTION DECISIONS (record every one; see RB_TRADING_SYSTEM_HANDOFF.md
for the full reasoning trail):

1. `rejected` flag -- RB HAS NO ANALOG, and none is invented. RB's own zone
   dataclass (`RbZone` in weekly_rb_generator.py) has no `rejected` field at
   all; RB_Indicator_v1.pine's header explicitly does not describe a
   rejection mechanism for RB zones (that's an OB-specific concept: OB zones
   can be invalidated pre-eligibility by price breaching before eligibility
   is granted; RB zones have no such pre-eligibility breach check in STEP2/
   STEP3). Substitution: hardwire `rejected := False` everywhere OB's
   `is_alive_state`/`is_spent_state` take it as a parameter, and never
   populate a `newly_rejected_ids` set (it stays permanently empty). This
   isn't a guess -- it's the literal absence of the field in RB's own data
   model, confirmed by reading `RbZone`'s dataclass fields (id, candle, zb,
   zt, bullish, trigger, eligible, stop, state, origin, pre_spent_state,
   trigger_time, eligible_time, impact_time -- no `rejected`).

2. `is_alive_state(state, rejected)` -- OB: `state in (0,1,4) and not
   rejected` (IFOB/AOB/AIFOB, i.e. every OB pre-lifecycle type before
   OOB/SPENT). RB has no AIFOB-equivalent promotion state (RB zones are
   created once as IRB(0) or ARB(1) and never promoted to a third alive
   type). Substitution: `is_alive_state(state) := state in (0, 1)` -- IRB or
   ARB, not yet ORB(2)/SPENT(3). Structurally the same meaning ("still
   capable of forcing or contributing to control"), just over RB's smaller
   state family.

3. `is_spent_state(state, rejected)` -- OB: `state == 3 and not rejected`.
   RB: `state == 3` (SPENT means the same thing in both systems: reached its
   own impact reaction). Trivial substitution, no reasoning needed beyond
   dropping the always-False `rejected` term.

4. `body_close_dead()` (OB's SPEC.md SS14 Weekly-close body-breach rule,
   used ONLY to kill an already-SPENT zone that is the sole
   `controlling_zone_id` for single-side BUY_ONLY/SELL_ONLY control, added to
   weekly_control_engine.py 2026-09-18) -- **NO RB ANALOG EXISTS, and this is
   the one place this port had to verify structurally rather than invent
   one.** Traced exactly how `body_close_dead` is used in
   `weekly_control_engine.py`: it is called once, in the single-side
   ZONE_DEATH block (`if control in (BUY_ONLY,SELL_ONLY) and
   controlling_zone_id is not None: ... if body_close_dead(z, weeks[k]):
   control = NONE`). It is a check bolted onto the CONTROL layer itself
   (not part of the locked OB zone engine's own STATE machine) that lets an
   ALREADY-SPENT zone's thesis die a second death -- via a Weekly candle's
   BODY closing at/through its near boundary -- even though the zone's own
   `state` field never changes (it stays 3/SPENT forever once impacted; OB's
   locked engine has no state transition out of SPENT at all). RB's own pine
   spec (`RB_Indicator_v1.pine` header, lines ~26-33) is explicit and
   unambiguous: "Lifecycle: wick IMPACT + STRANDING only. No close-through
   rule." This is not "RB doesn't happen to implement one yet" (a judgment
   call) -- it is RB's own authoritative spec stating in so many words that
   this exact mechanism (a body/close-through condition acting on a zone)
   does not exist for RB, full stop, at any layer. There is no RB-native fact
   (impact, stranding, SPENT) that this could be substituted with, because
   the thing being detected -- "the zone's thesis dies AGAIN, after it
   already delivered its impact reaction, via a later candle's body" -- has
   no RB counterpart: RB's own zone lifecycle (STEP3) only ever acts on a
   zone while `state in (0,1)` (stranding) or via the impact check (which is
   a one-way transition into SPENT that nothing later reverses). Once an RB
   zone is SPENT, RB's own spec has literally nothing further to say about
   it ever "dying" again.
   DECISION: body_close_dead is NOT ported. The single-side ZONE_DEATH
   transition in this module is omitted entirely; single-side RB control
   only ever changes via the mechanisms RB's own zone facts DO support
   (swing-pause/resume, opposing-zone impact -> BOTH, opposing-gains/loses
   control via stranding). This was flagged, not silently decided, per the
   task's own "stop rather than guess" instruction -- but since the pine
   spec is explicit and unambiguous on this exact point (not merely silent),
   this is recorded as a resolved substitution decision rather than a
   blocking question back to the user.

5. "Opposing loses control" (`newly_oob_ids`, used for the BOTH-side
   `controlling_opp` zone breaching) -- RB's stranding-to-ORB (state 2) is
   the direct, literal analog of OB's stranding-to-OOB (state 2): both are
   "a zone dies via an opposing swing forming beyond it while never having
   been impacted" (compare `weekly_ob_generator.py`'s AOB/AIFOB stranding
   check to `weekly_rb_generator.py`'s STEP3 stranding loop -- both flip
   `state` to `2` under the same kind of condition, a fresh opposing swing
   price beyond the zone). No substitution reasoning needed here beyond
   pointing `newly_oob_ids` at RB's own `state==2` transition, which this
   module does.

Everything else (trend read from `engine.regime`; pro/opposing classified
purely by direction vs current CONTROL direction, per OB's own SS9 rule
already generalized in `is_pro`; the same-week trigger-ordering machinery;
CAMPAIGN_START/CAMPAIGN_START_COUNTERTREND/OPPOSING_ENCOUNTER/
CONTROL_SWITCHED/OPPOSING_GAINS_CONTROL/OPPOSING_LOSES_CONTROL/
RETURN_TO_PRO_TREND/NO_CONTROL/SWING_PAUSE/SWING_PAUSE_BOTH/SWING_RESUME) is
copied rule-for-rule from `weekly_control_engine.py`, operating on RB zones
(`z.bullish`/`z.state`/`z.stop`/`z.impact_time`/`z.id`) in place of OB zones.

Outputs, next to the input CSV:
  weekly_control_ledger_rb.csv   one row per week: trend, control, and the
                                  RB zone IDs responsible for that state
  weekly_control_events_rb.csv   one row per control-relevant event, causal
                                  order
  weekly_control_report_rb.txt   plain-English summary of every decision
                                  above
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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ob_reference"))
import weekly_rb_generator as wrb  # noqa: E402  (locked RB engine, unmodified)
import weekly_ob_generator as wob  # noqa: E402  (only for load_minutes/aggregate_weeks/iso/display_iso -- identical CSV-loading helpers, reused not reimplemented)

UTC = timezone.utc

TREND = {0: "UNDEFINED", 1: "BULLISH", 2: "BEARISH"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RB-native weekly direction-control state machine")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


@dataclass
class ControlEvent:
    week: int
    at_utc: Optional[datetime]
    kind: str
    detail: str
    zone_id: Optional[int]
    trend: str
    control: str


def is_pro(z: "wrb.RbZone", trend: int) -> bool:
    if trend == 1:
        return z.bullish
    if trend == 2:
        return not z.bullish
    return False


def is_alive_state(state: Optional[int]) -> bool:
    """RB analog of OB's is_alive_state(state, rejected): RB has no
    `rejected` flag (substitution #1) and no AIFOB-style 3rd alive state
    (substitution #2) -- IRB(0)/ARB(1), not yet ORB(2)/SPENT(3)."""
    return state is not None and state in (0, 1)


def is_spent_state(state: Optional[int]) -> bool:
    """RB analog of OB's is_spent_state(state, rejected) -- substitution #3:
    rejected is always False for RB, so this is just state == 3 (SPENT)."""
    return state == 3


def run(args: argparse.Namespace) -> int:
    path = Path(args.csv_file).expanduser().resolve()
    base = Path(args.out_dir).expanduser().resolve() if args.out_dir else path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    engine = wrb.WeeklyRBEngine(minutes, weeks)

    # Drive week-by-week to snapshot each zone's (state) immediately after
    # each week is processed -- same lookahead-bug fix OB's control engine
    # applies (see weekly_control_engine.py's own long comment on this),
    # necessary here for the identical reason: RbZone.state is a live,
    # ever-mutating field on the SAME object across the whole dataset.
    trend_at: List[int] = []
    state_by_week: List[Dict[int, int]] = []
    for k in range(len(weeks)):
        engine.process(k)
        trend_at.append(engine.regime)
        state_by_week.append({z.id: z.state for z in engine.rbs})

    n = len(weeks)
    impacts_by_week: Dict[int, List["wrb.RbZone"]] = {}
    for z in engine.rbs:
        if z.state == 3 and z.stop is not None and 0 <= z.stop < n:
            impacts_by_week.setdefault(z.stop, []).append(z)
    swing_high_weeks = sorted({e.confirm for e in engine.events if e.kind == 0})
    swing_low_weeks = sorted({e.confirm for e in engine.events if e.kind == 1})
    earliest_swing_at: Dict[Tuple[int, int], datetime] = {}
    for e in engine.events:
        if e.at is None:
            continue
        key = (e.kind, e.confirm)
        if key not in earliest_swing_at or e.at < earliest_swing_at[key]:
            earliest_swing_at[key] = e.at

    prev_state: Dict[int, int] = {}

    trend = "UNDEFINED"
    control = "NONE"
    controlling_opp: Optional[int] = None
    controlling_zone_id: Optional[int] = None
    paused_bull: Optional[bool] = None
    # body_zone_id: the zone whose IMPACT most recently gave the current side
    # control, persisted through SWING_PAUSE/SWING_RESUME (unlike
    # controlling_zone_id, which the existing swing-pause code clears to None
    # -- see the new CONTROL-LAYER body-close-violation check below, which
    # needs to keep pointing at "the zone this side's thesis rests on" across
    # a pause/resume cycle, not just while a swing-pause hasn't fired yet).
    # Cleared whenever control fully drops to NONE with no side, or escalates
    # to BOTH (no single zone identity to check at that point).
    body_zone_id: Optional[int] = None
    events: List[ControlEvent] = []
    weekly_rows = []

    def log(k: int, kind: str, detail: str, zone_id: Optional[int], at_override: Optional[datetime] = None) -> None:
        at = at_override if at_override is not None else weeks[k].start
        events.append(ControlEvent(k, at, kind, detail, zone_id, trend, control))

    for k in range(n):
        new_trend = TREND[trend_at[k]]
        if new_trend != trend:
            trend = new_trend
            log(k, "TREND_FLIP", f"Weekly trend -> {trend}", None)

        snapshot_k = state_by_week[k]
        zones_this_week = [z for z in engine.rbs if z.id in snapshot_k]
        impacts_this_week = impacts_by_week.get(k, [])

        # newly_oob_ids: RB stranding-to-ORB (state 2), substitution #5.
        # newly_rejected_ids: no RB analog (substitution #1) -- stays empty.
        newly_oob_ids: set = set()
        for z in zones_this_week:
            state_now = snapshot_k[z.id]
            was_state = prev_state.get(z.id, z.origin)
            if state_now == 2 and was_state != 2:
                newly_oob_ids.add(z.id)
            prev_state[z.id] = state_now

        if trend == "UNDEFINED":
            weekly_rows.append((k, trend, control, "", ""))
            continue

        control_bull = control == "BUY_ONLY"

        week_triggers: List[Tuple[datetime, str, object]] = []
        for z in impacts_this_week:
            week_triggers.append((z.impact_time, "impact", z))
        if (0, k) in earliest_swing_at:
            week_triggers.append((earliest_swing_at[(0, k)], "swing_high", None))
        if (1, k) in earliest_swing_at:
            week_triggers.append((earliest_swing_at[(1, k)], "swing_low", None))
        week_triggers.sort(key=lambda t: t[0])

        for at, kind_, payload in week_triggers:
            if kind_ == "impact":
                z = payload
                if control == "NONE":
                    control = "BUY_ONLY" if z.bullish else "SELL_ONLY"
                    control_bull = z.bullish
                    controlling_zone_id = z.id
                    log_kind = "CAMPAIGN_START" if is_pro(z, trend_at[k]) else "CAMPAIGN_START_COUNTERTREND"
                    log(k, log_kind, f"RB zone {z.id} impacted (direction={'BUY' if z.bullish else 'SELL'}, trend={trend})", z.id, at_override=at)
                    body_zone_id = z.id
            elif kind_ in ("swing_high", "swing_low"):
                pauses_sell = kind_ == "swing_low"
                pauses_buy = kind_ == "swing_high"
                if control == "SELL_ONLY" and pauses_sell or control == "BUY_ONLY" and pauses_buy:
                    log(k, "SWING_PAUSE", f"{'Swing low' if not control_bull else 'Swing high'} confirms, no opposing control -> NONE", None, at_override=at)
                    paused_bull = control_bull
                    control = "NONE"
                    control_bull = False
                    controlling_zone_id = None
                elif control == "BOTH" and (pauses_sell or pauses_buy):
                    surviving_bull = True if pauses_sell else False
                    survivor = next(
                        (zz for zz in engine.rbs
                         if zz.bullish == surviving_bull and zz.id in snapshot_k and is_spent_state(snapshot_k[zz.id])),
                        None,
                    )
                    if survivor is not None:
                        control = "BUY_ONLY" if surviving_bull else "SELL_ONLY"
                        control_bull = surviving_bull
                        controlling_zone_id = survivor.id
                        controlling_opp = None
                        paused_bull = None
                        log(k, "SWING_PAUSE_BOTH",
                            f"{'Swing low' if pauses_sell else 'Swing high'} confirms while BOTH -> "
                            f"opposing side keeps control ({control})", survivor.id, at_override=at)
                elif control == "NONE" and paused_bull is False and kind_ == "swing_high":
                    control = "SELL_ONLY"
                    control_bull = False
                    log(k, "SWING_RESUME", "Swing high confirms -> SELL_ONLY", None, at_override=at)
                    paused_bull = None
                elif control == "NONE" and paused_bull is True and kind_ == "swing_low":
                    control = "BUY_ONLY"
                    control_bull = True
                    log(k, "SWING_RESUME", f"{'Swing high' if not paused_bull else 'Swing low'} confirms -> {control}", None, at_override=at)
                    paused_bull = None

        # NOTE: no ZONE_DEATH block here -- substitution #4 (body_close_dead
        # has no RB analog, RB's own spec is explicit: "no close-through
        # rule"). Single-side control here only ever ends via swing-pause,
        # opposing-impact escalation to BOTH, or the BOTH-side mechanics
        # below -- never via a zone's own body closing through it.

        if control in ("BUY_ONLY", "SELL_ONLY"):
            opp_impacts = [z for z in impacts_this_week if z.bullish != control_bull]
            if opp_impacts:
                old_side_alive = any(
                    z.bullish == control_bull and is_alive_state(snapshot_k[z.id])
                    for z in engine.rbs if z.id in snapshot_k
                )
                if old_side_alive:
                    control = "BOTH"
                    controlling_zone_id = None
                    body_zone_id = None
                    for z in opp_impacts:
                        log(k, "OPPOSING_ENCOUNTER", f"Opposing RB zone {z.id} impacted, old side still active -> BOTH", z.id)
                else:
                    new_zone = opp_impacts[0]
                    control = "BUY_ONLY" if new_zone.bullish else "SELL_ONLY"
                    control_bull = new_zone.bullish
                    controlling_zone_id = new_zone.id
                    body_zone_id = new_zone.id
                    log(k, "CONTROL_SWITCHED", f"Old side exhausted; RB zone {new_zone.id} impacted -> {control}", new_zone.id)

        if control == "BOTH" and controlling_opp is None:
            for candidate_bull in (True, False):
                need_kind_weeks = swing_high_weeks if candidate_bull else swing_low_weeks
                candidates = [
                    z for z in engine.rbs
                    if z.bullish == candidate_bull and z.id in snapshot_k and is_spent_state(snapshot_k[z.id])
                ]
                other_side_alive = any(
                    z.bullish != candidate_bull and is_alive_state(snapshot_k[z.id])
                    for z in engine.rbs if z.id in snapshot_k
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
                    body_zone_id = z.id
                    log(k, "OPPOSING_GAINS_CONTROL", f"RB zone {z.id} confirmed swing at week {confirmed_after[0]}, other side exhausted", z.id)
                    break
                if controlling_opp is not None:
                    break

        if controlling_opp is not None:
            opp_zone = next((z for z in engine.rbs if z.id == controlling_opp), None)
            if opp_zone is not None and controlling_opp in newly_oob_ids:
                log(k, "OPPOSING_LOSES_CONTROL", f"RB zone {controlling_opp} stranded (ORB)", controlling_opp)
                controlling_opp = None
                controlling_zone_id = None
                other_opp_alive = any(
                    z.bullish != control_bull and is_alive_state(snapshot_k[z.id])
                    for z in engine.rbs if z.id in snapshot_k
                )
                pro_alive = any(
                    z.bullish == control_bull and is_alive_state(snapshot_k[z.id])
                    for z in engine.rbs if z.id in snapshot_k
                )
                if other_opp_alive:
                    control = "BOTH"
                    body_zone_id = None
                elif pro_alive:
                    control = "BUY_ONLY" if control_bull else "SELL_ONLY"
                    log(k, "RETURN_TO_PRO_TREND", f"No opposing RB zone remains active -> {control}", None)
                    # No specific zone id is tracked for the "pro" side at
                    # this branch either (controlling_zone_id is left None
                    # here too, an existing quirk of this port -- see
                    # controlling_zone_id above), so body_zone_id follows
                    # suit rather than guessing which pro zone to attribute
                    # this to.
                    body_zone_id = None
                else:
                    control = "NONE"
                    body_zone_id = None
                    log(k, "NO_CONTROL", "No active RB zone on either side", None)

        # --- NEW CONTROL-LAYER CHECK (independent of all the event-based
        # transitions above): a zone that gained sole BUY_ONLY/SELL_ONLY
        # control dies a SECOND way if a later Weekly candle's own CLOSE
        # lands back inside that zone's [bottom, top] range -- "especially
        # the first one, two, or few candles" reacting to it (user's own
        # framing). This is a NEW rule at the CONTROL state-machine layer
        # only; RB's own zone lifecycle (impact + stranding only, no
        # close-through) is unchanged -- see substitution #4 above, which
        # still stands unmodified for zone lifecycle. Checked every week
        # from the zone's own impact week onward (inclusive: the impact
        # week's own close is the first candle that can react, since impact
        # can land mid-week before that week's candle has closed), using the
        # engine's own already-aggregated Weekly OHLC (weeks[k].c), not a
        # hand-rolled recomputation.
        # Deliberately NOT gated on `control != "NONE"`: this check must run
        # independently of whatever the event-based transitions above did to
        # `control` THIS SAME week (e.g. a same-week SWING_PAUSE can already
        # have dropped control to NONE by the time this runs, as happens for
        # RB zone 2's own impact week -- see RB_TRADING_SYSTEM_HANDOFF.md).
        # The body-close check still evaluates and, if it independently
        # confirms a violation, logs it (a no-op on `control` if already
        # NONE, but the event record itself is the point -- it documents
        # THIS reason, distinct from whatever else already zeroed control).
        if body_zone_id is not None:
            bz = next((zz for zz in engine.rbs if zz.id == body_zone_id), None)
            if bz is not None and bz.stop is not None and k >= bz.stop:
                close_k = weeks[k].c
                if bz.zb <= close_k <= bz.zt:
                    log(k, "BODY_CLOSE_VIOLATION",
                        f"Week {k} close {close_k} falls inside controlling RB zone {bz.id}'s "
                        f"range [{bz.zb},{bz.zt}] -> NONE", bz.id, at_override=weeks[k].end)
                    control = "NONE"
                    control_bull = False
                    controlling_zone_id = None
                    controlling_opp = None
                    paused_bull = None
                    body_zone_id = None

        weekly_rows.append((k, trend, control, str(controlling_opp) if controlling_opp else "", str(controlling_zone_id) if controlling_zone_id else ""))

    write_outputs(base, weeks, weekly_rows, events, display_tz)
    print("Created:")
    print("  weekly_control_ledger_rb.csv")
    print("  weekly_control_events_rb.csv")
    print("  weekly_control_report_rb.txt")
    print(f"Processed {n} weeks. {len(events)} control-relevant events logged.")
    return 0


def write_outputs(base: Path, weeks, weekly_rows, events: List[ControlEvent], display_tz: ZoneInfo) -> None:
    with (base / "weekly_control_ledger_rb.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["week_index", "week_start_utc", "week_start_riyadh", "trend", "control", "controlling_opposing_zone_id", "controlling_zone_id"])
        for k, trend, control, opp_id, controlling_zone_id in weekly_rows:
            wk = weeks[k]
            wr.writerow([k, wob.iso(wk.start), wob.display_iso(wk.start, display_tz), trend, control, opp_id, controlling_zone_id])

    with (base / "weekly_control_events_rb.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["week_index", "week_start_utc", "week_start_riyadh", "event", "detail", "zone_id", "trend_after", "control_after"])
        for e in events:
            wr.writerow([e.week, wob.iso(e.at_utc), wob.display_iso(e.at_utc, display_tz), e.kind, e.detail, e.zone_id or "", e.trend, e.control])

    lines = [
        "RB-NATIVE WEEKLY DIRECTION-CONTROL STATE MACHINE",
        "",
        "Rule-for-rule port of weekly_control_engine.py, driven on RB's own",
        "IRB/ARB/ORB/SPENT zone/event timeline instead of OB's. See the module",
        "docstring in weekly_control_engine_rb.py for the full substitution",
        "reasoning (rejected flag, is_alive/is_spent, body_close_dead).",
        "",
        "SUBSTITUTIONS MADE (verify against RB_Indicator_v1.pine):",
        "1. `rejected` -- RB has no such field; hardwired absent (RbZone has",
        "   no rejected attribute at all).",
        "2. is_alive_state: state in (0,1) [IRB/ARB] -- RB's state family has",
        "   no 3rd alive type (no AIFOB-equivalent promotion).",
        "3. is_spent_state: state == 3 [SPENT], trivial once rejected is gone.",
        "4. body_close_dead -- NOT PORTED. RB_Indicator_v1.pine's header says",
        "   in so many words: wick IMPACT + STRANDING only, no close-through",
        "   rule. There is no RB fact this could substitute with (once",
        "   SPENT, RB's own lifecycle never revisits a zone again). The",
        "   single-side ZONE_DEATH transition this enables in OB's control",
        "   engine is simply absent here; single-side control only changes",
        "   via swing-pause/resume or opposing-impact escalation.",
        "5. newly_oob_ids -- RB's stranding-to-ORB (state 2) is the direct",
        "   analog of OB's stranding-to-OOB (state 2); used unchanged for",
        "   OPPOSING_LOSES_CONTROL.",
        "",
        f"Weeks processed: {len(weeks)}",
        f"Control-relevant events: {len(events)}",
    ]
    (base / "weekly_control_report_rb.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
