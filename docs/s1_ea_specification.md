# ICT S1 — Weekly → H4 → M5 — Final Functional Specification

Authoritative reference for the S1 cTrader cBot. Supersedes ad-hoc
interpretation — every rule below was either stated directly by the
strategy owner or derived explicitly (derivation shown) from confirmed
rules. Do not re-litigate anything here without a stated reason.

Source of truth for market structure/POI mechanics: `pine/ICT_Full_OB_v24.pine`
(ported faithfully to `ctrader/Indicators/ICT_Full_OB_v24.cs`). S1 is a
strategy layer on top of that engine, not a replacement for it.

---

## 1. Timeframe Roles

| TF | Role |
|---|---|
| Weekly | Determines whether a directional opportunity exists at all. Master gate — every trade traces back to a Weekly POI. |
| H4 | Determines whether a Weekly opportunity has developed into a tradable lower-TF setup. |
| M5 | Execution only: relevant swing tracking + dynamic stop-entry placement. |

No H4 or M5 process may independently authorize a trade. `H4 bearish Aggressive POI alone ≠ permission to SELL` without a valid Weekly SELL opportunity already active.

---

## 2. Unified POI Lifecycle (applies to ALL families/states alike)

One state machine for OB/FVG/RB/VI, In-Favor, Aggressive, Aggressive-In-Favor, and Old POIs alike — no separate models per type.

```
AVAILABLE
   │  (qualifying impact per Pine engine)
   ▼
IMPACTED_UNRESOLVED  ──────────────┐
   │  (repeatable retouch while    │ (S1-family invalidation rule fires)
   │   here: no time limit, no     │
   │   touch-count limit)          ▼
   │                          INVALIDATED (terminal)
   │  (respected + relevant reaction
   │   swing confirms — see §2.1)
   ▼
REACTION_SWING_CONFIRMED
   │
   ▼
RETIRED (terminal — no further re-touch trades from this POI)
```

