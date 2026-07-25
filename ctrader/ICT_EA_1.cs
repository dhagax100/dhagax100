// ICT_EA_1.cs -- cTrader (cAlgo) port of ICT_EA_1.mq5
//
// This is a faithful LOGIC port, not a literal line-for-line translation --
// cAlgo's C# API has no equivalent of MQL5's CopyOpen()/O[]/H[]/L[]/C[]/Time[]
// arrays or CTrade; it uses Bars objects (which, unlike the arrays we used to
// fetch in MQL5, are permanent and only ever grow -- see the note on Refresh()
// below) and ExecuteMarketOrder()/Positions instead. Every rule, threshold,
// and state transition from the .mq5 is preserved exactly; only the platform
// plumbing changed. A couple of calls are flagged with NOTE comments where I
// have moderate-but-not-certain confidence in the exact cAlgo method name/
// signature for your SDK version -- check those first if it doesn't compile.
//
// Architecture (unchanged from the .mq5): three independent instances of the
// same swing/MSS/OB engine (dual-candle swing detection, alternation rule,
// MSS, IFOB/AOB/AIFOB/OOB/SPENT, body-superiority ranking, AOB/AIFOB range
// widening, mirrored stranding direction) -- one on Daily (bias + highest-
// conviction setups), one on H4 (continuation hunting once daily is used up),
// one on H1 (entry timing: MSS/AOB formation, respect-check, execution).

