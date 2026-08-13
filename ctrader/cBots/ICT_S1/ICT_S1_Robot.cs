// ICT_S1_Robot — main cBot entry point. Wires every layer together:
//   PoiMarketEngine x3 (Weekly/H4/M5)
//     -> PoiLifecycleTracker x2 (Weekly/H4 -- M5 needs none, spec section 1)
//       -> WeeklyOpportunityEngine / H4SetupEngine
//         -> M5ExecutionEngine -> TradeManager (real cAlgo orders) -> RiskManager
//   JournalManager + VisualizationManager subscribe to every layer's events.
//
// Fetches all three timeframes explicitly via MarketData.GetBars rather
// than relying on whatever chart the cBot happens to be attached to --
// robust regardless of the attached chart's own timeframe.
//
// RESTART/RECONCILIATION (master prompt section 41): stable IDs are
// generated fresh each run (IdGenerator is per-process, not persisted),
// and cAlgo order labels carry the M5AttemptId. On a cBot restart mid-
// session, IN-FLIGHT cAlgo positions/pending orders from a PRIOR run will
// not automatically re-attach to new in-memory M5Attempt objects (their
// labels won't match anything in the fresh IdGenerator sequence) --
// TradeManager's FindAttempt lookups will simply return null for those
// and they'll be left alone (not touched, not duplicated), while OnStart's
// full-history backfill re-derives every WeeklyOpportunity/H4Setup/POI
// state fresh from market data (deterministic, no look-ahead, matches
// section 38's live/backtest consistency requirement). A pre-existing
// live position from before a restart will keep trading under cTrader's
// own SL/TP until it closes, just without S1-side journal linkage for
// that one trade -- flagging this explicitly as a known limitation of
// this first version rather than a silent gap; a persisted-state file
// (writing IdGenerator's counters + open attempt IDs to disk on every
// change, reloaded in OnStart) is the natural follow-up if uninterrupted
// live-restart continuity becomes a requirement.

