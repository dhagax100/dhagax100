// ICT_S1 — TradeManager. Implements ITradeExecutor against the real cAlgo
// trading API. Spec: docs/s1_ea_specification.md sections 8-9.
//
// Confirmed against a real build (2026-08-13):
// - PlaceStopOrder takes a symbol NAME (string), not a Symbol object -- fixed.
// - ModifyPendingOrder's Symbol/PendingOrder overload used here is flagged
//   obsolete in favor of a ProtectionType-parameter version, but that newer
//   version has confirmed community reports of a runtime TypeLoadException
//   on some cTrader installs (undocumented/unstable as of this writing) --
//   deliberately kept on the old overload. The CS0618 warning is expected
//   and safe to ignore; switching it is a "fix" only once cTrader's own API
//   stabilizes, not before.
//
// SL/TP are placed via PIPS (PlaceStopOrder's standard parameter shape),
// converted from the absolute price levels M5ExecutionEngine computes --
// if the installed API version supports absolute-price SL/TP directly,
// that would avoid pip-rounding and is worth switching to.
//
// Manual intervention detection (confirmed rule: respect + log, never
// recreate): an order Cancelled or a position Closed with a reason other
// than our own SL/TP, where the M5Attempt hadn't already been transitioned
// to Cancelled/Closed by our own code, is treated as external/manual.
//
// ROUND 2 FIX (audit sections 5-6) -- the OLD classification relied on
// `attempt.Status == Cancelled` at the moment PendingOrderCancelled fires.
// That is unreliable by construction: every order MOVE cancels the old
// order and immediately places a replacement, which sets attempt.Status
// back to Pending before the old order's (possibly async) cancellation
// confirmation arrives -- so a perfectly normal internal move looked
// identical to a manual cancel, and that is the confirmed root cause of
// the ~34 false MANUAL_INTERVENTION_DETECTED events in the Round 2 backtest.
// Fixed by tracking INTENT explicitly, keyed by order label, independent of
// whatever attempt.Status has moved on to by the time the confirmation
// arrives: CancelPendingOrder() (this class's own method, called by
// M5ExecutionEngine for both order moves and parent-setup termination)
// records the intent BEFORE issuing the real cAlgo cancel. A counter (not a
// flag) because the same label can legitimately have more than one
// internal cancel in flight (e.g. a very fast successive move).

