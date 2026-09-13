#!/usr/bin/env python3
"""
si_engine.py -- shared, faithful port of the locked indicator's core.
Used by the per-group pre-calc scripts so there is ONE engine, not copies.

Contains ONLY what is verified so far:
  * loading the FXCM 1-minute CSV,
  * resampling to H4 and to Weekly candles,
  * swing-high / swing-low detection + regime/MSS,
  * emitting a draw-only Pine overlay for swings + MSS.

Order-block trigger / eligibility / impact are NOT here yet -- they arrive in
later groups and will be added deliberately, one verified piece at a time.
"""

import pandas as pd


# ============================================================
# LOADING
# ============================================================
def load_m1(path, feed="Bid", date_format="%m/%d/%Y %H:%M:%S", tz_shift_hours=0):
    df = pd.read_csv(path)
    needed = ["Date", "Time",
              f"Open{feed}", f"High{feed}", f"Low{feed}", f"Close{feed}"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns {missing}. Found: {list(df.columns)}")
    ts = pd.to_datetime(df["Date"].astype(str).str.strip() + " "
                        + df["Time"].astype(str).str.strip(),
                        format=date_format)
    if tz_shift_hours:
        ts = ts + pd.Timedelta(hours=tz_shift_hours)
    m1 = pd.DataFrame({
        "open":  df[f"Open{feed}"].to_numpy(),
        "high":  df[f"High{feed}"].to_numpy(),
        "low":   df[f"Low{feed}"].to_numpy(),
        "close": df[f"Close{feed}"].to_numpy(),
    }, index=pd.DatetimeIndex(ts)).sort_index()
    return m1


def _ms(ts):
    return int(pd.Timestamp(ts).value // 1_000_000)  # ns -> ms


def _highfirst_children(block, bh, bl):
    """Faithful to h4_highFirst / w_highFirst: first minute reaching the
    candle high vs first minute reaching the candle low; tie -> that
    minute's own close<open."""
    hi_pos = int((block["high"].to_numpy() >= bh).argmax())
    lo_pos = int((block["low"].to_numpy() <= bl).argmax())
    if hi_pos < lo_pos:
        return True
    if lo_pos < hi_pos:
        return False
    r = block.iloc[hi_pos]
    return float(r["close"]) < float(r["open"])


def resample_h4(m1):
    """H4 candles. High/low order resolved from 1m children (faithful to the
    locked h4_highFirst). Returns O,H,L,C, BTms, highFirst, blocks."""
    grp = m1.resample("4h", label="left", closed="left")
    O = []; H = []; L = []; C = []; BTms = []; highFirst = []; blocks = []
    for bstart, block in grp:
        if len(block) == 0:
            continue
        bo = float(block["open"].iloc[0]); bh = float(block["high"].max())
        bl = float(block["low"].min());   bc = float(block["close"].iloc[-1])
        O.append(bo); H.append(bh); L.append(bl); C.append(bc)
        BTms.append(_ms(bstart)); highFirst.append(_highfirst_children(block, bh, bl))
        blocks.append(block)
    return O, H, L, C, BTms, highFirst, blocks


def resample_weekly(m1, anchor_weekday=0):
    """Weekly candles grouped by a fixed week-start weekday (0=Mon ... 6=Sun).
    High/low order = candle colour (close<open), per owner: weekly swings/MSS
    do not need 1m. Returns O,H,L,C, BTms, highFirst, blocks."""
    idx = m1.index
    days_since = (idx.weekday - anchor_weekday) % 7
    week_start = (idx.normalize() - pd.to_timedelta(days_since, unit="D"))
    m1w = m1.assign(_wk=week_start)
    O = []; H = []; L = []; C = []; BTms = []; highFirst = []; blocks = []
    for wk, block in m1w.groupby("_wk", sort=True):
        if len(block) == 0:
            continue
        bo = float(block["open"].iloc[0]); bh = float(block["high"].max())
        bl = float(block["low"].min());   bc = float(block["close"].iloc[-1])
        O.append(bo); H.append(bh); L.append(bl); C.append(bc)
        # faithful to w_highFirst: 1m children decide high/low order (tie -> colour)
        BTms.append(_ms(wk)); highFirst.append(_highfirst_children(block, bh, bl))
        blocks.append(block)
    return O, H, L, C, BTms, highFirst, blocks


# ============================================================
# FAITHFUL SWING + MSS ENGINE (ported from the locked Pine)
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
    """Returns swHighs, swLows (pivot indices), msses (list[Mss])."""
    n = len(O)
    events = []; msses = []; swHighs = []; swLows = []
    peakIdx = 0; troughIdx = 0
    haveSWH = False; swhPrice = 0.0; swhIdx = 0
    haveSWL = False; swlPrice = 0.0; swlIdx = 0
    regime = 0; ei = 0
    lastSWHidx = -1; lastSWLidx = -1  # noqa: F841 (kept for parity/readability)

    def addSH(idx):
        if not swHighs or swHighs[-1] != idx:
            swHighs.append(idx)

    def addSL(idx):
        if not swLows or swLows[-1] != idx:
            swLows.append(idx)

    for i in range(1, n):
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

        if not isBull:
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

        k = i
        evTotal = len(events)

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
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    msses.append(Mss(k, swhIdx, swhPrice, True))
                haveSWH = False; swhCons = True
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
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    msses.append(Mss(k, swlIdx, swlPrice, False))
                haveSWL = False; swlCons = True
        else:
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    msses.append(Mss(k, swlIdx, swlPrice, False))
                haveSWL = False; swlCons = True
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
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    msses.append(Mss(k, swhIdx, swhPrice, True))
                haveSWH = False; swhCons = True

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
# DRAW-ONLY PINE EMITTER (swings + MSS)
# ============================================================
_PINE = '''//@version=6
// AUTO-GENERATED by tools/precalc -- do not hand-edit.
// {title}
// Pre-computed from FXCM 1-minute {feed} data. Load on the matching EURUSD
// chart next to your live indicator and check markers land on the same candles.
indicator("{title}", overlay=true, max_labels_count=500, max_lines_count=500)

InpShowSH  = input.bool(true,  "Swing highs")
InpShowSL  = input.bool(true,  "Swing lows")
InpShowMSS = input.bool(true,  "MSS")

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


def emit_structure_pine(out_path, title, feed, swHighs, swLows, msses, H, L, BTms):
    sh = ",".join(f"{BTms[i]}:{H[i]:.5f}" for i in swHighs)
    sl = ",".join(f"{BTms[i]}:{L[i]:.5f}" for i in swLows)
    ms = ",".join(f"{BTms[m.atIdx]}:{m.price:.5f}:{1 if m.toUp else 0}"
                  for m in msses)
    with open(out_path, "w") as f:
        f.write(_PINE.format(title=title, feed=feed, sh=sh, sl=sl, mss=ms))
