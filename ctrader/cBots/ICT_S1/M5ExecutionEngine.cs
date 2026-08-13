// ICT_S1 — M5ExecutionEngine. Spec: docs/s1_ea_specification.md section 8.
//
// M5 needs only Swing High/Low + dynamic stop-entry placement (master
// prompt section 3 -- "Do not require an additional discretionary M5 POI
// model"), so this reads directly off the M5 PoiMarketEngine's raw
// SwHighs/SwLows -- no PoiLifecycleTracker involved at this timeframe.
//
// cAlgo API surface (order placement, fills, closes) is deliberately kept
// out of this file -- ITradeExecutor is the seam. TradeManager implements
// it against the real Robot API; this class only knows swing/attempt
// logic. Same reasoning as the rest of this build: keep strategy logic
// separable from platform-mechanics code that needs a real compiler to
// verify.

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    // Seam between M5ExecutionEngine's pure logic and cAlgo's real trading
    // API (implemented by TradeManager).
    public interface ITradeExecutor
    {
        double Bid { get; }
        double Ask { get; }
        double PipSize { get; }
        double ComputeVolume(double slDistance);
        // Returns a broker-side pending order id, or null if placement failed.
        string PlaceStopOrder(Direction dir, double volume, double triggerPrice, double slPrice, double tpPrice, string label);
        void ModifyPendingOrder(string orderId, double newTriggerPrice, double newSlPrice, double newTpPrice);
        void CancelPendingOrder(string orderId);
    }

    public class M5ExecutionEngine
    {
        private readonly PoiMarketEngine _m5Engine;
        private readonly H4SetupEngine _h4Engine;
        private readonly ITradeExecutor _executor;

        // One live (non-closed, non-cancelled) attempt per H4SetupId at most
        // -- spec confirmed: sequential only, never concurrent within a setup.
        private readonly Dictionary<string, M5Attempt> _liveAttemptByH4Setup = new Dictionary<string, M5Attempt>();
        public readonly List<M5Attempt> AllAttempts = new List<M5Attempt>();

        public event Action<M5Attempt> AttemptCreated;
        public event Action<M5Attempt> OrderPlaced;
        public event Action<M5Attempt> OrderMoved;
        public event Action<M5Attempt> OrderCancelled;
        public event Action<M5Attempt> AttemptFilled;
        public event Action<M5Attempt> AttemptClosed;

        public M5ExecutionEngine(PoiMarketEngine m5Engine, H4SetupEngine h4Engine, ITradeExecutor executor)
        {
            _m5Engine = m5Engine;
            _h4Engine = h4Engine;
            _executor = executor;
        }

        // Call once per cycle, after the M5 PoiMarketEngine.Update() and
        // after H4SetupEngine.Update() (events already drained there --
        // this reads H4SetupEngine.Setups directly, not its event queue,
        // since M5 needs to react to a setup's CURRENT status every cycle,
        // not just the instant it changed).
        public void Update()
        {
            foreach (var setup in _h4Engine.Setups)
            {
                if (setup.Status == H4SetupStatus.Impacted)
                    EnsureAttemptTracking(setup);
                else if (setup.Status == H4SetupStatus.Terminated)
                    CancelLiveAttemptIfAny(setup, "Parent H4Setup terminated");
            }

            foreach (var kvp in _liveAttemptByH4Setup)
                ProcessAttempt(kvp.Value);
        }

        private void EnsureAttemptTracking(H4Setup setup)
        {
            if (_liveAttemptByH4Setup.ContainsKey(setup.H4SetupId)) return;
            if (setup.HasOpenAttempt) return; // an attempt already ran to open/close and no new one started yet -- handled by ProcessAttempt's re-entry path instead

            var attempt = new M5Attempt
            {
                M5AttemptId = IdGenerator.NextM5AttemptId(),
                H4SetupId = setup.H4SetupId,
                Direction = setup.Direction,
                Status = M5AttemptStatus.TrackingSwing,
                AttemptNumber = setup.M5Attempts.Count + 1
            };
            setup.M5Attempts.Add(attempt);
            AllAttempts.Add(attempt);
            _liveAttemptByH4Setup[setup.H4SetupId] = attempt;
            AttemptCreated?.Invoke(attempt);
        }

        private void CancelLiveAttemptIfAny(H4Setup setup, string reason)
        {
            if (!_liveAttemptByH4Setup.TryGetValue(setup.H4SetupId, out var attempt)) return;
            if (attempt.Status == M5AttemptStatus.TrackingSwing)
            {
                attempt.Status = M5AttemptStatus.Cancelled;
            }
            else if (attempt.Status == M5AttemptStatus.Pending)
            {
                if (attempt.PendingOrderId != null) _executor.CancelPendingOrder(attempt.PendingOrderId);
                attempt.Status = M5AttemptStatus.Cancelled;
                OrderCancelled?.Invoke(attempt);
            }
            // Triggered/Open attempts are live positions -- those are left
            // to TradeManager's own close handling, not force-closed here;
            // an already-filled position is a real market exposure, not a
            // pending order this engine can simply cancel.
            _liveAttemptByH4Setup.Remove(setup.H4SetupId);
        }

        private void ProcessAttempt(M5Attempt attempt)
        {
            if (attempt.Status == M5AttemptStatus.TrackingSwing)
            {
                TryPlaceOrder(attempt);
            }
            else if (attempt.Status == M5AttemptStatus.Pending)
            {
                TryMoveOrder(attempt);
            }
        }

        private void TryPlaceOrder(M5Attempt attempt)
        {
            if (!TryGetRelevantSwings(attempt.Direction, out var entryIdx, out var entryPrice, out var entryTime,
                                       out var stopIdx, out var stopPrice, out var stopTime))
                return;

            PlaceForSwing(attempt, entryIdx, entryPrice, entryTime, stopIdx, stopPrice, stopTime);
        }

        private void TryMoveOrder(M5Attempt attempt)
        {
            if (!TryGetRelevantSwings(attempt.Direction, out var entryIdx, out var entryPrice, out var entryTime,
                                       out var stopIdx, out var stopPrice, out var stopTime))
                return;

            bool sameSwing = entryTime == attempt.EntrySwingTime && stopTime == attempt.StopSwingTime;
            if (sameSwing) return;

            if (attempt.PendingOrderId != null) _executor.CancelPendingOrder(attempt.PendingOrderId);
            PlaceForSwing(attempt, entryIdx, entryPrice, entryTime, stopIdx, stopPrice, stopTime);
            attempt.PendingOrderModificationCount++;
            OrderMoved?.Invoke(attempt);
        }

        private void PlaceForSwing(M5Attempt attempt, int entryIdx, double entryPrice, DateTime entryTime,
                                    int stopIdx, double stopPrice, DateTime stopTime)
        {
            bool bull = attempt.Direction == Direction.Buy;
            double spreadBuffer = _executor.Ask - _executor.Bid;
            double sl = bull ? stopPrice - spreadBuffer : stopPrice + spreadBuffer;
            double risk = Math.Abs(entryPrice - sl);
            double tp = bull ? entryPrice + 3 * risk : entryPrice - 3 * risk;
            double volume = _executor.ComputeVolume(risk);

            var orderId = _executor.PlaceStopOrder(attempt.Direction, volume, entryPrice, sl, tp, attempt.M5AttemptId);
            if (orderId == null) return;

            attempt.EntrySwingType = bull ? SwingType.High : SwingType.Low;
            attempt.EntrySwingPrice = entryPrice;
            attempt.EntrySwingTime = entryTime;
            attempt.StopSwingType = bull ? SwingType.Low : SwingType.High;
            attempt.StopSwingPrice = stopPrice;
            attempt.StopSwingTime = stopTime;
            attempt.RequestedEntryPrice = entryPrice;
            attempt.SLPrice = sl;
            attempt.TPPrice = tp;
            attempt.PendingOrderId = orderId;
            attempt.PendingOrderCreatedTime = attempt.PendingOrderCreatedTime ?? DateTime.UtcNow;
            attempt.Status = M5AttemptStatus.Pending;
            OrderPlaced?.Invoke(attempt);
        }

        // "Relevant" M5 swing = the most recently confirmed swing of the
        // needed kind on this timeframe. No requirement that it sits
        // inside the H4 POI's physical box (spec section 8/22).
        private bool TryGetRelevantSwings(Direction dir, out int entryIdx, out double entryPrice, out DateTime entryTime,
                                           out int stopIdx, out double stopPrice, out DateTime stopTime)
        {
            entryIdx = stopIdx = -1;
            entryPrice = stopPrice = 0;
            entryTime = stopTime = default(DateTime);

            bool bull = dir == Direction.Buy;
            var entryList = bull ? _m5Engine.SwHighs : _m5Engine.SwLows;
            var stopList = bull ? _m5Engine.SwLows : _m5Engine.SwHighs;
            if (entryList.Count == 0 || stopList.Count == 0) return false;

            entryIdx = entryList[entryList.Count - 1];
            stopIdx = stopList[stopList.Count - 1];

            entryPrice = bull ? _m5Engine.H[entryIdx] : _m5Engine.L[entryIdx];
            stopPrice = bull ? _m5Engine.L[stopIdx] : _m5Engine.H[stopIdx];
            entryTime = _m5Engine.BT[entryIdx];
            stopTime = _m5Engine.BT[stopIdx];
            return true;
        }

        // TradeManager calls these back on real fills/closes.
        public void OnAttemptFilled(M5Attempt attempt, double fillPrice, DateTime fillTime)
        {
            bool bull = attempt.Direction == Direction.Buy;
            double risk = Math.Abs(fillPrice - attempt.SLPrice);
            // Slippage/gap recalculation from actual fill (confirmed rule).
            attempt.SLPrice = bull ? attempt.SLPrice : attempt.SLPrice; // SL distance/level unchanged by design (buffer already set); only entry+TP re-anchor to actual fill
            attempt.TPPrice = bull ? fillPrice + 3 * risk : fillPrice - 3 * risk;
            attempt.ActualFillPrice = fillPrice;
            attempt.EntryTime = fillTime;
            attempt.Status = M5AttemptStatus.Open;
            AttemptFilled?.Invoke(attempt);
        }

        public void OnAttemptClosed(M5Attempt attempt, double exitPrice, DateTime exitTime, ExitReason reason,
                                     double grossPnL, double netPnL)
        {
            attempt.ExitPrice = exitPrice;
            attempt.ExitTime = exitTime;
            attempt.ExitReason = reason;
            attempt.GrossPnL = grossPnL;
            attempt.NetPnL = netPnL;
            double risk = Math.Abs((attempt.ActualFillPrice ?? attempt.RequestedEntryPrice) - attempt.SLPrice);
            bool bull = attempt.Direction == Direction.Buy;
            double priceMove = bull ? exitPrice - (attempt.ActualFillPrice ?? attempt.RequestedEntryPrice)
                                     : (attempt.ActualFillPrice ?? attempt.RequestedEntryPrice) - exitPrice;
            attempt.RealizedR = risk > 0 ? priceMove / risk : 0;
            attempt.Status = reason == ExitReason.TakeProfit ? M5AttemptStatus.ClosedTP : M5AttemptStatus.ClosedSL;

            var h4SetupId = attempt.H4SetupId;
            _liveAttemptByH4Setup.Remove(h4SetupId);
            AttemptClosed?.Invoke(attempt);

            // Re-entry: only on SL, and only if the parent H4Setup is still
            // live -- +3R does NOT re-arm (confirmed rule; EnsureAttemptTracking
            // will simply not fire again until a fresh H4 POI impact creates
            // a new H4Setup).
            if (reason == ExitReason.StopLoss)
            {
                foreach (var setup in _h4Engine.Setups)
                {
                    if (setup.H4SetupId == h4SetupId && setup.Status == H4SetupStatus.Impacted)
                        EnsureAttemptTracking(setup);
                }
            }
        }
    }
}
