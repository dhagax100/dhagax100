// ICT_Full_OB_v24 — cTrader (cAlgo.API, C#)
// Faithful 1:1 port of pine/ICT_Full_OB_v24.pine (Pine Script v5).
// Draws swing highs, swing lows, MSS flips, and all four POI types with
// identical state machines to the Pine source:
//   OB  : IFOB, AOB, AIFOB, OOB, SPENT
//   FVG : IFVG, AFVG, OFVG, SPENT            (no AIFVG)
//   RB  : IRB, ARB, AIRB, ORB, SPENT
//   VI  : IVI, AVI, OVI, SPENT               (no AIVI)
// See docs/trading_logic.md and HANDOFF.md for the full design history.
//
// ONE DELIBERATE ADAPTATION FROM THE PINE SOURCE:
// Pine's "process each bar exactly once" guard (bar_index != lastProcessedBI)
// only blocks re-execution within the same still-forming bar; on a live feed
// that means it captures whatever OHLC existed on that bar's very FIRST tick
// and never updates it again -- a quirk that only makes sense on TradingView's
// bar-replay tool (this script's real use case), not on a live chart. Here,
// the whole engine (RunEngine) instead fires exactly once per bar, and only
// once that bar has fully CLOSED (see OnBarOpened below) -- so every zone is
// always built from a bar's final OHLC, never a partial live print. This is
// the correct behavior for what the Pine guard was actually trying to do,
// not a shortcut.
//
// Zone types (ObZone/FvgZone/RbZone/ViZone) are C# classes, i.e. reference
// types -- exactly like Pine v5's `type`. array.get(...) + mutate + array.set
// in the Pine source is just Pine's own defensive (and redundant) style; a
// plain field mutation on the object already stored in the list has the same
// effect here, so the explicit "set back into the list" step is omitted
// throughout -- not a behavior change, just dropped boilerplate.
//
// NOTE: written and reviewed line-by-line against the Pine source, but not
// compiled against the real cAlgo SDK (unavailable in this environment).
// Paste into cTrader Automate -> New Indicator, hit Build, and report back
// any compiler errors -- likely candidates are exact Chart.Draw* overload
// names, which I could not verify against the live API here.

using System;
using System.Collections.Generic;
using cAlgo.API;

namespace cAlgo.Indicators
{
    [Indicator(IsOverlay = true)]
    public class ICT_Full_OB_v24 : Indicator
    {
        // ===================== INPUTS =====================
        [Parameter("Months to display", DefaultValue = 6, Group = "Display")]
        public int InpMonthsBack { get; set; }

        [Parameter("Display from date", DefaultValue = "2025-07-25", Group = "Display")]
        public DateTime InpDisplayFrom { get; set; }

        [Parameter("Use exact display-from date (else use months)", DefaultValue = true, Group = "Display")]
        public bool UseDisplayFrom { get; set; }

        [Parameter("Enable replay mode", DefaultValue = false, Group = "Replay")]
        public bool UseReplay { get; set; }

        [Parameter("Replay up to date (ignored unless replay enabled)", Group = "Replay")]
        public DateTime InpReplayUpTo { get; set; }

        [Parameter("Focus OB (0=show all in window, N=Nth from end)", DefaultValue = 0, Group = "Display")]
        public int InpFocusOB { get; set; }

        [Parameter("Max swing-high / swing-low / MSS labels shown (each)", DefaultValue = 150, MinValue = 1, MaxValue = 160, Group = "Display")]
        public int InpMaxLabelsPerCategory { get; set; }

        [Parameter("Swing-low arrow / down-MSS gap below the low (x ATR14)", DefaultValue = 0.08, MinValue = 0.0, Group = "Display")]
        public double InpSwingLowGapATR { get; set; }

        [Parameter("Max IFVG / AFVG boxes shown (each category)", DefaultValue = 150, MinValue = 1, MaxValue = 160, Group = "Display")]
        public int InpMaxFvgPerCategory { get; set; }

        [Parameter("IFVG fill transparency % (0=solid, 100=invisible)", DefaultValue = 85, MinValue = 0, MaxValue = 100, Group = "Display")]
        public int InpFvgFillTransparency { get; set; }

        [Parameter("Max IRB / ARB boxes shown (each category)", DefaultValue = 150, MinValue = 1, MaxValue = 160, Group = "Display")]
        public int InpMaxRbPerCategory { get; set; }

        [Parameter("Max IVI / AVI boxes shown (each category)", DefaultValue = 150, MinValue = 1, MaxValue = 160, Group = "Display")]
        public int InpMaxViPerCategory { get; set; }

        [Parameter("IVI fill transparency % (0=solid, 100=invisible)", DefaultValue = 85, MinValue = 0, MaxValue = 100, Group = "Display")]
        public int InpViFillTransparency { get; set; }

        // ===================== TYPES =====================
        // Reference types, mirroring Pine v5's `type` -- see header note.
        private class SwEv
        {
            public int ConfirmIdx;
            public int Kind;   // 0=high, 1=low
            public int SwingIdx;
            public double Price;
        }

        private class MssEv
        {
            public int AtIdx;
            public int BrokenIdx;
            public double Price;
            public bool ToUp;
        }

        private class ObZone
        {
            public int Candle;
            public double Zb, Zt;
            public bool Bullish;
            public int TriggerK;
            public int EligibleK = -1;
            public int StopK = -1;
            public int State;         // 0=IFOB,1=AOB,2=OOB,3=SPENT,4=AIFOB
            public int OrigState;
            public int PreSpentState;
        }

        // IFVG mirrors IFOB one-for-one (delayed eligibility, far-side
        // stranding); AFVG mirrors AOB (immediate eligibility, near-side
        // stranding). AIFVG not implemented (matches Pine source).
        private class FvgZone
        {
            public int LeftIdx;
            public double Zb, Zt;
            public bool Bullish;
            public int TriggerK;
            public int EligibleK = -1;
            public int StopK = -1;
            public int State;         // 0=IFVG,1=AFVG,2=OFVG,3=SPENT
            public int Origin;        // permanent: 0=far-side stranding, 1=near-side
            public int PreSpentState;
        }

        // RB zone: the WICK of a single swing-pivot candle (no scanning).
        private class RbZone
        {
            public int LeftIdx;
            public double Zb, Zt;
            public bool Bullish;      // RAW WICK TYPE: swing-low wick=true, swing-high wick=false
            public int TriggerK;
            public int EligibleK = -1;
            public int StopK = -1;
            public int State;         // 0=IRB,1=ARB,2=ORB,3=SPENT,4=AIRB
            public int Origin;        // 0=IRB-style far-side, 1=ARB-style near-side.
                                       // AIRB born with Origin=4 (far-side bucket, same
                                       // as OrigState!=1 selecting far-side for OB),
                                       // reset to 0 on promotion to a real IRB.
            public int PreSpentState;
        }

        // VI: the 2-candle version of an FVG (close[1] vs open[2], not wicks).
        private class ViZone
        {
            public int LeftIdx;
            public double Zb, Zt;
            public bool Bullish;
            public int TriggerK;
            public int EligibleK = -1;
            public int StopK = -1;
            public int State;         // 0=IVI,1=AVI,2=OVI,3=SPENT
            public int Origin;        // 0=IVI-style far-side, 1=AVI-style near-side
            public int PreSpentState;
        }

        // ===================== PERSISTENT STATE =====================
        private readonly List<SwEv> _events = new List<SwEv>();
        private readonly List<MssEv> _msses = new List<MssEv>();
        private readonly List<ObZone> _obs = new List<ObZone>();
        private readonly List<FvgZone> _fvgs = new List<FvgZone>();
        private readonly List<RbZone> _rbs = new List<RbZone>();
        private readonly List<ViZone> _vis = new List<ViZone>();
        private readonly List<int> _swHighs = new List<int>();
        private readonly List<int> _swLows = new List<int>();

        // OHLC + time storage, absolute indexing oldest=0 -- mirrors Pine's
        // O_/H_/L_/C_/BT arrays. Index into these equals the source Bars
        // index one-for-one as long as every bar is processed in order from
        // index 0 (replay mode only ever truncates the tail, never skips a
        // hole in the middle), so these indices double as chart bar indices
        // for drawing.
        private readonly List<double> _O = new List<double>();
        private readonly List<double> _H = new List<double>();
        private readonly List<double> _L = new List<double>();
        private readonly List<double> _C = new List<double>();
        private readonly List<DateTime> _BT = new List<DateTime>();

        // Swing detection trackers
        private int _peakIdx = 0;
        private int _troughIdx = 0;

