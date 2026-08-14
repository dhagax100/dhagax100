// ICT_S1 — Data models, enums, and ID generation.
// See docs/s1_ea_specification.md for the rules these types encode.
//
// Design note: the raw Pine-mirrored zone objects (ObZone/FvgZone/RbZone/
// ViZone from ICT_Full_OB_v24.cs / MarketStructureEngine below) are NOT
// replaced by these types. S1PoiSnapshot WRAPS a raw zone at the moment of
// its first qualifying impact and then lives independently of it -- per
// spec section 2, "Pine SPENT is not S1's terminal state." The raw engine
// stays the single source of truth for swing/regime/POI DETECTION; these
// types are the S1 strategy-layer lifecycle built on top of that.

using System;
using System.Collections.Generic;

namespace cAlgo.Robots.ICT_S1
{
    public enum Direction
    {
        Buy,
        Sell
    }

    public enum PoiFamily
    {
        OB,
        FVG,
        RB,
        VI
    }

    // The POI's type at the moment S1 froze it -- kept as a label, not an
    // enum tied to the raw engine's numeric state, because the raw state
    // keeps evolving (e.g. AIFOB -> IFOB) while this stays frozen forever
    // (spec section 6/2.1: "historical identity never rewritten").
    public enum PoiTypeLabel
    {
        IFOB, AOB, AIFOB, OOB,
        IFVG, AFVG, OFVG,
        IRB, ARB, AIRB, ORB,
        IVI, AVI, OVI
    }

    // Unified S1 POI lifecycle -- spec section 2. Applies identically to
    // Old, Aggressive, In-Favor, and Aggressive-In-Favor POIs alike.
    public enum S1PoiLifecycleState
    {
        Available,
        ImpactedUnresolved,
        Invalidated,
        ReactionSwingConfirmed,
        Retired
    }

    // Directional Control -- spec section 3. Strategy-owner-confirmed
    // (concurrency mandate, 2026-08-13, Owner Answer A): scoped per genuinely-
    // independent DirectionalPhaseContext, not one system-wide gate and not
    // one instance per WeeklyOpportunity (that was the earlier, over-
    // fragmented model, corrected once already -- see DirectionalPhaseContext
    // below for the current model and why it isn't either extreme).
    public enum ControlState
    {
        BuyControl,
        SellControl,
        Neutral
    }

    public enum WeeklyOpportunityStatus
    {
        Active,
        Terminated
    }

    // Spec section 7.
    public enum H4Route
    {
        RouteA_Confirmed,
        RouteB_Aggressive
    }

    public enum H4SetupStatus
    {
        Watching,   // parent Weekly active, no MSS/AggPOI impact yet
        Impacted,   // H4 POI cluster impacted, M5 execution active
        // Strategy clarification (follow-up round): a SUCCESSFUL structural
        // outcome -- a new same-kind H4 protected swing confirms beyond
        // (better than) this reaction's own -- is not the same thing as
        // INVALIDATED (a failure outcome). Superseded means R1's execution
        // job is done and the market has moved on to a new H4 structure; it
        // is not "wrong", it's "finished". No new M5 attempts originate
        // from a Superseded setup; an already-open position is untouched.
        Superseded,
        Terminated  // failure path: protected swing violated, or all supporting POIs terminal
    }

    // Strategy clarification (follow-up round), Part 38: attempt-level
    // status (M5AttemptStatus) and execution-WINDOW-level status are
    // different concepts and must not be overloaded onto one enum. One H4
    // reaction's M5 execution window can span several sequential Attempts
    // (each with its own SL/TP/Cancelled outcome) before the window itself
    // completes.
    public enum M5ExecutionState
    {
        Active,
        // Post-entry structure has successfully advanced (Part 6/11): the
        // execution thesis is proven and no further M5 attempt may
        // originate from this H4 reaction, regardless of what happens to
        // whichever attempt is currently open.
        CompletedStructurally
    }

    public enum M5AttemptStatus
    {
        TrackingSwing, // watching for relevant M5 swing, order not yet placed
        Pending,       // stop order live, not yet triggered
        Triggered,
        Open,
        ClosedSL,
        ClosedTP,
        Cancelled
    }

