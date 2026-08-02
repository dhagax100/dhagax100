"""Faithful port of the swing-detection + regime/MSS logic from
ICT_Full_OB_v24_indicator_2.pine (the user's own indicator), stripped of the
order-block engine (IFOB/AOB/AIFOB/OOB/SPENT), which this research doesn't
need -- only swing confirmation and MSS marking.

Ported piece for piece against the source:
  - Swing detection: lines 171-236 (one-bar-break confirmation, intrabar
    ordering by candle direction, alternation guard, post-dual-candle block).
  - Regime/MSS: the break-check + arm halves of lines 259-407 (STEP 0's
    lastSWHidx/lastSWLidx peek-ahead and STEP 2's redundant re-arm exist in
    the original only to feed the OB engine's zone geometry -- confirmed by
    re-reading them against every call site, neither one affects `regime`,
    `haveSWH/haveSWL`, or `swhPrice/swlPrice`, so omitting them changes
    nothing about swing/MSS results while dropping OB-only bookkeeping).

Runs as ONE continuous pass over the whole series, matching how the
indicator actually behaves live on a chart -- state carries across days,
not reset per day.
"""
import numpy as np


def run_engine(opens, highs, lows, closes):
    """Returns (mss_events, regime_at_bar).

    mss_events: list of dicts {bar, direction ('up'/'down'), swing_idx, swing_price}
    regime_at_bar: int array, regime AFTER processing each bar (0 warmup, 1 up, 2 down)
    """
    n = len(closes)
    regime_at_bar = np.zeros(n, dtype=np.int8)

    peakIdx, peakH = 0, highs[0]
    troughIdx, troughL = 0, lows[0]

    ev_kind, ev_confirm_idx, ev_swing_idx, ev_price = [], [], [], []

    haveSWH = haveSWL = False
    swhPrice = swlPrice = 0.0
    swhIdx = swlIdx = 0
    regime = 0
    mss_events = []

    for i in range(1, n):
        bullishBar = closes[i] >= opens[i]
        breaksPrevHigh = highs[i] > highs[i - 1]
        breaksPrevLow = lows[i] < lows[i - 1]
        dualAction = breaksPrevHigh and breaksPrevLow

        prevDual = False
        if len(ev_kind) >= 2:
            prevDual = (ev_kind[-1] != ev_kind[-2] and ev_confirm_idx[-1] == ev_confirm_idx[-2]
                       and ev_confirm_idx[-1] == i - 1)
        blockPostDual = prevDual and not dualAction

        before = len(ev_kind)

        if not bullishBar:
            if highs[i] > peakH:
                peakIdx, peakH = i, highs[i]
            if breaksPrevHigh:
                lastWasLow = ev_kind and ev_kind[-1] == 1
                if not lastWasLow and not blockPostDual:
                    ev_kind.append(1); ev_confirm_idx.append(i); ev_swing_idx.append(troughIdx); ev_price.append(troughL)
                    peakIdx, peakH = i, highs[i]
            if lows[i] < troughL:
                troughIdx, troughL = i, lows[i]
            if breaksPrevLow:
                lastWasHigh = ev_kind and ev_kind[-1] == 0
                if not lastWasHigh and not blockPostDual:
                    ev_kind.append(0); ev_confirm_idx.append(i); ev_swing_idx.append(peakIdx); ev_price.append(peakH)
                    troughIdx, troughL = i, lows[i]
        else:
            if lows[i] < troughL:
                troughIdx, troughL = i, lows[i]
            if breaksPrevLow:
                lastWasHigh = ev_kind and ev_kind[-1] == 0
                if not lastWasHigh and not blockPostDual:
                    ev_kind.append(0); ev_confirm_idx.append(i); ev_swing_idx.append(peakIdx); ev_price.append(peakH)
                    troughIdx, troughL = i, lows[i]
            if highs[i] > peakH:
                peakIdx, peakH = i, highs[i]
            if breaksPrevHigh:
                lastWasLow = ev_kind and ev_kind[-1] == 1
                if not lastWasLow and not blockPostDual:
                    ev_kind.append(1); ev_confirm_idx.append(i); ev_swing_idx.append(troughIdx); ev_price.append(troughL)
                    peakIdx, peakH = i, highs[i]

        after = len(ev_kind)

        # regime / MSS -- break-check then arm, ordered by which side the
        # candle's own direction implies happened first (matches the .pine)
        if not bullishBar:
            if haveSWH and highs[i] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    mss_events.append({"bar": i, "dir": "up", "swing_idx": swhIdx, "swing_price": swhPrice})
                haveSWH = False
            for idx in range(before, after):
                if ev_kind[idx] == 0:
                    haveSWH, swhPrice, swhIdx = True, ev_price[idx], ev_swing_idx[idx]
                else:
                    haveSWL, swlPrice, swlIdx = True, ev_price[idx], ev_swing_idx[idx]
            if haveSWL and lows[i] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    mss_events.append({"bar": i, "dir": "down", "swing_idx": swlIdx, "swing_price": swlPrice})
                haveSWL = False
        else:
            if haveSWL and lows[i] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    mss_events.append({"bar": i, "dir": "down", "swing_idx": swlIdx, "swing_price": swlPrice})
                haveSWL = False
            for idx in range(before, after):
                if ev_kind[idx] == 0:
                    haveSWH, swhPrice, swhIdx = True, ev_price[idx], ev_swing_idx[idx]
                else:
                    haveSWL, swlPrice, swlIdx = True, ev_price[idx], ev_swing_idx[idx]
            if haveSWH and highs[i] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    mss_events.append({"bar": i, "dir": "up", "swing_idx": swhIdx, "swing_price": swhPrice})
                haveSWH = False

        regime_at_bar[i] = regime

    return mss_events, regime_at_bar
