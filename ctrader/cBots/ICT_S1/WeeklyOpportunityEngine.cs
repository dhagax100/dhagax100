// ICT_S1 — WeeklyOpportunityEngine. Spec: docs/s1_ea_specification.md
// sections 3, 4, 6. Repaired per the 2026-08-13 audit (see repair notes
// inline at each fix).
//
// DIRECTIONAL CONTROL — CORRECTED MODEL (audit Critical 3 / Findings 8,9):
// Control is narrative-scoped, never global (Section 10/11 concurrency
// stands). Within its OWN narrative it DOES have a real consequence: a
// WeeklyOpportunity may only authorize NEW H4Setups while its own Control
// currently matches its own base Direction (enforced in H4SetupEngine).
// Existing already-open H4Setups/M5Attempts are not force-closed when
// Control moves away -- they continue under their own independent rules.
// This was previously implemented as journal-only (documented as a
// deliberate reading at the time); the audit correctly identified that
// reading as wrong given the doc's own NEUTRAL example ("SELL entries =
// OFF and BUY entries = OFF for THAT narrative").
//
// Two heuristics remain (now fixed AT CREATION TIME, not re-derived later):
// (1) which opposite-direction opportunity a new counter-POI's own
//     narrative is contesting -- decided once, when that counter narrative
//     is created, and stored as ContestingOfWeeklyOpportunityId. Zone
//     overlap can't be the test here (a counter-POI typically forms well
//     away from the original zone after price has moved), so the tie-break
//     is "whichever opposite-direction opportunity currently holds control
//     in its own direction" -- still a documented implementation choice,
//     but now fixed once instead of re-guessed by recency at retirement
//     time (the actual defect).
// (2) NEUTRAL detection no longer uses the raw Weekly regime flag (that
//     heuristic is removed per Finding 8 -- Pine regime and S1 Control are
//     NOT confirmed equivalent). It now directly follows the doc's own
//     worked example: the current controlling direction's own next
//     opposite-kind swing (SellControl ends on the next Weekly Swing Low,
//     BuyControl ends on the next Weekly Swing High) ends that phase.

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

        // Cursor into _engine.Events for incremental Neutral-detection scans
        // (Finding 8 fix) -- avoids rescanning all history every cycle.
        private int _lastSwingCheckIdx = -1;

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

        // Call once per cycle with the SAME event batch the caller already
        // drained from weeklyTracker (a Queue can only be drained by one
        // consumer -- the caller owns the single drain and fans the batch
        // out to this engine AND to Journal/Visualization directly).
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
                ReactivateFromNeutralIfDue(joinable, ev.Time);
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

            // Finding 9 fix: establish the contesting relationship ONCE, now,
            // explicitly -- not re-guessed later by recency at retirement.
            LinkContestingNarrativeIfAny(opp, ev.Time);

            Opportunities.Add(opp);
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Activated, Opportunity = opp, TriggeringPoi = snap, Time = ev.Time, Note = $"Activated by {snap.TypeAtActivation}" });
        }

        // Finding 4 fix: Weekly clustering requires GENUINE price overlap
        // with at least one existing member of an active same-direction
        // opportunity's cluster. The earlier "any active same-direction
        // opportunity qualifies" rule was an unconfirmed extension of the
        // H4-specific non-overlap rule -- that rule was never confirmed at
        // Weekly level, so the safe default (independent opportunities
        // supported explicitly by section 10) applies instead.
        private WeeklyOpportunity FindJoinableOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                if (opp.Direction != snap.Direction) continue;
                foreach (var member in opp.SupportingCluster.Members)
                {
                    if (Math.Max(member.Zb, snap.Zb) <= Math.Min(member.Zt, snap.Zt))
                        return opp;
                }
            }
            return null;
        }

        // Finding 9: a counter-direction POI's zone typically does NOT
        // overlap the original narrative's zone (price has already moved
        // away by the time a counter-POI forms) -- so overlap can't be the
        // contesting test. Instead: at the moment this counter-direction
        // opportunity is created, link it to whichever ACTIVE opposite-
        // direction opportunity currently holds control in its own
        // direction (the one genuinely "in play" right now). This is a
        // documented implementation choice, but fixed once at creation,
        // not re-derived later.
        private void LinkContestingNarrativeIfAny(WeeklyOpportunity newOpp, DateTime now)
        {
            var oppositeDir = newOpp.Direction == Direction.Buy ? Direction.Sell : Direction.Buy;
            WeeklyOpportunity target = null;
            foreach (var opp in Opportunities)
            {
                if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                if (opp.Direction != oppositeDir) continue;
                bool inOwnControl = (opp.Control == ControlState.BuyControl && opp.Direction == Direction.Buy)
                                  || (opp.Control == ControlState.SellControl && opp.Direction == Direction.Sell);
                if (!inOwnControl) continue;
                if (target == null || opp.ActivationTime > target.ActivationTime) target = opp;
            }
            if (target == null) return;

            newOpp.ContestingOfWeeklyOpportunityId = target.WeeklyOpportunityId;
            target.ContestingCluster = newOpp.SupportingCluster;
        }

        private void HandleRetouch(PoiLifecycleEvent ev)
        {
            var opp = FindOwningOpportunity(ev.Snapshot);
            if (opp == null) return;
            opp.RetouchCounter++;
            ReactivateFromNeutralIfDue(opp, ev.Time);
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = opp, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = $"Weekly retouch #{opp.RetouchCounter}" });
        }

        // "Valid bullish/bearish location subsequently qualifies" (doc's own
        // NEUTRAL -> BUY_CONTROL example) -- a fresh same-direction POI
        // activity under THIS opportunity's own cluster is what ends a
        // Neutral phase and restores control to this narrative's own
        // direction.
        private void ReactivateFromNeutralIfDue(WeeklyOpportunity opp, DateTime time)
        {
            if (opp.Control != ControlState.Neutral) return;
            var restored = opp.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            opp.Control = restored;
            _eventQueue.Enqueue(new WeeklyOpportunityEvent
            {
                Type = WeeklyOpportunityEventType.ControlChanged,
                Opportunity = opp,
                Time = time,
                Note = $"Control -> {restored} (valid own-direction location reached)"
            });
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
        // direction for the narrative it was EXPLICITLY linked to at
        // creation (Finding 9 fix -- no recency search here anymore).
        private void ComputeControlTransitionOnRetire(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            var owner = FindOwningOpportunity(snap);
            if (owner?.ContestingOfWeeklyOpportunityId == null) return;

            var contested = FindById(owner.ContestingOfWeeklyOpportunityId);
            if (contested == null || contested.Status != WeeklyOpportunityStatus.Active) return;

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

        // Finding 8 fix: NEUTRAL is no longer derived from the raw Weekly
        // regime flag (Pine regime and S1 Control were never confirmed
        // equivalent). Instead, directly follows the doc's own worked
        // example: whichever direction currently controls a narrative ends
        // that phase on ITS OWN next opposite-kind Weekly swing --
        // SellControl ends on the next Weekly Swing Low, BuyControl ends on
        // the next Weekly Swing High -- confirmed strictly after control was
        // established. Incremental cursor scan, not a full rescan each call.
        private void ComputeNeutralTransitions()
        {
            int total = _engine.Events.Count;
            for (int i = _lastSwingCheckIdx + 1; i < total; i++)
            {
                var swingEv = _engine.Events[i];
                DateTime evTime = swingEv.ConfirmIdx >= 0 && swingEv.ConfirmIdx < _engine.BT.Count
                    ? _engine.BT[swingEv.ConfirmIdx]
                    : default(DateTime);

                foreach (var opp in Opportunities)
                {
                    if (opp.Status != WeeklyOpportunityStatus.Active) continue;
                    if (opp.Control == ControlState.Neutral) continue;

                    int endingKind = opp.Control == ControlState.SellControl ? 1 : 0; // 1=Low ends Sell, 0=High ends Buy
                    if (swingEv.Kind != endingKind) continue;

                    DateTime controlSince = opp.ControlSwingTime ?? opp.ActivationTime;
                    if (evTime <= controlSince) continue; // must be a NEW swing after control was established

                    opp.Control = ControlState.Neutral;
                    _eventQueue.Enqueue(new WeeklyOpportunityEvent
                    {
                        Type = WeeklyOpportunityEventType.ControlChanged,
                        Opportunity = opp,
                        Time = evTime,
                        Note = $"Control -> Neutral ({(endingKind == 1 ? "Swing Low" : "Swing High")} confirmed @ {swingEv.Price}, no fresh own-direction POI yet)"
                    });
                }
            }
            _lastSwingCheckIdx = total - 1;
        }

        private WeeklyOpportunity FindOwningOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
                if (opp.WeeklyOpportunityId == snap.WeeklyOpportunityId) return opp;
            return null;
        }

        private WeeklyOpportunity FindById(string id)
        {
            foreach (var opp in Opportunities)
                if (opp.WeeklyOpportunityId == id) return opp;
            return null;
        }
    }
}