    public enum ExitReason
    {
        StopLoss,
        TakeProfit,
        ManualIntervention,
        SetupTerminated
    }

    public enum SwingType
    {
        High,
        Low
    }

    // Monotonic per-run ID generator. Prefixed strings match the spec's
    // WeeklyOpportunityID/H4SetupID/M5AttemptID/etc. naming.
    public static class IdGenerator
    {
        private static int _weekly = 0;
        private static int _poiCluster = 0;
        private static int _poi = 0;
        private static int _h4Setup = 0;
        private static int _m5Attempt = 0;
        private static int _trade = 0;
        private static int _order = 0;

        public static string NextWeeklyOpportunityId() => "W" + (++_weekly).ToString("D4");
        public static string NextPoiClusterId() => "PC" + (++_poiCluster).ToString("D5");
        public static string NextPoiId() => "POI" + (++_poi).ToString("D5");
        public static string NextH4SetupId() => "H4" + (++_h4Setup).ToString("D5");
        public static string NextM5AttemptId() => "M5" + (++_m5Attempt).ToString("D5");
        public static string NextTradeId() => "T" + (++_trade).ToString("D5");
        public static string NextOrderId() => "O" + (++_order).ToString("D5");

        private static int _directionalContext = 0;
        public static string NextDirectionalContextId() => "CTX" + (++_directionalContext).ToString("D4");
    }

    // Frozen S1 representation of a POI -- spec section 2.1. Created once,
    // at the POI's first qualifying impact; independently tracked from
    // then on regardless of what the raw Pine-mirrored engine does to the
    // live zone object afterward.
    public class S1PoiSnapshot
    {
        public string SourcePoiId;         // stable identity of the underlying raw zone
        public string S1PoiId;             // this snapshot's own ID (IdGenerator.NextPoiId)
        public string WeeklyOpportunityId;
        public string PoiClusterId;
        public string Timeframe;           // "Weekly" or "H4"
        public PoiFamily Family;
        public PoiTypeLabel TypeAtActivation;
        public Direction Direction;
        public double Zb;
        public double Zt;
        public DateTime CreationTime;
        public DateTime TriggerTime;
        public DateTime EligibilityTime;
        public DateTime FirstImpactTime;
        public int FirstImpactBarIndex;    // this timeframe's own bar index, for event-scan cursoring

        // Raw origin bucket at freeze time (ObZone.OrigState / Fvg|Rb|ViZone.Origin):
        // 0/4 = far-side ("I..."-style) bucket, 1 = near-side ("A..."-style) bucket.
        // Preserved so PoiLifecycleTracker can keep applying the correct
        // family-specific stranding rule independently after Pine stops
        // watching this (now SPENT) zone.
        public int OriginBucket;

        // Exact structural swing this POI was created from, as stored by
        // the engine at creation time (Round 2 fix -- consumed directly by
        // H4SetupEngine as the protected swing; never reconstructed after
        // the fact by scanning for "the nearest swing near this POI").
        public SwingType? SourceSwingType;
        public double? SourceSwingPrice;
        public DateTime? SourceSwingConfirmationTime;
        // Stable structural identity (this timeframe's own raw engine swing
        // index) -- Part 15 hardening: reaction/ownership identity checks
        // must compare this, not float Price equality.
        public int SourceSwingIdx = -1;

        public S1PoiLifecycleState LifecycleState = S1PoiLifecycleState.Available;
        public int RetouchCount = 0;

        public SwingType? RelevantReactionSwingType;
        public double? RelevantReactionSwingPrice;
        public DateTime? RelevantReactionSwingConfirmationTime;

        public string InvalidationReason;
        public DateTime? InvalidationTime;
        public string RetirementReason;
        public DateTime? RetirementTime;

        // True while this POI's frozen [Zb,Zt] range should still be
        // independently watched for a new touch (spec section 2: while
        // ImpactedUnresolved, "may remain repeatably tradable").
        public bool IsRepeatable => LifecycleState == S1PoiLifecycleState.ImpactedUnresolved;

