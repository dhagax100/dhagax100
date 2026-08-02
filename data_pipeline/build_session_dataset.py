"""Build the per-day Asian/London session dataset from raw HistData 1-minute bars.

Timestamps in the raw HistData files are Eastern Standard Time with no DST
adjustment (fixed UTC-5 all year round). We treat that column as our single
reference clock -- see README.md for why, and for the exact session window
definitions used below (ASIAN_START/END, LONDON_KZ_START/END, EXTENDED_END).

Output: derived/asian_london_sessions_<PAIR>_<START>_<END>.csv, one row per
trading day, plus derived/daily_ohlc_<PAIR>_<START>_<END>.csv (full calendar-day
OHLC, used for ATR and kept for reuse).
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

PIP = 0.0001  # EUR/USD pip size

# Session windows, in the fixed-EST clock used by the raw data.
ASIAN_START_H = 20   # prior calendar day 20:00 EST
ASIAN_END_H = 24      # current day 00:00 EST (i.e. midnight)
LONDON_KZ_START_H = 2  # current day 02:00 EST
LONDON_KZ_END_H = 5    # current day 05:00 EST
EXTENDED_END_H = 12    # current day 12:00 EST -- how far we look for a delayed reversal

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "derived")


def load_raw(pair: str, start_year: int, end_year: int) -> pd.DataFrame:
    frames = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(RAW_DIR, f"DAT_ASCII_{pair.upper()}_M1_{year}.csv")
        df = pd.read_csv(
            path, sep=";", header=None,
            names=["ts", "open", "high", "low", "close", "volume"],
        )
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    df = df.sort_values("ts").drop_duplicates(subset="ts").set_index("ts")
    return df


def build_daily_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    daily = df.resample("D").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        bar_count=("close", "count"),
    )
    daily = daily.dropna(subset=["open"])
    daily["range_pips"] = (daily["high"] - daily["low"]) / PIP
    # Wilder-style ATR proxy using daily high-low range (no gap component needed
    # for a single continuously-quoted FX pair).
    daily["atr14_pips"] = daily["range_pips"].rolling(14, min_periods=5).mean()
    return daily


def analyze_day(df: pd.DataFrame, day: pd.Timestamp) -> dict:
    asian_start = (day - pd.Timedelta(days=1)).replace(hour=ASIAN_START_H, minute=0, second=0)
    asian_end = day.replace(hour=0, minute=0, second=0)
    kz_start = day.replace(hour=LONDON_KZ_START_H, minute=0, second=0)
    kz_end = day.replace(hour=LONDON_KZ_END_H, minute=0, second=0)
    ext_end = day.replace(hour=EXTENDED_END_H, minute=0, second=0)

    asian = df.loc[asian_start:asian_end - pd.Timedelta(seconds=1)]
    kz = df.loc[kz_start:kz_end - pd.Timedelta(seconds=1)]
    ext = df.loc[kz_start:ext_end - pd.Timedelta(seconds=1)]

    row = {
        "date": day.date(),
        "day_of_week": day.day_name(),
        "asian_bar_count": len(asian),
        "london_kz_bar_count": len(kz),
    }

    if asian.empty or kz.empty:
        row["data_gap"] = True
        return row

    asian_high = asian["high"].max()
    asian_high_time = asian["high"].idxmax()
    asian_low = asian["low"].min()
    asian_low_time = asian["low"].idxmin()
    asian_range_pips = (asian_high - asian_low) / PIP

    row.update({
        "data_gap": len(asian) < 200 or len(kz) < 150,  # expected 240 / 180 bars
        "asian_open": asian["open"].iloc[0],
        "asian_close": asian["close"].iloc[-1],
        "asian_high": asian_high,
        "asian_high_time": asian_high_time.strftime("%H:%M"),
        "asian_low": asian_low,
        "asian_low_time": asian_low_time.strftime("%H:%M"),
        "asian_high_before_low": asian_high_time < asian_low_time,
        "asian_range_pips": round(asian_range_pips, 1),
        "london_kz_open": kz["open"].iloc[0],
        "london_kz_close": kz["close"].iloc[-1],
        "london_kz_high": kz["high"].max(),
        "london_kz_low": kz["low"].min(),
        "london_kz_range_pips": round((kz["high"].max() - kz["low"].min()) / PIP, 1),
    })

    # --- sweep detection within the killzone ---
    swept_high_mask = kz["high"] > asian_high
    swept_low_mask = kz["low"] < asian_low
    swept_high = swept_high_mask.any()
    swept_low = swept_low_mask.any()

    high_sweep_time = kz.index[swept_high_mask][0] if swept_high else pd.NaT
    low_sweep_time = kz.index[swept_low_mask][0] if swept_low else pd.NaT

    if not swept_high and not swept_low:
        row["first_sweep_side"] = "none"
        return row

    if swept_high and (not swept_low or high_sweep_time <= low_sweep_time):
        first_side, sweep_time, level = "high", high_sweep_time, asian_high
    else:
        first_side, sweep_time, level = "low", low_sweep_time, asian_low

    row["both_sides_swept_in_kz"] = bool(swept_high and swept_low)
    row["first_sweep_side"] = first_side
    row["first_sweep_time"] = sweep_time.strftime("%H:%M")

    post_sweep = ext.loc[sweep_time:]
    if first_side == "high":
        depth = (post_sweep["high"].max() - level) / PIP
        close_beyond = (post_sweep["close"] > level).any()
    else:
        depth = (level - post_sweep["low"].min()) / PIP
        close_beyond = (post_sweep["close"] < level).any()
    row["sweep_depth_pips"] = round(depth, 1)
    row["sweep_close_beyond_level"] = bool(close_beyond)

    # --- reversal to the opposite Asian level, checked through the extended window ---
    opposite_level = asian_low if first_side == "high" else asian_high
    if first_side == "high":
        reach_mask = post_sweep["low"] <= opposite_level
    else:
        reach_mask = post_sweep["high"] >= opposite_level

    reversal_reached = reach_mask.any()
    row["reversal_reached_opposite"] = bool(reversal_reached)

    entry_price = post_sweep["close"].iloc[0]
    direction = "short" if first_side == "high" else "long"
    row["direction_if_faded"] = direction

    if reversal_reached:
        reversal_time = post_sweep.index[reach_mask][0]
        row["reversal_time"] = reversal_time.strftime("%H:%M")
        row["minutes_to_reversal"] = int((reversal_time - sweep_time).total_seconds() / 60)
        path = post_sweep.loc[:reversal_time]
    else:
        path = post_sweep

    if direction == "long":
        mfe = (path["high"].max() - entry_price) / PIP
        mae = (entry_price - path["low"].min()) / PIP
    else:
        mfe = (entry_price - path["low"].min()) / PIP
        mae = (path["high"].max() - entry_price) / PIP
    row["mfe_pips"] = round(mfe, 1)
    row["mae_pips"] = round(mae, 1)

    # --- how far, as a % of the Asian range, did price ever get toward the
    # opposite level across the FULL extended window (regardless of whether
    # it fully reached it)? Measured from the swept level itself, not the
    # entry price, so 100% means "touched the opposite Asian level exactly".
    if direction == "long":
        best_price = post_sweep["high"].max()
        progress_price = best_price - level
    else:
        best_price = post_sweep["low"].min()
        progress_price = level - best_price
    asian_range_price = asian_high - asian_low
    row["progress_pct_of_asian_range"] = round(float(progress_price / asian_range_price * 100), 1)

    return row


def build_session_dataset(df: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range(df.index.min().normalize(), df.index.max().normalize(), freq="D")
    rows = [analyze_day(df, d) for d in days if d.day_name() not in ("Saturday", "Sunday")]
    out = pd.DataFrame(rows)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="eurusd")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    raw = load_raw(args.pair, args.start_year, args.end_year)
    print(f"Loaded {len(raw):,} raw 1-minute bars from {raw.index.min()} to {raw.index.max()}")

    daily = build_daily_ohlc(raw)
    daily_path = os.path.join(OUT_DIR, f"daily_ohlc_{args.pair}_{args.start_year}_{args.end_year}.csv")
    daily.to_csv(daily_path)
    print(f"Wrote {daily_path} ({len(daily)} rows)")

    sessions = build_session_dataset(raw)

    # attach ATR context from the daily table (previous day's trailing ATR)
    daily_atr = daily["atr14_pips"].copy()
    daily_atr.index = daily_atr.index.date
    sessions["atr14_pips_prior"] = sessions["date"].map(lambda d: daily_atr.get(d))

    # low-liquidity proxy: asian range far below trailing 20-day median
    med20 = sessions["asian_range_pips"].rolling(20, min_periods=10).median()
    sessions["low_liquidity_flag"] = sessions["asian_range_pips"] < 0.4 * med20

    sessions_path = os.path.join(OUT_DIR, f"asian_london_sessions_{args.pair}_{args.start_year}_{args.end_year}.csv")
    sessions.to_csv(sessions_path, index=False)
    print(f"Wrote {sessions_path} ({len(sessions)} rows)")
