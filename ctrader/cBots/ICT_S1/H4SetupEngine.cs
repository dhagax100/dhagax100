// ICT_S1 — H4SetupEngine. Spec: docs/s1_ea_specification.md section 7.
//
// TWO IMPLEMENTATION CHOICES DOCUMENTED HERE (mechanical derivations from
// confirmed rules, not new strategy decisions -- flagged per the "explain
// the derivation" instruction rather than re-asking):
//
// 1. Protected-swing reconstruction. The confirmed rule is "the SAME swing
//    reference the POI itself was created from internally." The raw engine
//    (PoiMarketEngine) tracks exactly one 'current' swing low and one
//    'current' swing high at any moment (_swlIdx/_swhIdx, _lastSWLidx/
//    _lastSWHidx) -- every POI-creation function reads one of those same
//    underlying values, just via different local parameter names
//    (aobSWHi, pLastSWLi, swlIdx, etc. all resolve to the same tracked
//    state at that instant). So instead of threading a new field through
//    every Add*/Try* call site, this reconstructs it: for a BUY H4 POI,
//    scan the H4 engine's own Events for the swing LOW with the latest
//    ConfirmIdx at or before the POI's TriggerK bar -- that IS the swing
//    reference in effect at creation time, by construction. Mirrored for
//    SELL using swing HIGH.
//
// 2. H4Setup-per-WeeklyOpportunity exclusivity. The confirmed answer for
//    simultaneously-valid H4 POIs was "cluster into one, look for one
//    trade" -- this is applied continuously over time too: a Weekly
//    opportunity has at most ONE live (non-terminated) H4Setup at a time;
//    a fresh H4 POI impact either joins that live setup's cluster, or, if
//    none is live, starts a new one (this is what "Retouch #1 -> H4Setup
//    H001, Retouch #2 -> H4Setup H002" in the spec's retouch example
//    actually requires -- H002 only starts once H001 has terminated).
//
// Route derivation (fully mechanical, no ambiguity): IFOB/IFVG/IRB/IVI ->
// RouteA_Confirmed; AOB/AFVG/ARB/AVI/AIFOB/AIRB -> RouteB_Aggressive
// (AIFOB/AIRB are still-pending at the MID-ARM moment, same timing as the
// Aggressive family, hence Route B if impacted before promotion).

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum H4SetupEventType
    {
        Created,
        Impacted,
        Retouched,
        Terminated
    }

    public class H4SetupEvent
    {
        public H4SetupEventType Type;
        public H4Setup Setup;
        public S1PoiSnapshot TriggeringPoi;
        public DateTime Time;
        public string Note;
    }

    public class H4SetupEngine
    {
        private readonly PoiMarketEngine _h4Engine;
        private readonly PoiLifecycleTracker _h4Tracker;
        private readonly WeeklyOpportunityEngine _weeklyEngine;
        private readonly double _pipSize;

        public readonly List<H4Setup> Setups = new List<H4Setup>();
        private readonly Queue<H4SetupEvent> _eventQueue = new Queue<H4SetupEvent>();

        public H4SetupEngine(PoiMarketEngine h4Engine, PoiLifecycleTracker h4Tracker, WeeklyOpportunityEngine weeklyEngine, double pipSize)
        {
            _h4Engine = h4Engine;
            _h4Tracker = h4Tracker;
            _weeklyEngine = weeklyEngine;
            _pipSize = pipSize;
        }

        public List<H4SetupEvent> DrainEvents()
        {
            var list = new List<H4SetupEvent>(_eventQueue.Count);
            while (_eventQueue.Count > 0) list.Add(_eventQueue.Dequeue());
            return list;
        }

        // Call once per cycle with the SAME event batch the caller already
        // drained from h4Tracker (single-drain, fanned out by the caller --
        // see WeeklyOpportunityEngine.Update for the same pattern).
        public void Update(List<PoiLifecycleEvent> poiEvents)
        {
            foreach (var ev in poiEvents)
            {
                switch (ev.Type)
                {
                    case PoiEventType.NewImpact:
                        HandleNewImpact(ev);
                        break;
                    case PoiEventType.Retouch:
                        HandleRetouch(ev);
                        break;
                    case PoiEventType.Invalidated:
                    case PoiEventType.Retired:
                        HandleTerminalPoi(ev);
                        break;
                }
            }
        }

        // Call every tick with current quotes -- spec section 7/9: any live
        // tick >=0.5 pip beyond the protected level, checked immediately.
        public void CheckProtectedSwingViolations(double bid, double ask, double violationPips = 0.5)
        {
            double violationDistance = violationPips * _pipSize;
            foreach (var setup in Setups)
            {
                if (setup.Status != H4SetupStatus.Impacted && setup.Status != H4SetupStatus.Watching) continue;
                bool violated;
                if (setup.Direction == Direction.Buy)
                    violated = bid <= setup.ProtectedSwingPrice - violationDistance;
                else
                    violated = ask >= setup.ProtectedSwingPrice + violationDistance;

                if (violated)
                    Terminate(setup, "Protected swing violated (≥0.5 pip)", DateTime.UtcNow);
            }
        }

        private void HandleNewImpact(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            var weekly = FindArmingWeeklyOpportunity(snap.Direction);
            if (weekly == null) return; // no valid Weekly opportunity authorizes this direction -- section 6/28

            snap.WeeklyOpportunityId = weekly.WeeklyOpportunityId;

            var live = FindLiveSetup(weekly.WeeklyOpportunityId);
            if (live != null)
            {
                snap.PoiClusterId = live.SupportingCluster.PoiClusterId;
                live.SupportingCluster.Members.Add(snap);
                _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = live, TriggeringPoi = snap, Time = ev.Time, Note = $"H4 POI joined live setup ({snap.TypeAtActivation})" });
                return;
            }

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);
            snap.PoiClusterId = cluster.PoiClusterId;

            var route = IsInFavorType(snap.TypeAtActivation) ? H4Route.RouteA_Confirmed : H4Route.RouteB_Aggressive;
            var (swingType, swingPrice, swingTime) = ReconstructProtectedSwing(snap);

            var setup = new H4Setup
            {
                H4SetupId = IdGenerator.NextH4SetupId(),
                WeeklyOpportunityId = weekly.WeeklyOpportunityId,
                Direction = snap.Direction,
                Route = route,
                Status = H4SetupStatus.Impacted,
                SupportingCluster = cluster,
                ProtectedSwingType = swingType,
                ProtectedSwingPrice = swingPrice,
                ProtectedSwingTime = swingTime,
                CreatedTime = ev.Time,
                WeeklyRetouchNumber = weekly.RetouchCounter
            };
            Setups.Add(setup);
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Impacted, Setup = setup, TriggeringPoi = snap, Time = ev.Time, Note = $"{route} via {snap.TypeAtActivation}" });
        }

        private static bool IsInFavorType(PoiTypeLabel t) =>
            t == PoiTypeLabel.IFOB || t == PoiTypeLabel.IFVG || t == PoiTypeLabel.IRB || t == PoiTypeLabel.IVI;

        // Reconstruct the swing reference in effect at this POI's TriggerK
        // -- see file header note 1.
        private (SwingType, double, DateTime) ReconstructProtectedSwing(S1PoiSnapshot snap)
        {
            bool bull = snap.Direction == Direction.Buy;
            int wantKind = bull ? 1 : 0; // BUY protected by a swing LOW, SELL by a swing HIGH
            SwEv best = null;
            foreach (var e in _h4Engine.Events)
            {
                if (e.Kind != wantKind) continue;
                if (e.ConfirmIdx > snap.FirstImpactBarIndex) continue;
                if (best == null || e.ConfirmIdx > best.ConfirmIdx) best = e;
            }
            if (best == null)
                return (bull ? SwingType.Low : SwingType.High, bull ? snap.Zb : snap.Zt, snap.FirstImpactTime);

            var swingIdx = best.SwingIdx;
            var time = swingIdx >= 0 && swingIdx < _h4Engine.BT.Count ? _h4Engine.BT[swingIdx] : snap.FirstImpactTime;
            return (bull ? SwingType.Low : SwingType.High, best.Price, time);
        }

        private WeeklyOpportunity FindArmingWeeklyOpportunity(Direction dir)
        {
            WeeklyOpportunity chosen = null;
            foreach (var opp in _weeklyEngine.Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                if (opp.Direction != dir) continue;
                if (chosen == null || opp.ActivationTime > chosen.ActivationTime) chosen = opp;
            }
            return chosen;
        }

        private H4Setup FindLiveSetup(string weeklyOpportunityId)
        {
            foreach (var s in Setups)
                if (s.WeeklyOpportunityId == weeklyOpportunityId && s.Status != H4SetupStatus.Terminated)
                    return s;
            return null;
        }

        private void HandleRetouch(PoiLifecycleEvent ev)
        {
            var setup = FindOwningSetup(ev.Snapshot);
            if (setup == null) return;
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = setup, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = "H4 POI retouched" });
        }

        private void HandleTerminalPoi(PoiLifecycleEvent ev)
        {
            var setup = FindOwningSetup(ev.Snapshot);
            if (setup == null) return;
            if (setup.Status == H4SetupStatus.Terminated) return;
            if (setup.SupportingCluster.HasLiveMember) return;

            Terminate(setup, $"All supporting H4 POIs terminal (last: {ev.Snapshot.TypeAtActivation} {ev.Type})", ev.Time);
        }

        private void Terminate(H4Setup setup, string reason, DateTime time)
        {
            setup.Status = H4SetupStatus.Terminated;
            setup.TerminatedTime = time;
            setup.TerminationReason = reason;
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Terminated, Setup = setup, TriggeringPoi = null, Time = time, Note = reason });
            // Parent WeeklyOpportunity is deliberately untouched (spec section 7).
        }

        private H4Setup FindOwningSetup(S1PoiSnapshot snap)
        {
            foreach (var s in Setups)
                if (s.SupportingCluster.Members.Contains(snap))
                    return s;
            return null;
        }
    }
}
