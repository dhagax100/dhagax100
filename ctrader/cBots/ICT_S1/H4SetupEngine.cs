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
// ROUND 2 FIX (audit sections 18-19) -- the "most recently activated"
// tie-break for MULTIPLE simultaneously-qualifying same-direction Weekly
// opportunities was REMOVED.
//
// FOLLOW-UP STRATEGY CLARIFICATION (2026-08-13, final audit Parts 10-13):
// the Round 2 replacement -- "authorize/join every qualifying narrative
// independently" -- turned out to be ITSELF an unconfirmed decision, and
// backtest evidence proved it: ~42 cases of one physical H4 POI impact
// being cloned across multiple WeeklyOpportunityID/H4SetupID pairs, i.e.
// duplicate trade streams from a single event. Asked the strategy owner
// directly; RESOLVED: "Multiple independent valid Weekly opportunities may
// simultaneously support the same physical H4 reaction, but they must NOT
// create duplicate H4/M5 trade streams. The H4 reaction is the execution-
// level object: one physical H4 reaction creates ONE H4Setup and ONE M5
// execution stream, regardless of how many valid Weekly opportunities
// support/authorize it. Preserve all qualifying WeeklyOpportunityIDs as
// supporting lineage for journaling/audit, but deduplicate execution at
// the H4 reaction level." Implemented: dedup key is the protected-swing
// identity ALONE (see FindLiveSetupForSwing); every qualifying Weekly is
// recorded in H4Setup.SupportingWeeklyOpportunityIds, not collapsed to a
// single "owner" and not spawning duplicate setups either. The SAME
// principle resolves WeeklyOpportunityEngine's analogous contesting-
// narrative fan-out without any separate code change: Control changes
// don't themselves create trades, and execution-level dedup now happens
// here regardless of how many Weeklies are simultaneously eligible.
//
// FINDING 10 FIX — protected-swing reconstruction no longer falls back to
// the POI's own Zb/Zt when no real swing reference is found. A wrong
// protected swing can silently create false re-entries, so this now fails
// safely: reject the setup, journal why, do not arm anything.
//
// FINDING 11 FIX — every created H4Setup is now added to
// WeeklyOpportunity.H4Setups (was never populated before).
//
// ROUND 2 FIX (audit section 25) — ReconstructProtectedSwing() is REMOVED.
// It used to infer the protected swing purely from direction ("BUY always
// protected by the most recent swing LOW before TriggerK, SELL always by
// the most recent swing HIGH") -- itself exactly the kind of after-the-fact
// reconstruction the Round 2 audit requires eliminated, and provably wrong
// for aggressive-family POIs (e.g. a bullish AOB is armed off the broken
// swing HIGH it pulled back from, not a swing low). The protected swing is
// now read directly from S1PoiSnapshot.SourceSwingType/Price/ConfirmationTime
// -- the exact structural swing PoiMarketEngine stamped on the raw zone at
// the moment it was created (see PoiMarketEngine's AddOB/AddFvg/AddRb/AddVi
// sourceSwingIdx parameter and PoiLifecycleTracker.PopulateSourceSwing).
//
// H4 REACTION GROUPING (audit sections 7-9, 43 -- strategy owner
// clarification, 2026-08-13): "same H4 reaction" was previously conflated
// with "same still-live setup under the same Weekly parent", with no
// boundary condition for when a NEW reaction should begin. Resolved:
// reaction identity is the EXACT protected H4 swing a POI is anchored to
// (not time, not geometry) -- see HandleNewImpact/FindLiveSetupForSwing.
// More than one H4Setup can now be simultaneously live under one Weekly
// opportunity, one per distinct protected swing (and, per the follow-up
// multiplicity clarification below, one H4Setup can now also be supported
// by more than one Weekly opportunity at once).

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum H4SetupEventType
    {
        Created,
        Impacted,
        Retouched,
        Terminated,
        // Strategy clarification (follow-up round), Parts 14-16, 39: a
        // SUCCESS outcome -- distinct from Terminated (failure) -- the
        // market structurally advanced past this reaction's own protected
        // swing.
        Superseded
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
        private int _h4SwingCheckIdx = -1; // incremental cursor for CheckSupersession

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
            // Checked BEFORE processing this cycle's POI events, so a
            // supersession detected on this very bar already blocks a
            // same-bar HandleNewImpact from joining the just-superseded
            // reaction (FindLiveSetupForSwing already excludes non-Impacted
            // setups, but ordering here keeps the sequence causally clean).
            CheckSupersession();

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

        // Strategy clarification (follow-up round), Parts 14-16, 39, 44: a
        // live H4 reaction is SUPERSEDED (a SUCCESS outcome, not a failure)
        // the moment a NEW H4-timeframe swing of its OWN protected-swing
        // kind confirms BEYOND (better than) its own protected level -- the
        // market has structurally advanced past this reaction's own
        // reference, and new H4 POIs now belong to that new structure
        // (they'll naturally create/join a DIFFERENT H4Setup via
        // FindLiveSetupForSwing's swing-identity keying -- this method only
        // needs to stop R1 from continuing to accept fresh M5 attempts in
        // parallel with R2). Incremental cursor scan over the H4 engine's
        // own raw swing Events (same technique as
        // WeeklyOpportunityEngine.ComputeGlobalNeutralTransition) -- a pure
        // structural fact, independent of whether any new H4 POI has
        // actually impacted yet.
        private void CheckSupersession()
        {
            var events = _h4Engine.Events;
            for (int i = _h4SwingCheckIdx + 1; i < events.Count; i++)
            {
                var ev = events[i];
                var t = ev.ConfirmIdx >= 0 && ev.ConfirmIdx < _h4Engine.BT.Count ? _h4Engine.BT[ev.ConfirmIdx] : default(DateTime);

                foreach (var setup in Setups)
                {
                    if (setup.Status != H4SetupStatus.Impacted && setup.Status != H4SetupStatus.Watching) continue;

                    bool bull = setup.Direction == Direction.Buy;
                    int wantKind = bull ? 1 : 0; // BUY protected by a Low -> superseded by a NEW higher Low; SELL protected by a High -> superseded by a NEW lower High
                    if (ev.Kind != wantKind) continue;
                    if (ev.SwingIdx == setup.ProtectedSwingIdx) continue; // same swing, not a new one
                    if (t <= setup.ProtectedSwingTime) continue; // must be genuinely newer

                    bool supersedes = bull ? ev.Price > setup.ProtectedSwingPrice : ev.Price < setup.ProtectedSwingPrice;
                    if (!supersedes) continue;

                    setup.Status = H4SetupStatus.Superseded;
                    setup.SupersededBySwingIdx = ev.SwingIdx;
                    setup.SupersededBySwingPrice = ev.Price;
                    setup.SupersededTime = t;
                    _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Superseded, Setup = setup, TriggeringPoi = null, Time = t, Note = $"New protected H4 {setup.ProtectedSwingType} @ {ev.Price} supersedes this reaction's own {setup.ProtectedSwingType} @ {setup.ProtectedSwingPrice}" });
                }
            }
            _h4SwingCheckIdx = events.Count - 1;
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

        // RESOLVED (strategy owner clarification, follow-up round, 2026-08-13
        // -- supersedes the earlier fan-to-all reading): "Multiple independent
        // valid Weekly opportunities may simultaneously support the same
        // physical H4 reaction, but they must NOT create duplicate H4/M5
        // trade streams. The H4 reaction is the execution-level object: one
        // physical H4 reaction (per the confirmed protected-swing grouping
        // rule) creates ONE H4Setup/H4Reaction and ONE M5 execution stream,
        // regardless of how many valid same-direction Weekly opportunities
        // support/authorize it. Preserve all qualifying WeeklyOpportunityIDs
        // as supporting lineage for journaling/audit, but deduplicate
        // execution at the H4 reaction level." Implemented below: dedup key
        // is the protected-swing identity ALONE (H4Setup.ProtectedSwingIdx),
        // not (Weekly, swing) -- so one physical impact anchored to one
        // protected swing produces exactly one H4Setup no matter how many
        // Weekly opportunities qualify for it. Every qualifying Weekly is
        // recorded in H4Setup.SupportingWeeklyOpportunityIds (full lineage,
        // no information lost) and gets the SAME shared setup object added
        // to its own H4Setups list.
        private void HandleNewImpact(PoiLifecycleEvent ev)
        {
            var snap = ev.Snapshot;

            var (qualifying, temporallyValid) = FindArmingWeeklyOpportunities(snap.Direction, ev.Time);
            if (qualifying.Count == 0)
            {
                bool anyTemporallyValidCandidate = temporallyValid.Count > 0;
                var code = anyTemporallyValidCandidate
                    ? RejectionCode.H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL
                    : RejectionCode.H4_POI_REJECTED_NO_WEEKLY_PARENT;
                var rejection = new RejectionEvent
                {
                    Code = code,
                    Time = ev.Time,
                    Direction = snap.Direction,
                    PoiId = snap.S1PoiId,
                    PoiType = snap.TypeAtActivation,
                    Note = $"{snap.TypeAtActivation} impact at {ev.Time:O} has no authorizing Weekly narrative",
                    SourceSwingIdx = snap.SourceSwingIdx,
                };
                if (anyTemporallyValidCandidate)
                {
                    // Part 48, concurrency-mandate update: Control is now
                    // per-context (Owner Answer A), so there is no single
                    // shared "the phase" to record -- each temporally-valid
                    // same-direction candidate can belong to a DIFFERENT
                    // context. Parallel/index-aligned lists let a SELL-
                    // suppression audit pass answer "why" (which context,
                    // in what state) for every candidate, from the journal
                    // alone.
                    rejection.TemporallyValidSameDirectionWeeklyIds = new List<string>();
                    rejection.TemporallyValidContextIds = new List<string>();
                    rejection.TemporallyValidContextStates = new List<string>();
                    foreach (var w in temporallyValid)
                    {
                        var ctx = _weeklyEngine.GetContext(w.DirectionalContextId);
                        rejection.TemporallyValidSameDirectionWeeklyIds.Add(w.WeeklyOpportunityId);
                        rejection.TemporallyValidContextIds.Add(w.DirectionalContextId);
                        rejection.TemporallyValidContextStates.Add(ctx?.State?.ToString());
                    }
                }
                _rejectionQueue.Enqueue(rejection);
                return;
            }

            // Round 2 fix (audit section 25): the protected swing is the
            // EXACT structural swing PoiMarketEngine stamped on the raw zone
            // at creation (frozen onto the snapshot by PoiLifecycleTracker),
            // not a reconstruction inferred from direction alone. Checked
            // ONCE here (not per-qualifying-Weekly) since it's a property of
            // the POI itself, and H4 reaction identity (below) is defined by
            // this exact swing regardless of which Weekly(ies) support it.
            if (snap.SourceSwingType == null || snap.SourceSwingPrice == null || snap.SourceSwingConfirmationTime == null || snap.SourceSwingIdx < 0)
            {
                // Finding 10: fail safely, no fake fallback -- do not arm.
                _rejectionQueue.Enqueue(new RejectionEvent { Code = RejectionCode.H4_POI_REJECTED_NO_PROTECTED_SWING, Time = ev.Time, Direction = snap.Direction, PoiId = snap.S1PoiId, PoiType = snap.TypeAtActivation, Note = $"No source-swing reference was stored for this {snap.TypeAtActivation} at creation -- refusing to arm with a substituted level" });
                return;
            }

            // H4 REACTION GROUPING RULE (strategy owner clarification,
            // 2026-08-13): H4 reaction identity is structural, not time-
            // based and not geometric -- anchored to the exact protected H4
            // swing, no elapsed-time/distance/"most recent" heuristic. Live-
            // setup lookup is scoped by swing identity ALONE (not by Weekly
            // -- see the class comment above) so this dedupes correctly even
            // when multiple Weeklies simultaneously qualify.
            var live = FindLiveSetupForSwing(snap.SourceSwingIdx);
            if (live != null)
            {
                AttachQualifyingWeeklies(live, qualifying);
                snap.WeeklyOpportunityId = live.WeeklyOpportunityId;
                snap.PoiClusterId = live.SupportingCluster.PoiClusterId;
                live.SupportingCluster.Members.Add(snap);
                _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = live, TriggeringPoi = snap, Time = ev.Time, Note = $"H4 POI joined live reaction -- same protected swing {snap.SourceSwingType}@{snap.SourceSwingPrice} ({snap.TypeAtActivation})" });
                return;
            }

            var route = IsInFavorType(snap.TypeAtActivation) ? H4Route.RouteA_Confirmed : H4Route.RouteB_Aggressive;

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);
            var primary = qualifying[0];
            snap.WeeklyOpportunityId = primary.WeeklyOpportunityId;
            snap.PoiClusterId = cluster.PoiClusterId;

            var setup = new H4Setup
            {
                H4SetupId = IdGenerator.NextH4SetupId(),
                WeeklyOpportunityId = primary.WeeklyOpportunityId, // primary = display convenience only, NOT an ownership decision -- full lineage is SupportingWeeklyOpportunityIds
                Direction = snap.Direction,
                Route = route,
                Status = H4SetupStatus.Impacted,
                SupportingCluster = cluster,
                ProtectedSwingType = snap.SourceSwingType.Value,
                ProtectedSwingPrice = snap.SourceSwingPrice.Value,
                ProtectedSwingTime = snap.SourceSwingConfirmationTime.Value,
                ProtectedSwingIdx = snap.SourceSwingIdx,
                CreatedTime = ev.Time,
                WeeklyRetouchNumber = primary.RetouchCounter
            };
            Setups.Add(setup);
            AttachQualifyingWeeklies(setup, qualifying); // adds ALL qualifying Weeklies (including primary) to SupportingWeeklyOpportunityIds + their own H4Setups list
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Impacted, Setup = setup, TriggeringPoi = snap, Time = ev.Time, Note = $"{route} via {snap.TypeAtActivation} -- new H4 reaction, protected swing {snap.SourceSwingType}@{snap.SourceSwingPrice}, supported by {qualifying.Count} Weekly opportunit{(qualifying.Count == 1 ? "y" : "ies")}" });
        }

        // Merges any newly-qualifying Weekly opportunities into an existing
        // (live or freshly created) H4Setup's supporting lineage -- a Weekly
        // that didn't qualify at this setup's original creation can still
        // become a legitimate supporter later (e.g. it just re-entered its
        // own control) while the SAME physical H4 reaction is still live.
        private void AttachQualifyingWeeklies(H4Setup setup, List<WeeklyOpportunity> qualifying)
        {
            foreach (var weekly in qualifying)
            {
                if (setup.SupportingWeeklyOpportunityIds.Contains(weekly.WeeklyOpportunityId)) continue;
                setup.SupportingWeeklyOpportunityIds.Add(weekly.WeeklyOpportunityId);
                weekly.H4Setups.Add(setup); // Finding 11 fix -- same shared setup object, not a copy

                // Concurrency mandate Part 38: record which context(s)
                // actually authorized this reaction, supplementing (not
                // replacing) the Weekly lineage above.
                if (weekly.DirectionalContextId != null && !setup.SupportingDirectionalContextIds.Contains(weekly.DirectionalContextId))
                    setup.SupportingDirectionalContextIds.Add(weekly.DirectionalContextId);
            }
        }

        private static bool IsInFavorType(PoiTypeLabel t) =>
            t == PoiTypeLabel.IFOB || t == PoiTypeLabel.IFVG || t == PoiTypeLabel.IRB || t == PoiTypeLabel.IVI;

        // CRITICAL 2 + CRITICAL 3: returns EVERY currently-qualifying Weekly
        // opportunity (temporally valid AND ITS OWN DirectionalPhaseContext
        // currently permits this direction) -- no tie-break, no single
        // "chosen" winner (Round 2 fix, see HandleNewImpact). The bool
        // tells the caller whether ANY temporally-valid same-direction
        // candidate existed at all (for accurate rejection-code selection:
        // NO_WEEKLY_PARENT vs NOT_IN_CONTROL).
        //
        // Concurrency mandate (2026-08-13, Owner Answer A): each opportunity
        // is checked against its OWN context (WeeklyOpportunity.
        // DirectionalContextId), not one shared global phase -- this is
        // exactly what lets a genuinely independent fresh BUY narrative and
        // a genuinely independent fresh SELL narrative both qualify at the
        // same historical moment, each governed by its own context's own
        // Control evolution.
        private (List<WeeklyOpportunity> qualifying, List<WeeklyOpportunity> temporallyValid) FindArmingWeeklyOpportunities(Direction dir, DateTime h4EventTime)
        {
            var qualifying = new List<WeeklyOpportunity>();
            var temporallyValid = new List<WeeklyOpportunity>();

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

                temporallyValid.Add(opp); // Part 48 forensic journal: every temporally-valid same-direction candidate, not just a bool

                // POI validity (this opportunity being Active) and
                // directional permission (this opportunity's OWN context
                // currently matching its own direction) are separate gates,
                // both required.
                var ctx = _weeklyEngine.GetContext(opp.DirectionalContextId);
                var contextState = ctx?.State;
                bool contextPermits = (contextState == ControlState.BuyControl && opp.Direction == Direction.Buy)
                                    || (contextState == ControlState.SellControl && opp.Direction == Direction.Sell);
                if (!contextPermits) continue; // Critical 3 gate: this opportunity's own context does not currently permit this direction

                qualifying.Add(opp);
            }
            return (qualifying, temporallyValid);
        }

        // RESOLVED (audit sections 7-9, 43 -- strategy owner clarification
        // 2026-08-13, see HandleNewImpact's H4 REACTION GROUPING RULE
        // comment): "same reaction" = anchored to the same exact protected
        // H4 swing, not merely "same Weekly parent, still live". A live
        // setup only qualifies as the same reaction if its ProtectedSwing
        // identity matches exactly.
        //
        // Follow-up strategy clarification (2026-08-13): dedup is scoped by
        // swing identity ALONE, NOT also by WeeklyOpportunityId -- one
        // physical H4 reaction is ONE execution stream regardless of how
        // many Weekly opportunities support it (see HandleNewImpact's
        // class-level comment). Scoping by Weekly too would recreate the
        // exact duplicate-H4Setup bug this resolves.
        //
        // Part 15 hardening: compare by ProtectedSwingIdx (the H4 engine's
        // own stable structural swing index -- the same int PoiMarketEngine
        // stamped on the raw zone at creation), NOT by float Price equality.
        // Two swings could in principle share an identical price (e.g. a
        // double top/bottom) while being genuinely different structural
        // points; the index can never collide that way. Type/Price/Time
        // stay on H4Setup purely for display/journaling.
        private H4Setup FindLiveSetupForSwing(int protectedSwingIdx)
        {
            foreach (var s in Setups)
            {
                if (s.Status == H4SetupStatus.Terminated) continue;
                if (s.ProtectedSwingIdx == protectedSwingIdx)
                    return s;
            }
            return null;
        }

        private void HandleRetouch(PoiLifecycleEvent ev)
        {
            foreach (var setup in FindOwningSetups(ev.Snapshot))
                _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = setup, TriggeringPoi = ev.Snapshot, Time = ev.Time, Note = "H4 POI retouched" });
        }

        private void HandleTerminalPoi(PoiLifecycleEvent ev)
        {
            // Round 2 fix: fan out to EVERY setup this POI supports (a POI
            // can now support more than one, see HandleNewImpact), not just
            // the first one found.
            foreach (var setup in FindOwningSetups(ev.Snapshot))
            {
                // Strategy clarification (follow-up round): Superseded is a
                // SUCCESS outcome, already final -- do not overwrite it with
                // a failure-labeled Terminated just because its supporting
                // POIs eventually go terminal too. Its execution job is
                // already done either way.
                if (setup.Status == H4SetupStatus.Terminated || setup.Status == H4SetupStatus.Superseded) continue;
                if (setup.SupportingCluster.HasLiveMember) continue;

                Terminate(setup, $"All supporting H4 POIs terminal (last: {ev.Snapshot.TypeAtActivation} {ev.Type})", ev.Time);
            }
        }

        private void Terminate(H4Setup setup, string reason, DateTime time)
        {
            setup.Status = H4SetupStatus.Terminated;
            setup.TerminatedTime = time;
            setup.TerminationReason = reason;
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Terminated, Setup = setup, TriggeringPoi = null, Time = time, Note = reason });
            // Parent WeeklyOpportunity is deliberately untouched (spec section 7).
        }

        private List<H4Setup> FindOwningSetups(S1PoiSnapshot snap)
        {
            var result = new List<H4Setup>();
            foreach (var s in Setups)
                if (s.SupportingCluster.Members.Contains(snap))
                    result.Add(s);
            return result;
        }
    }
}
