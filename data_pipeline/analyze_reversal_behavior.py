"""Characterize HOW price behaves after sweeping an Asian session level.

Answers the questions the naive backtest skipped:
  1. How far past the swept level does price actually run before turning?
     (the excursion distribution -- what stop distance would have survived)
  2. What does the reversal itself look like? Does price reclaim the level,
     retest it, poke it repeatedly, V-turn or grind?

Everything here is descriptive measurement of the raw 1-minute bars. No
strategy rule is chosen from it in this file -- see optimize_strategy.py.
"""
import argparse
import os

import numpy as np
import pandas as pd

PIP = 0.0001
ASIAN_START_H = 20
LONDON_KZ_START_H = 2
LONDON_KZ_END_H = 5
EXTENDED_END_H = 12
RETEST_TOL_PIPS = 2.0  # how close to the level counts as "retested it"

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "derived")


def load_raw(pair, start_year, end_year):
    frames = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(RAW_DIR, f"DAT_ASCII_{pair.upper()}_M1_{year}.csv")
        frames.append(pd.read_csv(path, sep=";", header=None,
                                  names=["ts", "open", "high", "low", "close", "volume"]))
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    return df.sort_values("ts").drop_duplicates(subset="ts").set_index("ts")


def analyze_day(df, day):
    asian_start = (day - pd.Timedelta(days=1)).replace(hour=ASIAN_START_H, minute=0, second=0)
    asian_end = day.replace(hour=0, minute=0, second=0)
    kz_start = day.replace(hour=LONDON_KZ_START_H, minute=0, second=0)
    kz_end = day.replace(hour=LONDON_KZ_END_H, minute=0, second=0)
    ext_end = day.replace(hour=EXTENDED_END_H, minute=0, second=0)

    asian = df.loc[asian_start:asian_end - pd.Timedelta(seconds=1)]
    kz = df.loc[kz_start:kz_end - pd.Timedelta(seconds=1)]
    if len(asian) < 200 or len(kz) < 150:
        return None

    asian_high, asian_low = asian["high"].max(), asian["low"].min()
    hi_mask, lo_mask = kz["high"] > asian_high, kz["low"] < asian_low
    hi_t = kz.index[hi_mask][0] if hi_mask.any() else pd.NaT
    lo_t = kz.index[lo_mask][0] if lo_mask.any() else pd.NaT
    if pd.isna(hi_t) and pd.isna(lo_t):
        return None
    if not pd.isna(hi_t) and (pd.isna(lo_t) or hi_t <= lo_t):
        side, sweep_time = "high", hi_t
    else:
        side, sweep_time = "low", lo_t

    post = df.loc[sweep_time:ext_end - pd.Timedelta(seconds=1)]
    if len(post) < 10:
        return None

    highs, lows, closes = post["high"].values, post["low"].values, post["close"].values
    entry_price = closes[0]
    asian_range_pips = (asian_high - asian_low) / PIP

    row = {
        "date": day.date(), "side": side, "sweep_time": sweep_time.strftime("%H:%M"),
        "sweep_hour": sweep_time.hour, "asian_range_pips": round(asian_range_pips, 1),
    }

    if side == "low":
        level, target = asian_low, asian_high
        hit = np.where(highs >= target)[0]
        end_idx = int(hit[0]) if len(hit) else len(post) - 1
        seg = lows[:end_idx + 1]
        turn_idx = int(np.argmin(seg))
        extreme = seg[turn_idx]
        excursion_level = (level - extreme) / PIP
        excursion_entry = (entry_price - extreme) / PIP
        reclaim = np.where(closes > level)[0]
        outside = lows < level
    else:
        level, target = asian_high, asian_low
        hit = np.where(lows <= target)[0]
        end_idx = int(hit[0]) if len(hit) else len(post) - 1
        seg = highs[:end_idx + 1]
        turn_idx = int(np.argmax(seg))
        extreme = seg[turn_idx]
        excursion_level = (extreme - level) / PIP
        excursion_entry = (extreme - entry_price) / PIP
        reclaim = np.where(closes < level)[0]
        outside = highs > level

    row["reached_target"] = bool(len(hit) > 0)
    row["excursion_beyond_level_pips"] = round(float(excursion_level), 1)
    row["excursion_beyond_entry_pips"] = round(float(excursion_entry), 1)
    row["excursion_pct_of_asian_range"] = round(float(excursion_level / asian_range_pips * 100), 1)
    row["minutes_sweep_to_turn"] = int(turn_idx)
    row["minutes_turn_to_target"] = int(end_idx - turn_idx) if len(hit) else None

    # how many separate excursions past the level (repeat liquidity pokes)
    flips = np.diff(outside[:end_idx + 1].astype(int))
    row["n_pokes"] = int(1 + (flips == 1).sum())

    # reclaim = first candle CLOSING back inside the Asian range
    if len(reclaim):
        r_idx = int(reclaim[0])
        row["reclaimed"] = True
        row["minutes_sweep_to_reclaim"] = r_idx
        row["reclaim_price"] = float(closes[r_idx])
        # excursion already spent by the time we could enter on the reclaim
        seg_r = lows[:r_idx + 1] if side == "low" else highs[:r_idx + 1]
        ext_at_reclaim = (level - seg_r.min()) / PIP if side == "low" else (seg_r.max() - level) / PIP
        row["excursion_at_reclaim_pips"] = round(float(ext_at_reclaim), 1)
        # worst adverse move AFTER the reclaim, before target -- the stop a
        # reclaim-entry would actually need
        if r_idx < end_idx:
            if side == "low":
                post_r_worst = lows[r_idx:end_idx + 1].min()
                row["max_adverse_after_reclaim_pips"] = round(float((closes[r_idx] - post_r_worst) / PIP), 1)
                retest = (lows[r_idx:end_idx + 1] <= level + RETEST_TOL_PIPS * PIP).any()
            else:
                post_r_worst = highs[r_idx:end_idx + 1].max()
                row["max_adverse_after_reclaim_pips"] = round(float((post_r_worst - closes[r_idx]) / PIP), 1)
                retest = (highs[r_idx:end_idx + 1] >= level - RETEST_TOL_PIPS * PIP).any()
            row["retested_level_after_reclaim"] = bool(retest)
    else:
        row["reclaimed"] = False

    return row


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pair", default="eurusd")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year", type=int, default=2025)
    args = p.parse_args()

    raw = load_raw(args.pair, args.start_year, args.end_year)
    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")
    rows = [r for d in days if d.day_name() not in ("Saturday", "Sunday")
            for r in [analyze_day(raw, d)] if r is not None]
    out = pd.DataFrame(rows)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"reversal_behavior_{args.pair}_{args.start_year}_{args.end_year}.csv")
    out.to_csv(path, index=False)
    print(f"Wrote {path} ({len(out)} rows)")
