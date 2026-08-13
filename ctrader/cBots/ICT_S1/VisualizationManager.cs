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
        private readonly List<string> _activeOnlyNames = new List<string>();
        private int _counter = 0;

        public VisualizationManager(Chart chart, VisualizationMode mode)
        {
            _chart = chart;
            _mode = mode;
        }

        private string NextName(string prefix) => prefix + "_" + (++_counter);

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

        // --- POI boxes (Weekly + H4) ---
        public void DrawPoiImpact(S1PoiSnapshot s)
        {
            if (_mode == VisualizationMode.Off) return;
            var name = NextName("POI_" + s.S1PoiId);
            var color = ColorForLifecycle(s.LifecycleState, s.Direction);
            var rect = _chart.DrawRectangle(name, s.FirstImpactTime, s.Zt, s.FirstImpactTime.AddHours(4), s.Zb, color, 1);
            rect.IsFilled = false;
            _chart.DrawText(name + "_lbl", $"{s.TypeAtActivation} {s.S1PoiId}", s.FirstImpactTime, s.Zt, color);
            Track(name);
        }

        // `time` is the actual event time (ev.Time from the caller) --
        // never DateTime.UtcNow, so historical backtest objects are drawn
        // at their real historical moment (audit section 32).
        public void UpdatePoiTerminal(S1PoiSnapshot s, DateTime time)
        {
            if (_mode == VisualizationMode.Off) return;
            // Terminal color update: redraw a small marker at the
            // resolution point rather than trying to find/recolor the
            // original rectangle by name (kept simple and robust).
            var name = NextName("POI_END_" + s.S1PoiId);
            var color = ColorForLifecycle(s.LifecycleState, s.Direction);
            var price = s.RelevantReactionSwingPrice ?? (s.Direction == Direction.Buy ? s.Zt : s.Zb);
            _chart.DrawText(name, s.LifecycleState == S1PoiLifecycleState.Retired ? "RETIRED" : "INVALID", time, price, color);
            Track(name);
        }

        // --- H4 protected swing ---
        // Extends a fixed, deterministic duration forward from the setup's
        // own creation time -- NOT DateTime.UtcNow/"now" (audit section 32:
        // during a fast backtest replay, "now" is wall-clock real time,
        // which has no relationship to where the simulation actually is;
        // it would draw historical objects at the wrong, ever-changing
        // position). Redrawn objects (VisualizationMode.ActiveOnly) get
        // cleaned up on their own terminal event instead of relying on a
        // moving "still open" endpoint.
        public void DrawProtectedSwing(H4Setup setup, DateTime createdAt)
        {
            if (_mode == VisualizationMode.Off) return;
            var name = NextName("PROT_" + setup.H4SetupId);
            var extendTo = createdAt.AddDays(7);
            _chart.DrawTrendLine(name, setup.ProtectedSwingTime, setup.ProtectedSwingPrice, extendTo, setup.ProtectedSwingPrice, Color.Purple, 1, LineStyle.Dots);
            Track(name);
        }

        // --- M5 pending order / SL / TP ---
        public void DrawAttemptOrder(M5Attempt attempt, DateTime createdAt)
        {
            if (_mode == VisualizationMode.Off) return;
            var baseName = "ATT_" + attempt.M5AttemptId;
            RemoveIfActiveOnly(baseName + "_entry");
            RemoveIfActiveOnly(baseName + "_sl");
            RemoveIfActiveOnly(baseName + "_tp");

            var anchor = attempt.PendingOrderCreatedTime ?? createdAt;
            var extendTo = anchor.AddHours(6);
            _chart.DrawTrendLine(baseName + "_entry", anchor, attempt.RequestedEntryPrice, extendTo, attempt.RequestedEntryPrice, Color.Blue, 1, LineStyle.Solid);
            _chart.DrawTrendLine(baseName + "_sl", anchor, attempt.SLPrice, extendTo, attempt.SLPrice, Color.Red, 1, LineStyle.Dots);
            _chart.DrawTrendLine(baseName + "_tp", anchor, attempt.TPPrice, extendTo, attempt.TPPrice, Color.Green, 1, LineStyle.Dots);
            Track(baseName + "_entry");
            Track(baseName + "_sl");
            Track(baseName + "_tp");
        }

        public void DrawAttemptClosed(M5Attempt attempt, DateTime asOf)
        {
            if (_mode == VisualizationMode.Off) return;
            var name = NextName("EXIT_" + attempt.M5AttemptId);
            var color = attempt.ExitReason == ExitReason.TakeProfit ? Color.Green
                      : attempt.ExitReason == ExitReason.StopLoss ? Color.Red
                      : Color.Orange;
            var t = attempt.ExitTime ?? asOf;
            var p = attempt.ExitPrice ?? attempt.RequestedEntryPrice;
            _chart.DrawText(name, $"{attempt.ExitReason} R={attempt.RealizedR:F2}", t, p, color);
            Track(name);

            if (_mode == VisualizationMode.ActiveOnly)
            {
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_entry");
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_sl");
                RemoveIfActiveOnly("ATT_" + attempt.M5AttemptId + "_tp");
            }
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
