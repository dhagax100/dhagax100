#!/usr/bin/env python3
"""
WEEKLY ORDER BLOCKS -- trigger / eligibility / impact at the EXACT minute
========================================================================
Faithful port of your locked indicator's Weekly OB engine (locked4):
  * weekly candles built from your 1m data (high/low order via 1m children),
  * IFOB / AOB / AIFOB creation, eligibility, impact, stranding, rejection,
  * trigger, eligibility and impact each resolved to the EXACT 1-minute time
    (w_childEventTime / w_childFirstTouch / weeklyTriggerEventTime).

Outputs:
  * weekly_ob.pine  -- draws each IMPACTED weekly OB box + impact line at the
    exact minute, on your EURUSD H4 (or Weekly) chart.
  * a printed report: every impacted OB with trigger / eligibility / impact time.

Run (in the folder with your CSV + si_engine.py):
    python weekly_ob.py EURUSD_m1_BidAndAsk.csv
"""

import sys
import pandas as pd
import si_engine as eng

# ---- settings we may tune together ----
FEED = "Bid"
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"
TZ_SHIFT_HOURS = 0
WEEK_ANCHOR_WEEKDAY = 0     # 0=Mon..6=Sun


class OB:
    __slots__ = ("candle", "zb", "zt", "bullish", "triggerK", "eligibleK",
                 "stopK", "eligibleTime", "impactTime", "eligibleKind",
                 "state", "origState", "preSpentState", "rejected")

    def __init__(self, candle, zb, zt, bullish, tK, st):
        self.candle = candle; self.zb = zb; self.zt = zt; self.bullish = bullish
        self.triggerK = tK; self.eligibleK = -1; self.stopK = -1
        self.eligibleTime = -1; self.impactTime = -1; self.eligibleKind = -1
        self.state = st; self.origState = st; self.preSpentState = st
        self.rejected = False


class SwEv:
    __slots__ = ("confirmIdx", "kind", "swingIdx", "price")
    def __init__(self, c, k, s, p):
        self.confirmIdx = c; self.kind = k; self.swingIdx = s; self.price = p


