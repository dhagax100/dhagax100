#!/usr/bin/env python3
"""4H RB (Rejection Block) engine.

Parallel to `rb_system/ob_reference/h4_ob_engine.py`, but reuses
`weekly_rb_generator.WeeklyRBEngine` (RB, not OB) driven on native 4-hour
bars instead of Weekly bars -- the same "same engine in terms of
trigger/eligibility/impact, just fed a different bar grid" reuse pattern
h4_ob_engine.py uses for `WeeklyOBEngine`.

RESOLVED AMBIGUITY (does not need a "weekly control" gating layer):
`h4_ob_engine.py` only draws an H4 OB when its direction matches the Weekly
control permission from `weekly_control_engine.py` (BUY_ONLY/SELL_ONLY/BOTH,
SPEC.md SS9-16). That control state machine is a project-specific concept
built entirely on top of OB's own zone-lifecycle nuances (the OOB/rejected
distinction, the AOB/IFOB/AIFOB state family, the Weekly-close body-death
rule discovered specifically for OB) and is documented and driven purely off
`weekly_ob_generator.py`'s `Zone`/`STATE` semantics. `RB_Indicator_v1.pine`
(grep'd in full) never mentions "control", "permit", "BUY_ONLY"/"SELL_ONLY"/
"BOTH", or a weekly-gating concept anywhere -- it is a standalone,
timeframe-agnostic script with no cross-timeframe permission layer at all.
There is therefore no RB analog to gate H4 RB zones against, and building
one would be inventing a rule neither the OB reference nor the RB pine spec
states. This script produces the H4 RB ledger UNGATED: every H4 RB zone
computed by `WeeklyRBEngine` on the H4 bar grid, with its own lifecycle
status (IRB/ARB/ORB/SPENT), same as the Weekly RB ledger. If the user wants
an RB-specific cross-timeframe permission layer later, that is new work to
scope explicitly, not a silent reuse of the OB one.

No third-party Python packages required. Python 3.9+.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_rb_generator as wrb  # noqa: E402  (verified engine, unmodified)

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="4H RB engine (WeeklyRBEngine reused on a native 4H bar grid)")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4),
                    help="UTC hour the 4H grid starts from -- same value h4_ob_engine.py chart-verified "
                         "2026-09-16 (1 => 01/05/09/13/17/21 UTC).")
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
                   "status", "stop_bar_idx", "impact_time_utc", "impact_time_display"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for z in engine.rbs:
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
            })

    counts = {}
    for z in engine.rbs:
        counts[wrb.status(z)] = counts.get(wrb.status(z), 0) + 1
    with (out_dir / "h4_rb_report.txt").open("w", encoding="utf-8") as f:
        f.write("4H RB ENGINE -- UNGATED (no weekly-control analog; see module docstring)\n\n")
        f.write(f"4H bars: {len(h4_bars)} (grid anchor: {args.h4_anchor_hour:02d}:00 UTC, matches h4_ob_engine.py's chart-verified anchor)\n")
        f.write(f"Swing events: {len(engine.events)} (highs {len(engine.sw_highs)}, lows {len(engine.sw_lows)})\n")
        f.write(f"MSS events: {len(engine.msses)}\n")
        f.write(f"RB zones: {len(engine.rbs)}\n")
        for k, v in sorted(counts.items()):
            f.write(f"  {k}: {v}\n")

    print(f"4H bars: {len(h4_bars)}  Swings: {len(engine.events)}  MSS: {len(engine.msses)}  RB zones: {len(engine.rbs)}")
    print(f"Output written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