Key rules:
- **Pine's SPENT is not S1's terminal state.** S1 freezes its own snapshot at first qualifying impact and continues tracking the frozen `[zb, zt]` independently of what Pine does to the live object afterward.
- **First impact ≠ one-shot.** While `IMPACTED_UNRESOLVED`, the same POI may be re-touched and re-traded indefinitely — no time decay, no touch-count cap.
- **Two, and only two, ways out:** `INVALIDATED` (failed per family-specific rule) or `RETIRED` (succeeded — produced its relevant reaction swing). These are different concepts and must be logged/journaled distinctly.
- **Relevant reaction swing:** for a bullish POI, the confirmed Swing Low that forms from its respected reaction; for a bearish POI, the confirmed Swing High. Uses the same swing-confirmation algorithm as the ported engine, on the POI's own timeframe.
- **Family-specific invalidation** (never a universal rule):
  - OB/RB: structural stranding rule (mirrors Pine's own OOB/ORB stranding geometry).
  - FVG/VI: close-through invalidation (mirrors Pine's own OFVG/OVI close-through geometry — continuation-type only, `origin==0`), in addition to structural stranding.
- **Overlapping/clustered POIs invalidate independently.** One member reaching `INVALIDATED` or `RETIRED` does not affect other members of the same cluster; the cluster/opportunity survives as long as at least one member is not terminal.

### 2.1 Frozen S1 POI Snapshot (per activated POI)
`SourcePOIID, WeeklyOpportunityID, PoiClusterID, Timeframe, POIFamily, POITypeAtActivation, Direction, Zb, Zt, CreationTime, TriggerTime, EligibilityTime, FirstImpactTime, CurrentS1LifecycleState, RetouchCount, RelevantReactionSwingType, RelevantReactionSwingPrice, RelevantReactionSwingConfirmationTime, InvalidationReason, RetirementReason, RetirementTime`

---

## 3. Directional Control Model

Scoped **per narrative** (per originating Weekly opportunity's own contest between its activating POI and a counter-POI) — **not** a system-wide gate. Section 10/11 concurrency (multiple simultaneous Weekly BUY+SELL streams, simultaneous opposite positions) is untouched by this model; Control only decides whether a *specific* counter-move graduates from "failed pullback" into "the new controlling direction" for that one narrative thread.

```
BUY_CONTROL
   │ (counter-direction Old/Aggressive POI reached)
   ▼
[contested] ──── POI invalidated ────────────► stays BUY_CONTROL (counter-POI failed)
   │
   └─ POI respected + relevant reaction swing confirmed
            │
            ▼
      SELL_CONTROL  (counter-POI now RETIRED — see §2)
            │ (relevant swing confirms in SELL's own direction,
            │  but no valid bullish In-Favor/Aggressive-In-Favor
            │  POI has been reached yet)
            ▼
        NEUTRAL  (SELL=off, BUY=off, waiting)
            │ (valid bullish POI reached + respected per normal rules)
            ▼
      BUY_CONTROL
```

Rules:
- A confirmed swing terminates the current phase; it does **not** by itself activate the opposite direction (`Stop SELL ≠ Start BUY`).
- The opposite direction requires its own valid POI/location under the normal Weekly→H4→M5 rules.
- Control state, source POI, and control swing are journaled (`ControlStateBefore/After/Reason/SourcePOIID/SwingType/Price/Time`).

---

## 4. POI Clustering (same rule at Weekly AND H4 level)

Two or more simultaneously-valid, same-direction POIs are **one** trading stream, not N:
- **Trigger for clustering: any overlap at all** — geometric price overlap, OR (derived, confirmed by analogy — see §12 decision log item D1) simply being simultaneously valid under the same parent, even without price overlap. In both cases: one cluster, one opportunity/setup, one trade search.
- Members remain individually tracked (§2's lifecycle is per-member). The cluster/opportunity/setup survives as long as ≥1 member is not terminal.

This applies identically to: multiple Weekly POIs forming one WeeklyOpportunity, and multiple H4 POIs forming one H4Setup (no concurrent H4Setups from simultaneously-valid H4 POIs under one Weekly opportunity — they cluster into one).

---

## 5. Hierarchy & ID Model

```
WeeklyOpportunity (BUY or SELL; independent — multiple, even opposite-direction, coexist)
 └─ SupportingPOI[]        (cluster members, §2 lifecycle each)
 └─ H4Setup[]               (sequential per retouch/interaction; one live cluster at a time)
     └─ SupportingH4POI[]   (cluster members, §2 lifecycle each)
     └─ M5Attempt[]         (sequential only — never concurrent within one H4Setup)
         └─ Order/Trade
```

IDs: `WeeklyOpportunityID, PoiClusterID, WeeklyPoiID (SourcePOIID), H4SetupID, H4PoiID, M5AttemptID, PendingOrderID, TradeID`. Every trade traces: `Trade → M5Attempt → H4Setup → WeeklyOpportunity → source POI(s)`.

- One WeeklyOpportunity can generate many H4Setups over its life (`Section 26`), including from repeated retouches of the same still-`IMPACTED_UNRESOLVED` Weekly POI (`WeeklyRetouchNumber` journaled).
- One H4Setup can generate many M5Attempts (sequential; SL → re-entry while parent valid, no arbitrary cap).
- **+3R does NOT re-arm the same H4Setup.** A fresh H4 POI impact is required to start a new H4Setup.
- H4Setup runs strictly sequential M5Attempts (no concurrent attempts within one setup).

---

## 6. Weekly Opportunity Lifecycle

```
Dormant → Active (on qualifying Weekly POI impact, §2)
        → generates H4Setup(s) over time (incl. repeated retouches)
        → Terminated when ALL cluster members reach INVALIDATED or RETIRED
          with no remaining live member (no other independent trigger terminates it —
          not time, not a trade's W/L, not Pine SPENT)
```

Weekly opportunity direction is fixed at activation (frozen POI snapshot, §2.1 — e.g. an activating AIFOB stays recorded as AIFOB in this opportunity's lineage even if Pine later promotes the live object to IFOB).

---

## 7. H4 Setup Lifecycle

Two routes to Impacted (mirrors OB engine's IFOB/AIFOB vs AOB/AIFOB split):

- **Route A (Confirmed/In-Favor):** relevant H4 swing breaks → H4 MSS → H4 In-Favor POIs (IFOB/IFVG/IRB/IVI) watched → impact → M5 activated.
- **Route B (Aggressive):** pre-MSS → H4 Aggressive POIs (AOB/AFVG/ARB/AVI, and pending AIFOB/AIRB) watched → impact → M5 activated before confirmed MSS.

**Protected swing** (structural invalidation reference): the *same* swing reference the POI itself was created from internally (`lastSWLidx`/`swlIdx` or `lastSWHidx`/`swhIdx`, whichever the Pine creation function used for that POI) — not a separately-chosen "most recent swing." Same rule for Route A and Route B, Weekly and H4.

**Violation rule:** any live tick where Bid (protected low) or Ask (protected high) trades ≥0.5 pip beyond the protected level counts immediately — no candle-close wait, no leniency, first qualifying tick ends it.

On violation: cancel pending M5 orders for that H4Setup, terminate the H4Setup, do **not** touch the parent WeeklyOpportunity (it may spawn a new H4Setup later).

On all supporting H4 POIs reaching terminal (§2): same cancel/terminate behavior, parent WeeklyOpportunity untouched.

---

## 8. M5 Execution Engine

```
H4 POI impact
  → identify relevant M5 swing (Swing High for BUY entry, Swing Low for BUY SL — mirrored for SELL)
  → place dynamic stop order (Buy Stop @ Swing High / Sell Stop @ Swing Low)
  → SL = swing ± spread-based buffer (current spread's distance beyond the swing)
  → track: as a newer relevant M5 swing forms before trigger, cancel/move the order to it
  → on trigger: SL/TP recalculated from ACTUAL fill price (slippage/gap-safe, true 3R preserved)
  → TP = Entry ± 3 × (Entry − SL)   [pure price distance, no commission adjustment]
  → on SL: if parent H4Setup + WeeklyOpportunity still valid → new M5Attempt on newest relevant swing (sequential, not concurrent)
  → on TP (+3R): H4Setup does NOT re-arm; requires a fresh H4 POI impact
```

Entry does not need to trigger inside the H4 POI's physical box — continued thesis validity governs, not physical containment at trigger instant.

---

## 9. Risk & Execution Parameters (confirmed)

| Parameter | Rule |
|---|---|
| Position sizing | Fixed % of account **balance** per trade (ignores floating P&L on other open positions) |
| M5 SL buffer | Spread-based — SL placed the current spread's distance beyond the entry swing |
| Protected-swing violation | Any live tick ≥0.5 pip beyond the protected level (Bid for lows, Ask for highs), immediate |
| TP | 3R, pure price distance, recalculated from actual fill price |
| Max simultaneous positions | No cap — any independently-valid setup per the rules may trade |
| Account-level risk governor (daily/weekly loss caps, total concurrent risk %) | **None for MVP** — explicitly deferred, add later without touching core logic |
| Spread filter (reject entry on wide spread) | **None for MVP** — not filtered; `SpreadAtEntry` is journaled for later analysis, not acted on |
| Manual intervention | EA respects any manual close/modify of its own orders/positions, logs `MANUAL_INTERVENTION_DETECTED` with full context, does not recreate/fight it |
| Slippage / gap-through fill | SL/TP recalculated from actual fill price, not the originally requested level |
| Time/session filters | **Explicitly deferred** — none implemented yet; will be added later per Section 15 of the master prompt. Nothing in the current build should assume time-based invalidation. |

---

## 10. Concurrency Model

- Multiple independent WeeklyOpportunities coexist freely, including simultaneous opposite directions (BUY stream + SELL stream).
- Simultaneous opposite-direction positions allowed — a valid opposite signal is never rejected merely because the opposite position is already open.
- Within one WeeklyOpportunity: H4 POIs cluster into one live H4Setup (§4) — no concurrent H4Setups from simultaneously-valid H4 POIs.
- Within one H4Setup: M5Attempts are strictly sequential — never concurrent.
- No global position cap; every independently-valid signal may trade.

---

## 11. Journal / Audit Requirements

Three CSV exports per run: `S1_TradeSummary_<run>.csv`, `S1_OpportunitySummary_<run>.csv`, `S1_EventLog_<run>.csv`, plus an optional human-readable debug log. Full column lists per the master prompt Sections 33–36, extended with the Directional Control fields from Section 23 of that document (`ControlStateBefore/After/Reason/SourcePOIID/SwingType/Price/Time`) and POI-lifecycle fields from §2.1 above (`PoiRetouchNumber`, `PoiS1LifecycleState`, `PoiRetirementReason/Time`, `PoiInvalidationReason`). UTC internally; export/display timezone configurable.

Export mechanism: cAlgo's supported file-write path (`Environment.GetFolderPath` + a fixed subfolder under the account data directory, the only sandbox-safe location cBots can reliably write to) — exact path confirmed in the implementation notes once built, since this is a platform-mechanics detail rather than a strategy rule.

---

## 12. Confirmed Decision Log

| # | Question | Answer |
|---|---|---|
| RB direction | Translate raw-wick or hunt-direction? | Use Pine's raw `.bullish` field as-is, no translation |
| AIFOB/AIRB promotion | Does S1 snapshot follow live promotion? | No — frozen at activation, historical identity never rewritten |
| Same-bar create+impact | Valid activation? | Yes, including dual-action/outside-bar cases |
| FVG/VI close-through in a cluster | Kills whole opportunity or just that POI? | Just that POI (§2, §4) |
| Old POI re-impact | One-shot or repeatable? | Repeatable — resolved fully by the unified lifecycle (§2) |
| Old-POI kill rule | What ends the repeatable thesis? | Unified lifecycle §2: INVALIDATED or RETIRED (superseded my earlier MSS/close-through proposal) |
| Directional Control scope | Global gate or per-narrative? | Per-narrative (§3); Section 10/11 concurrency untouched |
| In-Favor/AIF POI lifecycle | Same as Old/Aggressive, or Pine-only? | Same unified lifecycle (§2) — not a separate model |
| Position sizing | Basis? | Fixed % of balance |
| M5 SL buffer | Exact rule? | Spread-based |
| Protected-swing violation | Exact mechanics? | Any live tick ≥0.5 pip beyond level, Bid/Ask, immediate |
| POI clustering | Overlap threshold? | Any overlap at all |
| Protected swing selection | Which swing exactly? | Same swing reference the POI was created from internally |
| M5 concurrency within one H4Setup | Sequential or parallel? | Sequential only |
| Post-3R H4Setup reuse | Re-arm or new setup? | Requires a fresh H4 POI impact |
| H4Setup concurrency within one WeeklyOpportunity | Parallel or clustered? | Clustered into one (§4) |
| Weekly-level analog of H4 clustering | D1 — non-overlapping same-direction Weekly POIs | Derived by direct analogy to the H4 answer: cluster into one WeeklyOpportunity, not confirmed with a fresh question — flagged for correction if wrong |
| Max simultaneous positions | Cap? | No cap |
| Account risk governor | Daily/weekly loss caps now? | None for MVP |
| Spread filter | Reject wide-spread entries? | No — journal only |
| Slippage/gap fill | Recalc SL/TP from actual fill? | Yes |
| Manual intervention | Fight or respect? | Respect, log, don't recreate |
| 3R commission basis | Price-only or commission-adjusted? | Price-only (derived directly from Section 23's stated formula) |

---

## 13. Explicitly NOT Yet Implemented (by design, confirmed deferred)

- Time/session trading-window filters (Section 15) — coming later.
- Account-level risk governor (daily/weekly loss caps, total concurrent risk ceiling).
- Spread-based entry rejection.
- Persistence/restart reconciliation is designed for (stable IDs + comment/label tagging on live orders) but the exact serialization mechanism will be finalized during implementation and noted in the build's implementation log.