def run_weekly_ob(O, H, L, C, BTms, highFirst, wkT, wkH, wkL, wkO, wkC):
    n = len(O)
    events = []; obs = []; activeObs = []
    swHighs = []; swLows = []; msses = []

    peakIdx = 0; troughIdx = 0
    haveSWH = False; swhPrice = 0.0; swhIdx = 0
    haveSWL = False; swlPrice = 0.0; swlIdx = 0
    regime = 0; ei = 0
    lastSWHidx = -1; lastSWLidx = -1
    pendBullAifob = -1; pendBearAifob = -1

    # ---- exact-minute resolvers (faithful to w_childEventTime/FirstTouch) ----
    def childEventTime(wKind, k):
        if k <= 0 or k >= n:
            return -1
        threshold = L[k - 1] if wKind == 0 else H[k - 1]
        T = wkT[k]; A = wkL[k] if wKind == 0 else wkH[k]
        for idx in range(len(T)):
            hit = (A[idx] < threshold) if wKind == 0 else (A[idx] > threshold)
            if hit:
                return int(T[idx])
        return -1

    def childFirstTouch(fromTime, k, zb, zt):
        T = wkT[k]; Hh = wkH[k]; Ll = wkL[k]
        for idx in range(len(T)):
            mt = int(T[idx])
            if mt >= fromTime and Hh[idx] > zb and Ll[idx] < zt:  # strict
                return mt
        return -1

    # ---- creation helpers ----
    def addSH(idx):
        if not swHighs or swHighs[-1] != idx:
            swHighs.append(idx)

    def addSL(idx):
        if not swLows or swLows[-1] != idx:
            swLows.append(idx)

    def addOB(cand, zb, zt, bull, tK, st):
        obs.append(OB(cand, zb, zt, bull, tK, st))
        activeObs.append(len(obs) - 1)
        return len(obs) - 1

    def candleClaimed(cand, bull):
        return any(z.candle == cand and z.bullish == bull for z in obs)

    def existsAifobInRange(lo, hi, bull):
        return any(z.origState == 4 and z.bullish == bull and lo <= z.candle <= hi
                   for z in obs)

    def tryBullAOB(pReg, aobSWHi, newSwlI, newSwlP, k):
        if pReg == 1 and aobSWHi >= 0:
            armed = H[aobSWHi]
            if any(H[v] >= armed for v in range(aobSWHi + 1, newSwlI + 1)):
                return
            lo2 = max(0, min(aobSWHi - 1, newSwlI)); hi2 = max(aobSWHi - 1, newSwlI)
            best2 = -1
            for x in range(lo2, hi2 + 1):
                if C[x] > O[x] and (best2 == -1 or C[x] > C[best2]):
                    best2 = x
            if best2 != -1 and L[best2] > newSwlP:
                ai = addOB(best2, min(O[best2], C[best2]), max(O[best2], C[best2]),
                           False, k, 1)
                aob = obs[ai]
                if k > 0:
                    if H[k - 1] > aob.zt:
                        aob.rejected = True; aob.eligibleK = -1; aob.stopK = -1
                    else:
                        aob.eligibleK = k; aob.eligibleKind = 1
                        aob.eligibleTime = childEventTime(1, k)

    def tryBearAOB(pReg, aobSWLi, newSwhI, newSwhP, k):
        if pReg == 2 and aobSWLi >= 0:
            armed = L[aobSWLi]
            if any(L[v] <= armed for v in range(aobSWLi + 1, newSwhI + 1)):
                return
            lo2 = max(0, min(aobSWLi - 1, newSwhI)); hi2 = max(aobSWLi - 1, newSwhI)
            best2 = -1
            for x in range(lo2, hi2 + 1):
                if C[x] < O[x] and (best2 == -1 or C[x] < C[best2]):
                    best2 = x
            if best2 != -1 and H[best2] < newSwhP:
                ai = addOB(best2, min(O[best2], C[best2]), max(O[best2], C[best2]),
                           True, k, 1)
                aob = obs[ai]
                if k > 0:
                    if L[k - 1] < aob.zb:
                        aob.rejected = True; aob.eligibleK = -1; aob.stopK = -1
                    else:
                        aob.eligibleK = k; aob.eligibleKind = 0
                        aob.eligibleTime = childEventTime(0, k)

    def tryBullAIFOB(pReg, pHaveSWH, pSwhI, pLastSWLi, newSwlI, k):
        if L[k] < L[newSwlI]:
            return -1
        if pReg == 1 and pHaveSWH and pSwhI >= 0 and pLastSWLi >= 0:
            lo = max(0, min(pLastSWLi, newSwlI, pSwhI - 1))
            hi = max(pLastSWLi, newSwlI, pSwhI - 1)
            best = -1
            for x in range(lo, hi + 1):
                if x < 0:
                    continue
                if C[x] < O[x] and (best == -1 or C[x] < C[best]):
                    best = x
            if best != -1 and not candleClaimed(best, True):
                return addOB(best, min(O[best], C[best]), max(O[best], C[best]),
                             True, k, 4)
        return -1

    def tryBearAIFOB(pReg, pHaveSWL, pSwlI, pLastSWHi, newSwhI, k):
        if H[k] > H[newSwhI]:
            return -1
        if pReg == 2 and pHaveSWL and pSwlI >= 0 and pLastSWHi >= 0:
            lo = max(0, min(pLastSWHi, newSwhI, pSwlI - 1))
            hi = max(pLastSWHi, newSwhI, pSwlI - 1)
            best = -1
            for x in range(lo, hi + 1):
                if x < 0:
                    continue
                if C[x] > O[x] and (best == -1 or C[x] > C[best]):
                    best = x
            if best != -1 and not candleClaimed(best, False):
                return addOB(best, min(O[best], C[best]), max(O[best], C[best]),
                             False, k, 4)
        return -1

    def prune():
        i2 = len(activeObs) - 1
        while i2 >= 0:
            z = obs[activeObs[i2]]
            if z.state == 3 or z.rejected:
                activeObs.pop(i2)
            i2 -= 1

    # ================= main per-week pass =================
    for i in range(1, n):
        prevDual = False; pdK1 = pdI1 = pdK2 = pdI2 = -1
        if len(events) >= 2:
            e1 = events[-1]; e2 = events[-2]
            if (e1.kind != e2.kind and e1.confirmIdx == e2.confirmIdx
                    and e1.confirmIdx == i - 1):
                prevDual = True
                pdK1 = e1.kind; pdI1 = e1.swingIdx; pdK2 = e2.kind; pdI2 = e2.swingIdx

        isBull = not highFirst[i]
        brkH = H[i] > H[i - 1]; brkL = L[i] < L[i - 1]; dualAct = brkH and brkL
        evBeforeSwing = len(events)

        # ---- swing detection ----
        if not isBull:
            if H[i] > H[peakIdx]:
                peakIdx = i
            if brkH:
                lk = events[-1].kind if events else -1
                bd = (prevDual and not dualAct and
                      ((pdK1 == 1 and pdI1 == troughIdx) or (pdK2 == 1 and pdI2 == troughIdx)))
                if lk != 1 and not bd:
                    addSL(troughIdx); events.append(SwEv(i, 1, troughIdx, L[troughIdx])); peakIdx = i
            if L[i] < L[troughIdx]:
                troughIdx = i
            if brkL:
                lk = events[-1].kind if events else -1
                bd = (prevDual and not dualAct and
                      ((pdK1 == 0 and pdI1 == peakIdx) or (pdK2 == 0 and pdI2 == peakIdx)))
                if lk != 0 and not bd:
                    addSH(peakIdx); events.append(SwEv(i, 0, peakIdx, H[peakIdx])); troughIdx = i
        else:
            if L[i] < L[troughIdx]:
                troughIdx = i
            if brkL:
                lk = events[-1].kind if events else -1
                bd = (prevDual and not dualAct and
                      ((pdK1 == 0 and pdI1 == peakIdx) or (pdK2 == 0 and pdI2 == peakIdx)))
                if lk != 0 and not bd:
                    addSH(peakIdx); events.append(SwEv(i, 0, peakIdx, H[peakIdx])); troughIdx = i
            if H[i] > H[peakIdx]:
                peakIdx = i
            if brkH:
                lk = events[-1].kind if events else -1
                bd = (prevDual and not dualAct and
                      ((pdK1 == 1 and pdI1 == troughIdx) or (pdK2 == 1 and pdI2 == troughIdx)))
                if lk != 1 and not bd:
                    addSL(troughIdx); events.append(SwEv(i, 1, troughIdx, L[troughIdx])); peakIdx = i

        k = i; evTotal = len(events)

        # STEP 0 peek
        p0 = ei
        while p0 < evTotal and events[p0].confirmIdx == k:
            if events[p0].kind == 0:
                lastSWHidx = events[p0].swingIdx
            else:
                lastSWLidx = events[p0].swingIdx
            p0 += 1

        prevReg = regime; swhCons = False; swlCons = False
        aobSWHi = swhIdx; aobSWLi = swlIdx
        kBull = not highFirst[k]

        def create_ifob(lo, hi, bull):
            best = -1
            for x in range(lo, hi + 1):
                if x == k:
                    continue
                if bull:
                    if C[x] < O[x] and (best == -1 or C[x] < C[best]):
                        best = x
                else:
                    if C[x] > O[x] and (best == -1 or C[x] > C[best]):
                        best = x
            if best != -1 and not candleClaimed(best, bull):
                addOB(best, min(O[best], C[best]), max(O[best], C[best]), bull, k, 0)

        def promote_aifob(pend):
            z = obs[pend]
            z.state = 0; z.origState = 0; z.eligibleK = -1

        if not kBull:
            # SWH break
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1; msses.append((k, swhIdx, swhPrice, True))
                alive = pendBullAifob != -1 and obs[pendBullAifob].state == 4
                if alive:
                    promote_aifob(pendBullAifob)
                pendBullAifob = -1
                if not alive and lastSWLidx >= 0:
                    lo = min(lastSWLidx, k, swhIdx); hi = max(lastSWLidx, k, swhIdx)
                    if not existsAifobInRange(lo, hi, True):
                        create_ifob(lo, hi, True)
                haveSWH = False; swhCons = True
            # MID-ARM
            p2 = ei
            while p2 < evTotal and events[p2].confirmIdx == k:
                ev = events[p2]
                if ev.kind == 0:
                    haveSWH = True; swhPrice = ev.price; swhIdx = ev.swingIdx
                    pendBullAifob = -1
                    tryBearAOB(prevReg, aobSWLi, ev.swingIdx, ev.price, k)
                    if pendBearAifob == -1:
                        r = tryBearAIFOB(prevReg, haveSWL, aobSWLi, lastSWHidx, ev.swingIdx, k)
                        if r != -1:
                            pendBearAifob = r
                else:
                    haveSWL = True; swlPrice = ev.price; swlIdx = ev.swingIdx
                    pendBearAifob = -1
                    tryBullAOB(prevReg, aobSWHi, ev.swingIdx, ev.price, k)
                    if pendBullAifob == -1:
                        r = tryBullAIFOB(prevReg, haveSWH, aobSWHi, lastSWLidx, ev.swingIdx, k)
                        if r != -1:
                            pendBullAifob = r
                p2 += 1
            # SWL break
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2; msses.append((k, swlIdx, swlPrice, False))
                alive = pendBearAifob != -1 and obs[pendBearAifob].state == 4
                if alive:
                    promote_aifob(pendBearAifob)
                pendBearAifob = -1
                if not alive and lastSWHidx >= 0:
                    lo = min(lastSWHidx, k, swlIdx); hi = max(lastSWHidx, k, swlIdx)
                    if not existsAifobInRange(lo, hi, False):
                        create_ifob(lo, hi, False)
                haveSWL = False; swlCons = True
        else:
            # SWL break
            if haveSWL and L[k] < swlPrice:
                if regime == 0:
                    regime = 2
                elif regime == 1:
                    regime = 2; msses.append((k, swlIdx, swlPrice, False))
                alive = pendBearAifob != -1 and obs[pendBearAifob].state == 4
                if alive:
                    promote_aifob(pendBearAifob)
                pendBearAifob = -1
                if not alive and lastSWHidx >= 0:
                    lo = min(lastSWHidx, k, swlIdx); hi = max(lastSWHidx, k, swlIdx)
                    if not existsAifobInRange(lo, hi, False):
                        create_ifob(lo, hi, False)
                haveSWL = False; swlCons = True
            # MID-ARM
            p3 = ei
            while p3 < evTotal and events[p3].confirmIdx == k:
                ev = events[p3]
                if ev.kind == 0:
                    haveSWH = True; swhPrice = ev.price; swhIdx = ev.swingIdx
                    pendBullAifob = -1
                    tryBearAOB(prevReg, aobSWLi, ev.swingIdx, ev.price, k)
                    if pendBearAifob == -1:
                        r = tryBearAIFOB(prevReg, haveSWL, aobSWLi, lastSWHidx, ev.swingIdx, k)
                        if r != -1:
                            pendBearAifob = r
                else:
                    haveSWL = True; swlPrice = ev.price; swlIdx = ev.swingIdx
                    pendBearAifob = -1
                    tryBullAOB(prevReg, aobSWHi, ev.swingIdx, ev.price, k)
                    if pendBullAifob == -1:
                        r = tryBullAIFOB(prevReg, haveSWH, aobSWHi, lastSWLidx, ev.swingIdx, k)
                        if r != -1:
                            pendBullAifob = r
                p3 += 1
            # SWH break
            if haveSWH and H[k] > swhPrice:
                if regime == 0:
                    regime = 1
                elif regime == 2:
                    regime = 1; msses.append((k, swhIdx, swhPrice, True))
                alive = pendBullAifob != -1 and obs[pendBullAifob].state == 4
                if alive:
                    promote_aifob(pendBullAifob)
                pendBullAifob = -1
                if not alive and lastSWLidx >= 0:
                    lo = min(lastSWLidx, k, swhIdx); hi = max(lastSWLidx, k, swhIdx)
                    if not existsAifobInRange(lo, hi, True):
                        create_ifob(lo, hi, True)
                haveSWH = False; swhCons = True

        # STEP 2: arm swings + eligibility
        while ei < evTotal and events[ei].confirmIdx == k:
            sEv = events[ei]
            if sEv.kind == 0:
                if not swhCons:
                    haveSWH = True; swhPrice = sEv.price; swhIdx = sEv.swingIdx
                lastSWHidx = sEv.swingIdx
                for z in activeObs:
                    o = obs[z]
                    if (o.bullish and o.state in (0, 1, 4) and o.eligibleK == -1
                            and not o.rejected and k > o.triggerK):
                        srcOk = (o.origState not in (1, 4)) or o.zt < sEv.price
                        ep = L[k - 1] if k > 0 else None
                        if (not srcOk) or (ep is not None and ep < o.zb):
                            o.rejected = True; o.eligibleK = -1; o.stopK = -1
                        else:
                            o.eligibleK = k; o.eligibleKind = sEv.kind
                            o.eligibleTime = childEventTime(sEv.kind, k)
            else:
                if not swlCons:
                    haveSWL = True; swlPrice = sEv.price; swlIdx = sEv.swingIdx
                lastSWLidx = sEv.swingIdx
                for z in activeObs:
                    o = obs[z]
                    if ((not o.bullish) and o.state in (0, 1, 4) and o.eligibleK == -1
                            and not o.rejected and k > o.triggerK):
                        srcOk = (o.origState not in (1, 4)) or o.zb > sEv.price
                        ep = H[k - 1] if k > 0 else None
                        if (not srcOk) or (ep is not None and ep > o.zt):
                            o.rejected = True; o.eligibleK = -1; o.stopK = -1
                        else:
                            o.eligibleK = k; o.eligibleKind = sEv.kind
                            o.eligibleTime = childEventTime(sEv.kind, k)
            ei += 1

        # STEP 3: impact + stranding
        for z in list(activeObs):
            o = obs[z]
            if o.state == 3 or o.rejected:
                continue
            zb = o.zb; zt = o.zt; bull = o.bullish
            if o.eligibleK != -1 and k >= o.eligibleK:
                fromT = o.eligibleTime if o.eligibleTime >= 0 else BTms[k]
                touch = childFirstTouch(fromT, k, zb, zt)
                if touch != -1:
                    o.preSpentState = o.state; o.state = 3; o.stopK = k
                    o.impactTime = touch
                    continue
            if o.state in (0, 1, 4) and o.eligibleK != -1:
                isIFOB = o.origState != 1
                for e2 in range(evBeforeSwing, evTotal):
                    st = events[e2]
                    if st.confirmIdx != k:
                        continue
                    stranded = ((bull and st.kind == 1 and st.price > zt) or
                                ((not bull) and st.kind == 0 and st.price < zb))
                    if stranded:
                        o.state = 2
                        break
        prune()

    # ---- trigger exact-minute resolver (weeklyTriggerEventTime) ----
    def trigger_time(o):
        k = o.triggerK
        if k < 0 or k >= n:
            return -1
        if o.origState in (1, 4):
            wanted = (0 if o.bullish else 1) if o.origState == 1 else (1 if o.bullish else 0)
            for ev in events:
                if ev.confirmIdx == k and ev.kind == wanted:
                    return childEventTime(ev.kind, k)
            return -1
        else:
            level = None
            for ev in events:
                relevant = (ev.kind == 0) if o.bullish else (ev.kind == 1)
                if relevant and ev.confirmIdx <= k:
                    level = ev.price
            if level is None:
                return -1
            T = wkT[k]; Hh = wkH[k]; Ll = wkL[k]
            for idx in range(len(T)):
                crossed = (Hh[idx] > level) if o.bullish else (Ll[idx] < level)
                if crossed:
                    return int(T[idx])
            return -1

    return obs, trigger_time


