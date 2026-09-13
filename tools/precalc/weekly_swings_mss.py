#!/usr/bin/env python3
"""
WEEKLY step 1: Weekly candles + Weekly swings + Weekly MSS
==========================================================
The no-1m foundation the Weekly order blocks sit on. It:
  1. reads your FXCM 1-minute file,
  2. groups it into WEEKLY candles,
  3. prints the first/last few weekly candles so you can check them against
     your TradingView WEEKLY chart,
  4. finds the weekly swing highs/lows + MSS with the locked logic, and
  5. writes weekly_swings_mss.pine to draw them.

Weekly high/low order uses the candle colour (close<open) -- your locked
indicator's own fallback -- because weekly swings/MSS do not need 1m data.

Run (in the folder with your CSV):
    python weekly_swings_mss.py EURUSD_m1_BidAndAsk.csv

Then paste weekly_swings_mss.pine into a new Pine indicator on your EURUSD
WEEKLY chart and compare with your live indicator.
"""

import sys
import pandas as pd
import si_engine as eng

# ------------------------------------------------------------------
# SETTINGS we may tune together. Change nothing yet.
# ------------------------------------------------------------------
FEED = "Bid"
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"
TZ_SHIFT_HOURS = 0
WEEK_ANCHOR_WEEKDAY = 0   # 0=Mon 1=Tue ... 6=Sun. Forex weekly often opens
                          # Sunday(6) or Monday(0). If the weekly candles are
                          # off by a day/boundary vs TradingView, we change this.


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "EURUSD_m1_BidAndAsk.csv"
    print(f"Reading {path} ...")
    m1 = eng.load_m1(path, feed=FEED, date_format=DATE_FORMAT,
                     tz_shift_hours=TZ_SHIFT_HOURS)
    print(f"Loaded {len(m1):,} one-minute rows ({FEED}).")
    print(f"Range: {m1.index[0]}  ->  {m1.index[-1]}\n")

    O, H, L, C, BTms, highFirst, _blocks = eng.resample_weekly(
        m1, anchor_weekday=WEEK_ANCHOR_WEEKDAY)
    print(f"Built {len(O):,} weekly candles "
          f"(week starts on weekday {WEEK_ANCHOR_WEEKDAY}: 0=Mon..6=Sun).\n")

    def show(rng, label):
        print(label)
        for i in rng:
            t = pd.Timestamp(BTms[i], unit="ms")
            print(f"  {t:%Y-%m-%d}   O {O[i]:.5f}  H {H[i]:.5f}  "
                  f"L {L[i]:.5f}  C {C[i]:.5f}")
        print()

    show(range(0, min(6, len(O))), "FIRST weekly candles (compare to TradingView):")
    show(range(max(0, len(O) - 4), len(O)), "LAST weekly candles (compare to TradingView):")

    swHighs, swLows, msses = eng.run_engine(O, H, L, C, highFirst)
    print(f"Found {len(swHighs)} weekly swing highs, {len(swLows)} swing lows, "
          f"{len(msses)} MSS points.")

    out = "weekly_swings_mss.pine"
    eng.emit_structure_pine(out, "Pre-calc Weekly - Swings + MSS", FEED,
                            swHighs, swLows, msses, H, L, BTms)
    print(f"\nWrote {out}")
    print("Paste it into a Pine indicator on your EURUSD WEEKLY chart and check")
    print("the SH/SL/MSS markers vs your live indicator. Tell me: do the weekly")
    print("CANDLES match first (dates + O/H/L/C), then do the markers match?")


if __name__ == "__main__":
    main()
