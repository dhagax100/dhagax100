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
