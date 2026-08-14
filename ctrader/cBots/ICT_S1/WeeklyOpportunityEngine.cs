// ICT_S1 — WeeklyOpportunityEngine. Spec: docs/s1_ea_specification.md
// sections 3, 4, 6. Repaired per the 2026-08-13 audit (see repair notes
// inline at each fix).
//
// DIRECTIONAL CONTROL — ARCHITECTURE HISTORY:
//   Round A: Control lived per-WeeklyOpportunity ("audit Critical 3 /
//   Findings 8,9" -- see git history). Documented failure mode: a late-
//   activating same-direction Weekly opportunity blindly defaulted to
//   BuyControl even while an in-progress counter-reaction elsewhere had
//   already moved the real narrative toward SellControl/Neutral, because
//   each opportunity computed its own Control independently.
//   Round B (forensic-audit mandate, Parts 17-37): collapsed to ONE
//   DirectionalPhase per run. Fixed Round A's inconsistency, but could not
//   represent two genuinely independent fresh opposite-direction narratives
//   existing at once.
//   Round C (concurrency mandate, 2026-08-13, OWNER ANSWER A -- "both fresh
//   streams allowed"): Control is scoped per DirectionalPhaseContext
//   (Models.cs) -- neither Round A's full fragmentation nor Round B's
//   single instance. See DirectionalPhaseContext's own doc comment in
//   Models.cs for the full context-membership rule (Weekly MSS-scoped,
//   ENGINEERING-PROPOSED per the owner's explicit "propose the rule"
//   answer) and why it avoids resurrecting Round A's failure mode: a
//   counter-POI flips the Control of whichever context it is ALREADY a
//   member of (assigned at its own activation), never a different one and
//   never fanned to all live contexts.
//
// POI VALIDITY (WeeklyOpportunity) and DIRECTIONAL TRADE PERMISSION
// (DirectionalPhaseContext) remain separate concepts throughout every
// round above -- only how many simultaneous Control instances exist, and
// which POIs feed which one, has changed.

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

    // Separate event stream for DirectionalPhaseContext transitions -- these
    // are NOT about any one WeeklyOpportunity (Opportunity may be null even
    // when TriggeringPoi isn't, e.g. a Neutral transition has a source
    // swing but no single "owning" POI/opportunity to attach the event to).
    // ContextId (concurrency mandate): which context this transition
    // belongs to -- required now that more than one can exist/transition.
    public class DirectionalPhaseEvent
    {
        public string ContextId;
        // Denormalized from the context's own OriginMss* fields at the
        // moment this event is emitted (Models.cs DirectionalPhaseContext
        // is the source of truth) -- carried here so JournalManager, which
        // never holds a reference to WeeklyOpportunityEngine.Contexts, can
        // write them onto the PhaseHistory row without a lookup.
        public bool? ContextOriginMssToUp;
        public double? ContextOriginMssPrice;
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

        // Concurrency mandate (Owner Answer A): replaces the single
        // `Phase` instance. Every context ever created stays in this list
        // for its own lifetime -- an older context superseded for NEW
        // membership purposes keeps evolving here using only its existing
        // members (see Models.cs DirectionalPhaseContext doc comment).
        public readonly List<DirectionalPhaseContext> Contexts = new List<DirectionalPhaseContext>();

        // The context newly-activating WeeklyOpportunities join. Null only
        // before the very first-ever Weekly opportunity activation.
        private DirectionalPhaseContext _currentContext;

        public DirectionalPhaseContext GetContext(string contextId)
        {
            if (contextId == null) return null;
            foreach (var c in Contexts)
                if (c.ContextId == contextId) return c;
            return null;
        }

        private readonly Queue<WeeklyOpportunityEvent> _eventQueue = new Queue<WeeklyOpportunityEvent>();
        private readonly Queue<DirectionalPhaseEvent> _phaseEventQueue = new Queue<DirectionalPhaseEvent>();

        // Cursor into _engine.Events for incremental Neutral-detection scans
        // (Finding 8 fix) -- avoids rescanning all history every cycle.
        private int _lastSwingCheckIdx = -1;

        // Cursor into _engine.Msses for incremental context-boundary scans
        // (concurrency mandate) -- same incremental-cursor technique.
        private int _lastMssCheckIdx = -1;

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
            // Checked BEFORE this cycle's POI events (same ordering pattern
            // as H4SetupEngine.CheckSupersession) so a context boundary that
            // opens on this very bar already applies to a same-bar fresh
            // WeeklyOpportunity activation below.
            CheckMssContextBoundary();

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
                        ComputeContextControlTransitionOnRetire(ev);
                        break;
                }
            }
            ComputeContextNeutralTransitions();
        }

        // Concurrency mandate: a DirectionalPhaseContext boundary opens on
        // every Weekly MSS (PoiMarketEngine.Msses -- an already-computed,
        // Pine-native structural-shift fact) whose direction is OPPOSITE
        // the currently-governing context's own origin direction. A same-
        // direction MSS re-confirmation does not fragment the context
        // (still the same movement, Part 27). See Models.cs
        // DirectionalPhaseContext for the full rationale.
        private void CheckMssContextBoundary()
        {
            int total = _engine.Msses.Count;
            for (int i = _lastMssCheckIdx + 1; i < total; i++)
            {
                var mss = _engine.Msses[i];
                if (_currentContext != null && _currentContext.OriginMssToUp == mss.ToUp) continue;

                DateTime t = mss.AtIdx >= 0 && mss.AtIdx < _engine.BT.Count ? _engine.BT[mss.AtIdx] : default(DateTime);
                var ctx = new DirectionalPhaseContext
                {
                    ContextId = IdGenerator.NextDirectionalContextId(),
                    OriginMssAtIdx = mss.AtIdx,
                    OriginMssPrice = mss.Price,
                    OriginMssToUp = mss.ToUp,
                    OriginMssTime = t,
                };
                Contexts.Add(ctx);
                _currentContext = ctx;
            }
            _lastMssCheckIdx = total - 1;
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
                ReactivateContextIfDue(joinable, snap, ev.Time);
                _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = joinable, TriggeringPoi = snap, Time = ev.Time, Note = $"Joined existing cluster ({snap.TypeAtActivation})" });
                return;
            }

            // Bootstrap ONLY: before the very first-ever MSS has fired,
            // there is no context yet to join -- mirrors the prior round's
            // "very first Weekly opportunity ever activated establishes the
            // initial phase" rule, just as the seed context instead of a
            // seed phase value.
            if (_currentContext == null)
            {
                _currentContext = new DirectionalPhaseContext { ContextId = IdGenerator.NextDirectionalContextId(), BootstrapOrigin = true };
                Contexts.Add(_currentContext);
            }

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);

            var opp = new WeeklyOpportunity
            {
                WeeklyOpportunityId = IdGenerator.NextWeeklyOpportunityId(),
                Direction = snap.Direction,
                ActivationTime = ev.Time,
                SupportingCluster = cluster,
                DirectionalContextId = _currentContext.ContextId
            };
            snap.WeeklyOpportunityId = opp.WeeklyOpportunityId;
            snap.PoiClusterId = cluster.PoiClusterId;
            Opportunities.Add(opp);

            // Bootstrap ONLY: the very first member of THIS context
            // establishes ITS OWN initial Control (there is nothing else
            // for this context's Control to have been derived from yet).
            // Every SUBSEQUENT same-context activation does NOT reset/
            // re-claim Control merely by activating -- that is exactly the
            // Round-A failure mode this model must not resurrect. This is
            // scoped to `_currentContext` only, never to any OTHER context
            // in `Contexts` -- an older, still-live context's Control is
            // completely unaffected by a brand-new context's own bootstrap.
            if (_currentContext.State == null)
                SetContextPhase(_currentContext, snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl,
                          null, snap, ev.Time, $"Bootstrap: first activation in this context ({snap.TypeAtActivation} {snap.S1PoiId})");

            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Activated, Opportunity = opp, TriggeringPoi = snap, Time = ev.Time, Note = $"Activated by {snap.TypeAtActivation}" });
        }

        // Finding 4 fix: Weekly clustering requires GENUINE price overlap
        // with at least one existing member of an active same-direction
        // opportunity's cluster. The earlier "any active same-direction
        // opportunity qualifies" rule was an unconfirmed extension of the
        // H4-specific non-overlap rule -- that rule was never confirmed at
        // Weekly level, so the safe default (independent opportunities
        // supported explicitly by section 10) applies instead. Unaffected
        // by the concurrency mandate -- POI-cluster identity (Finding 4)
        // and Control-context identity (this round) are separate axes; see
        // Models.cs DirectionalPhaseContext doc comment.
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
            ReactivateContextIfDue(opp, ev.Snapshot, ev.Time);
            _eventQueue.Enqueue(new WeeklyOpportunityEvent { Type = WeeklyOpportunityEventType.Retouched, Opportunity = opp, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = $"Weekly retouch #{opp.RetouchCounter}" });
        }

        // "Valid bullish/bearish location subsequently qualifies" (doc's own
        // NEUTRAL -> BUY_CONTROL example) -- a fresh In-Favor/Aggressive-
        // In-Favor POI reached WHILE this POI's OWN context is Neutral is
        // what ends that context's Neutral state and establishes Control in
        // THAT POI's own direction (either direction can reactivate from
        // Neutral -- the confirmed worked example only shows the opposite-
        // of-pre-Neutral direction reactivating, but nothing restricts it to
        // that case, and the symmetric reading matches "new SELL entries =
        // OFF and new BUY entries = OFF" being genuinely direction-agnostic
        // while Neutral).
        //
        // Round 2 fix (audit section 23): NOT "any retouch". The doc's own
        // example is specifically "a valid bullish/bearish LOCATION" -- read
        // as the In-Favor/Aggressive-In-Favor POI families, the confirmed
        // "in this narrative's favor" location types.
        //
        // PROVEN BUG FIX (forensic audit, follow-up round, Parts 31-34):
        // this used to test `OriginBucket == 0 || OriginBucket == 4`.
        // EventLog evidence showed OFVG/OOB (Old-family types) reactivating
        // Control -- traced to the root cause: PoiMarketEngine's structural-
        // stranding demotion (`State = 2`, RunEngine STEP 3) updates a raw
        // zone's State but never its OrigState/Origin, so a zone that
        // started as an IFOB/AIFOB (etc.) candidate and got stranded before
        // ever impacting freezes with TypeAtActivation correctly reading
        // OOB/OFVG/etc. while OriginBucket kept the STALE original bucket.
        // Two fixes applied together (belt-and-suspenders, Part 74 "fix the
        // model, not the symptom"): (1) PoiLifecycleTracker.Freeze* now
        // stamps OriginBucket from the SAME PreSpentState value TypeAtActivation
        // itself is derived from, eliminating the staleness at the root; (2)
        // this predicate ALSO no longer trusts OriginBucket at all -- it
        // enumerates the confirmed continuation taxonomy directly off the
        // frozen PoiTypeLabel (Part 32's explicit instruction: "do not infer
        // semantic POI class from OriginBucket alone"). Deliberately does
        // NOT reuse H4SetupEngine.IsInFavorType -- that predicate excludes
        // AIFOB/AIRB on purpose (H4 Route classification treats them as
        // Aggressive-route), but Part 32 explicitly requires THIS predicate
        // to include them as valid continuation types for Neutral
        // reactivation. Two different semantic questions, two predicates.
        private static bool IsInFavorOrAggressiveInFavorType(PoiTypeLabel type) =>
            type == PoiTypeLabel.IFOB || type == PoiTypeLabel.IFVG || type == PoiTypeLabel.IRB || type == PoiTypeLabel.IVI ||
            type == PoiTypeLabel.AIFOB || type == PoiTypeLabel.AIRB;

        // Concurrency mandate: scoped to `owningOpp`'s OWN context only --
        // never any other live context. This is what keeps Neutral
        // reactivation from leaking across genuinely independent narratives
        // (Part 29 of the concurrency mandate).
        private void ReactivateContextIfDue(WeeklyOpportunity owningOpp, S1PoiSnapshot triggeringSnap, DateTime time)
        {
            var ctx = GetContext(owningOpp?.DirectionalContextId);
            if (ctx == null) return;
            if (ctx.State != ControlState.Neutral) return;
            if (!IsInFavorOrAggressiveInFavorType(triggeringSnap.TypeAtActivation)) return;

            var restored = triggeringSnap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            SetContextPhase(ctx, restored, ControlState.Neutral, triggeringSnap, time,
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
        // touch its DirectionalPhaseContext -- one POI-lineage object going
        // terminal says nothing about that context's current Control (Part
        // 31 of the concurrency mandate: WeeklyOpportunity termination
        // remains POI-based, independent of Control).
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
        // the CURRENT Control of the context THIS POI ITSELF belongs to
        // (its own WeeklyOpportunity's DirectionalContextId, assigned at
        // its own activation in HandleNewImpact) to the counter-POI's own
        // direction. Concurrency mandate: no fan-out to other contexts --
        // membership alone answers "which narrative is this a counter-
        // reaction WITHIN" (Part 26/43 of the concurrency mandate), because
        // the counter-POI was already filed into whichever context was
        // current at ITS OWN activation time, exactly like any other POI.
        private void ComputeContextControlTransitionOnRetire(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;
            var opp = FindOwningOpportunity(snap);
            if (opp == null) return;
            var ctx = GetContext(opp.DirectionalContextId);
            if (ctx == null || ctx.State == null) return; // no Control established yet in this context -- nothing to contest
            if (IsInFavorOrAggressiveInFavorType(snap.TypeAtActivation)) return; // continuation-type POIs don't "contest" Control -- Part 31-34 fix, see ReactivateContextIfDue

            var newControl = snap.Direction == Direction.Buy ? ControlState.BuyControl : ControlState.SellControl;
            bool isOpposite = (ctx.State == ControlState.BuyControl && snap.Direction == Direction.Sell)
                            || (ctx.State == ControlState.SellControl && snap.Direction == Direction.Buy);
            if (!isOpposite) return; // same-direction Old/Aggressive retirement, or already Neutral -- not a contest of this context's Control

            SetContextPhase(ctx, newControl, ctx.State, snap, ev.Time,
                      $"Counter-POI respected + reaction swing confirmed: {snap.TypeAtActivation} {snap.S1PoiId}");
        }

        // Finding 8 fix: NEUTRAL is not derived from the raw Weekly regime
        // flag (Pine regime and S1 Control were never confirmed
        // equivalent). Instead, directly follows the doc's own worked
        // example: a context's Control ends on ITS OWN next opposite-kind
        // Weekly swing -- SellControl ends on the next Weekly Swing Low,
        // BuyControl ends on the next Weekly Swing High -- confirmed
        // strictly after THAT context's own Control was established.
        // Concurrency mandate: now iterates every live (non-Neutral)
        // context independently against the SAME shared swing-event scan
        // (one incremental cursor over _engine.Events, Pine-mechanical
        // order preserved, Task #35) -- a swing can end more than one
        // context's Neutral window on the same bar without any cross-
        // context interaction; each context's own condition is evaluated
        // independently, order among contexts in the inner loop cannot
        // change any individual context's outcome.
        private void ComputeContextNeutralTransitions()
        {
            int total = _engine.Events.Count;
            for (int i = _lastSwingCheckIdx + 1; i < total; i++)
            {
                var swingEv = _engine.Events[i];
                DateTime evTime = swingEv.ConfirmIdx >= 0 && swingEv.ConfirmIdx < _engine.BT.Count
                    ? _engine.BT[swingEv.ConfirmIdx]
                    : default(DateTime);

                foreach (var ctx in Contexts)
                {
                    if (ctx.State == null || ctx.State == ControlState.Neutral) continue;

                    int endingKind = ctx.State == ControlState.SellControl ? 1 : 0; // 1=Low ends Sell, 0=High ends Buy
                    if (swingEv.Kind != endingKind) continue;

                    DateTime controlSince = ctx.SourceSwingTime ?? ctx.EstablishedTime ?? default(DateTime);
                    if (evTime <= controlSince) continue; // must be a NEW swing after THIS context's Control was established

                    SetContextPhase(ctx, ControlState.Neutral, ctx.State, null, evTime,
                              $"{(endingKind == 1 ? "Swing Low" : "Swing High")} confirmed @ {swingEv.Price}, no fresh own-direction POI yet");
                }
            }
            _lastSwingCheckIdx = total - 1;
        }

        private void SetContextPhase(DirectionalPhaseContext ctx, ControlState newState, ControlState? oldState, S1PoiSnapshot sourceSnap, DateTime time, string reason)
        {
            ctx.State = newState;
            ctx.EstablishedTime = time;
            ctx.SourcePoiId = sourceSnap?.S1PoiId;
            ctx.SourcePoiType = sourceSnap?.TypeAtActivation;
            ctx.SourcePoiDirection = sourceSnap?.Direction;
            ctx.SourcePoiFamily = sourceSnap?.Family;
            ctx.SourcePoiOriginBucket = sourceSnap?.OriginBucket;
            ctx.SourcePoiLifecycleState = sourceSnap?.LifecycleState;
            ctx.SourceSwingType = sourceSnap?.RelevantReactionSwingType;
            ctx.SourceSwingPrice = sourceSnap?.RelevantReactionSwingPrice;
            ctx.SourceSwingTime = sourceSnap?.RelevantReactionSwingConfirmationTime;
            ctx.TransitionReason = reason;
            _phaseEventQueue.Enqueue(new DirectionalPhaseEvent
            {
                ContextId = ctx.ContextId,
                ContextOriginMssToUp = ctx.OriginMssToUp,
                ContextOriginMssPrice = ctx.OriginMssPrice,
                NewState = newState,
                OldState = oldState,
                SourcePoi = sourceSnap,
                Time = time,
                Reason = reason
            });
        }

        private WeeklyOpportunity FindOwningOpportunity(S1PoiSnapshot snap)
        {
            foreach (var opp in Opportunities)
                if (opp.WeeklyOpportunityId == snap.WeeklyOpportunityId) return opp;
            return null;
        }
    }
}
