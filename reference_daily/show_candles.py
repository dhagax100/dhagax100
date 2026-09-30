"""Dhagax Dailies -- standalone diagnostic: show one day's candles, one
timeframe, visually (candlestick chart, saved as PNG) and tabularly
(printed OHLC table). Not part of the main pipeline -- run on demand
whenever you want to eyeball a specific day/timeframe directly.

Usage:
    python show_candles.py EURUSD_m1_BidAndAsk.csv --tf 4h --date 2026-01-16
    python show_candles.py EURUSD_m1_BidAndAsk.csv --tf 1h --date 2026-01-16 --out day16_1h.png

--tf choices: d, 4h, 1h, 5m
"""
import argparse
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference_combined"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))

import weekly_ob_generator as wob
import daily_combined_generator as dc

DISPLAY_TZ = ZoneInfo("Asia/Riyadh")
CLOSE_TZ = ZoneInfo("America/New_York")


def build_bars(minutes, tf: str, day_close_hour: int):
    if tf == "d":
        return dc.aggregate_days(minutes, CLOSE_TZ, day_close_hour, DISPLAY_TZ)
    if tf == "4h":
        return dc.aggregate_hours(minutes, 4, CLOSE_TZ, day_close_hour, DISPLAY_TZ)
    if tf == "1h":
        return dc.aggregate_hours(minutes, 1, CLOSE_TZ, day_close_hour, DISPLAY_TZ)
    if tf == "5m":
        return dc.aggregate_minutes(minutes, 5)
    raise ValueError(f"unknown --tf {tf!r}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path")
    p.add_argument("--tf", choices=("d", "4h", "1h", "5m"), required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD (Riyadh calendar day)")
    p.add_argument("--day-close-hour", type=int, default=17)
    p.add_argument("--out", default=None, help="PNG path (default: candles_<date>_<tf>.png)")
    args = p.parse_args()

    minutes, warnings = wob.load_minutes(Path(args.csv_path), ZoneInfo("UTC"), "bid")
    minutes = [m for m in minutes if m.t.astimezone(DISPLAY_TZ).weekday() != 6]

    bars = build_bars(minutes, args.tf, args.day_close_hour)
    day_bars = [b for b in bars if b.start.astimezone(DISPLAY_TZ).date().isoformat() == args.date]

    if not day_bars:
        print(f"No {args.tf} bars found on {args.date}.")
        return

    print(f"{args.tf.upper()} candles on {args.date} (Riyadh) -- {len(day_bars)} bars\n")
    print(f"{'#':<4}{'Time (Riyadh)':<22}{'Open':<10}{'High':<10}{'Low':<10}{'Close':<10}")
    for i, b in enumerate(day_bars, start=1):
        rt = b.start.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")
        print(f"{i:<4}{rt:<22}{b.o:<10.5f}{b.h:<10.5f}{b.l:<10.5f}{b.c:<10.5f}")

    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, ax = plt.subplots(figsize=(max(8, len(day_bars) * 0.6), 6))
    for i, b in enumerate(day_bars):
        bull = b.c >= b.o
        color = "#26a69a" if bull else "#ef5350"
        ax.plot([i, i], [b.l, b.h], color=color, linewidth=1, zorder=2)
        body_bottom = min(b.o, b.c)
        body_height = max(abs(b.c - b.o), 0.00001)
        ax.add_patch(Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                                facecolor=color, edgecolor=color, zorder=3))

    labels = [b.start.astimezone(DISPLAY_TZ).strftime("%H:%M") for b in day_bars]
    ax.set_xticks(range(len(day_bars)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title(f"EURUSD {args.tf.upper()} -- {args.date} (Riyadh)")
    ax.set_ylabel("Price")
    ax.margins(x=0.02)
    fig.tight_layout()

    out_path = args.out or f"candles_{args.date}_{args.tf}.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart: {out_path}")


if __name__ == "__main__":
    main()
