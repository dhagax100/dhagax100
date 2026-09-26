#!/usr/bin/env python3
"""OB+RB+FVG Weekly direction-control state machine -- ONE unified pool.

Direct generalization of reference_rb/weekly_rb_control_engine.py's own
state machine (BUY_ONLY/SELL_ONLY/BOTH/NONE, respect-vs-anchor-break,
swing-pause+resume with same-minute-collision handling, parent-in-charge)
to a merged candidate pool of ALL THREE POI types at once, per explicit
user direction (2026-09-26): "everything is the same in terms of POI to
POI control shift... this time all the POIs are the same, they just have
different names." Concretely, this means:

  - A zone's IDENTITY at the control layer is just (label, bullish,
    protect_level, zb, zt, impact_time) -- OB, RB and FVG zones are
    interchangeable inputs to the SAME state machine, not three separate
    ones merged after the fact.
  - ANCHOR BREAK uses each zone's own `protect_level` (the supporting
    swing point, added 2026-09-26 to all three types), NOT its own box
    edge -- this is what FVG's control walk already established as the
    correct rule (docs_fvg/FVG_RULES_LEARNED.md item 1: "This is NOT a bug
    in RB's own engine -- RB zones are built directly from a swing-pivot
    candle's wick, so their box edge IS their supporting swing's price by
    construction" -- meaning for RB, protect_level and the box edge are
    numerically the SAME value anyway, so using protect_level uniformly
    changes nothing for RB while being the geometrically correct level for
    OB and FVG too).
  - WEEKLY-CLOSE BODY-BREACH (the "candle close" death, SPEC.md SS14) still
    checks each zone's own zb/zt (near edge) -- this is the CONTROL layer's
    own death rule, distinct from FVG's zone-lifecycle CLOSE_THROUGH
    (far edge, a different concept at a different layer -- see
    docs_fvg/FVG_RULES_LEARNED.md's own note on this not being the same
    threshold). Applied identically to all three types here.
  - Every other rule (opposing-impact always -> BOTH, respect vs
    anchor-break/body-death resolving BOTH, same-minute collision
    handling, parent-in-charge tracked per side independent of control
    state) is IDENTICAL to RB's own engine, unchanged.

FIRST PASS. Not yet cross-checked against a hand-walked gate table the way
RB's own engine was validated -- treat its output as a starting point for
manual verification, same discipline every other control engine in this
project was held to before being trusted.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference", _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob        # noqa: E402
import weekly_rb_generator as wrb        # noqa: E402
import weekly_fvg_generator as wfvg      # noqa: E402
import weekly_combined_generator as wc   # noqa: E402

UTC = timezone.utc


@dataclass
class UnifiedZone:
    label: str          # e.g. "FVG#1"
    bullish: bool
    protect_level: Optional[float]
    zb: float
    zt: float
    impact_time: Optional[datetime]


@dataclass
class ControlEvent:
    at_utc: Optional[datetime]
    kind: str
    detail: str
    zone_label: Optional[str]
    control: str
    sell_parent: str
    buy_parent: str


def first_breach(mt: List[datetime], lo: List[float], hi: List[float], start: datetime,
                  level: float, above: bool) -> Optional[datetime]:
    i = bisect_left(mt, start)
    n = len(mt)
    while i < n:
        if (hi[i] > level) if above else (lo[i] < level):
            return mt[i]
        i += 1
    return None


def week_at(weeks: List["wob.Week"], t: datetime) -> Optional[int]:
    starts = [w.start for w in weeks]
    i = bisect_left(starts, t)
    if i < len(starts) and starts[i] == t:
        return i
    return i - 1 if i > 0 else None


def build_unified_zones(engine: "wc.WeeklyCombinedEngine") -> List[UnifiedZone]:
    out: List[UnifiedZone] = []
    for z in engine.ob_zones:
        if z.rejected:
            continue
        out.append(UnifiedZone(f"OB#{z.id}", z.bullish, z.protect_level, z.zb, z.zt, z.impact_time))
    for z in engine.rb_zones:
        out.append(UnifiedZone(f"RB#{z.id}", z.bullish, z.protect_level, z.zb, z.zt, z.impact_time))
    for z in engine.fvg_zones:
        out.append(UnifiedZone(f"FVG#{z.id}", z.bullish, z.protect_level, z.zb, z.zt, z.impact_time))
    return out


def run_control_walk(engine: "wc.WeeklyCombinedEngine", weeks: List["wob.Week"], minutes: List["wob.Minute"]) -> List[ControlEvent]:
    zones = build_unified_zones(engine)
    mt = [m.t for m in minutes]
    lo = [m.l for m in minutes]
    hi = [m.h for m in minutes]

    impacts = sorted([z for z in zones if z.impact_time is not None], key=lambda z: z.impact_time)
    swing_highs = sorted([e for e in engine.events if e.kind == 0 and e.at is not None], key=lambda e: e.at)
    swing_lows = sorted([e for e in engine.events if e.kind == 1 and e.at is not None], key=lambda e: e.at)
    sh_times = [e.at for e in swing_highs]
    sl_times = [e.at for e in swing_lows]

    def next_swing(times: List[datetime], after: datetime) -> Optional[datetime]:
        i = bisect_left(times, after)
        while i < len(times) and times[i] <= after:
            i += 1
        return times[i] if i < len(times) else None

    def next_impact(side_bull: Optional[bool], after: datetime) -> Optional[UnifiedZone]:
        i = bisect_left([z.impact_time for z in impacts], after)
        while i < len(impacts) and impacts[i].impact_time <= after:
            i += 1
        while i < len(impacts):
            if side_bull is None or impacts[i].bullish == side_bull:
                return impacts[i]
            i += 1
        return None

    def impact_at_exact(side_bull: Optional[bool], at: datetime) -> Optional[UnifiedZone]:
        for z in impacts:
            if z.impact_time == at and (side_bull is None or z.bullish == side_bull):
                return z
        return None

    def parent_at(side_bull: bool, t: datetime) -> str:
        best = None
        for z in impacts:
            if z.bullish == side_bull and z.impact_time <= t:
                best = z
            elif z.impact_time > t:
                break
        return best.label if best is not None else ""

    def body_close_dead_after(z: UnifiedZone, start: datetime) -> Optional[datetime]:
        wi = week_at(weeks, start)
        if wi is None:
            return None
        for w in weeks[wi:]:
            if w.end < start:
                continue
            inside = (w.c >= z.zb) if not z.bullish else (w.c <= z.zt)
            if inside:
                return w.end
        return None

    events: List[ControlEvent] = []
    end_of_data = mt[-1]

    def log(at: datetime, kind: str, detail: str, zone_label: Optional[str], control: str) -> None:
        events.append(ControlEvent(at, kind, detail, zone_label, control, parent_at(False, at), parent_at(True, at)))

    t = mt[0]
    control = "NONE"
    paused_bull: Optional[bool] = None
    challenger: Optional[UnifiedZone] = None
    pre_both_bull: Optional[bool] = None
    anchor_zone: Optional[UnifiedZone] = None

    guard = 0
    while t < end_of_data and guard < 5000:
        guard += 1

        if control == "NONE":
            imp = next_impact(None, t)
            resume_at = None
            if paused_bull is not None:
                resume_at = next_swing(sh_times if paused_bull is False else sl_times, t)
            candidates = [c for c in (
                (imp.impact_time, "impact", imp) if imp else None,
                (resume_at, "resume", None) if resume_at else None,
            ) if c is not None]
            if not candidates:
                break
            candidates.sort(key=lambda c: c[0])
            at, kind_, payload = candidates[0]
            same_minute_opp = None
            if paused_bull is not None and resume_at == at:
                want_bull = paused_bull
                same_minute_opp = impact_at_exact(not want_bull, at)
            if same_minute_opp is not None:
                control = "BOTH"
                challenger = same_minute_opp
                pre_both_bull = paused_bull
                paused_bull = None
                log(at, "SWING_RESUME_COLLIDES_WITH_IMPACT",
                    f"Swing {'high' if not want_bull else 'low'} resumes {('SELL' if not want_bull else 'BUY')} "
                    f"same minute zone {challenger.label} impacts -> BOTH", challenger.label, control)
                t = at
                continue
            if kind_ == "impact":
                z = payload
                control = "BUY_ONLY" if z.bullish else "SELL_ONLY"
                anchor_zone = z
                paused_bull = None
                log(at, "CAMPAIGN_START", f"Zone {z.label} impacted (from NONE) -> {control}", z.label, control)
                t = at
                continue
            else:
                control = "BUY_ONLY" if paused_bull else "SELL_ONLY"
                anchor_zone = None
                log(at, "SWING_RESUME", f"Swing {'high' if not paused_bull else 'low'} confirms -> {control}", None, control)
                paused_bull = None
                t = at
                continue

        if control in ("BUY_ONLY", "SELL_ONLY"):
            control_bull = control == "BUY_ONLY"
            opp = next_impact(not control_bull, t)
            parent_label = parent_at(control_bull, t)
            death_at = body_close_dead_after(next(z for z in impacts if z.label == parent_label), t) if parent_label else None
            anchor_break_at = None
            if anchor_zone is not None and anchor_zone.protect_level is not None:
                anchor_break_at = first_breach(mt, lo, hi, t, anchor_zone.protect_level, above=not control_bull)
            pause_at = next_swing(sh_times if control_bull else sl_times, t)

            cands = [c for c in (
                (opp.impact_time, "opp_impact", opp) if opp else None,
                (death_at, "death", None) if death_at else None,
                (anchor_break_at, "anchor_break", None) if anchor_break_at else None,
                (pause_at, "pause", None) if pause_at else None,
            ) if c is not None]
            if not cands:
                break
            cands.sort(key=lambda c: c[0])
            at, kind_, payload = cands[0]

            if kind_ == "opp_impact":
                z = payload
                control = "BOTH"
                challenger = z
                pre_both_bull = control_bull
                log(at, "OPPOSING_ENCOUNTER", f"Zone {z.label} impacted -> BOTH", z.label, control)
                t = at
                continue
            if kind_ == "death":
                same_side = impact_at_exact(control_bull, at)
                if same_side is not None:
                    anchor_zone = same_side
                    log(at, "ZONE_DEATH_BUT_REINFORCED", f"Zone {parent_label} dies, zone {same_side.label} impacts same minute -> stays {control}", same_side.label, control)
                    t = at
                    continue
                log(at, "ZONE_DEATH", f"Zone {parent_label} closes body inside/through its own box -> NONE", parent_label, "NONE")
                control = "NONE"
                paused_bull = None
                anchor_zone = None
                t = at
                continue
            if kind_ == "anchor_break":
                new_control = "SELL_ONLY" if control_bull else "BUY_ONLY"
                log(at, "ANCHOR_BREAK_FLIP", f"Zone {anchor_zone.label}'s own protect_level breached -> {new_control}", anchor_zone.label, new_control)
                control = new_control
                anchor_zone = None
                t = at
                continue
            same_minute_opp = impact_at_exact(not control_bull, at)
            if same_minute_opp is not None:
                control = "BOTH"
                challenger = same_minute_opp
                pre_both_bull = control_bull
                log(at, "PAUSE_COLLIDES_WITH_IMPACT", f"Swing confirms same minute zone {challenger.label} impacts -> BOTH", challenger.label, control)
                t = at
                continue
            same_side_imp = impact_at_exact(control_bull, at)
            if same_side_imp is not None:
                anchor_zone = same_side_imp
                log(at, "PAUSE_OVERRIDDEN_BY_IMPACT", f"Swing confirms same minute zone {same_side_imp.label} impacts -> stays {control}", same_side_imp.label, control)
                t = at
                continue
            log(at, "SWING_PAUSE", f"{'Swing high' if control_bull else 'Swing low'} confirms, no opposing zone -> NONE", None, "NONE")
            paused_bull = control_bull
            control = "NONE"
            anchor_zone = None
            t = at
            continue

        if control == "BOTH":
            resp_kind_times = sl_times if challenger.bullish else sh_times
            respect_at = next_swing(resp_kind_times, t)
            break_at = first_breach(mt, lo, hi, t, challenger.zb if challenger.bullish else challenger.zt, above=not challenger.bullish)
            body_death_at = body_close_dead_after(challenger, t)
            cands = [c for c in (
                (respect_at, "respect", None) if respect_at else None,
                (break_at, "break", None) if break_at else None,
                (body_death_at, "body_death", None) if body_death_at else None,
            ) if c is not None]
            if not cands:
                break
            cands.sort(key=lambda c: c[0])
            at, kind_, _ = cands[0]
            if kind_ == "respect":
                new_control = "BUY_ONLY" if challenger.bullish else "SELL_ONLY"
                log(at, "RESPECT_FULL_FLIP", f"Zone {challenger.label} respected -> {new_control}", challenger.label, new_control)
                control = new_control
                anchor_zone = challenger
            else:
                new_control = "BUY_ONLY" if pre_both_bull else "SELL_ONLY"
                kind_label = "ANCHOR_BREAK_REVERT" if kind_ == "break" else "BODY_DEATH_REVERT"
                reason = "own level breached, no respect" if kind_ == "break" else "closes body inside/through its own box"
                log(at, kind_label, f"Zone {challenger.label}'s {reason} -> {new_control}", challenger.label, new_control)
                control = new_control
                anchor_zone = None
            challenger = None
            pre_both_bull = None
            t = at
            continue

        break

    return events


def write_outputs(base: Path, events: List[ControlEvent], display_tz: ZoneInfo) -> None:
    with (base / "weekly_combined_control_events.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["at_utc", "at_riyadh", "event", "detail", "zone_label", "control", "sell_parent", "buy_parent"])
        for e in events:
            wr.writerow([wob.iso(e.at_utc), wob.display_iso(e.at_utc, display_tz), e.kind, e.detail,
                         e.zone_label or "", e.control, e.sell_parent, e.buy_parent])
    lines = [
        "OB+RB+FVG WEEKLY UNIFIED DIRECTION-CONTROL STATE MACHINE -- FIRST PASS, UNVERIFIED",
        "",
        f"Control-relevant events: {len(events)}",
    ]
    (base / "weekly_combined_control_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OB+RB+FVG Weekly unified direction-control state machine")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
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
        engine = wc.WeeklyCombinedEngine(minutes, weeks)
        engine.run()
        events = run_control_walk(engine, weeks, minutes)
        write_outputs(base, events, display_tz)
        print("Created:")
        print("  weekly_combined_control_events.csv")
        print("  weekly_combined_control_report.txt")
        print(f"{len(events)} control-relevant events logged.")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
