#!/usr/bin/env python3
"""5m BSO (Break-of-Swing Opportunity) engine -- SPEC.md SS20-24.

For every authorized 4H OB (same impacted+authorized gate as
h4_ob_engine.py/full_viewer.py, optionally scoped to one Weekly zone via
--focus-weekly-id), runs a native 5m structure engine (reuses
wob.WeeklyOBEngine's swing detection only -- its OB/lifecycle machinery is
not needed at 5m and is ignored) to find the resting swing and entry
candidate, races entry against candidate replacement and against
invalidation, then computes the structural SL and fixed 3R TP.

Invalidation is computed once per OB by `structural_invalid_at()` (SPEC.md
SS17's parent-POI premise, per the user's explicit rule, 2026-09-16) --
NOT a raw 1m wick touching the H4 OB's far boundary, NOT "any new 4H swing
forms", and NOT "a formal MSS against the OB's bias" (three progressively
corrected approximations). The OB stays valid until whichever of these
happens first:
  (a) 'h4_close' -- a fully completed H4 candle closes its BODY at or
      beyond the NEAR boundary (the side price approaches the zone from).
      Per the user: every POI except FVG invalidates on a body close either
      inside its zone or through it -- a bare wick doesn't count.
  (b) 'swing_break' -- the specific 4H swing currently protecting this OB
      (the last confirmed swing of the protecting kind at/before impact)
      gets exceeded, at the exact 1m moment it happens -- whether or not
      the core engine's own regime tracking classifies that as a formal
      MSS. It usually does (that's why the "MSS against the OB's bias"
      approximation worked for a while), but not always: a SELL OB sitting
      inside an already-local-uptrend pullback has no down-regime left to
      shift FROM, so a continuation swing taking out its supporting high
      never registers as an MSS, even though the OB is just as dead.
Both require confirmation, never a raw tick or an unrelated swing.

Post-SL re-entry (SS27, made universal per the user's explicit instruction,
2026-09-16): `run_bso_chain()` re-arms and searches again after an SL, as
long as the OB's own structural premise (above) hasn't been invalidated --
that invalidation time, once it exists, is a hard ceiling on further
attempts. A chain stops on the first attempt that resolves to anything
other than a plain SL (TP, OPEN, AMBIGUOUS, a breach, or any no-entry
stage). Each H4 OB can now produce more than one row in the ledger,
numbered by `attempt`.

SCOPE OF THIS FIRST PASS -- explicitly NOT yet implemented:
  - Break-even (SPEC.md SS25): not computed. Every trade record's
    effective stop equals its original SL. Deferred until after MFE/MAE
    are recorded, per the user's explicit instruction.
  - MFE/MAE (SS34): not computed.
These are follow-up stages, matching the build order's own stage split
(SS36 stages 11-12 vs 13). Every record is clearly one BSO attempt, not a
finished trade-management lifecycle.

Run order: weekly_control_engine.py -> full_viewer.py (or h4_ob_engine.py)
-> this script. Requires the same CSV/args as those.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_ob_generator as wob  # noqa: E402  (locked engine, unmodified)
import h4_ob_engine as h4          # noqa: E402

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="5m BSO engine (entry + SL/TP), scoped like the H4 layer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4))
    p.add_argument("--control-ledger", default=None)
    p.add_argument("--focus-weekly-id", type=int, default=0, help="0 = every authorized H4 OB in the dataset")
    return p.parse_args()


def aggregate_5m(minutes: List["wob.Minute"]) -> List["wob.Week"]:
    """Native 5-minute bars. No anchor ambiguity: any whole-hour timezone
    offset (Riyadh = UTC+3) is a multiple of 5 minutes, so the grid lines up
    identically in UTC or any such display timezone."""
    EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
    bars: List["wob.Week"] = []
    i, n = 0, len(minutes)
    while i < n:
        t = minutes[i].t
        epoch_min = int((t - EPOCH).total_seconds() // 60)
        grid_min = (epoch_min // 5) * 5
        start = EPOCH + timedelta(minutes=grid_min)
        end = start + timedelta(minutes=5)
        j = i + 1
        high, low = minutes[i].h, minutes[i].l
        while j < n and minutes[j].t < end:
            high = max(high, minutes[j].h)
            low = min(low, minutes[j].l)
            j += 1
        bars.append(wob.Week(start, end, minutes[i].o, high, low, minutes[j - 1].c, i, j))
        i = j
    return bars


def run_bso(z, it: datetime, five_bar_starts: List[datetime], five_events: List["wob.Event"],
            minutes: List["wob.Minute"], mt: List[datetime],
            invalidated_at: Optional[datetime]) -> Dict:
    """`invalidated_at` is precomputed once per OB by structural_invalid_at()
    -- see that function for what it means. Passing it in rather than
    recomputing it here means every attempt in a chain (see run_bso_chain)
    shares one canonical answer to "is this OB still structurally alive".

    The resting swing is NOT required to print strictly inside the H4 OB's
    own price zone (a rule dropped 2026-09-16 per the user: "simply the
    swing rest is not strict to inside OB box zone. it can be outside. we
    only want to happen after impact and before breaching the supporting
    zone or closing the 4h candle with body"). It's simply the first swing
    of the needed kind confirmed after the OB's impact -- the "before
    breaching" half of that rule is enforced by the caller (run_bso_chain),
    which rejects any resting swing at/after invalidated_at."""
    bull = z.bullish
    need_rest_kind = 1 if bull else 0   # bullish BSO needs a resting LOW; bearish needs a resting HIGH
    need_cand_kind = 0 if bull else 1   # candidate is the opposite kind

    start5 = bisect_right(five_bar_starts, it) - 1
    if start5 < 0:
        return dict(stage="NO_5M_BAR_FOR_IMPACT")

    events_sorted = sorted(five_events, key=lambda e: (e.confirm, e.kind))

    resting = None
    for ev in events_sorted:
        if ev.kind != need_rest_kind or ev.swing < start5:
            continue
        resting = ev
        break
    if resting is None:
        return dict(stage="NO_RESTING_SWING")
    if resting.at is None:
        return dict(stage="RESTING_SWING_UNRESOLVED_M1")

    candidates_before = [ev for ev in events_sorted if ev.kind == need_cand_kind and ev.swing <= resting.swing]
    if not candidates_before:
        return dict(stage="NO_CANDIDATE")
    candidate = candidates_before[-1]

    later_candidates = sorted(
        [ev for ev in events_sorted if ev.kind == need_cand_kind and ev.at is not None and ev.at > resting.at],
        key=lambda e: e.at)

    idx = bisect_left(mt, resting.at)
    entry_m = None
    stopped = False
    cand_ptr = 0
    replacements = 0
    current = candidate
    current_since = five_bar_starts[current.swing]
    for i in range(idx, len(minutes)):
        m = minutes[i]
        # Invalidation checked BEFORE the break test, not after: a real bug
        # (user-caught, OB #194) let an entry fire on the exact same minute
        # the OB's own impact-containing H4 candle closed through the zone,
        # since the old order let "price broke the candidate" win a tie
        # against "the OB just died" on that shared minute.
        if invalidated_at is not None and m.t >= invalidated_at:
            stopped = True
            break
        while cand_ptr < len(later_candidates) and later_candidates[cand_ptr].at <= m.t:
            current = later_candidates[cand_ptr]
            current_since = five_bar_starts[current.swing]
            replacements += 1
            cand_ptr += 1
        broke = (m.h > current.price) if bull else (m.l < current.price)
        if broke:
            entry_m = m
            break

    if entry_m is None:
        return dict(stage="H4_OB_BREACHED" if stopped else "NO_ENTRY_IN_DATA",
                    resting_at=resting.at, candidate_price=current.price, replacements=replacements,
                    invalidated_at=invalidated_at if stopped else None)

    entry_price = current.price
    entry_time = entry_m.t

    # Structural SL: extreme of every qualifying resting-kind swing from the
    # impact-containing 5m bar through the entry minute.
    pool = [ev for ev in events_sorted if ev.kind == need_rest_kind and ev.swing >= start5
            and ev.at is not None and ev.at <= entry_time]
    if not pool:
        return dict(stage="NO_SL_POOL", resting_at=resting.at, entry_time=entry_time, entry_price=entry_price)
    sl_price = min(p.price for p in pool) if bull else max(p.price for p in pool)
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return dict(stage="ZERO_RISK", resting_at=resting.at, entry_time=entry_time, entry_price=entry_price, sl_price=sl_price)
    tp_price = entry_price + 3 * risk if bull else entry_price - 3 * risk

    # Exit resolution (no break-even yet -- see module docstring): first SL
    # or TP touch after the entry minute (excluded, per SS34's own rule that
    # 1m OHLC can't order the entry minute's own high/low).
    result, exit_time, exit_price = None, None, None
    for i in range(bisect_left(mt, entry_time) + 1, len(minutes)):
        m = minutes[i]
        hit_sl = (m.l <= sl_price) if bull else (m.h >= sl_price)
        hit_tp = (m.h >= tp_price) if bull else (m.l <= tp_price)
        if hit_sl and hit_tp:
            result, exit_time, exit_price = "AMBIGUOUS", m.t, None
            break
        if hit_sl:
            result, exit_time, exit_price = "SL", m.t, sl_price
            break
        if hit_tp:
            result, exit_time, exit_price = "TP", m.t, tp_price
            break

    return dict(stage="ENTERED", resting_at=resting.at, resting_price=resting.price,
                candidate_price=entry_price, replacements=replacements,
                candidate_since=current_since,
                entry_time=entry_time, entry_price=entry_price,
                sl_price=sl_price, risk=risk, tp_price=tp_price,
                result=result or "OPEN", exit_time=exit_time, exit_price=exit_price)


def structural_invalid_at(z, it: datetime, h4_bars: List["wob.Week"], h4_bar_starts: List[datetime],
                           h4_events: List["wob.Event"], minutes: List["wob.Minute"], mt: List[datetime]
                           ) -> Tuple[Optional[datetime], Optional[str]]:
    """When does this H4 OB's own structural premise stop being valid, per
    the user's explicit rule (2026-09-16, twice corrected -- see below):
    whichever of these happens first, computed once from the OB's own
    impact time --
      (a) 'h4_close' -- a fully completed H4 candle closes its BODY at or
          beyond the NEAR boundary (the side price approaches the zone
          from -- zb for a SELL OB approached from below, zt for a BUY OB
          approached from above). Per the user: every POI except FVG
          invalidates on a body close either inside its zone or through it
          -- a bare wick, or a close that hasn't even reached the zone yet,
          does not count.
      (b) 'swing_break' -- the specific 4H swing that currently
          supports/protects this OB gets exceeded. That swing is simply the
          LAST native-4H swing of the protecting kind (a swing HIGH for a
          SELL OB, a swing LOW for a BUY OB) confirmed at or before the
          OB's own impact -- whatever swing happens to be "the one in
          force" at the moment of impact. Invalidation is the exact 1m
          moment price first crosses that swing's price afterward.

          This does NOT require a formal MSS (regime-shift) classification
          from the core engine -- corrected 2026-09-16 per the user, on OB
          #190: "190 is AOB, meaning we are uptrend, so price took the
          supporting swing high, this is not MSS to up and it does not
          have to be, but our whole pull back leg is blown and our OB is
          no longer there." An earlier version of this rule only counted a
          break when the core engine's own regime tracking happened to
          also register it as an MSS -- true for #190 by coincidence (the
          engine was still in a down regime), but not something to depend
          on: a SELL OB sitting inside what's already a local uptrend has
          no down-regime left to flip FROM, so the engine would never
          register a "MSS to up" for a continuation swing there, even
          though the swing that supported this specific OB was still
          genuinely taken out. Checking the raw swing sequence directly,
          independent of MSS classification, fixes this for both cases.

          Before that, an even earlier version accepted "any new 4H swing
          at all, either direction" -- corrected first to "an MSS on the
          protecting side" (fixing OB #186, where an unrelated MSS far
          below the OB's own zone was wrongly counted), and now to this:
          "the specific swing this OB depends on, exceeded, whether or not
          that counts as an MSS."
    Returns (time, reason); (None, None) if the OB is never structurally
    invalidated in the available data.

    Real bug fixed 2026-09-16 (user-caught, OB #194): the h4_close scan
    started at `bisect_left(h4_bar_starts, it)`, which finds the first bar
    starting AT OR AFTER `it`. Since the impact minute almost always falls
    MID-candle (not exactly on a 4H bar boundary), this skipped the very
    candle containing the impact -- exactly the candle most likely to close
    through the zone right as/after the OB gets touched. For #194, that
    candle (2026-05-27 00:00-04:00) closed at 1.16377, above both zb
    (1.16293) and zt (1.16360) -- the OB was impacted and closed fully
    through on the SAME 4H candle, yet the old scan started at the NEXT
    candle (04:00) and never saw it, letting two "entries" happen after
    the OB should already have been dead. Fixed by starting from the bar
    that CONTAINS `it` (bisect_right - 1), the same pattern run_bso() uses
    for start5."""
    bull = z.bullish
    near_boundary = z.zt if bull else z.zb

    h4_close_invalid_at = None
    start_idx = max(0, bisect_right(h4_bar_starts, it) - 1)
    for hb in h4_bars[start_idx:]:
        breach = (hb.c <= near_boundary) if bull else (hb.c >= near_boundary)
        if breach:
            h4_close_invalid_at = hb.end
            break

    protect_kind = 1 if bull else 0  # swing LOW protects a BUY OB; swing HIGH protects a SELL OB
    protecting_events = [e for e in h4_events if e.kind == protect_kind and e.at is not None and e.at <= it]
    swing_break_at = None
    if protecting_events:
        protecting_price = max(protecting_events, key=lambda e: e.at).price
        idx = bisect_right(mt, it)
        for m in minutes[idx:]:
            if (m.l < protecting_price) if bull else (m.h > protecting_price):
                swing_break_at = m.t
                break

    if h4_close_invalid_at is not None and (swing_break_at is None or h4_close_invalid_at <= swing_break_at):
        return h4_close_invalid_at, "h4_close"
    if swing_break_at is not None:
        return swing_break_at, "swing_break"
    return None, None


def run_bso_chain(z, it: datetime, five_bar_starts: List[datetime], five_events: List["wob.Event"],
                   minutes: List["wob.Minute"], mt: List[datetime],
                   invalidated_at: Optional[datetime]) -> List[Dict]:
    """Chain of BSO attempts on the same H4 OB: after an SL, re-arm and
    search again from the SL exit onward, as long as the OB's own structural
    premise (see structural_invalid_at) hasn't been invalidated. Stops on
    the first attempt that is not a plain SL (TP, OPEN, AMBIGUOUS,
    H4_OB_BREACHED, or any no-entry stage), or when the next search would
    start at/after invalidated_at.

    Real bug fixed 2026-09-16 (user-caught, OB #197): the ceiling was only
    checked against the PREVIOUS attempt's exit time before launching the
    next search -- it never re-checked whether the NEW attempt's own
    resting swing landed at/after the ceiling once actually found. Since
    search_from only advances to the previous exit, a slow-forming resting
    swing could (and did) print well past the ceiling and still get
    accepted as a live trade. Now validated per-attempt: any attempt whose
    resting swing is at/after the ceiling is converted to H4_OB_BREACHED
    instead of being accepted.

    This check applies to attempt 1 as well, not just re-entries -- a fix
    initially tried, then wrongly reverted the same day on an unverified
    assumption ("a 4H swing forms constantly, so this would veto valid
    entries"), then re-applied after a second user report (OB #190) with
    direct evidence: its resting swing didn't form until 6 days after
    impact, by which point a new 4H swing had confirmed within an hour of
    impact. Checking the data for the earlier "reverted" OBs (#159, #181,
    #186) showed the exact same pattern -- 12 hours to 6 days of staleness
    -- confirming they were real defects, not false positives. The 6 OBs
    that were never flagged all have their resting swing forming before any
    subsequent structural invalidation, so this check does not touch them.

    Reporting rule (user, 2026-09-16): a RE-ENTRY (attempt_no > 1) that never
    actually became a trade -- breached, structurally invalidated, no
    resting swing, whatever the reason -- is not a "second opportunity" and
    is not reported at all: no table row, no ledger row, nothing. It is
    still used internally to decide the chain should stop there, just never
    appended to the returned list. The OB's original first attempt is
    always reported regardless of its outcome (that's the OB's own result,
    not a re-entry)."""
    attempts: List[Dict] = []
    search_from = it
    attempt_no = 1
    while True:
        res = run_bso(z, search_from, five_bar_starts, five_events, minutes, mt, invalidated_at)
        resting_at = res.get("resting_at")
        if invalidated_at is not None and resting_at is not None and resting_at >= invalidated_at:
            res = dict(stage="H4_OB_BREACHED", resting_at=resting_at, invalidated_at=invalidated_at)
        entered = res.get("stage") == "ENTERED"
        if attempt_no == 1 or entered:
            res["attempt"] = attempt_no
            attempts.append(res)
        if not entered or res.get("result") != "SL":
            break
        exit_time = res.get("exit_time")
        if exit_time is None:
            break
        if invalidated_at is not None and exit_time >= invalidated_at:
            break
        search_from = exit_time
        attempt_no += 1
    return attempts


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger.csv"
    if not control_path.exists():
        print("weekly_control_ledger.csv not found. Run weekly_control_engine.py first.", file=sys.stderr)
        return 2

    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    mt = [m.t for m in minutes]
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    week_starts = [w.start for w in weeks]
    control_by_week, parent_by_week = {}, {}
    with control_path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            idx = int(row["week_index"])
            control_by_week[idx] = row["control"]
            parent_by_week[idx] = row.get("controlling_zone_id", "")

    h4_bars = h4.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wob.WeeklyOBEngine(minutes, h4_bars, origin_gap_window=None)
    h4_engine.run()

    def control_and_parent_at(t: Optional[datetime]):
        if t is None:
            return "", ""
        idx = bisect_left(week_starts, t)
        if idx >= len(week_starts) or week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(week_starts) - 1))
        return control_by_week.get(idx, "NONE"), parent_by_week.get(idx, "")

    targets = []
    for z in h4_engine.zones:
        et, ep = wob.eligibility_detail(h4_engine, z)
        it = wob.impact_time(h4_engine, z, et)
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1, 4) if impacted else None
        ctrl, parent_id = control_and_parent_at(it) if impacted else ("", "")
        authorized = bool(impacted and pre_spent_ok and h4.permits(ctrl, z.bullish))
        if not authorized or it is None:
            continue
        if args.focus_weekly_id and parent_id != str(args.focus_weekly_id):
            continue
        targets.append((z, it, parent_id))

    print(f"{len(targets)} authorized 4H OBs to run BSO on"
          + (f" (--focus-weekly-id {args.focus_weekly_id})" if args.focus_weekly_id else ""))

    h4_bar_starts = [b.start for b in h4_bars]
    five_bars = aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = wob.WeeklyOBEngine(minutes, five_bars, origin_gap_window=None)
    five_engine.run()

    rows = []
    for z, it, parent_id in targets:
        invalidated_at, invalidation_reason = structural_invalid_at(z, it, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = run_bso_chain(z, it, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            row = dict(
                h4_ob_id=z.id, attempt=res.get("attempt"), parent_weekly_id=parent_id, side="BUY" if z.bullish else "SELL",
                h4_impact_riyadh=wob.display_iso(it, display_tz), stage=res.get("stage"),
                resting_riyadh=wob.display_iso(res.get("resting_at"), display_tz),
                candidate_since_riyadh=wob.display_iso(res.get("candidate_since"), display_tz),
                entry_riyadh=wob.display_iso(res.get("entry_time"), display_tz),
                entry_price="" if res.get("entry_price") is None else f"{res['entry_price']:.5f}",
                sl_price="" if res.get("sl_price") is None else f"{res['sl_price']:.5f}",
                risk_price="" if res.get("risk") is None else f"{res['risk']:.5f}",
                tp_price="" if res.get("tp_price") is None else f"{res['tp_price']:.5f}",
                candidate_replacements=res.get("replacements", ""),
                result=res.get("result", ""),
                exit_riyadh=wob.display_iso(res.get("exit_time"), display_tz),
                exit_price="" if res.get("exit_price") is None else f"{res['exit_price']:.5f}",
                invalidated_riyadh=wob.display_iso(res.get("invalidated_at"), display_tz),
                invalidation_reason=invalidation_reason if res.get("invalidated_at") is not None else "",
            )
            rows.append(row)

    fields = ["h4_ob_id", "attempt", "parent_weekly_id", "side", "h4_impact_riyadh", "stage", "resting_riyadh",
              "candidate_since_riyadh", "entry_riyadh", "entry_price", "sl_price", "risk_price", "tp_price",
              "candidate_replacements", "result", "exit_riyadh", "exit_price",
              "invalidated_riyadh", "invalidation_reason"]
    with (base / "five_bso_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    stages = {}
    for r in rows:
        stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    print("Created: five_bso_ledger.csv")
    print("Stage breakdown:", stages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