# ================= driver + output =================
_STATE = {0: "IFOB", 1: "AOB", 2: "OOB", 3: "SPENT", 4: "AIFOB"}

_PINE = '''//@version=6
// AUTO-GENERATED by tools/precalc/weekly_ob.py -- do not hand-edit.
// Weekly order blocks, pre-computed from FXCM 1-minute {feed} data, drawn the
// same way as the live indicator: state colour, box from OB candle to its exact
// impact minute (impacted) or extended right (still active); impacted OBs also
// get a vertical impact line at the exact minute.
// Colour = display state (IFOB bull=blue/bear=black, AOB=green, OOB=red, AIFOB=orange).
indicator("Pre-calc Weekly OB", overlay=true, max_boxes_count=500, max_lines_count=500, max_labels_count=500)

InpImpactLines = input.bool(true, "Show impact lines")

// per OB: "candleMs:zb:zt:dispState:bull:impactMs"  (impactMs = -1 if not impacted)
var string WOB = "{wob}"

stateColor(int st, bool bull) =>
    st == 0 ? (bull ? color.blue : color.black) : st == 1 ? color.green : st == 2 ? color.red : st == 4 ? color.orange : color.gray

if barstate.islast and str.length(WOB) > 0
    int rightActive = time + 60 * 7 * 24 * 60 * 60 * 1000  // ~60 weeks to the right
    toks = str.split(WOB, ",")
    for ti = 0 to array.size(toks) - 1
        f = str.split(array.get(toks, ti), ":")
        if array.size(f) == 6
            int ct = int(str.tonumber(array.get(f, 0)))
            float zb = str.tonumber(array.get(f, 1))
            float zt = str.tonumber(array.get(f, 2))
            int ds = int(str.tonumber(array.get(f, 3)))
            bool bull = array.get(f, 4) == "1"
            int it = int(str.tonumber(array.get(f, 5)))
            color c = stateColor(ds, bull)
            int rightT = it >= 0 ? it : rightActive
            box.new(ct, zt, rightT, zb, xloc=xloc.bar_time, border_color=color.new(c,0), border_width=2, bgcolor=na)
            if InpImpactLines and it >= 0
                line.new(it, zb, it, zt, xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,20), width=1)
'''


