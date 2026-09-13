#!/usr/bin/env python3
"""
STEP 1 of the pre-calculation pipeline
======================================
Goal of this step ONLY: read your FXCM 1-minute file and rebuild the H4
(4-hour) candles, so we can confirm those candles match your TradingView H4
EURUSD chart BEFORE we compute any swings / MSS / order blocks on top of them.

This file decides no strategy. It only:
  1. reads your 1-minute CSV,
  2. picks the BID prices,
  3. groups the minutes into 4-hour candles (H4),
  4. prints the first and last few H4 candles so you can eyeball them
     against TradingView.

How to run (in the folder that has your CSV):
    python step1_build_h4_candles.py EURUSD_m1_BidAndAsk.csv

If the printed candles look time-shifted vs TradingView, tell me and we change
ONE number below (TZ_SHIFT_HOURS). Nothing else needs to change.
"""

import sys
import pandas as pd

# ------------------------------------------------------------------
# SETTINGS we may tune together (one line each). Change nothing yet.
# ------------------------------------------------------------------
FEED = "Bid"                          # "Bid" or "Ask" -- we start with Bid
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"     # your file shows e.g. 1/2/2026 6:31:00
TZ_SHIFT_HOURS = 0                    # if candles look shifted vs TradingView,
                                      # we set this (e.g. -5, +2, +3) TOGETHER
H4_HOURS = 4                          # 4-hour candles


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "EURUSD_m1_BidAndAsk.csv"
    print(f"Reading {path} ...")
    df = pd.read_csv(path)

    # Confirm the columns we expect are really there, in plain language.
    needed = ["Date", "Time",
              f"Open{FEED}", f"High{FEED}", f"Low{FEED}", f"Close{FEED}"]
    missing = [col for col in needed if col not in df.columns]
    if missing:
        print("\nERROR: your file is missing these columns:", missing)
        print("Columns I actually found:", list(df.columns))
        print("Send me this list and I'll adjust the reader.")
        return

    # Build one timestamp per minute from Date + Time.
    ts = pd.to_datetime(df["Date"].astype(str).str.strip() + " "
                        + df["Time"].astype(str).str.strip(),
                        format=DATE_FORMAT)
    if TZ_SHIFT_HOURS:
        ts = ts + pd.Timedelta(hours=TZ_SHIFT_HOURS)

    m1 = pd.DataFrame({
        "open":  df[f"Open{FEED}"].to_numpy(),
        "high":  df[f"High{FEED}"].to_numpy(),
        "low":   df[f"Low{FEED}"].to_numpy(),
        "close": df[f"Close{FEED}"].to_numpy(),
    }, index=pd.DatetimeIndex(ts)).sort_index()

    print(f"Loaded {len(m1):,} one-minute rows (using {FEED} prices).")
    print(f"First minute in file: {m1.index[0]}")
    print(f"Last  minute in file: {m1.index[-1]}")
    print("  --> please confirm this date range is what you expect.\n")

    # Group the minutes into 4-hour candles.
    # A 4h candle's stamp is its OPEN time (left edge), same as TradingView.
    rule = f"{H4_HOURS}h"
    h4 = (m1.resample(rule, label="left", closed="left")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
             .dropna())

    print(f"Built {len(h4):,} H4 candles.\n")

    def show(block, label):
        print(label)
        for t, row in block.iterrows():
            print(f"  {t:%Y-%m-%d %H:%M}   "
                  f"O {row.open:.5f}  H {row.high:.5f}  "
                  f"L {row.low:.5f}  C {row.close:.5f}")
        print()

    show(h4.head(10), "FIRST 10 H4 candles (compare these to TradingView):")
    show(h4.tail(5),  "LAST 5 H4 candles (compare these to TradingView):")

    print("Next: open TradingView on the EURUSD H4 chart, hover the same")
    print("candles, and check the O/H/L/C and the candle TIME match. Tell me")
    print("if they match, or if everything is shifted by a fixed number of hours.")


if __name__ == "__main__":
    main()
