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
        // Round 2 fix (audit section 27): marks the exact moment the M5
        // execution window (re)opens for a setup -- the boundary
        // TryGetRelevantSwings now enforces (see H4Setup.M5ExecutionActivationTime).
        public event Action<H4Setup, DateTime> M5ExecutionActivated;

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

            // Round 2 fix (audit section 19): (re)open the M5 execution
            // activation window right as this tracking cycle begins -- see
            // H4Setup.M5ExecutionActivationTime field comment.
            setup.M5ExecutionActivationTime = _m5Engine.LastProcessedIndex >= 0 && _m5Engine.LastProcessedIndex < _m5Engine.BT.Count
                ? _m5Engine.BT[_m5Engine.LastProcessedIndex]
                : setup.CreatedTime;
            M5ExecutionActivated?.Invoke(setup, setup.M5ExecutionActivationTime.Value);

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
                attempt.LastCancellationReason = reason;
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
            var setup = FindSetup(attempt.H4SetupId);
            if (setup == null || setup.M5ExecutionActivationTime == null) return;
            if (!TryGetRelevantSwings(setup, out var entryIdx, out var entryPrice, out var entryTime,
                                       out var stopIdx, out var stopPrice, out var stopTime))
                return;

            PlaceForSwing(attempt, entryIdx, entryPrice, entryTime, stopIdx, stopPrice, stopTime);
        }

        private void TryMoveOrder(M5Attempt attempt)
        {
            var setup = FindSetup(attempt.H4SetupId);
            if (setup == null || setup.M5ExecutionActivationTime == null) return;
            if (!TryGetRelevantSwings(setup, out var entryIdx, out var entryPrice, out var entryTime,
                                       out var stopIdx, out var stopPrice, out var stopTime))
                return;

            bool sameSwing = entryTime == attempt.EntrySwingTime && stopTime == attempt.StopSwingTime;
            if (sameSwing) return;

            // Capture the outgoing pairing for the ORDER_MOVED journal row
            // before PlaceForSwing overwrites Entry/StopSwing* with the new
            // one (audit section 3/27 -- explicit A->B, not a silent overwrite).
            attempt.PreviousEntrySwingType = attempt.EntrySwingType;
            attempt.PreviousEntrySwingPrice = attempt.EntrySwingPrice;
            attempt.PreviousEntrySwingTime = attempt.EntrySwingTime;
            attempt.PreviousStopSwingType = attempt.StopSwingType;
            attempt.PreviousStopSwingPrice = attempt.StopSwingPrice;
            attempt.PreviousStopSwingTime = attempt.StopSwingTime;

            // Round 2 fix (audit section 5/6): this move's cancel is an
            // INTERNAL, intentional cancellation -- not a manual one.
            // Recorded on the executor BEFORE the real cancel call so the
            // async PendingOrderCancelled callback (which can fire after
            // this attempt's Status has already moved back to Pending for
            // the replacement order) can still be correctly classified.
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
            // Actual simulated bar time this order was placed at -- not
            // DateTime.UtcNow (audit section 32: that's real wall-clock
            // time, meaningless during a historical backtest replay).
            var placedAt = _m5Engine.LastProcessedIndex >= 0 && _m5Engine.LastProcessedIndex < _m5Engine.BT.Count
                ? _m5Engine.BT[_m5Engine.LastProcessedIndex]
                : entryTime;
            // Round 2 fix (audit section 3): FirstPendingOrderCreatedTime is
            // set exactly once (immutable identity of the attempt's first
            // order); PendingOrderCreatedTime is the CURRENT order's own
            // placement time and updates on every move, so it always stays
            // consistent with whichever EntrySwingTime/StopSwingTime pairing
            // is currently live -- this is what removes the "order created
            // before its authorizing swing" false appearance in the journal.
            attempt.FirstPendingOrderCreatedTime = attempt.FirstPendingOrderCreatedTime ?? placedAt;
            attempt.PendingOrderCreatedTime = placedAt;
            attempt.Status = M5AttemptStatus.Pending;
            OrderPlaced?.Invoke(attempt);
        }

        private H4Setup FindSetup(string h4SetupId)
        {
            foreach (var s in _h4Engine.Setups)
                if (s.H4SetupId == h4SetupId)
                    return s;
            return null;
        }

        private DateTime BarTime(int idx) =>
            idx >= 0 && idx < _m5Engine.BT.Count ? _m5Engine.BT[idx] : default(DateTime);

        // Round 2 fix (audit sections 6/19): "relevant" M5 swing used to
        // mean "the most recently confirmed swing of each kind, queried
        // independently from the engine's ENTIRE history" -- with no
        // relationship to this setup's own M5 execution window and no
        // relationship to EACH OTHER. That could pair a fresh entry swing
        // with an ancient, structurally unrelated stop swing (e.g. the very
        // swing that just stopped out a prior attempt on this same setup),
        // which is a confirmed contributor to the repeated-attempts anomaly.
        //
        // Fixed to require BOTH:
        //   1. Confirmed strictly after setup.M5ExecutionActivationTime
        //      (this attempt cycle's own window -- not stale history).
        //   2. Structurally adjacent: swings on one timeframe strictly
        //      alternate High/Low/High/Low (engine invariant), so the
        //      correct stop swing for a given entry swing is the nearest
        //      OPPOSITE-kind swing confirmed immediately before it in that
        //      same filtered sequence -- not independently "the latest of
        //      each kind ever seen".
        //
        // Still no requirement that either swing sits inside the H4 POI's
        // physical box (spec section 8/22 -- unchanged).
        private bool TryGetRelevantSwings(H4Setup setup, out int entryIdx, out double entryPrice, out DateTime entryTime,
                                           out int stopIdx, out double stopPrice, out DateTime stopTime)
        {
            entryIdx = stopIdx = -1;
            entryPrice = stopPrice = 0;
            entryTime = stopTime = default(DateTime);

            bool bull = setup.Direction == Direction.Buy;
            int entryKind = bull ? 0 : 1; // 0=High, 1=Low
            int stopKind = bull ? 1 : 0;
            DateTime activation = setup.M5ExecutionActivationTime.Value;

            var events = _m5Engine.Events;

            int entryEvIdx = -1;
            for (int i = events.Count - 1; i >= 0; i--)
            {
                var e = events[i];
                if (e.Kind != entryKind) continue;
                if (BarTime(e.ConfirmIdx) <= activation) break; // chronological list -- nothing earlier can qualify either
                entryEvIdx = i;
                break;
            }
            if (entryEvIdx == -1) return false;

            int stopEvIdx = -1;
            for (int i = entryEvIdx - 1; i >= 0; i--)
            {
                var e = events[i];
                if (BarTime(e.ConfirmIdx) <= activation) break;
                if (e.Kind == stopKind) { stopEvIdx = i; break; }
            }
            if (stopEvIdx == -1) return false;

            var entryEv = events[entryEvIdx];
            var stopEv = events[stopEvIdx];
            entryIdx = entryEv.SwingIdx;
            stopIdx = stopEv.SwingIdx;
            entryPrice = entryEv.Price;
            stopPrice = stopEv.Price;
            entryTime = BarTime(entryEv.ConfirmIdx);
            stopTime = BarTime(stopEv.ConfirmIdx);
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
