// ICT_S1 — WeeklyOpportunityEngine. Spec: docs/s1_ea_specification.md
// sections 3, 4, 6. Repaired per the 2026-08-13 audit (see repair notes
// inline at each fix).
//
// DIRECTIONAL CONTROL — ARCHITECTURE REBUILT (strategy owner clarification,
// follow-up round, 2026-08-13, Parts 17-37): earlier rounds modeled Control
// as narrative-scoped per WeeklyOpportunity ("audit Critical 3 / Findings
// 8,9" -- see git history), on the reading that Section 10/11 concurrency
// required each Weekly opportunity to carry its own independent Control.
// The strategy owner corrected this directly: several bullish Weekly POIs
// that are simply sequential locations inside the same current uptrend do
// NOT need independent parallel BUY_CONTROL universes (Part 21) -- that was
// itself an over-fragmented reading, proven by the actual failure mode
// (a late-activating same-direction Weekly opportunity blindly defaulting
// to BuyControl even while an in-progress counter-reaction had already
// moved the REAL current phase toward SellControl/Neutral, since each
// opportunity computed its own Control independently of the others).
//
// The corrected model: DirectionalPhase (Models.cs) is ONE object per run,
// not one per WeeklyOpportunity. POI validity/lineage (WeeklyOpportunity)
// and directional trade permission (DirectionalPhase) are separate
// concepts (Part 21-23). Section 10/11 concurrency is preserved by this
// split, not by giving Control multiple simultaneous instances:
//   - "Multiple independent WeeklyOpportunities coexist freely, including
//     simultaneous opposite directions" -- WeeklyOpportunity objects are
//     fully independent of Phase.State; a bearish WeeklyOpportunity's own
//     POIs stay tracked/valid regardless of what the current phase is, and
//     it becomes eligible to authorize a NEW H4Setup the moment the phase
//     (singular) reaches SellControl -- exactly the confirmed IVI->IFVG
//     worked example (Part 18), generalized across directions.
//   - "Simultaneous opposite-direction positions allowed" -- an existing
//     open position from BEFORE the phase flipped keeps running to its own
//     SL/3R TP (Part 41); the CURRENT phase only gates NEW entries. This is
//     literally how a BUY position and a SELL position end up open at the
//     same time under a single evolving phase, with no need for two
//     simultaneous "in control" phase objects.
// If a genuine conflict with Section 10 concurrency had been found here,
// the mandate was to STOP and ask (Part 30/53) rather than pick an
// architecture alone -- none was found: every previously-confirmed
// concurrency guarantee is satisfied by the POI-validity/position-lifecycle
// split above, without requiring more than one simultaneous phase.

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum WeeklyOpportunityEventType
    {
        Activated,
        Retouched,
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

    // Separate event stream for DirectionalPhase transitions -- these are
    // NOT about any one WeeklyOpportunity (Opportunity may be null even
    // when TriggeringPoi isn't, e.g. a Neutral transition has a source
    // swing but no single "owning" POI/opportunity to attach the event to).
    public class DirectionalPhaseEvent
    {
        public ControlState NewState;
        public ControlState? OldState;
        public S1PoiSnapshot SourcePoi;
        public DateTime Time;
        public string Reason;
    }

    public class WeeklyOpportunityEngine
    {
        private readonly PoiMarketEngine _engine;
        private readonly PoiLifecycleTracker _tracker;

        public readonly List<WeeklyOpportunity> Opportunities = new List<WeeklyOpportunity>();
        public readonly DirectionalPhase Phase = new DirectionalPhase();

        private readonly Queue<WeeklyOpportunityEvent> _eventQueue = new Queue<WeeklyOpportunityEvent>();
        private readonly Queue<DirectionalPhaseEvent> _phaseEventQueue = new Queue<DirectionalPhaseEvent>();

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

        public List<DirectionalPhaseEvent> DrainPhaseEvents()
        {
            var list = new List<DirectionalPhaseEvent>(_phaseEventQueue.Count);
            while (_phaseEventQueue.Count > 0) list.Add(_phaseEventQueue.Dequeue());
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
                        ComputeGlobalControlTransitionOnRetire(ev);
                        break;
                }
            }
            ComputeGlobalNeutralTransition();
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
                ReactivateGlobalPhaseIfDue(snap, ev.Time);
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
                SupportingCluster = cluster
            };
            snap.WeeklyOpportunityId = opp.WeeklyOpportunityId;
            snap.PoiClusterId = cluster.PoiClusterId;
            Opportunities.Add(opp);

            // Bootstrap ONLY: the very first Weekly opportunity ever
            // activated establishes the initial phase (there is nothing
            // else for the phase to have been derived from yet). Every
            // SUBSEQUENT same-direction activation does NOT reset/re-claim
            // the phase merely by activating -- this is exactly the bug
            // being fixed (Part 21): a new bullish Weekly POI activating
            // mid-SELL-phase must NOT silently flip trade permission back
            // to BUY. It just becomes a tracked, independently-valid
            // narrative that's eligible to authorize a new H4Setup the
            // moment the (unique, shared) phase reaches its own direction.
            if (Phase.State == null)
                SetPhase(snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl,
                          null, snap, ev.Time, $"Bootstrap: first-ever Weekly opportunity activation ({snap.TypeAtActivation} {snap.S1PoiId})");

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

        private void HandleRetouch(PoiLifecycleEvent ev)
        {
            var opp = FindOwningOpportunity(ev.Snapshot);
            if (opp == null) return;
            opp.RetouchCounter++;
            ReactivateGlobalPhaseIfDue(ev.Snapshot, ev.Time);
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = opp, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = $"Weekly retouch #{opp.RetouchCounter}" });
        }

        // "Valid bullish/bearish location subsequently qualifies" (doc's own
        // NEUTRAL -> BUY_CONTROL example) -- a fresh In-Favor/Aggressive-
        // In-Favor POI reached WHILE Neutral is what ends the phase and
        // establishes control in THAT POI's own direction (either
        // direction can reactivate from Neutral -- the confirmed worked
        // example only shows the opposite-of-pre-Neutral direction
        // reactivating, but nothing restricts it to that case, and the
        // symmetric reading matches "new SELL entries = OFF and new BUY
        // entries = OFF" being genuinely direction-agnostic while Neutral).
        //
        // Round 2 fix (audit section 23): NOT "any retouch". The doc's own
        // example is specifically "a valid bullish/bearish LOCATION" --
        // this is read as the In-Favor/Aggressive-In-Favor POI families
        // (OriginBucket 0/4, i.e. the "I..."/"AI..." types), which are the
        // confirmed "in this narrative's favor" location types elsewhere in
        // the spec (same family H4SetupEngine.IsInFavorType tests for RouteA
        // vs RouteB classification). An Old or plain-Aggressive (A.../O...)
        // POI impact or retouch does NOT qualify.
        private static bool IsInFavorOrigin(int originBucket) => originBucket == 0 || originBucket == 4;

        private void ReactivateGlobalPhaseIfDue(S1PoiSnapshot triggeringSnap, DateTime time)
        {
            if (Phase.State != ControlState.Neutral) return;
            if (!IsInFavorOrigin(triggeringSnap.OriginBucket)) return;

            var restored = triggeringSnap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            SetPhase(restored, ControlState.Neutral, triggeringSnap, time,
                      $"Valid own-direction In-Favor/Aggressive-In-Favor location reached: {triggeringSnap.TypeAtActivation} {triggeringSnap.S1PoiId}");
        }

        // PARENT TERMINATION PROPAGATION (Part 19 audit, verified not
        // guessed): this Weekly opportunity's termination is driven purely
        // by its OWN cluster reaching all-terminal -- spec section 6 is
        // explicit ("no other independent trigger terminates it -- not
        // time, not a trade's W/L, not Pine SPENT"). It intentionally does
        // NOT touch opp.H4Setups here. This is the confirmed symmetric
        // counterpart of spec section 7's H4Setup termination rule ("do
        // not touch the parent WeeklyOpportunity... it may spawn a new
        // H4Setup later") -- the two lifecycles are independently driven by
        // their own layer's cluster/swing state, deliberately allowed to
        // diverge (a Weekly's own zone-cluster can go fully terminal while
        // a child H4Setup/M5Attempt it already spawned keeps running under
        // its own protected-swing/POI-terminal rules). No existing pending
        // order or open position is force-closed by this. It also does NOT
        // touch DirectionalPhase -- one POI-lineage object going terminal
        // says nothing about the current market-wide directional phase.
        //
        // What DOES change once Status flips to Terminated: no NEW child
        // activity can start under this narrative going forward --
        // H4SetupEngine.FindArmingWeeklyOpportunities filters to
        // Status == Active only, so a Terminated opportunity can never again
        // be returned as a qualifying candidate for a fresh H4Setup. This is
        // the "no new child activity may continue from a dead parent"
        // guarantee (Part 19) -- already enforced structurally, not by a
        // special-case check here.
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
        // confirmed) -- per spec section 3, this is the event that flips
        // the CURRENT global phase to the counter-POI's own direction.
        // Global model (Part 25): no "contesting" linkage bookkeeping is
        // needed anymore -- ANY Old/Aggressive-family POI (NOT In-Favor/AIF
        // -- those are continuation-type, not counter-type) whose OWN
        // direction is opposite the CURRENT phase, retiring, is exactly
        // "the market encountered a counter-direction location and
        // respected it" (Part 25's worked example), regardless of which
        // WeeklyOpportunity object it happens to be filed under.
        private void ComputeGlobalControlTransitionOnRetire(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            if (Phase.State == null) return; // no phase established yet -- nothing to contest
            if (IsInFavorOrigin(snap.OriginBucket)) return; // continuation-type POIs don't "contest" the phase

            var newControl = snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            bool isOpposite = (Phase.State == ControlState.BuyControl && snap.Direction == Direction.Sell)
                            || (Phase.State == ControlState.SellControl && snap.Direction == Direction.Buy);
            if (!isOpposite) return; // same-direction Old/Aggressive retirement, or already Neutral -- not a contest of the current phase

            SetPhase(newControl, Phase.State, snap, ev.Time,
                      $"Counter-POI respected + reaction swing confirmed: {snap.TypeAtActivation} {snap.S1PoiId}");
        }

        // Finding 8 fix: NEUTRAL is no longer derived from the raw Weekly
        // regime flag (Pine regime and S1 Control were never confirmed
        // equivalent). Instead, directly follows the doc's own worked
        // example: the CURRENT global phase ends on ITS OWN next opposite-
        // kind Weekly swing -- SellControl ends on the next Weekly Swing
        // Low, BuyControl ends on the next Weekly Swing High -- confirmed
        // strictly after the phase was established. Incremental cursor
        // scan, not a full rescan each call. Global model: ONE phase to
        // check, not one per opportunity.
        private void ComputeGlobalNeutralTransition()
        {
            if (Phase.State == null || Phase.State == ControlState.Neutral) return;

            int total = _engine.Events.Count;
            for (int i = _lastSwingCheckIdx + 1; i < total; i++)
            {
                if (Phase.State == null || Phase.State == ControlState.Neutral) break;

                var swingEv = _engine.Events[i];
                DateTime evTime = swingEv.ConfirmIdx >= 0 && swingEv.ConfirmIdx < _engine.BT.Count
                    ? _engine.BT[swingEv.ConfirmIdx]
                    : default(DateTime);

                int endingKind = Phase.State == ControlState.SellControl ? 1 : 0; // 1=Low ends Sell, 0=High ends Buy
                if (swingEv.Kind != endingKind) continue;

                DateTime controlSince = Phase.SourceSwingTime ?? Phase.EstablishedTime ?? default(DateTime);
                if (evTime <= controlSince) continue; // must be a NEW swing after this phase was established

                SetPhase(ControlState.Neutral, Phase.State, null, evTime,
                          $"{(endingKind == 1 ? "Swing Low" : "Swing High")} confirmed @ {swingEv.Price}, no fresh own-direction POI yet");
            }
            _lastSwingCheckIdx = total - 1;
        }

        private void SetPhase(ControlState newState, ControlState? oldState, S1PoiSnapshot sourceSnap, DateTime time, string reason)
        {
            Phase.State = newState;
            Phase.EstablishedTime = time;
            Phase.SourcePoiId = sourceSnap?.S1PoiId;
            Phase.SourceSwingType = sourceSnap?.RelevantReactionSwingType;
            Phase.SourceSwingPrice = sourceSnap?.RelevantReactionSwingPrice;
            Phase.SourceSwingTime = sourceSnap?.RelevantReactionSwingConfirmationTime;
            Phase.TransitionReason = reason;
            _phaseEventQueue.Enqueue(new DirectionalPhaseEvent { NewState = newState, OldState = oldState, SourcePoi = sourceSnap, Time = time, Reason = reason });
        }

        private WeeklyOpportunity FindOwningOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
                if (opp.WeeklyOpportunityId == snap.WeeklyOpportunityId) return opp;
            return null;
        }
    }
}
