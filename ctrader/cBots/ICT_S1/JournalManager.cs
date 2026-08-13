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
// KNOWN GAPS (explicit, not silently dropped): raw SWING_HIGH_CONFIRMED /
// SWING_LOW_CONFIRMED / MSS_UP / MSS_DOWN events are not yet wired into the
// EventLog -- PoiMarketEngine doesn't currently raise events for these
// (it's pure state, no event queue), so hooking them in is a follow-up.
// MFE/MAE (max favorable/adverse excursion) need a tick-by-tick high-
// water-mark tracker per open position, not yet implemented. SpreadAtEntry
// is captured; Slippage and Commission are left blank until the exact
// data the installed API exposes for these is confirmed against a real
// build.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace cAlgo.Robots.ICT_S1
{
    public class JournalManager
    {
        private readonly string _tradeSummaryPath;
        private readonly string _opportunitySummaryPath;
        private readonly string _eventLogPath;
        private readonly string _debugLogPath;
        private readonly bool _debugLoggingEnabled;

        private readonly List<string> _eventLogBuffer = new List<string>();
        private readonly List<string> _tradeSummaryBuffer = new List<string>();
        private readonly List<string> _opportunitySummaryBuffer = new List<string>();
        private readonly List<string> _debugBuffer = new List<string>();
        private readonly HashSet<string> _opportunitiesWritten = new HashSet<string>();

        private const string EventLogHeader = "Timestamp,Symbol,Timeframe,EventType,Direction,WeeklyOpportunityID,PoiClusterID,POIID,H4SetupID,M5AttemptID,TradeID,Price,POITop,POIBottom,PreviousState,NewState,Reason,Notes";

        private const string TradeSummaryHeader = "StrategyVersion,Symbol,TradeID,PositionID,WeeklyOpportunityID,PoiClusterID,H4SetupID,M5AttemptID,AttemptNumber," +
            "TradeDirection,WeeklyOpportunityDirection," +
            "H4Route,H4ProtectedSwingType,H4ProtectedSwingPrice,H4ProtectedSwingTime,WeeklyRetouchNumber," +
            "M5EntrySwingType,M5EntrySwingPrice,M5EntrySwingTime,M5StopSwingType,M5StopSwingPrice,M5StopSwingTime," +
            "PendingOrderCreatedTime,PendingOrderModificationCount,EntryTime,RequestedEntryPrice,ActualFillPrice," +
            "SLPrice,TPPrice,TargetR,RiskPercent,PositionVolume," +
            "ExitTime,ExitPrice,ExitReason,GrossPnL,NetPnL,RealizedR";

        private const string OpportunitySummaryHeader = "Symbol,WeeklyOpportunityID,Direction,ActivationTime,Status,TerminationTime,TerminationReason," +
            "Control,ControlSourcePoiId,SupportingPoiCount,H4SetupCount,RetouchCounter";

        public string SymbolName;
        public string StrategyVersion = "S1-v1";
        public double RiskPercentConfigured;

        public JournalManager(string runId, bool debugLoggingEnabled)
        {
            _debugLoggingEnabled = debugLoggingEnabled;
            string baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "cAlgo", "S1", runId);
            Directory.CreateDirectory(baseDir);

            _tradeSummaryPath = Path.Combine(baseDir, "S1_TradeSummary_" + runId + ".csv");
            _opportunitySummaryPath = Path.Combine(baseDir, "S1_OpportunitySummary_" + runId + ".csv");
            _eventLogPath = Path.Combine(baseDir, "S1_EventLog_" + runId + ".csv");
            _debugLogPath = Path.Combine(baseDir, "S1_Debug_" + runId + ".log");

            File.WriteAllText(_eventLogPath, EventLogHeader + Environment.NewLine);
            File.WriteAllText(_tradeSummaryPath, TradeSummaryHeader + Environment.NewLine);
            File.WriteAllText(_opportunitySummaryPath, OpportunitySummaryHeader + Environment.NewLine);
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
            WriteOpportunitySummaryRow(o);
        }

        public void LogH4SetupEvent(H4SetupEvent ev)
        {
            var h = ev.Setup;
            WriteEventRow(ev.Time, "H4", "H4_" + ev.Type.ToString().ToUpperInvariant(), h.Direction.ToString(),
                h.WeeklyOpportunityId, h.SupportingCluster?.PoiClusterId ?? "", ev.TriggeringPoi?.S1PoiId ?? "", h.H4SetupId, "", "",
                "", "", "", "", h.Status.ToString(), ev.Note, "");
        }

        public void LogOrderEvent(M5Attempt attempt, string eventType, string note)
        {
            WriteEventRow(DateTime.UtcNow, "M5", eventType, attempt.Direction.ToString(),
                "", "", "", attempt.H4SetupId, attempt.M5AttemptId, "",
                attempt.RequestedEntryPrice, "", "", "", attempt.Status.ToString(), note, "");
        }

        public void LogManualIntervention(M5Attempt attempt, string detail)
        {
            WriteEventRow(DateTime.UtcNow, "M5", "MANUAL_INTERVENTION_DETECTED", attempt.Direction.ToString(),
                "", "", "", attempt.H4SetupId, attempt.M5AttemptId, "",
                "", "", "", "", attempt.Status.ToString(), detail, "");
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
        public void LogTradeClosed(M5Attempt attempt, H4Setup setup, WeeklyOpportunity weekly)
        {
            var row = string.Join(",", new[]
            {
                Csv(StrategyVersion), Csv(SymbolName), Csv(IdGenerator.NextTradeId()), Csv(""),
                Csv(weekly?.WeeklyOpportunityId), Csv(setup?.SupportingCluster?.PoiClusterId), Csv(setup?.H4SetupId), Csv(attempt.M5AttemptId), Csv(attempt.AttemptNumber.ToString()),
                Csv(attempt.Direction.ToString()), Csv(weekly?.Direction.ToString()),
                Csv(setup?.Route.ToString()), Csv(setup?.ProtectedSwingType.ToString()), Csv(setup?.ProtectedSwingPrice.ToString()), Csv(setup?.ProtectedSwingTime.ToString("O")), Csv(setup?.WeeklyRetouchNumber.ToString()),
                Csv(attempt.EntrySwingType.ToString()), Csv(attempt.EntrySwingPrice.ToString()), Csv(attempt.EntrySwingTime.ToString("O")), Csv(attempt.StopSwingType.ToString()), Csv(attempt.StopSwingPrice.ToString()), Csv(attempt.StopSwingTime.ToString("O")),
                Csv(attempt.PendingOrderCreatedTime?.ToString("O")), Csv(attempt.PendingOrderModificationCount.ToString()), Csv(attempt.EntryTime?.ToString("O")), Csv(attempt.RequestedEntryPrice.ToString()), Csv(attempt.ActualFillPrice?.ToString()),
                Csv(attempt.SLPrice.ToString()), Csv(attempt.TPPrice.ToString()), Csv("3"), Csv(RiskPercentConfigured.ToString()), Csv(""),
                Csv(attempt.ExitTime?.ToString("O")), Csv(attempt.ExitPrice?.ToString()), Csv(attempt.ExitReason?.ToString()), Csv(attempt.GrossPnL?.ToString()), Csv(attempt.NetPnL?.ToString()), Csv(attempt.RealizedR?.ToString())
            });
            _tradeSummaryBuffer.Add(row);
            FlushTradeSummary();
        }

        // ---------------- Opportunity Summary ----------------
        private void WriteOpportunitySummaryRow(WeeklyOpportunity o)
        {
            // One row per opportunity, rewritten (append-then-dedupe on read)
            // each time its state changes -- simplest reliable way to keep
            // this file current without an update-in-place CSV writer.
            var row = string.Join(",", new[]
            {
                Csv(SymbolName), Csv(o.WeeklyOpportunityId), Csv(o.Direction.ToString()), Csv(o.ActivationTime.ToString("O")), Csv(o.Status.ToString()),
                Csv(o.TerminationTime?.ToString("O")), Csv(o.TerminationReason),
                Csv(o.Control.ToString()), Csv(o.ControlSourcePoiId), Csv(o.SupportingCluster?.Members.Count.ToString()), Csv(o.H4Setups.Count.ToString()), Csv(o.RetouchCounter.ToString())
            });
            _opportunitySummaryBuffer.Add(row);
            _opportunitiesWritten.Add(o.WeeklyOpportunityId);
            FlushOpportunitySummary();
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
            FlushOpportunitySummary();
            FlushDebugLog();
        }

        private void FlushEventLog()
        {
            if (_eventLogBuffer.Count == 0) return;
            File.AppendAllLines(_eventLogPath, _eventLogBuffer);
            _eventLogBuffer.Clear();
        }

        private void FlushTradeSummary()
        {
            if (_tradeSummaryBuffer.Count == 0) return;
            File.AppendAllLines(_tradeSummaryPath, _tradeSummaryBuffer);
            _tradeSummaryBuffer.Clear();
        }

        private void FlushOpportunitySummary()
        {
            if (_opportunitySummaryBuffer.Count == 0) return;
            File.AppendAllLines(_opportunitySummaryPath, _opportunitySummaryBuffer);
            _opportunitySummaryBuffer.Clear();
        }

        private void FlushDebugLog()
        {
            if (_debugBuffer.Count == 0) return;
            File.AppendAllLines(_debugLogPath, _debugBuffer);
            _debugBuffer.Clear();
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
