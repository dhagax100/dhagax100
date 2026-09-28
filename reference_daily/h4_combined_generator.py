#!/usr/bin/env python3
"""4H FXCM EURUSD OB+RB+FVG unified indicator -- "Dhagax Dailies" intraday.

Same combined engine as daily_combined_generator.py and
reference_combined/weekly_combined_generator.py -- it is generic over bar
timeframe, so no swing/MSS/POI rule changes here either. Bars are built by
daily_combined_generator.aggregate_hours(minutes, 4): plain UTC-clock-aligned
4H buckets (00:00, 04:00, 08:00, 12:00, 16:00, 20:00), the same boundary
convention TradingView itself uses for standard forex 4H candles.

Per the user's explicit direction (2026-09-28, after seeing the daily-only
indicator show nothing on the 4H/1H chart): the daily engine has no 4H/1H
structure of its own, so this is a real second engine run on 4H bars, not a
re-drawing of the daily zones.

Writes, next to the CSV: h4_combined_viewer.pine, h4_combined_swings.csv,
h4_combined_report.txt -- same fixed names every run, overwritten in place.

Run (flat folder, same convention as every other generator here):

    python3 h4_combined_generator.py ..\EURUSD_m1_BidAndAsk.csv --as-of 2026-01-12 --default-side SELL
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference_combined", _here.parent / "reference",
           _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob          # noqa: E402
import weekly_combined_generator as wc     # noqa: E402
import daily_combined_generator as dc      # noqa: E402 -- aggregate_hours, write_report, write_swings_csv

UTC = timezone.utc
BAR_HOURS = 4
TF_PERIOD = "240"   # Pine's timeframe.period string for 4H
TITLE = "4H"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=160, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-rbs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-fvgs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help="Truncate the input data to end of this day (in --display-tz wall "
                         "time) so the output is exactly what existed as of that date.")
    p.add_argument("--default-side", choices=("ALL", "BUY", "SELL"), default="ALL",
                    help="Bakes the viewer's 'Side' input to open already set to this.")
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
        display_tz = ZoneInfo(args.display_tz)

        minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)

        out_name = f"h{BAR_HOURS}_combined_viewer.pine"
        if args.as_of:
            y, m, d = (int(x) for x in args.as_of.split("-"))
            cutoff_local = datetime(y, m, d, 23, 59, 59, tzinfo=display_tz) + timedelta(seconds=1)
            cutoff_utc = cutoff_local.astimezone(UTC)
            minutes = [x for x in minutes if x.t < cutoff_utc]
            if not minutes:
                print(f"No data at or before {args.as_of}", file=sys.stderr)
                return 2

        bars = dc.aggregate_hours(minutes, BAR_HOURS)

        engine = wc.WeeklyCombinedEngine(minutes, bars)
        engine.run()

        wc.write_combined_pine(base, engine, args.pine_labels, args.pine_obs, args.pine_rbs,
                                args.pine_fvgs, args.pine_table, display_tz, out_name=out_name)
        pine_path = base / out_name
        text = pine_path.read_text(encoding="utf-8")
        text = text.replace(
            'indicator("FXCM Weekly OB+RB+FVG Combined - Python Reference"',
            f'indicator("FXCM {TITLE} OB+RB+FVG Combined - Python Reference"',
        )
        text = text.replace(
            'bool onWeekly = timeframe.period == "1W"',
            f'bool onWeekly = timeframe.period == "{TF_PERIOD}"',
        )
        if args.default_side != "ALL":
            text = text.replace(
                'string sideFilter = input.string("ALL", "Side"',
                f'string sideFilter = input.string("{args.default_side}", "Side"',
            )
        pine_path.write_text(text, encoding="utf-8")

        dc.write_swings_csv(base, engine, display_tz, f"h{BAR_HOURS}_combined_swings.csv")
        dc.write_report(base, minutes, bars, engine, display_tz, f"h{BAR_HOURS}_combined_report.txt",
                         label=TITLE, bar_word="4h_bars")

        print("Created:")
        print(f"  {out_name}   <-- open this on the {TITLE} chart")
        print(f"  h{BAR_HOURS}_combined_swings.csv")
        print(f"  h{BAR_HOURS}_combined_report.txt")
        print(f"Processed {len(minutes):,} minutes into {len(bars)} {TITLE} bars.")
        print(f"OB zones={len(engine.ob_zones)}  RB zones={len(engine.rb_zones)}  FVG zones={len(engine.fvg_zones)}")
        if warnings:
            print(f"({len(warnings)} data warnings -- see load_minutes output)")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
