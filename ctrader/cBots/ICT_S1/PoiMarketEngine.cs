// ICT_S1 — PoiMarketEngine: reusable swing/regime/MSS/POI detection engine.
//
// This is the SAME logic as ctrader/Indicators/ICT_Full_OB_v24.cs's engine
// (itself a faithful port of pine/ICT_Full_OB_v24.pine), lifted out of the
// Indicator class so it can be instantiated independently per timeframe --
// S1 needs three live instances at once (Weekly, H4, M5), each fed its own
// Bars series via MarketData.GetBars(), which an Indicator subclass (tied
// to one chart's own timeframe) cannot do.
//
// KNOWN PLATFORM LIMITATION (flagging per spec deliverable "known platform
// limitations"): cTrader Automate's paste-into-editor workflow does not
// give an Indicator project and a Robot project a shared compiled library
// in the simple case, so this engine is DUPLICATED here rather than
// referenced from the Indicator. The two copies must be kept logically
// identical -- any future fix to the swing/POI/MSS rules must be mirrored
// in both files. A proper shared class-library project (via cTrader's
// local/Visual-Studio development mode) would eliminate this duplication
// risk entirely and is the recommended follow-up once this is running.
//
// No drawing code here -- that's VisualizationManager's job, kept
// separate per the modular architecture (docs/s1_ea_specification.md).

