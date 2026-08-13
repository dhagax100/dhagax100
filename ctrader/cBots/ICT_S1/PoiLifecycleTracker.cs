// ICT_S1 — PoiLifecycleTracker: the unified S1 POI lifecycle overlay.
// Spec: docs/s1_ea_specification.md section 2.
//
// Wraps a PoiMarketEngine's raw zones with the S1 lifecycle:
//   AVAILABLE -> IMPACTED_UNRESOLVED -> INVALIDATED | RETIRED
// applying IDENTICALLY to Old, Aggressive, In-Favor and Aggressive-In-Favor
// POIs alike (confirmed rule -- no separate models per type).
//
// Core principle this file exists to enforce: Pine's SPENT is NOT S1's
// terminal state. The raw engine only ever fires an IMPACT event once per
// zone (state==3 is terminal there, checked-and-skipped forever after).
// This tracker freezes a snapshot at that first impact, then INDEPENDENTLY
// keeps re-checking the frozen [Zb,Zt] range against new bars for further
// retouches, using the same swing/candle data the paired engine keeps
// producing -- because the raw zone itself will never fire another event.
//
// Family-specific rules (never a universal one):
//   - OB/RB: structural stranding only (RB's near/far-side formula is
//     IDENTICAL for both origin buckets -- a confirmed quirk from the
//     ARB/AFVG divergence, preserved exactly, see below).
//   - FVG/VI: structural stranding AND close-through (continuation-type
//     only, OriginBucket != 1), mirroring Pine's own dual invalidation path
//     for these two families.
//
// "Relevant reaction swing" (RETIRED trigger) is an S1-only concept with
// no Pine equivalent: the first confirmed swing, on this same timeframe,
// in the POI's own favor direction (Swing Low for bullish, Swing High for
// bearish), confirming strictly after the POI's first impact. This reuses
// the exact same swing-confirmation engine used everywhere else in S1
// (protected-swing selection, MSS, etc.) rather than inventing a new
// "respected candle" mechanic -- see file comments at the call site if
// this interpretation ever needs revisiting with the strategy owner.

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum PoiEventType
    {
        NewImpact,
        Retouch,
        Invalidated,
        Retired
    }

    public class PoiLifecycleEvent
    {
        public PoiEventType Type;
        public S1PoiSnapshot Snapshot;
        public DateTime Time;
        public string Note;
    }

    public class PoiLifecycleTracker
    {
        private readonly PoiMarketEngine _engine;

        public readonly List<S1PoiSnapshot> AllSnapshots = new List<S1PoiSnapshot>();
        private readonly List<S1PoiSnapshot> _unresolved = new List<S1PoiSnapshot>();
        private readonly Queue<PoiLifecycleEvent> _eventQueue = new Queue<PoiLifecycleEvent>();

        // Pending-freeze cursors: only zones not yet frozen need checking
        // each cycle, and only newly-created zones need adding to that set.
        private int _obsSeenUpto = -1;
        private int _fvgsSeenUpto = -1;
        private int _rbsSeenUpto = -1;
        private int _visSeenUpto = -1;
        private readonly List<ObZone> _obsPending = new List<ObZone>();
        private readonly List<FvgZone> _fvgsPending = new List<FvgZone>();
        private readonly List<RbZone> _rbsPending = new List<RbZone>();
        private readonly List<ViZone> _visPending = new List<ViZone>();

        private int _lastLifecycleIdx = -1; // last bar index this tracker has run retouch/invalidate/retire checks for

        public string Timeframe { get; }

        public PoiLifecycleTracker(PoiMarketEngine engine, string timeframe)
        {
            _engine = engine;
            Timeframe = timeframe;
        }

        public List<PoiLifecycleEvent> DrainEvents()
        {
            var list = new List<PoiLifecycleEvent>(_eventQueue.Count);
            while (_eventQueue.Count > 0) list.Add(_eventQueue.Dequeue());
            return list;
        }

        // Call once per cycle, after the paired PoiMarketEngine.Update().
        public void Update()
        {
            RegisterNewZones();
            FreezeQualifyingImpacts();
            RunOngoingLifecycle();
        }

        private void RegisterNewZones()
        {
            var obs = _engine.Obs;
            for (int i = _obsSeenUpto + 1; i < obs.Count; i++) _obsPending.Add(obs[i]);
            _obsSeenUpto = obs.Count - 1;

            var fvgs = _engine.Fvgs;
            for (int i = _fvgsSeenUpto + 1; i < fvgs.Count; i++) _fvgsPending.Add(fvgs[i]);
            _fvgsSeenUpto = fvgs.Count - 1;

            var rbs = _engine.Rbs;
            for (int i = _rbsSeenUpto + 1; i < rbs.Count; i++) _rbsPending.Add(rbs[i]);
            _rbsSeenUpto = rbs.Count - 1;

            var vis = _engine.Vis;
            for (int i = _visSeenUpto + 1; i < vis.Count; i++) _visPending.Add(vis[i]);
            _visSeenUpto = vis.Count - 1;
        }

        private void FreezeQualifyingImpacts()
        {
            _obsPending.RemoveAll(z =>
            {
                if (z.State != 3) return false;
                FreezeOb(z);
                return true;
            });
            _fvgsPending.RemoveAll(z =>
            {
                if (z.State != 3) return false;
                FreezeFvg(z);
                return true;
            });
            _rbsPending.RemoveAll(z =>
            {
                if (z.State != 3) return false;
                FreezeRb(z);
                return true;
            });
            _visPending.RemoveAll(z =>
            {
                if (z.State != 3) return false;
                FreezeVi(z);
                return true;
            });
        }

        private void FreezeOb(ObZone z)
        {
            PoiTypeLabel type;
            switch (z.PreSpentState)
            {
                case 0: type = PoiTypeLabel.IFOB; break;
                case 1: type = PoiTypeLabel.AOB; break;
                case 2: type = PoiTypeLabel.OOB; break;
                case 4: type = PoiTypeLabel.AIFOB; break;
                default: type = PoiTypeLabel.IFOB; break;
            }
            var snap = NewSnapshot(PoiFamily.OB, type, z.Bullish, z.Zb, z.Zt, z.OrigState, z.StopK, z.Candle, z.TriggerK, z.EligibleK, z.SourcePoiId, z.SourceSwingIdx);
            z.S1SnapshotId = snap.S1PoiId;
        }

        private void FreezeFvg(FvgZone z)
        {
            PoiTypeLabel type;
            switch (z.PreSpentState)
            {
                case 0: type = PoiTypeLabel.IFVG; break;
                case 1: type = PoiTypeLabel.AFVG; break;
                case 2: type = PoiTypeLabel.OFVG; break;
                default: type = PoiTypeLabel.IFVG; break;
            }
            var snap = NewSnapshot(PoiFamily.FVG, type, z.Bullish, z.Zb, z.Zt, z.Origin, z.StopK, z.LeftIdx, z.TriggerK, z.EligibleK, z.SourcePoiId, z.SourceSwingIdx);
            z.S1SnapshotId = snap.S1PoiId;
        }

        private void FreezeRb(RbZone z)
        {
            PoiTypeLabel type;
            switch (z.PreSpentState)
            {
                case 0: type = PoiTypeLabel.IRB; break;
                case 1: type = PoiTypeLabel.ARB; break;
                case 2: type = PoiTypeLabel.ORB; break;
                case 4: type = PoiTypeLabel.AIRB; break;
                default: type = PoiTypeLabel.IRB; break;
            }
            // RB direction is used AS-IS from the raw engine's raw-wick
            // convention -- confirmed rule, no hunt-direction translation.
            var snap = NewSnapshot(PoiFamily.RB, type, z.Bullish, z.Zb, z.Zt, z.Origin, z.StopK, z.LeftIdx, z.TriggerK, z.EligibleK, z.SourcePoiId, z.SourceSwingIdx);
            z.S1SnapshotId = snap.S1PoiId;
        }

        private void FreezeVi(ViZone z)
        {
            PoiTypeLabel type;
            switch (z.PreSpentState)
            {
                case 0: type = PoiTypeLabel.IVI; break;
                case 1: type = PoiTypeLabel.AVI; break;
                case 2: type = PoiTypeLabel.OVI; break;
                default: type = PoiTypeLabel.IVI; break;
            }
            var snap = NewSnapshot(PoiFamily.VI, type, z.Bullish, z.Zb, z.Zt, z.Origin, z.StopK, z.LeftIdx, z.TriggerK, z.EligibleK, z.SourcePoiId, z.SourceSwingIdx);
            z.S1SnapshotId = snap.S1PoiId;
        }

        // Finding 13 fix: CreationTime/TriggerTime/EligibilityTime are now
        // populated from the raw zone's own bar indices instead of being
        // left at their default (unset) value forever.
        //
        // Round 2 fix (audit section 25): sourcePoiId/sourceSwingIdx are the
        // exact identity/structural-swing metadata the raw engine stamped
        // at creation time (PoiMarketEngine.RawPoiIdGenerator / AddOB|Fvg|Rb|Vi's
        // sourceSwingIdx parameter). Frozen here so H4SetupEngine can consume
        // the exact original swing directly instead of reconstructing it later.
        private S1PoiSnapshot NewSnapshot(PoiFamily family, PoiTypeLabel type, bool bullish, double zb, double zt, int originBucket, int impactBarIdx, int creationBarIdx, int triggerBarIdx, int eligibleBarIdx, string sourcePoiId, int sourceSwingIdx)
        {
            var snap = new S1PoiSnapshot
            {
                S1PoiId = IdGenerator.NextPoiId(),
                SourcePoiId = sourcePoiId,
                Timeframe = Timeframe,
                Family = family,
                TypeAtActivation = type,
                Direction = bullish ? Direction.Buy : Direction.Sell,
                Zb = zb,
                Zt = zt,
                OriginBucket = originBucket,
                FirstImpactBarIndex = impactBarIdx,
                FirstImpactTime = BarTime(impactBarIdx),
                CreationTime = BarTime(creationBarIdx),
                TriggerTime = BarTime(triggerBarIdx),
                EligibilityTime = BarTime(eligibleBarIdx),
                LifecycleState = S1PoiLifecycleState.ImpactedUnresolved
            };
            PopulateSourceSwing(snap, sourceSwingIdx);
            AllSnapshots.Add(snap);
            _unresolved.Add(snap);
            _eventQueue.Enqueue(new PoiLifecycleEvent { Type = PoiEventType.NewImpact, Snapshot = snap, Time = snap.FirstImpactTime, Note = $"{type} first qualifying impact" });
            return snap;
        }

        // Looks up the exact recorded swing-confirmation event for the
        // structural swing index the engine stamped on the raw zone at
        // creation -- not a reconstruction/approximation: SwingIdx is the
        // same bar index AddOB/AddFvg/AddRb/AddVi's caller passed in, and
        // each confirmed swing has exactly one AddEv entry recording its
        // Kind (High/Low), Price, and confirmation bar (ConfirmIdx).
        private void PopulateSourceSwing(S1PoiSnapshot snap, int sourceSwingIdx)
        {
            if (sourceSwingIdx < 0) return;
            // Stable structural identity, independent of Type/Price/Time
            // (Part 15 hardening: H4 reaction-swing identity comparisons
            // must not rely on floating-point price equality).
            snap.SourceSwingIdx = sourceSwingIdx;
            foreach (var ev in _engine.Events)
            {
                if (ev.SwingIdx != sourceSwingIdx) continue;
                snap.SourceSwingType = ev.Kind == 0 ? SwingType.High : SwingType.Low;
                snap.SourceSwingPrice = ev.Price;
                snap.SourceSwingConfirmationTime = BarTime(ev.ConfirmIdx);
                return;
            }
        }

        // -1 (e.g. EligibleK not yet set at freeze time, though it always
        // is by SPENT time in practice) or an out-of-range index -> default
        // DateTime rather than throwing.
        private DateTime BarTime(int idx) =>
            idx >= 0 && idx < _engine.BT.Count ? _engine.BT[idx] : default(DateTime);

        private void RunOngoingLifecycle()
        {
            int upto = _engine.LastProcessedIndex;
            for (int k = _lastLifecycleIdx + 1; k <= upto; k++)
                CheckBar(k);
            _lastLifecycleIdx = upto;
        }

        private void CheckBar(int k)
        {
            if (_unresolved.Count == 0) return;
            double hK = _engine.H[k];
            double lK = _engine.L[k];
            double cK = _engine.C[k];
            DateTime t = _engine.BT[k];

            // Snapshot the list since items get removed from _unresolved mid-loop.
            var snapshot = _unresolved.ToArray();
            foreach (var s in snapshot)
            {
                if (s.LifecycleState != S1PoiLifecycleState.ImpactedUnresolved) continue;

                // CRITICAL invariant: no lifecycle event may be generated from
                // a bar at or before this snapshot's own first qualifying
                // impact. A single Update() call can process many bars at
                // once (e.g. OnStart backfill) for snapshots frozen partway
                // through that range -- without this guard, a snapshot frozen
                // at bar 50 would still get checked against bars 0-49,
                // "retouching" or invalidating on history that predates its
                // own existence. `k != FirstImpactBarIndex` alone (the old
                // check) let k < FirstImpactBarIndex straight through.
                if (k <= s.FirstImpactBarIndex) continue;

                bool bull = s.Direction == Direction.Buy;

                // --- Retouch (informational; does not itself change state) ---
                if (hK >= s.Zb && lK <= s.Zt)
                {
                    s.RetouchCount++;
                    _eventQueue.Enqueue(new PoiLifecycleEvent { Type = PoiEventType.Retouch, Snapshot = s, Time = t, Note = $"Retouch #{s.RetouchCount}" });
                }

                // --- Invalidation (family-specific) ---
                bool invalidated = CheckInvalidation(s, k, bull, cK, t);
                if (invalidated) continue;

                // --- Retirement (reaction swing confirmed) ---
                CheckRetirement(s, k, bull, t);
            }
        }

        private bool CheckInvalidation(S1PoiSnapshot s, int k, bool bull, double cK, DateTime t)
        {
            // CLOSE-THROUGH -- FVG/VI, continuation-type only (OriginBucket != 1).
            if ((s.Family == PoiFamily.FVG || s.Family == PoiFamily.VI) && s.OriginBucket != 1)
            {
                bool closedThrough = bull ? cK < s.Zb : cK > s.Zt;
                if (closedThrough)
                {
                    Invalidate(s, "close-through", t);
                    return true;
                }
            }

            // STRUCTURAL STRANDING -- scan swing events confirmed exactly at bar k.
            foreach (var ev in _engine.Events)
            {
                if (ev.ConfirmIdx != k) continue;
                bool stranded;
                if (s.Family == PoiFamily.RB)
                {
                    // Confirmed quirk: RB's near-side (ARB) formula is
                    // IDENTICAL to its far-side (IRB) formula -- ARB's raw-
                    // wick bull/bear tag is the opposite convention from
                    // AFVG's hunt-direction tag, so origin doesn't change
                    // which geometry applies here. See PoiMarketEngine's
                    // STEP 3c comment for the full derivation.
                    stranded = (bull && ev.Kind == 1 && ev.Price > s.Zt) || (!bull && ev.Kind == 0 && ev.Price < s.Zb);
                }
                else
                {
                    bool isFarSide = s.OriginBucket != 1;
                    if (isFarSide)
                        stranded = (bull && ev.Kind == 1 && ev.Price > s.Zt) || (!bull && ev.Kind == 0 && ev.Price < s.Zb);
                    else
                        stranded = (bull && ev.Kind == 0 && ev.Price < s.Zb) || (!bull && ev.Kind == 1 && ev.Price > s.Zt);
                }
                if (stranded)
                {
                    Invalidate(s, "structural stranding", t);
                    return true;
                }
            }
            return false;
        }

        private void CheckRetirement(S1PoiSnapshot s, int k, bool bull, DateTime t)
        {
            if (k <= s.FirstImpactBarIndex) return;
            foreach (var ev in _engine.Events)
            {
                if (ev.ConfirmIdx != k) continue;
                // Bullish POI retires on its relevant reaction Swing LOW (kind==1);
                // bearish POI retires on its relevant reaction Swing HIGH (kind==0).
                bool isReactionSwing = bull ? ev.Kind == 1 : ev.Kind == 0;
                if (isReactionSwing)
                {
                    s.LifecycleState = S1PoiLifecycleState.ReactionSwingConfirmed;
                    s.RelevantReactionSwingType = bull ? SwingType.Low : SwingType.High;
                    s.RelevantReactionSwingPrice = ev.Price;
                    s.RelevantReactionSwingConfirmationTime = t;
                    s.RetirementReason = "Reaction swing confirmed";
                    s.RetirementTime = t;
                    s.LifecycleState = S1PoiLifecycleState.Retired;
                    _unresolved.Remove(s);
                    _eventQueue.Enqueue(new PoiLifecycleEvent { Type = PoiEventType.Retired, Snapshot = s, Time = t, Note = "Reaction swing confirmed -> retired" });
                    return;
                }
            }
        }

        private void Invalidate(S1PoiSnapshot s, string reason, DateTime t)
        {
            s.LifecycleState = S1PoiLifecycleState.Invalidated;
            s.InvalidationReason = reason;
            s.InvalidationTime = t;
            _unresolved.Remove(s);
            _eventQueue.Enqueue(new PoiLifecycleEvent { Type = PoiEventType.Invalidated, Snapshot = s, Time = t, Note = reason });
        }
    }
}
