#!/usr/bin/env python3
"""Weekly-only Pine viewer: swing highs/lows, MSS flips, and RB zones only.

Parallel to `ob_reference/weekly_ob_viewer.pine`'s scope, but for RB. This
is `full_viewer_rb.py`'s Weekly layer only (no H4, no 5m) -- it imports and
calls `build_struct_block`/`build_rb_block` from `full_viewer_rb.py`
UNCHANGED, so the drawing conventions (dashed hollow boxes; IRB
blue(bull)/black(bear) by raw wick; ARB green; ORB red) are identical to
the combined viewer's Weekly section, not re-derived.

Draws on any chart timeframe (no `onWeekly` gate), same reasoning as the
attached `RB_Indicator_v1.pine` diagnostic: this script computes Weekly
bars/RB zones from the M1 CSV itself, independent of whatever timeframe
the chart happens to be on.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_rb_generator as wrb  # noqa: E402
from full_viewer_rb import build_struct_block, build_rb_block  # noqa: E402  (reused unchanged)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly-only swing/MSS/RB Pine viewer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--label-cap", type=int, default=150, choices=range(1, 161))
    p.add_argument("--rb-cap", type=int, default=150, choices=range(1, 451))
    p.add_argument("--table-cap", type=int, default=20, choices=range(1, 21))
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wrb.load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)

    weeks = wrb.aggregate_weeks(minutes, ZoneInfo("America/New_York"), 17)
    weekly_engine = wrb.WeeklyRBEngine(minutes, weeks)
    weekly_engine.run()

    right_edge = minutes[-1].t + timedelta(days=365)
    weekly_shown = weekly_engine.rbs[-args.rb_cap:]
    weekly_table = weekly_engine.rbs[-args.table_cap:][::-1]

    lines = [
        "//@version=6",
        "indicator(\"FXCM RB - Weekly Reference (Swings/MSS/RB only)\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA by weekly_rb_viewer.py.",
        "// Swing/MSS detection and RB construction/lifecycle are unchanged from",
        "// weekly_rb_generator.py (itself a verbatim port of weekly_ob_generator.py's",
        "// swing/MSS engine, per that file's own header). RB zones follow",
        "// RB_Indicator_v1.pine's addRBFromSwing/tryBullARB/tryBearARB/STEP2/STEP3.",
        "// Drawing convention (from that pine file's header): dashed hollow boxes;",
        "// IRB blue(bull)/black(bear) by raw wick; ARB green, fixed; ORB red, fixed.",
        "// No native H4 engine here -- this file is Weekly swings/MSS/RB only. The",
        "// SAME Weekly RB boxes are also shown on the 4H chart (zones+impact lines",
        "// only, no swing/MSS labels or table) purely for closer-resolution viewing",
        "// of the same Weekly zone; every other timeframe draws nothing.",
        "float lowGap = ta.atr(14) * 0.08",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
        "inspectOneRB = input.bool(false, \"Inspect one RB only\")",
        "rbFromLast = input.int(1, \"RB from last\", minval=1)",
    ]
    lines += build_struct_block("w", weekly_engine, weeks, args.label_cap, "onWeekly")
    lines += build_rb_block("w", weekly_engine, weeks, weekly_shown, weekly_table, display_tz,
                             draw_flag_expr="onWeekly or onH4", hide_orb=False, right_edge=right_edge,
                             with_table=True, table_flag_expr="onWeekly",
                             inspect_flag_expr="inspectOneRB", from_last_expr="rbFromLast",
                             draw_impact_line=True)

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "weekly_rb_viewer.pine"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Created: {out_path}")
    print(f"Weekly swing highs: {len([e for e in weekly_engine.events if e.kind == 0])}")
    print(f"Weekly swing lows: {len([e for e in weekly_engine.events if e.kind == 1])}")
    print(f"Weekly MSS: {len(weekly_engine.msses)}")
    print(f"Weekly RB zones: {len(weekly_engine.rbs)} ({len(weekly_shown)} shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