using System;
using System.Collections.Generic;
using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    public class TradeManager : ITradeExecutor
    {
        private readonly Robot _robot;
        private readonly Symbol _symbol;
        private readonly RiskManager _riskManager;
        private readonly Dictionary<string, int> _internalCancelIntent = new Dictionary<string, int>();

        public double Bid => _symbol.Bid;
        public double Ask => _symbol.Ask;
        public double PipSize => _symbol.PipSize;

        // Set by the main Robot after both objects exist (avoids a
        // circular constructor dependency between TradeManager and
        // M5ExecutionEngine).
        public M5ExecutionEngine ExecutionEngine { get; set; }

        public event Action<M5Attempt, string> ManualInterventionDetected;

        public TradeManager(Robot robot, Symbol symbol, RiskManager riskManager)
        {
            _robot = robot;
            _symbol = symbol;
            _riskManager = riskManager;

            _robot.Positions.Closed += OnPositionClosed;
            _robot.PendingOrders.Filled += OnPendingOrderFilled;
            _robot.PendingOrders.Cancelled += OnPendingOrderCancelled;
        }

        public double ComputeVolume(double slDistance) => _riskManager.ComputeVolume(slDistance);

        public string PlaceStopOrder(Direction dir, double volume, double triggerPrice, double slPrice, double tpPrice, string label)
        {
            var tradeType = dir == Direction.Buy ? TradeType.Buy : TradeType.Sell;
            double slPips = Math.Abs(triggerPrice - slPrice) / _symbol.PipSize;
            double tpPips = Math.Abs(tpPrice - triggerPrice) / _symbol.PipSize;

            var result = _robot.PlaceStopOrder(tradeType, _symbol.Name, volume, triggerPrice, label, slPips, tpPips);
            if (result == null || !result.IsSuccessful || result.PendingOrder == null) return null;
            return label; // our own M5AttemptId doubles as the cAlgo order label and our lookup key
        }

        public void ModifyPendingOrder(string orderId, double newTriggerPrice, double newSlPrice, double newTpPrice)
        {
            var order = FindPendingOrder(orderId);
            if (order == null) return;
            double slPips = Math.Abs(newTriggerPrice - newSlPrice) / _symbol.PipSize;
            double tpPips = Math.Abs(newTpPrice - newTriggerPrice) / _symbol.PipSize;
            _robot.ModifyPendingOrder(order, newTriggerPrice, slPips, tpPips);
        }

        public void CancelPendingOrder(string orderId)
        {
            var order = FindPendingOrder(orderId);
            if (order == null) return;
            // Record intent BEFORE the real cancel -- see class header.
            _internalCancelIntent.TryGetValue(orderId, out var n);
            _internalCancelIntent[orderId] = n + 1;
            _robot.CancelPendingOrder(order);
        }

        private PendingOrder FindPendingOrder(string label)
        {
            foreach (var o in _robot.PendingOrders)
                if (o.Label == label) return o;
            return null;
        }

        private M5Attempt FindAttempt(string label)
        {
            if (ExecutionEngine == null) return null;
            foreach (var a in ExecutionEngine.AllAttempts)
                if (a.M5AttemptId == label) return a;
            return null;
        }

        private void OnPendingOrderFilled(PendingOrderFilledEventArgs args)
        {
            var attempt = FindAttempt(args.Position.Label);
            if (attempt == null) return; // not one of ours
            ExecutionEngine.OnAttemptFilled(attempt, args.Position.EntryPrice, _robot.Server.Time);

            attempt.TradeId = attempt.TradeId ?? IdGenerator.NextTradeId(); // Round 2 fix (audit 29): assigned once, at fill
            attempt.PositionId = args.Position.Id;
            attempt.PositionVolume = args.Position.VolumeInUnits;

            // Round 2 fix (audit sections 30-32): OnAttemptFilled just
            // recalculated SLPrice/TPPrice anchored to the ACTUAL fill price
            // (slippage/gap-adjusted) -- push those to the real broker
            // position so the live protective orders match what our own
            // journal/RealizedR math assumes. Without this the broker keeps
            // protecting the ORIGINAL pre-fill levels while S1 reports
            // R-multiples computed from the recalculated ones -- confirmed
            // root cause of the RealizedR anomalies in the Round 2 backtest.
            args.Position.ModifyStopLossPrice(attempt.SLPrice);
            args.Position.ModifyTakeProfitPrice(attempt.TPPrice);
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var pos = args.Position;
            var attempt = FindAttempt(pos.Label);
            if (attempt == null) return; // not one of ours

            bool weAlreadyTransitioned = attempt.Status == M5AttemptStatus.ClosedSL || attempt.Status == M5AttemptStatus.ClosedTP;
            if (weAlreadyTransitioned) return;

            ExitReason reason;
            switch (args.Reason)
            {
                case PositionCloseReason.StopLoss:
                    reason = ExitReason.StopLoss;
                    break;
                case PositionCloseReason.TakeProfit:
                    reason = ExitReason.TakeProfit;
                    break;
                default:
                    // Client-initiated close, margin call, etc. -- respect it,
                    // don't fight the trader (confirmed rule).
                    reason = ExitReason.ManualIntervention;
                    ManualInterventionDetected?.Invoke(attempt, args.Reason.ToString());
                    break;
            }

            // Round 2 fix (audit sections 30-32): exit price now comes from
            // the account's actual closed-trade record (History), which
            // carries the REAL closing price cAlgo executed at -- not a
            // live Bid/Ask quote fetched after the close event fires, which
            // can already have moved past the true fill and was flagged as
            // only an approximate proxy. Falls back to the live quote only
            // if the historical record genuinely isn't found (shouldn't
            // happen for a position that was just closed).
            var histTrade = FindHistoricalTrade(pos.Id);
            double exitPrice = histTrade != null
                ? histTrade.ClosingPrice
                : (pos.TradeType == TradeType.Buy ? _symbol.Bid : _symbol.Ask);
            ExecutionEngine.OnAttemptClosed(attempt, exitPrice, _robot.Server.Time, reason, pos.GrossProfit, pos.NetProfit);
        }

        private HistoricalTrade FindHistoricalTrade(long positionId)
        {
            for (int i = _robot.History.Count - 1; i >= 0; i--)
            {
                var t = _robot.History[i];
                if (t.PositionId == positionId) return t;
            }
            return null;
        }

        private void OnPendingOrderCancelled(PendingOrderCancelledEventArgs args)
        {
            var label = args.PendingOrder.Label;
            var attempt = FindAttempt(label);
            if (attempt == null) return;

            // Intent-based classification (Round 2 fix) -- NOT attempt.Status,
            // which may already have moved on to Pending (replacement order
            // from a move) or Cancelled (terminal cancel already applied) by
            // the time this confirmation arrives. Either way, if WE initiated
            // this specific cancellation, consume one unit of intent and stop:
            // the M5ExecutionEngine call site that triggered it already did
            // (or is doing) whatever attempt.Status transition is correct.
            if (_internalCancelIntent.TryGetValue(label, out var n) && n > 0)
            {
                if (n <= 1) _internalCancelIntent.Remove(label);
                else _internalCancelIntent[label] = n - 1;
                return;
            }

            attempt.Status = M5AttemptStatus.Cancelled;
            ManualInterventionDetected?.Invoke(attempt, "Pending order cancelled externally");
        }
    }
}
