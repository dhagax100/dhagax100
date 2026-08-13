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

    // Directional Control -- spec section 3. Scoped per-narrative (one
    // instance lives on the WeeklyOpportunity that is being contested),
    // never a system-wide gate.
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
        Terminated
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

        public S1PoiLifecycleState LifecycleState = S1PoiLifecycleState.Available;
        public int RetouchCount = 0;

        public SwingType? RelevantReactionSwingType;
        public double? RelevantReactionSwingPrice;
        public DateTime? RelevantReactionSwingConfirmationTime;

        public string InvalidationReason;
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

    public class WeeklyOpportunity
    {
        public string WeeklyOpportunityId;
        public Direction Direction;
        public WeeklyOpportunityStatus Status = WeeklyOpportunityStatus.Active;
        public DateTime ActivationTime;

        public PoiCluster SupportingCluster;
        public readonly List<H4Setup> H4Setups = new List<H4Setup>();

        // Directional Control -- spec section 3. Starts matching this
        // opportunity's own direction (it IS the current control when it
        // activates); may flip when a counter-direction Old/Aggressive POI
        // is respected and its reaction swing confirms.
        public ControlState Control;
        public string ControlSourcePoiId;
        public SwingType? ControlSwingType;
        public double? ControlSwingPrice;
        public DateTime? ControlSwingTime;

        // The counter-direction cluster currently being contested for
        // control of this narrative (if any) -- separate from
        // SupportingCluster, which supports the ORIGINAL direction.
        public PoiCluster ContestingCluster;

        public DateTime? TerminationTime;
        public string TerminationReason;

        public int RetouchCounter = 0; // WeeklyRetouchNumber source
    }

    public class H4Setup
    {
        public string H4SetupId;
        public string WeeklyOpportunityId;
        public Direction Direction;
        public H4Route Route;
        public H4SetupStatus Status = H4SetupStatus.Watching;

        public PoiCluster SupportingCluster;

        // Protected structural swing -- spec section 7: the SAME swing
        // reference the POI itself was created from internally.
        public SwingType ProtectedSwingType;
        public double ProtectedSwingPrice;
        public DateTime ProtectedSwingTime;

        public readonly List<M5Attempt> M5Attempts = new List<M5Attempt>();

        public DateTime CreatedTime;
        public DateTime? TerminatedTime;
        public string TerminationReason;

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

        public SwingType StopSwingType;
        public double StopSwingPrice;
        public DateTime StopSwingTime;

        public string PendingOrderId;
        public DateTime? PendingOrderCreatedTime;
        public int PendingOrderModificationCount = 0;

        public DateTime? EntryTime;
        public double RequestedEntryPrice;
        public double? ActualFillPrice;

        public double SLPrice;
        public double TPPrice;

        public long? PositionId;

        public DateTime? ExitTime;
        public double? ExitPrice;
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
