#!/usr/bin/env python3
"""4H RB (Rejection Block) engine.

Parallel to `rb_system/ob_reference/h4_ob_engine.py`, but reuses
`weekly_rb_generator.WeeklyRBEngine` (RB, not OB) driven on native 4-hour
bars instead of Weekly bars -- the same "same engine in terms of
trigger/eligibility/impact, just fed a different bar grid" reuse pattern
h4_ob_engine.py uses for `WeeklyOBEngine`.

SUPERSEDED (2026-09-18, later this same day, per explicit user decision):
the paragraph below records the earlier finding that RB has no control-rule
of its OWN to derive from the pine spec -- that finding still stands and is
kept for the record. But the user separately decided RB should not run
ungated either: instead of inventing an RB-native control rule (which would
require guessing), RB's H4 engine now OBEYS the SAME Weekly control
permission that already gates OB's H4/5m, consumed as an external gate via
the exact same interface `h4_ob_engine.py` uses (`weekly_control_ledger.py`'s
`weekly_control_ledger.csv`, `load_control_by_week`, `permits(control,
bullish)`, `control_at(t)` via bisect on week_starts) -- see
`RB_TRADING_SYSTEM_HANDOFF.md` SS8 for the decision and verification. This
file's ledger now has an `authorized` column exactly like `h4_ob_ledger.csv`
does, and the Pine viewer / 5m BSO stage should read it the same way OB's
downstream stages read OB's `authorized` column.

ORIGINAL FINDING, still true, kept for context: `RB_Indicator_v1.pine`
(grep'd in full) never mentions "control", "permit", "BUY_ONLY"/"SELL_ONLY"/
"BOTH", or a weekly-gating concept anywhere -- RB's own pine spec is a
standalone, timeframe-agnostic script with no cross-timeframe permission
layer of its own. That is still true. What changed is the user's choice of
what to do about it: rather than run ungated, RB borrows OB's existing
Weekly control signal as-is (unmodified `weekly_control_engine.py`, driven
on OB zones, exactly as before) and treats it as an external permission
gate on RB opportunities too.

No third-party Python packages required. Python 3.9+.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ob_reference"))
import weekly_rb_generator as wrb  # noqa: E402  (verified engine, unmodified)
import weekly_ob_generator as wob  # noqa: E402  (only for load_minutes/aggregate_weeks -- to rebuild the same week grid weekly_control_engine.py used)

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def load_control_by_week(path: Path) -> Dict[int, str]:
    """Identical to h4_ob_engine.py's helper of the same name -- same CSV, same column."""
    out: Dict[int, str] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[int(row["week_index"])] = row["control"]
    return out


def permits(control: str, bullish: bool) -> bool:
    """Identical to h4_ob_engine.py's helper of the same name."""
    if bullish:
        return control in ("BUY_ONLY", "BOTH")
    return control in ("SELL_ONLY", "BOTH")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="4H RB engine (WeeklyRBEngine reused on a native 4H bar grid), "
                                             "gated by the same Weekly control permission that gates OB's H4/5m")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4),
                    help="UTC hour the 4H grid starts from -- same value h4_ob_engine.py chart-verified "
                         "2026-09-16 (1 => 01/05/09/13/17/21 UTC).")
    p.add_argument("--week-close-zone", default="America/New_York", help="must match the run that produced --control-ledger")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24), help="must match the run that produced --control-ledger")
    p.add_argument("--control-ledger", default=None, help="path to weekly_control_ledger.csv; default: alongside input CSV")
    p.add_argument("--out-dir", default=None, help="output directory, default: alongside this script's ../data")
    return p.parse_args()


