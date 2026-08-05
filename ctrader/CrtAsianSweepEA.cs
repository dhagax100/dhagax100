// CrtAsianSweepEA.cs -- cTrader (cAlgo) Robot.
//
// Pipeline, exactly as specified:
//   1. Mark the Asian session's high (AH) and low (AL) -- default window
//      20:00-00:00 US Eastern, same box every chart in this project already
//      draws (see SessionSweepIndicator.cs).
//   2. From Asian close (00:00 EST) through the end of the trading window
//      (default 04:00 EST -- the gap AND the trading hours both count),
//      wait for AH or AL to be swept. Whichever goes FIRST sets the day's
//      bias: AH first -> sell, AL first -> buy. If both are taken on the
//      exact same 1-minute bar (no clean "first"), the day is skipped, same
//      convention as this project's "engulfed day" rule elsewhere.
//   3. Mark the most recent confirmed 15-minute swing high AND swing low at
//      that moment. Only the one matching the bias direction matters (swing
//      high if bias=sell, swing low if bias=buy).
//   4. That matching 15m swing level must get swept during Frankfurt open
//      through London's first hour (default 02:00-04:00 EST, a 2-hour
//      window) -- checked via 1-minute price crossing it, for precise
//      timing. If it isn't swept by the window's end, no trade today.
//   5. The instant that 15m sweep happens, drop to the 1-minute chart and
//      hunt CRT (Candle Range Theory): a base candle, then a manipulation
//      candle that wicks beyond the base's high/low (matching bias
//      direction) but CLOSES BACK INSIDE the base candle's range (a wick on
//      one side with a close beyond it is just a breakout, not
//      manipulation -- it does not qualify). The moment a manipulation
//      candle confirms, we are already standing at the open of the very
//      next candle (candle 3) -- enter there, in the bias direction.
//      Candle pairs that don't qualify roll forward one candle at a time
//      (the failed candle becomes the new base) until one does, bounded by
//      the 2-hour trading window.
//   6. Stop loss: the manipulation candle's own wick extreme, plus a 1-pip
//      buffer. Target: 5R (5x the stop distance).
//   7. On a WIN: stop hunting for the rest of the day.
//   8. On a LOSS: don't re-hunt immediately. The failed level (our stop
//      price) must first become a genuinely confirmed 1-minute swing pivot
//      (price has to actually build real structure around it, not just
//      touch it), and THEN get swept again -- only then does CRT hunting
//      restart (fresh base/manipulation search), still in the same bias
//      direction. Repeat this loss/rearm/re-hunt loop until either a win or
//      the 2-hour trading window ends; no new entries after that.
//
// Swing engine: the exact same dual-candle, alternation-guarded swing
// detection already proven in SessionSweepIndicator.cs's StepBar() (also
// reused verbatim in DailyBiasLegLadderEA.cs) -- run here as two
// independent instances (15m for the swing-level reference, 1m for both
// CRT candle mechanics and the post-loss "become a swing, then get swept
// again" rearm check).
//
// Session/timezone handling: identical DST-aware US-Eastern conversion as
// the rest of this project. Asian start defaults to 20:00 EST; the trading
// window (Frankfurt open through London's first hour) defaults to
// 02:00-04:00 EST -- confirmed against Riyadh local clock: 09:00-11:00
// Riyadh in (Northern-hemisphere) summer, 10:00-12:00 Riyadh in winter, both
// of which land on 02:00-04:00 US Eastern once DST is accounted for on both
// sides (Riyadh has no DST; US Eastern does).
//
// Risk/order mechanics: same risk-% position sizing / margin-capped volume
// pattern as ICT_EA_1.cs and DailyBiasLegLadderEA.cs. One position open at a
// time -- the loss/rearm loop is sequential by design (the spec's own
// "repeat" logic), never concurrent.
//
// Logging: every stage transition and every entry/exit is Print()'d with
// full context (bias, which AH/AL swept, the 15m reference level, attempt
// number, entry/exit time, entry/exit price, SL, TP, reason).

