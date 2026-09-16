#!/usr/bin/env python3
"""5m BSO (Break-of-Swing Opportunity) engine -- SPEC.md SS20-24.

For every authorized 4H OB (same impacted+authorized gate as
h4_ob_engine.py/full_viewer.py, optionally scoped to one Weekly zone via
--focus-weekly-id), runs a native 5m structure engine (reuses
wob.WeeklyOBEngine's swing detection only -- its OB/lifecycle machinery is
not needed at 5m and is ignored) to find the resting swing and entry
candidate, races entry against candidate replacement and against
invalidation, then computes the structural SL and fixed 3R TP.

Invalidation is NOT a raw 1m wick touching the H4 OB's far boundary -- an
earlier version used that and killed setups where price wicked through the
zone and was later respected. Two confirmed conditions instead, whichever
comes first: (a) a fully completed H4 candle whose CLOSE breaches the far
boundary, or (b) a confirmed 5m swing of the resting kind whose own price
already exceeds the far boundary. Both require confirmation, not a raw tick.

Post-SL re-entry (SS27, made universal per the user's explicit instruction,
2026-09-16): `run_bso_chain()` re-arms and searches again after an SL, as
long as the H4 OB isn't breached (the invalidation above) AND no new native
4H swing (either kind) has been confirmed yet since the OB's own impact
(`first_h4_swing_after`) -- that swing, once it exists, is a hard ceiling on
further attempts. A chain stops on the first attempt that resolves to
anything other than a plain SL (TP, OPEN, AMBIGUOUS, a breach, or any
no-entry stage). Each H4 OB can now produce more than one row in the
ledger, numbered by `attempt`.

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
from typing import Dict, List, Optional
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
            h4_bars: List["wob.Week"], h4_bar_starts: List[datetime]) -> Dict:
    bull = z.bullish
    need_rest_kind = 1 if bull else 0   # bullish BSO needs a resting LOW inside the H4 POI
    need_cand_kind = 0 if bull else 1   # bearish BSO needs a resting HIGH; candidate is the opposite kind

    start5 = bisect_right(five_bar_starts, it) - 1
    if start5 < 0:
        return dict(stage="NO_5M_BAR_FOR_IMPACT")

    events_sorted = sorted(five_events, key=lambda e: (e.confirm, e.kind))

    resting = None
    for ev in events_sorted:
        if ev.kind != need_rest_kind or ev.swing < start5:
            continue
        if not (z.zb <= ev.price <= z.zt):
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

    far_boundary = z.zb if bull else z.zt

    # Invalidation: NOT a raw 1m wick touching the far boundary any more --
    # that killed setups that wicked through and were later respected. Two
    # confirmed conditions instead, whichever comes first:
    #  (a) a fully COMPLETED H4 candle whose CLOSE breaches the far boundary
    #      (a body close through the zone, not a wick);
    #  (b) a CONFIRMED 5m swing of the resting kind whose own price already
    #      exceeds the far boundary (a genuine structural break, faster to
    #      arrive than waiting a full H4 candle, but still a confirmed swing
    #      rather than raw 1m noise).
    h4_close_invalid_at = None
    h4_start_idx = bisect_left(h4_bar_starts, resting.at)
    for hb in h4_bars[h4_start_idx:]:
        breach = (hb.c < far_boundary) if bull else (hb.c > far_boundary)
        if breach:
            h4_close_invalid_at = hb.end
            break

    swing_exceed_at = None
    for ev in events_sorted:
        if ev.kind != need_rest_kind or ev.at is None or ev.at <= resting.at:
            continue
        exceeded = (ev.price < far_boundary) if bull else (ev.price > far_boundary)
        if exceeded:
            swing_exceed_at = ev.at
            break

    invalid_candidates = [t for t in (h4_close_invalid_at, swing_exceed_at) if t is not None]
    invalidated_at = min(invalid_candidates) if invalid_candidates else None

    idx = bisect_left(mt, resting.at)
    entry_m = None
    stopped = False
    cand_ptr = 0
    replacements = 0
    current = candidate
    current_since = five_bar_starts[current.swing]
    for i in range(idx, len(minutes)):
        m = minutes[i]
        while cand_ptr < len(later_candidates) and later_candidates[cand_ptr].at <= m.t:
            current = later_candidates[cand_ptr]
            current_since = five_bar_starts[current.swing]
            replacements += 1
            cand_ptr += 1
        broke = (m.h > current.price) if bull else (m.l < current.price)
        if broke:
            entry_m = m
            break
        if invalidated_at is not None and m.t >= invalidated_at:
            stopped = True
            break

    if entry_m is None:
        return dict(stage="H4_OB_BREACHED" if stopped else "NO_ENTRY_IN_DATA",
                    resting_at=resting.at, candidate_price=current.price, replacements=replacements,
                    invalidated_at=invalidated_at,
                    invalidation_reason=("h4_close" if invalidated_at == h4_close_invalid_at else "swing_exceed") if stopped else None)

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


def first_h4_swing_after(h4_engine_events: List["wob.Event"], it: datetime) -> Optional[datetime]:
    """The confirm time of the first native-4H swing (either kind -- high or
    low) confirmed after the H4 OB's own impact. Re-entry per SPEC.md SS27,
    made universal per the user's explicit instruction (2026-09-16): after
    an SL, keep re-arming and re-entering on the same H4 OB as long as (a)
    it isn't breached (existing far-boundary invalidation) and (b) no new 4H
    swing point -- of either kind -- has been confirmed yet since impact.
    The first such swing, once it exists, is a hard ceiling: no further
    attempt may start after it, regardless of how many SLs came before."""
    times = [e.at for e in h4_engine_events if e.at is not None and e.at > it]
    return min(times) if times else None


def run_bso_chain(z, it: datetime, five_bar_starts: List[datetime], five_events: List["wob.Event"],
                   minutes: List["wob.Minute"], mt: List[datetime],
                   h4_bars: List["wob.Week"], h4_bar_starts: List[datetime],
                   swing_stop_at: Optional[datetime]) -> List[Dict]:
    """Chain of BSO attempts on the same H4 OB: after an SL, re-arm and
    search again from the SL exit onward, as long as neither the far
    boundary has been breached nor a new 4H swing has formed (see
    first_h4_swing_after). Stops on the first attempt that is not a plain
    SL (TP, OPEN, AMBIGUOUS, H4_OB_BREACHED, or any no-entry stage), or when
    the next search would start at/after swing_stop_at."""
    attempts: List[Dict] = []
    search_from = it
    attempt_no = 1
    while True:
        res = run_bso(z, search_from, five_bar_starts, five_events, minutes, mt, h4_bars, h4_bar_starts)
        res["attempt"] = attempt_no
        attempts.append(res)
        if res.get("stage") != "ENTERED" or res.get("result") != "SL":
            break
        exit_time = res.get("exit_time")
        if exit_time is None:
            break
        if swing_stop_at is not None and exit_time >= swing_stop_at:
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
        swing_stop_at = first_h4_swing_after(h4_engine.events, it)
        attempts = run_bso_chain(z, it, five_bar_starts, five_engine.events, minutes, mt,
                                  h4_bars, h4_bar_starts, swing_stop_at)
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
                invalidation_reason=res.get("invalidation_reason", ""),
                swing_stop_riyadh=wob.display_iso(swing_stop_at, display_tz),
            )
            rows.append(row)

    fields = ["h4_ob_id", "attempt", "parent_weekly_id", "side", "h4_impact_riyadh", "stage", "resting_riyadh",
              "candidate_since_riyadh", "entry_riyadh", "entry_price", "sl_price", "risk_price", "tp_price",
              "candidate_replacements", "result", "exit_riyadh", "exit_price",
              "invalidated_riyadh", "invalidation_reason", "swing_stop_riyadh"]
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
