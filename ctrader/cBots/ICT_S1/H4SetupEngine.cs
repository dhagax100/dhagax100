// ICT_S1 — H4SetupEngine. Spec: docs/s1_ea_specification.md section 7.
// Repaired per the 2026-08-13 audit.
//
// CRITICAL 2 FIX — Weekly->H4 authorization was direction-only ("any active
// same-direction Weekly opportunity"), with no temporal or control
// constraint. That is the confirmed root cause of the 47-trade overtrading
// found in the first backtest: an H4 POI anywhere on the chart, unrelated
// to any real reaction near a specific Weekly zone, could still authorize
// a trade as long as SOME same-direction Weekly opportunity happened to be
// open. Fixed to require:
//   1. Temporal validity: the Weekly opportunity must have been ACTIVE at
//      or before this H4 POI's own impact time (defensive check per audit
//      section 6, on top of the chronological-processing fix in the main
//      Robot which should already guarantee this holds by construction).
//   2. Control gating (Critical 3): the Weekly opportunity may only
//      authorize a NEW H4Setup while its own Control currently matches its
//      own base Direction -- a narrative that has lost control (Neutral or
//      contested away) does not get to open fresh H4 activity, even though
//      it's still "Active" as an object.
//
// BLOCKED STRATEGY DECISION (audit section 63 -- flagging rather than
// inventing): when MULTIPLE same-direction Weekly opportunities are both
// temporally valid AND currently in their own control at the same H4
// impact moment, which one does that H4 POI actually belong to? Neither
// the Pine source nor the S1 spec gives a geometric-proximity rule (a
// price-distance threshold between the H4 POI and each Weekly zone would
// be new, invented strategy logic). Until the strategy owner answers this,
// the tie-break used below is "most recently activated among the temporally
// valid, currently-in-control candidates" -- a documented, narrow
// implementation choice, not a proven rule. This is the ONE remaining
// authorization ambiguity; everything else in Critical 2 is a real fix.
//
// FINDING 10 FIX — protected-swing reconstruction no longer falls back to
// the POI's own Zb/Zt when no real swing reference is found. A wrong
// protected swing can silently create false re-entries, so this now fails
// safely: reject the setup, journal why, do not arm anything.
//
// FINDING 11 FIX — every created H4Setup is now added to
// WeeklyOpportunity.H4Setups (was never populated before).

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
        private readonly Queue<RejectionEvent> _rejectionQueue = new Queue<RejectionEvent>();

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

        public List<RejectionEvent> DrainRejections()
        {
            var list = new List<RejectionEvent>(_rejectionQueue.Count);
            while (_rejectionQueue.Count > 0) list.Add(_rejectionQueue.Dequeue());
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

        // Call every tick with current quotes and the ACTUAL current time
        // (Server.Time during backtest -- NOT DateTime.UtcNow, see audit
        // section 32) -- spec section 7/9: any live tick >=0.5 pip beyond
        // the protected level, checked immediately.
        public void CheckProtectedSwingViolations(double bid, double ask, DateTime now, double violationPips = 0.5)
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
                    Terminate(setup, "Protected swing violated (≥0.5 pip)", now);
            }
        }

        private void HandleNewImpact(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;

            var (weekly, anyTemporallyValidCandidate) = FindArmingWeeklyOpportunity(snap.Direction, ev.Time);
            if (weekly == null)
            {
                var code = anyTemporallyValidCandidate
                    ? RejectionCode.H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL
                    : RejectionCode.H4_POI_REJECTED_NO_WEEKLY_PARENT;
                _rejectionQueue.Enqueue(new RejectionEvent { Code = code, Time = ev.Time, Direction = snap.Direction, PoiId = snap.S1PoiId, Note = $"{snap.TypeAtActivation} impact at {ev.Time:O} has no authorizing Weekly narrative" });
                return;
            }

            snap.WeeklyOpportunityId = weekly.WeeklyOpportunityId;

            var live = FindLiveSetup(weekly.WeeklyOpportunityId);
            if (live != null)
            {
                snap.PoiClusterId = live.SupportingCluster.PoiClusterId;
                live.SupportingCluster.Members.Add(snap);
                _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = live, TriggeringPoi = snap, Time = ev.Time, Note = $"H4 POI joined live setup ({snap.TypeAtActivation})" });
                return;
            }

            var route = IsInFavorType(snap.TypeAtActivation) ? H4Route.RouteA_Confirmed : H4Route.RouteB_Aggressive;
            var protectedSwing = ReconstructProtectedSwing(snap);
            if (protectedSwing == null)
            {
                // Finding 10: fail safely, no fake fallback -- do not arm.
                _rejectionQueue.Enqueue(new RejectionEvent { Code = RejectionCode.H4_POI_REJECTED_NO_PROTECTED_SWING, Time = ev.Time, Direction = snap.Direction, PoiId = snap.S1PoiId, Note = $"No real swing reference found before {snap.TypeAtActivation}'s trigger bar -- refusing to arm with a substituted level" });
                return;
            }

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);
            snap.PoiClusterId = cluster.PoiClusterId;

            var setup = new H4Setup
            {
                H4SetupId = IdGenerator.NextH4SetupId(),
                WeeklyOpportunityId = weekly.WeeklyOpportunityId,
                Direction = snap.Direction,
                Route = route,
                Status = H4SetupStatus.Impacted,
                SupportingCluster = cluster,
                ProtectedSwingType = protectedSwing.Value.Item1,
                ProtectedSwingPrice = protectedSwing.Value.Item2,
                ProtectedSwingTime = protectedSwing.Value.Item3,
                CreatedTime = ev.Time,
                WeeklyRetouchNumber = weekly.RetouchCounter
            };
            Setups.Add(setup);
            weekly.H4Setups.Add(setup); // Finding 11 fix
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Impacted, Setup = setup, TriggeringPoi = snap, Time = ev.Time, Note = $"{route} via {snap.TypeAtActivation}" });
        }

        private static bool IsInFavorType(PoiTypeLabel t) =>
            t == PoiTypeLabel.IFOB || t == PoiTypeLabel.IFVG || t == PoiTypeLabel.IRB || t == PoiTypeLabel.IVI;

        // Reconstruct the swing reference in effect at this POI's TriggerK
        // -- see class header note 1 (H4SetupEngine's original derivation).
        // Finding 10: returns null (no substitution) if none is found.
        private (SwingType, double, DateTime)? ReconstructProtectedSwing(S1PoiSnapshot snap)
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
            if (best == null) return null;

            var swingIdx = best.SwingIdx;
            var time = swingIdx >= 0 && swingIdx < _h4Engine.BT.Count ? _h4Engine.BT[swingIdx] : snap.FirstImpactTime;
            return (bull ? SwingType.Low : SwingType.High, best.Price, time);
        }

        // CRITICAL 2 + CRITICAL 3: returns the authorizing Weekly opportunity,
        // or null. The bool return tells the caller whether ANY temporally-
        // valid same-direction candidate existed at all (for accurate
        // rejection-code selection: NO_WEEKLY_PARENT vs NOT_IN_CONTROL).
        private (WeeklyOpportunity, bool) FindArmingWeeklyOpportunity(Direction dir, DateTime h4EventTime)
        {
            WeeklyOpportunity chosen = null;
            bool anyTemporallyValid = false;

            foreach (var opp in _weeklyEngine.Opportunities)
            {
                if (opp.Direction != dir) continue;
                // Temporal authorization guard (audit section 6): a Weekly
                // opportunity activated AFTER this H4 event cannot author it,
                // and one already terminated BEFORE this H4 event cannot
                // either. Defensive on top of chronological processing.
                if (opp.ActivationTime > h4EventTime) continue;
                if (opp.Status == WeeklyOpportunityStatus.Terminated && opp.TerminationTime != null && opp.TerminationTime.Value <= h4EventTime) continue;
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;

                anyTemporallyValid = true;

                bool inOwnControl = (opp.Control == ControlState.BuyControl && opp.Direction == Direction.Buy)
                                  || (opp.Control == ControlState.SellControl && opp.Direction == Direction.Sell);
                if (!inOwnControl) continue; // Critical 3 gate: not currently in control of its own narrative

                if (chosen == null || opp.ActivationTime > chosen.ActivationTime) chosen = opp; // documented tie-break, see class header BLOCKED note
            }
            return (chosen, anyTemporallyValid);
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
