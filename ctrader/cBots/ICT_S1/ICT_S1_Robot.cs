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
// CRITICAL 1 FIX (audit 2026-08-13): the previous OnStart processed the
// ENTIRE Weekly history, then the ENTIRE H4 history, then the ENTIRE M5
// history, each in one shot. That let an H4 bar from early in the backtest
// see the fully-completed FUTURE Weekly state (opportunities that, in real
// chronological time, hadn't activated yet at that H4 bar's moment) --
// genuine look-ahead. AdvanceChronologically() below replaces that: it
// repeatedly finds whichever of the three timeframes' NEXT unprocessed bar
// is chronologically earliest, processes exactly that one bar, and
// immediately propagates its downstream effects (Weekly/H4 opportunity and
// setup engines) before moving to the next bar -- possibly on a different
// timeframe. This is the same primitive used for both the OnStart backfill
// and live OnTick processing, so backtest and live share one causally
// correct code path (matches spec section 38's live/backtest consistency
// requirement, now enforced structurally rather than by convention).
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

        // Round 2 fix (audit section 27): cursors for mechanically draining
        // PoiMarketEngine's already-computed Events/Msses lists into the
        // journal (SWING_HIGH/LOW_CONFIRMED, MSS_UP/DOWN) -- no new
        // detection logic, just visibility into data the engine already
        // produces.
        private int _weeklySwingLogIdx, _weeklyMssLogIdx;
        private int _h4SwingLogIdx, _h4MssLogIdx;

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

            // Backfill: chronological, one bar at a time across all three
            // timeframes, never one timeframe's completed future feeding
            // another's past decision (Critical 1 fix -- see file header).
            AdvanceChronologically();

            // Live quotes are only meaningful once backfill has caught up to
            // "now" -- checking protected-swing violations against current
            // Bid/Ask DURING the historical catch-up loop would itself be a
            // look-ahead bug (today's price against historically-old
            // setups). One check here, after backfill completes and every
            // surviving setup is genuinely current, is correct.
            _h4SetupEngine.CheckProtectedSwingViolations(Symbol.Bid, Symbol.Ask, Server.Time, ViolationPips);

            _journal.Debug($"S1 started on {SymbolName}. Weekly bars={weeklyBars.Count}, H4 bars={h4Bars.Count}, M5 bars={m5Bars.Count}.");
            Print($"ICT_S1 started. Journal: {_journal.RunDirectory}");
        }

        protected override void OnTick()
        {
            AdvanceChronologically();
            _h4SetupEngine.CheckProtectedSwingViolations(Symbol.Bid, Symbol.Ask, Server.Time, ViolationPips);
        }

        // The chronological scheduler (Critical 1 fix). Repeatedly advances
        // whichever of Weekly/H4/M5 has the earliest next unprocessed bar,
        // one bar at a time, propagating that bar's downstream effects
        // immediately before considering the next bar on any timeframe.
        // Weekly wins exact-timestamp ties over H4, H4 over M5 (higher
        // timeframe causality resolved first) -- ties are rare (only at
        // exactly-aligned bar-open boundaries) and the loop naturally
        // revisits on the next iteration regardless.
        private void AdvanceChronologically()
        {
            while (true)
            {
                DateTime? tW = _weeklyEngine.PeekNextBarTime();
                DateTime? tH = _h4Engine.PeekNextBarTime();
                DateTime? tM = _m5Engine.PeekNextBarTime();
                if (tW == null && tH == null && tM == null) break;

                DateTime earliest = DateTime.MaxValue;
                if (tW != null && tW.Value < earliest) earliest = tW.Value;
                if (tH != null && tH.Value < earliest) earliest = tH.Value;
                if (tM != null && tM.Value < earliest) earliest = tM.Value;

                if (tW != null && tW.Value == earliest)
                {
                    _weeklyEngine.ProcessOneBar();
                    DrainWeeklySide();
                }
                else if (tH != null && tH.Value == earliest)
                {
                    _h4Engine.ProcessOneBar();
                    DrainH4Side();
                }
                else
                {
                    _m5Engine.ProcessOneBar();
                }

                // Re-evaluated after every single bar, on any timeframe --
                // an H4 termination or a fresh H4 impact must be visible to
                // M5 execution before the next bar (of any timeframe) is
                // processed, not just after an M5 bar happens to close.
                _m5ExecEngine.Update();
            }
        }

        protected override void OnStop()
        {
            // Part 25/26: still-open POIs/H4Setups at run end must extend
            // to the real current simulated time, not be left at whatever
            // their last event happened to draw -- not silently truncated,
            // not left implying an open-ended future.
            if (_viz != null && _weeklyTracker != null && _h4Tracker != null)
            {
                _viz.FinalizeOpenPois(FindOpenPois(_weeklyTracker), Server.Time);
                _viz.FinalizeOpenPois(FindOpenPois(_h4Tracker), Server.Time);
            }
            if (_viz != null && _h4SetupEngine != null)
                _viz.FinalizeOpenSetups(FindOpenSetups(), Server.Time);

            _journal?.Debug("S1 stopped.");
            _journal?.FlushAll();
        }

        private System.Collections.Generic.IEnumerable<S1PoiSnapshot> FindOpenPois(PoiLifecycleTracker tracker)
        {
            foreach (var s in tracker.AllSnapshots)
                if (!s.IsTerminal) yield return s;
        }

        private System.Collections.Generic.IEnumerable<H4Setup> FindOpenSetups()
        {
            foreach (var s in _h4SetupEngine.Setups)
                if (s.Status != H4SetupStatus.Terminated && s.Status != H4SetupStatus.Superseded) yield return s;
        }

        private void DrainSwingAndMssLog(PoiMarketEngine engine, string timeframe, ref int swingIdx, ref int mssIdx)
        {
            for (; swingIdx < engine.Events.Count; swingIdx++)
            {
                var e = engine.Events[swingIdx];
                var t = e.ConfirmIdx >= 0 && e.ConfirmIdx < engine.BT.Count ? engine.BT[e.ConfirmIdx] : default(DateTime);
                _journal.LogSwingEvent(timeframe, e.Kind == 0, e.Price, t);
            }
            for (; mssIdx < engine.Msses.Count; mssIdx++)
            {
                var m = engine.Msses[mssIdx];
                var t = m.AtIdx >= 0 && m.AtIdx < engine.BT.Count ? engine.BT[m.AtIdx] : default(DateTime);
                _journal.LogMssEvent(timeframe, m.ToUp, m.Price, t);
            }
        }

        private void DrainWeeklySide()
        {
            DrainSwingAndMssLog(_weeklyEngine, "Weekly", ref _weeklySwingLogIdx, ref _weeklyMssLogIdx);
            _weeklyTracker.Update();
            var poiEvents = _weeklyTracker.DrainEvents();
            foreach (var ev in poiEvents)
            {
                _journal.LogPoiEvent(ev);
                if (ev.Type == PoiEventType.NewImpact) _viz.DrawPoiImpact(ev.Snapshot);
                else if (ev.Type == PoiEventType.Retouch) _viz.UpdatePoiRetouch(ev.Snapshot, ev.Time);
                else if (ev.Type == PoiEventType.Invalidated || ev.Type == PoiEventType.Retired) _viz.UpdatePoiTerminal(ev.Snapshot, ev.Time);
            }
            _weeklyOppEngine.Update(poiEvents);
            foreach (var ev in _weeklyOppEngine.DrainEvents())
                _journal.LogWeeklyOpportunityEvent(ev);
            foreach (var pev in _weeklyOppEngine.DrainPhaseEvents())
            {
                _journal.LogPhaseTransition(pev);
                _viz.DrawPhaseTransition(pev);
            }
        }

        private void DrainH4Side()
        {
            DrainSwingAndMssLog(_h4Engine, "H4", ref _h4SwingLogIdx, ref _h4MssLogIdx);
            _h4Tracker.Update();
            var poiEvents = _h4Tracker.DrainEvents();
            foreach (var ev in poiEvents)
            {
                _journal.LogPoiEvent(ev);
                if (ev.Type == PoiEventType.NewImpact) _viz.DrawPoiImpact(ev.Snapshot);
                else if (ev.Type == PoiEventType.Retouch) _viz.UpdatePoiRetouch(ev.Snapshot, ev.Time);
                else if (ev.Type == PoiEventType.Invalidated || ev.Type == PoiEventType.Retired) _viz.UpdatePoiTerminal(ev.Snapshot, ev.Time);
            }
            _h4SetupEngine.Update(poiEvents);
            foreach (var ev in _h4SetupEngine.DrainEvents())
            {
                _journal.LogH4SetupEvent(ev);
                if (ev.Type == H4SetupEventType.Impacted)
                {
                    _viz.DrawProtectedSwing(ev.Setup, ev.Time);
                    _viz.DrawH4PoiJoinedReaction(ev);
                }
                else if (ev.Type == H4SetupEventType.Retouched)
                {
                    _viz.UpdateH4SetupActivity(ev.Setup, ev.Time);
                    _viz.DrawH4PoiJoinedReaction(ev);
                }
                else if (ev.Type == H4SetupEventType.Terminated)
                {
                    _viz.UpdateH4SetupTerminal(ev.Setup, ev.Time);
                }
                else if (ev.Type == H4SetupEventType.Superseded)
                {
                    _viz.UpdateH4SetupSuperseded(ev.Setup, ev.Time);
                }
            }
            foreach (var rej in _h4SetupEngine.DrainRejections())
                _journal.LogRejection(rej);
        }

        private void WireEvents()
        {
            _m5ExecEngine.OrderPlaced += a => { _journal.LogOrderEvent(a, "PENDING_ORDER_CREATED", $"@{a.RequestedEntryPrice}", Server.Time); _viz.DrawAttemptOrder(a, Server.Time); };
            _m5ExecEngine.OrderMoved += a =>
            {
                // Round 2 fix (audit sections 3/27): explicit A->B swing
                // transition instead of a silent overwrite -- this is what
                // makes clear in the journal that a later PendingOrderCreatedTime
                // legitimately supersedes an earlier one, rather than looking
                // like "order created before its authorizing swing".
                string note = $"@{a.RequestedEntryPrice} | entry {a.PreviousEntrySwingType}@{a.PreviousEntrySwingPrice} ({a.PreviousEntrySwingTime:O}) -> {a.EntrySwingType}@{a.EntrySwingPrice} ({a.EntrySwingTime:O}); stop {a.PreviousStopSwingType}@{a.PreviousStopSwingPrice} ({a.PreviousStopSwingTime:O}) -> {a.StopSwingType}@{a.StopSwingPrice} ({a.StopSwingTime:O})";
                _journal.LogOrderEvent(a, "ORDER_MOVED_FROM_SWING_A_TO_SWING_B", note, Server.Time);
                _viz.DrawAttemptOrder(a, Server.Time);
            };
            _m5ExecEngine.OrderCancelled += a => _journal.LogOrderEvent(a, "PENDING_ORDER_CANCELLED_INTERNAL", a.LastCancellationReason ?? "", Server.Time);
            _m5ExecEngine.AttemptFilled += a => { _journal.LogOrderEvent(a, "TRADE_ENTERED", $"fill={a.ActualFillPrice}", Server.Time); _viz.DrawAttemptFilled(a, a.EntryTime ?? Server.Time); };
            _m5ExecEngine.M5ExecutionCompleted += setup => _journal.LogM5ExecutionCompleted(setup, setup.M5ExecutionCompletedTime ?? Server.Time);
            _m5ExecEngine.AttemptClosed += a =>
            {
                var setup = FindSetup(a.H4SetupId);
                var weekly = setup != null ? FindWeekly(setup.WeeklyOpportunityId) : null;
                _journal.LogTradeClosed(a, setup, weekly, _weeklyOppEngine.Phase);
                _viz.DrawAttemptClosed(a, Server.Time);
            };
            _tradeManager.ManualInterventionDetected += (a, detail) => _journal.LogManualIntervention(a, detail, Server.Time);
            _m5ExecEngine.M5ExecutionActivated += (setup, t) => _journal.LogM5ExecutionActivated(setup, t);
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