        public bool IsTerminal => LifecycleState == S1PoiLifecycleState.Invalidated
                                || LifecycleState == S1PoiLifecycleState.Retired;
    }

    // A cluster of S1PoiSnapshots forming ONE trading stream (spec section 4).
    // Any overlap (or, at H4 level, simultaneous validity under one parent)
    // groups POIs into a cluster; membership survives individual member
    // invalidation/retirement as long as >=1 member is not terminal.
    public class PoiCluster
    {
        public string PoiClusterId;
        public Direction Direction;
        public readonly List<S1PoiSnapshot> Members = new List<S1PoiSnapshot>();

        public bool HasLiveMember
        {
            get
            {
                foreach (var m in Members)
                    if (!m.IsTerminal) return true;
                return false;
            }
        }
    }

    // Strategy clarification (follow-up round, 2026-08-13, Parts 17-37):
    // WeeklyOpportunity is PURELY a POI-validity/lineage object --
    // individual family-specific validity, invalidation, lifecycle,
    // retouch history. It does NOT carry its own Control -- that was the
    // confirmed bug from an earlier round ("an independent simultaneous
    // BUY_CONTROL universe" per Weekly POI, Part 21). Directional trade
    // PERMISSION lives on whichever DirectionalPhaseContext this
    // opportunity belongs to (DirectionalContextId, below) -- CONFIRMED
    // UPDATED (concurrency mandate, 2026-08-13, Owner Answer A): Control
    // is scoped per-context, not one single system-wide instance as the
    // immediately-prior round had it. A context can own many
    // WeeklyOpportunities of BOTH directions (Part 10: "same context does
    // not mean same POI"); this field just says which one.
    public class WeeklyOpportunity
    {
        public string WeeklyOpportunityId;
        public Direction Direction;
        public WeeklyOpportunityStatus Status = WeeklyOpportunityStatus.Active;
        public DateTime ActivationTime;

        public PoiCluster SupportingCluster;
        public readonly List<H4Setup> H4Setups = new List<H4Setup>();

        // Which DirectionalPhaseContext this opportunity's activation/
        // retouch/retirement events feed into and are governed by -- set
        // once, at activation (WeeklyOpportunityEngine.HandleNewImpact),
        // never reassigned afterward (an opportunity does not change which
        // narrative it belongs to mid-life).
        public string DirectionalContextId;

        public DateTime? TerminationTime;
        public string TerminationReason;

        public int RetouchCounter = 0; // WeeklyRetouchNumber source
    }

    // CONCURRENCY MANDATE, 2026-08-13, OWNER ANSWER A ("both fresh streams
    // allowed") -- REPLACES the immediately-prior round's single global
    // DirectionalPhase (ONE instance per run). That model could not
    // represent a genuinely independent fresh BUY narrative and a
    // genuinely independent fresh SELL narrative both existing at once
    // (Owner-confirmed: this must be possible). It is also NOT a return to
    // "one Control per WeeklyOpportunity" (the earlier, already-discredited
    // over-fragmented model, Part 4/56 of the concurrency mandate) -- that
    // model's own documented failure was a late-activating same-direction
    // opportunity independently claiming Control while a real, already-in-
    // progress counter-reaction elsewhere said otherwise.
    //
    // CONTEXT-MEMBERSHIP RULE (owner selected "B -- coarser movement-based
    // grouping needed" over the zero-invention "1:1 WeeklyOpportunity"
    // option, and asked this engineer to propose the rule -- ENGINEERING-
    // PROPOSED, not independently owner-verified beyond that selection;
    // flag for owner review):
    //   A DirectionalPhaseContext's boundary is the Weekly timeframe's own
    //   Market Structure Shift (MssEv, PoiMarketEngine.Msses) -- an
    //   already-computed, Pine-native structural fact, not a new invented
    //   rule. Every Weekly POI/opportunity that activates between one MSS
    //   and the next OPPOSITE-direction MSS shares ONE context, regardless
    //   of price overlap -- this is what actually captures "several Weekly
    //   POIs inside the SAME current uptrend" (original owner clarification,
    //   Part 27 of the forensic-audit mandate) beyond the narrower,
    //   overlap-only WeeklyOpportunity/PoiCluster grouping (Finding 4).
    //   A same-direction MSS re-confirmation does NOT open a new context
    //   (still the same movement). When a NEW context opens, the OLD one is
    //   not terminated or force-reset -- its existing members keep
    //   evolving its Control independently using only their own events
    //   (Part 63/64: POI validity/narrative state is never invalidated by
    //   a newer, unrelated development) -- this is exactly what allows an
    //   older still-live context and the newest context to simultaneously
    //   hold opposite Control states, satisfying Owner Answer A.
    //   Before the very first MSS ever fires, one bootstrap context (no MSS
    //   provenance) is used, mirroring the prior round's global-bootstrap
    //   rule exactly, just scoped.
    //   A counter-direction Old/Aggressive-family POI's retirement flips
    //   the Control of whichever context IT ITSELF is already a member of
    //   (assigned at its own activation, like any other POI) -- never a
    //   different context, and never fanned to every live context. This
    //   answers Part 26 of the concurrency mandate ("do not fan X to all
    //   contexts") without inventing a separate routing rule: membership
    //   answers it because a counter-POI is simply a member of whichever
    //   context was current when it activated, exactly like any continuation
    //   POI is.
    //
    // This rule is ENGINEERING-PROPOSED (Part 54 labeling discipline) --
    // it was not independently spelled out by the owner beyond selecting
    // "propose the rule" -- and should be treated as reviewable, not as
    // settled OWNER-CONFIRMED fact, until exercised against a real backtest.
    public class DirectionalPhaseContext
    {
        public string ContextId;

