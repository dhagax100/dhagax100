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
// opportunities was REMOVED, replaced with "authorize/join every qualifying
// narrative independently" (FindArmingWeeklyOpportunities/HandleNewImpact).
//
// COMMENT-ACCURACY CORRECTION (Part 28/29 of the 2026-08-13 final audit --
// the prior wording here overclaimed this as a settled fix): "every
// qualifying candidate" is ITSELF an unconfirmed strategy decision, exactly
// as much a guess as "most recent" was, just a different one -- backtest
// evidence shows ~42 cases of one physical H4 POI impact being cloned
// across multiple WeeklyOpportunityID/H4SetupID pairs as a direct result.
// This is NOT presented as resolved. See the current repair report's open
// strategy question (Weekly->H4 ownership) -- BLOCKED pending the owner's
// answer, not silently left as "all candidates" by default.
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
// (not time, not geometry) -- see AuthorizeOrJoin/FindLiveSetupForSwing.
// More than one H4Setup can now be simultaneously live under one Weekly
// opportunity, one per distinct protected swing.

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

            var (qualifying, anyTemporallyValidCandidate) = FindArmingWeeklyOpportunities(snap.Direction, ev.Time);
            if (qualifying.Count == 0)
            {
                var code = anyTemporallyValidCandidate
                    ? RejectionCode.H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL
                    : RejectionCode.H4_POI_REJECTED_NO_WEEKLY_PARENT;
                _rejectionQueue.Enqueue(new RejectionEvent { Code = code, Time = ev.Time, Direction = snap.Direction, PoiId = snap.S1PoiId, Note = $"{snap.TypeAtActivation} impact at {ev.Time:O} has no authorizing Weekly narrative" });
                return;
            }

            // BLOCKED STRATEGY QUESTION, NOT A SETTLED FIX (final audit
            // Parts 10-13/28-29): the "most recently activated" tie-break
            // was REMOVED, but "authorize every qualifying narrative
            // independently" is ITSELF an unconfirmed strategy decision --
            // no more proven than the tie-break it replaced. Backtest
            // evidence: ~42 cases of one physical H4 POI impact producing
            // more than one WeeklyOpportunityID/H4SetupID. Left running
            // as-is (not reverted to a single-owner guess either, per "do
            // not choose merely because you cannot fan-out") while this is
            // an open question to the strategy owner -- see the current
            // repair report. snap.WeeklyOpportunityId/PoiClusterId (single-
            // valued display fields) are set from the FIRST authorization
            // only; the authoritative multi-owner relationship lives in
            // each H4Setup's own SupportingCluster.Members (see
            // FindOwningSetups, which every consumer of "this POI's setup"
            // must use instead of assuming a single owner).
            bool first = true;
            foreach (var weekly in qualifying)
            {
                AuthorizeOrJoin(snap, weekly, ev, first);
                first = false;
            }
        }

        private void AuthorizeOrJoin(S1PoiSnapshot snap, WeeklyOpportunity weekly, PoiLifecycleEvent ev, bool isPrimary)
        {
            // Round 2 fix (audit section 25): the protected swing is now the
            // EXACT structural swing PoiMarketEngine stamped on the raw zone
            // at creation (frozen onto the snapshot by PoiLifecycleTracker),
            // not a reconstruction inferred from direction alone. Different
            // POI types are armed off different swings (e.g. an aggressive
            // continuation OB is armed off the broken opposite-side swing,
            // not always "the same-direction swing") -- consuming the exact
            // stored reference is what the audit requires; a direction-only
            // "BUY always protected by a swing LOW" rule was itself the kind
            // of reconstruction/approximation this fix removes. Needed here
            // BEFORE the live-setup lookup too, since H4 reaction identity
            // (below) is itself defined by this exact swing.
            if (snap.SourceSwingType == null || snap.SourceSwingPrice == null || snap.SourceSwingConfirmationTime == null || snap.SourceSwingIdx < 0)
            {
                // Finding 10: fail safely, no fake fallback -- do not arm.
                _rejectionQueue.Enqueue(new RejectionEvent { Code = RejectionCode.H4_POI_REJECTED_NO_PROTECTED_SWING, Time = ev.Time, Direction = snap.Direction, PoiId = snap.S1PoiId, Note = $"No source-swing reference was stored for this {snap.TypeAtActivation} at creation -- refusing to arm with a substituted level" });
                return;
            }

            // H4 REACTION GROUPING RULE (strategy owner clarification,
            // 2026-08-13): H4 reaction identity is structural, not time-
            // based and not geometric. Multiple H4 POIs belong to the SAME
            // H4 reaction/H4Setup while they are anchored to the SAME
            // relevant protected H4 swing. Geometric overlap is not
            // required. A later qualifying H4 POI anchored to a newly
            // confirmed protected swing DIFFERENT from a live setup's own
            // starts a NEW H4 reaction/H4Setup, even if that earlier setup
            // under the same Weekly narrative hasn't otherwise terminated.
            // No elapsed-time, distance, or "most recent" heuristic --
            // exact swing-identity match only. This also means more than
            // one H4Setup can now be simultaneously live under one Weekly
            // opportunity (one per distinct protected swing), which is why
            // "live setup" below is scoped by swing identity, not just by
            // WeeklyOpportunityId.
            var live = FindLiveSetupForSwing(weekly.WeeklyOpportunityId, snap.SourceSwingIdx);
            if (live != null)
            {
                if (isPrimary) { snap.WeeklyOpportunityId = weekly.WeeklyOpportunityId; snap.PoiClusterId = live.SupportingCluster.PoiClusterId; }
                live.SupportingCluster.Members.Add(snap);
                _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Retouched, Setup = live, TriggeringPoi = snap, Time = ev.Time, Note = $"H4 POI joined live reaction -- same protected swing {snap.SourceSwingType}@{snap.SourceSwingPrice} ({snap.TypeAtActivation})" });
                return;
            }

            var route = IsInFavorType(snap.TypeAtActivation) ? H4Route.RouteA_Confirmed : H4Route.RouteB_Aggressive;

            var cluster = new PoiCluster { PoiClusterId = IdGenerator.NextPoiClusterId(), Direction = snap.Direction };
            cluster.Members.Add(snap);
            if (isPrimary) { snap.WeeklyOpportunityId = weekly.WeeklyOpportunityId; snap.PoiClusterId = cluster.PoiClusterId; }

            var setup = new H4Setup
            {
                H4SetupId = IdGenerator.NextH4SetupId(),
                WeeklyOpportunityId = weekly.WeeklyOpportunityId,
                Direction = snap.Direction,
                Route = route,
                Status = H4SetupStatus.Impacted,
                SupportingCluster = cluster,
                ProtectedSwingType = snap.SourceSwingType.Value,
                ProtectedSwingPrice = snap.SourceSwingPrice.Value,
                ProtectedSwingTime = snap.SourceSwingConfirmationTime.Value,
                ProtectedSwingIdx = snap.SourceSwingIdx,
                CreatedTime = ev.Time,
                WeeklyRetouchNumber = weekly.RetouchCounter
            };
            Setups.Add(setup);
            weekly.H4Setups.Add(setup); // Finding 11 fix
            _eventQueue.Enqueue(new H4SetupEvent { Type = H4SetupEventType.Impacted, Setup = setup, TriggeringPoi = snap, Time = ev.Time, Note = $"{route} via {snap.TypeAtActivation} -- new H4 reaction, protected swing {snap.SourceSwingType}@{snap.SourceSwingPrice}" });
        }

        private static bool IsInFavorType(PoiTypeLabel t) =>
            t == PoiTypeLabel.IFOB || t == PoiTypeLabel.IFVG || t == PoiTypeLabel.IRB || t == PoiTypeLabel.IVI;

        // CRITICAL 2 + CRITICAL 3: returns EVERY currently-qualifying Weekly
        // opportunity (temporally valid AND currently in its own control) --
        // no tie-break, no single "chosen" winner (Round 2 fix, see
        // HandleNewImpact). The bool tells the caller whether ANY temporally-
        // valid same-direction candidate existed at all (for accurate
        // rejection-code selection: NO_WEEKLY_PARENT vs NOT_IN_CONTROL).
        private (List<WeeklyOpportunity>, bool) FindArmingWeeklyOpportunities(Direction dir, DateTime h4EventTime)
        {
            var qualifying = new List<WeeklyOpportunity>();
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

                qualifying.Add(opp);
            }
            return (qualifying, anyTemporallyValid);
        }

        // RESOLVED (audit sections 7-9, 43 -- strategy owner clarification
        // 2026-08-13, see AuthorizeOrJoin's H4 REACTION GROUPING RULE
        // comment): "same reaction" = anchored to the same exact protected
        // H4 swing, not merely "same Weekly parent, still live". A live
        // setup only qualifies as the same reaction if its ProtectedSwing
        // identity matches exactly.
        //
        // Part 15 hardening: compare by ProtectedSwingIdx (the H4 engine's
        // own stable structural swing index -- the same int PoiMarketEngine
        // stamped on the raw zone at creation), NOT by float Price equality.
        // Two swings could in principle share an identical price (e.g. a
        // double top/bottom) while being genuinely different structural
        // points; the index can never collide that way. Type/Price/Time
        // stay on H4Setup purely for display/journaling.
        private H4Setup FindLiveSetupForSwing(string weeklyOpportunityId, int protectedSwingIdx)
        {
            foreach (var s in Setups)
            {
                if (s.WeeklyOpportunityId != weeklyOpportunityId) continue;
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
                if (setup.Status == H4SetupStatus.Terminated) continue;
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
