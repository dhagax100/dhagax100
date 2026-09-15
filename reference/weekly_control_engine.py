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
from typing import Dict, List, Optional
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
# OPPOSING_LOSES_CONTROL, RETURN_TO_PRO_TREND, NO_CONTROL


def is_pro(z: "wob.Zone", trend: int) -> bool:
    """Direction-vs-current-trend classification (SPEC.md SS15 wording: 'old'
    and 'aggressive' POIs become opposing purely by direction after a trend
    flip -- not by their orig_state family)."""
    if trend == 1:
        return z.bullish
    if trend == 2:
        return not z.bullish
    return False


def is_alive(z: "wob.Zone") -> bool:
    """Not rejected, not OOB (stranded), not yet spent -- i.e. still capable
    of forcing or contributing to control."""
    return not z.rejected and z.state in (0, 1, 4)


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
    trend_at: List[int] = []
    for k in range(len(weeks)):
        engine.process(k)
        trend_at.append(engine.regime)

    n = len(weeks)
    # Week -> zones impacted that week (already-finalized facts, safe to index
    # post-hoc since we only ever look at week k using trend_at[<=k] and zone
    # facts whose own week index is <= k).
    impacts_by_week: Dict[int, List["wob.Zone"]] = {}
    for z in engine.zones:
        if z.state == 3 and 0 <= z.stop < n:
            impacts_by_week.setdefault(z.stop, []).append(z)
    swing_high_weeks = sorted({e.confirm for e in engine.events if e.kind == 0})
    swing_low_weeks = sorted({e.confirm for e in engine.events if e.kind == 1})

    # Track OOB/rejected transitions week-by-week for "loses control".
    prev_state: Dict[int, int] = {}
    prev_rejected: Dict[int, bool] = {}

    trend = "UNDEFINED"
    control = "NONE"
    controlling_opp: Optional[int] = None  # zone id currently holding full opposing control
    controlling_zone_id: Optional[int] = None  # the single Weekly zone responsible for the
    # ACTIVE single-direction control (BUY_ONLY/SELL_ONLY), for H4 parent-zone linkage.
    # None while control is NONE or BOTH (BOTH has two sides, no single "the" zone).
    events: List[ControlEvent] = []
    weekly_rows = []

    def log(k: int, kind: str, detail: str, zone_id: Optional[int]) -> None:
        at = weeks[k].start
        events.append(ControlEvent(k, at, kind, detail, zone_id, trend, control))

    for k in range(n):
        new_trend = TREND[trend_at[k]]
        if new_trend != trend:
            trend = new_trend
            # Trend is a separate, structural fact (SPEC.md SS9). A flip does
            # NOT by itself change control -- control only changes through the
            # explicit transfer rules below (campaign start/stop, opposing
            # encounter/gain/lose, no-control). An active campaign carries
            # straight through a trend flip until one of those rules fires.
            log(k, "TREND_FLIP", f"Weekly trend -> {trend}", None)

        zones_this_week = [z for z in engine.zones if z.candle <= k]
        impacts_this_week = impacts_by_week.get(k, [])

        # OOB / rejection transitions this week, for "loses control".
        newly_oob, newly_rejected = [], []
        for z in zones_this_week:
            was_state = prev_state.get(z.id, z.created_state)
            was_rej = prev_rejected.get(z.id, False)
            if z.state == 2 and was_state != 2:
                newly_oob.append(z)
            if z.rejected and not was_rej:
                newly_rejected.append(z)
            prev_state[z.id] = z.state
            prev_rejected[z.id] = z.rejected

        if trend == "UNDEFINED":
            weekly_rows.append((k, trend, control, "", ""))
            continue

        # From here on, "pro"/"opposing" for control-escalation purposes are
        # relative to the ESTABLISHED CONTROL DIRECTION, not structural trend
        # (SPEC.md SS9: trend and control are independent states; a control
        # campaign can start opposite of trend -- see decision #6 below).
        control_bull = control == "BUY_ONLY"

        # 1) Campaign start/resume from NONE: whichever POI (either
        #    direction) is impacted first starts control in ITS OWN
        #    direction. Implements SS16's "wait until price encounters a
        #    valid Weekly POI of either direction, process normally."
        if control == "NONE" and impacts_this_week:
            first = impacts_this_week[0]
            control = "BUY_ONLY" if first.bullish else "SELL_ONLY"
            control_bull = first.bullish
            controlling_zone_id = first.id
            kind = "CAMPAIGN_START" if is_pro(first, trend_at[k]) else "CAMPAIGN_START_COUNTERTREND"
            log(k, kind, f"Zone {first.id} impacted (direction={'BUY' if first.bullish else 'SELL'}, trend={trend})", first.id)

        # 2) A zone opposite the CONTROLLING direction gets impacted. Only
        #    escalate to BOTH if the CURRENT controlling side still has a
        #    live, unspent zone (a genuine concurrent thesis). If the old
        #    side already delivered its reaction and is spent, there is
        #    nothing to run concurrently with -- switch control straight to
        #    the new zone's direction instead.
        if control in ("BUY_ONLY", "SELL_ONLY"):
            opp_impacts = [z for z in impacts_this_week if z.bullish != control_bull]
            if opp_impacts:
                old_side_alive = any(z.bullish == control_bull and is_alive(z) for z in engine.zones if z.candle <= k)
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
                candidates = [z for z in engine.zones if z.bullish == candidate_bull and z.state == 3 and not z.rejected]
                other_side_alive = any(z.bullish != candidate_bull and is_alive(z) for z in engine.zones if z.candle <= k)
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
            if opp_zone is not None and opp_zone in newly_oob + newly_rejected:
                log(k, "OPPOSING_LOSES_CONTROL", f"Zone {controlling_opp} breached", controlling_opp)
                controlling_opp = None
                controlling_zone_id = None
                other_opp_alive = any(z.bullish != control_bull and is_alive(z) for z in engine.zones if z.candle <= k)
                pro_alive = any(z.bullish == control_bull and is_alive(z) for z in engine.zones if z.candle <= k)
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

        # 5) DISABLED (SPECIFICATION_PENDING). A prior version dropped control
        #    to NONE the week after the founding zone itself became spent --
        #    but a spent founding zone is not an invalidation; the campaign
        #    persists as a state until a real transfer event fires (opposing
        #    encounter/switch above), per the user's explicit rule: "keep
        #    selling until we come across another OB." SPEC.md SS16's actual
        #    no-control case (a confirmed swing forms with NO POI reaction
        #    behind it) is a different, more specific check this module does
        #    not yet implement -- do not approximate it with "is the founding
        #    zone still unspent," which is what caused the bug.

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