        // Null = no Control established yet in this context (bootstrap not
        // yet reached -- mirrors the prior round's global-bootstrap null).
        public ControlState? State;
        public DateTime? EstablishedTime;

        // Provenance: how this CONTEXT (not its Control state) came into
        // existence -- either the one pre-MSS bootstrap context, or a
        // genuine Weekly MSS. Distinct from Source*/TransitionReason below,
        // which describe the MOST RECENT Control transition inside this
        // context, not the context's own origin.
        public bool BootstrapOrigin;
        public int OriginMssAtIdx = -1;
        public double? OriginMssPrice;
        public bool? OriginMssToUp;
        public DateTime? OriginMssTime;

        // Same forensic Source*/TransitionReason shape the prior round's
        // single DirectionalPhase carried (Parts 47/48) -- now per-context.
        public string SourcePoiId;
        public PoiTypeLabel? SourcePoiType;
        public Direction? SourcePoiDirection;
        public PoiFamily? SourcePoiFamily;
        public int? SourcePoiOriginBucket;
        public S1PoiLifecycleState? SourcePoiLifecycleState;
        public SwingType? SourceSwingType;
        public double? SourceSwingPrice;
        public DateTime? SourceSwingTime;
        public string TransitionReason;
    }

    public enum RejectionCode
    {
        H4_POI_REJECTED_NO_WEEKLY_PARENT,
        H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL,
        H4_POI_REJECTED_NO_PROTECTED_SWING
    }

    // Suppression/rejection journaling (audit section 28) -- proves the EA
    // is filtering correctly, not just showing what it accepted.
    public class RejectionEvent
    {
        public RejectionCode Code;
        public DateTime Time;
        public Direction Direction;
        public string PoiId;
        public PoiTypeLabel? PoiType;
        public string Note;

        // Part 48 forensic-journal fields -- populated only for
        // H4_POI_REJECTED_NARRATIVE_NOT_IN_CONTROL (the phase-suppression
        // path); null/default for the other rejection codes, which don't
        // involve Directional Control. Lets a SELL-suppression forensic
        // pass answer "why was this SELL candidate rejected" from the
        // journal alone, without re-deriving Control state from other files.
        //
        // CONCURRENCY MANDATE UPDATE: with Control scoped per
        // DirectionalPhaseContext (Owner Answer A) rather than one shared
        // global phase, there is no single "the phase" to record anymore --
        // different temporally-valid same-direction Weekly candidates can
        // belong to DIFFERENT contexts with different states. The three
        // lists below are parallel/index-aligned: entry i of
        // TemporallyValidContextIds/States describes the context that
        // TemporallyValidSameDirectionWeeklyIds[i]'s own Weekly opportunity
        // belongs to. A candidate is only actually REJECTED here if EVERY
        // one of its candidate contexts' states failed to permit its
        // direction -- these lists prove that from the journal alone.
        public int SourceSwingIdx = -1;
        public List<string> TemporallyValidSameDirectionWeeklyIds;
        public List<string> TemporallyValidContextIds;
        public List<string> TemporallyValidContextStates;
    }

