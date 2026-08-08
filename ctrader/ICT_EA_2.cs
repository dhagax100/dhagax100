// ICT_EA_2.cs -- cTrader (cAlgo) Weekly/Daily bias -> 4H confirm -> 5M entry cascade.
//
// Reuses the same swing/MSS engine as ICT_EA_1.cs, extended with a THIRD POI
// type: RB (Rejection Block), ported from pine/ICT_RB_Diagnostic.pine (spec
// confirmed there already). So this hunts OB, FVG, and RB zones, all in one
// unified list, all sharing the same eligibility/impact/stranding lifecycle.
//
// TIER 1 (bias, Weekly or Daily -- InpBiasTF): a POI goes live the instant
// price wicks into it and stays live -- rolling forward across period closes
// -- until EITHER a candle BODY closes inside its range, OR the matching-
// direction swing confirms after entry (swing high kills a bearish POI,
// swing low kills a bullish one). Wick-only touches never kill it.
//
// TIER 2 (confirm, fixed 4H): once the bias POI is live, hunt 4H POIs
// (aggressive = counter-trend, or in-favor = with-trend) matching the bias
// direction, formed since bias entry. Same two kill conditions apply here
// too. A newly-touched 4H zone that overlaps the one already being watched
// is merged into it rather than restarting the watch.
//
// TIER 3 (entry, fixed 5M): once price wicks into the live 4H zone, trail a
// stop order to the latest matching-direction 5M swing (sell-stop at swing
// lows for a bearish cascade, buy-stop at swing highs for a bullish one)
// until it fills, the 4H/bias POI invalidates, or the session window closes
// for the day. SL sits just behind the swing candle's own wick (+1 pip for
// spread); TP is a fixed reward:risk multiple of that.
//
// After a fill: the cascade does NOT reset. It keeps hunting the SAME 4H
// zone for another 5M entry as long as that zone (and the bias POI it came
// from) is still live and we're inside a trading session window. Only when
// the 4H zone or the bias POI itself dies do we go back up a tier to look
// for a fresh one.
//
// Trading hours (confirmed, same as ICT_EA_1): London 08:00-12:00 and New
// York 13:00-17:00, broker/server time -- both adjustable below.
//
// One trade at a time: any open position blocks new entries (checked
// unfiltered, same convention as ICT_EA_1).
//
// First complete build of this cascade -- expect a test-and-refine cycle,
// same as every other EA in this repo. A couple of cAlgo calls are flagged
// NOTE where the exact overload should be checked against your SDK version.

