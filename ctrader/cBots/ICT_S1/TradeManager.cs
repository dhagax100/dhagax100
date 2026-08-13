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

using System;
using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    public class TradeManager : ITradeExecutor
    {
        private readonly Robot _robot;
        private readonly Symbol _symbol;
        private readonly RiskManager _riskManager;

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

            // Exit price: current quote at close time as the closest
            // available proxy -- verify whether the installed API exposes
            // Position's actual closing price more directly (see file header).
            double exitPrice = pos.TradeType == TradeType.Buy ? _symbol.Bid : _symbol.Ask;
            ExecutionEngine.OnAttemptClosed(attempt, exitPrice, _robot.Server.Time, reason, pos.GrossProfit, pos.NetProfit);
        }

        private void OnPendingOrderCancelled(PendingOrderCancelledEventArgs args)
        {
            var attempt = FindAttempt(args.PendingOrder.Label);
            if (attempt == null) return;
            if (attempt.Status == M5AttemptStatus.Cancelled) return; // we already did this ourselves

            attempt.Status = M5AttemptStatus.Cancelled;
            ManualInterventionDetected?.Invoke(attempt, "Pending order cancelled externally");
        }
    }
}
