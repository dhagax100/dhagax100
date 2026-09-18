# Build order tracker (SPEC.md §36)

Lock each stage before starting the next. Status reflects this repository
only (see `docs/PROJECT_SCOPE.md` for why `dhagax100/dhagax100`'s existing
pine/mq5/ctrader files are out of scope here).

| # | Stage | Status | Notes |
|---|-------|--------|-------|
| 1 | Confirm the native Weekly structure and OB engine | **Done — verified** | Swing detection, MSS, and the full IFOB/AOB/AIFOB/OOB/SPENT state machine are implemented in `locked/Weekly_and_4h_baseline_locked.txt` (`ObZone` type, `addOB`/`promoteNativeWaitingAOB`/`tryBull*`/`tryBear*`). Matches §1–4. |
| 2 | Add exact 1m Weekly trigger, eligibility and impact timing | **Done — verified** | `h4_childEventTime`, `h4_childFirstTouch`, and the live eligibility watcher resolve exact 1m timestamps via `request.security_lower_tf`. Matches §6–8. |
| 3 | Verify Weekly tables, visuals, focus and replay | **Partially verified** | `InpFocusOB`, `InpReplayUpTo`/`useReplay`/`skipBar`, and a Weekly table exist and were located in code. Not yet independently proven causal per §29 (i.e. that replay filters computation, not just drawing) — needs a dedicated trace, not just presence-of-feature confirmation. |
| 4 | Implement the Weekly direction-control state machine | **Implemented in Python (`reference/weekly_control_engine.py`), 2026-09-16** | Absent from the locked mq/pine files (see 2026-09-15 audit below), but now built as a standalone Python module per §9–16 (trend BULLISH/BEARISH/UNDEFINED, trade-control BUY_ONLY/SELL_ONLY/BOTH/NONE), reusing `WeeklyOBEngine` unmodified and driving it week-by-week. Outputs `weekly_control_ledger.csv`/`weekly_control_events.csv`/`weekly_control_report.txt` with 6 documented interpretive decisions. Not yet independently re-verified against locked-mq/pine semantics — this is a fresh implementation, not an audit of existing code. |
| 5 | Define immutable Weekly-to-H4 handoff records | **Partially present in Python** | `full_viewer.py` attaches `parent_weekly_id` (from `weekly_control_ledger.csv`'s `controlling_zone_id`) to every drawn H4 OB — the parent-POI linkage §17 requires. Control-state-at-creation/at-impact and a data-quality-status field are not yet modeled as a formal immutable record; still gaps against §17's full field list. |
| 6 | Display Weekly POIs correctly on H4 | **Done — verified (locked mq/pine)** | `InpShowWeeklyImpactOnH4` and Weekly-on-H4 drawing logic present. Reproduced in the Python/Pine reference too (`weekly_ob_generator.write_ob_pine`'s `onWeekly or onH4` gate). |
| 7 | Confirm the native H4 structure and POI engine | **Done — verified (locked mq/pine)** | Present in both locked files. Reproduced in Python as `h4_ob_engine.py`/`full_viewer.py` (native 4H bars via `WeeklyOBEngine` with `origin_gap_window=None`, chart-verified grid anchor `--h4-anchor-hour=1`). |
| 8 | Connect Weekly control permissions to H4 opportunity hunting | **Implemented in Python, 2026-09-16** | `full_viewer.py` authorizes a drawn H4 OB only if `h4.permits(control_at_impact, z.bullish)` — i.e. its direction matched the Weekly control state active at its exact impact time. Being verified OB-by-OB against the real TradingView chart, one Weekly control window ("leg") at a time; zone #3's SELL_ONLY window (10 authorized OBs) is the current one under review. |
| 9 | Confirm exact 1m H4 event timing | **Done — verified (locked mq/pine)** | Same mechanism as stage 2, confirmed present in `4h_and_5m_baseline_locked.txt` too. |
| 10 | Define immutable H4-to-5m handoff records | **Partially present in Python** | `five_bso_engine.py` reads `h4_ob_ledger.csv`'s `authorized`/`parent_weekly_id`/side/bottom/top and impact time as its handoff input, but this is not yet formalized as an explicit immutable-record type; still needs a field-by-field audit against §19. |
| 11 | Implement the complete 5m BSO process | **First Python version implemented, 2026-09-16 — NOT yet chart-verified** | `reference/five_bso_engine.py` implements resting swing, candidate arming/replacement, the entry race vs invalidation, structural SL and fixed 3R TP per §20-24. Explicitly not yet implemented: break-even (§25), post-SL re-entry (§27), completed-H4-close invalidation (only 1m far-boundary breach checked so far), MFE/MAE (§34). First test run on zone #3's window: 9 `ENTERED`, 1 `H4_OB_BREACHED`. This is a separate, unaudited implementation from the locked-mq/pine stage 11 row below — see the 2026-09-15 audit for that file's own status. |
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