using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class ICT_EA_2 : Robot
    {
        [Parameter("Bias timeframe (Weekly or Daily)", DefaultValue = "Weekly", Group = "Cascade")]
        public TimeFrame InpBiasTF { get; set; }

        [Parameter("Risk % of equity per trade", DefaultValue = 1.0, Group = "Risk")]
        public double InpRiskPercent { get; set; }

        [Parameter("Reward:risk target (TP)", DefaultValue = 3.0, Group = "Risk")]
        public double InpRR_Target { get; set; }

        [Parameter("Move SL to breakeven at this RR", DefaultValue = 2.0, Group = "Risk")]
        public double InpRR_BE { get; set; }

        [Parameter("London session start hour (broker/server time)", DefaultValue = 8, Group = "Session")]
        public int InpLondonStartHour { get; set; }

        [Parameter("New York session start hour (broker/server time)", DefaultValue = 13, Group = "Session")]
        public int InpNewYorkStartHour { get; set; }

        [Parameter("Trading window length from each session start (hrs)", DefaultValue = 4, Group = "Session")]
        public int InpSessionWindowHrs { get; set; }

        [Parameter("Position label", DefaultValue = "ICT_EA_2", Group = "Misc")]
        public string InpLabel { get; set; }

        [Parameter("Show bias-tier structure on chart", DefaultValue = true, Group = "Visuals")]
        public bool InpShowBias { get; set; }

        [Parameter("Show 4H confirm structure on chart", DefaultValue = true, Group = "Visuals")]
        public bool InpShowConfirm { get; set; }

        [Parameter("Show 5M entry structure on chart", DefaultValue = false, Group = "Visuals")]
        public bool InpShowEntry { get; set; }

        //================================ ENGINE TYPES ================================
        private struct SwEv
        {
            public int ConfirmIdx;
            public int Kind; // 0 = high, 1 = low
            public int SwingIdx;
            public double Price;
        }

        private enum PoiKind { OB, FVG, RB }

        // state: 0=IFOB/IRB, 1=AOB/ARB, 2=OOB/ORB, 3=SPENT, 4=AIFOB (OB only, RB has no AIFOB-equivalent)
        private class ObZone
        {
            public int Candle;
            public DateTime T;
            public double Zb, Zt;
            public bool Bullish;
            public int TriggerK;
            public int EligibleK;
            public int TouchK;
            public int State;
            public int OrigState;
            public PoiKind Kind = PoiKind.OB;
        }

        private struct MssEvent { public int K; public bool Bullish; }

        //+------------------------------------------------------------------+
        //| OBEngine -- one instance per timeframe. Refresh() reprocesses the  |
        //| full window from scratch each call. cAlgo's Bars object is        |
        //| permanent (only ever grows), so an OB/event assigned index Q      |
        //| keeps index Q for the entire run.                                  |
        //+------------------------------------------------------------------+
        private class OBEngine
        {
            private readonly Bars _bars;

            public readonly List<SwEv> Ev = new List<SwEv>();
            public readonly List<ObZone> Ob = new List<ObZone>();
            public readonly List<MssEvent> Mss = new List<MssEvent>();

            public bool HaveSWH; public double SwhPrice; public int SwhIdx;
            public bool HaveSWL; public double SwlPrice; public int SwlIdx;
            public int Regime;
            public int LastSWHidx = -1, LastSWLidx = -1;
            public int PendingBullAifobIdx = -1, PendingBearAifobIdx = -1;

            public int N;

            public OBEngine(Bars bars) { _bars = bars; }

            public double O(int i) => _bars.OpenPrices[i];
            public double H(int i) => _bars.HighPrices[i];
            public double L(int i) => _bars.LowPrices[i];
            public double C(int i) => _bars.ClosePrices[i];
            public DateTime T(int i) => _bars.OpenTimes[i];

            public void AddEv(int confirmIdx, int kind, int swingIdx, double price)
            {
                Ev.Add(new SwEv { ConfirmIdx = confirmIdx, Kind = kind, SwingIdx = swingIdx, Price = price });
            }

            public int AddOB(int candle, double zb, double zt, bool bull, int triggerK, int state)
            {
                Ob.Add(new ObZone
                {
                    Candle = candle,
                    T = T(candle),
                    Zb = zb,
                    Zt = zt,
                    Bullish = bull,
                    TriggerK = triggerK,
                    EligibleK = (state == 1 || state == 4) ? triggerK : -1,
                    TouchK = -1,
                    State = state,
                    OrigState = state
                });
                return Ob.Count - 1;
            }

            public int AddFvg(int candle, double zb, double zt, bool bull, int triggerK, int state)
            {
                int idx = AddOB(candle, zb, zt, bull, triggerK, state);
                Ob[idx].Kind = PoiKind.FVG;
                return idx;
            }

            // RB zone: the WICK of a single swing-pivot candle, not a scanned pick.
            // Swing high: top=the high, bottom=closer of open/close. Mirrored for a
            // swing low. isHigh=true -> bearish RB; isHigh=false -> bullish RB
            // (label is by raw wick type, regardless of which hunt created it).
            public int AddRbFromSwing(int idx, bool isHigh, int triggerK, int state)
            {
                int newIdx = isHigh
                    ? AddOB(idx, Math.Max(O(idx), C(idx)), H(idx), false, triggerK, state)
                    : AddOB(idx, L(idx), Math.Min(O(idx), C(idx)), true, triggerK, state);
                Ob[newIdx].Kind = PoiKind.RB;
                return newIdx;
            }

            public void ScanFvgs(int lo, int hi, bool bullish, int triggerK, int state, double? straddlePrice = null)
            {
                lo = Math.Max(lo, 0);
                int limit = Math.Min(hi, N - 3);
                for (int i = lo; i <= limit; i++)
                {
                    if (bullish)
                    {
                        if (L(i + 2) > H(i))
                        {
                            if (straddlePrice.HasValue && H(i) <= straddlePrice.Value) continue;
                            AddFvg(i, H(i), L(i + 2), true, triggerK, state);
                        }
                    }
                    else
                    {
                        if (H(i + 2) < L(i))
                        {
                            if (straddlePrice.HasValue && L(i) >= straddlePrice.Value) continue;
                            AddFvg(i, H(i + 2), L(i), false, triggerK, state);
                        }
                    }
                }
            }

            public int PickLowestBearish(int lo, int hi)
            {
                int best = -1;
                for (int x = lo; x <= hi; x++)
                    if (C(x) < O(x) && (best == -1 || C(x) < C(best))) best = x;
                return best;
            }

            public int PickHighestBullish(int lo, int hi)
            {
                int best = -1;
                for (int x = lo; x <= hi; x++)
                    if (C(x) > O(x) && (best == -1 || C(x) > C(best))) best = x;
                return best;
            }

            public int TryBullishAOB(int prevRegime, int aobSWHidx, int newSwlIdx, double newSwlPrice, int k)
            {
                if (prevRegime != 1 || aobSWHidx < 0) return -1;
                int lo = Math.Max(0, Math.Min(aobSWHidx - 1, newSwlIdx));
                int hi = Math.Max(aobSWHidx - 1, newSwlIdx);
                ScanFvgs(lo, hi, true, k, 1, newSwlPrice);
                int best = PickHighestBullish(lo, hi);
                if (best == -1 || L(best) <= newSwlPrice) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 1);
            }

            public int TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice, int k)
            {
                if (prevRegime != 2 || aobSWLidx < 0) return -1;
                int lo = Math.Max(0, Math.Min(aobSWLidx - 1, newSwhIdx));
                int hi = Math.Max(aobSWLidx - 1, newSwhIdx);
                ScanFvgs(lo, hi, false, k, 1, newSwhPrice);
                int best = PickLowestBearish(lo, hi);
                if (best == -1 || H(best) >= newSwhPrice) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 1);
            }

            public int TryBullishAIFOB(int prevRegime, bool haveSWH_, int swhIdx_, int lastSWLidx_, int newSwlIdx, int k)
            {
                if (prevRegime != 1 || !haveSWH_ || swhIdx_ < 0 || lastSWLidx_ < 0) return -1;
                int lo = Math.Max(0, Math.Min(Math.Min(lastSWLidx_, newSwlIdx), swhIdx_ - 1));
                int hi = Math.Max(Math.Max(lastSWLidx_, newSwlIdx), swhIdx_ - 1);
                ScanFvgs(lo, hi, true, k, 4);
                int best = PickLowestBearish(lo, hi);
                if (best == -1) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 4);
            }

            public int TryBearishAIFOB(int prevRegime, bool haveSWL_, int swlIdx_, int lastSWHidx_, int newSwhIdx, int k)
            {
                if (prevRegime != 2 || !haveSWL_ || swlIdx_ < 0 || lastSWHidx_ < 0) return -1;
                int lo = Math.Max(0, Math.Min(Math.Min(lastSWHidx_, newSwhIdx), swlIdx_ - 1));
                int hi = Math.Max(Math.Max(lastSWHidx_, newSwhIdx), swlIdx_ - 1);
                ScanFvgs(lo, hi, false, k, 4);
                int best = PickHighestBullish(lo, hi);
                if (best == -1) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 4);
            }

            // ARB: same trigger moment + reference-validity gate as the matching AOB
            // (armed swing must not have been exceeded since), but instead of
            // scanning/picking a candle, the zone is just the armed swing's own
            // wick. Anchor = the FAR (armed) swing, immediate eligibility.
            public void TryBullArb(int prevRegime, int aobSWHidx, int newSwlIdx, int k)
            {
                if (prevRegime != 1 || aobSWHidx < 0) return;
                double armedSwhPrice = H(aobSWHidx);
                for (int v = aobSWHidx + 1; v <= newSwlIdx; v++)
                    if (H(v) >= armedSwhPrice) return; // reference violated -- no ARB
                AddRbFromSwing(aobSWHidx, true, k, 1);
            }

            public void TryBearArb(int prevRegime, int aobSWLidx, int newSwhIdx, int k)
            {
                if (prevRegime != 2 || aobSWLidx < 0) return;
                double armedSwlPrice = L(aobSWLidx);
                for (int v = aobSWLidx + 1; v <= newSwhIdx; v++)
                    if (L(v) <= armedSwlPrice) return;
                AddRbFromSwing(aobSWLidx, false, k, 1);
            }

            public bool Refresh()
            {
                N = _bars.Count;
                if (N < 2) return false;

                Ev.Clear();
                Ob.Clear();
                Mss.Clear();
                HaveSWH = false; SwhPrice = 0; SwhIdx = 0;
                HaveSWL = false; SwlPrice = 0; SwlIdx = 0;
                Regime = 0; LastSWHidx = -1; LastSWLidx = -1;
                PendingBullAifobIdx = -1; PendingBearAifobIdx = -1;

                int peakIdx = 0, troughIdx = 0;
                for (int i = 1; i < N; i++)
                {
                    bool bullish = (C(i) >= O(i));
                    bool breaksPrevHigh = (H(i) > H(i - 1));
                    bool breaksPrevLow = (L(i) < L(i - 1));
                    bool dualAction = (breaksPrevHigh && breaksPrevLow);

                    bool prevDual = false;
                    if (Ev.Count >= 2)
                    {
                        bool diffKinds = (Ev[Ev.Count - 1].Kind != Ev[Ev.Count - 2].Kind);
                        bool sameConfirm = (Ev[Ev.Count - 1].ConfirmIdx == Ev[Ev.Count - 2].ConfirmIdx);
                        bool wasLastCandle = (Ev[Ev.Count - 1].ConfirmIdx == i - 1);
                        prevDual = diffKinds && sameConfirm && wasLastCandle;
                    }
                    bool blockPostDual = (prevDual && !dualAction);

                    if (!bullish)
                    {
                        if (H(i) > H(peakIdx)) peakIdx = i;
                        if (breaksPrevHigh)
                        {
                            bool lastWasLow = (Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 1);
                            if (!lastWasLow && !blockPostDual)
                            { AddEv(i, 1, troughIdx, L(troughIdx)); peakIdx = i; }
                        }
                        if (L(i) < L(troughIdx)) troughIdx = i;
                        if (breaksPrevLow)
                        {
                            bool lastWasHigh = (Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 0);
                            if (!lastWasHigh && !blockPostDual)
                            { AddEv(i, 0, peakIdx, H(peakIdx)); troughIdx = i; }
                        }
                    }
                    else
                    {
                        if (L(i) < L(troughIdx)) troughIdx = i;
                        if (breaksPrevLow)
                        {
                            bool lastWasHigh = (Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 0);
                            if (!lastWasHigh && !blockPostDual)
                            { AddEv(i, 0, peakIdx, H(peakIdx)); troughIdx = i; }
                        }
                        if (H(i) > H(peakIdx)) peakIdx = i;
                        if (breaksPrevHigh)
                        {
                            bool lastWasLow = (Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 1);
                            if (!lastWasLow && !blockPostDual)
                            { AddEv(i, 1, troughIdx, L(troughIdx)); peakIdx = i; }
                        }
                    }
                }

                int ei = 0;
                for (int k = 0; k < N; k++)
                {
                    {
                        int peek = ei;
                        while (peek < Ev.Count && Ev[peek].ConfirmIdx == k)
                        {
                            if (Ev[peek].Kind == 0) LastSWHidx = Ev[peek].SwingIdx;
                            else LastSWLidx = Ev[peek].SwingIdx;
                            peek++;
                        }
                    }
                    int prevRegime = Regime;
                    bool swhConsumed = false, swlConsumed = false;
                    int aobSWHidx = SwhIdx, aobSWLidx = SwlIdx;

                    bool kBullish = (C(k) >= O(k));
                    if (!kBullish)
                    {
                        if (HaveSWH && H(k) > SwhPrice)
                        {
                            if (Regime == 0) Regime = 1; else if (Regime == 2) Regime = 1;
                            if (PendingBullAifobIdx != -1)
                            { Ob[PendingBullAifobIdx].State = 0; Ob[PendingBullAifobIdx].OrigState = 0; PendingBullAifobIdx = -1; }
                            else if (LastSWLidx >= 0)
                            {
                                int lo = Math.Min(Math.Min(LastSWLidx, k), SwhIdx);
                                int hi = Math.Max(Math.Max(LastSWLidx, k), SwhIdx);
                                ScanFvgs(lo, hi, true, k, 0);
                                int best = PickLowestBearish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 0);
                            }
                            // IRB fires here too, independent of the IFOB/AIFOB branch above.
                            if (LastSWLidx >= 0) AddRbFromSwing(LastSWLidx, false, k, 0);
                            HaveSWH = false; swhConsumed = true;
                        }
                        {
                            int peek2 = ei;
                            while (peek2 < Ev.Count && Ev[peek2].ConfirmIdx == k)
                            {
                                if (Ev[peek2].Kind == 0)
                                {
                                    HaveSWH = true; SwhPrice = Ev[peek2].Price; SwhIdx = Ev[peek2].SwingIdx;
                                    PendingBullAifobIdx = -1;
                                    TryBearishAOB(prevRegime, aobSWLidx, Ev[peek2].SwingIdx, Ev[peek2].Price, k);
                                    TryBearArb(prevRegime, aobSWLidx, Ev[peek2].SwingIdx, k);
                                    if (PendingBearAifobIdx == -1)
                                    {
                                        int idx2 = TryBearishAIFOB(prevRegime, HaveSWL, aobSWLidx, LastSWHidx, Ev[peek2].SwingIdx, k);
                                        if (idx2 != -1) PendingBearAifobIdx = idx2;
                                    }
                                }
                                else
                                {
                                    HaveSWL = true; SwlPrice = Ev[peek2].Price; SwlIdx = Ev[peek2].SwingIdx;
                                    PendingBearAifobIdx = -1;
                                    TryBullishAOB(prevRegime, aobSWHidx, Ev[peek2].SwingIdx, Ev[peek2].Price, k);
                                    TryBullArb(prevRegime, aobSWHidx, Ev[peek2].SwingIdx, k);
                                    if (PendingBullAifobIdx == -1)
                                    {
                                        int idx2 = TryBullishAIFOB(prevRegime, HaveSWH, aobSWHidx, LastSWLidx, Ev[peek2].SwingIdx, k);
                                        if (idx2 != -1) PendingBullAifobIdx = idx2;
                                    }
                                }
                                peek2++;
                            }
                        }
                        if (HaveSWL && L(k) < SwlPrice)
                        {
                            if (Regime == 0) Regime = 2; else if (Regime == 1) Regime = 2;
                            if (PendingBearAifobIdx != -1)
                            { Ob[PendingBearAifobIdx].State = 0; Ob[PendingBearAifobIdx].OrigState = 0; PendingBearAifobIdx = -1; }
                            else if (LastSWHidx >= 0)
                            {
                                int lo = Math.Min(Math.Min(LastSWHidx, k), SwlIdx);
                                int hi = Math.Max(Math.Max(LastSWHidx, k), SwlIdx);
                                ScanFvgs(lo, hi, false, k, 0);
                                int best = PickHighestBullish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 0);
                            }
                            if (LastSWHidx >= 0) AddRbFromSwing(LastSWHidx, true, k, 0);
                            HaveSWL = false; swlConsumed = true;
                        }
                    }
                    else
                    {
                        if (HaveSWL && L(k) < SwlPrice)
                        {
                            if (Regime == 0) Regime = 2; else if (Regime == 1) Regime = 2;
                            if (PendingBearAifobIdx != -1)
                            { Ob[PendingBearAifobIdx].State = 0; Ob[PendingBearAifobIdx].OrigState = 0; PendingBearAifobIdx = -1; }
                            else if (LastSWHidx >= 0)
                            {
                                int lo = Math.Min(Math.Min(LastSWHidx, k), SwlIdx);
                                int hi = Math.Max(Math.Max(LastSWHidx, k), SwlIdx);
                                ScanFvgs(lo, hi, false, k, 0);
                                int best = PickHighestBullish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 0);
                            }
                            if (LastSWHidx >= 0) AddRbFromSwing(LastSWHidx, true, k, 0);
                            HaveSWL = false; swlConsumed = true;
                        }
                        {
                            int peek2 = ei;
                            while (peek2 < Ev.Count && Ev[peek2].ConfirmIdx == k)
                            {
                                if (Ev[peek2].Kind == 0)
                                {
                                    HaveSWH = true; SwhPrice = Ev[peek2].Price; SwhIdx = Ev[peek2].SwingIdx;
                                    PendingBullAifobIdx = -1;
                                    TryBearishAOB(prevRegime, aobSWLidx, Ev[peek2].SwingIdx, Ev[peek2].Price, k);
                                    TryBearArb(prevRegime, aobSWLidx, Ev[peek2].SwingIdx, k);
                                    if (PendingBearAifobIdx == -1)
                                    {
                                        int idx2 = TryBearishAIFOB(prevRegime, HaveSWL, aobSWLidx, LastSWHidx, Ev[peek2].SwingIdx, k);
                                        if (idx2 != -1) PendingBearAifobIdx = idx2;
                                    }
                                }
                                else
                                {
                                    HaveSWL = true; SwlPrice = Ev[peek2].Price; SwlIdx = Ev[peek2].SwingIdx;
                                    PendingBearAifobIdx = -1;
                                    TryBullishAOB(prevRegime, aobSWHidx, Ev[peek2].SwingIdx, Ev[peek2].Price, k);
                                    TryBullArb(prevRegime, aobSWHidx, Ev[peek2].SwingIdx, k);
                                    if (PendingBullAifobIdx == -1)
                                    {
                                        int idx2 = TryBullishAIFOB(prevRegime, HaveSWH, aobSWHidx, LastSWLidx, Ev[peek2].SwingIdx, k);
                                        if (idx2 != -1) PendingBullAifobIdx = idx2;
                                    }
                                }
                                peek2++;
                            }
                        }
                        if (HaveSWH && H(k) > SwhPrice)
                        {
                            if (Regime == 0) Regime = 1; else if (Regime == 2) Regime = 1;
                            if (PendingBullAifobIdx != -1)
                            { Ob[PendingBullAifobIdx].State = 0; Ob[PendingBullAifobIdx].OrigState = 0; PendingBullAifobIdx = -1; }
                            else if (LastSWLidx >= 0)
                            {
                                int lo = Math.Min(Math.Min(LastSWLidx, k), SwhIdx);
                                int hi = Math.Max(Math.Max(LastSWLidx, k), SwhIdx);
                                ScanFvgs(lo, hi, true, k, 0);
                                int best = PickLowestBearish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 0);
                            }
                            if (LastSWLidx >= 0) AddRbFromSwing(LastSWLidx, false, k, 0);
                            HaveSWH = false; swhConsumed = true;
                        }
                    }

                    if (Regime != prevRegime)
                        Mss.Add(new MssEvent { K = k, Bullish = Regime == 1 });

                    while (ei < Ev.Count && Ev[ei].ConfirmIdx == k)
                    {
                        if (Ev[ei].Kind == 0)
                        {
                            if (!swhConsumed) { HaveSWH = true; SwhPrice = Ev[ei].Price; SwhIdx = Ev[ei].SwingIdx; }
                            LastSWHidx = Ev[ei].SwingIdx;
                            for (int z = 0; z < Ob.Count; z++)
                                if (Ob[z].Bullish && Ob[z].State == 0 && Ob[z].EligibleK == -1 && k > Ob[z].TriggerK)
                                    Ob[z].EligibleK = k;
                        }
                        else
                        {
                            if (!swlConsumed) { HaveSWL = true; SwlPrice = Ev[ei].Price; SwlIdx = Ev[ei].SwingIdx; }
                            LastSWLidx = Ev[ei].SwingIdx;
                            for (int z = 0; z < Ob.Count; z++)
                                if (!Ob[z].Bullish && Ob[z].State == 0 && Ob[z].EligibleK == -1 && k > Ob[z].TriggerK)
                                    Ob[z].EligibleK = k;
                        }
                        ei++;
                    }

                    for (int z = 0; z < Ob.Count; z++)
                    {
                        if (Ob[z].State == 3) continue;
                        double zb = Ob[z].Zb, zt = Ob[z].Zt; bool bull = Ob[z].Bullish;
                        bool impacted = false;
                        if (Ob[z].EligibleK != -1 && k >= Ob[z].EligibleK)
                        {
                            if (H(k) >= zb && L(k) <= zt)
                            {
                                Ob[z].State = 3; Ob[z].TouchK = k; impacted = true;
                            }
                        }
                        if (!impacted && (Ob[z].State == 0 || Ob[z].State == 1 || Ob[z].State == 4) && Ob[z].EligibleK != -1)
                        {
                            bool isIFOB = (Ob[z].OrigState != 1); // 0/4 = far-side stranding (IFOB/IRB-style); 1 = near-side (AOB/ARB-style)
                            for (int e2 = 0; e2 < Ev.Count; e2++)
                            {
                                if (Ev[e2].ConfirmIdx != k) continue;
                                if (isIFOB)
                                {
                                    if (bull && Ev[e2].Kind == 1 && Ev[e2].Price > zt) Ob[z].State = 2;
                                    if (!bull && Ev[e2].Kind == 0 && Ev[e2].Price < zb) Ob[z].State = 2;
                                }
                                else
                                {
                                    if (bull && Ev[e2].Kind == 0 && Ev[e2].Price < zb) Ob[z].State = 2;
                                    if (!bull && Ev[e2].Kind == 1 && Ev[e2].Price > zt) Ob[z].State = 2;
                                }
                            }
                        }
                    }
                }
                return true;
            }

            public int LastClosedIdx() => N - 2;
        }

        //================================ THE THREE ENGINE INSTANCES ================================
        private OBEngine _bias, _confirm, _entry;
        private Bars _biasBars, _confirmBars, _entryBars;

        //================================ CHART DRAWING ================================
        private class DrawCache
        {
            public List<int> ObState = new List<int>();
            public int EvDrawn = 0;
            public int MssDrawn = 0;
        }
        private readonly DrawCache _biasDraw = new DrawCache();
        private readonly DrawCache _confirmDraw = new DrawCache();
        private readonly DrawCache _entryDraw = new DrawCache();

        //================================ TIER TRACKING ================================
        // Generic "is this POI still halal" tracker, shared by the bias and confirm
        // tiers -- the two kill conditions scale to every tier.
        private class PoiTrack
        {
            public int Idx = -1;
            public int EntryK = -1;
            public int SwingPtr = 0;
        }

        private readonly PoiTrack _biasTr = new PoiTrack();
        private readonly PoiTrack _confirmTr = new PoiTrack();

        private DateTime _huntStartTime;
        private bool _confirmBull;
        private double _confirmZb, _confirmZt;

        private int _entryStage = 0;          // 0 idle, 1 active (watching/trailing on M5)
        private DateTime _entryWatchStart;    // H4 touch time -- M5 structure must be fresh from here
        private int _entryEnteredIdx = -1;    // M5 candle idx when price first got inside the confirm zone
        private double _entrySwingPrice;
        private PendingOrder _pendingOrder;

        //+------------------------------------------------------------------+
        //| Session filter: only enter in the first InpSessionWindowHrs of   |
        //| the London or New York session (broker/server time).             |
        //+------------------------------------------------------------------+
        private bool InSessionWindow(DateTime t)
        {
            int h = t.Hour;
            bool inLondon = (h >= InpLondonStartHour && h < InpLondonStartHour + InpSessionWindowHrs);
            bool inNY = (h >= InpNewYorkStartHour && h < InpNewYorkStartHour + InpSessionWindowHrs);
            return inLondon || inNY;
        }

        //+------------------------------------------------------------------+
        //| Risk-based position sizing from SL distance (in price).           |
        //+------------------------------------------------------------------+
        private double CalcLotSize(double riskDistPrice, bool isBuy, double entryPrice)
        {
            double riskMoney = Account.Equity * (InpRiskPercent / 100.0);
            if (riskDistPrice <= 0) return 0;
            double riskPips = riskDistPrice / Symbol.PipSize;

            // NOTE: VolumeForFixedRisk is cAlgo's standard risk-based sizing helper --
            // verify the exact overload against your API version.
            double volume = Symbol.VolumeForFixedRisk(riskMoney, riskPips, RoundingMode.Down);
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;

            TradeType tt = isBuy ? TradeType.Buy : TradeType.Sell;
            double margin = Symbol.GetEstimatedMargin(tt, volume);
            if (margin > 0)
            {
                double freeMargin = Account.FreeMargin;
                if (margin > freeMargin)
                {
                    double scaled = volume * (freeMargin / margin) * 0.95;
                    scaled = Symbol.NormalizeVolumeInUnits(scaled, RoundingMode.Down);
                    volume = (scaled < Symbol.VolumeInUnitsMin) ? 0 : scaled;
                }
            }
            return volume;
        }

        //+------------------------------------------------------------------+
        //| Is the tracked POI (bias or confirm tier -- same rule, either      |
        //| engine) still halal on the tier's own just-closed candle lc?      |
        //| Kills on: (1) a candle BODY closing inside the zone, or (2) the   |
        //| matching-direction swing confirming any time after entry.         |
        //+------------------------------------------------------------------+
        private bool PoiStillHalal(OBEngine eng, PoiTrack tr, int lc)
        {
            if (tr.Idx == -1) return false;
            var z = eng.Ob[tr.Idx];

            double bodyLo = Math.Min(eng.O(lc), eng.C(lc));
            double bodyHi = Math.Max(eng.O(lc), eng.C(lc));
            if (bodyHi >= z.Zb && bodyLo <= z.Zt) return false; // kill condition 1

            bool wantHigh = !z.Bullish; // bearish POI dies on a swing HIGH, bullish on a swing LOW
            for (int e = tr.SwingPtr; e < eng.Ev.Count; e++)
            {
                if (eng.Ev[e].ConfirmIdx <= tr.EntryK) continue;
                if ((wantHigh && eng.Ev[e].Kind == 0) || (!wantHigh && eng.Ev[e].Kind == 1))
                    return false; // kill condition 2
            }
            tr.SwingPtr = eng.Ev.Count;
            return true;
        }

        //+------------------------------------------------------------------+
        //| First eligible wick-touch on the tier's just-closed candle lc,    |
        //| among POIs formed at/after notBefore and (if requireDirection)    |
        //| matching wantBull. -1 if none.                                    |
        //+------------------------------------------------------------------+
        private int FindFreshTouch(OBEngine eng, int lc, DateTime notBefore, bool wantBull, bool requireDirection)
        {
            for (int z = eng.Ob.Count - 1; z >= 0; z--)
            {
                var ob = eng.Ob[z];
                if (requireDirection && ob.Bullish != wantBull) continue;
                if (ob.T < notBefore) continue;
                if (ob.EligibleK == -1 || lc < ob.EligibleK) continue;
                bool wick = (eng.H(lc) >= ob.Zb && eng.L(lc) <= ob.Zt);
                if (wick) return z;
            }
            return -1;
        }

        //+------------------------------------------------------------------+
        private void CancelPendingOrderIfAny()
        {
            // NOTE: CancelPendingOrder(PendingOrder) is the expected cAlgo Robot method --
            // verify against your API version.
            if (_pendingOrder != null)
            {
                CancelPendingOrder(_pendingOrder);
                _pendingOrder = null;
            }
        }

        private void RetireConfirm()
        {
            _confirmTr.Idx = -1;
            _entryStage = 0;
            _entryEnteredIdx = -1;
            CancelPendingOrderIfAny();
        }

        private void RetireBias()
        {
            _biasTr.Idx = -1;
            RetireConfirm();
        }

        private void StartEntryWatch(DateTime fromTime)
        {
            _entryStage = 1;
            _entryWatchStart = fromTime;
            _entryEnteredIdx = -1;
            CancelPendingOrderIfAny();
        }

        //+------------------------------------------------------------------+
        //| TIER 1: bias POI (Weekly or Daily) lifecycle.                     |
        //+------------------------------------------------------------------+
        private void UpdateBiasLevel()
        {
            int lc = _bias.LastClosedIdx();
            if (lc < 0) return;

            if (_biasTr.Idx != -1 && !PoiStillHalal(_bias, _biasTr, lc))
            {
                Print($"[BIAS] {_bias.T(lc):u} POI #{_biasTr.Idx} KILLED");
                RetireBias();
            }

            if (_biasTr.Idx == -1)
            {
                int z = FindFreshTouch(_bias, lc, DateTime.MinValue, false, false);
                if (z != -1)
                {
                    _biasTr.Idx = z; _biasTr.EntryK = lc; _biasTr.SwingPtr = _bias.Ev.Count;
                    _huntStartTime = _bias.T(lc);
                    RetireConfirm(); // fresh bias entry -- drop any stale confirm/entry watch
                    var ob = _bias.Ob[z];
                    Print($"[BIAS] {_bias.T(lc):u} entered {(ob.Bullish ? "bullish" : "bearish")} POI #{z} [{ob.Zb:F5}-{ob.Zt:F5}]");
                }
            }
        }

        //+------------------------------------------------------------------+
        //| TIER 2: 4H confirm zone (aggressive or in-favor), same lifecycle. |
        //+------------------------------------------------------------------+
        private void UpdateConfirmLevel()
        {
            if (_biasTr.Idx == -1) { if (_confirmTr.Idx != -1) RetireConfirm(); return; }

            int lc = _confirm.LastClosedIdx();
            if (lc < 0) return;

            if (_confirmTr.Idx != -1 && !PoiStillHalal(_confirm, _confirmTr, lc))
            {
                Print($"[CONFIRM] {_confirm.T(lc):u} 4H POI #{_confirmTr.Idx} KILLED");
                RetireConfirm();
            }

            bool wantBull = _bias.Ob[_biasTr.Idx].Bullish;

            if (_confirmTr.Idx == -1)
            {
                int z = FindFreshTouch(_confirm, lc, _huntStartTime, wantBull, true);
                if (z == -1) return;

                var ob = _confirm.Ob[z];
                bool overlapsLive = (_entryStage == 1 && ob.Zb <= _confirmZt && ob.Zt >= _confirmZb);

                _confirmTr.Idx = z; _confirmTr.EntryK = lc; _confirmTr.SwingPtr = _confirm.Ev.Count;
                _confirmBull = wantBull;

                if (overlapsLive)
                {
                    // overlaps the zone we were already trailing on -- merge bounds only,
                    // keep the existing M5 watch/pending order progress intact.
                    _confirmZb = Math.Min(_confirmZb, ob.Zb);
                    _confirmZt = Math.Max(_confirmZt, ob.Zt);
                    Print($"[CONFIRM] {_confirm.T(lc):u} merged overlapping {(wantBull ? "bullish" : "bearish")} 4H POI #{z} into live watch [{_confirmZb:F5}-{_confirmZt:F5}]");
                }
                else
                {
                    _confirmZb = ob.Zb; _confirmZt = ob.Zt;
                    StartEntryWatch(_confirm.T(lc));
                    string flavor = ob.OrigState == 1 ? "aggressive" : "in-favor";
                    string kind = ob.Kind == PoiKind.OB ? "OB" : ob.Kind == PoiKind.FVG ? "FVG" : "RB";
                    Print($"[CONFIRM] {_confirm.T(lc):u} escalating {(wantBull ? "bullish" : "bearish")} 4H {flavor} {kind} POI #{z} [{ob.Zb:F5}-{ob.Zt:F5}] to 5m watch");
                }
            }
        }

        //+------------------------------------------------------------------+
        //| TIER 3: 5M trailing stop-entry inside the live confirm zone.      |
        //| SL sits just behind the entry swing candle's own wick (+1 pip     |
        //| for spread); TP is InpRR_Target x that risk.                      |
        //+------------------------------------------------------------------+
        private void UpdateEntryLevel()
        {
            if (_entryStage == 0) return;
            if (Positions.Count > 0) return; // one trade at a time (unfiltered, matches ICT_EA_1)

            int lc = _entry.LastClosedIdx();
            if (lc < 0) return;

            DateTime now = _entry.T(lc);
            if (!InSessionWindow(now))
            {
                if (_pendingOrder != null)
                {
                    CancelPendingOrderIfAny();
                    _entryEnteredIdx = -1;
                    Print($"[ENTRY] {now:u} outside session window -- pending order cancelled for today");
                }
                return;
            }

            if (_entryEnteredIdx == -1)
            {
                if (_entry.T(lc) < _entryWatchStart) return;
                bool inside = (_entry.H(lc) >= _confirmZb && _entry.L(lc) <= _confirmZt);
                if (!inside) return;
                _entryEnteredIdx = lc;
                Print($"[ENTRY] {now:u} 5m entered the confirm zone -- trailing {(_confirmBull ? "buy stop at swing highs" : "sell stop at swing lows")}");
            }

            int wantKind = _confirmBull ? 0 : 1; // buy zone -> swing high anchors the stop; sell zone -> swing low
            int bestE = -1;
            for (int e = 0; e < _entry.Ev.Count; e++)
            {
                if (_entry.Ev[e].ConfirmIdx < _entryEnteredIdx) continue;
                if (_entry.Ev[e].Kind != wantKind) continue;
                if (bestE == -1 || _entry.Ev[e].ConfirmIdx > _entry.Ev[bestE].ConfirmIdx) bestE = e;
            }
            if (bestE == -1) return; // no matching swing yet to anchor the stop on

            double price = _entry.Ev[bestE].Price;
            if (_pendingOrder != null && Math.Abs(price - _entrySwingPrice) < Symbol.TickSize) return; // unchanged

            double onePip = Symbol.PipSize;
            int swingCandleIdx = _entry.Ev[bestE].SwingIdx;
            double sl = _confirmBull ? _entry.L(swingCandleIdx) - onePip : _entry.H(swingCandleIdx) + onePip;
            double riskDist = _confirmBull ? (price - sl) : (sl - price);
            if (riskDist <= 0) return; // degenerate geometry -- skip until it resolves
            double tp = _confirmBull ? price + riskDist * InpRR_Target : price - riskDist * InpRR_Target;
            double volume = CalcLotSize(riskDist, _confirmBull, price);
            if (volume <= 0) return;

            CancelPendingOrderIfAny();
            double slPips = Math.Abs(price - sl) / Symbol.PipSize;
            double tpPips = Math.Abs(tp - price) / Symbol.PipSize;
            // NOTE: PlaceStopOrder's exact overload/argument order -- verify against your API version.
            var result = PlaceStopOrder(_confirmBull ? TradeType.Buy : TradeType.Sell, SymbolName, volume, price,
                InpLabel, slPips, tpPips, null, InpLabel);
            if (result.IsSuccessful)
            {
                _pendingOrder = result.PendingOrder;
                _entrySwingPrice = price;
                Print($"[ENTRY] {now:u} placed {(_confirmBull ? "BUY" : "SELL")} stop @ {price} SL={sl} TP={tp} volume={volume}");
            }
            else
            {
                Print($"[ENTRY] {now:u} order placement FAILED: {result.Error}");
            }
        }

        //+------------------------------------------------------------------+
        //| A fill does NOT reset the cascade -- keep hunting the same 4H     |
        //| zone for another 5M entry as long as it (and the bias POI) is     |
        //| still live. Only PoiStillHalal killing the confirm/bias tier      |
        //| ever fully retires the hunt.                                      |
        //+------------------------------------------------------------------+
        private void OnPositionOpenedHandler(PositionOpenedEventArgs args)
        {
            if (args.Position.Label != InpLabel) return;
            Print($"[ENTRY] {Server.Time:u} position opened -- watching for the next setup while the zone stays live");
            _pendingOrder = null; // it just became this position -- nothing left to cancel
            _entryEnteredIdx = -1;
            _entryStage = (_confirmTr.Idx != -1) ? 1 : 0;
        }

        //+------------------------------------------------------------------+
        //| Move SL to breakeven once a position reaches InpRR_BE reward:risk.|
        //+------------------------------------------------------------------+
        private void ManageBreakeven()
        {
            foreach (var position in Positions.FindAll(InpLabel, SymbolName))
            {
                double openPrice = position.EntryPrice;
                double sl = position.StopLoss ?? 0;
                bool isBuy = position.TradeType == TradeType.Buy;
                double curPrice = isBuy ? Symbol.Bid : Symbol.Ask;
                double riskDist = isBuy ? (openPrice - sl) : (sl - openPrice);
                if (riskDist <= 0) continue;
                double rr = isBuy ? (curPrice - openPrice) / riskDist : (openPrice - curPrice) / riskDist;
                if (rr >= InpRR_BE)
                {
                    bool alreadyBE = isBuy ? (sl >= openPrice) : (sl <= openPrice);
                    if (!alreadyBE)
                        position.ModifyStopLossPrice(openPrice);
                }
            }
        }

        //+------------------------------------------------------------------+
        //| Chart drawing.                                                     |
        //+------------------------------------------------------------------+
        private Color ObColor(int state, int origState, PoiKind kind)
        {
            if (kind == PoiKind.OB)
            {
                if (state == 2) return Color.Gray;
                if (state == 3) return origState == 1 ? Color.RoyalBlue : origState == 4 ? Color.Teal : Color.SeaGreen;
                if (origState == 1) return Color.DeepSkyBlue;
                if (origState == 4) return Color.Turquoise;
                return Color.LimeGreen;
            }
            if (kind == PoiKind.FVG)
            {
                if (state == 2) return Color.DimGray;
                if (state == 3) return origState == 1 ? Color.MediumPurple : origState == 4 ? Color.Indigo : Color.Purple;
                if (origState == 1) return Color.Orange;
                if (origState == 4) return Color.DarkOrange;
                return Color.Gold;
            }
            // RB
            if (state == 2) return Color.Red;
            if (state == 3) return origState == 1 ? Color.DarkGreen : Color.SaddleBrown;
            if (origState == 1) return Color.MediumSeaGreen; // ARB, live
            return Color.SteelBlue;                          // IRB, live
        }

        private string ObLabel(int state, int origState, PoiKind kind)
        {
            string baseLabel = kind == PoiKind.OB
                ? (origState == 1 ? "AOB" : origState == 4 ? "AIFOB" : "IFOB")
                : kind == PoiKind.FVG
                    ? (origState == 1 ? "AFVG" : origState == 4 ? "AIFVG" : "IFVG")
                    : (origState == 1 ? "ARB" : "IRB");
            if (state == 2) return kind == PoiKind.OB ? "OOB" : kind == PoiKind.FVG ? "OFVG" : "ORB";
            if (state == 3) return baseLabel + " (spent)";
            return baseLabel;
        }

        private void DrawEngine(OBEngine eng, DrawCache cache, string prefix)
        {
            for (int i = cache.EvDrawn; i < eng.Ev.Count; i++)
            {
                var e = eng.Ev[i];
                DateTime t = eng.T(e.SwingIdx);
                bool isHigh = e.Kind == 0;
                Chart.DrawIcon($"{prefix}_sw_{i}", ChartIconType.Circle, t, e.Price, isHigh ? Color.OrangeRed : Color.DodgerBlue);
            }
            cache.EvDrawn = eng.Ev.Count;

            for (int i = cache.MssDrawn; i < eng.Mss.Count; i++)
            {
                var m = eng.Mss[i];
                DateTime t = eng.T(m.K);
                double y = m.Bullish ? eng.L(m.K) : eng.H(m.K);
                Chart.DrawText($"{prefix}_mss_{i}", "MSS", t, y, m.Bullish ? Color.LimeGreen : Color.OrangeRed);
            }
            cache.MssDrawn = eng.Mss.Count;

            for (int i = 0; i < eng.Ob.Count; i++)
            {
                var ob = eng.Ob[i];
                bool stillLive = (ob.State == 0 || ob.State == 1 || ob.State == 4);
                int lastState = i < cache.ObState.Count ? cache.ObState[i] : -1;
                if (!stillLive && lastState == ob.State) continue;

                Color c = ObColor(ob.State, ob.OrigState, ob.Kind);
                string label = ObLabel(ob.State, ob.OrigState, ob.Kind);
                DateTime t1 = eng.T(ob.Candle);
                DateTime t2 = stillLive ? eng.T(eng.N - 1) : (ob.TouchK != -1 ? eng.T(ob.TouchK) : t1);

                var rect = Chart.DrawRectangle($"{prefix}_ob_{i}", t1, ob.Zt, t2, ob.Zb, c, 1);
                rect.IsFilled = false;
                // NOTE: verify this property name (LineStyle vs Style) against your cAlgo API version.
                rect.LineStyle = ob.Kind == PoiKind.OB ? LineStyle.Solid : ob.Kind == PoiKind.FVG ? LineStyle.Dots : LineStyle.Lines;
                Chart.DrawText($"{prefix}_obtxt_{i}", $"{prefix} {label}", t1, ob.Bullish ? ob.Zb : ob.Zt, c);

                while (cache.ObState.Count <= i) cache.ObState.Add(-1);
                cache.ObState[i] = ob.State;
            }
        }

        //+------------------------------------------------------------------+
        //| Live status readout, corner-anchored.                             |
        //+------------------------------------------------------------------+
        private void UpdateStatusText()
        {
            string biasTxt = _biasTr.Idx == -1
                ? "waiting for a fresh bias touch"
                : $"live POI #{_biasTr.Idx} ({(_bias.Ob[_biasTr.Idx].Bullish ? "bullish" : "bearish")})";
            string confirmTxt = _confirmTr.Idx == -1
                ? "none"
                : $"live 4H POI #{_confirmTr.Idx} [{_confirmZb:F5}-{_confirmZt:F5}]";
            string entryTxt = _entryStage == 0 ? "idle" : (_entryEnteredIdx == -1 ? "waiting for 5m to enter zone" : "trailing stop");

            string text = $"Bias: {biasTxt}\nConfirm: {confirmTxt}\nEntry: {entryTxt}";
            Chart.DrawStaticText("ict2_status", text, VerticalAlignment.Top, HorizontalAlignment.Left, Color.White);
        }

        //+------------------------------------------------------------------+
        //| Request extra history without blocking (fire-and-forget --        |
        //| see ICT_EA_1.cs for why a synchronous wait-loop deadlocks).       |
        //+------------------------------------------------------------------+
        private Bars GetEngineBars(TimeFrame tf)
        {
            var bars = MarketData.GetBars(tf, SymbolName);
            bars.LoadMoreHistory();
            return bars;
        }

        protected override void OnStart()
        {
            _biasBars = GetEngineBars(InpBiasTF);
            _confirmBars = GetEngineBars(TimeFrame.Hour4);
            _entryBars = GetEngineBars(TimeFrame.Minute5);

            _bias = new OBEngine(_biasBars);
            _confirm = new OBEngine(_confirmBars);
            _entry = new OBEngine(_entryBars);

            _biasBars.BarOpened += OnBiasBarOpened;
            _confirmBars.BarOpened += OnConfirmBarOpened;
            _entryBars.BarOpened += OnEntryBarOpened;
            Positions.Opened += OnPositionOpenedHandler;

            _bias.Refresh(); UpdateBiasLevel();
            _confirm.Refresh(); UpdateConfirmLevel();
            _entry.Refresh(); UpdateEntryLevel();

            if (InpShowBias) DrawEngine(_bias, _biasDraw, "BIAS");
            if (InpShowConfirm) DrawEngine(_confirm, _confirmDraw, "H4");
            if (InpShowEntry) DrawEngine(_entry, _entryDraw, "M5");
            UpdateStatusText();
        }

        private void OnBiasBarOpened(BarOpenedEventArgs args)
        {
            _bias.Refresh();
            UpdateBiasLevel();
            if (InpShowBias) DrawEngine(_bias, _biasDraw, "BIAS");
            UpdateStatusText();
        }

        private void OnConfirmBarOpened(BarOpenedEventArgs args)
        {
            _confirm.Refresh();
            UpdateConfirmLevel();
            if (InpShowConfirm) DrawEngine(_confirm, _confirmDraw, "H4");
            UpdateStatusText();
        }

        private void OnEntryBarOpened(BarOpenedEventArgs args)
        {
            _entry.Refresh();
            UpdateEntryLevel();
            if (InpShowEntry) DrawEngine(_entry, _entryDraw, "M5");
            UpdateStatusText();
        }

        protected override void OnTick()
        {
            ManageBreakeven();
        }
    }
}