    public class H4Setup
    {
        public string H4SetupId;
        // Primary (first-authorizing) Weekly -- display/journal convenience
        // ONLY, not an ownership decision. Full lineage is
        // SupportingWeeklyOpportunityIds (strategy owner clarification,
        // 2026-08-13): one physical H4 reaction is ONE H4Setup/execution
        // stream no matter how many Weekly opportunities support it: every
        // qualifying Weekly is recorded here for audit, none is "the owner".
        public string WeeklyOpportunityId;
        public readonly List<string> SupportingWeeklyOpportunityIds = new List<string>();
        // Concurrency mandate Part 38: which DirectionalPhaseContext(s)
        // actually authorized this reaction -- supplements (does not
        // replace) SupportingWeeklyOpportunityIds, since two contexts could
        // in principle both support the same physical H4 reaction (Part 22
        // of the concurrency mandate) just as multiple Weeklies already can.
        public readonly List<string> SupportingDirectionalContextIds = new List<string>();
        public Direction Direction;
        public H4Route Route;
        public H4SetupStatus Status = H4SetupStatus.Watching;

        public PoiCluster SupportingCluster;

        // Protected structural swing -- spec section 7: the SAME swing
        // reference the POI itself was created from internally.
        public SwingType ProtectedSwingType;
        public double ProtectedSwingPrice;
        public DateTime ProtectedSwingTime;
        // Stable structural identity (H4 timeframe's own raw engine swing
        // index) -- the authoritative test for "same H4 reaction" (Part 15
        // hardening); Type/Price/Time are retained for display/journaling.
        public int ProtectedSwingIdx = -1;

        public readonly List<M5Attempt> M5Attempts = new List<M5Attempt>();

        // Round 2 fix (audit section 19): the M5 timeframe must only pair
        // swings confirmed AFTER this window opens -- set/reset by
        // M5ExecutionEngine.EnsureAttemptTracking each time a NEW tracking
        // cycle begins for this setup (first impact, and again on every
        // SL re-entry), so a fresh attempt can never be authorized by a
        // stale swing pair left over from before this cycle (e.g. the very
        // swing pair that just stopped out the previous attempt).
        public DateTime? M5ExecutionActivationTime;

        public DateTime CreatedTime;
        public DateTime? TerminatedTime;
        public string TerminationReason;

        // ==================== M5 EXECUTION COMPLETION (Part 12) ====================
        // Scoped to the H4 reaction, not any one M5Attempt, because it spans
        // however many sequential Attempts occur before either completion
        // or the reaction's own termination/supersession.
        public M5ExecutionState M5ExecutionState = M5ExecutionState.Active;

        // Completion baseline: (re)anchored to whichever M5Attempt most
        // recently FILLED under this setup (M5ExecutionEngine.OnAttemptFilled)
        // -- each fresh fill (e.g. after a non-completing SL re-entry) resets
        // this to that attempt's OWN entry/stop swing pair, since completion
        // is evaluated relative to "has price advanced past what would
        // invalidate THIS live trade's own thesis", not the very first
        // attempt ever made under this reaction.
        public int InitialEntrySwingIdx = -1;
        public double InitialEntrySwingPrice;
        public int InitialStopSwingIdx = -1;
        public double InitialStopSwingPrice;
        public DateTime? InitialEntryTime; // fill time

        // H2 (BUY) / L2 (SELL) -- the continuation swing confirmed after entry.
        public int? PostEntryContinuationSwingIdx;
        public double? PostEntryContinuationSwingPrice;
        public DateTime? PostEntryContinuationSwingTime;

