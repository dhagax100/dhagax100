#!/usr/bin/env python3
"""
GROUP 1: H4 swings + MSS (thin wrapper over si_engine.py)
=========================================================
Reads your FXCM 1-minute file, builds H4 candles, finds the H4 swing highs /
lows and MSS with the locked logic, and writes group1_h4_structure.pine to
draw them on your EURUSD H4 chart.

H4 high/low order is resolved from the 1m children (faithful to the locked
h4_highFirst), because inside a single H4 candle the order of the high vs the
low can change which swing confirms first.

Run (in the folder with your CSV):
    python group1_h4_structure.py EURUSD_m1_BidAndAsk.csv
"""

import sys
import si_engine as eng

FEED = "Bid"
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"
TZ_SHIFT_HOURS = 0


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "EURUSD_m1_BidAndAsk.csv"
    print(f"Reading {path} ...")
    m1 = eng.load_m1(path, feed=FEED, date_format=DATE_FORMAT,
                     tz_shift_hours=TZ_SHIFT_HOURS)
    print(f"Loaded {len(m1):,} one-minute rows ({FEED}).")
    print(f"Range: {m1.index[0]}  ->  {m1.index[-1]}")

    O, H, L, C, BTms, highFirst, _blocks = eng.resample_h4(m1)
    print(f"Built {len(O):,} H4 candles.")

    swHighs, swLows, msses = eng.run_engine(O, H, L, C, highFirst)
    print(f"Found {len(swHighs)} swing highs, {len(swLows)} swing lows, "
          f"{len(msses)} MSS points.")

    out = "group1_h4_structure.pine"
    eng.emit_structure_pine(out, "Pre-calc G1 - H4 Structure", FEED,
                            swHighs, swLows, msses, H, L, BTms)
    print(f"\nWrote {out}")
    print("Paste it into a Pine indicator on your EURUSD H4 chart and check the")
    print("SH/SL/MSS markers vs your live indicator.")


if __name__ == "__main__":
    main()
