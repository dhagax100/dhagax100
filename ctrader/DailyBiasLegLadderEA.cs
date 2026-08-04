// DailyBiasLegLadderEA.cs -- cTrader (cAlgo) Robot.
//
// Pipeline, exactly as specified:
//   1. BIAS (daily): the one setup validated across this whole project --
//      "setup 1a" -- does live price trade beyond YESTERDAY's whole
//      calendar-day high (sell bias) or low (buy bias), checked from Asian
//      open (default 20:00 EST) through the trading session's own end
//      (default 05:00 EST)? 82.3% directional accuracy, stable train
//      (82.4%) vs test (82.1%) -- the only signal from that research with
//      real, repeatable evidence behind it. If both sides break, that's a
//      conflict day -- no bias, no trades, matching the same convention
//      used throughout the Python research this EA is built on.
//   2. STRUCTURE (5-minute): once a bias is set, watch the 5-minute chart
//      for an MSS (Market Structure Shift) in the SAME direction as the
//      bias. The leg that caused that MSS -- from its most recent opposite
//      swing origin (100%) down/up to its own breaking extreme (0%) --
//      defines a retracement "ladder": the 50%-100% zone (the far half of
//      the leg, back toward its origin). Only this zone is tradeable.
//   3. ENTRY (1-minute): while price sits inside that 50-100% zone and the
//      leg is still valid, every fresh 1-minute MSS in the bias direction
//      is a new entry -- there is no cap on how many times price can re-
//      enter the zone and re-trigger, only a check that each 1m MSS event
//      is used once.
//   4. If price breaks back through the leg's own 100% origin (the leg is
//      "violated"), that leg is abandoned and stage 2 restarts from
//      scratch, watching for a fresh 5-minute MSS in the bias direction --
//      "repeat the same scenario." A brand new leg gets a fresh ladder and
//      its own attempt counter.
//   5. All of the above (5m MSS search, ladder, 1m entries) only runs
//      while the current time is inside our Frankfurt+London trading
//      session (default 01:00-05:00 EST) -- bias tracking itself keeps
//      running from Asian open onward, per its own validated window, but
//      no structure is searched and no trade is ever placed outside the
//      session.
//
// Swing/MSS engine: the exact same dual-candle, alternation-guarded
// swing-detection + regime/MSS logic already proven in
// ctrader/SessionSweepIndicator.cs's StepBar() (itself a trim of
// ctrader/ICT_EA_1.cs's OBEngine.Refresh()), reused verbatim here as a
// small reusable class, run as two independent instances -- one on 5m
// bars, one on 1m bars -- via MarketData.GetBars(TimeFrame.Minute5/Minute).
//
// Session/timezone handling: identical DST-aware US-Eastern conversion and
// hour-of-day session convention as SessionSweepIndicator.cs (ASIAN_START_H
// / LONDON_KZ_START_H / LONDON_KZ_END_H, Frankfurt = killzone start - 1),
// so this EA lines up with every chart/box this project already draws.
//
// "Yesterday's whole calendar-day high/low" for the bias check is tracked
// as a rolling EST-calendar-day high/low, frozen at each EST midnight
// rollover -- NOT cAlgo's own Daily bars (which are anchored to broker
// midnight, not US Eastern midnight, and would silently misalign the bias
// with the validated research). During the evening leg of the bias window
// (yday 20:00-24:00 EST), the reference is the still-accumulating current
// day's own running high/low -- this reproduces, causally and live, the
// exact same comparison the historical daily-OHLC backtest made, since a
// calendar day's own final high can itself be set inside that same
// window; freezing early would silently diverge from the validated rule.
//
// Risk/order mechanics (RR-target take-profit, risk-% position sizing,
// margin-capped volume) are carried over from ctrader/ICT_EA_1.cs's
// already-working CalcLotSize, the proven pattern in this codebase --
// unlike that EA's one-trade-at-a-time cascade, this one allows multiple
// concurrent positions (one per valid 1m re-entry), each independently
// stopped and targeted.
//
// Logging: every stage transition and every entry/exit is Print()'d with
// full context (bias, leg number, attempt number within that leg, entry/
// exit time, entry/exit price, SL, TP, reason), per spec.