def aggregate_h4(minutes: List["wrb.Minute"], anchor_hour: int) -> List["wrb.Week"]:
    """Copied verbatim in structure from h4_ob_engine.py's aggregate_h4 --
    native 4-hour bars aligned to anchor_hour UTC, built into wrb.Week's
    generic shape (start,end,o,h,l,c,first,last)."""
    bars: List["wrb.Week"] = []
    i, n = 0, len(minutes)
    while i < n:
        t = minutes[i].t
        epoch_hours = int((t - EPOCH).total_seconds() // 3600)
        grid_hours = ((epoch_hours - anchor_hour) // 4) * 4 + anchor_hour
        start = EPOCH + timedelta(hours=grid_hours)
        end = start + timedelta(hours=4)
        j = i + 1
        high, low = minutes[i].h, minutes[i].l
        while j < n and minutes[j].t < end:
            high = max(high, minutes[j].h)
            low = min(low, minutes[j].l)
            j += 1
        bars.append(wrb.Week(start, end, minutes[i].o, high, low, minutes[j - 1].c, i, j))
        i = j
    return bars


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wrb.load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)

    base = csv_path.resolve().parent
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger.csv"
    if not control_path.exists():
        print("weekly_control_ledger.csv not found. Run weekly_control_engine.py first (same CSV, same "
              "--week-close-zone/--week-close-hour), or pass --control-ledger.", file=sys.stderr)
        return 2
    control_by_week = load_control_by_week(control_path)
    close_tz = ZoneInfo(args.week_close_zone)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    week_starts = [w.start for w in weeks]

    def control_at(t: Optional[datetime]) -> str:
        if t is None:
            return ""
        idx = bisect_left(week_starts, t)
        if idx >= len(week_starts) or week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(week_starts) - 1))
        return control_by_week.get(idx, "NONE")

    h4_bars = aggregate_h4(minutes, args.h4_anchor_hour)
    engine = wrb.WeeklyRBEngine(minutes, h4_bars)
    engine.run()

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "h4_rb_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["record", "kind", "origin", "confirm", "price"])
        for ev in engine.events:
            wr.writerow(["SWING", "HIGH" if ev.kind == 0 else "LOW",
                         wrb.iso(engine.w[ev.swing].start), wrb.iso(engine.w[ev.confirm].start), f"{ev.price:.5f}"])
        for mss in engine.msses:
            wr.writerow(["MSS_UP" if mss.up else "MSS_DOWN", "",
                         wrb.iso(engine.w[mss.broken].start), wrb.iso(engine.w[mss.at].start), f"{mss.price:.5f}"])

    with (out_dir / "h4_rb_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "type", "side", "origin_bar_idx", "origin_start_utc", "origin_start_display",
                   "bottom", "top", "trigger_bar_idx", "trigger_time_utc", "trigger_time_display",
                   "eligible_bar_idx", "eligible_time_utc", "eligible_time_display",
                   "status", "stop_bar_idx", "impact_time_utc", "impact_time_display",
                   "control_at_impact", "authorized"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        n_authorized = 0
        for z in engine.rbs:
            impacted = z.state == 3
            pre_spent_ok = z.pre_spent_state in (0, 1) if impacted else None
            ctrl = control_at(z.impact_time) if impacted else ""
            authorized = bool(impacted and pre_spent_ok and permits(ctrl, z.bullish))
            n_authorized += int(authorized)
            wr.writerow({
                "id": z.id,
                "type": wrb.RB_STATE[z.origin],
                "side": "BUY" if z.bullish else "SELL",
                "origin_bar_idx": z.candle,
                "origin_start_utc": wrb.iso(engine.w[z.candle].start),
                "origin_start_display": wrb.display_iso(engine.w[z.candle].start, display_tz),
                "bottom": f"{z.zb:.5f}",
                "top": f"{z.zt:.5f}",
                "trigger_bar_idx": z.trigger,
                "trigger_time_utc": wrb.iso(z.trigger_time),
                "trigger_time_display": wrb.display_iso(z.trigger_time, display_tz),
                "eligible_bar_idx": z.eligible,
                "eligible_time_utc": wrb.iso(z.eligible_time),
                "eligible_time_display": wrb.display_iso(z.eligible_time, display_tz),
                "status": wrb.status(z),
                "stop_bar_idx": z.stop,
                "impact_time_utc": wrb.iso(z.impact_time),
                "impact_time_display": wrb.display_iso(z.impact_time, display_tz),
                "control_at_impact": ctrl,
                "authorized": authorized,
            })

    counts = {}
    for z in engine.rbs:
        counts[wrb.status(z)] = counts.get(wrb.status(z), 0) + 1
    with (out_dir / "h4_rb_report.txt").open("w", encoding="utf-8") as f:
        f.write("4H RB ENGINE -- gated by the same Weekly control permission that gates OB's H4/5m "
                "(weekly_control_engine.py, unmodified, run on OB zones; see RB_TRADING_SYSTEM_HANDOFF.md SS8)\n\n")
        f.write(f"4H bars: {len(h4_bars)} (grid anchor: {args.h4_anchor_hour:02d}:00 UTC, matches h4_ob_engine.py's chart-verified anchor)\n")
        f.write(f"Swing events: {len(engine.events)} (highs {len(engine.sw_highs)}, lows {len(engine.sw_lows)})\n")
        f.write(f"MSS events: {len(engine.msses)}\n")
        f.write(f"RB zones: {len(engine.rbs)}\n")
        for k, v in sorted(counts.items()):
            f.write(f"  {k}: {v}\n")
        f.write(f"Authorized (impacted + pre-eligible, not ORB-before-impact + control-permits direction at impact): {n_authorized}\n")
        f.write("Every row is kept for audit even when not authorized; 'authorized' is False for: never impacted, "
                "was stranded (ORB) before impact, or impacted while the Weekly control state did not permit that direction.\n")

    print(f"4H bars: {len(h4_bars)}  Swings: {len(engine.events)}  MSS: {len(engine.msses)}  RB zones: {len(engine.rbs)}  Authorized: {n_authorized}")
    print(f"Output written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
