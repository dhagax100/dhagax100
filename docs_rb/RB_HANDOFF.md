# RB Trading System Handoff — FXCM EURUSD, 2026 data

**Purpose:** parallel project to `docs/TRADING_SYSTEM_HANDOFF.md`, same discipline: give this file to whoever continues the work; it must continue from the current state, not redesign or silently "fix" anything.

## 1. What this is

Same architecture as the OB project (`reference/` + `docs/`), same EURUSD 2026 1-minute CSV, same Weekly control-gate engine -- but for RB (Rejection Block) POIs instead of OB. Only the zone-construction rules differ.

RB's construction rules come from `RB_Indicator_v1.pine` (a standalone TradingView diagnostic the user supplied, confirmed with them before it was written): an RB zone is the wick of a single swing-pivot candle, not a scanned pick. See `reference_rb/weekly_rb_generator.py`'s module docstring for the full rule set (IRB/ARB trigger moments, anchor-candle rule, bull/bear-by-raw-wick-type, near/far stranding) -- copied there almost verbatim from that pine file's own header comment, which is the source of truth for these rules.

## 2. Session update — 2026-09-19 (first deliverable: Weekly RB engine)

**Built `reference_rb/weekly_rb_generator.py`.** Structure:

- **Swing/MSS detection is copied verbatim from `weekly_ob_generator.py`'s `WeeklyOBEngine`** (`event_time`, `high_first`, `add_event`, and `process()`'s own body) -- not reimplemented, not approximated. Verified directly: `weekly_rb_swings.csv` and `weekly_ob_swings.csv` are byte-identical (`diff` empty) on the same input CSV -- same 10 swing highs, 10 swing lows, 2 MSS-up, 2 MSS-down.
- **RB zone construction replaces OB's scanning-loop origin selection** (`best`/`best_ifob_origin`) with the direct-wick construction from the pine spec: for a swing high, top=high, bottom=max(open,close); for a swing low, bottom=low, top=min(open,close). No "best candidate in a range" search -- the anchor candle is always the known swing-pivot candle itself.
- **IRB** (mirrors IFOB): created at the exact same call site OB's `add_ifob` fires from (inside `consume_break`, when a break confirms and `last_h`/`last_l` -- the opposite reference swing -- is available), anchored on that opposite swing. Delayed eligibility: armed when the NEXT same-direction swing confirms (identical direction convention to OB's own `finish_events_and_lifecycle`).
- **ARB** (mirrors AOB): created at MID-ARM (`try_bull_arb`/`try_bear_arb`, called from `mid_arm`, same reference-validity gate as `try_bull_aob`/`try_bear_aob` -- the armed swing must not have been violated since). Immediate eligibility, no promotion step -- RB has no AIFOB-style pending object, since nothing needs to be "picked" later.
- **Lifecycle**: wick impact (once eligible) + stranding only, no close-through rule. IRB strands far-side (mirrors IFOB), ARB strands near-side (mirrors AOB). An already-stranded (ORB) zone can still later be impacted; it can never re-strand. Same "resolve same-bar impact-vs-strand by exact M1 timestamp, earlier wins" ordering already used by OB.
- **Deliberate precision upgrade, flagged not hidden:** the standalone pine diagnostic only checks impact/stranding at week-bar (H/L) granularity, since live Pine execution has no access to sub-bar 1-minute data. This Python engine upgrades that to exact M1 precision (`first_touch`, M1-level strand-event ordering), matching the "exact 1m event clock" standard used throughout the OB side of this project. The RB *construction* rules (which candle, which type, which side strands) are unchanged from the pine spec -- only the impact/strand timing precision is upgraded.

**Not yet ported (first deliverable was explicitly scoped to "weekly engine, RB zones, impact lines, weekly RB focus toggle and table" only):**
- H4 cascade, 5m BSO entries, Weekly direction-control state machine (all exist for OB in `weekly_control_engine.py`/`h4_ob_engine.py`/`five_bso_engine.py` and are expected to be reused/adapted the same way, once the Weekly RB layer itself is chart-verified).
- The cross-timeframe `impact_x_<id>` watcher-variable mechanism OB's Pine viewer uses to keep impact lines correctly time-bucketed per chart timeframe -- the current `weekly_rb_viewer.pine` draws each RB box's right edge as a static resolved timestamp, sufficient for the Weekly chart but not yet extended to H4/5m.