        // Regime / MSS / OB trackers
        private bool _haveSWH = false;
        private double _swhPrice = 0.0;
        private int _swhIdx = 0;
        private bool _haveSWL = false;
        private double _swlPrice = 0.0;
        private int _swlIdx = 0;
        private int _regime = 0;      // 0=warmup, 1=up, 2=down
        private int _ei = 0;          // event pointer
        private int _lastSWHidx = -1;
        private int _lastSWLidx = -1;
        private int _pendBullAifob = -1;
        private int _pendBearAifob = -1;
        private int _pendBullAirb = -1;
        private int _pendBearAirb = -1;
        private int _fvgBullScanUpto = -1;
        private int _fvgBearScanUpto = -1;
        private int _viBullScanUpto = -1;
        private int _viBearScanUpto = -1;

        // Guard: only ever process a given source-bar index once (mirrors
        // Pine's "process each bar exactly once" intent, see header note).
        private int _lastProcessedIndex = -1;

        private AverageTrueRange _atr;

        // Drawing bookkeeping (mirrors Pine's drawnLabels/drawnBoxes/drawnLines
        // delete-then-redraw pattern, using chart object names instead).
        private readonly List<string> _drawnObjectNames = new List<string>();

        // ===================== LIFECYCLE =====================
        protected override void Initialize()
        {
            _atr = Indicators.AverageTrueRange(14, MovingAverageType.WilderSmoothing);

            // Process every already-closed historical bar. The current last
            // bar (still forming) is deliberately left for OnBarOpened, so
            // the engine never runs on partial/live OHLC (see header note).
            int upto = Bars.Count - 1;
            for (int idx = 0; idx < upto; idx++)
                MaybeProcessBar(idx);

            Bars.BarOpened += OnBarOpened;
            RedrawAll();
        }

        private void OnBarOpened(BarOpenedEventArgs obj)
        {
            // A new bar just opened, so Bars.Count-2 is now fully closed.
            int closedIndex = Bars.Count - 2;
            if (closedIndex >= 0)
                MaybeProcessBar(closedIndex);
            RedrawAll();
        }

        public override void Calculate(int index)
        {
            // Keep the drawing fresh as the current bar's price moves, using
            // whatever has already been processed (closed bars only).
            if (index == Bars.Count - 1)
                RedrawAll();
        }

        private void MaybeProcessBar(int srcIndex)
        {
            if (srcIndex <= _lastProcessedIndex) return;
            _lastProcessedIndex = srcIndex;
            PushBarAndProcess(srcIndex);
        }

        private void PushBarAndProcess(int srcIndex)
        {
            // Replay gate -- mirrors Pine's skipBar: bars beyond the replay
            // cutoff are excluded entirely, never pushed into the arrays.
            bool replayActive = UseReplay && InpReplayUpTo != default(DateTime);
            if (replayActive && Bars.OpenTimes[srcIndex] > InpReplayUpTo)
                return;

            _O.Add(Bars.OpenPrices[srcIndex]);
            _H.Add(Bars.HighPrices[srcIndex]);
            _L.Add(Bars.LowPrices[srcIndex]);
            _C.Add(Bars.ClosePrices[srcIndex]);
            _BT.Add(Bars.OpenTimes[srcIndex]);

            int n = _O.Count;
            if (n < 2) return; // matches Pine's "if n >= 2" gate

            int k = n - 1;
            RunEngine(k);
        }

