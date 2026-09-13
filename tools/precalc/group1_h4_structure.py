#!/usr/bin/env python3
"""
GROUP 1 of the pre-calculation pipeline: H4 STRUCTURE
=====================================================
Reads your FXCM 1-minute file, builds H4 candles, then finds the H4
SWING HIGHS / SWING LOWS and the MSS (market-structure-shift) points --
using the EXACT logic from your locked indicator (no invented rules).

It writes a ready-to-use TradingView indicator file:  group1_h4_structure.pine
You paste that into TradingView and it draws the swings + MSS on your H4 chart,
so you can check they land on the same candles as your live indicator.

The 1-minute data is used two ways, exactly like your locked indicator:
  * grouped into H4 candles (structure is measured on H4), and
  * kept raw to decide, inside each H4 candle, whether the HIGH or the LOW
    happened first (this changes which swing gets confirmed first).

How to run (in the folder that has your CSV):
    python group1_h4_structure.py EURUSD_m1_BidAndAsk.csv

Then open group1_h4_structure.pine, copy all of it, and paste into a new
TradingView Pine indicator on your EURUSD H4 chart.
"""

import sys
import pandas as pd

# ------------------------------------------------------------------
# SETTINGS we may tune together (one line each). Change nothing yet.
# ------------------------------------------------------------------
FEED = "Bid"                          # "Bid" or "Ask" -- we start with Bid
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"     # your file shows e.g. 1/2/2026 6:31:00
TZ_SHIFT_HOURS = 0                    # if markers are shifted vs TradingView,
                                      # we set this together (e.g. -5, +2, +3)
H4_HOURS = 4