using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class DailyBiasLegLadderEA : Robot
    {
        //================================ PARAMETERS ================================
        [Parameter("Risk % of equity per trade", DefaultValue = 0.5, Group = "Risk")]
        public double InpRiskPercent { get; set; }

        [Parameter("Reward:risk target (TP)", DefaultValue = 2.0, Group = "Risk")]
        public double InpRR_Target { get; set; }

        [Parameter("SL buffer beyond the 1m MSS swing (pips)", DefaultValue = 1.0, Group = "Risk")]
        public double InpSlBufferPips { get; set; }

        [Parameter("Asian session start (hour, 0-23, US Eastern) -- bias window opens here", DefaultValue = 20, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpAsianStartHourEst { get; set; }

        [Parameter("London killzone start (hour, 0-23, US Eastern)", DefaultValue = 2, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpLondonStartHourEst { get; set; }

        [Parameter("London killzone end (hour, 0-23, US Eastern) -- bias window AND trading session both end here", DefaultValue = 5, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern -- auto DST)")]
        public int InpLondonKzEndHourEst { get; set; }

        [Parameter("Position label (magic-number equivalent)", DefaultValue = "BiasLegLadder", Group = "Misc")]
        public string InpLabel { get; set; }

        [Parameter("Verbose per-bar logging (bias/leg state, not just entries/exits)", DefaultValue = false, Group = "Misc")]
        public bool InpVerboseLog { get; set; }

        //================================ TIMEZONE / SESSION HELPERS ================================
        // Identical to SessionSweepIndicator.cs -- see that file's header for why
        // this is the correct, auto-DST way to do it regardless of broker server time.
        private static readonly TimeZoneInfo EasternTz = ResolveEasternTimeZone();
        private static TimeZoneInfo ResolveEasternTimeZone()
        {
            try { return TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch (TimeZoneNotFoundException) { return TimeZoneInfo.FindSystemTimeZoneById("America/New_York"); }
        }
        private DateTime ToEastern(DateTime utc) => TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), EasternTz);
        private DateTime ToUtc(DateTime est) => TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(est, DateTimeKind.Unspecified), EasternTz);

        // Frankfurt = 1 hour before the London killzone start, same convention as
        // SessionSweepIndicator.cs / the Python pipeline's FRANKFURT_START_H.
        private int FrankfurtStartHourEst => InpLondonStartHourEst - 1;

        // True while `est` sits inside our Frankfurt+London trading session -- the
        // ONLY window the 5m-MSS/ladder/1m-entry machinery is allowed to run in.
        private bool InTradingSession(DateTime est) => est.Hour >= FrankfurtStartHourEst && est.Hour < InpLondonKzEndHourEst;

        // True while `est` sits inside the (wider) bias-detection window -- Asian
        // open through the trading session's own end, matching setup 1a's
        // validated definition exactly.
        private bool InBiasWindow(DateTime est) =>
            est.Hour >= InpAsianStartHourEst || est.Hour < InpLondonKzEndHourEst;

        //================================ SWING/MSS ENGINE ================================
        // Verbatim port of SessionSweepIndicator.cs's StepBar()/_ev/_mss machinery,
        // generalized into a reusable class so it can run twice (5m + 1m) off two
        // different Bars objects. Behavior is unchanged from that proven file.
        private struct SwEv { public int ConfirmIdx; public int Kind; public int SwingIdx; public double Price; } // Kind: 0=high,1=low
        private struct MssEv { public int ConfirmIdx; public int SwingIdx; public double Price; public bool Bullish; }

        private class SwingMssEngine
        {
            private readonly Bars _bars;
            public readonly List<SwEv> Ev = new List<SwEv>();
            public readonly List<MssEv> Mss = new List<MssEv>();
            private int _peakIdx, _troughIdx;
            private bool _haveSwh, _haveSwl;
            private double _swhPrice, _swlPrice;
            private int _swhIdx, _swlIdx;
            private int _regime; // 0 warmup, 1 up, 2 down
            private int _ei;
            private int _stepped = 1; // next raw bar index StepBar() needs to process

            public SwingMssEngine(Bars bars) { _bars = bars; }

            public double O(int i) => _bars.OpenPrices[i];
            public double H(int i) => _bars.HighPrices[i];
            public double L(int i) => _bars.LowPrices[i];
            public double C(int i) => _bars.ClosePrices[i];
            public DateTime T(int i) => _bars.OpenTimes[i];

            private void AddEv(int confirmIdx, int kind, int swingIdx, double price) =>
                Ev.Add(new SwEv { ConfirmIdx = confirmIdx, Kind = kind, SwingIdx = swingIdx, Price = price });

            // Most recent CONFIRMED swing of the given kind (0=high,1=low) at or
            // before bar index `atOrBefore` -- used to find a leg's own origin
            // (the swing that started the impulsive move an MSS just broke).
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

            // Process every newly-closed bar since the last call. Bars is permanent
            // and only ever appends (see ICT_EA_1.cs's own note on this), so we can
            // safely resume from where we left off instead of reprocessing from bar 1
            // every time -- this engine runs once per closed bar, not once per tick.
            public void CatchUp()
            {
                int lastClosed = _bars.Count - 2; // -1 is the still-forming bar
                for (int i = _stepped; i <= lastClosed; i++) StepBar(i);
                _stepped = Math.Max(_stepped, lastClosed + 1);
            }
        }

        //================================ CALENDAR-DAY HIGH/LOW TRACKER ================================
        // "Yesterday's whole calendar-day high/low" for the bias check -- rolling,
        // EST-midnight-anchored, NOT cAlgo's broker-midnight Daily bars. See file
        // header for why the evening half of the bias window intentionally reads
        // the still-accumulating current day rather than a frozen prior value.
        private DateTime _curCalDate = DateTime.MinValue;
        private double _curDayHigh = double.NegativeInfinity, _curDayLow = double.PositiveInfinity;
        private double _frozenPrevDayHigh = double.NaN, _frozenPrevDayLow = double.NaN;

        private void UpdateCalendarDay(DateTime est, double h, double l)
        {
            DateTime d = est.Date;
            if (d != _curCalDate)
            {
                if (_curCalDate != DateTime.MinValue)
                {
                    _frozenPrevDayHigh = _curDayHigh;
                    _frozenPrevDayLow = _curDayLow;
                }
                _curCalDate = d;
                _curDayHigh = double.NegativeInfinity;
                _curDayLow = double.PositiveInfinity;
            }
            if (h > _curDayHigh) _curDayHigh = h;
            if (l < _curDayLow) _curDayLow = l;
        }

        // The bias reference: evening leg of the window (Asian-open hour onward)
        // reads the still-forming current calendar day (which IS "yesterday" from
        // the next calendar date's point of view); early-morning leg (before the
        // session end hour) reads yesterday's now-frozen final day.
        private bool TryGetBiasReference(DateTime est, out double refHigh, out double refLow)
        {
            if (est.Hour >= InpAsianStartHourEst) { refHigh = _curDayHigh; refLow = _curDayLow; return !double.IsInfinity(refHigh); }
            if (est.Hour < InpLondonKzEndHourEst) { refHigh = _frozenPrevDayHigh; refLow = _frozenPrevDayLow; return !double.IsNaN(refHigh); }
            refHigh = refLow = double.NaN; return false;
        }

        //================================ BIAS STATE ================================
        private DateTime _biasTradingDay = DateTime.MinValue; // EST calendar date this bias belongs to (today's date once past midnight)
        private bool _sellArmed, _buyArmed;

        // "Today", for bias-reset purposes, is the calendar date whose evening
        // (>= Asian start hour) or early morning (< session end hour) we're
        // currently in -- evening bars belong to TOMORROW's bias day.
        private DateTime BiasDayFor(DateTime est) => est.Hour >= InpAsianStartHourEst ? est.Date.AddDays(1) : est.Date;

        private string CurrentBias()
        {
            if (_sellArmed && _buyArmed) return "conflict";
            if (_sellArmed) return "sell";
            if (_buyArmed) return "buy";
            return "none";
        }

        //================================ LEG / LADDER STATE ================================
        private bool _legActive;
        private bool _legBullish; // true = buy leg (bought off a low), false = sell leg
        private double _legOrigin100;  // the leg's origin swing price (100%)
        private double _legExtreme0;   // the leg's own extreme so far (0%), extends while the leg survives
        private double _zoneLo, _zoneHi; // the tradeable 50%-100% band, in price
        private int _legNo;     // which leg (within today's bias) this is -- increments on every fresh 5m MSS/repeat
        private int _attemptNo; // which entry attempt within the CURRENT leg
        private readonly HashSet<int> _usedEntryMssConfirmIdx = new HashSet<int>(); // 1m MSS confirm-bar indices already traded

        private void ComputeZone()
        {
            double lo = Math.Min(_legOrigin100, _legExtreme0);
            double hi = Math.Max(_legOrigin100, _legExtreme0);
            double mid = lo + (hi - lo) * 0.5;
            // 50%-100% measured back toward the ORIGIN: for a sell leg the origin is
            // the top (premium), so the zone is [mid .. origin-high]; for a buy leg
            // the origin is the bottom (discount), so the zone is [origin-low .. mid].
            if (_legBullish) { _zoneLo = lo; _zoneHi = mid; }
            else { _zoneLo = mid; _zoneHi = hi; }
        }

        private void StartLeg(bool bullish, double origin100, double extreme0, string reasonPrefix)
        {
            _legActive = true;
            _legBullish = bullish;
            _legOrigin100 = origin100;
            _legExtreme0 = extreme0;
            _legNo++;
            _attemptNo = 0;
            ComputeZone();
            Print($"[LEG] {Server.Time:u} bias={CurrentBias()} legNo={_legNo} dir={(bullish ? "BUY" : "SELL")} "
                + $"origin100={origin100:F5} extreme0={extreme0:F5} zone=[{_zoneLo:F5}..{_zoneHi:F5}] ({reasonPrefix})");
        }

        private void AbandonLeg(string reason)
        {
            Print($"[LEG] {Server.Time:u} legNo={_legNo} abandoned -- {reason} -- repeating scenario, watching for a fresh 5m MSS");
            _legActive = false;
        }

        //================================ ENGINE INSTANCES ================================
        private Bars _bars5m, _bars1m;
        private SwingMssEngine _eng5m, _eng1m;
        private int _mss5mPtr; // how many _eng5m.Mss entries already looked at
        private int _mss1mPtr; // how many _eng1m.Mss entries already looked at

        //================================ ORDER / RISK ================================
        // Same risk-based sizing pattern as ctrader/ICT_EA_1.cs's CalcLotSize --
        // proven working in this codebase.
        private double CalcVolume(double riskDistPrice, bool isBuy)
        {
            double riskMoney = Account.Equity * (InpRiskPercent / 100.0);
            if (riskDistPrice <= 0) return 0;
            double riskPips = riskDistPrice / Symbol.PipSize;
            double volume = Symbol.VolumeForFixedRisk(riskMoney, riskPips, RoundingMode.Down);
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            if (volume > Symbol.VolumeInUnitsMax) volume = Symbol.VolumeInUnitsMax;

            TradeType tt = isBuy ? TradeType.Buy : TradeType.Sell;
            double margin = Symbol.GetEstimatedMargin(tt, volume);
            if (margin > 0 && margin > Account.FreeMargin)
            {
                double scaled = volume * (Account.FreeMargin / margin) * 0.95;
                scaled = Symbol.NormalizeVolumeInUnits(scaled, RoundingMode.Down);
                volume = (scaled < Symbol.VolumeInUnitsMin) ? 0 : scaled;
            }
            return volume;
        }

        private void EnterTrade(bool isBuy, double slPrice, string tag)
        {
            double entryPrice = isBuy ? Symbol.Ask : Symbol.Bid;
            double riskDist = isBuy ? (entryPrice - slPrice) : (slPrice - entryPrice);
            if (riskDist <= 0)
            {
                Print($"[ENTRY-SKIPPED] {Server.Time:u} legNo={_legNo} attempt={_attemptNo} -- SL already on wrong side of price (entry={entryPrice:F5} sl={slPrice:F5})");
                return;
            }
            double tpPrice = isBuy ? entryPrice + riskDist * InpRR_Target : entryPrice - riskDist * InpRR_Target;
            double volume = CalcVolume(riskDist, isBuy);
            double slPips = riskDist / Symbol.PipSize;
            double tpPips = Math.Abs(tpPrice - entryPrice) / Symbol.PipSize;

            Print($"[ENTRY] {Server.Time:u} bias={CurrentBias()} legNo={_legNo} attempt={_attemptNo} dir={(isBuy ? "BUY" : "SELL")} "
                + $"zone=[{_zoneLo:F5}..{_zoneHi:F5}] entryPrice={entryPrice:F5} sl={slPrice:F5} tp={tpPrice:F5} "
                + $"slPips={slPips:F1} volume={volume} tag={tag}");

            if (volume <= 0)
            {
                Print($"[ENTRY-SKIPPED] {Server.Time:u} legNo={_legNo} attempt={_attemptNo} -- zero tradeable volume (margin/size constraints)");
                return;
            }

            // NOTE: ICT_EA_1.cs calls ExecuteMarketOrder the same way but discards the
            // return value; capturing it to check .IsSuccessful/.Error is standard
            // cAlgo TradeResult usage but isn't independently exercised elsewhere in
            // this codebase -- verify against your API version if it doesn't compile.
            string label = $"{InpLabel}_L{_legNo}A{_attemptNo}";
            var result = ExecuteMarketOrder(isBuy ? TradeType.Buy : TradeType.Sell, SymbolName, volume, label, slPips, tpPips, label);
            if (result == null || !result.IsSuccessful)
            {
                Print($"[ENTRY-FAILED] {Server.Time:u} legNo={_legNo} attempt={_attemptNo} -- order rejected: {(result?.Error.ToString() ?? "unknown")}");
            }
        }

        // NOTE: Positions.Closed is standard cAlgo Robot API (fires with
        // PositionClosedEventArgs { Position, Reason }) but, like the TradeResult
        // capture above, isn't independently exercised elsewhere in this codebase --
        // check the exact event/args names first if this doesn't compile.
        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var p = args.Position;
            if (p.Label == null || !p.Label.StartsWith(InpLabel)) return;
            Print($"[EXIT] {Server.Time:u} label={p.Label} dir={p.TradeType} entryTime={p.EntryTime:u} entryPrice={p.EntryPrice:F5} "
                + $"exitTime={Server.Time:u} exitPrice={p.CurrentPrice:F5} pnl={p.NetProfit:F2} reason={args.Reason}");
        }

        //================================ BIAS EVALUATION (runs on every closed 1m bar) ================================
        private void EvaluateBias(int i1m)
        {
            DateTime barTimeUtc = _eng1m.T(i1m);
            DateTime est = ToEastern(barTimeUtc);

            UpdateCalendarDay(est, _eng1m.H(i1m), _eng1m.L(i1m));

            DateTime day = BiasDayFor(est);
            if (day != _biasTradingDay)
            {
                _biasTradingDay = day;
                _sellArmed = false;
                _buyArmed = false;
                _legActive = false;
                _legNo = 0;
                _attemptNo = 0;
                Print($"[BIAS] {Server.Time:u} new trading day {day:yyyy-MM-dd} -- bias reset, watching for setup-1a break of yesterday's high/low");
            }

            if (!InBiasWindow(est)) return;
            if (!TryGetBiasReference(est, out double refHigh, out double refLow)) return;

            bool changed = false;
            if (!_sellArmed && _eng1m.H(i1m) > refHigh) { _sellArmed = true; changed = true; }
            if (!_buyArmed && _eng1m.L(i1m) < refLow) { _buyArmed = true; changed = true; }

            if (changed)
                Print($"[BIAS] {Server.Time:u} day={day:yyyy-MM-dd} refHigh={refHigh:F5} refLow={refLow:F5} "
                    + $"price H={_eng1m.H(i1m):F5} L={_eng1m.L(i1m):F5} -> bias now {CurrentBias()}");
        }

        //================================ 5-MINUTE: LEG SEARCH ================================
        private void SearchForLeg()
        {
            string bias = CurrentBias();
            if (bias != "sell" && bias != "buy") return; // no bias, or conflicted -- nothing to trade today
            if (_legActive) return; // already watching one

            bool wantBullish = bias == "buy";
            for (; _mss5mPtr < _eng5m.Mss.Count; _mss5mPtr++)
            {
                var m = _eng5m.Mss[_mss5mPtr];
                DateTime est = ToEastern(_eng5m.T(m.ConfirmIdx));
                if (!InTradingSession(est)) continue; // per spec: the whole mechanism only runs inside our session
                if (m.Bullish != wantBullish) continue; // only MSS agreeing with today's bias starts a leg

                // Leg origin (100%) = the most recent opposite-kind swing before this
                // MSS -- the point that started the impulsive move which just broke
                // structure. Leg extreme (0%) = the breaking candle's own extreme,
                // the leg's current far end (will keep extending as the leg survives).
                int originKind = wantBullish ? 1 : 0; // a bullish MSS's leg started at a swing LOW; bearish at a swing HIGH
                if (!_eng5m.LastSwingBefore(originKind, m.ConfirmIdx, out _, out double originPrice))
                {
                    if (InpVerboseLog) Print($"[LEG-SKIP] {Server.Time:u} 5m MSS at {est:u} had no qualifying origin swing yet -- skipped");
                    continue;
                }
                // Extreme (0%) is the fresh point this MSS just reached: a HIGH for a
                // bullish leg (buying off a low origin, extending upward), a LOW for
                // a bearish leg (selling off a high origin, extending downward).
                double extreme0 = wantBullish ? _eng5m.H(m.ConfirmIdx) : _eng5m.L(m.ConfirmIdx);
                StartLeg(wantBullish, originPrice, extreme0, $"fresh 5m MSS at {est:u}");
                _mss5mPtr++;
                return; // one new leg per call -- the next 5m bar re-enters this search if it's still needed
            }
        }

        // Extends the active leg's own extreme as price keeps pushing further in
        // its direction (still the same leg, zone re-centers), and checks for
        // violation -- price breaking back through the ORIGIN (100%) level, which
        // invalidates the whole premise and triggers "repeat the same scenario."
        private void UpdateLegExtent(int i5m)
        {
            if (!_legActive) return;
            double h = _eng5m.H(i5m), l = _eng5m.L(i5m);

            // Violation: price re-crosses back through the leg's own 100% origin in
            // the direction that undoes it -- for a buy leg (origin = the leg's low),
            // that's price trading back BELOW the origin; for a sell leg (origin =
            // the leg's high), that's price trading back ABOVE the origin.
            bool violated = _legBullish ? (l < _legOrigin100) : (h > _legOrigin100);
            if (violated)
            {
                AbandonLeg($"price re-crossed the leg's own origin ({_legOrigin100:F5})");
                return;
            }

            // Extension: the leg's own extreme (0%) keeps growing while it survives
            // -- a fresh higher high for a buy leg, a fresh lower low for a sell leg.
            bool extended = _legBullish ? (h > _legExtreme0) : (l < _legExtreme0);
            if (extended)
            {
                _legExtreme0 = _legBullish ? h : l;
                ComputeZone();
                if (InpVerboseLog) Print($"[LEG] {Server.Time:u} legNo={_legNo} extended -- new extreme0={_legExtreme0:F5} zone=[{_zoneLo:F5}..{_zoneHi:F5}]");
            }
        }

        //================================ 1-MINUTE: ENTRY TRIGGER ================================
        private void SearchForEntry()
        {
            if (!_legActive) return;
            DateTime est = ToEastern(Server.Time);
            if (!InTradingSession(est)) return;

            for (; _mss1mPtr < _eng1m.Mss.Count; _mss1mPtr++)
            {
                var m = _eng1m.Mss[_mss1mPtr];
                if (_usedEntryMssConfirmIdx.Contains(m.ConfirmIdx)) continue;
                if (m.Bullish != _legBullish) continue; // 1m MSS must agree with the leg's (== bias's) direction

                DateTime mEst = ToEastern(_eng1m.T(m.ConfirmIdx));
                if (!InTradingSession(mEst)) continue;

                double triggerPrice = _eng1m.C(m.ConfirmIdx);
                bool insideZone = triggerPrice >= _zoneLo && triggerPrice <= _zoneHi;
                if (!insideZone) continue; // the whole point: only trade the 50-100% ladder

                _usedEntryMssConfirmIdx.Add(m.ConfirmIdx);
                _attemptNo++;

                // SL: beyond the confirming 1m MSS's own broken swing, plus a small buffer.
                double buffer = InpSlBufferPips * Symbol.PipSize;
                double slPrice = _legBullish ? m.Price - buffer : m.Price + buffer;

                EnterTrade(_legBullish, slPrice, $"1m MSS confirm={m.ConfirmIdx} @ {mEst:u} triggerPrice={triggerPrice:F5}");
            }
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
            _bars5m = GetEngineBars(TimeFrame.Minute5);
            _bars1m = GetEngineBars(TimeFrame.Minute); // cAlgo's 1-minute enum member is "Minute", not "Minute1"
            _eng5m = new SwingMssEngine(_bars5m);
            _eng1m = new SwingMssEngine(_bars1m);

            _bars5m.BarOpened += OnBar5mOpened;
            _bars1m.BarOpened += OnBar1mOpened;
            Positions.Closed += OnPositionClosed;

            // Baseline catch-up so both engines and the bias/calendar trackers are
            // warm immediately, same convention as ICT_EA_1.cs's OnStart().
            _eng1m.CatchUp();
            for (int i = 1; i <= _bars1m.Count - 2; i++) EvaluateBias(i);
            _eng5m.CatchUp();
            for (int i = 1; i <= _bars5m.Count - 2; i++) UpdateLegExtent(i); // no-op until a leg exists; harmless

            Print($"[START] {Server.Time:u} DailyBiasLegLadderEA started. Session=Frankfurt {FrankfurtStartHourEst:00}:00-London KZ {InpLondonKzEndHourEst:00}:00 EST, "
                + $"bias window opens {InpAsianStartHourEst:00}:00 EST.");
        }

        private void OnBar1mOpened(BarOpenedEventArgs args)
        {
            _eng1m.CatchUp();
            int justClosed = _bars1m.Count - 2;
            if (justClosed >= 1) EvaluateBias(justClosed);
            SearchForEntry();
        }

        private void OnBar5mOpened(BarOpenedEventArgs args)
        {
            _eng5m.CatchUp();
            int justClosed = _bars5m.Count - 2;
            if (justClosed >= 1) UpdateLegExtent(justClosed);
            SearchForLeg();
        }
    }
}