def _fmt(ms):
    return "-" if ms is None or ms < 0 else pd.Timestamp(ms, unit="ms").strftime("%Y-%m-%d %H:%M")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "EURUSD_m1_BidAndAsk.csv"
    print(f"Reading {path} ...")
    m1 = eng.load_m1(path, feed=FEED, date_format=DATE_FORMAT, tz_shift_hours=TZ_SHIFT_HOURS)
    print(f"Loaded {len(m1):,} one-minute rows ({FEED}). Range {m1.index[0]} -> {m1.index[-1]}")

    O, H, L, C, BTms, highFirst, blocks = eng.resample_weekly(m1, anchor_weekday=WEEK_ANCHOR_WEEKDAY)
    print(f"Built {len(O):,} weekly candles.")

    # to ms, independent of the index's datetime resolution (us/ns)
    wkT = [b.index.to_numpy().astype("datetime64[ms]").astype("int64") for b in blocks]
    wkH = [b["high"].to_numpy() for b in blocks]
    wkL = [b["low"].to_numpy() for b in blocks]
    wkO = [b["open"].to_numpy() for b in blocks]
    wkC = [b["close"].to_numpy() for b in blocks]

    obs, trigger_time = run_weekly_ob(O, H, L, C, BTms, highFirst, wkT, wkH, wkL, wkO, wkC)

    drawn = [o for o in obs if not o.rejected]          # every live/impacted OB
    impacted = [o for o in drawn if o.state == 3 and o.impactTime >= 0]
    print(f"\nTotal OBs: {len(obs)}.  Drawn: {len(drawn)}.  Impacted: {len(impacted)}.\n")

    print("ALL WEEKLY OBs (side | type | trigger | eligibility | impact | zone):")
    for i, o in enumerate(sorted(drawn, key=lambda z: BTms[z.candle]), 1):
        side = "BUY " if o.bullish else "SELL"
        cur = _STATE[o.preSpentState if o.state == 3 else o.state]
        print(f"  #{i:>2} {side} orig={_STATE[o.origState]:<5} now={cur:<5} "
              f"trig {_fmt(trigger_time(o))}  elig {_fmt(o.eligibleTime)}  "
              f"impact {_fmt(o.impactTime)}  [{o.zb:.5f}-{o.zt:.5f}]")

    def disp_state(o):
        return o.preSpentState if o.state == 3 else o.state

    wob = ",".join(
        f"{BTms[o.candle]}:{o.zb:.5f}:{o.zt:.5f}:{disp_state(o)}:{1 if o.bullish else 0}:{o.impactTime}"
        for o in drawn)
    with open("weekly_ob.pine", "w") as f:
        f.write(_PINE.format(feed=FEED, wob=wob))
    print("\nWrote weekly_ob.pine -- paste into a Pine indicator on your EURUSD chart.")


if __name__ == "__main__":
    main()