        // ===================== MAIN ENGINE (per bar k) =====================
        private void RunEngine(int k)
        {
            // ---------- SWING DETECTION ----------
            bool isBull = _C[k] >= _O[k];
            bool brkH = _H[k] > _H[k - 1];
            bool brkL = _L[k] < _L[k - 1];
            bool dualAct = brkH && brkL;

            bool prevDual = false;
            int pdKind1 = -1, pdIdx1 = -1, pdKind2 = -1, pdIdx2 = -1;
            int eCnt = _events.Count;
            if (eCnt >= 2)
            {
                var ev1 = _events[eCnt - 1];
                var ev2 = _events[eCnt - 2];
                if (ev1.Kind != ev2.Kind && ev1.ConfirmIdx == ev2.ConfirmIdx && ev1.ConfirmIdx == k - 1)
                {
                    prevDual = true;
                    pdKind1 = ev1.Kind; pdIdx1 = ev1.SwingIdx;
                    pdKind2 = ev2.Kind; pdIdx2 = ev2.SwingIdx;
                }
            }

            int evBeforeSwing = _events.Count; // save for STEP 3

            if (!isBull)
            {
                // BEARISH: High first, then Low
                if (_H[k] > _H[_peakIdx]) _peakIdx = k;
                if (brkH)
                {
                    int lk = _events.Count > 0 ? _events[_events.Count - 1].Kind : -1;
                    bool blockDup = prevDual && !dualAct && ((pdKind1 == 1 && pdIdx1 == _troughIdx) || (pdKind2 == 1 && pdIdx2 == _troughIdx));
                    if (lk != 1 && !blockDup)
                    {
                        AddSL(_troughIdx);
                        AddEv(k, 1, _troughIdx, _L[_troughIdx]);
                        _peakIdx = k;
                    }
                }
                if (_L[k] < _L[_troughIdx]) _troughIdx = k;
                if (brkL)
                {
                    int lk2 = _events.Count > 0 ? _events[_events.Count - 1].Kind : -1;
                    bool blockDup2 = prevDual && !dualAct && ((pdKind1 == 0 && pdIdx1 == _peakIdx) || (pdKind2 == 0 && pdIdx2 == _peakIdx));
                    if (lk2 != 0 && !blockDup2)
                    {
                        AddSH(_peakIdx);
                        AddEv(k, 0, _peakIdx, _H[_peakIdx]);
                        _troughIdx = k;
                    }
                }
            }
            else
            {
                // BULLISH: Low first, then High
                if (_L[k] < _L[_troughIdx]) _troughIdx = k;
                if (brkL)
                {
                    int lk3 = _events.Count > 0 ? _events[_events.Count - 1].Kind : -1;
                    bool blockDup3 = prevDual && !dualAct && ((pdKind1 == 0 && pdIdx1 == _peakIdx) || (pdKind2 == 0 && pdIdx2 == _peakIdx));
                    if (lk3 != 0 && !blockDup3)
                    {
                        AddSH(_peakIdx);
                        AddEv(k, 0, _peakIdx, _H[_peakIdx]);
                        _troughIdx = k;
                    }
                }
                if (_H[k] > _H[_peakIdx]) _peakIdx = k;
                if (brkH)
                {
                    int lk4 = _events.Count > 0 ? _events[_events.Count - 1].Kind : -1;
                    bool blockDup4 = prevDual && !dualAct && ((pdKind1 == 1 && pdIdx1 == _troughIdx) || (pdKind2 == 1 && pdIdx2 == _troughIdx));
                    if (lk4 != 1 && !blockDup4)
                    {
                        AddSL(_troughIdx);
                        AddEv(k, 1, _troughIdx, _L[_troughIdx]);
                        _peakIdx = k;
                    }
                }
            }

            // ---------- REGIME / MSS / OB ENGINE ----------
            int evTotal = _events.Count;

            // STEP 0: peek-ahead -- update lastSWHidx/lastSWLidx
            int peek0 = _ei;
            while (peek0 < evTotal)
            {
                var pEv = _events[peek0];
                if (pEv.ConfirmIdx != k) break;
                if (pEv.Kind == 0) _lastSWHidx = pEv.SwingIdx;
                else _lastSWLidx = pEv.SwingIdx;
                peek0++;
            }

            int prevReg = _regime;
            bool swhCons = false;
            bool swlCons = false;
            int aobSWHi = _swhIdx;
            int aobSWLi = _swlIdx;

            // STEP 1 + MID-ARM: break checks, MSS, IFOB, AOB, AIFOB, IRB/ARB/AIRB
            bool kBull = _C[k] >= _O[k];

            if (!kBull)
            {
                // --- BEARISH bar: high first -> SWH break first ---
                if (_haveSWH && _H[k] > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2) { _regime = 1; AddMss(k, _swhIdx, _swhPrice, true); }

                    bool pendStillAlive = false;
                    if (_pendBullAifob != -1) pendStillAlive = _obs[_pendBullAifob].State == 4;
                    if (pendStillAlive)
                    {
                        var obRef = _obs[_pendBullAifob];
                        obRef.State = 0;
                        obRef.OrigState = 0;
                        obRef.EligibleK = -1;
                        _pendBullAifob = -1;
                    }
                    else
                    {
                        _pendBullAifob = -1;
                    }
                    if (!pendStillAlive && _lastSWLidx >= 0)
                    {
                        int lo = Math.Min(Math.Min(_lastSWLidx, k), _swhIdx);
                        int hi = Math.Max(Math.Max(_lastSWLidx, k), _swhIdx);
                        TryCreateIFVGs(lo, hi, true, k);
                        _fvgBullScanUpto = hi;
                        TryCreateIVIs(lo, hi, true, k);
                        _viBullScanUpto = hi;
                        if (!ExistsAifobInRange(lo, hi, true))
                        {
                            int best = -1;
                            for (int x = lo; x <= hi; x++)
                            {
                                double cX = _C[x], oX = _O[x];
                                bool okB = false;
                                if (cX < oX) { if (best == -1) okB = true; else okB = cX < _C[best]; }
                                if (okB) best = x;
                            }
                            if (best != -1 && !CandleClaimed(best, true))
                            {
                                double oB = _O[best], cB = _C[best];
                                AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive = false;
                    if (_pendBullAirb != -1) pendRbStillAlive = _rbs[_pendBullAirb].State == 4;
                    if (pendRbStillAlive)
                    {
                        var rbRef = _rbs[_pendBullAirb];
                        rbRef.State = 0;
                        rbRef.Origin = 0;
                        rbRef.EligibleK = -1;
                        _pendBullAirb = -1;
                    }
                    else
                    {
                        _pendBullAirb = -1;
                    }
                    if (!pendRbStillAlive && _lastSWLidx >= 0)
                    {
                        int rbLo = Math.Min(Math.Min(_lastSWLidx, k), _swhIdx);
                        int rbHi = Math.Max(Math.Max(_lastSWLidx, k), _swhIdx);
                        if (!ExistsAirbInRange(rbLo, rbHi, true) && !SwingClaimed(_lastSWLidx, true))
                            AddRBFromSwing(_lastSWLidx, false, k, 0);
                    }

                    _haveSWH = false;
                    swhCons = true;
                }

                // MID-ARM
                int peek2 = _ei;
                while (peek2 < evTotal)
                {
                    var pEv2 = _events[peek2];
                    if (pEv2.ConfirmIdx != k) break;
                    if (pEv2.Kind == 0)
                    {
                        _haveSWH = true;
                        _swhPrice = pEv2.Price;
                        _swhIdx = pEv2.SwingIdx;
                        _pendBullAifob = -1;
                        _pendBullAirb = -1;
                        TryBearAOB(prevReg, aobSWLi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBearAFVG(prevReg, aobSWLi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBearARB(prevReg, aobSWLi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBearAVI(prevReg, aobSWLi, pEv2.SwingIdx, pEv2.Price, k);
                        if (_pendBearAifob == -1)
                        {
                            int r2 = TryBearAIFOB(prevReg, _haveSWL, aobSWLi, _lastSWHidx, pEv2.SwingIdx, k);
                            if (r2 != -1) _pendBearAifob = r2;
                        }
                        if (_pendBearAirb == -1)
                        {
                            int rr2 = TryBearAIRB(prevReg, _haveSWL, aobSWLi, _lastSWHidx, pEv2.SwingIdx, k);
                            if (rr2 != -1) _pendBearAirb = rr2;
                        }
                    }
                    else
                    {
                        _haveSWL = true;
                        _swlPrice = pEv2.Price;
                        _swlIdx = pEv2.SwingIdx;
                        _pendBearAifob = -1;
                        _pendBearAirb = -1;
                        TryBullAOB(prevReg, aobSWHi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBullAFVG(prevReg, aobSWHi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBullARB(prevReg, aobSWHi, pEv2.SwingIdx, pEv2.Price, k);
                        TryBullAVI(prevReg, aobSWHi, pEv2.SwingIdx, pEv2.Price, k);
                        if (_pendBullAifob == -1)
                        {
                            int r3 = TryBullAIFOB(prevReg, _haveSWH, aobSWHi, _lastSWLidx, pEv2.SwingIdx, k);
                            if (r3 != -1) _pendBullAifob = r3;
                        }
                        if (_pendBullAirb == -1)
                        {
                            int rr3 = TryBullAIRB(prevReg, _haveSWH, aobSWHi, _lastSWLidx, pEv2.SwingIdx, k);
                            if (rr3 != -1) _pendBullAirb = rr3;
                        }
                    }
                    peek2++;
                }

                // Second break: SWL
                if (_haveSWL && _L[k] < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1) { _regime = 2; AddMss(k, _swlIdx, _swlPrice, false); }

                    bool pendStillAlive2 = false;
                    if (_pendBearAifob != -1) pendStillAlive2 = _obs[_pendBearAifob].State == 4;
                    if (pendStillAlive2)
                    {
                        var obRef2 = _obs[_pendBearAifob];
                        obRef2.State = 0;
                        obRef2.OrigState = 0;
                        obRef2.EligibleK = -1;
                        _pendBearAifob = -1;
                    }
                    else
                    {
                        _pendBearAifob = -1;
                    }
                    if (!pendStillAlive2 && _lastSWHidx >= 0)
                    {
                        int lo2 = Math.Min(Math.Min(_lastSWHidx, k), _swlIdx);
                        int hi2 = Math.Max(Math.Max(_lastSWHidx, k), _swlIdx);
                        TryCreateIFVGs(lo2, hi2, false, k);
                        _fvgBearScanUpto = hi2;
                        TryCreateIVIs(lo2, hi2, false, k);
                        _viBearScanUpto = hi2;
                        if (!ExistsAifobInRange(lo2, hi2, false))
                        {
                            int best2 = -1;
                            for (int x = lo2; x <= hi2; x++)
                            {
                                double cX = _C[x], oX = _O[x];
                                bool okB2 = false;
                                if (cX > oX) { if (best2 == -1) okB2 = true; else okB2 = cX > _C[best2]; }
                                if (okB2) best2 = x;
                            }
                            if (best2 != -1 && !CandleClaimed(best2, false))
                            {
                                double oB = _O[best2], cB = _C[best2];
                                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive2 = false;
                    if (_pendBearAirb != -1) pendRbStillAlive2 = _rbs[_pendBearAirb].State == 4;
                    if (pendRbStillAlive2)
                    {
                        var rbRef2 = _rbs[_pendBearAirb];
                        rbRef2.State = 0;
                        rbRef2.Origin = 0;
                        rbRef2.EligibleK = -1;
                        _pendBearAirb = -1;
                    }
                    else
                    {
                        _pendBearAirb = -1;
                    }
                    if (!pendRbStillAlive2 && _lastSWHidx >= 0)
                    {
                        int rbLo2 = Math.Min(Math.Min(_lastSWHidx, k), _swlIdx);
                        int rbHi2 = Math.Max(Math.Max(_lastSWHidx, k), _swlIdx);
                        if (!ExistsAirbInRange(rbLo2, rbHi2, false) && !SwingClaimed(_lastSWHidx, false))
                            AddRBFromSwing(_lastSWHidx, true, k, 0);
                    }

                    _haveSWL = false;
                    swlCons = true;
                }
            }
            else
            {
                // --- BULLISH bar: low first -> SWL break first ---
                if (_haveSWL && _L[k] < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1) { _regime = 2; AddMss(k, _swlIdx, _swlPrice, false); }

                    bool pendStillAlive3 = false;
                    if (_pendBearAifob != -1) pendStillAlive3 = _obs[_pendBearAifob].State == 4;
                    if (pendStillAlive3)
                    {
                        var obRef3 = _obs[_pendBearAifob];
                        obRef3.State = 0;
                        obRef3.OrigState = 0;
                        obRef3.EligibleK = -1;
                        _pendBearAifob = -1;
                    }
                    else
                    {
                        _pendBearAifob = -1;
                    }
                    if (!pendStillAlive3 && _lastSWHidx >= 0)
                    {
                        int lo3 = Math.Min(Math.Min(_lastSWHidx, k), _swlIdx);
                        int hi3 = Math.Max(Math.Max(_lastSWHidx, k), _swlIdx);
                        TryCreateIFVGs(lo3, hi3, false, k);
                        _fvgBearScanUpto = hi3;
                        TryCreateIVIs(lo3, hi3, false, k);
                        _viBearScanUpto = hi3;
                        if (!ExistsAifobInRange(lo3, hi3, false))
                        {
                            int best3 = -1;
                            for (int x = lo3; x <= hi3; x++)
                            {
                                double cX = _C[x], oX = _O[x];
                                bool okB3 = false;
                                if (cX > oX) { if (best3 == -1) okB3 = true; else okB3 = cX > _C[best3]; }
                                if (okB3) best3 = x;
                            }
                            if (best3 != -1 && !CandleClaimed(best3, false))
                            {
                                double oB = _O[best3], cB = _C[best3];
                                AddOB(best3, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive3 = false;
                    if (_pendBearAirb != -1) pendRbStillAlive3 = _rbs[_pendBearAirb].State == 4;
                    if (pendRbStillAlive3)
                    {
                        var rbRef3 = _rbs[_pendBearAirb];
                        rbRef3.State = 0;
                        rbRef3.Origin = 0;
                        rbRef3.EligibleK = -1;
                        _pendBearAirb = -1;
                    }
                    else
                    {
                        _pendBearAirb = -1;
                    }
                    if (!pendRbStillAlive3 && _lastSWHidx >= 0)
                    {
                        int rbLo3 = Math.Min(Math.Min(_lastSWHidx, k), _swlIdx);
                        int rbHi3 = Math.Max(Math.Max(_lastSWHidx, k), _swlIdx);
                        if (!ExistsAirbInRange(rbLo3, rbHi3, false) && !SwingClaimed(_lastSWHidx, false))
                            AddRBFromSwing(_lastSWHidx, true, k, 0);
                    }

                    _haveSWL = false;
                    swlCons = true;
                }

                // MID-ARM
                int peek3 = _ei;
                while (peek3 < evTotal)
                {
                    var pEv3 = _events[peek3];
                    if (pEv3.ConfirmIdx != k) break;
                    if (pEv3.Kind == 0)
                    {
                        _haveSWH = true;
                        _swhPrice = pEv3.Price;
                        _swhIdx = pEv3.SwingIdx;
                        _pendBullAifob = -1;
                        _pendBullAirb = -1;
                        TryBearAOB(prevReg, aobSWLi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBearAFVG(prevReg, aobSWLi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBearARB(prevReg, aobSWLi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBearAVI(prevReg, aobSWLi, pEv3.SwingIdx, pEv3.Price, k);
                        if (_pendBearAifob == -1)
                        {
                            int r4 = TryBearAIFOB(prevReg, _haveSWL, aobSWLi, _lastSWHidx, pEv3.SwingIdx, k);
                            if (r4 != -1) _pendBearAifob = r4;
                        }
                        if (_pendBearAirb == -1)
                        {
                            int rr4 = TryBearAIRB(prevReg, _haveSWL, aobSWLi, _lastSWHidx, pEv3.SwingIdx, k);
                            if (rr4 != -1) _pendBearAirb = rr4;
                        }
                    }
                    else
                    {
                        _haveSWL = true;
                        _swlPrice = pEv3.Price;
                        _swlIdx = pEv3.SwingIdx;
                        _pendBearAifob = -1;
                        _pendBearAirb = -1;
                        TryBullAOB(prevReg, aobSWHi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBullAFVG(prevReg, aobSWHi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBullARB(prevReg, aobSWHi, pEv3.SwingIdx, pEv3.Price, k);
                        TryBullAVI(prevReg, aobSWHi, pEv3.SwingIdx, pEv3.Price, k);
                        if (_pendBullAifob == -1)
                        {
                            int r5 = TryBullAIFOB(prevReg, _haveSWH, aobSWHi, _lastSWLidx, pEv3.SwingIdx, k);
                            if (r5 != -1) _pendBullAifob = r5;
                        }
                        if (_pendBullAirb == -1)
                        {
                            int rr5 = TryBullAIRB(prevReg, _haveSWH, aobSWHi, _lastSWLidx, pEv3.SwingIdx, k);
                            if (rr5 != -1) _pendBullAirb = rr5;
                        }
                    }
                    peek3++;
                }

                // Second break: SWH
                if (_haveSWH && _H[k] > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2) { _regime = 1; AddMss(k, _swhIdx, _swhPrice, true); }

                    bool pendStillAlive4 = false;
                    if (_pendBullAifob != -1) pendStillAlive4 = _obs[_pendBullAifob].State == 4;
                    if (pendStillAlive4)
                    {
                        var obRef4 = _obs[_pendBullAifob];
                        obRef4.State = 0;
                        obRef4.OrigState = 0;
                        obRef4.EligibleK = -1;
                        _pendBullAifob = -1;
                    }
                    else
                    {
                        _pendBullAifob = -1;
                    }
                    if (!pendStillAlive4 && _lastSWLidx >= 0)
                    {
                        int lo4 = Math.Min(Math.Min(_lastSWLidx, k), _swhIdx);
                        int hi4 = Math.Max(Math.Max(_lastSWLidx, k), _swhIdx);
                        TryCreateIFVGs(lo4, hi4, true, k);
                        _fvgBullScanUpto = hi4;
                        TryCreateIVIs(lo4, hi4, true, k);
                        _viBullScanUpto = hi4;
                        if (!ExistsAifobInRange(lo4, hi4, true))
                        {
                            int best4 = -1;
                            for (int x = lo4; x <= hi4; x++)
                            {
                                double cX = _C[x], oX = _O[x];
                                bool okB4 = false;
                                if (cX < oX) { if (best4 == -1) okB4 = true; else okB4 = cX < _C[best4]; }
                                if (okB4) best4 = x;
                            }
                            if (best4 != -1 && !CandleClaimed(best4, true))
                            {
                                double oB = _O[best4], cB = _C[best4];
                                AddOB(best4, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive4 = false;
                    if (_pendBullAirb != -1) pendRbStillAlive4 = _rbs[_pendBullAirb].State == 4;
                    if (pendRbStillAlive4)
                    {
                        var rbRef4 = _rbs[_pendBullAirb];
                        rbRef4.State = 0;
                        rbRef4.Origin = 0;
                        rbRef4.EligibleK = -1;
                        _pendBullAirb = -1;
                    }
                    else
                    {
                        _pendBullAirb = -1;
                    }
                    if (!pendRbStillAlive4 && _lastSWLidx >= 0)
                    {
                        int rbLo4 = Math.Min(Math.Min(_lastSWLidx, k), _swhIdx);
                        int rbHi4 = Math.Max(Math.Max(_lastSWLidx, k), _swhIdx);
                        if (!ExistsAirbInRange(rbLo4, rbHi4, true) && !SwingClaimed(_lastSWLidx, true))
                            AddRBFromSwing(_lastSWLidx, false, k, 0);
                    }

                    _haveSWH = false;
                    swhCons = true;
                }
            }

            // STEP 1b: continuous IFVG scan (every bar the regime persists)
            if (_regime == 1 && k >= 2 && k > _fvgBullScanUpto)
            {
                double h1c = _H[k - 2], l3c = _L[k];
                if (h1c < l3c) AddFVG(k - 2, h1c, l3c, true, k, 0);
                _fvgBullScanUpto = k;
            }
            if (_regime == 2 && k >= 2 && k > _fvgBearScanUpto)
            {
                double l1c = _L[k - 2], h3c = _H[k];
                if (l1c > h3c) AddFVG(k - 2, h3c, l1c, false, k, 0);
                _fvgBearScanUpto = k;
            }

            // STEP 1c: continuous IVI scan
            if (_regime == 1 && k >= 1 && k > _viBullScanUpto)
            {
                double op1c = _O[k - 1], cl1c = _C[k - 1], op2c = _O[k], cl2c = _C[k];
                bool isBull1c = cl1c >= op1c;
                if (cl1c < op2c && cl2c > cl1c && isBull1c)
                    AddVI(k - 1, cl1c, op2c, true, k, 0);
                _viBullScanUpto = k;
            }
            if (_regime == 2 && k >= 1 && k > _viBearScanUpto)
            {
                double op1d = _O[k - 1], cl1d = _C[k - 1], op2d = _O[k], cl2d = _C[k];
                bool isBull1d = cl1d >= op1d;
                if (cl1d > op2d && cl2d < cl1d && !isBull1d)
                    AddVI(k - 1, op2d, cl1d, false, k, 0);
                _viBearScanUpto = k;
            }

            // STEP 2: arm swings (consumed check) + eligibility for all 4 POI types
            while (_ei < evTotal)
            {
                var sEv = _events[_ei];
                if (sEv.ConfirmIdx != k) break;
                if (sEv.Kind == 0)
                {
                    if (!swhCons)
                    {
                        _haveSWH = true;
                        _swhPrice = sEv.Price;
                        _swhIdx = sEv.SwingIdx;
                    }
                    _lastSWHidx = sEv.SwingIdx;
                    foreach (var obZ in _obs)
                        if (obZ.Bullish && (obZ.State == 0 || obZ.State == 4) && obZ.EligibleK == -1 && k > obZ.TriggerK)
                            obZ.EligibleK = k;
                    foreach (var fvgZ in _fvgs)
                        if (fvgZ.Bullish && fvgZ.State == 0 && fvgZ.EligibleK == -1 && k > fvgZ.TriggerK)
                            fvgZ.EligibleK = k;
                    foreach (var rbZ in _rbs)
                        if (rbZ.Bullish && (rbZ.State == 0 || rbZ.State == 4) && rbZ.EligibleK == -1 && k > rbZ.TriggerK)
                            rbZ.EligibleK = k;
                    foreach (var viZ in _vis)
                        if (viZ.Bullish && viZ.State == 0 && viZ.EligibleK == -1 && k > viZ.TriggerK)
                            viZ.EligibleK = k;
                }
                else
                {
                    if (!swlCons)
                    {
                        _haveSWL = true;
                        _swlPrice = sEv.Price;
                        _swlIdx = sEv.SwingIdx;
                    }
                    _lastSWLidx = sEv.SwingIdx;
                    foreach (var obZ2 in _obs)
                        if (!obZ2.Bullish && (obZ2.State == 0 || obZ2.State == 4) && obZ2.EligibleK == -1 && k > obZ2.TriggerK)
                            obZ2.EligibleK = k;
                    foreach (var fvgZ2 in _fvgs)
                        if (!fvgZ2.Bullish && fvgZ2.State == 0 && fvgZ2.EligibleK == -1 && k > fvgZ2.TriggerK)
                            fvgZ2.EligibleK = k;
                    foreach (var rbZ2 in _rbs)
                        if (!rbZ2.Bullish && (rbZ2.State == 0 || rbZ2.State == 4) && rbZ2.EligibleK == -1 && k > rbZ2.TriggerK)
                            rbZ2.EligibleK = k;
                    foreach (var viZ2 in _vis)
                        if (!viZ2.Bullish && viZ2.State == 0 && viZ2.EligibleK == -1 && k > viZ2.TriggerK)
                            viZ2.EligibleK = k;
                }
                _ei++;
            }

            double hK = _H[k];
            double lK = _L[k];

            // STEP 3: OB lifecycle at this candle
            foreach (var obZ3 in _obs)
            {
                if (obZ3.State == 3) continue;
                double zb = obZ3.Zb, zt = obZ3.Zt;
                bool bull = obZ3.Bullish;

                if (obZ3.EligibleK != -1 && k >= obZ3.EligibleK)
                {
                    if (hK >= zb && lK <= zt)
                    {
                        obZ3.PreSpentState = obZ3.State;
                        obZ3.State = 3;
                        obZ3.StopK = k;
                        continue;
                    }
                }

                if ((obZ3.State == 0 || obZ3.State == 1 || obZ3.State == 4) && obZ3.EligibleK != -1)
                {
                    bool isIFOB = obZ3.OrigState != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = _events[e2];
                        if (stEv.ConfirmIdx != k) continue;
                        bool stranded = false;
                        if (isIFOB)
                        {
                            if (bull && stEv.Kind == 1 && stEv.Price > zt) stranded = true;
                            if (!bull && stEv.Kind == 0 && stEv.Price < zb) stranded = true;
                        }
                        else
                        {
                            if (bull && stEv.Kind == 0 && stEv.Price < zb) stranded = true;
                            if (!bull && stEv.Kind == 1 && stEv.Price > zt) stranded = true;
                        }
                        if (stranded) { obZ3.State = 2; break; }
                    }
                }
            }

            // STEP 3b: IFVG/AFVG lifecycle
            foreach (var fvgZ3 in _fvgs)
            {
                if (fvgZ3.State == 3) continue;
                double zbf = fvgZ3.Zb, ztf = fvgZ3.Zt;
                bool bullf = fvgZ3.Bullish;

                if (fvgZ3.EligibleK != -1 && k >= fvgZ3.EligibleK)
                {
                    if (hK >= zbf && lK <= ztf)
                    {
                        fvgZ3.PreSpentState = fvgZ3.State;
                        fvgZ3.State = 3;
                        fvgZ3.StopK = k;
                        continue;
                    }
                }

                // CLOSE-THROUGH INVALIDATION -- IFVG only (origin 0).
                if (fvgZ3.Origin != 1 && fvgZ3.State == 0 && fvgZ3.EligibleK != -1 && k >= fvgZ3.EligibleK)
                {
                    double cK = _C[k];
                    bool closedThrough = bullf ? cK < zbf : cK > ztf;
                    if (closedThrough)
                    {
                        fvgZ3.PreSpentState = fvgZ3.State;
                        fvgZ3.State = 3;
                        fvgZ3.StopK = k;
                        continue;
                    }
                }

                if ((fvgZ3.State == 0 || fvgZ3.State == 1) && fvgZ3.EligibleK != -1)
                {
                    bool isIFVG = fvgZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = _events[e2];
                        if (stEv.ConfirmIdx != k) continue;
                        bool strandedF = false;
                        if (isIFVG)
                        {
                            if (bullf && stEv.Kind == 1 && stEv.Price > ztf) strandedF = true;
                            if (!bullf && stEv.Kind == 0 && stEv.Price < zbf) strandedF = true;
                        }
                        else
                        {
                            if (bullf && stEv.Kind == 0 && stEv.Price < zbf) strandedF = true;
                            if (!bullf && stEv.Kind == 1 && stEv.Price > ztf) strandedF = true;
                        }
                        if (strandedF) { fvgZ3.State = 2; break; }
                    }
                }
            }

            // STEP 3c: RB lifecycle -- IMPACT + STRANDING only (no close-through)
            foreach (var rbZ3 in _rbs)
            {
                if (rbZ3.State == 3) continue;
                double zbr = rbZ3.Zb, ztr = rbZ3.Zt;
                bool bullr = rbZ3.Bullish;

                if (rbZ3.EligibleK != -1 && k >= rbZ3.EligibleK)
                {
                    if (hK >= zbr && lK <= ztr)
                    {
                        rbZ3.PreSpentState = rbZ3.State;
                        rbZ3.State = 3;
                        rbZ3.StopK = k;
                        continue;
                    }
                }

                // AIRB (state==4, origin==4 while pending) falls into the
                // far-side/IRB-style bucket via origin!=1, same as OB treats
                // AIFOB as far-side/IFOB-style.
                if ((rbZ3.State == 0 || rbZ3.State == 1 || rbZ3.State == 4) && rbZ3.EligibleK != -1)
                {
                    bool isIRB = rbZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = _events[e2];
                        if (stEv.ConfirmIdx != k) continue;
                        bool strandedR = false;
                        if (isIRB)
                        {
                            if (bullr && stEv.Kind == 1 && stEv.Price > ztr) strandedR = true;
                            if (!bullr && stEv.Kind == 0 && stEv.Price < zbr) strandedR = true;
                        }
                        else
                        {
                            // ARB's bull/bear tag is RAW WICK TYPE, opposite of
                            // AFVG's hunt-direction tag -- see RbZone.Bullish
                            // comment. Near-side check is the OPPOSITE kind/side
                            // pairing from AFVG's formula, not a literal copy.
                            if (bullr && stEv.Kind == 1 && stEv.Price > ztr) strandedR = true;
                            if (!bullr && stEv.Kind == 0 && stEv.Price < zbr) strandedR = true;
                        }
                        if (strandedR) { rbZ3.State = 2; break; }
                    }
                }
            }

            // STEP 3d: IVI/AVI lifecycle -- close-through restricted to IVI only
            foreach (var viZ3 in _vis)
            {
                if (viZ3.State == 3) continue;
                double zbv = viZ3.Zb, ztv = viZ3.Zt;
                bool bullv = viZ3.Bullish;

                if (viZ3.EligibleK != -1 && k >= viZ3.EligibleK)
                {
                    if (hK >= zbv && lK <= ztv)
                    {
                        viZ3.PreSpentState = viZ3.State;
                        viZ3.State = 3;
                        viZ3.StopK = k;
                        continue;
                    }
                }

                if (viZ3.Origin != 1 && viZ3.State == 0 && viZ3.EligibleK != -1 && k >= viZ3.EligibleK)
                {
                    double cKv = _C[k];
                    bool closedThroughV = bullv ? cKv < zbv : cKv > ztv;
                    if (closedThroughV)
                    {
                        viZ3.PreSpentState = viZ3.State;
                        viZ3.State = 3;
                        viZ3.StopK = k;
                        continue;
                    }
                }

                if ((viZ3.State == 0 || viZ3.State == 1) && viZ3.EligibleK != -1)
                {
                    bool isIVI = viZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = _events[e2];
                        if (stEv.ConfirmIdx != k) continue;
                        bool strandedV = false;
                        if (isIVI)
                        {
                            if (bullv && stEv.Kind == 1 && stEv.Price > ztv) strandedV = true;
                            if (!bullv && stEv.Kind == 0 && stEv.Price < zbv) strandedV = true;
                        }
                        else
                        {
                            if (bullv && stEv.Kind == 0 && stEv.Price < zbv) strandedV = true;
                            if (!bullv && stEv.Kind == 1 && stEv.Price > ztv) strandedV = true;
                        }
                        if (strandedV) { viZ3.State = 2; break; }
                    }
                }
            }
        }

        // ===================== HELPER FUNCTIONS =====================
        private void AddSH(int idx)
        {
            int sz = _swHighs.Count;
            bool doPush = sz == 0 || _swHighs[sz - 1] != idx;
            if (doPush) _swHighs.Add(idx);
        }

        private void AddSL(int idx)
        {
            int sz = _swLows.Count;
            bool doPush = sz == 0 || _swLows[sz - 1] != idx;
            if (doPush) _swLows.Add(idx);
        }

        private void AddEv(int cIdx, int kind, int sIdx, double pr)
        {
            _events.Add(new SwEv { ConfirmIdx = cIdx, Kind = kind, SwingIdx = sIdx, Price = pr });
        }

        private void AddMss(int aIdx, int bIdx, double pr, bool up)
        {
            _msses.Add(new MssEv { AtIdx = aIdx, BrokenIdx = bIdx, Price = pr, ToUp = up });
        }

        private void AddOB(int cand, double zb, double zt, bool bull, int tK, int st)
        {
            // AIFOB (st==4) gets no immediate eligibility -- only AOB (st==1) does.
            int eK = (st == 1) ? tK : -1;
            _obs.Add(new ObZone { Candle = cand, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, OrigState = st, PreSpentState = st });
        }

        private bool CandleClaimed(int cand, bool bull)
        {
            foreach (var zz in _obs)
                if (zz.Candle == cand && zz.Bullish == bull) return true;
            return false;
        }

        private bool ExistsAifobInRange(int lo, int hi, bool bull)
        {
            foreach (var zz in _obs)
                if (zz.OrigState == 4 && zz.Bullish == bull && zz.Candle >= lo && zz.Candle <= hi) return true;
            return false;
        }

        private void AddFVG(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            _fvgs.Add(new FvgZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        private void TryCreateIFVGs(int lo, int hi, bool bullish, int triggerK)
        {
            if (hi < lo + 2) return;
            for (int c3 = lo + 2; c3 <= hi; c3++)
            {
                int c1 = c3 - 2;
                if (bullish)
                {
                    double h1 = _H[c1], l3 = _L[c3];
                    if (h1 < l3) AddFVG(c1, h1, l3, true, triggerK, 0);
                }
                else
                {
                    double l1 = _L[c1], h3 = _H[c3];
                    if (l1 > h3) AddFVG(c1, h3, l1, false, triggerK, 0);
                }
            }
        }

        private void TryCreateAFVGs(int lo, int hi, bool bullish, int triggerK, double guardPrice)
        {
            if (hi < lo + 2) return;
            for (int c3 = lo + 2; c3 <= hi; c3++)
            {
                int c1 = c3 - 2;
                if (bullish)
                {
                    double l1 = _L[c1], h3 = _H[c3];
                    if (l1 > h3)
                    {
                        double l3 = _L[c3];
                        if (l1 > guardPrice && l3 > guardPrice)
                            AddFVG(c1, h3, l1, true, triggerK, 1);
                    }
                }
                else
                {
                    double h1 = _H[c1], l3 = _L[c3];
                    if (h1 < l3)
                    {
                        double h3 = _H[c3];
                        if (h1 < guardPrice && h3 < guardPrice)
                            AddFVG(c1, h1, l3, false, triggerK, 1);
                    }
                }
            }
        }

        // --- AOB HUNT: Bullish ---
        private void TryBullAOB(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = _H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++)
                if (_H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, newSwlI));
            int hi2 = Math.Max(aobSWHi - 1, newSwlI);
            int best2 = -1;
            for (int x = lo2; x <= hi2; x++)
            {
                if (x < 0) continue;
                double cX = _C[x], oX = _O[x];
                bool okB2 = false;
                if (cX > oX) { if (best2 == -1) okB2 = true; else okB2 = cX > _C[best2]; }
                if (okB2) best2 = x;
            }
            if (best2 == -1) return;
            if (_L[best2] > newSwlP)
            {
                double oB = _O[best2], cB = _C[best2];
                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 1);
            }
        }

        // --- AOB HUNT: Bearish ---
        private void TryBearAOB(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = _L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++)
                if (_L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, newSwhI));
            int hi2 = Math.Max(aobSWLi - 1, newSwhI);
            int best2 = -1;
            for (int x = lo2; x <= hi2; x++)
            {
                if (x < 0) continue;
                double cX = _C[x], oX = _O[x];
                bool okB2 = false;
                if (cX < oX) { if (best2 == -1) okB2 = true; else okB2 = cX < _C[best2]; }
                if (okB2) best2 = x;
            }
            if (best2 == -1) return;
            if (_H[best2] < newSwhP)
            {
                double oB = _O[best2], cB = _C[best2];
                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 1);
            }
        }

        // --- AFVG HUNT: Bullish -- see Pine source comment for the swlExt
        // range-extension reasoning (b4b13d9/d99a0de).
        private void TryBullAFVG(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = _H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++)
                if (_H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int swlExt = (newSwlI + 1 <= k - 1) ? newSwlI + 1 : newSwlI;
            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, swlExt));
            int hi2 = Math.Max(aobSWHi - 1, swlExt);
            TryCreateAFVGs(lo2, hi2, true, k, newSwlP);
        }

        // --- AFVG HUNT: Bearish ---
        private void TryBearAFVG(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = _L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++)
                if (_L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int swhExt = (newSwhI + 1 <= k - 1) ? newSwhI + 1 : newSwhI;
            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, swhExt));
            int hi2 = Math.Max(aobSWLi - 1, swhExt);
            TryCreateAFVGs(lo2, hi2, false, k, newSwhP);
        }

        private void AddRB(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            _rbs.Add(new RbZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        // Builds an RB zone directly from a known swing-pivot candle's wick.
        // isHigh=true: swing high (top=wick tip, bottom=closer body edge, bull=false).
        // isHigh=false: swing low (mirrored, bull=true).
        private void AddRBFromSwing(int idx, bool isHigh, int tK, int st)
        {
            if (isHigh)
                AddRB(idx, Math.Max(_O[idx], _C[idx]), _H[idx], false, tK, st);
            else
                AddRB(idx, _L[idx], Math.Min(_O[idx], _C[idx]), true, tK, st);
        }

        // --- ARB HUNT: Bullish -- zone is the armed swing high's own wick (no scan) ---
        private void TryBullARB(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = _H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++)
                if (_H[v] >= armedSwhPrice) refViolated = true;
            if (!refViolated) AddRBFromSwing(aobSWHi, true, k, 1);
        }

        // --- ARB HUNT: Bearish ---
        private void TryBearARB(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = _L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++)
                if (_L[v] <= armedSwlPrice) refViolated = true;
            if (!refViolated) AddRBFromSwing(aobSWLi, false, k, 1);
        }

        // Is this exact swing already the anchor of an existing RB zone
        // (any state, alive or dead)? Mirrors OB's CandleClaimed.
        private bool SwingClaimed(int idx, bool bull)
        {
            foreach (var zz in _rbs)
                if (zz.LeftIdx == idx && zz.Bullish == bull) return true;
            return false;
        }

        // Mirrors OB's ExistsAifobInRange -- is there already a pending AIRB
        // (state==4) anchored inside this range?
        private bool ExistsAirbInRange(int lo, int hi, bool bull)
        {
            foreach (var zz in _rbs)
                if (zz.State == 4 && zz.Bullish == bull && zz.LeftIdx >= lo && zz.LeftIdx <= hi) return true;
            return false;
        }

        // --- AIRB HUNT: Bullish -- mirrors TryBullAIFOB's MID-ARM trigger and
        // gates one-for-one; zone is pLastSWLi's own wick, no scanning.
        // Returns rbs[] index or -1, for the caller to track via _pendBullAirb.
        private int TryBullAIRB(int pReg, bool pHaveSWH, int pSwhI, int pLastSWLi, int newSwlI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt = _L[k] < _L[newSwlI];
            if (pReg == 1 && pHaveSWH && pSwhI >= 0 && pLastSWLi >= 0 && !alreadyBrokeIt)
            {
                if (!SwingClaimed(pLastSWLi, true))
                {
                    AddRBFromSwing(pLastSWLi, false, k, 4);
                    result = _rbs.Count - 1;
                }
            }
            return result;
        }

        // --- AIRB HUNT: Bearish -- mirrors TryBearAIFOB ---
        private int TryBearAIRB(int pReg, bool pHaveSWL, int pSwlI, int pLastSWHi, int newSwhI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt2 = _H[k] > _H[newSwhI];
            if (pReg == 2 && pHaveSWL && pSwlI >= 0 && pLastSWHi >= 0 && !alreadyBrokeIt2)
            {
                if (!SwingClaimed(pLastSWHi, false))
                {
                    AddRBFromSwing(pLastSWHi, true, k, 4);
                    result = _rbs.Count - 1;
                }
            }
            return result;
        }

        private void AddVI(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            _vis.Add(new ViZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        // Scans [lo,hi] for EVERY qualifying 2-candle gap. Shape-based (matches
        // IFVG's convention). Guards: same-candle fill + candle1-direction.
        private void TryCreateIVIs(int lo, int hi, bool bullish, int triggerK)
        {
            if (hi < lo + 1) return;
            for (int c2 = lo + 1; c2 <= hi; c2++)
            {
                int c1 = c2 - 1;
                double op1 = _O[c1], cl1 = _C[c1], op2 = _O[c2], cl2 = _C[c2];
                bool isBull1 = cl1 >= op1;
                if (bullish)
                {
                    if (cl1 < op2 && cl2 > cl1 && isBull1)
                        AddVI(c1, cl1, op2, true, triggerK, 0);
                }
                else
                {
                    if (cl1 > op2 && cl2 < cl1 && !isBull1)
                        AddVI(c1, op2, cl1, false, triggerK, 0);
                }
            }
        }

        // Scans [lo,hi] for EVERY qualifying 2-candle gap left by the
        // retracement leg's OWN direction (mirrors AFVG). Guard checks WICKS.
        private void TryCreateAVIs(int lo, int hi, bool bullish, int triggerK, double guardPrice)
        {
            if (hi < lo + 1) return;
            for (int c2 = lo + 1; c2 <= hi; c2++)
            {
                int c1 = c2 - 1;
                double op1 = _O[c1], cl1 = _C[c1], op2 = _O[c2], cl2 = _C[c2];
                bool isBull1 = cl1 >= op1;
                if (bullish)
                {
                    if (cl1 > op2 && cl2 < cl1 && !isBull1)
                    {
                        double l1 = _L[c1], l2 = _L[c2];
                        if (l1 > guardPrice && l2 > guardPrice)
                            AddVI(c1, op2, cl1, true, triggerK, 1);
                    }
                }
                else
                {
                    if (cl1 < op2 && cl2 > cl1 && isBull1)
                    {
                        double h1 = _H[c1], h2 = _H[c2];
                        if (h1 < guardPrice && h2 < guardPrice)
                            AddVI(c1, cl1, op2, false, triggerK, 1);
                    }
                }
            }
        }

        // --- AVI HUNT: Bullish -- mirrors TryBullAFVG's range + guard one-for-one ---
        private void TryBullAVI(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = _H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++)
                if (_H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int swlExt = (newSwlI + 1 <= k - 1) ? newSwlI + 1 : newSwlI;
            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, swlExt));
            int hi2 = Math.Max(aobSWHi - 1, swlExt);
            TryCreateAVIs(lo2, hi2, true, k, newSwlP);
        }

        // --- AVI HUNT: Bearish -- mirrors TryBearAFVG ---
        private void TryBearAVI(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = _L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++)
                if (_L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int swhExt = (newSwhI + 1 <= k - 1) ? newSwhI + 1 : newSwhI;
            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, swhExt));
            int hi2 = Math.Max(aobSWLi - 1, swhExt);
            TryCreateAVIs(lo2, hi2, false, k, newSwhP);
        }

        // --- AIFOB HUNT: Bullish (returns obs[] index or -1) ---
        private int TryBullAIFOB(int pReg, bool pHaveSWH, int pSwhI, int pLastSWLi, int newSwlI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt = _L[k] < _L[newSwlI];
            if (pReg == 1 && pHaveSWH && pSwhI >= 0 && pLastSWLi >= 0 && !alreadyBrokeIt)
            {
                int lo = Math.Max(0, Math.Min(Math.Min(pLastSWLi, newSwlI), pSwhI - 1));
                int hi = Math.Max(Math.Max(pLastSWLi, newSwlI), pSwhI - 1);
                int best = -1;
                for (int x = lo; x <= hi; x++)
                {
                    if (x < 0) continue;
                    double cX = _C[x], oX = _O[x];
                    bool okB = false;
                    if (cX < oX) { if (best == -1) okB = true; else okB = cX < _C[best]; }
                    if (okB) best = x;
                }
                if (best != -1 && !CandleClaimed(best, true))
                {
                    double oB = _O[best], cB = _C[best];
                    AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 4);
                    result = _obs.Count - 1;
                }
            }
            return result;
        }

        // --- AIFOB HUNT: Bearish (returns obs[] index or -1) ---
        private int TryBearAIFOB(int pReg, bool pHaveSWL, int pSwlI, int pLastSWHi, int newSwhI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt2 = _H[k] > _H[newSwhI];
            if (pReg == 2 && pHaveSWL && pSwlI >= 0 && pLastSWHi >= 0 && !alreadyBrokeIt2)
            {
                int lo = Math.Max(0, Math.Min(Math.Min(pLastSWHi, newSwhI), pSwlI - 1));
                int hi = Math.Max(Math.Max(pLastSWHi, newSwhI), pSwlI - 1);
                int best = -1;
                for (int x = lo; x <= hi; x++)
                {
                    if (x < 0) continue;
                    double cX = _C[x], oX = _O[x];
                    bool okB = false;
                    if (cX > oX) { if (best == -1) okB = true; else okB = cX > _C[best]; }
                    if (okB) best = x;
                }
                if (best != -1 && !CandleClaimed(best, false))
                {
                    double oB = _O[best], cB = _C[best];
                    AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 4);
                    result = _obs.Count - 1;
                }
            }
            return result;
        }

        // ===================== DRAWING =====================
        private void RedrawAll()
        {
            foreach (var name in _drawnObjectNames)
                Chart.RemoveObject(name);
            _drawnObjectNames.Clear();

            int nArr = _O.Count;
            if (nArr < 2) return;

            DateTime dispFrom = UseDisplayFrom
                ? InpDisplayFrom
                : Bars.OpenTimes[Bars.Count - 1].AddDays(-InpMonthsBack * 30);

            // OOB/OFVG/ORB/OVI are never traded off 5m/1h/4h (see
            // docs/trading_logic.md's cascade), so hide the clutter there.
            bool hideOOBHere = TimeFrame == TimeFrame.Minute5 || TimeFrame == TimeFrame.Hour || TimeFrame == TimeFrame.Hour4;

            int extIndex = (Bars.Count - 1) + 50;

            // --- Swing HIGHS: blue up arrow ---
            int shSz = _swHighs.Count;
            int shStart = Math.Max(0, shSz - InpMaxLabelsPerCategory);
            for (int s = shStart; s < shSz; s++)
            {
                int idx = _swHighs[s];
                if (idx < 0 || idx >= nArr) continue;
                if (_BT[idx] < dispFrom) continue;
                DrawLabel("SH" + idx, "▲", idx, _H[idx], Color.Blue);
            }

            // --- Swing LOWS: black down arrow ---
            int slSz = _swLows.Count;
            int slStart = Math.Max(0, slSz - InpMaxLabelsPerCategory);
            for (int s = slStart; s < slSz; s++)
            {
                int idx = _swLows[s];
                if (idx < 0 || idx >= nArr) continue;
                if (_BT[idx] < dispFrom) continue;
                double gap = _atr.Result[idx] * InpSwingLowGapATR;
                DrawLabel("SL" + idx, "▼", idx, _L[idx] - gap, Color.Black);
            }

            // --- MSS flips: cross mark at broken swing's location ---
            int mssSz = _msses.Count;
            int mssStart = Math.Max(0, mssSz - InpMaxLabelsPerCategory);
            for (int m = mssStart; m < mssSz; m++)
            {
                var mEv = _msses[m];
                int bIdx = mEv.BrokenIdx;
                if (bIdx < 0 || bIdx >= nArr) continue;
                if (_BT[bIdx] < dispFrom) continue;
                bool isUp = mEv.ToUp;
                double gap = _atr.Result[bIdx] * InpSwingLowGapATR;
                double yP = isUp ? _H[bIdx] : _L[bIdx] - gap;
                Color col = isUp ? Color.Blue : Color.Black;
                DrawLabel("MSS" + m, "✕", bIdx, yP, col);
            }

            // --- OB zones: hollow boxes. IFOB bull=blue, bear=black, AOB=green,
            // OOB=red, AIFOB=orange, SPENT uses PreSpentState color ---
            int obSzD = _obs.Count;
            for (int z = 0; z < obSzD; z++)
            {
                var obD = _obs[z];
                int idx = obD.Candle;
                if (idx < 0 || idx >= nArr) continue;

                if (InpFocusOB > 0)
                {
                    if (obSzD - z != InpFocusOB) continue;
                }
                else
                {
                    if (_BT[idx] < dispFrom) continue;
                }

                int leftIdx = idx;
                int rightIdx = extIndex;
                if (obD.StopK != -1 && obD.StopK < nArr) rightIdx = obD.StopK;

                int dSt = obD.State == 3 ? obD.PreSpentState : obD.State;
                if (dSt == 2 && hideOOBHere) continue;

                Color col;
                if (dSt == 0) col = obD.Bullish ? Color.Blue : Color.Black;
                else if (dSt == 1) col = Color.Green;
                else if (dSt == 2) col = Color.Red;
                else if (dSt == 4) col = Color.Orange;
                else col = obD.Bullish ? Color.Blue : Color.Black;

                DrawHollowBox("OB" + z, leftIdx, obD.Zt, rightIdx, obD.Zb, col, LineStyle.Solid);
            }

            // --- IFVG/AFVG zones: filled box + gray dotted 50% midline.
            // Capped independently per category, by chronological LeftIdx.
            var ifvgLeft = new List<int>();
            var afvgLeft = new List<int>();
            foreach (var fvScan in _fvgs)
            {
                if (fvScan.Origin == 1) afvgLeft.Add(fvScan.LeftIdx);
                else ifvgLeft.Add(fvScan.LeftIdx);
            }
            ifvgLeft.Sort((a, b) => b.CompareTo(a));
            afvgLeft.Sort((a, b) => b.CompareTo(a));
            int ifvgCutoff = ifvgLeft.Count > 0 ? ifvgLeft[Math.Min(InpMaxFvgPerCategory, ifvgLeft.Count) - 1] : int.MaxValue;
            int afvgCutoff = afvgLeft.Count > 0 ? afvgLeft[Math.Min(InpMaxFvgPerCategory, afvgLeft.Count) - 1] : int.MaxValue;

            int fvgSzD = _fvgs.Count;
            for (int zf = 0; zf < fvgSzD; zf++)
            {
                var fvD = _fvgs[zf];
                int idxF = fvD.LeftIdx;
                if (idxF < 0 || idxF >= nArr) continue;
                int catCutoff = fvD.Origin == 1 ? afvgCutoff : ifvgCutoff;
                if (idxF < catCutoff) continue;
                if (_BT[idxF] < dispFrom) continue;

                int dStF = fvD.State == 3 ? fvD.PreSpentState : fvD.State;
                if (dStF == 2 && hideOOBHere) continue;

                int leftTF = idxF;
                int rightTF = extIndex;
                if (fvD.StopK != -1 && fvD.StopK < nArr) rightTF = fvD.StopK;

                Color colF = dStF == 2 ? Color.Red : dStF == 1 ? Color.Green : (fvD.Bullish ? Color.Blue : Color.Black);

                DrawFilledBox("FVG" + zf, leftTF, fvD.Zt, rightTF, fvD.Zb, colF, InpFvgFillTransparency);
                double midY = (fvD.Zt + fvD.Zb) / 2;
                DrawMidline("FVGmid" + zf, leftTF, midY, rightTF, midY);
            }

            // --- RB zones: dashed hollow box, no fill, no midline. IRB
            // blue(bull)/black(bear), ARB green, AIRB orange (pending),
            // ORB red (hidden on 5m/1h/4h like OOB). ---
            var irbLeft = new List<int>();
            var arbLeft = new List<int>();
            foreach (var rbScan in _rbs)
            {
                if (rbScan.Origin == 1) arbLeft.Add(rbScan.LeftIdx);
                else irbLeft.Add(rbScan.LeftIdx);
            }
            irbLeft.Sort((a, b) => b.CompareTo(a));
            arbLeft.Sort((a, b) => b.CompareTo(a));
            int irbCutoff = irbLeft.Count > 0 ? irbLeft[Math.Min(InpMaxRbPerCategory, irbLeft.Count) - 1] : int.MaxValue;
            int arbCutoff = arbLeft.Count > 0 ? arbLeft[Math.Min(InpMaxRbPerCategory, arbLeft.Count) - 1] : int.MaxValue;

            int rbSzD = _rbs.Count;
            for (int zr = 0; zr < rbSzD; zr++)
            {
                var rbD = _rbs[zr];
                int idxR = rbD.LeftIdx;
                if (idxR < 0 || idxR >= nArr) continue;
                int catCutoffR = rbD.Origin == 1 ? arbCutoff : irbCutoff;
                if (idxR < catCutoffR) continue;
                if (_BT[idxR] < dispFrom) continue;

                int dStR = rbD.State == 3 ? rbD.PreSpentState : rbD.State;
                if (dStR == 2 && hideOOBHere) continue;

                int leftTR = idxR;
                int rightTR = extIndex;
                if (rbD.StopK != -1 && rbD.StopK < nArr) rightTR = rbD.StopK;

                Color colR = dStR == 2 ? Color.Red : dStR == 1 ? Color.Green : dStR == 4 ? Color.Orange : (rbD.Bullish ? Color.Blue : Color.Black);

                DrawHollowBox("RB" + zr, leftTR, rbD.Zt, rightTR, rbD.Zb, colR, LineStyle.Lines);
            }

            // --- VI zones: filled box + gray dotted 50% midline, same style as FVG ---
            var iviLeft = new List<int>();
            var aviLeft = new List<int>();
            foreach (var vScan in _vis)
            {
                if (vScan.Origin == 1) aviLeft.Add(vScan.LeftIdx);
                else iviLeft.Add(vScan.LeftIdx);
            }
            iviLeft.Sort((a, b) => b.CompareTo(a));
            aviLeft.Sort((a, b) => b.CompareTo(a));
            int iviCutoff = iviLeft.Count > 0 ? iviLeft[Math.Min(InpMaxViPerCategory, iviLeft.Count) - 1] : int.MaxValue;
            int aviCutoff = aviLeft.Count > 0 ? aviLeft[Math.Min(InpMaxViPerCategory, aviLeft.Count) - 1] : int.MaxValue;

            int viSzD = _vis.Count;
            for (int zv = 0; zv < viSzD; zv++)
            {
                var vD = _vis[zv];
                int idxV = vD.LeftIdx;
                if (idxV < 0 || idxV >= nArr) continue;
                int catCutoffV = vD.Origin == 1 ? aviCutoff : iviCutoff;
                if (idxV < catCutoffV) continue;
                if (_BT[idxV] < dispFrom) continue;

                int dStV = vD.State == 3 ? vD.PreSpentState : vD.State;
                if (dStV == 2 && hideOOBHere) continue;

                int leftTV = idxV;
                int rightTV = extIndex;
                if (vD.StopK != -1 && vD.StopK < nArr) rightTV = vD.StopK;

                Color colV = dStV == 2 ? Color.Red : dStV == 1 ? Color.Green : (vD.Bullish ? Color.Blue : Color.Black);

                DrawFilledBox("VI" + zv, leftTV, vD.Zt, rightTV, vD.Zb, colV, InpViFillTransparency);
                double midYV = (vD.Zt + vD.Zb) / 2;
                DrawMidline("VImid" + zv, leftTV, midYV, rightTV, midYV);
            }
        }

        // --- Drawing primitives ---
        private void DrawLabel(string name, string text, int index, double y, Color color)
        {
            Chart.DrawText(name, text, index, y, color);
            _drawnObjectNames.Add(name);
        }

        private void DrawHollowBox(string name, int index1, double y1, int index2, double y2, Color color, LineStyle style)
        {
            var r = Chart.DrawRectangle(name, index1, y1, index2, y2, color, 1);
            r.IsFilled = false;
            r.LineStyle = style;
            _drawnObjectNames.Add(name);
        }

        // Fill transparency approximated by alpha-blending the same color used
        // for the border (Pine keeps the border opaque and only fades the
        // fill separately -- cAlgo's ChartRectangle exposes a single Color,
        // so this is the closest one-property equivalent; worth a look once
        // this is open in the real cTrader IDE in case a separate fill-color
        // property is actually available there).
        private void DrawFilledBox(string name, int index1, double y1, int index2, double y2, Color borderColor, int transparencyPct)
        {
            var r = Chart.DrawRectangle(name, index1, y1, index2, y2, borderColor, 1);
            r.IsFilled = true;
            int alpha = (int)Math.Round((100 - transparencyPct) / 100.0 * 255.0);
            r.Color = Color.FromArgb(alpha, borderColor.R, borderColor.G, borderColor.B);
            _drawnObjectNames.Add(name);
        }

        private void DrawMidline(string name, int index1, double y1, int index2, double y2)
        {
            Chart.DrawTrendLine(name, index1, y1, index2, y2, Color.Gray, 1, LineStyle.Dots);
            _drawnObjectNames.Add(name);
        }
    }
}