using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class ICT_EA_1 : Robot
    {
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

        [Parameter("Trading window length from each session start (hrs)", DefaultValue = 2, Group = "Session")]
        public int InpSessionWindowHrs { get; set; }

        [Parameter("Daily bars to keep loaded", DefaultValue = 800, Group = "Engine")]
        public int InpDailyBars { get; set; }

        [Parameter("H4 bars to keep loaded", DefaultValue = 2000, Group = "Engine")]
        public int InpH4Bars { get; set; }

        [Parameter("H1 bars to keep loaded", DefaultValue = 4000, Group = "Engine")]
        public int InpH1Bars { get; set; }

        [Parameter("Give up a stalled 1H watch/setup after this many hours", DefaultValue = 120, Group = "Engine")]
        public int InpMaxWaitH1Bars { get; set; }

        // cAlgo has no "magic number" concept -- a position Label is the
        // functional equivalent used to tag and later filter this bot's own
        // positions (ManageBreakeven uses it; the one-trade-at-a-time gate in
        // Advance1H deliberately does NOT filter by it, matching the .mq5's
        // own PositionsTotal() check, which is also unfiltered).
        [Parameter("Position label (magic-number equivalent)", DefaultValue = "ICT_EA_1", Group = "Misc")]
        public string InpLabel { get; set; }

        //================================ ENGINE TYPES ================================
        private struct SwEv
        {
            public int ConfirmIdx;
            public int Kind; // 0 = high, 1 = low
            public int SwingIdx;
            public double Price;
        }

        // state: 0=IFOB, 1=AOB, 2=OOB, 3=SPENT, 4=AIFOB
        private class ObZone
        {
            public int Candle;      // index at creation time (internal engine use only)
            public DateTime T;      // candle time (external/cross-timeframe use)
            public double Zb, Zt;
            public bool Bullish;
            public int TriggerK;
            public int EligibleK;   // -1 = not yet eligible
            public int TouchK;      // -1 = not yet touched; else the candle index of first Impact
            public int State;
            public int OrigState;   // classification for stranding direction (0/4 = IFOB-style, 1 = AOB-style)
        }

        //+------------------------------------------------------------------+
        //| OBEngine -- one instance per timeframe. Refresh() reprocesses the  |
        //| full window from scratch each call (mirrors the indicator's       |
        //| OnCalculate / the .mq5's COBEngine), same proven logic.           |
        //|                                                                    |
        //| Unlike the .mq5's CopyOpen()-based sliding window (which caused a |
        //| genuine crash there -- see the git history), cAlgo's Bars object  |
        //| is permanent: once a bar is loaded at index i, it never moves or  |
        //| gets dropped, and new bars only ever append at the end. That      |
        //| means an OB/event assigned index Q keeps index Q for the entire   |
        //| run, for free -- no fixed-anchor workaround needed here.          |
        //+------------------------------------------------------------------+
        private class OBEngine
        {
            private readonly Bars _bars;

            public readonly List<SwEv> Ev = new List<SwEv>();
            public readonly List<ObZone> Ob = new List<ObZone>();

            public bool HaveSWH; public double SwhPrice; public int SwhIdx;
            public bool HaveSWL; public double SwlPrice; public int SwlIdx;
            public int Regime;        // 0 warmup, 1 up, 2 down
            public int LastSWHidx = -1, LastSWLidx = -1;
            public int PendingBullAifobIdx = -1, PendingBearAifobIdx = -1;

            public int N; // bars processed on the last Refresh()

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

            // rank by body extremity (close), not wick -- zones are drawn/measured open-to-close
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
                int best = PickHighestBullish(lo, hi);
                if (best == -1 || L(best) <= newSwlPrice) return -1; // straddle guard
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 1);
            }

            public int TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice, int k)
            {
                if (prevRegime != 2 || aobSWLidx < 0) return -1;
                int lo = Math.Max(0, Math.Min(aobSWLidx - 1, newSwhIdx));
                int hi = Math.Max(aobSWLidx - 1, newSwhIdx);
                int best = PickLowestBearish(lo, hi);
                if (best == -1 || H(best) >= newSwhPrice) return -1; // straddle guard
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 1);
            }

            public int TryBullishAIFOB(int prevRegime, bool haveSWH_, int swhIdx_, int lastSWLidx_, int newSwlIdx, int k)
            {
                if (prevRegime != 1 || !haveSWH_ || swhIdx_ < 0 || lastSWLidx_ < 0) return -1;
                int lo = Math.Max(0, Math.Min(Math.Min(lastSWLidx_, newSwlIdx), swhIdx_ - 1));
                int hi = Math.Max(Math.Max(lastSWLidx_, newSwlIdx), swhIdx_ - 1);
                int best = PickLowestBearish(lo, hi);
                if (best == -1) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 4);
            }

            public int TryBearishAIFOB(int prevRegime, bool haveSWL_, int swlIdx_, int lastSWHidx_, int newSwhIdx, int k)
            {
                if (prevRegime != 2 || !haveSWL_ || swlIdx_ < 0 || lastSWHidx_ < 0) return -1;
                int lo = Math.Max(0, Math.Min(Math.Min(lastSWHidx_, newSwhIdx), swlIdx_ - 1));
                int hi = Math.Max(Math.Max(lastSWHidx_, newSwhIdx), swlIdx_ - 1);
                int best = PickHighestBullish(lo, hi);
                if (best == -1) return -1;
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 4);
            }

            public bool Refresh()
            {
                N = _bars.Count;
                if (N < 2) return false;

                Ev.Clear();
                Ob.Clear();
                HaveSWH = false; SwhPrice = 0; SwhIdx = 0;
                HaveSWL = false; SwlPrice = 0; SwlIdx = 0;
                Regime = 0; LastSWHidx = -1; LastSWLidx = -1;
                PendingBullAifobIdx = -1; PendingBearAifobIdx = -1;

                //--- swing detection (dual-candle aware, alternation-blocked) ---
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
                // (the .mq5 bubble-sorts Ev by ConfirmIdx here defensively; this loop
                // only ever appends in non-decreasing ConfirmIdx order by construction,
                // so no sort is needed -- kept as a note, not a behavior change.)

                //--- regime / MSS / OB engine ---
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
                                int best = PickLowestBearish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 0);
                            }
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
                                int best = PickHighestBullish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 0);
                            }
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
                                int best = PickHighestBullish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), false, k, 0);
                            }
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
                                int best = PickLowestBearish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 0);
                            }
                            HaveSWH = false; swhConsumed = true;
                        }
                    }

                    //--- STEP2: arm + eligibility ---
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

                    //--- STEP3: lifecycle ---
                    for (int z = 0; z < Ob.Count; z++)
                    {
                        if (Ob[z].State == 3) continue;
                        double zb = Ob[z].Zb, zt = Ob[z].Zt; bool bull = Ob[z].Bullish;
                        bool impacted = false;
                        if (Ob[z].EligibleK != -1 && k >= Ob[z].EligibleK)
                        {
                            if (H(k) >= zb && L(k) <= zt) { Ob[z].State = 3; Ob[z].TouchK = k; impacted = true; }
                        }
                        if (!impacted && (Ob[z].State == 0 || Ob[z].State == 1 || Ob[z].State == 4) && Ob[z].EligibleK != -1)
                        {
                            bool isIFOB = (Ob[z].OrigState != 1);
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

            public int LastClosedIdx() => N - 2; // N-1 is the still-forming bar
        }

        //================================ THE THREE ENGINE INSTANCES ================================
        private OBEngine _daily, _h4, _h1;
        private Bars _dailyBars, _h4Bars, _h1Bars;

        //================================ EA CASCADE STATE ================================
        // bias: 0 none, 1 bullish, 2 bearish -- mirrors _daily.Regime once established
        private int _bias = 0;

        // the daily OB we are currently tracking through touch -> violate/respect -> used-up
        private int _activeDailyIdx = -1;    // index into _daily.Ob
        private bool _activeDailyIsOpp = false; // true if this is an OPPOSING (counter-bias) daily OB
        private int _dailyEvPtr = 0;          // how far into _daily.Ev we've already scanned for the "used-up" swing

        // 4H hunting mode: 0 inactive, 1 buy-only, 2 sell-only, 3 both (ambiguous)
        private int _huntMode = 0;
        private DateTime _huntStartTime; // only 4H OBs formed after this count as fresh hunting POIs

        // which 4H OB (if any) is currently escalated to the 1H entry-watch
        private int _active4hIdx = -1;

        // ambiguity-resolution reference (set when an OPPOSING daily OB gets used up)
        private double _usedUpSwingPrice = 0;
        private bool _usedUpSwingIsHigh = false; // true = watch for price reclaiming ABOVE it (bullish resolution)

        // ---- 1H entry sub-state machine (reusable for daily- or 4h-driven setups) ----
        // 0 idle, 1 watching for the first matching 1H OB, 2 watching for the respect reaction, 3 pending entry
        private int _h1Stage = 0;
        private bool _h1Buy = false;
        private DateTime _h1WatchStart; // only 1H OBs created after this time count
        private int _h1OBIdx = -1;      // index into _h1.Ob once found
        private int _h1ReactionCandle = -1;
        private double _h1SLPrice = 0;  // SL level fixed at the reaction candle, checked while we wait for session window
        private DateTime _h1StageStart; // when we entered the CURRENT stage -- for the stall timeout

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

            // NOTE: VolumeForFixedRisk is cAlgo's standard risk-based sizing helper
            // (riskAmount / stopLossPips, normalized to a tradeable volume) -- the
            // direct equivalent of the .mq5's manual riskMoney/(riskDist/tickSize*
            // tickValue) math. Verify the exact overload against your API version.
            double volume = Symbol.VolumeForFixedRisk(riskMoney, riskPips, RoundingMode.Down);
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;

            // A tight SL relative to normal volatility can blow the risk-based size
            // up far past what the account can actually margin. Cap it to what free
            // margin can actually support instead of sending an order that just gets
            // rejected outright ("not enough money").
            TradeType tt = isBuy ? TradeType.Buy : TradeType.Sell;
            double margin = Symbol.GetEstimatedMargin(tt, volume);
            if (margin > 0)
            {
                double freeMargin = Account.FreeMargin;
                if (margin > freeMargin)
                {
                    double scaled = volume * (freeMargin / margin) * 0.95; // safety buffer
                    scaled = Symbol.NormalizeVolumeInUnits(scaled, RoundingMode.Down);
                    volume = (scaled < Symbol.VolumeInUnitsMin) ? 0 : scaled; // doesn't fit even at minimum -- skip the trade
                }
            }
            return volume;
        }

        //+------------------------------------------------------------------+
        //| Was a given daily OB just touched, and did it respect or violate  |
        //| on that same candle (body close through = violate)?                |
        //+------------------------------------------------------------------+
        private bool DailyRespected(int obIdx, int candleIdx)
        {
            var ob = _daily.Ob[obIdx];
            if (ob.Bullish) return _daily.C(candleIdx) >= ob.Zb; // did NOT close below the demand zone
            return _daily.C(candleIdx) <= ob.Zt; // did NOT close above the supply zone
        }

        //+------------------------------------------------------------------+
        //| Start the 1H entry-watch for a setup spawned by a daily or 4H OB. |
        //+------------------------------------------------------------------+
        private void StartWatching1H(bool buyDirection, DateTime fromTime)
        {
            _h1Stage = 1;
            _h1Buy = buyDirection;
            _h1WatchStart = fromTime;
            _h1OBIdx = -1;
            _h1ReactionCandle = -1;
            _h1StageStart = Server.Time;
        }

        //+------------------------------------------------------------------+
        //| Advance the 1H sub-state machine one step (call after each H1     |
        //| bar close). Places the entry order itself when respect confirms   |
        //| and the next hour's bar has opened.                                |
        //+------------------------------------------------------------------+
        private void Advance1H()
        {
            if (_h1Stage == 0) return;

            // Stall guard: none of the three sub-stages has a bound on how long they
            // may wait (stage 1 for a matching 1H structure, stage 2 for the wick
            // reaction, stage 3 for a session window to open). Left unbounded, a
            // direction that simply doesn't produce the next piece of structure for
            // a long stretch would occupy _h1Stage forever and block
            // UpdateHuntLevel()'s "one setup at a time" gate from ever starting a
            // fresh, more current setup. Give up and free the slot after
            // InpMaxWaitH1Bars hours with no resolution.
            if ((Server.Time - _h1StageStart).TotalHours >= InpMaxWaitH1Bars)
            {
                Print($"[1H] {Server.Time:u} stalled in stage {_h1Stage} for >{InpMaxWaitH1Bars} hours -- giving up this watch");
                _h1Stage = 0;
                return;
            }

            if (_h1Stage == 1)
            {
                int found = -1; DateTime foundTime = DateTime.MinValue;
                for (int z = 0; z < _h1.Ob.Count; z++)
                {
                    var ob = _h1.Ob[z];
                    if (ob.Bullish != _h1Buy) continue;
                    if (ob.T <= _h1WatchStart) continue;
                    if (found == -1 || ob.T < foundTime) { found = z; foundTime = ob.T; }
                }
                if (found != -1)
                {
                    _h1OBIdx = found; _h1Stage = 2; _h1StageStart = Server.Time;
                    Print($"[1H] found matching {(_h1Buy ? "bullish" : "bearish")} H1 OB #{found} (formed {foundTime:u}) -- watching for reaction");
                }
                return;
            }

            if (_h1Stage == 2)
            {
                int lc = _h1.LastClosedIdx();
                if (lc < 0) return;
                if (_h1.Ob[_h1OBIdx].State == 2)
                {
                    Print($"[1H] {_h1.T(lc):u} watched OB #{_h1OBIdx} stranded before reacting -- resume watching");
                    _h1Stage = 1; _h1OBIdx = -1; _h1StageStart = Server.Time; return; // stranded before reacting
                }
                double zb = _h1.Ob[_h1OBIdx].Zb, zt = _h1.Ob[_h1OBIdx].Zt;
                bool wicked = (_h1.H(lc) >= zb && _h1.L(lc) <= zt);
                if (!wicked) return;

                bool respected = _h1Buy ? (_h1.C(lc) >= zt) : (_h1.C(lc) <= zb);
                if (respected)
                {
                    _h1ReactionCandle = lc;
                    _h1SLPrice = _h1Buy ? _h1.L(lc) : _h1.H(lc);
                    _h1Stage = 3;
                    _h1StageStart = Server.Time;
                    Print($"[1H] {_h1.T(lc):u} reaction RESPECTED on OB #{_h1OBIdx} -- pending entry (SL={_h1SLPrice})");
                }
                else
                {
                    Print($"[1H] {_h1.T(lc):u} reaction VIOLATED on OB #{_h1OBIdx} -- resume watching");
                    _h1Stage = 1; _h1OBIdx = -1; _h1StageStart = Server.Time; // violated -- keep watching for the next 1H setup
                }
                return;
            }

            if (_h1Stage == 3)
            {
                // The session-time rule is a TIMING gate on when to fire the entry,
                // not a filter on which setups are eligible. A confirmed reaction
                // that happens to land outside the window must WAIT for the next
                // in-window hour, not be thrown away.
                int cur = _h1.N - 1; // the bar that just opened this tick (still forming)
                if (cur <= _h1ReactionCandle) return; // the bar right after the reaction hasn't opened yet

                // While we wait, make sure price hasn't already breached the reaction
                // candle's SL level -- entering late on a setup that already failed
                // would put the stop on the wrong side of price.
                for (int x = _h1ReactionCandle + 1; x <= cur; x++)
                {
                    bool breached = _h1Buy ? (_h1.L(x) <= _h1SLPrice) : (_h1.H(x) >= _h1SLPrice);
                    if (breached)
                    {
                        Print($"[1H] {_h1.T(x):u} SL level breached while waiting for session window -- resume watching");
                        _h1Stage = 1; _h1OBIdx = -1; _h1StageStart = Server.Time; return;
                    }
                }

                DateTime entryTime = _h1.T(cur);
                if (!InSessionWindow(entryTime)) return; // keep waiting for the next in-window hour

                // NOTE: unfiltered, matching the .mq5's PositionsTotal() check --
                // this counts ALL open positions on the account, not just this bot's.
                if (Positions.Count > 0)
                {
                    Print($"[1H] {entryTime:u} setup ready but a position is already open -- setup skipped");
                    _h1Stage = 0; return; // one trade at a time
                }

                double entryPrice = _h1.O(cur);
                double slPrice = _h1SLPrice;
                double riskDist = _h1Buy ? (entryPrice - slPrice) : (slPrice - entryPrice);
                if (riskDist <= 0) { _h1Stage = 1; _h1OBIdx = -1; _h1StageStart = Server.Time; return; }

                double tpPrice = _h1Buy ? entryPrice + riskDist * InpRR_Target : entryPrice - riskDist * InpRR_Target;
                double volume = CalcLotSize(riskDist, _h1Buy, entryPrice);
                Print($"[1H] {entryTime:u} ENTRY {(_h1Buy ? "BUY" : "SELL")} @ {entryPrice} SL={slPrice} TP={tpPrice} volume={volume}");
                if (volume > 0)
                {
                    double slPips = Math.Abs(entryPrice - slPrice) / Symbol.PipSize;
                    double tpPips = Math.Abs(tpPrice - entryPrice) / Symbol.PipSize;
                    ExecuteMarketOrder(_h1Buy ? TradeType.Buy : TradeType.Sell, SymbolName, volume, InpLabel, slPips, tpPips, InpLabel);
                }
                _h1Stage = 0;
            }
        }

        //+------------------------------------------------------------------+
        //| Move SL to breakeven once a position reaches InpRR_BE reward:risk. |
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
        //| Daily-level cascade: find/track the active daily OB through       |
        //| touch -> violate (done) / respect -> used-up (advance hunt mode). |
        //+------------------------------------------------------------------+
        private void UpdateDailyLevel()
        {
            int prevBias = _bias;
            _bias = (_daily.Regime == 1 || _daily.Regime == 2) ? _daily.Regime : _bias;
            if (_bias != prevBias)
                Print($"[DAILY] {_daily.T(_daily.LastClosedIdx()):u} bias -> {(_bias == 1 ? "BULLISH" : "BEARISH")}");

            // Always check for a fresh touch on the last closed candle, even while
            // another OB is still being tracked -- a "used up" confirmation can take
            // a long time (or never come) in a quiet market, and a new touch is
            // objectively more current. Without this, one early OB that never
            // resolves would permanently block all future daily engagement.
            int lc = _daily.LastClosedIdx();
            for (int z = 0; z < _daily.Ob.Count; z++)
            {
                if (_daily.Ob[z].TouchK != lc) continue; // only react to a touch that JUST happened
                if (z == _activeDailyIdx) break;         // this IS the one we're already tracking
                bool isOpposing = (_bias != 0) && (_daily.Ob[z].Bullish == (_bias == 2));
                if (DailyRespected(z, lc))
                {
                    _activeDailyIdx = z;
                    _activeDailyIsOpp = isOpposing;
                    _dailyEvPtr = _daily.Ev.Count; // only swings AFTER this count matter for "used up"
                    StartWatching1H(_daily.Ob[z].Bullish, _daily.T(lc));
                    Print($"[DAILY] {_daily.T(lc):u} touch RESPECTED on {(_daily.Ob[z].Bullish ? "bullish" : "bearish")} OB #{z} (opposing={isOpposing}) -- now tracking for used-up");
                }
                else
                {
                    Print($"[DAILY] {_daily.T(lc):u} touch VIOLATED on {(_daily.Ob[z].Bullish ? "bullish" : "bearish")} OB #{z} -- done, no action");
                }
                break;
            }
            if (_activeDailyIdx == -1) return;

            // we ARE tracking one -- watch for the confirming swing that makes it "used up"
            bool wantHighConfirm = !_daily.Ob[_activeDailyIdx].Bullish; // bearish OB -> wait for a SWH
            for (int e = _dailyEvPtr; e < _daily.Ev.Count; e++)
            {
                int kind = _daily.Ev[e].Kind;
                if ((wantHighConfirm && kind == 0) || (!wantHighConfirm && kind == 1))
                {
                    // USED UP
                    if (!_activeDailyIsOpp)
                    {
                        _huntMode = _daily.Ob[_activeDailyIdx].Bullish ? 1 : 2; // resume/continue single-direction hunt
                    }
                    else
                    {
                        _huntMode = 3; // ambiguous -- opposing OB proved itself, watch both ways
                        _usedUpSwingPrice = _daily.Ev[e].Price;
                        _usedUpSwingIsHigh = (kind == 0);
                    }
                    _huntStartTime = _daily.T(_daily.LastClosedIdx());
                    Print($"[DAILY] {_daily.T(_daily.LastClosedIdx()):u} USED UP OB #{_activeDailyIdx} -- huntMode={_huntMode}, huntStartTime={_huntStartTime:u}");
                    _activeDailyIdx = -1;
                    break;
                }
            }
        }

        //+------------------------------------------------------------------+
        //| 4H hunting: mark fresh 4H OBs matching the allowed direction(s)   |
        //| and escalate the first one to the 1H entry-watch.                 |
        //+------------------------------------------------------------------+
        private void UpdateHuntLevel()
        {
            if (_huntMode == 0) return;

            // Whenever the daily regime flips to a direction huntMode doesn't
            // already reflect -- a genuine new daily MSS -- redirect hunting to
            // follow it immediately, in EVERY huntMode (not just the ambiguous
            // one, 3). A clean single-direction hunt (1 or 2) set up once must not
            // keep hunting that same stale direction forever after the trend
            // reverses. Any stale 1H watch for the old direction is abandoned too.
            if (_daily.Regime != 0 && _daily.Regime != _huntMode)
            {
                Print($"[HUNT] {_daily.T(_daily.LastClosedIdx()):u} daily regime flip -- huntMode {_huntMode} -> {_daily.Regime}, abandoning any stale watch");
                _huntMode = _daily.Regime; // 1=up/buy, 2=down/sell -- same encoding as regime
                _bias = _daily.Regime;
                _huntStartTime = _daily.T(_daily.LastClosedIdx());
                _h1Stage = 0;
            }

            if (_h1Stage != 0) return; // already busy watching/entering one setup at a time

            int lc = _h4.LastClosedIdx();
            if (lc < 0) return;

            bool allowBuy = (_huntMode == 1 || _huntMode == 3);
            bool allowSell = (_huntMode == 2 || _huntMode == 3);

            for (int z = _h4.Ob.Count - 1; z >= 0; z--)
            {
                var ob = _h4.Ob[z];
                // any state (including OOB) is eligible, matching the daily-level rule --
                // what matters is whether price just touched it, not its current state.
                if (ob.T < _huntStartTime) continue; // only OBs formed since hunting began
                if (ob.Bullish && !allowBuy) continue;
                if (!ob.Bullish && !allowSell) continue;
                if (ob.TouchK == lc) // price just reached this 4H OB
                {
                    StartWatching1H(ob.Bullish, _h4.T(lc));
                    _active4hIdx = z;
                    Print($"[HUNT] {_h4.T(lc):u} escalating {(ob.Bullish ? "bullish" : "bearish")} H4 OB #{z} to 1H watch (huntMode={_huntMode})");
                    break;
                }
            }

            // ambiguity resolution (b), reaching a fresh in-trend daily IFOB/AIFOB, is
            // handled by UpdateDailyLevel()'s own touch/respect/used-up tracking; case
            // (b), a genuine regime flip, is handled generically above for every
            // huntMode. Only (c) -- price reclaiming past the opposing-OB reaction's
            // swing without waiting for a full new daily cycle -- needs handling here.
            if (_huntMode == 3)
            {
                double last = _daily.C(_daily.LastClosedIdx());
                if (_usedUpSwingIsHigh && last > _usedUpSwingPrice)
                {
                    // (c) price reclaimed back above the opposing-OB reaction's swing high
                    _huntMode = 1;
                    _huntStartTime = _h4.T(lc);
                    Print($"[HUNT] ambiguity resolved (c) reclaimed above {_usedUpSwingPrice} -> huntMode=1");
                }
                else if (!_usedUpSwingIsHigh && last < _usedUpSwingPrice)
                {
                    _huntMode = 2;
                    _huntStartTime = _h4.T(lc);
                    Print($"[HUNT] ambiguity resolved (c) reclaimed below {_usedUpSwingPrice} -> huntMode=2");
                }
            }
        }

        //+------------------------------------------------------------------+
        //| Make sure at least minBars are loaded before the engine starts --  |
        //| cAlgo lazy-loads history, unlike MQL5 where CopyOpen() would just  |
        //| return what it could. Bars loaded this way are permanent: index 0  |
        //| never moves and nothing ever drops off (see the note on Refresh()  |
        //| above), so this only needs to run once, at start.                  |
        //+------------------------------------------------------------------+
        private Bars EnsureBars(TimeFrame tf, int minBars)
        {
            var bars = MarketData.GetBars(tf, SymbolName);
            while (bars.Count < minBars)
            {
                int before = bars.Count;
                bars.LoadMoreHistory();
                if (bars.Count == before) break; // no more history available from the broker
            }
            return bars;
        }

        protected override void OnStart()
        {
            _dailyBars = EnsureBars(TimeFrame.Daily, InpDailyBars);
            _h4Bars = EnsureBars(TimeFrame.Hour4, InpH4Bars);
            _h1Bars = EnsureBars(TimeFrame.Hour, InpH1Bars);

            _daily = new OBEngine(_dailyBars);
            _h4 = new OBEngine(_h4Bars);
            _h1 = new OBEngine(_h1Bars);

            _dailyBars.BarOpened += OnDailyBarOpened;
            _h4Bars.BarOpened += OnH4BarOpened;
            _h1Bars.BarOpened += OnH1BarOpened;

            // establish a baseline state immediately, same as the .mq5's first tick
            // (which always refreshes all three engines unconditionally)
            _daily.Refresh(); UpdateDailyLevel();
            _h4.Refresh();
            _h1.Refresh(); UpdateHuntLevel(); Advance1H();
        }

        private void OnDailyBarOpened(BarOpenedEventArgs args)
        {
            _daily.Refresh();
            UpdateDailyLevel();
        }

        private void OnH4BarOpened(BarOpenedEventArgs args)
        {
            _h4.Refresh();
        }

        private void OnH1BarOpened(BarOpenedEventArgs args)
        {
            _h1.Refresh();
            UpdateHuntLevel();
            Advance1H();
        }

        protected override void OnTick()
        {
            ManageBreakeven();
        }
    }
}
