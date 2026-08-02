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

    mss_events: list of dicts {bar, direction ('up'/'down'), swing_idx, swing_price,
    leg_price, leg_idx}. `leg_price`/`leg_idx` are the price/bar of the swing
    on the OPPOSITE side that immediately precedes, in the confirmed-event
    sequence, the swing this MSS event just broke -- i.e. the leg's own
    origin swing, which is what a trade entered on this MSS would use as its
    stop. Since confirmed swings strictly alternate kind (enforced by the
    lastWasLow/lastWasHigh guards below), the event immediately before any
    given swing in the log is guaranteed to be the opposite kind.

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
    swhListPos = swlListPos = -1  # position of the armed swing in the event log
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
                    leg_p, leg_i = (ev_price[swhListPos - 1], ev_swing_idx[swhListPos - 1]) if swhListPos > 0 else (None, None)
                    mss_events.append({"bar": i, "dir": "up", "swing_idx": swhIdx, "swing_price": swhPrice,
                                      "leg_price": leg_p, "leg_idx": leg_i})
                haveSWH = False
            for idx in range(before, after):
                if ev_kind[idx] == 0:
                    haveSWH, swhPrice, swhIdx, swhListPos = True, ev_price[idx], ev_swing_idx[idx], idx
                else:
                    haveSWL, swlPrice, swlIdx, swlListPos = True, ev_price[idx], ev_swing_idx[idx], idx
            if haveSWL and lows[i] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    leg_p, leg_i = (ev_price[swlListPos - 1], ev_swing_idx[swlListPos - 1]) if swlListPos > 0 else (None, None)
                    mss_events.append({"bar": i, "dir": "down", "swing_idx": swlIdx, "swing_price": swlPrice,
                                      "leg_price": leg_p, "leg_idx": leg_i})
                haveSWL = False
        else:
            if haveSWL and lows[i] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2
                    leg_p, leg_i = (ev_price[swlListPos - 1], ev_swing_idx[swlListPos - 1]) if swlListPos > 0 else (None, None)
                    mss_events.append({"bar": i, "dir": "down", "swing_idx": swlIdx, "swing_price": swlPrice,
                                      "leg_price": leg_p, "leg_idx": leg_i})
                haveSWL = False
            for idx in range(before, after):
                if ev_kind[idx] == 0:
                    haveSWH, swhPrice, swhIdx, swhListPos = True, ev_price[idx], ev_swing_idx[idx], idx
                else:
                    haveSWL, swlPrice, swlIdx, swlListPos = True, ev_price[idx], ev_swing_idx[idx], idx
            if haveSWH and highs[i] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1
                    leg_p, leg_i = (ev_price[swhListPos - 1], ev_swing_idx[swhListPos - 1]) if swhListPos > 0 else (None, None)
                    mss_events.append({"bar": i, "dir": "up", "swing_idx": swhIdx, "swing_price": swhPrice,
                                      "leg_price": leg_p, "leg_idx": leg_i})
                haveSWH = False

        regime_at_bar[i] = regime

    event_log = {"kind": ev_kind, "confirm_idx": ev_confirm_idx,
                "swing_idx": ev_swing_idx, "price": ev_price}
    return mss_events, regime_at_bar, event_log