# ============================================================
# 1) LOAD 1-MINUTE DATA
# ============================================================
def load_m1(path):
    df = pd.read_csv(path)
    needed = ["Date", "Time",
              f"Open{FEED}", f"High{FEED}", f"Low{FEED}", f"Close{FEED}"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns {missing}. Found: {list(df.columns)}")
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
    return m1


# ============================================================
# 2) BUILD H4 CANDLES (+ was the high or the low first?)
# ============================================================
def build_h4(m1):
    """Returns parallel lists O,H,L,C, BTms (open time in unix-ms UTC),
    and highFirst (True if the H4 candle's high happened before its low).
    highFirst mirrors the locked indicator's h4_highFirst(): first minute
    reaching the candle high vs first minute reaching the candle low; a tie
    is broken by that minute's own close<open."""
    rule = f"{H4_HOURS}h"
    grp = m1.resample(rule, label="left", closed="left")
    O, H, L, C, BTms, highFirst = [], [], [], [], [], []
    for bucket_start, block in grp:
        if len(block) == 0:
            continue
        bo = float(block["open"].iloc[0])
        bh = float(block["high"].max())
        bl = float(block["low"].min())
        bc = float(block["close"].iloc[-1])
        # first minute reaching the extreme
        hi_pos = int((block["high"].to_numpy() >= bh).argmax())
        lo_pos = int((block["low"].to_numpy() <= bl).argmax())
        if hi_pos < lo_pos:
            hf = True
        elif lo_pos < hi_pos:
            hf = False
        else:  # same minute owns both extremes -> that minute's colour
            r = block.iloc[hi_pos]
            hf = float(r["close"]) < float(r["open"])
        O.append(bo); H.append(bh); L.append(bl); C.append(bc)
        BTms.append(int(bucket_start.value // 1_000_000))  # ns -> ms
        highFirst.append(hf)
    return O, H, L, C, BTms, highFirst


# ============================================================
# 3) FAITHFUL SWING + MSS ENGINE (ported from the locked Pine)
#    Only swing detection + regime/MSS is kept here; order-block
#    machinery belongs to Group 2 and is deliberately absent.
# ============================================================
class Ev:
    __slots__ = ("confirmIdx", "kind", "swingIdx", "price")
    def __init__(self, c, k, s, p):
        self.confirmIdx = c; self.kind = k; self.swingIdx = s; self.price = p

class Mss:
    __slots__ = ("atIdx", "brokenIdx", "price", "toUp")
    def __init__(self, a, b, p, u):
        self.atIdx = a; self.brokenIdx = b; self.price = p; self.toUp = u


def run_engine(O, H, L, C, highFirst):
    n = len(O)
    events = []          # list[Ev]
    msses = []           # list[Mss]
    swHighs = []         # list[int]  swing-high pivot indices (deduped)
    swLows = []          # list[int]

    peakIdx = 0
    troughIdx = 0
    haveSWH = False; swhPrice = 0.0; swhIdx = 0
    haveSWL = False; swlPrice = 0.0; swlIdx = 0
    regime = 0           # 0=warmup, 1=up, 2=down
    ei = 0
    lastSWHidx = -1; lastSWLidx = -1

    def addSH(idx):
        if not swHighs or swHighs[-1] != idx:
            swHighs.append(idx)
    def addSL(idx):
        if not swLows or swLows[-1] != idx:
            swLows.append(idx)

    for i in range(1, n):
        # ----- prevDual dedup lookback -----
        prevDual = False; pdKind1 = pdIdx1 = pdKind2 = pdIdx2 = -1
        if len(events) >= 2:
            ev1 = events[-1]; ev2 = events[-2]
            if (ev1.kind != ev2.kind and ev1.confirmIdx == ev2.confirmIdx
                    and ev1.confirmIdx == i - 1):
                prevDual = True
                pdKind1 = ev1.kind; pdIdx1 = ev1.swingIdx
                pdKind2 = ev2.kind; pdIdx2 = ev2.swingIdx

        isBull = not highFirst[i]
        brkH = H[i] > H[i - 1]
        brkL = L[i] < L[i - 1]
        dualAct = brkH and brkL

        # ----- SWING DETECTION -----
        if not isBull:
            # BEARISH: high first, then low
            if H[i] > H[peakIdx]:
                peakIdx = i
            if brkH:
                lk = events[-1].kind if events else -1
                blockDup = (prevDual and not dualAct and
                            ((pdKind1 == 1 and pdIdx1 == troughIdx) or
                             (pdKind2 == 1 and pdIdx2 == troughIdx)))
                if lk != 1 and not blockDup:
                    addSL(troughIdx)
                    events.append(Ev(i, 1, troughIdx, L[troughIdx]))
                    peakIdx = i
            if L[i] < L[troughIdx]:
                troughIdx = i
            if brkL:
                lk2 = events[-1].kind if events else -1
                blockDup2 = (prevDual and not dualAct and
                             ((pdKind1 == 0 and pdIdx1 == peakIdx) or
                              (pdKind2 == 0 and pdIdx2 == peakIdx)))
                if lk2 != 0 and not blockDup2:
                    addSH(peakIdx)
                    events.append(Ev(i, 0, peakIdx, H[peakIdx]))
                    troughIdx = i
        else:
            # BULLISH: low first, then high
            if L[i] < L[troughIdx]:
                troughIdx = i
            if brkL:
                lk3 = events[-1].kind if events else -1
                blockDup3 = (prevDual and not dualAct and
                             ((pdKind1 == 0 and pdIdx1 == peakIdx) or
                              (pdKind2 == 0 and pdIdx2 == peakIdx)))
                if lk3 != 0 and not blockDup3:
                    addSH(peakIdx)
                    events.append(Ev(i, 0, peakIdx, H[peakIdx]))
                    troughIdx = i
            if H[i] > H[peakIdx]:
                peakIdx = i
            if brkH:
                lk4 = events[-1].kind if events else -1
                blockDup4 = (prevDual and not dualAct and
                             ((pdKind1 == 1 and pdIdx1 == troughIdx) or
                              (pdKind2 == 1 and pdIdx2 == troughIdx)))
                if lk4 != 1 and not blockDup4:
                    addSL(troughIdx)
                    events.append(Ev(i, 1, troughIdx, L[troughIdx]))
                    peakIdx = i

        # ----- REGIME / MSS ENGINE -----
        k = i
        evTotal = len(events)

        # STEP 0: peek-ahead to update lastSWHidx/lastSWLidx
        peek0 = ei
        while peek0 < evTotal:
            pEv = events[peek0]
            if pEv.confirmIdx != k:
                break
            if pEv.kind == 0:
                lastSWHidx = pEv.swingIdx
            else:
                lastSWLidx = pEv.swingIdx
            peek0 += 1

        swhCons = False; swlCons = False
        kBull = not highFirst[k]

        if not kBull:
            # SWH break first
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    msses.append(Mss(k, swhIdx, swhPrice, True))
                haveSWH = False; swhCons = True
            # MID-ARM
            peek2 = ei
            while peek2 < evTotal:
                pEv2 = events[peek2]
                if pEv2.confirmIdx != k:
                    break
                if pEv2.kind == 0:
                    haveSWH = True; swhPrice = pEv2.price; swhIdx = pEv2.swingIdx
                else:
                    haveSWL = True; swlPrice = pEv2.price; swlIdx = pEv2.swingIdx
                peek2 += 1
            # SWL break
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    msses.append(Mss(k, swlIdx, swlPrice, False))
                haveSWL = False; swlCons = True
        else:
            # SWL break first
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    msses.append(Mss(k, swlIdx, swlPrice, False))
                haveSWL = False; swlCons = True
            # MID-ARM
            peek3 = ei
            while peek3 < evTotal:
                pEv3 = events[peek3]
                if pEv3.confirmIdx != k:
                    break
                if pEv3.kind == 0:
                    haveSWH = True; swhPrice = pEv3.price; swhIdx = pEv3.swingIdx
                else:
                    haveSWL = True; swlPrice = pEv3.price; swlIdx = pEv3.swingIdx
                peek3 += 1
            # SWH break
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    msses.append(Mss(k, swhIdx, swhPrice, True))
                haveSWH = False; swhCons = True

        # STEP 2: arm swings confirmed at this bar
        while ei < evTotal:
            sEv = events[ei]
            if sEv.confirmIdx != k:
                break
            if sEv.kind == 0:
                if not swhCons:
                    haveSWH = True; swhPrice = sEv.price; swhIdx = sEv.swingIdx
                lastSWHidx = sEv.swingIdx
            else:
                if not swlCons:
                    haveSWL = True; swlPrice = sEv.price; swlIdx = sEv.swingIdx
                lastSWLidx = sEv.swingIdx
            ei += 1

    return swHighs, swLows, msses


# ============================================================
# 4) EMIT THE DRAW-ONLY PINE FILE
# ============================================================
PINE_TEMPLATE = '''//@version=6
// AUTO-GENERATED by tools/precalc/group1_h4_structure.py -- do not hand-edit.
// GROUP 1 verification overlay: H4 swing highs / lows + MSS, pre-computed from
// FXCM 1-minute {feed} data. Load on your EURUSD H4 chart next to your live
// indicator and check the markers land on the same candles.
indicator("Pre-calc G1 - H4 Structure", overlay=true, max_labels_count=500, max_lines_count=500)

InpShowSH  = input.bool(true,  "Swing highs")
InpShowSL  = input.bool(true,  "Swing lows")
InpShowMSS = input.bool(true,  "MSS")

// Pre-computed data. Format "timeMs:price" pairs (MSS adds ":1" up / ":0" down).
var string SH_DATA  = "{sh}"
var string SL_DATA  = "{sl}"
var string MSS_DATA = "{mss}"

drawPairs(string s, bool isHigh) =>
    if str.length(s) > 0
        toks = str.split(s, ",")
        for ti = 0 to array.size(toks) - 1
            kv = str.split(array.get(toks, ti), ":")
            if array.size(kv) == 2
                int tt = int(str.tonumber(array.get(kv, 0)))
                float pp = str.tonumber(array.get(kv, 1))
                label.new(tt, pp, isHigh ? "SH" : "SL", xloc=xloc.bar_time,
                     style = isHigh ? label.style_label_down : label.style_label_up,
                     color = isHigh ? color.new(color.red, 0) : color.new(color.green, 0),
                     textcolor = color.white, size = size.tiny)

drawMss(string s) =>
    if str.length(s) > 0
        toks = str.split(s, ",")
        for ti = 0 to array.size(toks) - 1
            kv = str.split(array.get(toks, ti), ":")
            if array.size(kv) == 3
                int tt = int(str.tonumber(array.get(kv, 0)))
                float pp = str.tonumber(array.get(kv, 1))
                bool up = array.get(kv, 2) == "1"
                label.new(tt, pp, up ? "MSS up" : "MSS dn", xloc=xloc.bar_time,
                     style = up ? label.style_label_up : label.style_label_down,
                     color = up ? color.new(color.teal, 0) : color.new(color.maroon, 0),
                     textcolor = color.white, size = size.small)

if barstate.islast
    if InpShowSH
        drawPairs(SH_DATA, true)
    if InpShowSL
        drawPairs(SL_DATA, false)
    if InpShowMSS
        drawMss(MSS_DATA)
'''


def emit_pine(out_path, feed, swHighs, swLows, msses, H, L, BTms):
    sh = ",".join(f"{BTms[i]}:{H[i]:.5f}" for i in swHighs)
    sl = ",".join(f"{BTms[i]}:{L[i]:.5f}" for i in swLows)
    ms = ",".join(f"{BTms[m.atIdx]}:{m.price:.5f}:{1 if m.toUp else 0}"
                  for m in msses)
    with open(out_path, "w") as f:
        f.write(PINE_TEMPLATE.format(feed=feed, sh=sh, sl=sl, mss=ms))


# ============================================================
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "EURUSD_m1_BidAndAsk.csv"
    print(f"Reading {path} ...")
    m1 = load_m1(path)
    print(f"Loaded {len(m1):,} one-minute rows ({FEED}).")
    print(f"Range: {m1.index[0]}  ->  {m1.index[-1]}")

    O, H, L, C, BTms, highFirst = build_h4(m1)
    print(f"Built {len(O):,} H4 candles.")

    swHighs, swLows, msses = run_engine(O, H, L, C, highFirst)
    print(f"Found {len(swHighs)} swing highs, {len(swLows)} swing lows, "
          f"{len(msses)} MSS points.")

    out = "group1_h4_structure.pine"
    emit_pine(out, FEED, swHighs, swLows, msses, H, L, BTms)
    print(f"\nWrote {out}")
    print("Open it, copy ALL of it, and paste into a new Pine indicator on your")
    print("EURUSD H4 chart. Check the SH/SL/MSS markers vs your live indicator.")


if __name__ == "__main__":
    main()
