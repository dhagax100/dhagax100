#!/usr/bin/env python3
"""Daily FXCM EURUSD OB+RB+FVG unified indicator -- "Dhagax Dailies", stage 1.

This is a thin daily wrapper around the already-verified combined engine
(reference_combined/weekly_combined_generator.py's WeeklyCombinedEngine).
That engine is generic over "bars" -- it only ever reads self.w[k].first/
.last/.o/.h/.l/.c and never assumes the bar spans a week -- so nothing about
the swing, MSS, OB, RB or FVG rules changes here. The ONLY new thing this
file adds is aggregate_days(): the same forex-session bucketing rule as
aggregate_weeks() (17:00 America/New_York rollover, DST-aware), just
timedelta(days=1) instead of timedelta(days=7).

Per the user's explicit direction (2026-09-28): draw swing points, MSS and
POIs (OB+RB+FVG, unified) on the daily chart, same rules as before, nothing
new invented. Control gates (BUY_ONLY/SELL_ONLY/BOTH/NONE) and the H4/5m
entry layer are intentionally NOT part of this stage -- user said "do not
worry about that now."

Writes, next to itself:
  daily_combined_viewer.pine    TradingView indicator: daily swings, MSS,
                                 OB+RB+FVG boxes (same visual convention as
                                 the weekly combined viewer)
  daily_combined_swings.csv     every daily swing high/low and MSS, with
                                 exact confirmation day and price
  daily_combined_report.txt     day/swing/MSS/POI counts, for a quick sanity
                                 check against the .pine before opening it

Run (flat folder: this file + weekly_ob_generator.py + weekly_rb_generator.py
+ weekly_fvg_generator.py + weekly_combined_generator.py copied together,
raw CSV one level up, same convention as every other generator here):

    python3 daily_combined_generator.py ..\EURUSD_m1_BidAndAsk.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

# Two supported layouts, same convention as reference_combined/
# weekly_combined_generator.py: (1) this repo's own sibling folders, or
# (2) all five .py files copied flat into one working folder with the CSV
# one level up. Both are tried; flat-folder is checked first.
_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference_combined", _here.parent / "reference",
           _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob          # noqa: E402
import weekly_combined_generator as wc     # noqa: E402 -- WeeklyCombinedEngine,
                                            # write_combined_pine, OB/RB/FVG_STATE

UTC = timezone.utc


def forex_day_start(t: datetime, close_zone: ZoneInfo, close_hour: int) -> datetime:
    """Exact mirror of wob.forex_week_start(), one day instead of seven:
    the latest close_hour:00 local-wall-time rollover at or before t."""
    local = t.astimezone(close_zone)
    start = datetime(local.year, local.month, local.day, close_hour, tzinfo=close_zone)
    if local < start:
        start -= timedelta(days=1)
    return start.astimezone(UTC)


def aggregate_days(minutes: List["wob.Minute"], close_zone: ZoneInfo, close_hour: int) -> List["wob.Week"]:
    """Same aggregation loop as wob.aggregate_weeks(), daily instead of
    weekly. Reuses wob.Week as the bar container -- it is just
    (start, end, o, h, l, c, first, last), nothing week-specific about it.
    A day with no minutes (weekend) simply never appears -- there is no gap
    to skip, aggregate_weeks() has the same property for Saturdays."""
    days: List["wob.Week"] = []
    i = 0
    while i < len(minutes):
        start = forex_day_start(minutes[i].t, close_zone, close_hour)
        end = (start.astimezone(close_zone) + timedelta(days=1)).astimezone(UTC)
        j = i + 1
        high, low = minutes[i].h, minutes[i].l
        while j < len(minutes) and minutes[j].t < end:
            high = max(high, minutes[j].h)
            low = min(low, minutes[j].l)
            j += 1
        days.append(wob.Week(start, end, minutes[i].o, high, low, minutes[j - 1].c, i, j))
        i = j
    return days


def write_report(base: Path, minutes, days, e: "wc.WeeklyCombinedEngine", display_zone: ZoneInfo) -> None:
    n_high = sum(1 for x in e.events if x.kind == 0)
    n_low = sum(1 for x in e.events if x.kind == 1)
    n_up = sum(1 for x in e.msses if x.up)
    n_down = sum(1 for x in e.msses if not x.up)

    def counts_for(zones, state_map, status_fn):
        c = {name: 0 for name in state_map.values()}
        for z in zones:
            if not getattr(z, "rejected", False):
                c[status_fn(z)] += 1
        return c

    ob_counts = counts_for(e.ob_zones, wc.OB_STATE, wc.ob_status)
    rb_counts = counts_for(e.rb_zones, wc.RB_STATE, wc.rb_status)
    fvg_counts = counts_for(e.fvg_zones, wc.FVG_STATE, wc.fvg_status)

    rows = [
        "DAILY COMBINED (OB+RB+FVG unified) REFERENCE RUN -- Dhagax Dailies",
        f"minute_coverage={wob.iso(minutes[0].t)} to {wob.iso(minutes[-1].t)}",
        f"minutes={len(minutes):,}; days={len(days):,}",
        f"swing_highs={n_high:,}; swing_lows={n_low:,}; mss_up={n_up:,}; mss_down={n_down:,}",
        "",
        "OB counts (non-rejected): " + ", ".join(f"{k}={v}" for k, v in ob_counts.items()),
        "RB counts (non-rejected): " + ", ".join(f"{k}={v}" for k, v in rb_counts.items()),
        "FVG counts (non-rejected): " + ", ".join(f"{k}={v}" for k, v in fvg_counts.items()),
        "",
        "Colors: IFOB/IRB/IFVG BUY=blue, SELL=black; AOB/ARB/AFVG=green; "
        "AIFOB/AIRB=orange; OOB/ORB/OFVG=red (still tradeable, see SPEC.md SS12-15); "
        "SPENT keeps its preceding color.",
        "Control gates (BUY_ONLY/SELL_ONLY/BOTH/NONE) and the H4/5m entry layer "
        "are NOT part of this stage -- structure only (swings, MSS, POIs).",
    ]
    (base / "daily_combined_report.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_swings_csv(base: Path, e: "wc.WeeklyCombinedEngine", display_zone: ZoneInfo) -> None:
    import csv
    with (base / "daily_combined_swings.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["kind", "side", "swing_day_start_utc", "confirm_day_start_utc",
                     "confirm_day_start_riyadh", "price"])
        for ev in e.events:
            wr.writerow(["SWING", "HIGH" if ev.kind == 0 else "LOW",
                         wob.iso(e.w[ev.swing].start), wob.iso(e.w[ev.confirm].start),
                         wob.display_iso(e.w[ev.confirm].start, display_zone), f"{ev.price:.5f}"])
        for x in e.msses:
            wr.writerow(["MSS_UP" if x.up else "MSS_DOWN", "",
                         wob.iso(e.w[x.broken].start), wob.iso(e.w[x.at].start),
                         wob.display_iso(e.w[x.at].start, display_zone), f"{x.price:.5f}"])


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--day-close-zone", default="America/New_York")
    p.add_argument("--day-close-hour", type=int, default=17, choices=range(24),
                    help="Daily rollover hour in --day-close-zone wall time "
                         "(default 17:00 NY, the standard broker forex-day "
                         "convention -- same clock weekly already uses for "
                         "its Sunday-open boundary).")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=60, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=80, choices=range(1, 451))
    p.add_argument("--pine-rbs", type=int, default=80, choices=range(1, 451))
    p.add_argument("--pine-fvgs", type=int, default=80, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent  # outputs land beside the CSV, same convention as every other generator here
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    try:
        input_tz = ZoneInfo(args.input_tz)
        close_tz = ZoneInfo(args.day_close_zone)
        display_tz = ZoneInfo(args.display_tz)

        minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
        days = aggregate_days(minutes, close_tz, args.day_close_hour)

        engine = wc.WeeklyCombinedEngine(minutes, days)
        engine.run()

        wc.write_combined_pine(base, engine, args.pine_labels, args.pine_obs, args.pine_rbs,
                                args.pine_fvgs, args.pine_table, display_tz,
                                out_name="daily_combined_viewer.pine")
        write_swings_csv(base, engine, display_tz)
        write_report(base, minutes, days, engine, display_tz)

        print("Created:")
        print("  daily_combined_viewer.pine   <-- open this in TradingView on the Daily chart")
        print("  daily_combined_swings.csv")
        print("  daily_combined_report.txt")
        print(f"Processed {len(minutes):,} minutes into {len(days)} daily bars.")
        print(f"OB zones={len(engine.ob_zones)}  RB zones={len(engine.rb_zones)}  FVG zones={len(engine.fvg_zones)}")
        if warnings:
            print(f"({len(warnings)} data warnings -- see load_minutes output)")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