        // L2 (BUY) / H2 (SELL) -- the pullback swing confirmed after the
        // continuation swing; its price relative to Initial*StopSwingPrice
        // is the actual completion test.
        public int? CompletionPullbackSwingIdx;
        public double? CompletionPullbackSwingPrice;
        public DateTime? CompletionPullbackSwingTime;

        public DateTime? M5ExecutionCompletedTime;
        public string M5ExecutionCompletionReason;

        // ==================== H4 SUPERSESSION (Part 15) ====================
        public int? SupersededBySwingIdx;
        public double? SupersededBySwingPrice;
        public DateTime? SupersededTime;

        public int WeeklyRetouchNumber; // which Weekly retouch spawned this setup

        public bool HasOpenAttempt
        {
            get
            {
                foreach (var a in M5Attempts)
                    if (a.Status == M5AttemptStatus.Pending || a.Status == M5AttemptStatus.Triggered || a.Status == M5AttemptStatus.Open)
                        return true;
                return false;
            }
        }
    }

    public class M5Attempt
    {
        public string M5AttemptId;
        public string H4SetupId;
        public Direction Direction;
        public M5AttemptStatus Status = M5AttemptStatus.TrackingSwing;
        public int AttemptNumber;

        public SwingType EntrySwingType;
        public double EntrySwingPrice;
        public DateTime EntrySwingTime;
        public int EntrySwingIdx = -1; // stable structural identity -- Part 12, so H4Setup's completion baseline can reference it exactly

        public SwingType StopSwingType;
        public double StopSwingPrice;
        public DateTime StopSwingTime;
        public int StopSwingIdx = -1;

        // Transient -- set by M5ExecutionEngine.TryMoveOrder immediately
        // before it overwrites Entry/StopSwing* with the new pairing, so
        // the ORDER_MOVED journal row can state exactly which swing pairing
        // was replaced by which (audit section 3/27).
        public SwingType? PreviousEntrySwingType;
        public double? PreviousEntrySwingPrice;
        public DateTime? PreviousEntrySwingTime;
        public SwingType? PreviousStopSwingType;
        public double? PreviousStopSwingPrice;
        public DateTime? PreviousStopSwingTime;

        public string PendingOrderId;
        public string LastCancellationReason; // set immediately before OrderCancelled fires (e.g. "Parent H4Setup terminated")

        // Round 2 fix (audit section 3): FirstPendingOrderCreatedTime is
        // set exactly once and never changes -- "when this attempt's order
        // first went live". PendingOrderCreatedTime is the CURRENT live
        // order's own placement/replace time, and DOES update on every
        // move -- so it always matches whichever EntrySwingTime/StopSwingTime
        // pairing is currently live. Journaling the two separately (plus an
        // explicit ORDER_MOVED_FROM_SWING_A_TO_SWING_B event, see
        // M5ExecutionEngine.TryMoveOrder) is what makes "order timestamp
        // precedes its authorizing swing" stop being ambiguous in the CSV:
        // the FIRST timestamp can legitimately precede a LATER swing that
        // caused a later move: that's not a bug, that's the order having
        // been moved. Only PendingOrderCreatedTime (current) needs to be
        // >= the CURRENT EntrySwingTime/StopSwingTime for a given row.
        public DateTime? FirstPendingOrderCreatedTime;
        public DateTime? PendingOrderCreatedTime;
        public int PendingOrderModificationCount = 0;

        public DateTime? EntryTime;
        public double RequestedEntryPrice;
        public double? ActualFillPrice;

        public double SLPrice;
        public double TPPrice;

        public long? PositionId;
        public double? PositionVolume;

        // Assigned once, at fill time (Round 2 fix, audit section 29) --
        // never regenerated later at close/journal time.
        public string TradeId;

        public DateTime? ExitTime;
        public double? ExitPrice;
        public string ExitPriceSource; // "HistoricalTrade" | "QuoteFallback" -- Part 21 audit instrumentation
        public ExitReason? ExitReason;

        public double? GrossPnL;
        public double? NetPnL;
        public double? RealizedR;
        public double? MFE;
        public double? MFE_R;
        public double? MAE;
        public double? MAE_R;
    }
}
