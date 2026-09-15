# Build order tracker (SPEC.md §36)

Lock each stage before starting the next. Status reflects this repository
only (see `docs/PROJECT_SCOPE.md` for why `dhagax100/dhagax100`'s existing
pine/mq5/ctrader files are out of scope here).

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | Confirm the native Weekly structure and OB engine | **Done — verified** | Swing detection, MSS, and the full IFOB/AOB/AIFOB/OOB/SPENT state machine are implemented in `locked/Weekly_and_4h_baseline_locked.txt` (`ObZone` type, `addOB`/`promoteNativeWaitingAOB`/`tryBull*`/`tryBear*`). Matches §1–4. |
| 2 | Add exact 1m Weekly trigger, eligibility and impact timing | **Done — verified** | `h4_childEventTime`, `h4_childFirstTouch`, and the live eligibility watcher resolve exact 1m timestamps via `request.security_lower_tf`. Matches §6–8. |
| 3 | Verify Weekly tables, visuals, focus and replay | **Partially verified** | `InpFocusOB`, `InpReplayUpTo`/`useReplay`/`skipBar`, and a Weekly table exist and were located in code. Not yet independently proven causal per §29 (i.e. that replay filters computation, not just drawing) — needs a dedicated trace, not just presence-of-feature confirmation. |
| 4 | Implement the Weekly direction-control state machine | **Not started — confirmed absent** | Grepped both locked files for `BUY_ONLY`/`SELL_ONLY`/`BOTH`/`NONE`/trend-state: zero matches. §9–16 do not exist in either file. This is the first genuinely new module required. |
| 5 | Define immutable Weekly-to-H4 handoff records | **Partially present, gaps confirmed** | `ObZone` has no parent/child POI ID field and no data-quality-status field (checked the struct directly, lines 70–84). W1→H4 linkage exists structurally (cascade table, `InpFocusWeeklySetupID`) but not as the full immutable record §17 requires. |
| 6 | Display Weekly POIs correctly on H4 | **Done — verified** | `InpShowWeeklyImpactOnH4` and Weekly-on-H4 drawing logic present. |
| 7 | Confirm the native H4 structure and POI engine | **Done — verified** | Present in both locked files. |
| 8 | Connect Weekly control permissions to H4 opportunity hunting | **Blocked on stage 4** | Cannot wire this until the direction-control state machine exists. |
| 9 | Confirm exact 1m H4 event timing | **Done — verified** | Same mechanism as stage 2, confirmed present in `4h_and_5m_baseline_locked.txt` too. |
| 10 | Define immutable H4-to-5m handoff records | **Present, not yet field-audited** | `ObZone`/setup linkage exists (`candidate = array.get(obs, obIndex)` etc.); has not been checked field-by-field against §19's required list. |
| 11 | Implement the complete 5m BSO process | **Done — verified** | Full candidate chain, replacement (`WAIT RE-CANDIDATE`), and the entry race are implemented and match §20–22's described behavior (comments in the source explicitly cite the same rules, e.g. "Candidate #1 is ALWAYS the immediate opposite swing"). |
| 12 | Implement SL, 3R TP and H4 break-even | **Done — verified** | Explicit "Locked 3R target" comment, structural-stop search, and an "ADDITIVE H4-STRUCTURE BREAK-EVEN LAYER" block are present and match §23–25. MFE/MAE excluding the entry minute (§34) is also implemented (`tradeExcursions1m`). |
| 13 | Implement post-SL re-entry | **Present, not yet field-audited** | Re-candidate/re-entry code paths exist (`WAIT RE-CANDIDATE`) but haven't been checked against every §27 sub-rule (e.g. trade-attempt numbering, stop-pool origin). |
| 14 | Implement alerts | **Not started — confirmed absent** | Grepped both files for `alertcondition`/`alert(`: zero matches in either. §32's entire alert catalog is missing. |
| 15 | Implement causal replay | **Same gap as stage 3** | `useReplay`/`InpReplayUpTo`/`skipBar` exist but their causality (computed state, not just hidden drawings) is unverified. |
| 16 | Build the external 1m backtester | **Not started in this repo** | The handoff describes a *separate* Python `weekly_ob_generator.py` for this purpose, excluded from this repo's scope. No backtester exists yet for this repo's Pine engine. |
| 17 | Compare indicator and backtester event by event | **Not started** | Depends on 16. |
| 18 | Daily → H1 → 5m (System B) | **Explicitly deferred** | Per SPEC.md §1/§18. |
| 19 | Execution and position-sizing rules | **Explicitly deferred** | Per SPEC.md §38 (SPECIFICATION_PENDING). |

## Audit summary (2026-09-15)

Read both locked files in full and grepped for every spec-required mechanism
rather than trusting file/section names. Findings:

- **Solid and verified:** swing/MSS/OB state machine, exact-1m timing
  resolution (Weekly and H4 alike), the complete 5m BSO candidate/entry
  process, SL/3R-TP/break-even, MFE/MAE. These stages are genuinely done, not
  just "present."
- **Confirmed absent (zero grep matches, not just unexamined):**
  - The entire §9–16 Weekly direction-control state machine
    (BUY_ONLY/SELL_ONLY/BOTH/NONE, trend state, opposing-POI control
    transfer). Both locked files only produce OB state (IFOB/AOB/OOB/etc.),
    never a Weekly campaign-control decision.
  - The entire §32 alert catalog — no `alertcondition`/`alert()` calls
    anywhere.
  - §11's second breach mechanism: the locked stranding logic (`STRANDING ->
    OOB`, both files) uses the swing's wick price against the zone boundary —
    that is the *immediate structural swing breach*. There is no separate
    Weekly-candle-close-only POI-breach check. Only one of the spec's two
    independent breach mechanisms exists.
  - `ObZone` (the shared record type, both files) has no parent/child POI ID
    and no data-quality-status field, so §3's full POI record and §17's
    immutable handoff record are not fully modeled even where the underlying
    facts (times/prices) are computed correctly.

## Next concrete action

Implement the Weekly direction-control state machine (stage 4) as the first
new module, since stages 1–2, 6–7, 9, 11–12 are already done in the locked
sources and stage 4 is the hard blocker for everything downstream (stage 8+).
It should read the existing `ObZone` state/eligibility/impact facts already
computed by `locked/Weekly_and_4h_baseline_locked.txt` rather than
recomputing them, per SPEC.md §1 and §35.