**Verified so far (mechanical, not yet chart-confirmed by the user):**
- Ran clean against the full EURUSD 2026 CSV: 37 weeks, 10 swing highs, 10 swing lows, 2 MSS-up, 2 MSS-down (all matching OB exactly).
- 13 RB zones created: 6 ARB, 7 ORB (stranded), 0 IRB still pending, 0 zones showing literal "SPENT" as their ledger type (matches OB's own convention: a SPENT zone displays under its pre-spent type, e.g. an impacted ARB still reads "ARB" in the ledger's `type` column -- `pre_spent_state` carries the display lineage, same as OB's `status()`).
- Pine output (`weekly_rb_viewer.pine`) is 59 lines, array-packed from the start (one statement per field, one runtime loop to draw) -- deliberately avoiding the CE10295/CE10205/CE10013 class of errors already documented in `docs/TRADING_SYSTEM_HANDOFF.md`'s OB history, rather than hitting them and fixing them after the fact.
- **Not yet chart-verified against the real TradingView chart.** No RB zone's exact box position, type, or lifecycle has been checked against a chart screenshot yet -- this is the immediate next step before trusting any of the 13 zones above.

## 3. Run order (current)

```
cd reference_rb
python3 weekly_rb_generator.py <path-to-EURUSD_m1_BidAndAsk.csv>
```

Produces, next to the CSV:
- `weekly_rb_ledger.csv` -- one row per RB zone, full audit trail (anchor candle OHLC, trigger/eligible/impact timestamps, type, side, box coordinates)
- `weekly_rb_swings.csv` -- swing/MSS facts (identical to `weekly_ob_swings.csv` on the same input)
- `weekly_rb_viewer.pine` -- paste into TradingView Pine Editor, attach to EURUSD/FXCM Weekly chart
- `weekly_rb_report.txt` -- coverage and lifecycle counts

## 4. Next concrete step

Chart-verify the 13 Weekly RB zones above (box position, type IRB/ARB/ORB, side) against the real TradingView chart, the same candle-by-candle discipline the OB project used from its own first Weekly deliverable onward. Do not proceed to H4/5m until this passes.

## Session update — 2026-09-20 (gate 1 recorded; H4 RB layer + 5m entries added)

**User-supplied claims, both verified true against the actual data before building anything:**
1. RB zone #2 (Weekly, ARB, bearish, top=1.20825, bottom=1.18609) is the first RB ever impacted, chronologically. Trigger, eligible and impact are all the same minute: 2026-02-09 15:07 Riyadh. Confirmed directly against `weekly_rb_ledger.csv`.
2. Trend context (2025 carryover -- not derivable from this 2026-only dataset, user-supplied): Weekly trend was UP at this point, making this a COUNTERTREND SELL_ONLY start -- same mechanism as the OB side's own zone #1 (trend and control are independent, SPEC.md SS9).
3. The zone dies at the containing week's own close: week 2026-02-09 01:00 -> 02-16 01:00 Riyadh closes at 1.18722, which is `>= zb` (1.18609) -- the same Weekly-close-body-inside/through POI-breach rule (SPEC.md SS14) already used throughout the OB side. Confirmed directly against the week's own O/H/L/C.

**Gate 1 recorded** (`build_manual_rb_gates()` in `reference_rb/full_rb_viewer.py`): SELL_ONLY (RB zone #2) from 2026-02-09 15:07 to 2026-02-16 01:00 Riyadh, then NONE through the end of the dataset (09-11 22:05) -- no further RB gates built yet, out of scope for this delivery.

**New file: `reference_rb/full_rb_viewer.py`** -- RB counterpart of `full_viewer.py`. Reuses, completely unchanged, everything from the OB side that turned out to be genuinely generic (confirmed by reading each function's body, not assumed):
- `h4_ob_engine.aggregate_h4()` / `.permits()` -- pure minute/control math, no Zone-type coupling.
- `five_bso_engine.aggregate_5m()` / `.structural_invalid_at()` / `.run_bso_chain()` / `.ledger_row()` / `.LEDGER_FIELDS` -- every one only ever touches `z.bullish`, `z.zb`, `z.zt`, `z.id`, `z.state`, `z.pre_spent_state` -- `RBZone` has all six with identical names/meanings, so these ran against RB zones with zero modification.
- `full_viewer.build_bso_extra_lines()` / `.manual_control_and_parent_at()` / `.pine_time()` / `.pine_text()` -- same reasoning.

New/RB-specific: `build_manual_rb_gates()` (gate 1 only) and `build_h4_rb_extra_lines()` (RB's own H4 layer -- simpler than OB's `build_h4_extra_lines()` since `RBZone` already stores its own `trigger_time`/`eligible_time`/`impact_time` directly, no OB-style fallback-derivation helpers needed).

**Real bug caught and fixed before shipping**: the H4-window scoping first used `gates[-1][1]` (the trailing open-ended NONE gate's end, effectively the whole rest of the dataset) instead of gate 1's own end. Authorization itself was still correct regardless (a zone only gets authorized if its impact genuinely fell inside a real control gate), but the H4 swing/MSS label window was far too wide. Fixed to `gates[0][1]`.

**Toggles added, matching OB's exact pattern**: `Inspect one 4H RB only` / `H4 RB from last` (H4 table), `Inspect one 5m BSO only` / `5m BSO from last` (5m table) -- both reused verbatim from the OB side's own toggle mechanism.

**Verified against the regenerated output:**
- 6 H4 RBs authorized inside gate 1's window, all SELL, all parent Weekly RB #2 -- matching the claim exactly (2026-02-10 through 02-16).
- 10 total 5m entry attempts across those 6 H4 RBs (including re-entry chains): 7 ENTERED, 3 H4_OB_BREACHED.
- Pine output (`full_rb_viewer.pine`) is 243 lines, array-packed throughout -- same CE10295/CE10205 avoidance discipline as every other layer in this project.

**Run order:**
```
cd reference_rb
python3 full_rb_viewer.py ../data/EURUSD_m1_BidAndAsk.csv
```
Produces (next to the CSV): `full_rb_viewer.pine`, `h4_rb_ledger.csv`, `five_bso_rb_ledger.csv`, plus the Weekly RB files as before.

**Not yet done**: gates 2+ (only gate 1 was in scope this round). No automated RB control engine yet (mirrors the OB project's own history -- hand-verify gate-by-gate first, automate later once the sequence settles). Not yet chart-verified against the real TradingView chart.

## Session update — 2026-09-20 (real DST bug in shared h4_ob_engine; RB wording cleaned up)

**Real bug found via RB chart verification, but the bug lives in the SHARED `h4_ob_engine.py` (reused unchanged from the OB project) -- see `docs/TRADING_SYSTEM_HANDOFF.md`'s own 2026-09-20 entry for the full root-cause writeup.** In short: the H4 grid anchor was a fixed UTC hour, verified once in September (EDT); user caught a real winter (EST) 4H boundary at 01:00 Riyadh where the old code predicted 00:00 -- a genuine 1-hour DST gap. Fixed to anchor on 17:00 NY-LOCAL time (DST-aware, matching the Weekly close hour), verified against both real chart boundaries directly.

This is fixed in the shared file, so both OB and RB inherit it automatically. Regenerated RB's gate 1 window: 4H bars 1130 -> 1120, H4 RBs computed 446 -> 449, authorized in gate 1's window **6 -> 5**, 5m entries 10 -> 8 (5 ENTERED, 3 breached) -- unlike the OB side, RB's counts DID change, since gate 1's window (Feb 2026) is entirely in winter/EST.

**RB wording cleanup** (user: "we should use RB everywhere for consistency... I have seen 4H OB breached in the table which is weird"): `five_bso_engine.py`'s shared, generic result dict uses `"H4_OB_BREACHED"` as a literal stage string, and `full_viewer.build_bso_extra_lines()` (also reused) hardcodes `"Weekly OB"`/`"4H OB"` as its own 5m table headers. Neither is RB-aware, and neither should be edited directly (both are still the OB project's real, correct wording). Added `rb_relabel()` / `rb_ledger_row()` / `RB_LEDGER_FIELDS` in `full_rb_viewer.py`: a thin, display-only remapping layer that renames `H4_OB_BREACHED` -> `H4_RB_BREACHED`, `h4_ob_*` CSV columns -> `h4_rb_*`, and patches the two hardcoded 5m table header strings -- applied only to RB's own output, never touching the shared OB functions. Verified: zero "OB" wording anywhere in the regenerated `full_rb_viewer.pine` or `five_bso_rb_ledger.csv` except one accurate doc-comment describing swing/MSS lineage.

**Run order unchanged**:
```
cd reference_rb
python3 full_rb_viewer.py ../data/EURUSD_m1_BidAndAsk.csv
```

## Session update — 2026-09-26 (all 34 gates walked and chart-verified; automated engine built and validated; 2026 dataset now fully closed out)

**Full 34-gate control history walked, gate by gate, from RB zone #2's first impact (2026-02-09 15:07 Riyadh) to the end of the 2026 CSV (2026-09-11 22:05 Riyadh)**, using the same discipline as the OB side's own closeout: raw M1/Weekly data first, chart screenshots second, code only once both agreed. All 34 gates are recorded in `build_manual_rb_gates()` in `reference_rb/full_rb_viewer.py`.

**Corrected mid-way through this sweep**: the parent-in-charge rule was wrong in its first form (last zone *created* on a side) and was replaced with the correct rule (last zone that actually *reacted* -- was impacted -- on that side). All 34 gates were re-derived under the corrected rule; two gates (2 and 7) had their recorded parent changed as a direct result.

**Automated cross-check built**: `reference_rb/weekly_rb_control_engine.py`, a from-scratch derivation of the same 34 gates straight from raw data, independent of the hand-typed table. Three real engine bugs were found and fixed during validation (a same-minute collision-detection blind spot, a tie-break ordering bug, and a missing third BOTH-resolution path for ordinary Weekly-close body-death), plus one genuine hand-table gap (gate 2's early NONE window, since the dataset starts mid-campaign with no prior-year direction available) and two 1-hour timestamp slips (zone #8's and #14's Weekly-close death times). **After all fixes, the automated engine matches all 34 hand-verified gates exactly, to the minute.** RB is the more heavily user-verified of the two POI systems and is the declared benchmark over OB wherever the two disagree (explicit user ruling, 2026-09-24).

**Full entry history reviewed, all 90 entries, start to finish** (RB zone #2's first impact through end of data):

- 22 wins (TP, +3.00R each), 68 losses (SL, -1.00R each). Win rate 24.4%.
- **Net: -2.00R over the full dataset** (2026-02-09 15:07 through 09-11 22:05 end of data).
- Side split: 47 SELL entries, 43 BUY entries -- both directions traded, unlike the OB side's dataset where every entry was SELL.
- 449 H4 RBs computed, 120 authorized (inside a real control gate), 150 5m entry attempts on those authorized RBs: 90 ENTERED, 59 H4_RB_BREACHED (zone breached before an entry trigger), 1 NO_ENTRY_IN_DATA (dataset ended first).

**2026 dataset now fully closed out.** Every control gate from RB zone #2's first impact to the last 1-minute bar in the CSV is verified: 34 gates, all reproduced automatically by `weekly_rb_control_engine.py`, all cross-checked against `h4_rb_ledger.csv`/`five_bso_rb_ledger.csv`. Final state at end of file: **control = BUY_ONLY** (parent RB zone #12, challenger #14 still alive but not in charge), no open or pending H4 RB carrying forward past the CSV's last minute.

**How to close out this RB/dataset and hand off cleanly, for whoever (or whichever future session) picks this up next:**
1. **Nothing needs to be "closed" in code** -- there is no open position, no armed zone, no pending RB at the end of the CSV. The engine's own state at the last processed minute already IS the terminal state (BUY_ONLY, zone #12 in charge). Nothing to flatten or cancel.
2. **When new data is appended** (a newer EURUSD CSV extending past 2026-09-11), don't reprocess from scratch and don't assume continuity is automatic: rerun the full pipeline (`weekly_rb_generator.py` -> `weekly_rb_control_engine.py` -> `full_rb_viewer.py`) against the new file end-to-end, since the locked engines are stateless recomputations over the whole file, not incremental. Then re-verify starting from this exact known-good terminal state (control=BUY_ONLY, parent #12, challenger #14, last event 2026-09-09 09:15) forward -- treat everything before 09-11 22:05 as already locked and don't re-litigate it, only chart-verify the new tail.
3. **This file (`docs_rb/RB_HANDOFF.md`) and `docs_rb/RB_RULES_LEARNED.md` are the continuity record.** A new session or new dataset picks up by reading them end to end, not by re-deriving any of gates 1-34 from raw data again.
4. **`full_rb_viewer.py` still runs on the hand-typed `build_manual_rb_gates()` table, not the automated engine's output** -- deliberate, mirrors the OB project's own "verify before wiring in" precedent. They match exactly, so switching later is a mechanical change, not a re-derivation, whenever it's wanted.
5. Still-open, unrelated to this closure: the OB-side phantom Sunday-reopen H4 candle and ~3-pip live-feed discrepancy (see `docs/TRADING_SYSTEM_HANDOFF.md`) apply equally here, since RB reuses the same shared H4/5m engines. Neither blocks calling the 2026 RB dataset closed.

**Run order unchanged**:
```
cd reference_rb
python3 full_rb_viewer.py ../data/EURUSD_m1_BidAndAsk.csv
```
