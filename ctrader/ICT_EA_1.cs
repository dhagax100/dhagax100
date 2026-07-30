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
// Structure engine (unchanged from the .mq5, plus FVG added as a second POI
// flavor in the same unified list): three independent instances of the same
// swing/MSS/OB+FVG engine (dual-candle swing detection, alternation rule,
// MSS, IFOB/AOB/AIFOB/OOB/SPENT -- and the FVG equivalents IFVG/AFVG/AIFVG/
// OFVG/spent, all sharing the identical lifecycle since a POI is a POI
// regardless of whether it came from a single-candle body pick (OB) or a
// 3-candle gap (FVG, and unlike OB, EVERY qualifying gap in a leg is marked,
// not just the best one), body-superiority ranking, AOB/AFVG range widening
// and straddle guard, mirrored stranding direction) -- one on Daily, one on
// H4, one on H1. All three are drawn; 4H is visualization only now.
//
// Trading logic (this is a from-scratch entry design, not the old
// daily-bias/4H-hunt/1H-escalation cascade): triggered purely by a live daily
// IFOB getting wicked (no daily respect-check anymore -- the raw touch is
// the whole signal). From there the cascade watches the 1H chart only, for
// two mutually exclusive ways price can flip direction to match the daily
// IFOB's own bias -- see AdvanceCascade()'s stage-2 comments for the exact
// scenario A (genuine 1H MSS, trades the fresh continuation IFOB it creates)
// vs scenario B (a same-direction retracement swing confirms without
// exceeding the armed swing first, trades an ad-hoc "reversal AOB" candle)
// distinction -- then waits for a wick+close-respect reaction on whichever
// zone won, and fires at the next hour's open if within the session window.

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

        [Parameter("New York session end hour (broker/server time) -- a cascade never survives past this on the day its daily IFOB was touched", DefaultValue = 22, Group = "Session")]
        public int InpNewYorkSessionEndHour { get; set; }

        // cAlgo has no "magic number" concept -- a position Label is the
        // functional equivalent used to tag and later filter this bot's own
        // positions (ManageBreakeven uses it; the one-trade-at-a-time gate in
        // AdvanceCascade deliberately does NOT filter by it, matching the .mq5's
        // own PositionsTotal() check, which is also unfiltered).
        [Parameter("Position label (magic-number equivalent)", DefaultValue = "ICT_EA_1", Group = "Misc")]
        public string InpLabel { get; set; }

        [Parameter("Show Daily structure on chart", DefaultValue = true, Group = "Visuals")]
        public bool InpShowDaily { get; set; }

        [Parameter("Show H4 structure on chart", DefaultValue = true, Group = "Visuals")]
        public bool InpShowH4 { get; set; }

        [Parameter("Show H1 structure on chart", DefaultValue = true, Group = "Visuals")]
        public bool InpShowH1 { get; set; }

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
            public int PreSpentState = -1; // state right before transitioning to SPENT(3) -- lets callers
                                            // tell a genuine live touch (was 0/1/4) apart from a touch that
                                            // only happened AFTER the zone was already stranded (was 2/OOB)
            public bool IsFvg = false;      // display-only: OB (single-candle body pick) vs FVG (3-candle
                                            // gap). Every lifecycle rule (eligibility, touch, stranding,
                                            // used-up, hunting, entry) is identical either way -- OB and
                                            // FVG are just two flavors of the same POI in one unified list.
        }

        // one entry per genuine regime flip (MSS), for chart marking
        private struct MssEvent { public int K; public bool Bullish; }

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
            public readonly List<MssEvent> Mss = new List<MssEvent>();

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

            public int AddFvg(int candle, double zb, double zt, bool bull, int triggerK, int state)
            {
                int idx = AddOB(candle, zb, zt, bull, triggerK, state);
                Ob[idx].IsFvg = true;
                return idx;
            }

            // Scans (lo..hi) for every qualifying 3-candle gap in the given direction and
            // creates one FVG zone per gap found -- "mark all of them", unlike OB's
            // single-best-candle pick. straddlePrice mirrors the OB straddle guard (only
            // applied where the corresponding OB call applies it: AOB, not IFOB/AIFOB).
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
                            if (straddlePrice.HasValue && H(i) <= straddlePrice.Value) continue; // straddle guard
                            AddFvg(i, H(i), L(i + 2), true, triggerK, state);
                        }
                    }
                    else
                    {
                        if (H(i + 2) < L(i))
                        {
                            if (straddlePrice.HasValue && L(i) >= straddlePrice.Value) continue; // straddle guard
                            AddFvg(i, H(i + 2), L(i), false, triggerK, state);
                        }
                    }
                }
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
                ScanFvgs(lo, hi, true, k, 1, newSwlPrice);
                int best = PickHighestBullish(lo, hi);
                if (best == -1 || L(best) <= newSwlPrice) return -1; // straddle guard
                return AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 1);
            }

            public int TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice, int k)
            {
                if (prevRegime != 2 || aobSWLidx < 0) return -1;
                int lo = Math.Max(0, Math.Min(aobSWLidx - 1, newSwhIdx));
                int hi = Math.Max(aobSWLidx - 1, newSwhIdx);
                ScanFvgs(lo, hi, false, k, 1, newSwhPrice);
                int best = PickLowestBearish(lo, hi);
                if (best == -1 || H(best) >= newSwhPrice) return -1; // straddle guard
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
                                ScanFvgs(lo, hi, true, k, 0);
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
                                ScanFvgs(lo, hi, false, k, 0);
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
                                ScanFvgs(lo, hi, false, k, 0);
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
                                ScanFvgs(lo, hi, true, k, 0);
                                int best = PickLowestBearish(lo, hi);
                                if (best != -1) AddOB(best, Math.Min(O(best), C(best)), Math.Max(O(best), C(best)), true, k, 0);
                            }
                            HaveSWH = false; swhConsumed = true;
                        }
                    }

                    // MSS = the swing break that actually flips or establishes the regime.
                    if (Regime != prevRegime)
                        Mss.Add(new MssEvent { K = k, Bullish = Regime == 1 });

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
                            if (H(k) >= zb && L(k) <= zt)
                            {
                                Ob[z].PreSpentState = Ob[z].State; // remember what it was JUST before impact
                                Ob[z].State = 3; Ob[z].TouchK = k; impacted = true;
                            }
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

        //================================ CHART DRAWING ================================
        // Tracks what's already been drawn for one engine so Refresh() -> Draw() doesn't
        // redraw the whole history every bar: swings and MSS marks are append-only (drawn
        // once, never change); OB zones keep redrawing (extending their right edge to "now")
        // only while still live (IFOB/AOB/AIFOB) -- once a zone resolves (OOB or SPENT) it's
        // drawn once more at its final color/edge and then left alone.
        private class DrawCache
        {
            public List<int> ObState = new List<int>(); // last-drawn state per OB index, -1 = not drawn yet
            public int EvDrawn = 0;
            public int MssDrawn = 0;
        }
        private readonly DrawCache _dailyDraw = new DrawCache();
        private readonly DrawCache _h4Draw = new DrawCache();
        private readonly DrawCache _h1Draw = new DrawCache();

        //================================ EA CASCADE STATE ================================
        // Daily-IFOB-triggered cascade, entirely driven by Daily -> 1H (4H is drawn only,
        // no longer part of the trading logic). Stages:
        //   0 idle              -- waiting for a fresh daily IFOB touch
        //   1 waiting for pivot -- waiting for the first opposite-direction 1H swing after touch
        //   2 waiting for flip  -- waiting for either a genuine 1H MSS (scenario A) or a
        //                          same-direction retracement swing that does NOT exceed the
        //                          armed swing (scenario B), whichever happens first
        //   3 watching reaction -- watching the resulting zone (a real 1H IFOB for scenario A,
        //                          or an ad-hoc "reversal AOB" candle for scenario B) for a
        //                          wick-touch + close-respect reaction
        //   4 pending entry     -- reaction confirmed, waiting for next-hour open + session window
        private int _cascadeStage = 0;
        // The whole cascade dies at the end of the New York session on the day its daily
        // IFOB was touched -- never a rolling per-stage timeout. We'll never trade after
        // New York closes for that day, so there's nothing left to wait for past this
        // point regardless of which stage the cascade is stuck in.
        private DateTime _cascadeDeadline;

        private bool _targetBuy;      // the daily IFOB's own direction -- what we ultimately want to trade
        private int _pivotKind;       // 0 = wait for a new swing HIGH as pivot, 1 = wait for a new swing LOW
        private int _cascadeEvPtr;    // _h1.Ev.Count snapshot at daily touch -- only later events count

        private int _pivotSwingIdx = -1;   // the pivot's own swing index (e.g. SWH1)
        private int _pivotConfirmIdx = -1; // the candle where the pivot swing CONFIRMED
        private int _stage2MssPtr;         // _h1.Mss.Count snapshot at stage 1->2 transition
        private int _stage2EvPtr;          // _h1.Ev.Count snapshot at stage 1->2 transition

        // the zone being watched for reaction (stage 3+): either a real engine Ob index
        // (scenario A's freshly created continuation IFOB) or an ad-hoc candle (scenario B's
        // "reversal AOB", which is not the engine's own regime-continuation AOB and so isn't
        // added to _h1.Ob at all -- see AdvanceCascade's scenario B branch).
        private bool _zoneIsAdHoc;
        private int _zoneObIdx = -1;
        private double _zoneZb, _zoneZt;
        private bool _zoneBullish;

        private int _reactionCandle = -1;
        private double _entrySL = 0; // SL level fixed at the reaction candle, checked while we wait for session window

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
        //| Abandon the cascade back to idle -- ANY failure (violation,        |
        //| stranding, no qualifying candle, SL breached while waiting) ends    |
        //| this daily IFOB's one shot entirely. It does NOT retry with a       |
        //| fresh pivot: a daily IFOB is used once, then it expires, same as    |
        //| the engine's own zones (which can also only ever be touched once). |
        //| Trading it again on a later, separate reaction is a later stage.   |
        //+------------------------------------------------------------------+
        private void AbandonCascade(string reason)
        {
            Print($"[CASCADE] {Server.Time:u} {reason} -- IFOB expired, waiting for a fresh daily touch");
            _cascadeStage = 0;
        }

        //+------------------------------------------------------------------+
        //| Advance the daily-IFOB-triggered cascade one step (call after     |
        //| each H1 bar close). Places the entry order itself when respect    |
        //| confirms and the next hour's bar has opened. Falls straight       |
        //| through into the next stage's own check within the SAME call     |
        //| whenever a stage transition happens, rather than waiting for the  |
        //| next hourly call -- otherwise the very candle a transition should  |
        //| act on immediately (e.g. checking the entry candle right after a  |
        //| confirmed reaction) gets skipped, delaying entry by a full hour.  |
        //+------------------------------------------------------------------+
        private void AdvanceCascade()
        {
            if (_cascadeStage == 0) return;

            // We never trade after New York closes for the day the daily IFOB was
            // touched -- so nothing past that point is worth waiting for, regardless
            // of which stage the cascade is stuck in.
            if (Server.Time >= _cascadeDeadline)
            {
                AbandonCascade($"reached end of New York session ({_cascadeDeadline:u}) for the day this daily IFOB was touched, still in stage {_cascadeStage}");
                return;
            }

            if (_cascadeStage == 1)
            {
                for (int e = _cascadeEvPtr; e < _h1.Ev.Count; e++)
                {
                    if (_h1.Ev[e].Kind != _pivotKind) continue;
                    _pivotSwingIdx = _h1.Ev[e].SwingIdx;
                    _pivotConfirmIdx = _h1.Ev[e].ConfirmIdx;
                    _stage2MssPtr = _h1.Mss.Count;
                    _stage2EvPtr = e + 1;
                    _cascadeStage = 2;
                    Print($"[CASCADE] pivot {(_pivotKind == 0 ? "high" : "low")} confirmed at {_h1.T(_pivotSwingIdx):u} -- watching for direction change");
                    break;
                }
                return;
            }

            if (_cascadeStage == 2)
            {
                // Scenario A: a genuine 1H MSS in the target direction, at/after the pivot.
                int mssFoundK = -1;
                for (int m = _stage2MssPtr; m < _h1.Mss.Count; m++)
                {
                    if (_h1.Mss[m].K < _pivotConfirmIdx) continue;
                    if (_h1.Mss[m].Bullish != _targetBuy) continue;
                    mssFoundK = _h1.Mss[m].K;
                    _stage2MssPtr = m + 1;
                    break;
                }

                // Scenario B: the first opposite-kind swing confirming after the pivot,
                // without (yet) an MSS -- a same-direction retracement that holds.
                int oppKind = 1 - _pivotKind;
                int oppFoundEvIdx = -1;
                for (int e = _stage2EvPtr; e < _h1.Ev.Count; e++)
                {
                    if (_h1.Ev[e].Kind != oppKind) continue;
                    oppFoundEvIdx = e;
                    break;
                }

                bool haveA = mssFoundK != -1;
                bool haveB = oppFoundEvIdx != -1;
                if (!haveA && !haveB) return;

                // whichever happened at the earlier candle wins
                int bConfirmIdx = haveB ? _h1.Ev[oppFoundEvIdx].ConfirmIdx : int.MaxValue;
                bool takeA = haveA && (!haveB || mssFoundK <= bConfirmIdx);

                if (takeA)
                {
                    // find the freshly created continuation IFOB from this exact MSS candle
                    int found = -1;
                    for (int z = 0; z < _h1.Ob.Count; z++)
                        if (_h1.Ob[z].TriggerK == mssFoundK && _h1.Ob[z].Bullish == _targetBuy && _h1.Ob[z].State == 0)
                        { found = z; break; }
                    if (found == -1) { AbandonCascade("scenario A fired but no matching continuation IFOB found (shouldn't happen)"); return; }
                    _zoneIsAdHoc = false;
                    _zoneObIdx = found;
                    _zoneBullish = _targetBuy;
                    _cascadeStage = 3;
                    Print($"[CASCADE] scenario A: 1H MSS confirmed -- watching fresh 1H IFOB #{found} for reaction");
                }
                else
                {
                    var e = _h1.Ev[oppFoundEvIdx];
                    // range = [one candle before the pivot .. this retracement swing's own
                    // confirm], same widen-by-one convention as everywhere else. Pick the
                    // highest-closing BULLISH candle -- same pick rule as any bearish
                    // zone elsewhere -- but this is NOT the engine's own regime-continuation
                    // AOB (which would classify this same leg as bullish/continuation); it's
                    // traded in the daily IFOB's target direction, betting the retracement is
                    // actually a reversal. Computed ad-hoc rather than added to _h1.Ob.
                    int lo = Math.Max(0, Math.Min(_pivotSwingIdx - 1, e.SwingIdx));
                    int hi = Math.Max(_pivotSwingIdx - 1, e.SwingIdx);
                    int best = _targetBuy ? _h1.PickLowestBearish(lo, hi) : _h1.PickHighestBullish(lo, hi);
                    if (best == -1) { AbandonCascade("scenario B retracement had no qualifying candle in range"); return; }
                    _zoneIsAdHoc = true;
                    _zoneZb = Math.Min(_h1.O(best), _h1.C(best));
                    _zoneZt = Math.Max(_h1.O(best), _h1.C(best));
                    _zoneBullish = _targetBuy;
                    _cascadeStage = 3;
                    Print($"[CASCADE] scenario B: retracement swing at {_h1.T(e.SwingIdx):u} -- watching ad-hoc AOB candle={best} for reaction");
                }
                // fall straight through into stage 3 -- the swing-confirming candle itself
                // can also be the candle whose wick reaches the zone (e.g. the very candle
                // that breaks the prior candle's low to confirm the swing high dips down far
                // enough to touch it in the same move). Waiting for the next hourly call
                // would check the WRONG (later) candle and miss that same-candle case.
            }

            if (_cascadeStage == 3)
            {
                int lc = _h1.LastClosedIdx();
                if (lc < 0) return;

                // Ad-hoc (scenario B) zones aren't real Ob entries, so they get none of
                // the engine's own OOB-stranding checks for free. Their equivalent: if
                // the armed swing scenario A needed all along finally gets exceeded (a
                // genuine MSS) before this ad-hoc zone is ever touched, the reversal bet
                // failed -- it was just a retracement after all. Per the "OOB is useless,
                // never traded" rule, abandon this ad-hoc watch and pivot straight to the
                // fresh continuation IFOB that MSS just created, rather than stubbornly
                // continuing to watch a now-invalidated zone.
                if (_zoneIsAdHoc)
                {
                    for (int m = _stage2MssPtr; m < _h1.Mss.Count; m++)
                    {
                        if (_h1.Mss[m].Bullish != _targetBuy) continue;
                        int mssK = _h1.Mss[m].K;
                        _stage2MssPtr = m + 1;
                        int found = -1;
                        for (int z = 0; z < _h1.Ob.Count; z++)
                            if (_h1.Ob[z].TriggerK == mssK && _h1.Ob[z].Bullish == _targetBuy && _h1.Ob[z].State == 0)
                            { found = z; break; }
                        if (found != -1)
                        {
                            Print($"[CASCADE] ad-hoc AOB invalidated (armed swing exceeded, MSS at k={mssK}) -- pivoting to fresh 1H IFOB #{found}");
                            _zoneIsAdHoc = false;
                            _zoneObIdx = found;
                        }
                        break;
                    }
                }

                double zb, zt;
                if (!_zoneIsAdHoc)
                {
                    if (_h1.Ob[_zoneObIdx].State == 2)
                    {
                        AbandonCascade($"{_h1.T(lc):u} watched IFOB #{_zoneObIdx} stranded before reacting");
                        return;
                    }
                    zb = _h1.Ob[_zoneObIdx].Zb; zt = _h1.Ob[_zoneObIdx].Zt;
                }
                else { zb = _zoneZb; zt = _zoneZt; }

                bool wicked = (_h1.H(lc) >= zb && _h1.L(lc) <= zt);
                if (!wicked) return;

                bool respected = _zoneBullish ? (_h1.C(lc) >= zt) : (_h1.C(lc) <= zb);
                if (!respected)
                {
                    AbandonCascade($"{_h1.T(lc):u} reaction VIOLATED");
                    return;
                }

                _reactionCandle = lc;
                _entrySL = _zoneBullish ? _h1.L(lc) : _h1.H(lc);
                _cascadeStage = 4;
                Print($"[CASCADE] {_h1.T(lc):u} reaction RESPECTED -- pending entry (SL={_entrySL})");
                // fall straight through into stage 4 -- the very next candle after the
                // reaction is exactly what stage 4 needs to check for session-window
                // entry, and it may already be available in THIS same call.
            }

            if (_cascadeStage == 4)
            {
                // The session-time rule is a TIMING gate on when to fire the entry,
                // not a filter on which setups are eligible. A confirmed reaction
                // that happens to land outside the window must WAIT for the next
                // in-window hour, not be thrown away.
                int cur = _h1.N - 1; // the bar that just opened this tick (still forming)
                if (cur <= _reactionCandle) return; // the bar right after the reaction hasn't opened yet

                // While we wait, make sure price hasn't already breached the reaction
                // candle's SL level -- entering late on a setup that already failed
                // would put the stop on the wrong side of price.
                for (int x = _reactionCandle + 1; x <= cur; x++)
                {
                    bool breached = _zoneBullish ? (_h1.L(x) <= _entrySL) : (_h1.H(x) >= _entrySL);
                    if (breached)
                    {
                        AbandonCascade($"{_h1.T(x):u} SL level breached while waiting for session window");
                        return;
                    }
                }

                DateTime entryTime = _h1.T(cur);
                if (!InSessionWindow(entryTime)) return; // keep waiting for the next in-window hour

                // NOTE: unfiltered, matching the .mq5's PositionsTotal() check --
                // this counts ALL open positions on the account, not just this bot's.
                if (Positions.Count > 0)
                {
                    Print($"[CASCADE] {entryTime:u} setup ready but a position is already open -- setup skipped");
                    _cascadeStage = 0; return; // one trade at a time
                }

                double entryPrice = _h1.O(cur);
                double slPrice = _entrySL;
                double riskDist = _zoneBullish ? (entryPrice - slPrice) : (slPrice - entryPrice);
                if (riskDist <= 0) { AbandonCascade("entry price already past SL at fire time"); return; }

                double tpPrice = _zoneBullish ? entryPrice + riskDist * InpRR_Target : entryPrice - riskDist * InpRR_Target;
                double volume = CalcLotSize(riskDist, _zoneBullish, entryPrice);
                Print($"[CASCADE] {entryTime:u} ENTRY {(_zoneBullish ? "BUY" : "SELL")} @ {entryPrice} SL={slPrice} TP={tpPrice} volume={volume}");
                if (volume > 0)
                {
                    double slPips = Math.Abs(entryPrice - slPrice) / Symbol.PipSize;
                    double tpPips = Math.Abs(tpPrice - entryPrice) / Symbol.PipSize;
                    ExecuteMarketOrder(_zoneBullish ? TradeType.Buy : TradeType.Sell, SymbolName, volume, InpLabel, slPips, tpPips, InpLabel);
                    Chart.DrawIcon($"entry_{entryTime.Ticks}", _zoneBullish ? ChartIconType.UpArrow : ChartIconType.DownArrow,
                        entryTime, entryPrice, _zoneBullish ? Color.Lime : Color.Red);
                    Chart.DrawText($"entrytxt_{entryTime.Ticks}", _zoneBullish ? "BUY 3R" : "SELL 3R", entryTime, entryPrice,
                        _zoneBullish ? Color.Lime : Color.Red);
                }
                _cascadeStage = 0; // done -- wait for the next fresh daily IFOB touch
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
        //| Shared bookkeeping: which daily Ob indices have already triggered |
        //| the cascade, so a stale/older touch never resurfaces after a      |
        //| newer one takes over, and the tick-level scanner below and the    |
        //| once-daily official-close catch-up never double-fire the same     |
        //| zone.                                                              |
        //+------------------------------------------------------------------+
        private readonly HashSet<int> _dailyTriggeredObIdx = new HashSet<int>();

        private void StartCascadeFromDailyIfob(int obIdx, bool bullish, DateTime dayTime, double dayH, double dayL)
        {
            var ob = _daily.Ob[obIdx];
            _dailyTriggeredObIdx.Add(obIdx);
            _targetBuy = bullish;
            _pivotKind = bullish ? 1 : 0; // buy target -> wait for a new swing LOW; sell target -> new swing HIGH
            _cascadeEvPtr = _h1.Ev.Count;
            _cascadeStage = 1;
            // The cascade dies at the end of the New York session on THIS SAME calendar
            // day (the day of the daily touch) -- we never trade after New York, so
            // there's nothing to gain by surviving past it, no matter which stage it's in.
            _cascadeDeadline = new DateTime(dayTime.Year, dayTime.Month, dayTime.Day, InpNewYorkSessionEndHour, 0, 0, DateTimeKind.Utc);
            Print($"[CASCADE] fresh daily IFOB #{obIdx} touch ({(bullish ? "bullish" : "bearish")}) "
                + $"zone=[{ob.Zb:F5}..{ob.Zt:F5}] zoneFormedAt={ob.T:u} "
                + $"dailyCandle={dayTime:u} H={dayH:F5} L={dayL:F5} deadline={_cascadeDeadline:u} -- watching 1H for pivot");
        }

        //+------------------------------------------------------------------+
        //| Intraday touch scanner (call every tick): checks the CURRENT,     |
        //| still-forming daily candle's live high/low against every already- |
        //| confirmed (from a prior day's CLOSE), still-live daily IFOB zone. |
        //| Zone CREATION only ever happens off closed-bar data, via          |
        //| _daily.Refresh() once a day, so boundaries stay stable -- but     |
        //| "has price entered it" is a plain price-level check that doesn't  |
        //| need the candle to close first, so this runs on every tick for    |
        //| the moment-of-entry reaction the entry rule actually calls for,   |
        //| not a reaction delayed until the daily candle finishes.           |
        //+------------------------------------------------------------------+
        private void CheckDailyTouchIntraday()
        {
            if (_dailyBars == null || _dailyBars.Count == 0 || _daily.Ob.Count == 0) return;
            int curIdx = _dailyBars.Count - 1;
            double curH = _dailyBars.HighPrices[curIdx];
            double curL = _dailyBars.LowPrices[curIdx];
            DateTime curT = _dailyBars.OpenTimes[curIdx];

            for (int z = 0; z < _daily.Ob.Count; z++)
            {
                var ob = _daily.Ob[z];
                if (ob.State != 0) continue;              // only a still-live IFOB (covers a promoted AIFOB too)
                if (ob.EligibleK == -1) continue;          // not yet armed
                if (_dailyTriggeredObIdx.Contains(z)) continue;
                if (curH >= ob.Zb && curL <= ob.Zt)
                    StartCascadeFromDailyIfob(z, ob.Bullish, curT, curH, curL);
            }
        }

        //+------------------------------------------------------------------+
        //| Once-daily catch-up (call after _daily.Refresh()): the intraday   |
        //| scanner above should already have caught any touch as it          |
        //| happened. This just covers a touch the scanner could have missed  |
        //| (e.g. the EA was started mid-day, after the touch already         |
        //| happened), using the engine's own official TouchK/PreSpentState   |
        //| -- sharing the same _dailyTriggeredObIdx bookkeeping so nothing    |
        //| ever double-fires.                                                 |
        //+------------------------------------------------------------------+
        private void UpdateDailyTrigger()
        {
            // Must only ever consider a touch on the LAST CLOSED daily candle -- this
            // exists purely to catch a touch that happened earlier TODAY before the
            // intraday tick scanner had a chance to see it (e.g. the EA just started).
            // Scanning ALL of _daily.Ob for anything EVER touched (the previous bug)
            // reaches back into years of pre-loaded history and fires long-past
            // touches as if they just happened, using today's 1H data to hunt a pivot
            // that has nothing to do with that old touch -- i.e. trading off a touch
            // that isn't actually current at all.
            int lc = _daily.LastClosedIdx();
            if (lc < 0) return;
            for (int z = 0; z < _daily.Ob.Count; z++)
            {
                var ob = _daily.Ob[z];
                if (ob.TouchK != lc) continue;
                if (ob.PreSpentState != 0) continue; // only IFOB -- not AOB/AIFOB/already-stranded
                if (_dailyTriggeredObIdx.Contains(z)) continue;
                StartCascadeFromDailyIfob(z, ob.Bullish, _daily.T(lc), _daily.H(lc), _daily.L(lc));
            }
        }

        //+------------------------------------------------------------------+
        //| Chart drawing: swing highs/lows, MSS marks, and OB zones (colored |
        //| and labeled by exact type) for one engine. Daily draws all five   |
        //| states (IFOB/AOB/AIFOB/OOB/SPENT); 4H and 1H only ever ACT on     |
        //| IFOB/AOB, but OOB zones are still drawn there too (gray) purely   |
        //| for transparency -- so you can see a zone existed and why it was  |
        //| never traded, not just that nothing happened.                     |
        //+------------------------------------------------------------------+
        private Color ObColor(int state, int origState, bool isFvg)
        {
            if (!isFvg)
            {
                // OB palette: green/blue family
                if (state == 2) return Color.Gray;                                   // OOB -- dead
                if (state == 3)                                                       // SPENT -- shade by original type
                    return origState == 1 ? Color.RoyalBlue : origState == 4 ? Color.Teal : Color.SeaGreen;
                if (origState == 1) return Color.DeepSkyBlue;   // AOB, live
                if (origState == 4) return Color.Turquoise;     // AIFOB, live
                return Color.LimeGreen;                          // IFOB, live
            }
            else
            {
                // FVG palette: gold/orange/purple family -- never confusable with OB
                if (state == 2) return Color.DimGray;                                 // OFVG -- dead (Daily only)
                if (state == 3)                                                       // spent/invalidated -- shade by original type
                    return origState == 1 ? Color.MediumPurple : origState == 4 ? Color.Indigo : Color.Purple;
                if (origState == 1) return Color.Orange;         // AFVG, live
                if (origState == 4) return Color.DarkOrange;     // AIFVG, live
                return Color.Gold;                                // IFVG, live
            }
        }

        private string ObLabel(int state, int origState, bool isFvg)
        {
            string baseLabel = !isFvg
                ? (origState == 1 ? "AOB" : origState == 4 ? "AIFOB" : "IFOB")
                : (origState == 1 ? "AFVG" : origState == 4 ? "AIFVG" : "IFVG");
            if (state == 2) return isFvg ? "OFVG" : "OOB";
            if (state == 3) return baseLabel + " (spent)";
            return baseLabel;
        }

        private void DrawEngine(OBEngine eng, DrawCache cache, string prefix)
        {
            // swings -- append-only, never change once drawn
            for (int i = cache.EvDrawn; i < eng.Ev.Count; i++)
            {
                var e = eng.Ev[i];
                DateTime t = eng.T(e.SwingIdx);
                bool isHigh = e.Kind == 0;
                Chart.DrawIcon($"{prefix}_sw_{i}", ChartIconType.Circle, t, e.Price, isHigh ? Color.OrangeRed : Color.DodgerBlue);
            }
            cache.EvDrawn = eng.Ev.Count;

            // MSS marks -- append-only too
            for (int i = cache.MssDrawn; i < eng.Mss.Count; i++)
            {
                var m = eng.Mss[i];
                DateTime t = eng.T(m.K);
                double y = m.Bullish ? eng.L(m.K) : eng.H(m.K);
                Chart.DrawText($"{prefix}_mss_{i}", "MSS", t, y, m.Bullish ? Color.LimeGreen : Color.OrangeRed);
            }
            cache.MssDrawn = eng.Mss.Count;

            // OB zones -- keep redrawing (extending the right edge to "now") only while
            // still live; once resolved (OOB or SPENT), draw the final version once, then skip.
            for (int i = 0; i < eng.Ob.Count; i++)
            {
                var ob = eng.Ob[i];
                bool stillLive = (ob.State == 0 || ob.State == 1 || ob.State == 4);
                int lastState = i < cache.ObState.Count ? cache.ObState[i] : -1;
                if (!stillLive && lastState == ob.State) continue; // already drawn at its final state

                Color c = ObColor(ob.State, ob.OrigState, ob.IsFvg);
                string label = ObLabel(ob.State, ob.OrigState, ob.IsFvg);
                DateTime t1 = eng.T(ob.Candle);
                DateTime t2 = stillLive ? eng.T(eng.N - 1) : (ob.TouchK != -1 ? eng.T(ob.TouchK) : t1);

                var rect = Chart.DrawRectangle($"{prefix}_ob_{i}", t1, ob.Zt, t2, ob.Zb, c, 1);
                rect.IsFilled = false;
                // NOTE: verify this property name (LineStyle vs Style) against your cAlgo API version.
                rect.LineStyle = ob.IsFvg ? LineStyle.Dots : LineStyle.Solid; // FVG = dashed, OB = solid
                Chart.DrawText($"{prefix}_obtxt_{i}", $"{prefix} {label}", t1, ob.Bullish ? ob.Zb : ob.Zt, c);

                while (cache.ObState.Count <= i) cache.ObState.Add(-1);
                cache.ObState[i] = ob.State;
            }
        }

        //+------------------------------------------------------------------+
        //| Live status readout, corner-anchored (not tied to a chart time/   |
        //| price) so you can see the cascade's current state at a glance.   |
        //+------------------------------------------------------------------+
        private void UpdateStatusText()
        {
            string stageTxt;
            if (_cascadeStage == 0) stageTxt = "idle -- waiting for a fresh daily IFOB touch";
            else if (_cascadeStage == 1) stageTxt = $"daily IFOB touched ({(_targetBuy ? "buy" : "sell")} target) -- watching 1H for pivot {(_pivotKind == 0 ? "high" : "low")}";
            else if (_cascadeStage == 2) stageTxt = "pivot confirmed -- watching for 1H direction change";
            else if (_cascadeStage == 3) stageTxt = _zoneIsAdHoc ? "watching ad-hoc AOB for reaction" : $"watching 1H IFOB #{_zoneObIdx} for reaction";
            else stageTxt = "reaction confirmed -- waiting for session window / SL check";

            string text = $"Cascade stage: {stageTxt}";
            Chart.DrawStaticText("ict_status", text, VerticalAlignment.Top, HorizontalAlignment.Left, Color.White);
        }

        //+------------------------------------------------------------------+
        //| Request extra history without blocking. Bars.LoadMoreHistory() is |
        //| asynchronous -- it queues a request and the data arrives later via |
        //| the platform's event loop. A synchronous wait-loop on bars.Count   |
        //| (the previous version of this method) deadlocks OnStart(): the     |
        //| loop never returns control to the platform, so the very event     |
        //| that would satisfy it can never fire. Fire-and-forget instead --   |
        //| whatever is already loaded is used immediately, and more history   |
        //| simply becomes visible to later Refresh() calls once it arrives.  |
        //| Bars loaded this way are permanent (see the note on Refresh()      |
        //| above), so nothing is ever lost once it shows up.                  |
        //+------------------------------------------------------------------+
        private Bars GetEngineBars(TimeFrame tf)
        {
            var bars = MarketData.GetBars(tf, SymbolName);
            bars.LoadMoreHistory();
            return bars;
        }

        protected override void OnStart()
        {
            _dailyBars = GetEngineBars(TimeFrame.Daily);
            _h4Bars = GetEngineBars(TimeFrame.Hour4);
            _h1Bars = GetEngineBars(TimeFrame.Hour);

            _daily = new OBEngine(_dailyBars);
            _h4 = new OBEngine(_h4Bars);
            _h1 = new OBEngine(_h1Bars);

            _dailyBars.BarOpened += OnDailyBarOpened;
            _h4Bars.BarOpened += OnH4BarOpened;
            _h1Bars.BarOpened += OnH1BarOpened;

            // establish a baseline state immediately, same as the .mq5's first tick
            // (which always refreshes all three engines unconditionally)
            _daily.Refresh(); UpdateDailyTrigger();
            _h4.Refresh(); // 4H is drawn only -- no longer part of the trading cascade
            _h1.Refresh(); AdvanceCascade();

            if (InpShowDaily) DrawEngine(_daily, _dailyDraw, "D");
            if (InpShowH4) DrawEngine(_h4, _h4Draw, "H4");
            if (InpShowH1) DrawEngine(_h1, _h1Draw, "H1");
            UpdateStatusText();
        }

        private void OnDailyBarOpened(BarOpenedEventArgs args)
        {
            _daily.Refresh();
            UpdateDailyTrigger();
            if (InpShowDaily) DrawEngine(_daily, _dailyDraw, "D");
            UpdateStatusText();
        }

        private void OnH4BarOpened(BarOpenedEventArgs args)
        {
            _h4.Refresh();
            if (InpShowH4) DrawEngine(_h4, _h4Draw, "H4");
        }

        private void OnH1BarOpened(BarOpenedEventArgs args)
        {
            _h1.Refresh();
            AdvanceCascade();
            if (InpShowH1) DrawEngine(_h1, _h1Draw, "H1");
            UpdateStatusText();
        }

        protected override void OnTick()
        {
            ManageBreakeven();
            CheckDailyTouchIntraday();
        }
    }
}