using System;
using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class ICT_S1_Robot : Robot
    {
        [Parameter("Risk % per trade (of balance)", DefaultValue = 1.0, MinValue = 0.01, MaxValue = 100, Group = "Risk")]
        public double RiskPercent { get; set; }

        [Parameter("Protected-swing violation threshold (pips)", DefaultValue = 0.5, MinValue = 0.01, Group = "Risk")]
        public double ViolationPips { get; set; }

        [Parameter("Visualization mode", DefaultValue = VisualizationMode.Audit, Group = "Visualization")]
        public VisualizationMode VizMode { get; set; }

        [Parameter("Debug logging", DefaultValue = true, Group = "Journal")]
        public bool DebugLogging { get; set; }

        [Parameter("Run ID (blank = auto: Symbol_Timestamp)", DefaultValue = "", Group = "Journal")]
        public string RunIdOverride { get; set; }

        private PoiMarketEngine _weeklyEngine;
        private PoiMarketEngine _h4Engine;
        private PoiMarketEngine _m5Engine;
        private PoiLifecycleTracker _weeklyTracker;
        private PoiLifecycleTracker _h4Tracker;
        private WeeklyOpportunityEngine _weeklyOppEngine;
        private H4SetupEngine _h4SetupEngine;
        private RiskManager _riskManager;
        private TradeManager _tradeManager;
        private M5ExecutionEngine _m5ExecEngine;
        private JournalManager _journal;
        private VisualizationManager _viz;

        protected override void OnStart()
        {
            var weeklyBars = MarketData.GetBars(TimeFrame.Weekly, SymbolName);
            var h4Bars = MarketData.GetBars(TimeFrame.Hour4, SymbolName);
            var m5Bars = MarketData.GetBars(TimeFrame.Minute5, SymbolName);

            _weeklyEngine = new PoiMarketEngine(weeklyBars, "Weekly");
            _h4Engine = new PoiMarketEngine(h4Bars, "H4");
            _m5Engine = new PoiMarketEngine(m5Bars, "M5");

            _weeklyTracker = new PoiLifecycleTracker(_weeklyEngine, "Weekly");
            _h4Tracker = new PoiLifecycleTracker(_h4Engine, "H4");

            _weeklyOppEngine = new WeeklyOpportunityEngine(_weeklyEngine, _weeklyTracker);
            _h4SetupEngine = new H4SetupEngine(_h4Engine, _h4Tracker, _weeklyOppEngine, Symbol.PipSize);

            _riskManager = new RiskManager(Symbol, Account, RiskPercent);
            _tradeManager = new TradeManager(this, Symbol, _riskManager);
            _m5ExecEngine = new M5ExecutionEngine(_m5Engine, _h4SetupEngine, _tradeManager);
            _tradeManager.ExecutionEngine = _m5ExecEngine;

            string runId = string.IsNullOrEmpty(RunIdOverride) ? $"{SymbolName}_{Server.Time:yyyyMMdd_HHmmss}" : RunIdOverride;
            _journal = new JournalManager(runId, DebugLogging) { SymbolName = SymbolName, RiskPercentConfigured = RiskPercent };
            _viz = new VisualizationManager(Chart, VizMode);

            WireEvents();

            // Backfill: process all history already available on each
            // timeframe (deterministic, no look-ahead -- each engine only
            // ever reads bar k using data up to and including bar k, same
            // code path live and historical, per master prompt section 38).
            _weeklyEngine.Update();
            DrainWeeklySide();
            _h4Engine.Update();
            DrainH4Side();
            _m5Engine.Update();
            _m5ExecEngine.Update();
            _h4SetupEngine.CheckProtectedSwingViolations(Symbol.Bid, Symbol.Ask, ViolationPips);

            _journal.Debug($"S1 started on {SymbolName}. Weekly bars={weeklyBars.Count}, H4 bars={h4Bars.Count}, M5 bars={m5Bars.Count}.");
            Print($"ICT_S1 started. Journal: {_journal.RunDirectory}");
        }

        protected override void OnTick()
        {
            _weeklyEngine.Update();
            DrainWeeklySide();

            _h4Engine.Update();
            DrainH4Side();

            _m5Engine.Update();
            _m5ExecEngine.Update();

            _h4SetupEngine.CheckProtectedSwingViolations(Symbol.Bid, Symbol.Ask, ViolationPips);
        }

        protected override void OnStop()
        {
            _journal?.Debug("S1 stopped.");
            _journal?.FlushAll();
        }

        private void DrainWeeklySide()
        {
            var poiEvents = _weeklyTracker.DrainEvents();
            foreach (var ev in poiEvents)
            {
                _journal.LogPoiEvent(ev);
                if (ev.Type == PoiEventType.NewImpact) _viz.DrawPoiImpact(ev.Snapshot);
                else if (ev.Type == PoiEventType.Invalidated || ev.Type == PoiEventType.Retired) _viz.UpdatePoiTerminal(ev.Snapshot);
            }
            _weeklyOppEngine.Update(poiEvents);
            foreach (var ev in _weeklyOppEngine.DrainEvents())
                _journal.LogWeeklyOpportunityEvent(ev);
        }

        private void DrainH4Side()
        {
            var poiEvents = _h4Tracker.DrainEvents();
            foreach (var ev in poiEvents)
            {
                _journal.LogPoiEvent(ev);
                if (ev.Type == PoiEventType.NewImpact) _viz.DrawPoiImpact(ev.Snapshot);
                else if (ev.Type == PoiEventType.Invalidated || ev.Type == PoiEventType.Retired) _viz.UpdatePoiTerminal(ev.Snapshot);
            }
            _h4SetupEngine.Update(poiEvents);
            foreach (var ev in _h4SetupEngine.DrainEvents())
            {
                _journal.LogH4SetupEvent(ev);
                if (ev.Type == H4SetupEventType.Impacted) _viz.DrawProtectedSwing(ev.Setup);
            }
        }

        private void WireEvents()
        {
            _m5ExecEngine.OrderPlaced += a => { _journal.LogOrderEvent(a, "PENDING_ORDER_CREATED", $"@{a.RequestedEntryPrice}"); _viz.DrawAttemptOrder(a); };
            _m5ExecEngine.OrderMoved += a => { _journal.LogOrderEvent(a, "PENDING_ORDER_MOVED", $"@{a.RequestedEntryPrice}"); _viz.DrawAttemptOrder(a); };
            _m5ExecEngine.OrderCancelled += a => _journal.LogOrderEvent(a, "PENDING_ORDER_CANCELLED", "");
            _m5ExecEngine.AttemptFilled += a => _journal.LogOrderEvent(a, "TRADE_ENTERED", $"fill={a.ActualFillPrice}");
            _m5ExecEngine.AttemptClosed += a =>
            {
                var setup = FindSetup(a.H4SetupId);
                var weekly = setup != null ? FindWeekly(setup.WeeklyOpportunityId) : null;
                _journal.LogTradeClosed(a, setup, weekly);
                _viz.DrawAttemptClosed(a);
            };
            _tradeManager.ManualInterventionDetected += (a, detail) => _journal.LogManualIntervention(a, detail);
        }

        private H4Setup FindSetup(string id)
        {
            foreach (var s in _h4SetupEngine.Setups) if (s.H4SetupId == id) return s;
            return null;
        }

        private WeeklyOpportunity FindWeekly(string id)
        {
            foreach (var o in _weeklyOppEngine.Opportunities) if (o.WeeklyOpportunityId == id) return o;
            return null;
        }
    }
}
