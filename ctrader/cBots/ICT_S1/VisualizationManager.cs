// ICT_S1 — VisualizationManager. Master prompt sections 29-30.
//
// Draws on the Chart the cBot is attached to (typically the M5 execution
// chart) using TIME-based coordinates throughout, not bar-index-based --
// Weekly/H4 objects don't share the M5 chart's own index space, but a
// DateTime lines up correctly regardless of which timeframe the chart is
// currently showing.
//
// Modes (spec section 30):
//   Off        -- no drawing at all.
//   ActiveOnly -- only currently-live objects shown; terminal ones removed.
//   Audit      -- full history kept (nothing ever removed) for backtest
//                 verification across the whole tested range. This is the
//                 default recommendation for reviewing a backtest; switch
//                 to ActiveOnly for lower object-count/performance-
//                 sensitive live use. cTrader's own chart-object limits
//                 still apply -- if a very long backtest hits them, that's
//                 a platform ceiling, not a bug here (flagging per spec
//                 section 30's "explain limitations rather than silently
//                 dropping information").
//
// The trading engines are untouched by whatever this class does -- pure
// read-only visualization layer, per the modular architecture.
//
// FINAL AUDIT REWRITE (Parts 24-27): the previous version drew every
// lifecycle box/line with an ARBITRARY fixed duration (POI impact+4h,
// protected swing +7 days, M5 order +6h) purely because the true endpoint
// wasn't known yet at draw time. These were flagged as visualization
// heuristics that "don't affect trading, but violate the audit objective"
// (Part 24) -- fixed by using FIXED, stable object names per entity (so a
// later redraw call in-place UPDATES the same object instead of leaving a
// stale one behind) and redrawing on every lifecycle event this class is
// notified of, extending each object's visible extent to that event's own
// real historical time -- never to an invented future offset. A POI/setup/
// order that receives no further events between creation and its terminal
// event simply gets its final, exact [start, terminal] extent drawn once;
// one that receives retouches/moves along the way visibly grows in real
// historical time with each one. Still-open objects at backtest end are
// finalized via FinalizeOpenPois/FinalizeOpenSetups (called once from
// OnStop) so nothing is left artificially truncated or artificially
// extended past "now".

