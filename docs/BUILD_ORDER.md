# Build order tracker (SPEC.md §36)

Lock each stage before starting the next. Status reflects this repository
only (see `docs/PROJECT_SCOPE.md` for why `dhagax100/dhagax100`'s existing
pine/mq5/ctrader files are out of scope here).

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | Confirm the native Weekly structure and OB engine | **Carried over** | Present verbatim in `locked/Weekly_and_4h_baseline_locked.txt` (swing detection, MSS, IFOB/AOB/AIFOB/OOB/SPENT state machine). Needs re-verification as *this repo's* starting point, not re-implementation. |
| 2 | Add exact 1m Weekly trigger, eligibility and impact timing | **Partially carried over** | The locked file already resolves 1m-child timing for H4 eligibility/impact (`h4_childEventTime`, `h4_childFirstTouch`, live eligibility watcher). Weekly-level exact-1m trigger/eligibility/impact timing needs to be confirmed present with the same rigor — not yet audited in this repo. |
| 3 | Verify Weekly tables, visuals, focus and replay | **Not yet audited here** | Locked file has `InpFocusOB`, `InpReplayUpTo`/`useReplay`, and a Weekly table toggle. Needs a pass against SPEC.md §29–31 acceptance criteria specifically. |
| 4 | Implement the Weekly direction-control state machine | **Not started** | SPEC.md §9–16 (trend state, trade-control state, opposing-POI encounter/gain/lose control, no-control state) is not visible in either locked file as inspected so far. This is the next concrete implementation task. |
| 5 | Define immutable Weekly-to-H4 handoff records | **Partially present** | The locked file already links H4 OBs to a Weekly setup conceptually (W1→H4 cascade table, `InpFocusWeeklySetupID`), but SPEC.md §17's full immutable-record field list (control state at creation, at impact, etc.) is not yet confirmed to be fully modeled. |
| 6 | Display Weekly POIs correctly on H4 | **Carried over** | `InpShowWeeklyImpactOnH4` and related drawing logic present in the locked file. |
| 7 | Confirm the native H4 structure and POI engine | **Carried over** | Present in both locked files. |
| 8 | Connect Weekly control permissions to H4 opportunity hunting | **Blocked on stage 4** | Cannot wire this until the direction-control state machine (stage 4) exists. |
| 9 | Confirm exact 1m H4 event timing | **Carried over, needs audit** | See stage 2 note — H4-side 1m timing machinery exists; needs a dedicated correctness pass against §19. |
| 10 | Define immutable H4-to-5m handoff records | **Not yet audited** | `4h_and_5m_baseline_locked.txt` needs inspection specifically for this. |
| 11 | Implement the complete 5m BSO process | **Present in `4h_and_5m_baseline_locked.txt`, not yet audited against §20–22** | |
| 12 | Implement SL, 3R TP and H4 break-even | **Present in `4h_and_5m_baseline_locked.txt`, not yet audited against §23–25** | |
| 13 | Implement post-SL re-entry | **Not yet audited** | §27. |
| 14 | Implement alerts | **Not started** | §32's full alert catalog is not present in either locked file (they are display/table-oriented, not `alertcondition`/`alert()`-driven). |
| 15 | Implement causal replay | **Partially present** | `useReplay`/`InpReplayUpTo` exist; needs a rigorous audit against §29 (compute-time filtering, not just draw-time hiding). |
| 16 | Build the external 1m backtester | **Not started in this repo** | The handoff describes a *separate* Python `weekly_ob_generator.py` for this purpose, which is not included here per the chat-start-only scope. A backtester for *this* repo's engine has not been started. |
| 17 | Compare indicator and backtester event by event | **Not started** | Depends on 16. |
| 18 | Daily → H1 → 5m (System B) | **Explicitly deferred** | Per SPEC.md §1/§18, do not invent its narrative. |
| 19 | Execution and position-sizing rules | **Explicitly deferred** | Per SPEC.md §38 (SPECIFICATION_PENDING). |

## Next concrete action

Audit `locked/Weekly_and_4h_baseline_locked.txt` and
`locked/4h_and_5m_baseline_locked.txt` line-by-line against SPEC.md §1–8 and
§17–25 to produce a precise compliance/gap report, then implement the Weekly
direction-control state machine (stage 4) as the first genuinely new module,
since stages 1–3 and 6–7 already exist in the locked sources and stage 4 is
the first hard blocker for everything downstream (stage 8+).