using System;
using System.Collections.Generic;
using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    public class SwEv
    {
        public int ConfirmIdx;
        public int Kind;   // 0=high, 1=low
        public int SwingIdx;
        public double Price;
    }

    public class MssEv
    {
        public int AtIdx;
        public int BrokenIdx;
        public double Price;
        public bool ToUp;
    }

    public class ObZone
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
        // S1 bookkeeping: has this raw zone already been frozen into an
        // S1PoiSnapshot? Prevents re-freezing the same zone on a later scan.
        public string S1SnapshotId;
    }

    public class FvgZone
    {
        public int LeftIdx;
        public double Zb, Zt;
        public bool Bullish;
        public int TriggerK;
        public int EligibleK = -1;
        public int StopK = -1;
        public int State;         // 0=IFVG,1=AFVG,2=OFVG,3=SPENT
        public int Origin;
        public int PreSpentState;
        public string S1SnapshotId;
    }

    public class RbZone
    {
        public int LeftIdx;
        public double Zb, Zt;
        public bool Bullish;      // RAW WICK TYPE, see indicator header
        public int TriggerK;
        public int EligibleK = -1;
        public int StopK = -1;
        public int State;         // 0=IRB,1=ARB,2=ORB,3=SPENT,4=AIRB
        public int Origin;
        public int PreSpentState;
        public string S1SnapshotId;
    }

    public class ViZone
    {
        public int LeftIdx;
        public double Zb, Zt;
        public bool Bullish;
        public int TriggerK;
        public int EligibleK = -1;
        public int StopK = -1;
        public int State;         // 0=IVI,1=AVI,2=OVI,3=SPENT
        public int Origin;
        public int PreSpentState;
        public string S1SnapshotId;
    }

    public class PoiMarketEngine
    {
        public readonly string Label; // "Weekly" / "H4" / "M5" -- for logging only
        private readonly Bars _bars;

        public readonly List<SwEv> Events = new List<SwEv>();
        public readonly List<MssEv> Msses = new List<MssEv>();
        public readonly List<ObZone> Obs = new List<ObZone>();
        public readonly List<FvgZone> Fvgs = new List<FvgZone>();
        public readonly List<RbZone> Rbs = new List<RbZone>();
        public readonly List<ViZone> Vis = new List<ViZone>();
        public readonly List<int> SwHighs = new List<int>();
        public readonly List<int> SwLows = new List<int>();

        // OHLC + time storage, absolute indexing oldest=0 -- index equals
        // the source Bars index one-for-one (every bar processed in order
        // from index 0, no gaps).
        public readonly List<double> O = new List<double>();
        public readonly List<double> H = new List<double>();
        public readonly List<double> L = new List<double>();
        public readonly List<double> C = new List<double>();
        public readonly List<DateTime> BT = new List<DateTime>();

        private int _peakIdx = 0;
        private int _troughIdx = 0;

        private bool _haveSWH = false;
        private double _swhPrice = 0.0;
        private int _swhIdx = 0;
        private bool _haveSWL = false;
        private double _swlPrice = 0.0;
        private int _swlIdx = 0;
        private int _regime = 0;      // 0=warmup, 1=up, 2=down
        private int _ei = 0;
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

        private int _lastProcessedIndex = -1;

        // Current market regime exposed for S1 (0=warmup,1=up,2=down) --
        // used e.g. to pick which swing reference a POI was created from.
        public int Regime => _regime;
        public int LastSWHidx => _lastSWHidx;
        public int LastSWLidx => _lastSWLidx;
        public bool HaveSWH => _haveSWH;
        public double SwhPrice => _swhPrice;
        public int SwhIdx => _swhIdx;
        public bool HaveSWL => _haveSWL;
        public double SwlPrice => _swlPrice;
        public int SwlIdx => _swlIdx;

        public PoiMarketEngine(Bars bars, string label)
        {
            _bars = bars;
            Label = label;
        }

        // Call frequently (e.g. every OnTick). Internally detects and
        // processes any newly-closed bars on this engine's own Bars series
        // since the last call -- each engine instance tracks its own
        // progress independently, so the caller doesn't need per-timeframe
        // event wiring.
        public void Update()
        {
            int closedUpTo = _bars.Count - 2; // last fully-closed bar's index
            for (int idx = _lastProcessedIndex + 1; idx <= closedUpTo; idx++)
                ProcessBar(idx);
        }

        private void ProcessBar(int srcIndex)
        {
            if (srcIndex <= _lastProcessedIndex) return;
            _lastProcessedIndex = srcIndex;

            O.Add(_bars.OpenPrices[srcIndex]);
            H.Add(_bars.HighPrices[srcIndex]);
            L.Add(_bars.LowPrices[srcIndex]);
            C.Add(_bars.ClosePrices[srcIndex]);
            BT.Add(_bars.OpenTimes[srcIndex]);

            int n = O.Count;
            if (n < 2) return;

            int k = n - 1;
            RunEngine(k);
        }

        // ===================== MAIN ENGINE (per bar k) =====================
        private void RunEngine(int k)
        {
            // ---------- SWING DETECTION ----------
            bool isBull = C[k] >= O[k];
            bool brkH = H[k] > H[k - 1];
            bool brkL = L[k] < L[k - 1];
            bool dualAct = brkH && brkL;

            bool prevDual = false;
            int pdKind1 = -1, pdIdx1 = -1, pdKind2 = -1, pdIdx2 = -1;
            int eCnt = Events.Count;
            if (eCnt >= 2)
            {
                var ev1 = Events[eCnt - 1];
                var ev2 = Events[eCnt - 2];
                if (ev1.Kind != ev2.Kind && ev1.ConfirmIdx == ev2.ConfirmIdx && ev1.ConfirmIdx == k - 1)
                {
                    prevDual = true;
                    pdKind1 = ev1.Kind; pdIdx1 = ev1.SwingIdx;
                    pdKind2 = ev2.Kind; pdIdx2 = ev2.SwingIdx;
                }
            }

            int evBeforeSwing = Events.Count;

            if (!isBull)
            {
                if (H[k] > H[_peakIdx]) _peakIdx = k;
                if (brkH)
                {
                    int lk = Events.Count > 0 ? Events[Events.Count - 1].Kind : -1;
                    bool blockDup = prevDual && !dualAct && ((pdKind1 == 1 && pdIdx1 == _troughIdx) || (pdKind2 == 1 && pdIdx2 == _troughIdx));
                    if (lk != 1 && !blockDup)
                    {
                        AddSL(_troughIdx);
                        AddEv(k, 1, _troughIdx, L[_troughIdx]);
                        _peakIdx = k;
                    }
                }
                if (L[k] < L[_troughIdx]) _troughIdx = k;
                if (brkL)
                {
                    int lk2 = Events.Count > 0 ? Events[Events.Count - 1].Kind : -1;
                    bool blockDup2 = prevDual && !dualAct && ((pdKind1 == 0 && pdIdx1 == _peakIdx) || (pdKind2 == 0 && pdIdx2 == _peakIdx));
                    if (lk2 != 0 && !blockDup2)
                    {
                        AddSH(_peakIdx);
                        AddEv(k, 0, _peakIdx, H[_peakIdx]);
                        _troughIdx = k;
                    }
                }
            }
            else
            {
                if (L[k] < L[_troughIdx]) _troughIdx = k;
                if (brkL)
                {
                    int lk3 = Events.Count > 0 ? Events[Events.Count - 1].Kind : -1;
                    bool blockDup3 = prevDual && !dualAct && ((pdKind1 == 0 && pdIdx1 == _peakIdx) || (pdKind2 == 0 && pdIdx2 == _peakIdx));
                    if (lk3 != 0 && !blockDup3)
                    {
                        AddSH(_peakIdx);
                        AddEv(k, 0, _peakIdx, H[_peakIdx]);
                        _troughIdx = k;
                    }
                }
                if (H[k] > H[_peakIdx]) _peakIdx = k;
                if (brkH)
                {
                    int lk4 = Events.Count > 0 ? Events[Events.Count - 1].Kind : -1;
                    bool blockDup4 = prevDual && !dualAct && ((pdKind1 == 1 && pdIdx1 == _troughIdx) || (pdKind2 == 1 && pdIdx2 == _troughIdx));
                    if (lk4 != 1 && !blockDup4)
                    {
                        AddSL(_troughIdx);
                        AddEv(k, 1, _troughIdx, L[_troughIdx]);
                        _peakIdx = k;
                    }
                }
            }

            // ---------- REGIME / MSS / OB ENGINE ----------
            int evTotal = Events.Count;

            int peek0 = _ei;
            while (peek0 < evTotal)
            {
                var pEv = Events[peek0];
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

            bool kBull = C[k] >= O[k];

            if (!kBull)
            {
                if (_haveSWH && H[k] > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2) { _regime = 1; AddMss(k, _swhIdx, _swhPrice, true); }

                    bool pendStillAlive = false;
                    if (_pendBullAifob != -1) pendStillAlive = Obs[_pendBullAifob].State == 4;
                    if (pendStillAlive)
                    {
                        var obRef = Obs[_pendBullAifob];
                        obRef.State = 0; obRef.OrigState = 0; obRef.EligibleK = -1;
                        _pendBullAifob = -1;
                    }
                    else _pendBullAifob = -1;

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
                                double cX = C[x], oX = O[x];
                                bool okB = false;
                                if (cX < oX) { if (best == -1) okB = true; else okB = cX < C[best]; }
                                if (okB) best = x;
                            }
                            if (best != -1 && !CandleClaimed(best, true))
                            {
                                double oB = O[best], cB = C[best];
                                AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive = false;
                    if (_pendBullAirb != -1) pendRbStillAlive = Rbs[_pendBullAirb].State == 4;
                    if (pendRbStillAlive)
                    {
                        var rbRef = Rbs[_pendBullAirb];
                        rbRef.State = 0; rbRef.Origin = 0; rbRef.EligibleK = -1;
                        _pendBullAirb = -1;
                    }
                    else _pendBullAirb = -1;

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

                int peek2 = _ei;
                while (peek2 < evTotal)
                {
                    var pEv2 = Events[peek2];
                    if (pEv2.ConfirmIdx != k) break;
                    if (pEv2.Kind == 0)
                    {
                        _haveSWH = true; _swhPrice = pEv2.Price; _swhIdx = pEv2.SwingIdx;
                        _pendBullAifob = -1; _pendBullAirb = -1;
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
                        _haveSWL = true; _swlPrice = pEv2.Price; _swlIdx = pEv2.SwingIdx;
                        _pendBearAifob = -1; _pendBearAirb = -1;
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

                if (_haveSWL && L[k] < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1) { _regime = 2; AddMss(k, _swlIdx, _swlPrice, false); }

                    bool pendStillAlive2 = false;
                    if (_pendBearAifob != -1) pendStillAlive2 = Obs[_pendBearAifob].State == 4;
                    if (pendStillAlive2)
                    {
                        var obRef2 = Obs[_pendBearAifob];
                        obRef2.State = 0; obRef2.OrigState = 0; obRef2.EligibleK = -1;
                        _pendBearAifob = -1;
                    }
                    else _pendBearAifob = -1;

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
                                double cX = C[x], oX = O[x];
                                bool okB2 = false;
                                if (cX > oX) { if (best2 == -1) okB2 = true; else okB2 = cX > C[best2]; }
                                if (okB2) best2 = x;
                            }
                            if (best2 != -1 && !CandleClaimed(best2, false))
                            {
                                double oB = O[best2], cB = C[best2];
                                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive2 = false;
                    if (_pendBearAirb != -1) pendRbStillAlive2 = Rbs[_pendBearAirb].State == 4;
                    if (pendRbStillAlive2)
                    {
                        var rbRef2 = Rbs[_pendBearAirb];
                        rbRef2.State = 0; rbRef2.Origin = 0; rbRef2.EligibleK = -1;
                        _pendBearAirb = -1;
                    }
                    else _pendBearAirb = -1;

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
                if (_haveSWL && L[k] < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1) { _regime = 2; AddMss(k, _swlIdx, _swlPrice, false); }

                    bool pendStillAlive3 = false;
                    if (_pendBearAifob != -1) pendStillAlive3 = Obs[_pendBearAifob].State == 4;
                    if (pendStillAlive3)
                    {
                        var obRef3 = Obs[_pendBearAifob];
                        obRef3.State = 0; obRef3.OrigState = 0; obRef3.EligibleK = -1;
                        _pendBearAifob = -1;
                    }
                    else _pendBearAifob = -1;

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
                                double cX = C[x], oX = O[x];
                                bool okB3 = false;
                                if (cX > oX) { if (best3 == -1) okB3 = true; else okB3 = cX > C[best3]; }
                                if (okB3) best3 = x;
                            }
                            if (best3 != -1 && !CandleClaimed(best3, false))
                            {
                                double oB = O[best3], cB = C[best3];
                                AddOB(best3, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive3 = false;
                    if (_pendBearAirb != -1) pendRbStillAlive3 = Rbs[_pendBearAirb].State == 4;
                    if (pendRbStillAlive3)
                    {
                        var rbRef3 = Rbs[_pendBearAirb];
                        rbRef3.State = 0; rbRef3.Origin = 0; rbRef3.EligibleK = -1;
                        _pendBearAirb = -1;
                    }
                    else _pendBearAirb = -1;

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

                int peek3 = _ei;
                while (peek3 < evTotal)
                {
                    var pEv3 = Events[peek3];
                    if (pEv3.ConfirmIdx != k) break;
                    if (pEv3.Kind == 0)
                    {
                        _haveSWH = true; _swhPrice = pEv3.Price; _swhIdx = pEv3.SwingIdx;
                        _pendBullAifob = -1; _pendBullAirb = -1;
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
                        _haveSWL = true; _swlPrice = pEv3.Price; _swlIdx = pEv3.SwingIdx;
                        _pendBearAifob = -1; _pendBearAirb = -1;
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

                if (_haveSWH && H[k] > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2) { _regime = 1; AddMss(k, _swhIdx, _swhPrice, true); }

                    bool pendStillAlive4 = false;
                    if (_pendBullAifob != -1) pendStillAlive4 = Obs[_pendBullAifob].State == 4;
                    if (pendStillAlive4)
                    {
                        var obRef4 = Obs[_pendBullAifob];
                        obRef4.State = 0; obRef4.OrigState = 0; obRef4.EligibleK = -1;
                        _pendBullAifob = -1;
                    }
                    else _pendBullAifob = -1;

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
                                double cX = C[x], oX = O[x];
                                bool okB4 = false;
                                if (cX < oX) { if (best4 == -1) okB4 = true; else okB4 = cX < C[best4]; }
                                if (okB4) best4 = x;
                            }
                            if (best4 != -1 && !CandleClaimed(best4, true))
                            {
                                double oB = O[best4], cB = C[best4];
                                AddOB(best4, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 0);
                            }
                        }
                    }

                    bool pendRbStillAlive4 = false;
                    if (_pendBullAirb != -1) pendRbStillAlive4 = Rbs[_pendBullAirb].State == 4;
                    if (pendRbStillAlive4)
                    {
                        var rbRef4 = Rbs[_pendBullAirb];
                        rbRef4.State = 0; rbRef4.Origin = 0; rbRef4.EligibleK = -1;
                        _pendBullAirb = -1;
                    }
                    else _pendBullAirb = -1;

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

            // STEP 1b/1c: continuous IFVG/IVI scans
            if (_regime == 1 && k >= 2 && k > _fvgBullScanUpto)
            {
                double h1c = H[k - 2], l3c = L[k];
                if (h1c < l3c) AddFVG(k - 2, h1c, l3c, true, k, 0);
                _fvgBullScanUpto = k;
            }
            if (_regime == 2 && k >= 2 && k > _fvgBearScanUpto)
            {
                double l1c = L[k - 2], h3c = H[k];
                if (l1c > h3c) AddFVG(k - 2, h3c, l1c, false, k, 0);
                _fvgBearScanUpto = k;
            }
            if (_regime == 1 && k >= 1 && k > _viBullScanUpto)
            {
                double op1c = O[k - 1], cl1c = C[k - 1], op2c = O[k], cl2c = C[k];
                bool isBull1c = cl1c >= op1c;
                if (cl1c < op2c && cl2c > cl1c && isBull1c) AddVI(k - 1, cl1c, op2c, true, k, 0);
                _viBullScanUpto = k;
            }
            if (_regime == 2 && k >= 1 && k > _viBearScanUpto)
            {
                double op1d = O[k - 1], cl1d = C[k - 1], op2d = O[k], cl2d = C[k];
                bool isBull1d = cl1d >= op1d;
                if (cl1d > op2d && cl2d < cl1d && !isBull1d) AddVI(k - 1, op2d, cl1d, false, k, 0);
                _viBearScanUpto = k;
            }

            // STEP 2: eligibility arming for all 4 POI types
            while (_ei < evTotal)
            {
                var sEv = Events[_ei];
                if (sEv.ConfirmIdx != k) break;
                if (sEv.Kind == 0)
                {
                    if (!swhCons) { _haveSWH = true; _swhPrice = sEv.Price; _swhIdx = sEv.SwingIdx; }
                    _lastSWHidx = sEv.SwingIdx;
                    foreach (var obZ in Obs)
                        if (obZ.Bullish && (obZ.State == 0 || obZ.State == 4) && obZ.EligibleK == -1 && k > obZ.TriggerK) obZ.EligibleK = k;
                    foreach (var fvgZ in Fvgs)
                        if (fvgZ.Bullish && fvgZ.State == 0 && fvgZ.EligibleK == -1 && k > fvgZ.TriggerK) fvgZ.EligibleK = k;
                    foreach (var rbZ in Rbs)
                        if (rbZ.Bullish && (rbZ.State == 0 || rbZ.State == 4) && rbZ.EligibleK == -1 && k > rbZ.TriggerK) rbZ.EligibleK = k;
                    foreach (var viZ in Vis)
                        if (viZ.Bullish && viZ.State == 0 && viZ.EligibleK == -1 && k > viZ.TriggerK) viZ.EligibleK = k;
                }
                else
                {
                    if (!swlCons) { _haveSWL = true; _swlPrice = sEv.Price; _swlIdx = sEv.SwingIdx; }
                    _lastSWLidx = sEv.SwingIdx;
                    foreach (var obZ2 in Obs)
                        if (!obZ2.Bullish && (obZ2.State == 0 || obZ2.State == 4) && obZ2.EligibleK == -1 && k > obZ2.TriggerK) obZ2.EligibleK = k;
                    foreach (var fvgZ2 in Fvgs)
                        if (!fvgZ2.Bullish && fvgZ2.State == 0 && fvgZ2.EligibleK == -1 && k > fvgZ2.TriggerK) fvgZ2.EligibleK = k;
                    foreach (var rbZ2 in Rbs)
                        if (!rbZ2.Bullish && (rbZ2.State == 0 || rbZ2.State == 4) && rbZ2.EligibleK == -1 && k > rbZ2.TriggerK) rbZ2.EligibleK = k;
                    foreach (var viZ2 in Vis)
                        if (!viZ2.Bullish && viZ2.State == 0 && viZ2.EligibleK == -1 && k > viZ2.TriggerK) viZ2.EligibleK = k;
                }
                _ei++;
            }

            double hK = H[k];
            double lK = L[k];

            // STEP 3: OB lifecycle
            foreach (var obZ3 in Obs)
            {
                if (obZ3.State == 3) continue;
                double zb = obZ3.Zb, zt = obZ3.Zt;
                bool bull = obZ3.Bullish;

                if (obZ3.EligibleK != -1 && k >= obZ3.EligibleK)
                {
                    if (hK >= zb && lK <= zt)
                    {
                        obZ3.PreSpentState = obZ3.State; obZ3.State = 3; obZ3.StopK = k;
                        continue;
                    }
                }

                if ((obZ3.State == 0 || obZ3.State == 1 || obZ3.State == 4) && obZ3.EligibleK != -1)
                {
                    bool isIFOB = obZ3.OrigState != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = Events[e2];
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

            // STEP 3b: FVG lifecycle
            foreach (var fvgZ3 in Fvgs)
            {
                if (fvgZ3.State == 3) continue;
                double zbf = fvgZ3.Zb, ztf = fvgZ3.Zt;
                bool bullf = fvgZ3.Bullish;

                if (fvgZ3.EligibleK != -1 && k >= fvgZ3.EligibleK)
                {
                    if (hK >= zbf && lK <= ztf)
                    {
                        fvgZ3.PreSpentState = fvgZ3.State; fvgZ3.State = 3; fvgZ3.StopK = k;
                        continue;
                    }
                }

                if (fvgZ3.Origin != 1 && fvgZ3.State == 0 && fvgZ3.EligibleK != -1 && k >= fvgZ3.EligibleK)
                {
                    double cK = C[k];
                    bool closedThrough = bullf ? cK < zbf : cK > ztf;
                    if (closedThrough)
                    {
                        fvgZ3.PreSpentState = fvgZ3.State; fvgZ3.State = 3; fvgZ3.StopK = k;
                        continue;
                    }
                }

                if ((fvgZ3.State == 0 || fvgZ3.State == 1) && fvgZ3.EligibleK != -1)
                {
                    bool isIFVG = fvgZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = Events[e2];
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

            // STEP 3c: RB lifecycle
            foreach (var rbZ3 in Rbs)
            {
                if (rbZ3.State == 3) continue;
                double zbr = rbZ3.Zb, ztr = rbZ3.Zt;
                bool bullr = rbZ3.Bullish;

                if (rbZ3.EligibleK != -1 && k >= rbZ3.EligibleK)
                {
                    if (hK >= zbr && lK <= ztr)
                    {
                        rbZ3.PreSpentState = rbZ3.State; rbZ3.State = 3; rbZ3.StopK = k;
                        continue;
                    }
                }

                if ((rbZ3.State == 0 || rbZ3.State == 1 || rbZ3.State == 4) && rbZ3.EligibleK != -1)
                {
                    bool isIRB = rbZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = Events[e2];
                        if (stEv.ConfirmIdx != k) continue;
                        bool strandedR = false;
                        if (isIRB)
                        {
                            if (bullr && stEv.Kind == 1 && stEv.Price > ztr) strandedR = true;
                            if (!bullr && stEv.Kind == 0 && stEv.Price < zbr) strandedR = true;
                        }
                        else
                        {
                            if (bullr && stEv.Kind == 1 && stEv.Price > ztr) strandedR = true;
                            if (!bullr && stEv.Kind == 0 && stEv.Price < zbr) strandedR = true;
                        }
                        if (strandedR) { rbZ3.State = 2; break; }
                    }
                }
            }

            // STEP 3d: VI lifecycle
            foreach (var viZ3 in Vis)
            {
                if (viZ3.State == 3) continue;
                double zbv = viZ3.Zb, ztv = viZ3.Zt;
                bool bullv = viZ3.Bullish;

                if (viZ3.EligibleK != -1 && k >= viZ3.EligibleK)
                {
                    if (hK >= zbv && lK <= ztv)
                    {
                        viZ3.PreSpentState = viZ3.State; viZ3.State = 3; viZ3.StopK = k;
                        continue;
                    }
                }

                if (viZ3.Origin != 1 && viZ3.State == 0 && viZ3.EligibleK != -1 && k >= viZ3.EligibleK)
                {
                    double cKv = C[k];
                    bool closedThroughV = bullv ? cKv < zbv : cKv > ztv;
                    if (closedThroughV)
                    {
                        viZ3.PreSpentState = viZ3.State; viZ3.State = 3; viZ3.StopK = k;
                        continue;
                    }
                }

                if ((viZ3.State == 0 || viZ3.State == 1) && viZ3.EligibleK != -1)
                {
                    bool isIVI = viZ3.Origin != 1;
                    for (int e2 = evBeforeSwing; e2 < evTotal; e2++)
                    {
                        var stEv = Events[e2];
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
            int sz = SwHighs.Count;
            bool doPush = sz == 0 || SwHighs[sz - 1] != idx;
            if (doPush) SwHighs.Add(idx);
        }

        private void AddSL(int idx)
        {
            int sz = SwLows.Count;
            bool doPush = sz == 0 || SwLows[sz - 1] != idx;
            if (doPush) SwLows.Add(idx);
        }

        private void AddEv(int cIdx, int kind, int sIdx, double pr)
        {
            Events.Add(new SwEv { ConfirmIdx = cIdx, Kind = kind, SwingIdx = sIdx, Price = pr });
        }

        private void AddMss(int aIdx, int bIdx, double pr, bool up)
        {
            Msses.Add(new MssEv { AtIdx = aIdx, BrokenIdx = bIdx, Price = pr, ToUp = up });
        }

        private void AddOB(int cand, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            Obs.Add(new ObZone { Candle = cand, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, OrigState = st, PreSpentState = st });
        }

        private bool CandleClaimed(int cand, bool bull)
        {
            foreach (var zz in Obs)
                if (zz.Candle == cand && zz.Bullish == bull) return true;
            return false;
        }

        private bool ExistsAifobInRange(int lo, int hi, bool bull)
        {
            foreach (var zz in Obs)
                if (zz.OrigState == 4 && zz.Bullish == bull && zz.Candle >= lo && zz.Candle <= hi) return true;
            return false;
        }

        private void AddFVG(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            Fvgs.Add(new FvgZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        private void TryCreateIFVGs(int lo, int hi, bool bullish, int triggerK)
        {
            if (hi < lo + 2) return;
            for (int c3 = lo + 2; c3 <= hi; c3++)
            {
                int c1 = c3 - 2;
                if (bullish)
                {
                    double h1 = H[c1], l3 = L[c3];
                    if (h1 < l3) AddFVG(c1, h1, l3, true, triggerK, 0);
                }
                else
                {
                    double l1 = L[c1], h3 = H[c3];
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
                    double l1 = L[c1], h3 = H[c3];
                    if (l1 > h3)
                    {
                        double l3 = L[c3];
                        if (l1 > guardPrice && l3 > guardPrice) AddFVG(c1, h3, l1, true, triggerK, 1);
                    }
                }
                else
                {
                    double h1 = H[c1], l3 = L[c3];
                    if (h1 < l3)
                    {
                        double h3 = H[c3];
                        if (h1 < guardPrice && h3 < guardPrice) AddFVG(c1, h1, l3, false, triggerK, 1);
                    }
                }
            }
        }

        private void TryBullAOB(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++) if (H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, newSwlI));
            int hi2 = Math.Max(aobSWHi - 1, newSwlI);
            int best2 = -1;
            for (int x = lo2; x <= hi2; x++)
            {
                if (x < 0) continue;
                double cX = C[x], oX = O[x];
                bool okB2 = false;
                if (cX > oX) { if (best2 == -1) okB2 = true; else okB2 = cX > C[best2]; }
                if (okB2) best2 = x;
            }
            if (best2 == -1) return;
            if (L[best2] > newSwlP)
            {
                double oB = O[best2], cB = C[best2];
                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 1);
            }
        }

        private void TryBearAOB(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++) if (L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, newSwhI));
            int hi2 = Math.Max(aobSWLi - 1, newSwhI);
            int best2 = -1;
            for (int x = lo2; x <= hi2; x++)
            {
                if (x < 0) continue;
                double cX = C[x], oX = O[x];
                bool okB2 = false;
                if (cX < oX) { if (best2 == -1) okB2 = true; else okB2 = cX < C[best2]; }
                if (okB2) best2 = x;
            }
            if (best2 == -1) return;
            if (H[best2] < newSwhP)
            {
                double oB = O[best2], cB = C[best2];
                AddOB(best2, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 1);
            }
        }

        private void TryBullAFVG(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++) if (H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int swlExt = (newSwlI + 1 <= k - 1) ? newSwlI + 1 : newSwlI;
            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, swlExt));
            int hi2 = Math.Max(aobSWHi - 1, swlExt);
            TryCreateAFVGs(lo2, hi2, true, k, newSwlP);
        }

        private void TryBearAFVG(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++) if (L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int swhExt = (newSwhI + 1 <= k - 1) ? newSwhI + 1 : newSwhI;
            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, swhExt));
            int hi2 = Math.Max(aobSWLi - 1, swhExt);
            TryCreateAFVGs(lo2, hi2, false, k, newSwhP);
        }

        private void AddRB(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            Rbs.Add(new RbZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        private void AddRBFromSwing(int idx, bool isHigh, int tK, int st)
        {
            if (isHigh)
                AddRB(idx, Math.Max(O[idx], C[idx]), H[idx], false, tK, st);
            else
                AddRB(idx, L[idx], Math.Min(O[idx], C[idx]), true, tK, st);
        }

        private void TryBullARB(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++) if (H[v] >= armedSwhPrice) refViolated = true;
            if (!refViolated) AddRBFromSwing(aobSWHi, true, k, 1);
        }

        private void TryBearARB(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++) if (L[v] <= armedSwlPrice) refViolated = true;
            if (!refViolated) AddRBFromSwing(aobSWLi, false, k, 1);
        }

        private bool SwingClaimed(int idx, bool bull)
        {
            foreach (var zz in Rbs)
                if (zz.LeftIdx == idx && zz.Bullish == bull) return true;
            return false;
        }

        private bool ExistsAirbInRange(int lo, int hi, bool bull)
        {
            foreach (var zz in Rbs)
                if (zz.State == 4 && zz.Bullish == bull && zz.LeftIdx >= lo && zz.LeftIdx <= hi) return true;
            return false;
        }

        private int TryBullAIRB(int pReg, bool pHaveSWH, int pSwhI, int pLastSWLi, int newSwlI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt = L[k] < L[newSwlI];
            if (pReg == 1 && pHaveSWH && pSwhI >= 0 && pLastSWLi >= 0 && !alreadyBrokeIt)
            {
                if (!SwingClaimed(pLastSWLi, true))
                {
                    AddRBFromSwing(pLastSWLi, false, k, 4);
                    result = Rbs.Count - 1;
                }
            }
            return result;
        }

        private int TryBearAIRB(int pReg, bool pHaveSWL, int pSwlI, int pLastSWHi, int newSwhI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt2 = H[k] > H[newSwhI];
            if (pReg == 2 && pHaveSWL && pSwlI >= 0 && pLastSWHi >= 0 && !alreadyBrokeIt2)
            {
                if (!SwingClaimed(pLastSWHi, false))
                {
                    AddRBFromSwing(pLastSWHi, true, k, 4);
                    result = Rbs.Count - 1;
                }
            }
            return result;
        }

        private void AddVI(int leftIdx, double zb, double zt, bool bull, int tK, int st)
        {
            int eK = (st == 1) ? tK : -1;
            Vis.Add(new ViZone { LeftIdx = leftIdx, Zb = zb, Zt = zt, Bullish = bull, TriggerK = tK, EligibleK = eK, StopK = -1, State = st, Origin = st, PreSpentState = st });
        }

        private void TryCreateIVIs(int lo, int hi, bool bullish, int triggerK)
        {
            if (hi < lo + 1) return;
            for (int c2 = lo + 1; c2 <= hi; c2++)
            {
                int c1 = c2 - 1;
                double op1 = O[c1], cl1 = C[c1], op2 = O[c2], cl2 = C[c2];
                bool isBull1 = cl1 >= op1;
                if (bullish)
                {
                    if (cl1 < op2 && cl2 > cl1 && isBull1) AddVI(c1, cl1, op2, true, triggerK, 0);
                }
                else
                {
                    if (cl1 > op2 && cl2 < cl1 && !isBull1) AddVI(c1, op2, cl1, false, triggerK, 0);
                }
            }
        }

        private void TryCreateAVIs(int lo, int hi, bool bullish, int triggerK, double guardPrice)
        {
            if (hi < lo + 1) return;
            for (int c2 = lo + 1; c2 <= hi; c2++)
            {
                int c1 = c2 - 1;
                double op1 = O[c1], cl1 = C[c1], op2 = O[c2], cl2 = C[c2];
                bool isBull1 = cl1 >= op1;
                if (bullish)
                {
                    if (cl1 > op2 && cl2 < cl1 && !isBull1)
                    {
                        double l1 = L[c1], l2 = L[c2];
                        if (l1 > guardPrice && l2 > guardPrice) AddVI(c1, op2, cl1, true, triggerK, 1);
                    }
                }
                else
                {
                    if (cl1 < op2 && cl2 > cl1 && isBull1)
                    {
                        double h1 = H[c1], h2 = H[c2];
                        if (h1 < guardPrice && h2 < guardPrice) AddVI(c1, cl1, op2, false, triggerK, 1);
                    }
                }
            }
        }

        private void TryBullAVI(int pReg, int aobSWHi, int newSwlI, double newSwlP, int k)
        {
            if (pReg != 1 || aobSWHi < 0) return;
            double armedSwhPrice = H[aobSWHi];
            bool refViolated = false;
            for (int v = aobSWHi + 1; v <= newSwlI; v++) if (H[v] >= armedSwhPrice) refViolated = true;
            if (refViolated) return;

            int swlExt = (newSwlI + 1 <= k - 1) ? newSwlI + 1 : newSwlI;
            int lo2 = Math.Max(0, Math.Min(aobSWHi - 1, swlExt));
            int hi2 = Math.Max(aobSWHi - 1, swlExt);
            TryCreateAVIs(lo2, hi2, true, k, newSwlP);
        }

        private void TryBearAVI(int pReg, int aobSWLi, int newSwhI, double newSwhP, int k)
        {
            if (pReg != 2 || aobSWLi < 0) return;
            double armedSwlPrice = L[aobSWLi];
            bool refViolated = false;
            for (int v = aobSWLi + 1; v <= newSwhI; v++) if (L[v] <= armedSwlPrice) refViolated = true;
            if (refViolated) return;

            int swhExt = (newSwhI + 1 <= k - 1) ? newSwhI + 1 : newSwhI;
            int lo2 = Math.Max(0, Math.Min(aobSWLi - 1, swhExt));
            int hi2 = Math.Max(aobSWLi - 1, swhExt);
            TryCreateAVIs(lo2, hi2, false, k, newSwhP);
        }

        private int TryBullAIFOB(int pReg, bool pHaveSWH, int pSwhI, int pLastSWLi, int newSwlI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt = L[k] < L[newSwlI];
            if (pReg == 1 && pHaveSWH && pSwhI >= 0 && pLastSWLi >= 0 && !alreadyBrokeIt)
            {
                int lo = Math.Max(0, Math.Min(Math.Min(pLastSWLi, newSwlI), pSwhI - 1));
                int hi = Math.Max(Math.Max(pLastSWLi, newSwlI), pSwhI - 1);
                int best = -1;
                for (int x = lo; x <= hi; x++)
                {
                    if (x < 0) continue;
                    double cX = C[x], oX = O[x];
                    bool okB = false;
                    if (cX < oX) { if (best == -1) okB = true; else okB = cX < C[best]; }
                    if (okB) best = x;
                }
                if (best != -1 && !CandleClaimed(best, true))
                {
                    double oB = O[best], cB = C[best];
                    AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), true, k, 4);
                    result = Obs.Count - 1;
                }
            }
            return result;
        }

        private int TryBearAIFOB(int pReg, bool pHaveSWL, int pSwlI, int pLastSWHi, int newSwhI, int k)
        {
            int result = -1;
            bool alreadyBrokeIt2 = H[k] > H[newSwhI];
            if (pReg == 2 && pHaveSWL && pSwlI >= 0 && pLastSWHi >= 0 && !alreadyBrokeIt2)
            {
                int lo = Math.Max(0, Math.Min(Math.Min(pLastSWHi, newSwhI), pSwlI - 1));
                int hi = Math.Max(Math.Max(pLastSWHi, newSwhI), pSwlI - 1);
                int best = -1;
                for (int x = lo; x <= hi; x++)
                {
                    if (x < 0) continue;
                    double cX = C[x], oX = O[x];
                    bool okB = false;
                    if (cX > oX) { if (best == -1) okB = true; else okB = cX > C[best]; }
                    if (okB) best = x;
                }
                if (best != -1 && !CandleClaimed(best, false))
                {
                    double oB = O[best], cB = C[best];
                    AddOB(best, Math.Min(oB, cB), Math.Max(oB, cB), false, k, 4);
                    result = Obs.Count - 1;
                }
            }
            return result;
        }
    }
}
