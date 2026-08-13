// ICT_S1 — WeeklyOpportunityEngine. Spec: docs/s1_ea_specification.md
// sections 3, 4, 6.
//
// IMPLEMENTATION NOTE ON DIRECTIONAL CONTROL (flagging this clearly since
// it required resolving real tension between two confirmed rules rather
// than reading straight off the spec):
//
// The strategy owner confirmed Control is "scoped to the single narrative"
// and that Section 10/11 concurrency (multiple independent, even opposite-
// direction, WeeklyOpportunities trading simultaneously) "stands untouched."
// Combined with the walkthrough's own Phase B (a SELL trade fires off a
// bearish Old POI immediately on impact, BEFORE Control has shifted to
// SELL), the only self-consistent reading is: Control does NOT gate
// whether a WeeklyOpportunity may trade. Trading permission for every
// WeeklyOpportunity comes purely from its own POI cluster's lifecycle
// (section 2/6), independent of any other opportunity's state. Control is
// implemented here as a DESCRIPTIVE/journaled field per WeeklyOpportunity
// -- it records which direction currently "has the upper hand" in that
// specific narrative for audit purposes (the ControlChanged events read
// naturally in the journal, per the doc's own examples), but adds no
// additional veto. If this read is wrong, it's a one-place fix (the
// ComputeControlTransitions method below never touches Opportunity.Status).
//
// Two heuristics here are implementation choices, not stated rules --
// flagged inline where they occur: (1) which opposite-direction opportunity
// a given counter-POI's RETIRED event is "contesting" when several are
// active at once (most-recently-activated wins), and (2) NEUTRAL detection
// reuses the Weekly engine's own regime flip as the "phase ended" signal.

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum WeeklyOpportunityEventType
    {
        Activated,
        Retouched,
        ControlChanged,
        Terminated
    }

    public class WeeklyOpportunityEvent
    {
        public WeeklyOpportunityEventType Type;
        public WeeklyOpportunity Opportunity;
        public S1PoiSnapshot TriggeringPoi;
        public DateTime Time;
        public string Note;
    }

    public class WeeklyOpportunityEngine
    {
        private readonly PoiMarketEngine _engine;
        private readonly PoiLifecycleTracker _tracker;

        public readonly List<WeeklyOpportunity> Opportunities = new List<WeeklyOpportunity>();
        private readonly Queue<WeeklyOpportunityEvent> _eventQueue = new Queue<WeeklyOpportunityEvent>();

        private ControlState _lastKnownRegimeControl = ControlState.Neutral;

        public WeeklyOpportunityEngine(PoiMarketEngine weeklyEngine, PoiLifecycleTracker weeklyTracker)
        {
            _engine = weeklyEngine;
            _tracker = weeklyTracker;
        }

        public List<WeeklyOpportunityEvent> DrainEvents()
        {
            var list = new List<WeeklyOpportunityEvent>(_eventQueue.Count);
            while (_eventQueue.Count > 0) list.Add(_eventQueue.Dequeue());
            return list;
        }

        // Call once per cycle, after weeklyTracker.Update().
        public void Update()
        {
            foreach (var ev in _tracker.DrainEvents())
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
                        HandleTerminal(ev);
                        break;
                    case PoiEventType.Retired:
                        HandleTerminal(ev);
                        ComputeControlTransitionOnRetire(ev);
                        break;
                }
            }
            ComputeNeutralTransitions();
        }

        private void HandleNewImpact(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            var joinable = FindJoinableOpportunity(snap);
            if (joinable != null)
            {
                snap.WeeklyOpportunityId = joinable.WeeklyOpportunityId;
                snap.PoiClusterId = joinable.SupportingCluster.PoiClusterId;
                joinable.SupportingCluster.Members.Add(snap);
                _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = joinable, TriggeringPoi = snap, Time = ev.Time, Note = $"Joined existing cluster ({snap.TypeAtActivation})" });
                return;
            }

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);

            var opp = new WeeklyOpportunity
            {
                WeeklyOpportunityId = IdGenerator.NextWeeklyOpportunityId(),
                Direction = snap.Direction,
                ActivationTime = ev.Time,
                SupportingCluster = cluster,
                Control = snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl
            };
            snap.WeeklyOpportunityId = opp.WeeklyOpportunityId;
            snap.PoiClusterId = cluster.PoiClusterId;

            Opportunities.Add(opp);
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Activated, Opportunity = opp, TriggeringPoi = snap, Time = ev.Time, Note = $"Activated by {snap.TypeAtActivation}" });
        }

        // Clustering rule (spec section 4): any overlap, OR simultaneous
        // validity under one direction even without overlap (derived by
        // analogy to the confirmed H4-level answer -- flagged in the spec's
        // decision log as unconfirmed-by-direct-question).
        private WeeklyOpportunity FindJoinableOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                if (opp.Direction != snap.Direction) continue;
                // Any active same-direction opportunity qualifies -- overlap
                // is not required (the "simultaneously valid" extension).
                return opp;
            }
            return null;
        }

        private void HandleRetouch(PoiLifecycleEvent ev)
        {
            var opp = FindOwningOpportunity(ev.Snapshot);
            if (opp == null) return;
            opp.RetouchCounter++;
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = opp, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = $"Weekly retouch #{opp.RetouchCounter}" });
        }

        private void HandleTerminal(PoiLifecycleEvent ev)
        {
            var opp = FindOwningOpportunity(ev.Snapshot);
            if (opp == null) return;
            if (opp.Status == WeeklyOpportunityStatus.Terminated) return;
            if (opp.SupportingCluster.HasLiveMember) return; // other members keep the opportunity alive

            opp.Status = WeeklyOpportunityStatus.Terminated;
            opp.TerminationTime = ev.Time;
            opp.TerminationReason = $"All supporting POIs terminal (last: {ev.Snapshot.TypeAtActivation} {ev.Type})";
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Terminated, Opportunity = opp, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = opp.TerminationReason });
        }

        // A counter-direction POI just RETIRED (respected + reaction swing
        // confirmed) -- per spec section 3, this establishes Control in its
        // direction for whichever opposite-direction narrative it was
        // contesting. Heuristic: the most-recently-activated ACTIVE
        // opportunity of the opposite direction (documented above).
        private void ComputeControlTransitionOnRetire(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            var oppositeDir = snap.Direction == Direction.Buy ? Direction.Sell : Direction.Buy;

            WeeklyOpportunity contested = null;
            foreach (var opp in Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                if (opp.Direction != oppositeDir) continue;
                if (contested == null || opp.ActivationTime > contested.ActivationTime) contested = opp;
            }
            if (contested == null) return;

            var newControl = snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            if (contested.Control == newControl) return;

            contested.Control = newControl;
            contested.ControlSourcePoiId = snap.S1PoiId;
            contested.ControlSwingType = snap.RelevantReactionSwingType;
            contested.ControlSwingPrice = snap.RelevantReactionSwingPrice;
            contested.ControlSwingTime = snap.RelevantReactionSwingConfirmationTime;

            _eventQueue.Enqueue(new WeeklyOpportunityEvent
            {
                Type = WeeklyOpportunityEventType.ControlChanged,
                Opportunity = contested,
                TriggeringPoi = snap,
                Time = ev.Time,
                Note = $"Control -> {newControl} (source {snap.TypeAtActivation} {snap.S1PoiId})"
            });
        }

        // NEUTRAL detection (implementation choice, documented at file top):
        // reuse the Weekly engine's own regime as the "controlling phase
        // ended" signal -- when regime flips away from an opportunity's
        // current Control direction and no fresh same-direction opportunity
        // has taken over yet, Control -> Neutral.
        private void ComputeNeutralTransitions()
        {
            int regime = _engine.Regime; // 0=warmup,1=up,2=down
            if (regime == 0) return;
            var regimeDir = regime == 1 ? Direction.Buy : Direction.Sell;

            foreach (var opp in Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                bool controlMatchesRegime =
                    (opp.Control == ControlState.BuyControl && regimeDir == Direction.Buy) ||
                    (opp.Control == ControlState.SellControl && regimeDir == Direction.Sell);
                if (controlMatchesRegime || opp.Control == ControlState.Neutral) continue;

                // Regime has flipped away from this opportunity's current
                // Control direction -- that phase is over.
                opp.Control = ControlState.Neutral;
                _eventQueue.Enqueue(new WeeklyOpportunityEvent
                {
                    Type = WeeklyOpportunityEventType.ControlChanged,
                    Opportunity = opp,
                    TriggeringPoi = null,
                    Time = _engine.BT.Count > 0 ? _engine.BT[_engine.BT.Count - 1] : default(DateTime),
                    Note = "Control -> Neutral (regime reversed, no fresh opposite POI yet)"
                });
            }
        }

        private WeeklyOpportunity FindOwningOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
                if (opp.WeeklyOpportunityId == snap.WeeklyOpportunityId) return opp;
            return null;
        }
    }
}