using System;
using System.Collections.Generic;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class CrtAsianSweepEA : Robot
    {
        //================================ PARAMETERS ================================
        [Parameter("Risk % of equity per trade", DefaultValue = 1.0, Group = "Risk")]
        public double InpRiskPercent { get; set; }

        [Parameter("Reward:risk target (TP)", DefaultValue = 5.0, Group = "Risk")]
        public double InpRR_Target { get; set; }

        [Parameter("SL buffer beyond the CRT manipulation wick (pips)", DefaultValue = 1.0, Group = "Risk")]
        public double InpSlBufferPips { get; set; }

        [Parameter("Asian session start (hour, 0-23, US Eastern)", DefaultValue = 20, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpAsianStartHourEst { get; set; }

        [Parameter("Frankfurt open (hour, 0-23, US Eastern) -- 15m-sweep window starts here", DefaultValue = 2, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpFrankfurtStartHourEst { get; set; }

        [Parameter("London open (hour, 0-23, US Eastern) -- informational, window end is what matters", DefaultValue = 3, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpLondonStartHourEst { get; set; }

        [Parameter("Trading window end (hour, 0-23, US Eastern) -- Frankfurt open + London's first hour ends here", DefaultValue = 4, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpWindowEndHourEst { get; set; }

        [Parameter("Position label", DefaultValue = "CrtAsianSweep", Group = "Misc")]
        public string InpLabel { get; set; }

        [Parameter("Verbose per-bar logging", DefaultValue = false, Group = "Misc")]
        public bool InpVerboseLog { get; set; }

        //================================ TIMEZONE / SESSION HELPERS ================================
        private static readonly TimeZoneInfo EasternTz = ResolveEasternTimeZone();
        private static TimeZoneInfo ResolveEasternTimeZone()
        {
            try { return TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch (TimeZoneNotFoundException) { return TimeZoneInfo.FindSystemTimeZoneById("America/New_York"); }
        }
        private DateTime ToEastern(DateTime utc) => TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), EasternTz);

        // "Trading day D" spans Asian start (D-1 at InpAsianStartHourEst:00 EST)
        // through the trading window's own end (D at InpWindowEndHourEst:00 EST)
        // -- same convention as DailyBiasLegLadderEA.cs's BiasDayFor.
        private DateTime TradingDayFor(DateTime est) => est.Hour >= InpAsianStartHourEst ? est.Date.AddDays(1) : est.Date;

        // Gap-plus-trading-hours window in which AH/AL is allowed to sweep.
        private bool InAhAlWindow(DateTime est) => est.Hour < InpWindowEndHourEst;

        // The narrower 2-hour window (Frankfurt open -> London's first hour end)
        // in which the 15m reference level must get swept.
        private bool InSweepWindow(DateTime est) => est.Hour >= InpFrankfurtStartHourEst && est.Hour < InpWindowEndHourEst;

        //================================ SWING ENGINE ================================
        // Verbatim port of SessionSweepIndicator.cs's StepBar()/_ev machinery --
        // see DailyBiasLegLadderEA.cs for the same class, reused unchanged. Only
        // the swing list (Ev) is needed here, not the MSS list, but MSS is left
        // in place since it's part of the proven, unmodified logic.
        private struct SwEv { public int ConfirmIdx; public int Kind; public int SwingIdx; public double Price; } // Kind: 0=high,1=low
        private struct MssEv { public int ConfirmIdx; public int SwingIdx; public double Price; public bool Bullish; }

        private class SwingEngine
        {
            private readonly Bars _bars;
            public readonly List<SwEv> Ev = new List<SwEv>();
            public readonly List<MssEv> Mss = new List<MssEv>();
            private int _peakIdx, _troughIdx;
            private bool _haveSwh, _haveSwl;
            private double _swhPrice, _swlPrice;
            private int _swhIdx, _swlIdx;
            private int _regime;
            private int _ei;
            private int _stepped = 1;

            public SwingEngine(Bars bars) { _bars = bars; }

            public double O(int i) => _bars.OpenPrices[i];
            public double H(int i) => _bars.HighPrices[i];
            public double L(int i) => _bars.LowPrices[i];
            public double C(int i) => _bars.ClosePrices[i];
            public DateTime T(int i) => _bars.OpenTimes[i];

            private void AddEv(int confirmIdx, int kind, int swingIdx, double price) =>
                Ev.Add(new SwEv { ConfirmIdx = confirmIdx, Kind = kind, SwingIdx = swingIdx, Price = price });

            public bool LastSwingBefore(int kind, int atOrBefore, out int swingIdx, out double price)
            {
                for (int e = Ev.Count - 1; e >= 0; e--)
                {
                    if (Ev[e].ConfirmIdx > atOrBefore) continue;
                    if (Ev[e].Kind == kind) { swingIdx = Ev[e].SwingIdx; price = Ev[e].Price; return true; }
                }
                swingIdx = -1; price = 0; return false;
            }

            private void StepBar(int i)
            {
                bool bullish = C(i) >= O(i);
                bool breaksPrevHigh = H(i) > H(i - 1);
                bool breaksPrevLow = L(i) < L(i - 1);
                bool dualAction = breaksPrevHigh && breaksPrevLow;

                bool prevDual = false;
                if (Ev.Count >= 2)
                {
                    bool diffKinds = Ev[Ev.Count - 1].Kind != Ev[Ev.Count - 2].Kind;
                    bool sameConfirm = Ev[Ev.Count - 1].ConfirmIdx == Ev[Ev.Count - 2].ConfirmIdx;
                    bool wasLastCandle = Ev[Ev.Count - 1].ConfirmIdx == i - 1;
                    prevDual = diffKinds && sameConfirm && wasLastCandle;
                }
                bool blockPostDual = prevDual && !dualAction;

                if (!bullish)
                {
                    if (H(i) > H(_peakIdx)) _peakIdx = i;
                    if (breaksPrevHigh)
                    {
                        bool lastWasLow = Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 1;
                        if (!lastWasLow && !blockPostDual) { AddEv(i, 1, _troughIdx, L(_troughIdx)); _peakIdx = i; }
                    }
                    if (L(i) < L(_troughIdx)) _troughIdx = i;
                    if (breaksPrevLow)
                    {
                        bool lastWasHigh = Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 0;
                        if (!lastWasHigh && !blockPostDual) { AddEv(i, 0, _peakIdx, H(_peakIdx)); _troughIdx = i; }
                    }
                }
                else
                {
                    if (L(i) < L(_troughIdx)) _troughIdx = i;
                    if (breaksPrevLow)
                    {
                        bool lastWasHigh = Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 0;
                        if (!lastWasHigh && !blockPostDual) { AddEv(i, 0, _peakIdx, H(_peakIdx)); _troughIdx = i; }
                    }
                    if (H(i) > H(_peakIdx)) _peakIdx = i;
                    if (breaksPrevHigh)
                    {
                        bool lastWasLow = Ev.Count > 0 && Ev[Ev.Count - 1].Kind == 1;
                        if (!lastWasLow && !blockPostDual) { AddEv(i, 1, _troughIdx, L(_troughIdx)); _peakIdx = i; }
                    }
                }

                bool swhConsumed = false, swlConsumed = false;
                if (!bullish)
                {
                    if (_haveSwh && H(i) > _swhPrice)
                    {
                        if (_regime == 0) _regime = 1;
                        else if (_regime == 2) { Mss.Add(new MssEv { ConfirmIdx = i, SwingIdx = _swhIdx, Price = _swhPrice, Bullish = true }); _regime = 1; }
                        _haveSwh = false; swhConsumed = true;
                    }
                    for (int peek = _ei; peek < Ev.Count && Ev[peek].ConfirmIdx == i; peek++)
                    {
                        if (Ev[peek].Kind == 0) { _haveSwh = true; _swhPrice = Ev[peek].Price; _swhIdx = Ev[peek].SwingIdx; }
                        else { _haveSwl = true; _swlPrice = Ev[peek].Price; _swlIdx = Ev[peek].SwingIdx; }
                    }
                    if (_haveSwl && L(i) < _swlPrice)
                    {
                        if (_regime == 0) _regime = 2;
                        else if (_regime == 1) { Mss.Add(new MssEv { ConfirmIdx = i, SwingIdx = _swlIdx, Price = _swlPrice, Bullish = false }); _regime = 2; }
                        _haveSwl = false; swlConsumed = true;
                    }
                }
                else
                {
                    if (_haveSwl && L(i) < _swlPrice)
                    {
                        if (_regime == 0) _regime = 2;
                        else if (_regime == 1) { Mss.Add(new MssEv { ConfirmIdx = i, SwingIdx = _swlIdx, Price = _swlPrice, Bullish = false }); _regime = 2; }
                        _haveSwl = false; swlConsumed = true;
                    }
                    for (int peek = _ei; peek < Ev.Count && Ev[peek].ConfirmIdx == i; peek++)
                    {
                        if (Ev[peek].Kind == 0) { _haveSwh = true; _swhPrice = Ev[peek].Price; _swhIdx = Ev[peek].SwingIdx; }
                        else { _haveSwl = true; _swlPrice = Ev[peek].Price; _swlIdx = Ev[peek].SwingIdx; }
                    }
                    if (_haveSwh && H(i) > _swhPrice)
                    {
                        if (_regime == 0) _regime = 1;
                        else if (_regime == 2) { Mss.Add(new MssEv { ConfirmIdx = i, SwingIdx = _swhIdx, Price = _swhPrice, Bullish = true }); _regime = 1; }
                        _haveSwh = false; swhConsumed = true;
                    }
                }

                while (_ei < Ev.Count && Ev[_ei].ConfirmIdx == i)
                {
                    if (Ev[_ei].Kind == 0) { if (!swhConsumed) { _haveSwh = true; _swhPrice = Ev[_ei].Price; _swhIdx = Ev[_ei].SwingIdx; } }
                    else { if (!swlConsumed) { _haveSwl = true; _swlPrice = Ev[_ei].Price; _swlIdx = Ev[_ei].SwingIdx; } }
                    _ei++;
                }
            }

            public void CatchUp()
            {
                int lastClosed = _bars.Count - 2;
                for (int i = _stepped; i <= lastClosed; i++) StepBar(i);
                _stepped = Math.Max(_stepped, lastClosed + 1);
            }
        }

        //================================ DAY STATE MACHINE ================================
        private enum DayState { WaitingAhAl, WaitingSweep15m, Hunting, TradeOpen, RearmWaitSwing, RearmWaitSweep, Done }

        private DateTime _tradingDay = DateTime.MinValue;
        private DayState _state = DayState.Done;
        private string _bias = "none"; // "sell" or "buy" once resolved

        // Asian box (per trading day).
        private double _asianHigh = double.NegativeInfinity, _asianLow = double.PositiveInfinity;
        private bool _asianClosed;

        // The 15m reference level to sweep, and its kind (0=high,1=low, matches
        // SwEv.Kind -- always the one agreeing with _bias).
        private double _refSwingPrice;
        private int _refSwingKind;

        // CRT candle-pair hunt (1-minute).
        private int _baseIdx = -1; // -1 = "assign on next closed bar"

        // Post-loss rearm.
        private double _rearmSlPrice;
        private int _rearmKind;
        private int _rearmEvPtr;
        private double _rearmSwingPrice;

        private int _attemptNo; // entries fired today (logging only)
        private int _cycleNo;   // CRT hunt cycles today (fresh hunt after each loss) -- logging only

        private void ResetForNewDay(DateTime day)
        {
            _tradingDay = day;
            _state = DayState.WaitingAhAl;
            _bias = "none";
            _asianHigh = double.NegativeInfinity;
            _asianLow = double.PositiveInfinity;
            _asianClosed = false;
            _baseIdx = -1;
            _attemptNo = 0;
            _cycleNo = 0;
            Print($"[DAY] {Server.Time:u} new trading day {day:yyyy-MM-dd} -- watching Asian session, then AH/AL sweep.");
        }

        //================================ ENGINE INSTANCES ================================
        private Bars _bars1m, _bars15m;
        private SwingEngine _eng1m, _eng15m;

        //================================ ORDER / RISK ================================
        private double CalcVolume(double riskDistPrice)
        {
            double riskMoney = Account.Equity * (InpRiskPercent / 100.0);
            if (riskDistPrice <= 0) return 0;
            double riskPips = riskDistPrice / Symbol.PipSize;
            double volume = Symbol.VolumeForFixedRisk(riskMoney, riskPips, RoundingMode.Down);
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;
            return volume;
        }

        private void FireEntry(bool isBuy, double slRefPrice, string reasonTag)
        {
            double entryPrice = isBuy ? Symbol.Ask : Symbol.Bid;
            double buffer = InpSlBufferPips * Symbol.PipSize;
            double slPrice = isBuy ? slRefPrice - buffer : slRefPrice + buffer;
            double riskDist = isBuy ? (entryPrice - slPrice) : (slPrice - entryPrice);

            _attemptNo++;
            if (riskDist <= 0)
            {
                Print($"[ENTRY-SKIPPED] {Server.Time:u} attempt={_attemptNo} -- SL already on wrong side of price (entry={entryPrice:F5} sl={slPrice:F5})");
                _state = DayState.Hunting; // stay in the hunt, don't burn the day on a bad tick
                _baseIdx = -1;
                return;
            }

            double tpPrice = isBuy ? entryPrice + riskDist * InpRR_Target : entryPrice - riskDist * InpRR_Target;
            double volume = CalcVolume(riskDist);
            double slPips = riskDist / Symbol.PipSize;
            double tpPips = Math.Abs(tpPrice - entryPrice) / Symbol.PipSize;

            Print($"[ENTRY] {Server.Time:u} bias={_bias} cycle={_cycleNo} attempt={_attemptNo} dir={(isBuy ? "BUY" : "SELL")} "
                + $"entryPrice={entryPrice:F5} sl={slPrice:F5} tp={tpPrice:F5} slPips={slPips:F1} rr={InpRR_Target:F1} volume={volume} ({reasonTag})");

            if (volume <= 0)
            {
                Print($"[ENTRY-SKIPPED] {Server.Time:u} attempt={_attemptNo} -- zero tradeable volume (margin/size constraints)");
                _state = DayState.Hunting;
                _baseIdx = -1;
                return;
            }

            string label = $"{InpLabel}_{_tradingDay:yyyyMMdd}_A{_attemptNo}";
            var result = ExecuteMarketOrder(isBuy ? TradeType.Buy : TradeType.Sell, SymbolName, volume, label, slPips, tpPips, label);
            if (result == null || !result.IsSuccessful)
            {
                Print($"[ENTRY-FAILED] {Server.Time:u} attempt={_attemptNo} -- order rejected: {(result?.Error.ToString() ?? "unknown")}");
                _state = DayState.Hunting;
                _baseIdx = -1;
                return;
            }

            _state = DayState.TradeOpen;
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var p = args.Position;
            if (p.Label == null || !p.Label.StartsWith(InpLabel)) return;
            bool win = p.NetProfit > 0;
            Print($"[EXIT] {Server.Time:u} label={p.Label} dir={p.TradeType} entryTime={p.EntryTime:u} entryPrice={p.EntryPrice:F5} "
                + $"exitTime={Server.Time:u} exitPrice={p.CurrentPrice:F5} pnl={p.NetProfit:F2} reason={args.Reason} result={(win ? "WIN" : "LOSS")}");

            if (_state != DayState.TradeOpen) return; // stale/unrelated event

            if (win)
            {
                _state = DayState.Done;
                Print($"[DAY] {Server.Time:u} win booked -- done hunting for {_tradingDay:yyyy-MM-dd}.");
                return;
            }

            // Loss: arm the rearm check. slRefPrice was the manipulation wick this
            // trade's SL sat behind -- recover it from the position's own SL.
            _rearmSlPrice = p.StopLoss ?? p.EntryPrice;
            _rearmKind = _bias == "sell" ? 0 : 1; // sell failed -> need a fresh swing HIGH; buy failed -> swing LOW
            _rearmEvPtr = _eng1m.Ev.Count;
            _state = DayState.RearmWaitSwing;
            Print($"[REARM] {Server.Time:u} loss -- waiting for {_rearmSlPrice:F5} to become a confirmed 1m swing {(_rearmKind == 0 ? "high" : "low")}, then get swept again.");
        }

        //================================ PER-CLOSED-1M-BAR STATE MACHINE ================================
        private void ProcessClosed1mBar(int i)
        {
            DateTime est = ToEastern(_eng1m.T(i));
            double h = _eng1m.H(i), l = _eng1m.L(i);

            DateTime day = TradingDayFor(est);
            if (day != _tradingDay) ResetForNewDay(day);

            // -- Asian box: always track, regardless of state.
            if (est.Hour >= InpAsianStartHourEst)
            {
                if (h > _asianHigh) _asianHigh = h;
                if (l < _asianLow) _asianLow = l;
            }
            else if (!_asianClosed && !double.IsInfinity(_asianHigh))
            {
                _asianClosed = true;
                if (InpVerboseLog) Print($"[ASIAN] {Server.Time:u} closed AH={_asianHigh:F5} AL={_asianLow:F5} range={(_asianHigh - _asianLow) / Symbol.PipSize:F1}p");
            }

            // -- Window-end: no new setups/entries once the trading window is over.
            // Gated on _asianClosed so this never fires DURING the Asian session
            // itself (hour >= InpAsianStartHourEst is never < InpWindowEndHourEst,
            // which would otherwise mark every day "Done" before AH/AL even forms).
            bool activeState = _state == DayState.WaitingAhAl || _state == DayState.WaitingSweep15m
                || _state == DayState.Hunting || _state == DayState.RearmWaitSwing || _state == DayState.RearmWaitSweep;
            if (activeState && _asianClosed && !InAhAlWindow(est))
            {
                _state = DayState.Done;
                Print($"[DAY] {Server.Time:u} trading window closed with no resolved trade for {_tradingDay:yyyy-MM-dd}.");
                return;
            }
            if (!activeState) return; // Done or TradeOpen -- nothing to evaluate on closed bars

            switch (_state)
            {
                case DayState.WaitingAhAl:
                    if (!_asianClosed) return;
                    bool hitHigh = h > _asianHigh;
                    bool hitLow = l < _asianLow;
                    if (hitHigh && hitLow)
                    {
                        _state = DayState.Done;
                        Print($"[DAY] {Server.Time:u} AH and AL both swept on the same bar -- skipped, no clean bias.");
                        return;
                    }
                    if (hitHigh)
                    {
                        _bias = "sell";
                        _refSwingKind = 0; // need the last confirmed 15m swing HIGH
                        if (!_eng15m.LastSwingBefore(0, LastClosed15mIdx(est), out _, out _refSwingPrice))
                        {
                            _state = DayState.Done;
                            Print($"[DAY] {Server.Time:u} AH swept but no 15m swing high exists yet -- skipped.");
                            return;
                        }
                        _state = DayState.WaitingSweep15m;
                        Print($"[BIAS] {Server.Time:u} AH swept first (AH={_asianHigh:F5}) -> bias=sell. Watching 15m swing high {_refSwingPrice:F5} for a sweep in the trading window.");
                    }
                    else if (hitLow)
                    {
                        _bias = "buy";
                        _refSwingKind = 1; // need the last confirmed 15m swing LOW
                        if (!_eng15m.LastSwingBefore(1, LastClosed15mIdx(est), out _, out _refSwingPrice))
                        {
                            _state = DayState.Done;
                            Print($"[DAY] {Server.Time:u} AL swept but no 15m swing low exists yet -- skipped.");
                            return;
                        }
                        _state = DayState.WaitingSweep15m;
                        Print($"[BIAS] {Server.Time:u} AL swept first (AL={_asianLow:F5}) -> bias=buy. Watching 15m swing low {_refSwingPrice:F5} for a sweep in the trading window.");
                    }
                    return;

                case DayState.WaitingSweep15m:
                    if (!InSweepWindow(est)) return; // must happen inside Frankfurt+first-London-hour specifically
                    bool swept = _refSwingKind == 0 ? h > _refSwingPrice : l < _refSwingPrice;
                    if (!swept) return;
                    _cycleNo++;
                    _state = DayState.Hunting;
                    _baseIdx = -1;
                    Print($"[SWEEP-15M] {Server.Time:u} 15m {(_refSwingKind == 0 ? "high" : "low")} {_refSwingPrice:F5} swept -- dropping to 1m, hunting CRT (cycle {_cycleNo}).");
                    return;

                case DayState.Hunting:
                    EvaluateHunting(i);
                    return;

                case DayState.RearmWaitSwing:
                {
                    for (; _rearmEvPtr < _eng1m.Ev.Count; _rearmEvPtr++)
                    {
                        var ev = _eng1m.Ev[_rearmEvPtr];
                        if (ev.Kind != _rearmKind) continue;
                        bool qualifies = _rearmKind == 0 ? ev.Price >= _rearmSlPrice : ev.Price <= _rearmSlPrice;
                        if (!qualifies) continue;
                        _rearmSwingPrice = ev.Price;
                        _rearmEvPtr++;
                        _state = DayState.RearmWaitSweep;
                        Print($"[REARM] {Server.Time:u} {_rearmSlPrice:F5} is now a confirmed 1m swing {(_rearmKind == 0 ? "high" : "low")} at {_rearmSwingPrice:F5} -- waiting for it to be swept again.");
                        break;
                    }
                    return;
                }

                case DayState.RearmWaitSweep:
                    bool sweptAgain = _rearmKind == 0 ? h > _rearmSwingPrice : l < _rearmSwingPrice;
                    if (!sweptAgain) return;
                    _cycleNo++;
                    _state = DayState.Hunting;
                    _baseIdx = -1;
                    Print($"[REARM] {Server.Time:u} swing {_rearmSwingPrice:F5} swept again -- resuming CRT hunt (cycle {_cycleNo}).");
                    return;
            }
        }

        // Last 15m bar index fully closed at or before `est` -- used to anchor
        // "the last confirmed 15m swing" the instant AH/AL resolves.
        private int LastClosed15mIdx(DateTime est) => _bars15m.Count - 2;

        private void EvaluateHunting(int i)
        {
            if (_baseIdx == -1) { _baseIdx = i; return; } // this bar becomes the fresh base -- "1st candle of CRT"

            bool wantSell = _bias == "sell";
            double baseHigh = _eng1m.H(_baseIdx), baseLow = _eng1m.L(_baseIdx);
            double h = _eng1m.H(i), l = _eng1m.L(i), c = _eng1m.C(i);
            bool closesInsideBase = c >= baseLow && c <= baseHigh;

            bool isManipulation = wantSell
                ? (h > baseHigh && closesInsideBase)   // wicks above base high, closes back inside -- confirms
                : (l < baseLow && closesInsideBase);   // wicks below base low, closes back inside -- confirms

            if (!isManipulation)
            {
                if (InpVerboseLog) Print($"[CRT-ROLL] {Server.Time:u} candle {i} didn't confirm manipulation vs base [{baseLow:F5}..{baseHigh:F5}] -- rolling base forward.");
                _baseIdx = i; // this candle becomes the new candidate base
                return;
            }

            // Confirmed: we are standing at the open of the very next candle right
            // now (this call runs inside OnBar1mOpened, the instant that next bar
            // opened) -- enter here, per "enter third candle open of CRT".
            double slRef = wantSell ? h : l; // the manipulation candle's own wick extreme
            Print($"[CRT] {Server.Time:u} manipulation confirmed vs base [{baseLow:F5}..{baseHigh:F5}] wick={slRef:F5} close={c:F5} -- entering now.");
            FireEntry(!wantSell, slRef, $"CRT cycle={_cycleNo}");
        }

        //================================ LIFECYCLE ================================
        private Bars GetEngineBars(TimeFrame tf)
        {
            var bars = MarketData.GetBars(tf, SymbolName);
            bars.LoadMoreHistory();
            return bars;
        }

        protected override void OnStart()
        {
            _bars1m = GetEngineBars(TimeFrame.Minute); // cAlgo's 1-minute enum member is "Minute", not "Minute1"
            _bars15m = GetEngineBars(TimeFrame.Minute15);
            _eng1m = new SwingEngine(_bars1m);
            _eng15m = new SwingEngine(_bars15m);

            _bars1m.BarOpened += OnBar1mOpened;
            Positions.Closed += OnPositionClosed;

            _eng15m.CatchUp();
            _eng1m.CatchUp();
            for (int i = 1; i <= _bars1m.Count - 2; i++) ProcessClosed1mBar(i);

            Print($"[START] {Server.Time:u} CrtAsianSweepEA started. Asian={InpAsianStartHourEst:00}:00 EST, "
                + $"sweep window={InpFrankfurtStartHourEst:00}:00-{InpWindowEndHourEst:00}:00 EST, RR={InpRR_Target:F1}, risk={InpRiskPercent:F2}%.");
        }

        private void OnBar1mOpened(BarOpenedEventArgs args)
        {
            _eng15m.CatchUp();
            _eng1m.CatchUp();
            int justClosed = _bars1m.Count - 2;
            if (justClosed >= 1) ProcessClosed1mBar(justClosed);
        }
    }
}