using System;
using System.Collections.Generic;
using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    public enum VisualizationMode
    {
        Off,
        ActiveOnly,
        Audit
    }

    public class VisualizationManager
    {
        private readonly Chart _chart;
        private readonly VisualizationMode _mode;
        private readonly HashSet<string> _activeOnlyNames = new HashSet<string>();
        private int _phaseTransitionCounter = 0; // each transition is its own permanent historical marker, not an update-in-place object

        public VisualizationManager(Chart chart, VisualizationMode mode)
        {
            _chart = chart;
            _mode = mode;
        }

        private void Track(string name)
        {
            if (_mode == VisualizationMode.ActiveOnly) _activeOnlyNames.Add(name);
        }

        public void RemoveIfActiveOnly(string name)
        {
            if (_mode != VisualizationMode.ActiveOnly) return;
            _chart.RemoveObject(name);
            _activeOnlyNames.Remove(name);
        }

        // ============================= POI (Weekly + H4) =============================
        //
        // Real lifecycle, per Part 25:
        //   CreationTime -> zone extends -> Eligibility -> Impact -> Retouches -> TerminalTime
        // One fixed-name rectangle per POI, redrawn (updated in place) on
        // every event, right edge = that event's own time. TerminalTime is
        // InvalidationTime or RetirementTime; while still active it's
        // whatever the most recent known event's time is (extended to the
        // real current simulated time by FinalizeOpenPois at backtest end).

        public void DrawPoiImpact(S1PoiSnapshot s)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawPoiBox(s, s.FirstImpactTime);
            var lblName = "POI_" + s.S1PoiId + "_lbl";
            _chart.DrawText(lblName, $"{s.TypeAtActivation} {s.S1PoiId}", s.CreationTime, s.Zt, ColorForLifecycle(s.LifecycleState, s.Direction));
            Track(lblName);
        }

        public void UpdatePoiRetouch(S1PoiSnapshot s, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawPoiBox(s, time);
        }

        // `time` is the actual event time (ev.Time from the caller) --
        // never DateTime.UtcNow, so historical backtest objects are drawn
        // at their real historical moment (audit section 32).
        public void UpdatePoiTerminal(S1PoiSnapshot s, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawPoiBox(s, time); // final, exact extent -- ends precisely at Invalidation/RetirementTime
            var name = "POI_" + s.S1PoiId + "_end";
            var color = ColorForLifecycle(s.LifecycleState, s.Direction);
            var price = s.RelevantReactionSwingPrice ?? (s.Direction == Direction.Buy ? s.Zt : s.Zb);
            _chart.DrawText(name, s.LifecycleState == S1PoiLifecycleState.Retired ? "RETIRED" : "INVALID", time, price, color);
            Track(name);

            if (_mode == VisualizationMode.ActiveOnly)
            {
                RemoveIfActiveOnly("POI_" + s.S1PoiId);
                RemoveIfActiveOnly("POI_" + s.S1PoiId + "_lbl");
            }
        }

        // Called once from OnStop for every POI still ImpactedUnresolved at
        // the end of the run -- "if still active, extend to current
        // simulated time" (Part 25), not left at whatever its last event
        // happened to be.
        public void FinalizeOpenPois(IEnumerable<S1PoiSnapshot> stillOpen, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            foreach (var s in stillOpen) RedrawPoiBox(s, asOf);
        }

        private void RedrawPoiBox(S1PoiSnapshot s, DateTime rightEdge)
        {
            var name = "POI_" + s.S1PoiId; // fixed name -- redraw updates the same object in place
            var color = ColorForLifecycle(s.LifecycleState, s.Direction);
            var rect = _chart.DrawRectangle(name, s.CreationTime, s.Zt, rightEdge, s.Zb, color, 1);
            rect.IsFilled = false;
            Track(name);
        }

        // ============================= H4 reaction / setup =============================
        //
        // Part 26: protected swing line now extends exactly to the setup's
        // real known extent (creation -> latest event -> termination), not
        // an arbitrary +7 days. Reaction grouping (multiple H4 POIs sharing
        // one protected swing = one reaction) is shown by tagging every
        // supporting POI's own chart location with the owning H4SetupId, so
        // POIs that belong to the same reaction visibly carry the same tag.

        public void DrawProtectedSwing(H4Setup setup, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawProtectedSwingLine(setup, asOf);
            var lblName = "PROT_" + setup.H4SetupId + "_lbl";
            var weeklyLineage = string.Join("+", setup.SupportingWeeklyOpportunityIds);
            _chart.DrawText(lblName, $"{setup.H4SetupId} <- [{weeklyLineage}] ({setup.Route}, swing#{setup.ProtectedSwingIdx})", setup.CreatedTime, setup.ProtectedSwingPrice, Color.Purple);
            Track(lblName);
        }

        // Called on every H4SetupEvent (Impacted = new reaction, Retouched
        // = another POI joined it) so the protected-swing line's visible
        // extent tracks real history instead of a guessed future offset.
        public void UpdateH4SetupActivity(H4Setup setup, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawProtectedSwingLine(setup, time);
        }

        // Tags the triggering POI's own box location with the H4SetupId it
        // was authorized into -- this is the visible proof that e.g. an
        // IFOB and a non-overlapping IRB anchored to the same protected
        // swing belong to the SAME H4 reaction (Part 26).
        public void DrawH4PoiJoinedReaction(H4SetupEvent ev)
        {
            if (_mode == VisualizationMode.Off) return;
            var poi = ev.TriggeringPoi;
            if (poi == null) return;
            var name = "H4TAG_" + poi.S1PoiId;
            _chart.DrawText(name, $"reaction: {ev.Setup.H4SetupId}", poi.FirstImpactTime, poi.Zb, Color.Purple);
            Track(name);
        }

        public void UpdateH4SetupTerminal(H4Setup setup, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawProtectedSwingLine(setup, time); // final, exact extent
            var name = "PROT_" + setup.H4SetupId + "_end";
            _chart.DrawText(name, $"TERMINATED: {setup.TerminationReason}", time, setup.ProtectedSwingPrice, Color.DarkRed);
            Track(name);

            if (_mode == VisualizationMode.ActiveOnly)
            {
                RemoveIfActiveOnly("PROT_" + setup.H4SetupId);
                RemoveIfActiveOnly("PROT_" + setup.H4SetupId + "_lbl");
            }
        }

        // Strategy clarification (follow-up round), Part 39: success (a new
        // protected H4 structure superseded this reaction) is visually
        // distinct from failure (UpdateH4SetupTerminal, dark red) -- green,
        // matching the POI-retirement success color.
        public void UpdateH4SetupSuperseded(H4Setup setup, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawProtectedSwingLine(setup, time); // final, exact extent
            var name = "PROT_" + setup.H4SetupId + "_end";
            _chart.DrawText(name, $"SUPERSEDED (new protected swing {setup.SupersededBySwingPrice})", time, setup.ProtectedSwingPrice, Color.Green);
            Track(name);

            if (_mode == VisualizationMode.ActiveOnly)
            {
                RemoveIfActiveOnly("PROT_" + setup.H4SetupId);
                RemoveIfActiveOnly("PROT_" + setup.H4SetupId + "_lbl");
            }
        }

        // Called once from OnStop for every H4Setup still non-Terminated at
        // the end of the run.
        public void FinalizeOpenSetups(IEnumerable<H4Setup> stillOpen, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            foreach (var s in stillOpen) RedrawProtectedSwingLine(s, asOf);
        }

        private void RedrawProtectedSwingLine(H4Setup setup, DateTime rightEdge)
        {
            var name = "PROT_" + setup.H4SetupId; // fixed name -- redraw updates in place
            _chart.DrawTrendLine(name, setup.ProtectedSwingTime, setup.ProtectedSwingPrice, rightEdge, setup.ProtectedSwingPrice, Color.Purple, 1, LineStyle.Dots);
            Track(name);
        }

        // ============================= M5 attempt =============================
        //
        // Part 27: entry/SL/TP lines now extend to the attempt's real known
        // extent at each stage (created -> moved -> filled -> closed), not
        // an arbitrary +6h. AttemptNumber is shown in the label so repeated
        // attempts under one H4Setup are visually distinguishable.

        public void DrawAttemptOrder(M5Attempt attempt, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawAttemptLines(attempt, asOf);
            var lblName = "ATT_" + attempt.M5AttemptId + "_lbl";
            var anchor = attempt.FirstPendingOrderCreatedTime ?? asOf;
            _chart.DrawText(lblName, $"{attempt.M5AttemptId} #{attempt.AttemptNumber} entry={attempt.EntrySwingType}@{attempt.EntrySwingPrice} stop={attempt.StopSwingType}@{attempt.StopSwingPrice}", anchor, attempt.RequestedEntryPrice, Color.Blue);
            Track(lblName);
        }

        public void DrawAttemptFilled(M5Attempt attempt, DateTime fillTime)
        {
            if (_mode == VisualizationMode.Off) return;
            RedrawAttemptLines(attempt, fillTime);
        }

        public void DrawAttemptClosed(M5Attempt attempt, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            var t = attempt.ExitTime ?? asOf;
            RedrawAttemptLines(attempt, t); // final, exact extent -- ends precisely at ExitTime

            var name = "EXIT_" + attempt.M5AttemptId;
            var color = attempt.ExitReason == ExitReason.TakeProfit ? Color.Green
                      : attempt.ExitReason == ExitReason.StopLoss ? Color.Red
                      : Color.Orange;
            var p = attempt.ExitPrice ?? attempt.RequestedEntryPrice;
            _chart.DrawText(name, $"#{attempt.AttemptNumber} {attempt.ExitReason} R={attempt.RealizedR:F2} ({attempt.ExitPriceSource})", t, p, color);
            Track(name);

            if (_mode == VisualizationMode.ActiveOnly)
            {
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_entry");
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_sl");
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_tp");
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_lbl");
            }
        }

        private void RedrawAttemptLines(M5Attempt attempt, DateTime rightEdge)
        {
            var baseName = "ATT_" + attempt.M5AttemptId; // fixed name -- redraw updates in place (covers order moves too)
            var anchor = attempt.FirstPendingOrderCreatedTime ?? rightEdge;
            _chart.DrawTrendLine(baseName + "_entry", anchor, attempt.RequestedEntryPrice, rightEdge, attempt.RequestedEntryPrice, Color.Blue, 1, LineStyle.Solid);
            _chart.DrawTrendLine(baseName + "_sl", anchor, attempt.SLPrice, rightEdge, attempt.SLPrice, Color.Red, 1, LineStyle.Dots);
            _chart.DrawTrendLine(baseName + "_tp", anchor, attempt.TPPrice, rightEdge, attempt.TPPrice, Color.Green, 1, LineStyle.Dots);
            Track(baseName + "_entry");
            Track(baseName + "_sl");
            Track(baseName + "_tp");
        }

        // ============================= Directional Phase =============================
        //
        // Strategy clarification (follow-up round), Part 49: "the report
        // must make Control understandable as market behavior, not just
        // object mutation." One permanent text marker per transition
        // (unlike the update-in-place lifecycle objects above -- each
        // transition is its own distinct historical moment, not a single
        // evolving object's current extent).
        public void DrawPhaseTransition(DirectionalPhaseEvent ev)
        {
            if (_mode == VisualizationMode.Off) return;
            var name = "PHASE_" + (++_phaseTransitionCounter);
            var color = ev.NewState == ControlState.BuyControl ? Color.Blue
                      : ev.NewState == ControlState.SellControl ? Color.Black
                      : Color.Gray;
            var price = ev.SourcePoi != null
                ? (ev.NewState == ControlState.BuyControl ? ev.SourcePoi.Zt : ev.SourcePoi.Zb)
                : (double?)null;
            if (price == null) return; // no price to anchor the label to (e.g. a Neutral transition with no source POI) -- journal still has it
            _chart.DrawText(name, $"PHASE -> {ev.NewState} ({ev.Reason})", ev.Time, price.Value, color);
            Track(name);
        }

        private static Color ColorForLifecycle(S1PoiLifecycleState state, Direction dir)
        {
            switch (state)
            {
                case S1PoiLifecycleState.Invalidated: return Color.Red;
                case S1PoiLifecycleState.Retired:
                case S1PoiLifecycleState.ReactionSwingConfirmed: return Color.Green;
                default: return dir == Direction.Buy ? Color.Blue : Color.Black;
            }
        }
    }
}
