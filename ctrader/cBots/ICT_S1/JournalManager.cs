// ICT_S1 — JournalManager. Spec: docs/s1_ea_specification.md section 11
// (master prompt sections 33-36).
//
// Exports three CSVs (TradeSummary, OpportunitySummary, EventLog) plus an
// optional human-readable debug log. UTC timestamps throughout.
//
// FILE PATH: cAlgo Robots have standard .NET File I/O access on the
// desktop client -- this writes under
// Environment.SpecialFolder.MyDocuments\cAlgo\S1\<RunId>\. Confirm this
// resolves sensibly in your actual environment (Desktop vs Cloud/VPS can
// differ) -- flagged per spec section 24, not silently assumed.
//
// ROUND 2 (audit section 27): SWING_HIGH_CONFIRMED / SWING_LOW_CONFIRMED /
// MSS_UP / MSS_DOWN / M5_EXECUTION_ACTIVATED are now wired (see
// ICT_S1_Robot.DrainSwingAndMssLog and M5ExecutionEngine.M5ExecutionActivated).
// M5_SWING_SELECTED was considered and deliberately NOT added as a separate
// event: every successful swing selection immediately produces a
// PENDING_ORDER_CREATED or ORDER_MOVED_FROM_SWING_A_TO_SWING_B row that
// already carries the full entry+stop swing pairing -- a distinct event
// would duplicate that information under a different name, not add new
// visibility.
//
// H4 reaction grouping is now resolved (strategy owner clarification,
// 2026-08-13 -- see H4SetupEngine.HandleNewImpact) -- the existing
// H4_IMPACTED/H4_RETOUCHED EventLog rows (from LogH4SetupEvent) already
// carry this distinction in their Notes field ("new H4 reaction, protected
// swing X" vs "joined live reaction -- same protected swing X"), so no
// separate H4_REACTION_CREATED/H4_POI_JOINED_REACTION event types were
// needed on top of that.
//
// KNOWN GAPS still explicit, not silently dropped: MFE/MAE need a
// tick-by-tick high-water-mark tracker per open position -- a real new
// feature, not a fix to existing wrong behavior, so left out of this
// repair pass. SpreadAtEntry is captured; Slippage and Commission are left
// blank until the exact data the installed API exposes for these is
// confirmed against a real build.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace cAlgo.Robots.ICT_S1
{
    public class JournalManager
    {
        private readonly string _tradeSummaryPath;
        private readonly string _opportunityHistoryPath;
        private readonly string _opportunitySummaryPath;
        private readonly string _eventLogPath;
        private readonly string _debugLogPath;
        private readonly string _phaseHistoryPath;
        private readonly string _h4PhaseRejectionPath;
        private readonly bool _debugLoggingEnabled;

        private readonly List<string> _eventLogBuffer = new List<string>();
        private readonly List<string> _tradeSummaryBuffer = new List<string>();
        private readonly List<string> _opportunityHistoryBuffer = new List<string>();
        private readonly List<string> _debugBuffer = new List<string>();
        private readonly List<string> _phaseHistoryBuffer = new List<string>();
        private readonly List<string> _h4PhaseRejectionBuffer = new List<string>();
        // Part 23 fix: OpportunitySummary must be exactly ONE row per
        // WeeklyOpportunityID (a real summary), not a repeated-append log --
        // that repeated-append behavior moved to OpportunityHistory instead.
        // This dictionary holds each opportunity's LATEST row; the whole
        // summary file is rewritten from it on every change so the file is
        // always current without needing an update-in-place CSV writer.
        private readonly Dictionary<string, string> _latestOpportunityRow = new Dictionary<string, string>();
        private readonly List<string> _opportunityIdOrder = new List<string>();

        private const string EventLogHeader = "Timestamp,Symbol,Timeframe,EventType,Direction,WeeklyOpportunityID,PoiClusterID,POIID,H4SetupID,M5AttemptID,TradeID,Price,POITop,POIBottom,PreviousState,NewState,Reason,Notes";

        // Part 22 forensic-completeness fix: full Weekly/H4/M5/execution
        // lineage on every trade row, so a reviewer can answer "why did
        // this exact trade exist" from this file alone -- WeeklyPoiIds/
        // H4PoiIds list every supporting POI (not just the bounding box),
        // ControlAtTradeTime/ControlSourcePoiId/ControlContextId capture
        // the governing DirectionalPhaseContext's state at journal-write
        // time (concurrency mandate, 2026-08-13, Owner Answer A: Control is
        // scoped per-context, not one global phase as the immediately-prior
        // round had it -- ControlContextId records WHICH context),
        // AuthorizingDirectionalContextIds lists every context that
        // actually authorized this H4 reaction (supplementing, not
        // replacing, SupportingWeeklyOpportunityIDs -- Part 38 of the
        // concurrency mandate), H4ProtectedSwingIdx is the stable reaction
        // identity (Part 15),
        // M5ExecutionActivationTime is the swing-pairing window boundary,
        // and ExitPriceSource proves which of HistoricalTrade/QuoteFallback
        // actually supplied ExitPrice (Part 21).
        //
        // Forensic-audit round, Part 50 ("preserve and enrich if necessary
        // -- do not weaken existing logging"): the M5-completion swing
        // detail (PostEntryContinuationSwing*/CompletionPullbackSwing*) and
        // M5ExecutionCompletionReason already existed on H4Setup and were
        // already visible informally inside the EventLog's free-text Note
        // column (M5_EXECUTION_COMPLETED_STRUCTURALLY row) -- these trailing
        // columns are a pure enrichment, surfacing the same already-computed
        // fields as structured, machine-checkable data instead of a string a
        // reviewer would otherwise have to parse. Same reasoning for the
        // trailing H4Supersede* columns (Part 49): H4Setup already carries
        // SupersededBySwingIdx/Price/SupersededTime (Task #31/prior round);
        // rather than stand up a whole 5th dedicated CSV file duplicating
        // data that already lives on the H4Setup object and is already
        // reconcilable via H4SetupID/H4SetupStatusAtClose, they are appended
        // here so every closed trade's row states plainly whether -- and by
        // what new swing -- its own H4 reaction was later superseded. No
        // existing column was reordered or removed.
        private const string TradeSummaryHeader = "StrategyVersion,Symbol,TradeID,PositionID,WeeklyOpportunityID,SupportingWeeklyOpportunityIDs,WeeklyPoiIds,PoiClusterID,H4SetupID,H4PoiIds,H4ProtectedSwingIdx,M5AttemptID,AttemptNumber," +
            "TradeDirection,WeeklyOpportunityDirection,WeeklyActivationTime,WeeklyPOITop,WeeklyPOIBottom,ControlAtTradeTime,ControlSourcePoiId,ControlContextId,AuthorizingDirectionalContextIds," +
            "H4Route,H4ProtectedSwingType,H4ProtectedSwingPrice,H4ProtectedSwingTime,WeeklyRetouchNumber,H4SetupStatusAtClose,M5ExecutionStateAtClose," +
            "M5ExecutionActivationTime,M5EntrySwingType,M5EntrySwingPrice,M5EntrySwingTime,M5StopSwingType,M5StopSwingPrice,M5StopSwingTime," +
            "FirstPendingOrderCreatedTime,PendingOrderCreatedTime,PendingOrderModificationCount,EntryTime,RequestedEntryPrice,ActualFillPrice," +
            "SLPrice,TPPrice,TargetR,RiskPercent,PositionVolume," +
            "ExitTime,ExitPrice,ExitPriceSource,ExitReason,GrossPnL,NetPnL,RealizedR," +
            "M5ExecutionCompletedTime,M5ExecutionCompletionReason,PostEntryContinuationSwingIdx,PostEntryContinuationSwingPrice,PostEntryContinuationSwingTime," +
            "CompletionPullbackSwingIdx,CompletionPullbackSwingPrice,CompletionPullbackSwingTime," +
            "H4SupersededBySwingIdx,H4SupersededBySwingPrice,H4SupersededTime";

        // Same schema for both files -- History is the append-every-change
        // log, Summary is the one-row-latest-state view of it. No Control
        // columns here: Control is not a WeeklyOpportunity property -- see
        // S1_DirectionalPhaseHistory_<run>.csv for the governing
        // DirectionalPhaseContext(s)' transition history instead.
        private const string OpportunitySummaryHeader = "Symbol,WeeklyOpportunityID,Direction,ActivationTime,Status,TerminationTime,TerminationReason," +
            "SupportingPoiCount,H4SetupCount,RetouchCounter";

        // Part 47: full DirectionalPhaseContext transition history -- every
        // field needed to spot a misclassified source POI (e.g. an Old-
        // family POI that shouldn't have reactivated Neutral) immediately,
        // without cross-referencing other files. ContextId column added
        // (concurrency mandate, Owner Answer A): with Control scoped per
        // context rather than one shared global phase, a row is meaningless
        // without saying WHICH context transitioned. ContextOriginMssToUp/
        // ContextOriginMssPrice let a reviewer see which Weekly Market
        // Structure Shift (if any -- blank for the one pre-MSS bootstrap
        // context) this context's own boundary came from, directly on every
        // row, without cross-referencing a separate context-registry file
        // (none exists -- Contexts live only in memory/these rows).
        private const string PhaseHistoryHeader = "Symbol,Timestamp,ContextId,ContextOriginMssToUp,ContextOriginMssPrice,PreviousState,NewState," +
            "SourcePoiId,SourcePoiType,SourcePoiDirection,SourcePoiFamily,SourcePoiOriginBucket,SourcePoiLifecycleState," +
            "SourceReactionSwingType,SourceReactionSwingPrice,SourceReactionSwingTime,TransitionReason";

        // Part 48: every H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL rejection
        // with full phase-forensic context -- proves numerically WHY each
        // SELL (or BUY) candidate was suppressed, from this file alone.
        // Concurrency mandate update: the single PhaseStateAtRejection/
        // PhaseSourcePoiId columns no longer make sense once Control is
        // per-context -- replaced with the semicolon-joined, index-aligned
        // TemporallyValidContextIDs/TemporallyValidContextStates (one entry
        // per WeeklyID in TemporallyValidSameDirectionWeeklyIDs), so a
        // reviewer can see EXACTLY which context each candidate belonged to
        // and why that specific context didn't permit it.
        private const string H4PhaseRejectionHeader = "Symbol,Timestamp,H4PoiId,H4PoiType,Direction,H4SourceSwingIdx," +
            "TemporallyValidSameDirectionWeeklyIDs,TemporallyValidContextIDs,TemporallyValidContextStates,RejectionNote";

        public string SymbolName;
        public string StrategyVersion = "S1-v1";
        public double RiskPercentConfigured;

        public JournalManager(string runId, bool debugLoggingEnabled)
        {
            _debugLoggingEnabled = debugLoggingEnabled;
            string baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "cAlgo", "S1", runId);
            Directory.CreateDirectory(baseDir);

            _tradeSummaryPath = Path.Combine(baseDir, "S1_TradeSummary_" + runId + ".csv");
            _opportunityHistoryPath = Path.Combine(baseDir, "S1_OpportunityHistory_" + runId + ".csv");
            _opportunitySummaryPath = Path.Combine(baseDir, "S1_OpportunitySummary_" + runId + ".csv");
            _eventLogPath = Path.Combine(baseDir, "S1_EventLog_" + runId + ".csv");
            _debugLogPath = Path.Combine(baseDir, "S1_Debug_" + runId + ".log");
            _phaseHistoryPath = Path.Combine(baseDir, "S1_DirectionalPhaseHistory_" + runId + ".csv");
            _h4PhaseRejectionPath = Path.Combine(baseDir, "S1_H4PhaseRejections_" + runId + ".csv");

            System.IO.File.WriteAllText(_eventLogPath, EventLogHeader + Environment.NewLine);
            System.IO.File.WriteAllText(_tradeSummaryPath, TradeSummaryHeader + Environment.NewLine);
            System.IO.File.WriteAllText(_opportunityHistoryPath, OpportunitySummaryHeader + Environment.NewLine);
            System.IO.File.WriteAllText(_opportunitySummaryPath, OpportunitySummaryHeader + Environment.NewLine);
            System.IO.File.WriteAllText(_phaseHistoryPath, PhaseHistoryHeader + Environment.NewLine);
            System.IO.File.WriteAllText(_h4PhaseRejectionPath, H4PhaseRejectionHeader + Environment.NewLine);
        }

        public string RunDirectory => Path.GetDirectoryName(_eventLogPath);

        // ---------------- Event Log ----------------
        public void LogPoiEvent(PoiLifecycleEvent ev)
        {
            var s = ev.Snapshot;
            WriteEventRow(ev.Time, s.Timeframe, "POI_" + ev.Type.ToString().ToUpperInvariant(), s.Direction.ToString(),
                s.WeeklyOpportunityId, s.PoiClusterId, s.S1PoiId, "", "", "",
                "", s.Zt, s.Zb, "", s.LifecycleState.ToString(), ev.Note, "");
        }

        public void LogWeeklyOpportunityEvent(WeeklyOpportunityEvent ev)
        {
            var o = ev.Opportunity;
            WriteEventRow(ev.Time, "Weekly", "WEEKLY_" + ev.Type.ToString().ToUpperInvariant(), o.Direction.ToString(),
                o.WeeklyOpportunityId, o.SupportingCluster?.PoiClusterId ?? "", ev.TriggeringPoi?.S1PoiId ?? "", "", "", "",
                "", "", "", "", o.Status.ToString(), ev.Note, "");
            WriteOpportunityRow(o);
        }

        // Concurrency mandate (2026-08-13, Owner Answer A), Parts 21-34, 49:
        // a DirectionalPhaseContext's own transition history -- "the report
        // must make Control understandable as market behavior, not just
        // object mutation" (Part 49). Direction column is blank (a phase
        // transition isn't itself a Buy/Sell POI event); NewState/
        // PreviousState carry the actual transition. EventLog's PoiId
        // column (7th positional arg) now carries ContextId (not
        // SourcePoiId) since a reader needs to know WHICH context
        // transitioned at least as much as which POI triggered it -- the
        // dedicated PhaseHistory row below carries both explicitly.
        public void LogPhaseTransition(DirectionalPhaseEvent ev)
        {
            WriteEventRow(ev.Time, "Weekly", "DIRECTIONAL_PHASE_CHANGED", "",
                "", "", ev.ContextId ?? "", "", "", "",
                "", "", "", ev.OldState?.ToString(), ev.NewState.ToString(), ev.Reason, "");
            LogPhaseHistoryRow(ev);
        }

        // Part 47: dedicated file, full forensic detail per transition --
        // proves at a glance whether a source POI was correctly classified
        // (e.g. an Old-family POI must never appear here as a reactivation
        // source), and (concurrency mandate) which context it happened in.
        private void LogPhaseHistoryRow(DirectionalPhaseEvent ev)
        {
            var s = ev.SourcePoi;
            var row = string.Join(",", new[]
            {
                Csv(SymbolName), Csv(ev.Time.ToString("O")), Csv(ev.ContextId), Csv(ev.ContextOriginMssToUp?.ToString()), Csv(ev.ContextOriginMssPrice?.ToString()), Csv(ev.OldState?.ToString()), Csv(ev.NewState.ToString()),
                Csv(s?.S1PoiId), Csv(s?.TypeAtActivation.ToString()), Csv(s?.Direction.ToString()), Csv(s?.Family.ToString()), Csv(s?.OriginBucket.ToString()), Csv(s?.LifecycleState.ToString()),
                Csv(s?.RelevantReactionSwingType?.ToString()), Csv(s?.RelevantReactionSwingPrice?.ToString()), Csv(s?.RelevantReactionSwingConfirmationTime?.ToString("O")), Csv(ev.Reason)
            });
            _phaseHistoryBuffer.Add(row);
            if (_phaseHistoryBuffer.Count >= 20) FlushPhaseHistory();
        }

        // Round 2 fix (audit section 27): raw swing-confirmation / MSS
        // events, mechanically drained from PoiMarketEngine.Events/Msses
        // (already-computed data, not a new detection rule) -- previously a
        // documented gap ("EventLog has no SWING_HIGH_CONFIRMED/MSS_UP/DOWN
        // rows"), now closed.
        public void LogSwingEvent(string timeframe, bool isHigh, double price, DateTime time)
        {
            WriteEventRow(time, timeframe, isHigh ? "SWING_HIGH_CONFIRMED" : "SWING_LOW_CONFIRMED", "",
                "", "", "", "", "", "",
                price, "", "", "", "", "", "");
        }

        public void LogMssEvent(string timeframe, bool toUp, double price, DateTime time)
        {
            WriteEventRow(time, timeframe, toUp ? "MSS_UP" : "MSS_DOWN", "",
                "", "", "", "", "", "",
                price, "", "", "", "", "", "");
        }

        public void LogM5ExecutionActivated(H4Setup setup, DateTime time)
        {
            WriteEventRow(time, "M5", "M5_EXECUTION_ACTIVATED", setup.Direction.ToString(),
                setup.WeeklyOpportunityId, setup.SupportingCluster?.PoiClusterId, "", setup.H4SetupId, "", "",
                "", "", "", "", setup.Status.ToString(), "M5 swing-pairing window opened", "");
        }

        // Strategy clarification (follow-up round), Parts 6/11/38: the
        // execution thesis proved itself structurally -- distinct from any
        // individual attempt's own SL/TP outcome, and distinct from the H4
        // reaction's own lifecycle state (still Impacted; an open position,
        // if any, is untouched).
        public void LogM5ExecutionCompleted(H4Setup setup, DateTime time)
        {
            WriteEventRow(time, "M5", "M5_EXECUTION_COMPLETED_STRUCTURALLY", setup.Direction.ToString(),
                setup.WeeklyOpportunityId, setup.SupportingCluster?.PoiClusterId, "", setup.H4SetupId, "", "",
                "", "", "", "", setup.M5ExecutionState.ToString(), setup.M5ExecutionCompletionReason, "");
        }

        public void LogH4SetupEvent(H4SetupEvent ev)
        {
            var h = ev.Setup;
            WriteEventRow(ev.Time, "H4", "H4_" + ev.Type.ToString().ToUpperInvariant(), h.Direction.ToString(),
                h.WeeklyOpportunityId, h.SupportingCluster?.PoiClusterId ?? "", ev.TriggeringPoi?.S1PoiId ?? "", h.H4SetupId, "", "",
                "", "", "", "", h.Status.ToString(), ev.Note, "");
        }

        // `time` is the actual simulated event time (Server.Time from the
        // caller) -- not DateTime.UtcNow (audit section 32).
        public void LogOrderEvent(M5Attempt attempt, string eventType, string note, DateTime time)
        {
            WriteEventRow(time, "M5", eventType, attempt.Direction.ToString(),
                "", "", "", attempt.H4SetupId, attempt.M5AttemptId, attempt.TradeId ?? "",
                attempt.RequestedEntryPrice, "", "", "", attempt.Status.ToString(), note, "");
        }

        public void LogManualIntervention(M5Attempt attempt, string detail, DateTime time)
        {
            WriteEventRow(time, "M5", "MANUAL_INTERVENTION_DETECTED", attempt.Direction.ToString(),
                "", "", "", attempt.H4SetupId, attempt.M5AttemptId, attempt.TradeId ?? "",
                "", "", "", "", attempt.Status.ToString(), detail, "");
        }

        // Audit section 28 -- proves the EA is filtering correctly, not
        // just showing what it accepted. One row per rejected candidate.
        public void LogRejection(RejectionEvent rej)
        {
            WriteEventRow(rej.Time, "H4", rej.Code.ToString(), rej.Direction.ToString(),
                "", "", rej.PoiId, "", "", "",
                "", "", "", "", "REJECTED", rej.Note, "");

            // Part 48: dedicated file, ONLY for the phase-suppression path
            // (the one with real phase-forensic content to show) -- proves
            // numerically why each candidate was suppressed.
            if (rej.Code == RejectionCode.H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL)
                LogH4PhaseRejectionRow(rej);
        }

        private void LogH4PhaseRejectionRow(RejectionEvent rej)
        {
            // Concurrency mandate: three parallel/index-aligned semicolon-
            // joined lists instead of one shared PhaseStateAtRejection --
            // each temporally-valid candidate can belong to a different
            // context now.
            string weeklyIds = rej.TemporallyValidSameDirectionWeeklyIds != null ? string.Join(";", rej.TemporallyValidSameDirectionWeeklyIds) : "";
            string contextIds = rej.TemporallyValidContextIds != null ? string.Join(";", rej.TemporallyValidContextIds) : "";
            string contextStates = rej.TemporallyValidContextStates != null ? string.Join(";", rej.TemporallyValidContextStates) : "";
            var row = string.Join(",", new[]
            {
                Csv(SymbolName), Csv(rej.Time.ToString("O")), Csv(rej.PoiId), Csv(rej.PoiType?.ToString()), Csv(rej.Direction.ToString()), Csv(rej.SourceSwingIdx.ToString()),
                Csv(weeklyIds), Csv(contextIds), Csv(contextStates), Csv(rej.Note)
            });
            _h4PhaseRejectionBuffer.Add(row);
            if (_h4PhaseRejectionBuffer.Count >= 20) FlushH4PhaseRejection();
        }

        private void WriteEventRow(DateTime time, string timeframe, string eventType, string direction,
            string weeklyId, string clusterId, string poiId, string h4SetupId, string m5AttemptId, string tradeId,
            object price, object top, object bottom, string prevState, string newState, string reason, string notes)
        {
            var row = string.Join(",", new[]
            {
                Csv(time.ToString("O")), Csv(SymbolName), Csv(timeframe), Csv(eventType), Csv(direction),
                Csv(weeklyId), Csv(clusterId), Csv(poiId), Csv(h4SetupId), Csv(m5AttemptId), Csv(tradeId),
                Csv(price?.ToString()), Csv(top?.ToString()), Csv(bottom?.ToString()),
                Csv(prevState), Csv(newState), Csv(reason), Csv(notes)
            });
            _eventLogBuffer.Add(row);
            if (_eventLogBuffer.Count >= 50) FlushEventLog();
        }

        // ---------------- Trade Summary ----------------
        // `phase` (concurrency mandate, 2026-08-13, Owner Answer A): the
        // specific DirectionalPhaseContext that governed `weekly` (the
        // trade's own primary Weekly opportunity) -- resolved by the
        // caller via WeeklyOpportunityEngine.GetContext(weekly.
        // DirectionalContextId), since JournalManager itself has no
        // reference to the engine. ControlAtTradeTime/ControlSourcePoiId/
        // ControlContextId reflect THAT context's state at journal-write
        // time -- not a single shared global phase, which no longer exists.
        public void LogTradeClosed(M5Attempt attempt, H4Setup setup, WeeklyOpportunity weekly, DirectionalPhaseContext phase)
        {
            // Weekly zone bounding box across all supporting cluster members
            // -- lets the trade be checked directly against the chart
            // without needing to cross-reference the POI event log.
            string weeklyTop = "", weeklyBottom = "";
            if (weekly?.SupportingCluster?.Members != null && weekly.SupportingCluster.Members.Count > 0)
            {
                double top = double.MinValue, bottom = double.MaxValue;
                foreach (var m in weekly.SupportingCluster.Members)
                {
                    if (m.Zt > top) top = m.Zt;
                    if (m.Zb < bottom) bottom = m.Zb;
                }
                weeklyTop = top.ToString();
                weeklyBottom = bottom.ToString();
            }

            // Round 2 fix (audit section 29): TradeId is consumed from the
            // attempt (assigned once, at fill time by TradeManager) -- never
            // regenerated here. A closed attempt that somehow never got a
            // TradeId (shouldn't happen -- every ClosedTP/ClosedSL/ClosedManual
            // attempt passed through OnPendingOrderFilled first) still gets
            // one rather than leaving the row blank.
            string tradeId = attempt.TradeId ?? IdGenerator.NextTradeId();

            // Part 22 forensic-completeness fix: list every supporting POI
            // on both layers, not just the Weekly bounding box -- a reviewer
            // can now trace every POI that fed this trade's authorization
            // without cross-referencing the EventLog.
            string weeklyPoiIds = JoinPoiIds(weekly?.SupportingCluster?.Members);
            string h4PoiIds = JoinPoiIds(setup?.SupportingCluster?.Members);
            // Part 22 + follow-up multiplicity clarification: full Weekly
            // lineage -- every Weekly opportunity that supports this trade's
            // H4 reaction, not just the display-primary one in WeeklyOpportunityID.
            string supportingWeeklyIds = setup?.SupportingWeeklyOpportunityIds != null ? string.Join(";", setup.SupportingWeeklyOpportunityIds) : "";
            // Concurrency mandate Part 38: every context that authorized
            // this reaction (supplements, does not replace, the Weekly
            // lineage above).
            string authorizingContextIds = setup?.SupportingDirectionalContextIds != null ? string.Join(";", setup.SupportingDirectionalContextIds) : "";

            var row = string.Join(",", new[]
            {
                Csv(StrategyVersion), Csv(SymbolName), Csv(tradeId), Csv(attempt.PositionId?.ToString()),
                Csv(weekly?.WeeklyOpportunityId), Csv(supportingWeeklyIds), Csv(weeklyPoiIds), Csv(setup?.SupportingCluster?.PoiClusterId), Csv(setup?.H4SetupId), Csv(h4PoiIds), Csv(setup?.ProtectedSwingIdx.ToString()),
                Csv(attempt.M5AttemptId), Csv(attempt.AttemptNumber.ToString()),
                Csv(attempt.Direction.ToString()), Csv(weekly?.Direction.ToString()), Csv(weekly?.ActivationTime.ToString("O")), Csv(weeklyTop), Csv(weeklyBottom),
                Csv(phase?.State?.ToString()), Csv(phase?.SourcePoiId), Csv(phase?.ContextId), Csv(authorizingContextIds),
                Csv(setup?.Route.ToString()), Csv(setup?.ProtectedSwingType.ToString()), Csv(setup?.ProtectedSwingPrice.ToString()), Csv(setup?.ProtectedSwingTime.ToString("O")), Csv(setup?.WeeklyRetouchNumber.ToString()), Csv(setup?.Status.ToString()), Csv(setup?.M5ExecutionState.ToString()),
                Csv(setup?.M5ExecutionActivationTime?.ToString("O")), Csv(attempt.EntrySwingType.ToString()), Csv(attempt.EntrySwingPrice.ToString()), Csv(attempt.EntrySwingTime.ToString("O")), Csv(attempt.StopSwingType.ToString()), Csv(attempt.StopSwingPrice.ToString()), Csv(attempt.StopSwingTime.ToString("O")),
                Csv(attempt.FirstPendingOrderCreatedTime?.ToString("O")), Csv(attempt.PendingOrderCreatedTime?.ToString("O")), Csv(attempt.PendingOrderModificationCount.ToString()), Csv(attempt.EntryTime?.ToString("O")), Csv(attempt.RequestedEntryPrice.ToString()), Csv(attempt.ActualFillPrice?.ToString()),
                Csv(attempt.SLPrice.ToString()), Csv(attempt.TPPrice.ToString()), Csv("3"), Csv(RiskPercentConfigured.ToString()), Csv(attempt.PositionVolume?.ToString()),
                Csv(attempt.ExitTime?.ToString("O")), Csv(attempt.ExitPrice?.ToString()), Csv(attempt.ExitPriceSource), Csv(attempt.ExitReason?.ToString()), Csv(attempt.GrossPnL?.ToString()), Csv(attempt.NetPnL?.ToString()), Csv(attempt.RealizedR?.ToString()),
                Csv(setup?.M5ExecutionCompletedTime?.ToString("O")), Csv(setup?.M5ExecutionCompletionReason), Csv(setup?.PostEntryContinuationSwingIdx?.ToString()), Csv(setup?.PostEntryContinuationSwingPrice?.ToString()), Csv(setup?.PostEntryContinuationSwingTime?.ToString("O")),
                Csv(setup?.CompletionPullbackSwingIdx?.ToString()), Csv(setup?.CompletionPullbackSwingPrice?.ToString()), Csv(setup?.CompletionPullbackSwingTime?.ToString("O")),
                Csv(setup?.SupersededBySwingIdx?.ToString()), Csv(setup?.SupersededBySwingPrice?.ToString()), Csv(setup?.SupersededTime?.ToString("O"))
            });
            _tradeSummaryBuffer.Add(row);
            FlushTradeSummary();
        }

        private static string JoinPoiIds(List<S1PoiSnapshot> members)
        {
            if (members == null || members.Count == 0) return "";
            var sb = new StringBuilder();
            for (int i = 0; i < members.Count; i++)
            {
                if (i > 0) sb.Append(';');
                sb.Append(members[i].S1PoiId);
            }
            return sb.ToString();
        }

        // ---------------- Opportunity History / Summary ----------------
        // Part 23 fix: this used to be the ONLY opportunity file, with a new
        // row appended on every single state change under the name
        // "OpportunitySummary" -- not actually a summary. Now split:
        //   OpportunityHistory.csv -- every state change (this method's old
        //     behavior, unchanged, just renamed/redirected).
        //   OpportunitySummary.csv -- exactly ONE row per WeeklyOpportunityID,
        //     always reflecting the latest known state (rewritten in full
        //     from an in-memory latest-row map on every change).
        private void WriteOpportunityRow(WeeklyOpportunity o)
        {
            var row = string.Join(",", new[]
            {
                Csv(SymbolName), Csv(o.WeeklyOpportunityId), Csv(o.Direction.ToString()), Csv(o.ActivationTime.ToString("O")), Csv(o.Status.ToString()),
                Csv(o.TerminationTime?.ToString("O")), Csv(o.TerminationReason),
                Csv(o.SupportingCluster?.Members.Count.ToString()), Csv(o.H4Setups.Count.ToString()), Csv(o.RetouchCounter.ToString())
            });

            _opportunityHistoryBuffer.Add(row);
            FlushOpportunityHistory();

            if (!_latestOpportunityRow.ContainsKey(o.WeeklyOpportunityId)) _opportunityIdOrder.Add(o.WeeklyOpportunityId);
            _latestOpportunityRow[o.WeeklyOpportunityId] = row;
            RewriteOpportunitySummary();
        }

        private void RewriteOpportunitySummary()
        {
            var lines = new List<string>(_opportunityIdOrder.Count + 1) { OpportunitySummaryHeader };
            foreach (var id in _opportunityIdOrder)
                lines.Add(_latestOpportunityRow[id]);
            System.IO.File.WriteAllLines(_opportunitySummaryPath, lines);
        }

        // ---------------- Debug log ----------------
        public void Debug(string message)
        {
            if (!_debugLoggingEnabled) return;
            _debugBuffer.Add($"[{DateTime.UtcNow:O}] {message}");
            if (_debugBuffer.Count >= 50) FlushDebugLog();
        }

        // ---------------- Flushing ----------------
        public void FlushAll()
        {
            FlushEventLog();
            FlushTradeSummary();
            FlushOpportunityHistory();
            RewriteOpportunitySummary(); // idempotent full rewrite -- cheap, guarantees the summary file is current at shutdown
            FlushPhaseHistory();
            FlushH4PhaseRejection();
            FlushDebugLog();
        }

        private void FlushEventLog()
        {
            if (_eventLogBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_eventLogPath, _eventLogBuffer);
            _eventLogBuffer.Clear();
        }

        private void FlushTradeSummary()
        {
            if (_tradeSummaryBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_tradeSummaryPath, _tradeSummaryBuffer);
            _tradeSummaryBuffer.Clear();
        }

        private void FlushOpportunityHistory()
        {
            if (_opportunityHistoryBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_opportunityHistoryPath, _opportunityHistoryBuffer);
            _opportunityHistoryBuffer.Clear();
        }

        private void FlushDebugLog()
        {
            if (_debugBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_debugLogPath, _debugBuffer);
            _debugBuffer.Clear();
        }

        private void FlushPhaseHistory()
        {
            if (_phaseHistoryBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_phaseHistoryPath, _phaseHistoryBuffer);
            _phaseHistoryBuffer.Clear();
        }

        private void FlushH4PhaseRejection()
        {
            if (_h4PhaseRejectionBuffer.Count == 0) return;
            System.IO.File.AppendAllLines(_h4PhaseRejectionPath, _h4PhaseRejectionBuffer);
            _h4PhaseRejectionBuffer.Clear();
        }

        private static string Csv(string field)
        {
            if (string.IsNullOrEmpty(field)) return "";
            if (field.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0)
                return "\"" + field.Replace("\"", "\"\"") + "\"";
            return field;
        }
    }
}
