#!/usr/bin/env python3
"""RB Weekly direction-control state machine.

RB counterpart of reference/weekly_control_engine.py (OB's own control
engine). Same idea -- an ADDITIVE layer over the locked WeeklyRBEngine,
never recomputing swing/MSS/zone facts -- but RB's control rules are NOT
the same as OB's; they were derived independently this session (2026-09-24)
by walking 34 gates by hand against raw M1 data, and OB's engine does not
implement several of them. Differences from OB's engine, all load-bearing:

  - PARENT-IN-CHARGE = the last REACTED (impacted) zone on a side, tracked
    globally and independently of control state -- updates the instant any
    zone on that side is impacted, never on mere creation, and never resets
    when control changes direction or drops to NONE. See
    docs_rb/RB_RULES_LEARNED.md's "Parent-in-charge rule, corrected" entry.
  - EVERY opposing impact goes to BOTH, unconditionally (no OB-style
    direct-switch-if-old-side-already-spent exception).
  - BOTH resolves one of two ways, decided by whichever happens FIRST after
    the challenging zone's own impact: (a) RESPECT -- a swing of the
    challenger's own protecting kind (LOW for a BUY zone, HIGH for a SELL
    zone) formally CONFIRMS before the challenger's own zb/zt is breached
    -> full flip to the challenger's side, at the confirm minute; (b) ANCHOR
    BREAK -- price breaches the challenger's own zb/zt first, with no
    respect swing yet -> reverts to whichever side was controlling before
    BOTH started.
  - A single-direction campaign's SOLE controlling zone having its OWN
    zb/zt breached in real time (not a generic/unrelated swing elsewhere)
    flips control DIRECTLY to the opposite side -- no NONE in between.
  - A genuinely unrelated formal swing confirming opposite the current
    control direction (not the controlling zone's own level) PAUSES to
    NONE, resuming later via the opposite-kind swing (mirrors OB's
    SWING_PAUSE/SWING_RESUME, same polarity).
  - Weekly-close body-breach (SPEC.md SS14, same rule OB uses) can also end
    a single-direction campaign, on top of the above.
  - Collision rule: if an opposing impact and a would-be pause/resume swing
    land in the EXACT SAME M1 minute, the impact wins -- control goes to
    BOTH (or starts fresh) rather than pausing to NONE first. If a SAME-side
    impact collides with what would otherwise be a pausing opposite-swing,
    the campaign continues uninterrupted (only the parent updates).

FIRST PASS. Validate this against docs_rb's hand-verified 34-gate table
(`reference_rb/full_rb_viewer.py`'s `build_manual_rb_gates()`) before
trusting it over that table -- see `validate_against_manual_gates()` below,
which does exactly that comparison and prints every mismatch. Treat every
gate this engine produces as unverified until it matches, the same
discipline OB's own control engine was held to.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))
import weekly_ob_generator as wob  # noqa: E402  (locked engine, unmodified -- Minute/Week/Event/MSS/load_minutes/aggregate_weeks)
import weekly_rb_generator as rb   # noqa: E402  (locked-per-project RB engine -- WeeklyRBEngine/RBZone/status)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RB Weekly direction-control state machine (additive layer)")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    return p.parse_args()


@dataclass
class ControlEvent:
    at_utc: Optional[datetime]
    kind: str
    detail: str
    zone_id: Optional[int]
    control: str
    sell_parent: str
    buy_parent: str


def first_breach(mt: List[datetime], lo: List[float], hi: List[float], start: datetime,
                  level: float, above: bool) -> Optional[datetime]:
    """First M1 minute at/after `start` where price crosses `level` --
    high > level if `above`, else low < level. mt/lo/hi are the minutes'
    own .t/.l/.h lists (parallel arrays), for a fast bisect + linear scan."""
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
    engine = rb.WeeklyRBEngine(minutes, weeks)
    engine.run()

    mt = [m.t for m in minutes]
    lo = [m.l for m in minutes]
    hi = [m.h for m in minutes]

    zones = engine.zones
    impacts = sorted([z for z in zones if z.impact_time is not None], key=lambda z: z.impact_time)
    swing_highs = sorted([e for e in engine.events if e.kind == 0 and e.at is not None], key=lambda e: e.at)
    swing_lows = sorted([e for e in engine.events if e.kind == 1 and e.at is not None], key=lambda e: e.at)
    sh_times = [e.at for e in swing_highs]
    sl_times = [e.at for e in swing_lows]

    def next_swing(times: List[datetime], after: datetime) -> Optional[datetime]:
        i = bisect_left(times, after)
        # strictly after `after` -- an event AT exactly `after` is the one
        # that just fired, never its own resume/respect trigger.
        while i < len(times) and times[i] <= after:
            i += 1
        return times[i] if i < len(times) else None

    def next_impact(side_bull: Optional[bool], after: datetime) -> Optional["rb.RBZone"]:
        i = bisect_left([z.impact_time for z in impacts], after)
        while i < len(impacts) and impacts[i].impact_time <= after:
            i += 1
        while i < len(impacts):
            if side_bull is None or impacts[i].bullish == side_bull:
                return impacts[i]
            i += 1
        return None

    def impact_at_exact(side_bull: Optional[bool], at: datetime) -> Optional["rb.RBZone"]:
        """Is some zone impacted at EXACTLY this minute (optionally filtered
        by side)? Deliberately separate from next_impact(), which always
        skips anything at/before its `after` argument -- reused for that
        purpose, it can never see a same-minute collision by construction.
        That was a real bug here (2026-09-24): every same-minute-collision
        check below (resume-vs-impact, pause-vs-impact, death-vs-impact)
        silently never fired, because they all misused next_impact() for
        this instead."""
        for z in impacts:
            if z.impact_time == at and (side_bull is None or z.bullish == side_bull):
                return z
        return None

    # PARENT-IN-CHARGE: pure function of impact history, independent of
    # control state -- computed once, looked up by time whenever needed.
    def parent_at(side_bull: bool, t: datetime) -> str:
        best = None
        for z in impacts:
            if z.bullish == side_bull and z.impact_time <= t:
                best = z
            elif z.impact_time > t:
                break
        return f"{best.id}" if best is not None else ""

    def body_close_dead_after(z: "rb.RBZone", start: datetime) -> Optional[datetime]:
        """First Weekly close AT/AFTER `start` landing inside/through z's
        own box (SPEC.md SS14, same rule OB uses) -- returns that week's
        own end (=close) time, or None if it never happens in-dataset.

        Real bug, found 2026-09-24: filtered candidate weeks by `w.start <
        start`, which wrongly skips the very week whose CLOSE is the thing
        actually being checked, whenever `start` falls mid-week (the normal
        case -- a zone impact rarely lands exactly on a week boundary).
        Zone #8's own death (close 1.17446 >= zb 1.17354, at the week
        ending 2026-05-11 Riyadh) was silently skipped this way -- its
        containing week started 05-04, before the 05-06 13:45 impact `t`
        this was called with, so `w.start < start` discarded it even though
        its END (the actual close event) was still ahead. Filter by
        `w.end`, not `w.start`, matching what's actually being tested."""
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

    def log(at: datetime, kind: str, detail: str, zone_id: Optional[int], control: str) -> None:
        events.append(ControlEvent(at, kind, detail,
                                    zone_id, control, parent_at(False, at), parent_at(True, at)))

    t = mt[0]
    control = "NONE"
    paused_bull: Optional[bool] = None  # which side was paused, if NONE was entered via a swing pause

    # BOTH-state bookkeeping: which zone is the "challenger" being watched
    # for respect-vs-anchor-break, and which side was controlling before it.
    challenger: Optional["rb.RBZone"] = None
    pre_both_bull: Optional[bool] = None
    # Single-direction bookkeeping: the zone whose OWN level, if breached
    # in real time with nothing else intervening, flips control directly.
    anchor_zone: Optional["rb.RBZone"] = None

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
            # collision: an opposing impact at the SAME minute as a resume
            # -> BOTH directly (matches gate 8->9's 05-06 13:45 case and
            # gate 16->17's 06-05 16:00 case). Checked against the WINNING
            # timestamp directly, not "whichever candidate the sort picked"
            # -- a real bug here (2026-09-24): when impact and resume tie
            # exactly, the impact candidate was always listed (and so always
            # sorted) first, so `kind_ == "resume"` never matched on a tie
            # and this collision check silently never fired.
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
                    f"same minute zone {challenger.id} impacts -> BOTH", challenger.id, control)
                t = at
                continue
            if kind_ == "impact":
                z = payload
                control = "BUY_ONLY" if z.bullish else "SELL_ONLY"
                anchor_zone = z
                paused_bull = None
                log(at, "CAMPAIGN_START", f"Zone {z.id} impacted (from NONE) -> {control}", z.id, control)
                t = at
                continue
            else:
                control = "BUY_ONLY" if paused_bull else "SELL_ONLY"
                anchor_zone = None  # resumed campaign has no single fresh anchor zone (generic resume)
                log(at, "SWING_RESUME", f"Swing {'high' if not paused_bull else 'low'} confirms -> {control}", None, control)
                paused_bull = None
                t = at
                continue

        if control in ("BUY_ONLY", "SELL_ONLY"):
            control_bull = control == "BUY_ONLY"
            opp = next_impact(not control_bull, t)
            death_at = body_close_dead_after(next(z for z in impacts if f"{z.id}" == parent_at(control_bull, t)), t) \
                if parent_at(control_bull, t) else None
            anchor_break_at = None
            if anchor_zone is not None:
                anchor_break_at = first_breach(mt, lo, hi, t,
                                                anchor_zone.zb if control_bull else anchor_zone.zt,
                                                above=not control_bull)
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
                # same-minute same-side impact reinforcing instead? already
                # excluded (opp is opposite-side by construction).
                control = "BOTH"
                challenger = z
                pre_both_bull = control_bull
                log(at, "OPPOSING_ENCOUNTER", f"Zone {z.id} impacted -> BOTH", z.id, control)
                t = at
                continue
            if kind_ == "death":
                zid = int(parent_at(control_bull, at))
                # same-minute reinforcement: does a same-side zone impact
                # at this exact minute keep the campaign alive instead?
                same_side = impact_at_exact(control_bull, at)
                if same_side is not None:
                    anchor_zone = same_side
                    log(at, "ZONE_DEATH_BUT_REINFORCED", f"Zone {zid} dies, zone {same_side.id} impacts same minute -> stays {control}", same_side.id, control)
                    t = at
                    continue
                log(at, "ZONE_DEATH", f"Zone {zid} closes body inside/through its own box -> NONE", zid, "NONE")
                control = "NONE"
                paused_bull = None
                anchor_zone = None
                t = at
                continue
            if kind_ == "anchor_break":
                zid = anchor_zone.id
                new_control = "SELL_ONLY" if control_bull else "BUY_ONLY"
                log(at, "ANCHOR_BREAK_FLIP", f"Zone {zid}'s own level breached -> {new_control}", zid, new_control)
                control = new_control
                anchor_zone = None
                t = at
                continue
            # pause
            same_minute_opp = impact_at_exact(not control_bull, at)
            if same_minute_opp is not None:
                control = "BOTH"
                challenger = same_minute_opp
                pre_both_bull = control_bull
                log(at, "PAUSE_COLLIDES_WITH_IMPACT", f"Swing confirms same minute zone {challenger.id} impacts -> BOTH", challenger.id, control)
                t = at
                continue
            same_side_imp = impact_at_exact(control_bull, at)
            if same_side_imp is not None:
                anchor_zone = same_side_imp
                log(at, "PAUSE_OVERRIDDEN_BY_IMPACT", f"Swing confirms same minute zone {same_side_imp.id} impacts -> stays {control}", same_side_imp.id, control)
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
            break_at = first_breach(mt, lo, hi, t,
                                     challenger.zb if challenger.bullish else challenger.zt,
                                     above=not challenger.bullish)
            # Third resolution path, real gap found 2026-09-24 (gate 8->9's
            # 05-11 01:00 case): the challenger can also just die outright
            # via the ordinary Weekly-close body-breach rule, same as any
            # other zone -- BOTH doesn't exempt it. Missing this made the
            # engine keep watching for a respect/anchor-break that was never
            # coming, silently skipping straight past the real resolution
            # to a later, unrelated coincidental swing.
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
                log(at, "RESPECT_FULL_FLIP", f"Zone {challenger.id} respected -> {new_control}", challenger.id, new_control)
                control = new_control
                anchor_zone = challenger
            else:
                new_control = "BUY_ONLY" if pre_both_bull else "SELL_ONLY"
                kind_label = "ANCHOR_BREAK_REVERT" if kind_ == "break" else "BODY_DEATH_REVERT"
                reason = "own level breached, no respect" if kind_ == "break" else "closes body inside/through its own box"
                log(at, kind_label, f"Zone {challenger.id}'s {reason} -> {new_control}", challenger.id, new_control)
                control = new_control
                anchor_zone = None
            challenger = None
            pre_both_bull = None
            t = at
            continue

        break

    write_outputs(base, events, display_tz)
    print("Created:")
    print("  weekly_rb_control_events.csv")
    print("  weekly_rb_control_report.txt")
    print(f"{len(events)} control-relevant events logged.")
    return 0


def write_outputs(base: Path, events: List[ControlEvent], display_tz: ZoneInfo) -> None:
    with (base / "weekly_rb_control_events.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["at_utc", "at_riyadh", "event", "detail", "zone_id", "control", "sell_parent", "buy_parent"])
        for e in events:
            wr.writerow([wob.iso(e.at_utc), wob.display_iso(e.at_utc, display_tz), e.kind, e.detail,
                         e.zone_id or "", e.control, e.sell_parent, e.buy_parent])
    lines = [
        "RB WEEKLY DIRECTION-CONTROL STATE MACHINE -- FIRST PASS, UNVERIFIED",
        "",
        "Additive layer over the locked WeeklyRBEngine. Does not change any",
        "swing/MSS/zone fact. Validate against the hand-verified 34-gate table",
        "in full_rb_viewer.py's build_manual_rb_gates() before trusting this",
        "over that table -- run validate_against_manual_gates.py or the",
        "equivalent comparison. See this file's own module docstring for the",
        "full list of RB-specific rules this implements.",
        "",
        f"Control-relevant events: {len(events)}",
    ]
    (base / "weekly_rb_control_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
