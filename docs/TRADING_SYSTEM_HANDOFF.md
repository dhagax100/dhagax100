# Trading System Handoff — FXCM EURUSD Multi-Timeframe Project

**Purpose:** Give this file and the requested companion files to another AI at the start of a new session. It must continue from the current state, not redesign or silently “fix” the system.

## 1. User and working style

- The user wants a visual, verifiable TradingView workflow first. They check drawings on a white chart: bullish candles blue, bearish candles black.
- The market is **EURUSD only**. The intended chart/feed is **FXCM EURUSD** (OANDA only as a separately validated feed).
- The user has M1 FXCM Bid/Ask CSV data and Python 3.14 on Windows. Their working folder is commonly `Desktop\ForexTesting`.
- Keep answers short and concrete. Do not claim a fix is correct without comparison against the chart/data.
- Do not jump from a visible discrepancy straight into code. First identify the exact source-candle, timestamps, boundaries and rule responsible.

## 2. Overall system being built

The intended trading system is a three-timeframe hierarchy:

1. **Weekly:** swing structure, MSS, POIs, directional control.
2. **H4:** POIs and structure under Weekly permission.
3. **5m:** execution structure, entries, SL, TP and re-entry logic.

The immediate project stage is only **Weekly Order Blocks (OBs)** using Python preprocessing of M1 data and a static Pine viewer. Do not add RB, FVG, VI, H4, 5m, trading, backtest, EA, risk or alerts until the Weekly OB reference is verified.

### Historical and live-data architecture (important)

The project uses two deliberately separate modes:

1. **Historical verification / chart drawing now:** The user has acquired historical FXCM EURUSD M1 Bid/Ask data outside Pine and supplies it as a CSV. Python performs the expensive M1 calculation outside TradingView, then generates a Pine file containing pre-calculated timestamps, prices, labels, lines, boxes and table values. TradingView is used to **visually inspect the pre-calculated result** on the FXCM chart without asking Pine to retain years of M1 arrays.
2. **Live operation later:** The final indicator must calculate new events from genuinely available real-time M1 data as bars arrive, then show/alert only newly confirmed information. A real-time lower-timeframe/Pine design is **not built or validated yet**. It must not be presented as working merely because the historical static viewer works.

The new AI must preserve this distinction. The Python/static-Pine route solves historical visualization and verification; it is not the final live engine. When the user is ready, design the live path so it follows the same verified rules, and validate it against the Python reference on overlapping data.

## 3. Authority and rules

### Locked / authoritative

- `Weekly and 4h baseline locked(6).txt`: authoritative existing Weekly swing, MSS and OB implementation.
- `4h and 5m baseline locked(5).txt`: authoritative existing H4 structure, H4 OB and 5m execution implementation.
- Existing locked Weekly logic is the reference for Weekly OB calculation—not later informal explanations, screenshots or new display experiments.

### Not locked / not yet implemented

- RB, FVG and Volume Imbalance formulas and lifecycles.
- Protected-swing ownership, control conflict priority, detailed same-minute ordering, costs and final EA platform.
- Exact confirmation that the CSV timestamps and TradingView FXCM boundaries align. `--input-tz America/New_York` is being used in the current test command, but this still needs chart-by-chart verification.

## 4. Current implementation

### Core files

- `weekly_ob_generator.py` — current Python generator, Library version 9.
- `README_WEEKLY_OB_GENERATOR.txt` — run instructions, Library version 6.
- Generated in the same folder as the CSV after each run:
  - `weekly_ob_ledger.csv`
  - `weekly_ob_swings.csv`
  - `weekly_ob_viewer.pine`
  - `weekly_ob_report.txt`

### Input CSV schema

Required columns:

`Date, Time, OpenBid, HighBid, LowBid, CloseBid, OpenAsk, HighAsk, LowAsk, CloseAsk`

`TotalTicks` is optional. The current calculation uses **Bid** OHLC. Ask data is retained only for future execution work.

### Run command currently used

```bat
cd %USERPROFILE%\Desktop\ForexTesting
python weekly_ob_generator.py EURUSD_m1_BidAndAsk.csv --input-tz America/New_York --box-body-minutes 15
```

Close any generated CSV file in Excel before running again; Excel can lock it.

### What Python currently does

- Reads M1 Bid/Ask CSV with only the Python standard library.
- Aggregates scheduled Weekly bars using Sunday 17:00 `America/New_York` (DST-aware).
- Runs a Python transcription of the locked Weekly swing/MSS/OB engine.
- Creates a static Pine v6 viewer to draw its output.
- Draws swing highs as blue `▲`, swing lows as black `▼`, and MSS as blue/black `✕`.
- Draws non-rejected OB boxes and red vertical impact lines; rejected OBs stay ledger-only.

### Important distinction: engine range vs display range

The engine still creates and manages OBs using the locked Weekly origin body:

`min(Weekly open, Weekly close)` to `max(Weekly open, Weekly close)`.

An experimental **display-only** option was added:

- `--box-body-minutes 15` builds the displayed OB top/bottom from the **first observed 15-minute candle open** and **last observed 15-minute candle close** inside that selected Weekly origin.
- Those 15-minute candles are assembled from the available M1 rows. No missing minute is filled and no record is blocked.
- The ledger records engine boundaries and display boundaries separately, plus actual source times and row counts.
- This display experiment must not be mistaken for a validated OB rule. It can make the visible box differ from the engine’s impact/eligibility calculations.

## 5. Current unresolved problem

The user reports that impact endpoints/vertical impact candles that were correct in an earlier run now appear at the next Weekly candle or otherwise wrong. A prior attempted code change did **not** solve the user’s visible issue.

### What has been changed and why this remains unresolved

1. The system initially drew visual body boundaries from Weekly open/close.
2. Weekend gaps and missing M1 rows caused visual-body confusion. A 15-minute observed display-range experiment was introduced.
3. The Python engine stores the exact M1 touch time in `Zone.impact_time` when lifecycle processing identifies impact.
4. The viewer previously recomputed impact while writing Pine. That could fall through to a Weekly boundary; it was changed to return the stored `z.impact_time` first.
5. **The user says the visible behavior is still not fixed.** Treat that report as the current truth. Do not assert that stored-impact logic solved the actual chart issue.

### Most important next investigation rule

Do not make a general “gap fix” or change Week segmentation now. First investigate a single OB record at a time and collect evidence.

## 6. New single-OB inspection workflow

The latest generated Pine includes these TradingView settings:

- `Inspect one OB only` (toggle)
- `OB from last` (integer)

Use them as follows:

1. Turn **Inspect one OB only** on.
2. Set **OB from last = 1** to inspect the newest OB.
3. Set it to **2** for the next older OB, then 3, etc.
4. The viewer should show only that non-rejected OB’s box, impact line, origin-audit label and one table row.
5. Rejected OBs remain table-only under the existing locked visual convention.

For each OB, record in an error log:

| Field | Record exactly |
|---|---|
| Selection | `OB from last = n`, Pine table ID/type/side/status |
| Origin | Chart candle timestamp and raw M1/Weekly source candle |
| Boundaries | Engine bottom/top; display bottom/top; expected chart boundaries |
| Trigger / eligibility / impact | Table timestamps, exact observed M1 price and expected chart timestamp |
| Visual result | Box left/right, red line position, label position |
| Verdict | Correct / wrong; concise explanation; screenshot |

Do not modify the shared engine during this collection phase. After enough records are inspected, group discrepancies by cause (timestamp conversion, weekly aggregation, missing M1 data, display-range mismatch, lifecycle error, or Pine rendering error) and only then propose controlled fixes.

## 7. What another AI must do at the start of a continuation

1. Read this handoff completely.
2. Ask the user to attach the required files listed in section 9 if they are not already available.
3. Ask which exact `OB from last` number is currently being inspected and request one screenshot with the Pine table visible.
4. Compare the chart against the corresponding `weekly_ob_ledger.csv` row and raw M1 CSV rows before changing code.
5. Explain the evidence and likely cause first. Make only a narrowly scoped change approved by the user.
6. Validate Python syntax and generate outputs after each code change.
7. Update this handoff file before ending the session, including: date, what changed, exact command, tests run, current selected OB, observed results, unresolved problem, next action, and updated file versions.

### Required update block to append after every meaningful step

```md
## Session update — YYYY-MM-DD

- Current investigation: OB from last = ? / table ID = ?
- Evidence checked: [screenshots, ledger row, M1 timestamps]
- Change made: [none, or exact file/rule]
- Validation: [command and result]
- Result: [verified / not verified]
- Open issue:
- Next exact action:
```

Never remove old updates. Correct an error with a later update that states what was wrong.

## 8. Important facts and cautions

- The user found M1 export gaps around weekends. Example evidence included a Friday final row and a Sunday first available row many minutes later. Missing export rows must not be invented.
- The user explicitly asked not to show `DATA UNAVAILABLE` for the current display experiment. Do not use missing rows as an excuse to skip evidence collection, but do state precisely what rows are actually present.
- The red vertical lines in the Weekly Pine are impact lines, not box borders.
- A box’s left edge should remain tied to the selected origin Weekly candle unless the user explicitly approves a new display convention.
- A change to observed 15-minute visual boundaries can produce a mismatch between the box drawn and the locked engine’s body-based impact test. This is an unresolved design decision, not a fact to conceal.
- Do not use arbitrary historical OB numbers such as #872 as a required benchmark. They were legacy records and are useful only if the exact source data/session is reproduced.
- Known historical fixture references (only for later verification): #872 impact `2026-06-05 11:37`, `1.15351`; #877 eligible `2026-06-14 17:29`, `1.15922`, impact `2026-08-19 08:49`, `1.16357`; #878 trigger `2026-06-17 15:24`, `1.14987`, eligible `2026-07-14 08:30`, `1.14622`, impact `2026-07-30 09:48`, `1.15075`. Their time basis must be confirmed before treating them as a pass/fail test.

## 9. Files to attach to another AI

Always attach this handoff file first. Also attach or request these files:

1. **Current Python:** `weekly_ob_generator.py`.
2. **Current generated results:** `weekly_ob_ledger.csv`, `weekly_ob_swings.csv`, `weekly_ob_viewer.pine`, `weekly_ob_report.txt` from the exact run under discussion.
3. **Raw data:** the exact `EURUSD_m1_BidAndAsk.csv` used for that run. Do not substitute another export silently.
4. **Locked sources:** `Weekly and 4h baseline locked(6).txt` and `4h and 5m baseline locked(5).txt`.
5. **Evidence:** the TradingView screenshots for the selected OB and, if possible, screenshots/raw CSV rows around its origin, eligibility and impact minute.

If any item is unavailable, the other AI must ask for it rather than claim an exact comparison.

## 10. Future sequence after Weekly OB is trusted

1. Finish Weekly OB one-record-at-a-time verification and apply grouped fixes.
2. Lock the Python Weekly OB engine against the chart/feed.
3. Add Weekly control behavior and H4 integration according to agreed specifications.
4. Add 5m execution and verify with M1 resolution.
5. Define and add RB separately.
6. Define and add FVG separately.
7. Define and add Volume Imbalance separately.
8. Create a reference backtest with explicit ambiguity handling, then validate known 2025–2026 fixtures before the five-year run.
9. Build the EA only after the indicator/reference engine passes validation.

## Session update — 2026-09-14

- Current investigation: no OB has yet been validated with the new single-OB workflow.
- Latest change: added Pine inspection inputs `Inspect one OB only` and `OB from last`; Python generator Library version 9, README version 6.
- Validation completed: Python compilation and a synthetic generated-Pine check confirmed the inspection controls are emitted.
- Result: the workflow is available, but the earlier impact-endpoint issue is **not verified as fixed**.
- Next exact action: regenerate with the command in section 4, select `OB from last = 1`, and compare its Pine table row and chart drawing with the raw M1 rows before any calculation change.

## Session update — 2026-09-14 (handoff clarification)

- The handoff now explicitly distinguishes historical M1 pre-calculation → static TradingView visualization from the future real-time M1 indicator/alert engine.

## Session update — 2026-09-14 (Pine inspection syntax error)

- Error discovered: the generated Pine inspection-mode `if` statements had Python-style trailing `:` characters. TradingView reported `Extraneous input ':'`.
- Cause: generator formatting error only; no Weekly OB calculation or data was involved.
- Fix: removed the three trailing colons from generated Pine `if` statements.
- Validation required from user: regenerate the Pine file, paste it into TradingView, and confirm it compiles before starting OB-by-OB investigation.

## Session update — 2026-09-14 (AIFOB open-week rejection defect)

- Evidence reported: selected latest bullish AIFOB stays alive even though, during the still-open Weekly candle, price has gone below the AIFOB bottom and crossed the last swing low. The user expects a black MSS-down cross and AIFOB rejection at that M1 event.
- Root cause confirmed from locked Weekly source: M1 is currently an event-clock only. It resolves the timestamp of an already-valid Weekly event; it does not allow an open Weekly bar to create a Weekly MSS or alter AIFOB state. The Python reference copied that behavior by processing a Weekly bar as one completed unit.
- Consequence: the currently observed behavior is consistent with the locked implementation but not with the user's newly required open-week M1 behavior.
- Proposed extension to lock before implementation: while a bullish AIFOB is waiting for eligibility, a confirmed M1 low that strictly crosses its relevant protected/last swing low creates `MSS_DOWN` at that M1 time. If the same confirmed low is strictly below the AIFOB's canonical engine bottom, reject the AIFOB immediately with reason `OPEN_WEEK_MSS_DOWN_BELOW_BOTTOM`. Mirror for bearish AIFOBs using a confirmed M1 high strictly above the canonical engine top.
- Required implementation details: store M1 confirmation time and rejection reason; draw the black/blue MSS cross; expose the timestamps and reason in the inspection table/CSV; process this before eligibility/promotion for that M1 event. Do not use the experimental 15-minute display range for this business rule.
- Open boundary decision: the observed wording is “below/above”, so the proposed comparison is strict `<` / `>`. Equality has not been locked.
- Next exact action: user confirms the open-week rule above, then implement it first for the inspected AIFOB and verify it against raw M1 rows before changing trigger timing.

## Session update — 2026-09-14 (OB 1 deferred; OB 2 investigation)

- Decision: do not investigate or change the newest AIFOB (`OB from last = 1`) now. The reported breach occurred after the available CSV endpoint (user estimates the CSV ends on 11 September 2026), so an exact M1 comparison is not possible.
- Do not label this AIFOB correct or incorrect from the current static dataset.
- Current investigation: `OB from last = 2`. Await the user's chart report before making a code change.

## Session update — 2026-09-14 (OB 2 / table ID #15 comparison)

- Selected record: `OB from last = 2`, table ID `#15`, `OOB BUY`.
- Python table shown in screenshot: origin `2026-07-19 21:00:00` UTC; bottom `1.13689`; top `1.14373`; trigger `2026-07-30 14:43:00` UTC; eligibility `2026-08-30 23:27:00` UTC; no trigger or eligibility price is shown; no impact time is shown.
- User chart evidence: the intended top is the open of the Weekly origin's first H1 candle (black horizontal at the green vertical origin marker), not Python's higher red boundary. The intended bottom is the close of that origin week's last H1 candle (yellow horizontal at the green vertical marker), not Python's lower red boundary. The user also marked expected trigger and eligibility price/time intersections on the H1 chart.
- Confirmed defects: (1) origin display body does not match the user-defined origin open/close; (2) table has event times but omits trigger and eligibility prices; (3) trigger/eligibility times visibly disagree with user chart markers, but exact differences must be read from the raw CSV before assigning a cause.
- Time rule proposed: retain one internal UTC timeline. Convert only displayed ledger/table/audit timestamps to `Asia/Riyadh` (UTC+3). Do not set `--input-tz Asia/Riyadh` unless the raw CSV itself was stamped in Riyadh; that would change all underlying event times.
- Origin-data rule proposed: M1 remains canonical. Define a scheduled weekly session boundary, then use its first observed M1 open and its last observed M1 close as the origin body. Aggregate those same M1 rows into H1 only for visual audit. A higher timeframe cannot repair missing M1 rows; it can only hide them or introduce a different feed. Never use the previous week's close as the new week's open: a weekend gap is a real separate open price.
- Missing-first-minutes policy proposed: use the actual first available M1 open, retain its exact timestamp and offset from weekly session start in the ledger, and do not invent a price. This is an observation label, not a `DATA UNAVAILABLE` blocker.
- Assured verification plan: first prove the raw CSV timezone by matching one unique M1 candle to the TradingView chart; second, calculate #15's source open/close, trigger and eligibility directly from those raw M1 rows; third, print value + UTC + Riyadh time + source M1 timestamp for every field; fourth, change only the failing resolver; fifth, rerun #15 before proceeding to OB #14.
- No calculation fix has yet been applied for #15. The experimental 15-minute display rule is not accepted as the final OB body definition.

## Session update — 2026-09-14 (OB #15 diagnostic display change)

- Controlled display fix applied: default displayed OB body is now the open of the first observed H1 candle and close of the last observed H1 candle, both assembled from M1 rows. The default was changed from 15 minutes to 60 minutes.
- Diagnostic additions: Pine table uses Riyadh (`Asia/Riyadh`, UTC+3) display time and appends trigger/eligibility structural prices. CSV now contains UTC and Riyadh timestamps, source H1 bucket/open/close times and M1-row counts, plus trigger and eligibility prices.
- Scope: this does not change the locked Weekly swing/MSS/OB lifecycle engine. It is a body-display and evidence improvement only.
- Required user validation: rerun with `--box-body-minutes 60 --display-tz Asia/Riyadh`, inspect OB from last = 2, and compare the four chart markings to the new one-row table and CSV before any trigger-rule change.

## Session update — 2026-09-14 (Riyadh chart confirmation / #15 results)

- User confirmed TradingView chart time is Riyadh (UTC+3). All chart comparisons must now use Riyadh as the visible clock.
- The Pine inspection table now also displays Riyadh. For #15, origin reads `2026-07-20 00:00:00` and aligns with the user's green origin marker, so display-time conversion is not the explanation for the remaining discrepancies.
- Current displayed #15 diagnostics: top `1.14373`, bottom `1.13689`, trigger `2026-07-30 17:43:00 @ 1.14822`, eligibility `2026-08-31 04:04:00 @ 1.17112` (all visible times Riyadh).
- Chart annotation evidence indicates the intended trigger horizontal price is about `1.14825` at a different Riyadh time, and the expected eligibility marking is also different. Treat screenshot readings as preliminary until matched to raw M1 rows.
- Conclusion: H1 display aggregation did not resolve #15. The next task is raw-M1 provenance: inspect the exact first H1 open, last H1 close, trigger M1 and eligibility M1 selected by Python. Do not alter timezones or trigger logic before that comparison.

## Session update — 2026-09-14 (OB #15 likely root-cause split and repair design)

- New user observation: the wrong red top aligns with the previous Week's close. The intended top is the selected origin Week's first H1 open. This is a source-window/provenance defect, not a reason to use a higher calculation timeframe.
- Required origin repair: bind a source body explicitly to the selected Weekly origin interval `[week.start, week.end)`. Its open must be the first accepted M1 record at/after `week.start`; its close must be the last accepted M1 record before `week.end`. The previous Week's close must never be selected for the new origin. Emit the selected source timestamp and price in diagnostics.
- Separate trigger/eligibility repair: stop recomputing a zone's event data by searching only `(weekly index, event kind)`. Several events can share that combination. At zone creation, store the exact parent event identity, structural level, and first strict-cross M1 timestamp; at eligibility acceptance, store the exact eligibility event identity, level and M1 timestamp. The viewer/ledger must use those stored facts directly.
- Verification order: repair/verify origin source selection first; then repair/verify stored trigger facts; then repair/verify stored eligibility facts. M1 remains the calculation source; H1 is only an audit view.

## Session update — 2026-09-14 (OB #15 provenance repair implemented; awaiting chart validation)

- User requirement: always provide this updated handoff file with every response. Keep appending concrete discoveries, plans, fixes, commands and validation results; never replace evidence with assumptions.
- Implemented in `weekly_ob_generator.py`:
  1. **Strict source-window body selection.** `observed_box_body()` now slices M1 rows by the scheduled origin interval `[week.start, week.end)` using timestamps, instead of trusting stored row-index boundaries. A prior Week close cannot be selected as the new Week's first body open.
  2. **Stored lifecycle facts.** Every structure event now captures its exact existing M1 confirmation time. A zone captures its exact trigger price/time when it is created; accepted eligibility captures its exact event time/price. Pine and CSV use the stored facts first and label a fallback only when a legacy/partial record has no stored fact.
  3. **Diagnostics.** `weekly_ob_ledger.csv` now includes `origin_window_start_utc`, `origin_window_end_utc`, trigger/eligibility fact-source columns (`stored` or `fallback`), selected source H1 bucket/open/close timestamps and M1 counts, plus UTC and Riyadh event fields.
- Validation performed locally: Python compilation passed; a targeted synthetic test proved that a deliberately injected previous-Week row is excluded from the selected origin body, and that stored trigger/eligibility facts are returned instead of a broad lookup. A small fixture CSV completed normally, but it contains no zones, so it does not validate OB #15.
- Not yet claimed: the #15 top, trigger or eligibility is **not verified correct** until the user reruns against the exact full CSV and compares the printed ledger evidence to the Riyadh TradingView chart.
- Required validation command (raw CSV timezone remains a separate fact to verify):
  ```bat
  cd %USERPROFILE%\Desktop\ForexTesting
  python weekly_ob_generator.py EURUSD_m1_BidAndAsk.csv --input-tz America/New_York --box-body-minutes 60 --display-tz Asia/Riyadh
  ```
- First comparison steps for `OB from last = 2` / `#15`: in `weekly_ob_ledger.csv`, locate ID 15 and compare (a) `first_h1_open_time_utc` + `first_h1_open` with the origin first-H1 opening candle, (b) `last_h1_close_time_utc` + `last_h1_close` with the origin last-H1 closing candle, (c) trigger and eligibility Riyadh fields/prices with the chart markings, and (d) both fact-source columns. Send those one CSV row plus screenshots if any field differs.

## Session update — 2026-09-15 (OB #15 repair result: no visible change)

- User reran the generator and inspected `OB from last = 2` / `#15` on the Riyadh chart. The Pine table is still: bottom `1.13689`, top `1.14373`, trigger `2026-07-30 17:43:00 @ 1.14822`, eligibility `2026-08-31 04:04:00 @ 1.17112`.
- Therefore the 2026-09-14 provenance repair did **not** solve the visible #15 mismatch. It only made the source-window and fact resolver deterministic. On this dataset, its strict timestamp body slice selected the same rows as the prior stored index slice, and the stored facts matched the values that the previous broad lookup had happened to return.
- Do not claim that the origin top, trigger, or eligibility is fixed. The screenshot still shows the user’s intended origin top near `1.14278`, trigger near `1.14825`, and eligibility near `1.15776`, which differ from the generated values.
- Next investigation must be evidence-first, not another speculative code change: obtain the generated `weekly_ob_ledger.csv` row for ID 15 and the exact raw CSV M1 rows around (1) the scheduled origin boundary, (2) the chart-marked trigger, and (3) the chart-marked eligibility. Confirm the raw CSV timestamp basis against one unique TradingView candle. Only then identify whether the remaining defect is raw input timezone/session alignment, the intended origin-body definition, or the locked swing/MSS event rule.

## Session update — 2026-09-15 (ID #15 ledger evidence: input-timezone diagnosis)

- User supplied the generated ledger. The ID #15 row proves the currently selected origin source is: scheduled window `2026-07-19 21:00:00` to `2026-07-26 21:00:00` UTC; first source H1 bucket `2026-07-19 23:00:00` UTC; first source M1 `2026-07-19 23:02:00` UTC at `1.14373`; last source M1 `2026-07-25 00:58:00` UTC at `1.13689`.
- Riyadh Weekly origin is correctly displayed as `2026-07-20 00:00:00`, but the selected first source row is two hours late relative to that scheduled start. This is why the source top does not represent the intended opening H1 candle.
- The run was performed with `--input-tz America/New_York`. In July New York is UTC-4. The supplied raw timestamp which becomes `23:02 UTC` would instead become `21:02 UTC` if the CSV timestamps are UTC-2 (`Etc/GMT+2`). This is a strong candidate explanation for the exact two-hour offset, but not yet a proven fact: timezone conversion cannot itself change the `1.14373` price, and the chart’s reported intended opening price is about `1.14278`.
- No code change should be made yet. Required controlled test: run the exact same generator and CSV once with `--input-tz Etc/GMT+2`, retain all other arguments, then compare ID #15 `first_h1_open_time_utc`, `first_h1_open`, trigger and eligibility with the Riyadh chart. If first source is then around `21:02 UTC` / `00:02 Riyadh`, the session alignment is confirmed; if the opening price is still different, the remaining difference is missing initial source minutes or a feed-price difference, which must be recorded rather than invented.
- The supplied row also confirms trigger/eligibility already have `stored` provenance. Their disagreement with the chart is therefore not due to the former broad table lookup; it must be investigated after the raw timestamp basis is locked.

## Session update — 2026-09-15 (controlled #15 timezone inspection procedure)

1. In `Desktop\ForexTesting`, run the generator once with `--input-tz Etc/GMT+2 --box-body-minutes 60 --display-tz Asia/Riyadh`.
2. Open the new `weekly_ob_ledger.csv` in Excel. Press `Ctrl+F`, type `15,` and select the row whose first cell is `15` (do not use the table screenshot for this step).
3. Read only these four cells from that row: `first_h1_open_time_utc`, `first_h1_open`, `trigger_time_riyadh`, and `eligible_time_riyadh`. Also read `trigger_price` and `eligible_price` if visible.
4. In TradingView, keep chart time set to Riyadh and use the existing Pine inspector with `Inspect one OB only = on`, `OB from last = 2`. On the chart, place the crosshair on the first M1 candle after the green origin line and read the top-left OHLC open. Then place it at the existing trigger and eligibility markings and read each chart timestamp/price.
5. Report the six CSV values and screenshots. A successful timezone alignment requires the CSV first-source time to be about `00:02 Riyadh` (not `02:02 Riyadh`). Do not call price agreement successful unless the numerical opening price also matches the chart.

## Session update — 2026-09-15 (UTC-2 test result: timing alignment confirmed; record identity changed)

- User supplied the new ledger produced with the UTC-2 candidate. The prior target record must now be identified by its origin and type, not its old numeric ID: it is now **ID #14, OOB BUY, origin Riyadh 2026-07-20 00:00:00**. ID numbers changed because changing input-time interpretation changed the weekly swing/MSS sequence and therefore zone creation order.
- For target ID #14, first source M1 is now `2026-07-19 21:02:00 UTC` = `2026-07-20 00:02:00 Riyadh`, with first-source price `1.14373`. This confirms the UTC-2 interpretation aligns the observed source session to the scheduled `21:00 UTC` Weekly start; retain `--input-tz Etc/GMT+2` for the next evidence step unless a raw-feed timestamp check disproves it.
- Target #14 trigger is now `2026-07-30 15:43:00 Riyadh @ 1.14822`; eligibility is `2026-08-31 02:04:00 Riyadh @ 1.17112`. Both shifted two hours earlier versus the New-York-parsed run and are stored facts.
- Remaining unresolved facts: (1) first observed source price is still `1.14373`, while the user’s TradingView opening-H1 annotation is about `1.14278`; this cannot be repaired by timezone conversion and may be missing opening source minutes or a feed-price difference; (2) exact chart trigger/eligibility values/times still need direct comparison. Do not change lifecycle code yet.
- Next chart inspection must use `OB from last = 2` only if that Pine table shows #14. The robust identifier is: `OOB BUY`, origin `2026-07-20 00:00 Riyadh`, source body `1.13689–1.14373`.

## Session update — 2026-09-15 (how to distinguish missing rows, feed difference, and other causes)

- Use the target origin boundary only: scheduled `2026-07-20 00:00 Riyadh` = `2026-07-19 21:00 UTC` = **`2026-07-19 19:00` in the tested UTC-2 CSV clock**.
- In the raw `EURUSD_m1_BidAndAsk.csv`, filter Date `7/19/2026` and inspect rows from 18:55 through 19:10. Do not look only at the generated ledger. Record the first available raw time and its `OpenBid`.
- Decision table:
  - First raw row is 19:02 (or later): the export is missing the 19:00/19:01 opening rows. Python may truthfully use 19:02, but cannot recreate the 00:00 H1 opening price. Record it as an observed-source limitation; do not invent the price.
  - Raw row 19:00 exists and its `OpenBid` is 1.14373 while TradingView FXCM M1 at 00:00 Riyadh has a different open (about 1.14278): this is a feed/quote-construction difference, not missing rows. Verify both are EURUSD, FXCM, same Bid/Ask side and normal candles.
  - Raw row 19:00 exists and equals the TradingView M1 open, but the H1 open differs: the issue is H1 aggregation/session alignment or chart symbol settings, not the M1 export. Check that TradingView H1 begins at 00:00 Riyadh and that the selected chart is `EURUSD · FXCM`.
  - Raw rows are present but timestamps do not align to 00:00 Riyadh under UTC-2: test timezone/session labeling only after preserving the raw rows; do not modify OB logic.
  - Duplicates, gaps inside 18:55–19:10, or inconsistent OHLC values: this is export quality evidence; retain the raw excerpt.
- Required TradingView comparison: switch temporarily to **1m**, EURUSD FXCM, Riyadh chart time. Put the crosshair on 20 Jul 2026 00:00 and record the top-left O/H/L/C values. Then return to the Weekly/H1 validation chart. This preserves M1 as the authoritative timing resolution while H1 remains only the visual audit.
- The only evidence needed next is a screenshot or copied raw rows 18:55–19:10 plus the TradingView 1m O/H/L/C at 00:00 Riyadh. That evidence determines the branch above before further code changes.

## Session update — 2026-09-15 (recommended fix path after chart review)

- Definite result: with the UTC-2 interpretation, target #14’s first available source M1 is 00:02 Riyadh, not 00:00. The external M1 export therefore cannot itself supply the exact TradingView 00:00 opening price. No timezone change or box formula can truthfully recover an absent opening quote.
- Recommended permanent data policy: choose one **canonical source** for historical Python calculations and TradingView comparison. Preferred: obtain/export a complete FXCM M1 series that contains the 00:00 Riyadh opening minutes and matches the TradingView FXCM chart. Then regenerate all history from that one series. Do not mix a TradingView H1 open with FXCM-export M1 triggers in the same OB; that makes results non-reproducible.
- Temporary, honest policy if no matching complete M1 source is available: retain the observed-source body (`00:02` first available M1 onward), display the actual source timestamp, and explicitly treat exact origin-open matching as unverified. This is suitable for algorithm investigation but not a final chart-match claim.
- Trigger/eligibility remain a separate defect: after timezone correction, target #14 stored trigger is 30 Jul 15:43 Riyadh and eligibility is 31 Aug 02:04 Riyadh, whereas the user’s chart annotations appear near 30 Jul 13:00 and 31 Aug 00:00. The non-round differences mean this must not be “fixed” by applying another timezone offset.
- Next code change, only after user accepts it: add an inspection audit CSV for the selected OB that prints the exact raw M1 row selected for origin/trigger/eligibility, the comparison threshold, and a small M1 window before/after each event. This will show whether Python’s source data crosses the structural level later than the chart or whether its structural level/rule is wrong. No lifecycle rule should change until that audit is compared.

## Plain-language status — 2026-09-15

- Python needs the price at 00:00 Riyadh to draw the OB top exactly like the chart. The CSV starts at 00:02, so that price is absent from the CSV.
- The two-hour clock error is corrected by `--input-tz Etc/GMT+2`.
- The remaining trigger/eligibility mismatch is not another clock error. Before changing the OB rule, make Python print the exact M1 candle it used; compare that one candle to TradingView.

## Plain-language origin-body rule — 2026-09-15

- The OB **top** is the open of the first origin-session candle. The OB **bottom** is the close of the last origin-session candle (for this BUY OB; then use min/max to draw the box safely).
- Python currently uses the first and last M1 prices that exist in the CSV. Therefore #14 top `1.14373` is the first available 00:02 price; it is not the chart’s missing 00:00 price. Bottom `1.13689` is likewise the last available source close.
- Exact top/bottom fix: obtain the missing opening/closing minutes from the same FXCM/TradingView-compatible M1 series, then regenerate. Do not substitute a previous Week close or guess a price. Until then, Python can draw only the observed-data box, not an exact chart-body box.

## Session update — 2026-09-15 (full 2026 CSV inspection: new origin-top evidence)

- Full attached CSV inspected: 261,352 M1 rows, UTC coverage 2026-01-02 through 2026-09-11 after the tested UTC-2 interpretation. Across 36 usable 2026 Weekly starts, only 8 have a row exactly at the scheduled boundary; 28 start late, median delay 7 minutes, maximum 97 minutes. This is a recurring export/session-start characteristic, not a one-off #14 issue.
- Target #14 raw evidence at CSV date/time `07/19/2026 19:02` (which is 00:02 Riyadh under UTC-2): `OpenBid=1.14373`, `HighBid=1.14373`, `LowBid=1.14265`, `CloseBid=1.14278`. The user’s intended TradingView origin-top value is `1.14278`.
- Therefore the target top is not simply absent: it is present as the **CloseBid of the first available M1 row**. Current Python uses that row’s OpenBid, causing the displayed top `1.14373`.
- Do not immediately globalize a rule from one record. Proposed controlled next step: add a reversible inspection-only origin-body option that can select `first observed M1 close` instead of `first observed M1 open`, while retaining both values/timestamps in the ledger. For #14 this would display top `1.14278`; compare one additional OB before accepting it as the global origin-body rule. Keep last source close/bottom unchanged and do not modify trigger or eligibility during this test.

## Session update — 2026-09-15 (origin first-close inspection option implemented)

- Implemented `--origin-first-price open|close` in `weekly_ob_generator.py`. Default `open` preserves the prior behavior; `close` is reversible and changes only the displayed origin body, never Weekly swing/MSS/OB lifecycle, trigger, eligibility or impact calculations.
- Ledger now exposes `first_h1_open`, `first_h1_close`, `origin_first_price_source`, and `origin_first_selected_price`, making the selected boundary explicit.
- Full 2026 CSV test completed with `--input-tz Etc/GMT+2 --box-body-minutes 60 --origin-first-price close --display-tz Asia/Riyadh`. Target `#14 OOB BUY` now has display body `1.13689–1.14278`; the new top exactly matches the user’s chart annotation. Trigger remains 30 Jul 15:43 Riyadh @ 1.14822 and eligibility remains 31 Aug 02:04 Riyadh @ 1.17112; they were intentionally untouched.
- Required user validation: paste the newly generated Pine, set inspection to the target #14 / its corresponding `OB from last` rank, and compare only top/bottom. Then inspect one other OB before accepting first-close as a global display rule.

## Session update — 2026-09-15 (origin-top rule locked)

- User validated the target OB top and instructed to lock the fix. `--origin-first-price` now defaults to `close`: the origin body begins from the CloseBid of the first observed origin M1 row. `open` remains available only as a diagnostic fallback.
- Bottom remains the last observed source close. No trigger, eligibility, MSS, OB selection or lifecycle rule changed.
- Trigger/eligibility error-inspection plan, before any calculation fix:
  1. Generate an audit for one selected OB only.
  2. Print the exact stored structural threshold and the exact raw M1 row Python selected as trigger/eligibility, with a short window of rows immediately before and after it.
  3. Compare those raw rows to TradingView at the same Riyadh time.
  4. If raw M1 crosses at the same time as Python but chart differs, the data feed differs. If raw M1 crosses earlier, Python’s crossing/event resolver is wrong; change only that resolver and retest the same OB. Do not apply time shifts or change all OB rules without this proof.

## User report needed for trigger/eligibility investigation — 2026-09-15

- User does not need to inspect or send raw CSV rows again; the full 2026 file is already available for analysis.
- For the selected target OB (#14 OOB BUY, origin 20 Jul 2026 00:00 Riyadh), report only four chart facts from TradingView, in Riyadh time:
  1. Trigger: exact chart timestamp and price where the user says the trigger occurred.
  2. Eligibility: exact chart timestamp and price where the user says eligibility occurred.
- A screenshot is enough if the crosshair’s date/time and price labels are visible. Do not estimate a candle: place the crosshair on the exact candle/level.
- After an audit file is added, the user will compare those two chart facts directly with Python’s printed selected trigger and eligibility rows. No other report is required.

## Session update — 2026-09-15 (critical timezone correction from exact-minute chart evidence)

- User screenshots show the chart’s trigger at 30 Jul **13:43 Riyadh** and eligibility at 31 Aug **00:04 Riyadh**. The minutes exactly match the raw event rows; only the hour differs by two.
- Full CSV controlled comparison proves this:
  - Parsed as `UTC`, target OOB BUY is ID #12 and reports trigger **13:43 Riyadh**, eligibility **00:04 Riyadh**—matching the chart times.
  - Parsed as `Etc/GMT+2`, target OOB BUY is ID #14 and reports trigger 15:43 Riyadh, eligibility 02:04 Riyadh—two hours late.
- Conclusion: raw M1 timestamps must be parsed as **UTC for intraday trigger/eligibility events**. The earlier `Etc/GMT+2` recommendation is withdrawn for event calculations. Use `--input-tz UTC`.
- Important consequence: the previous origin top match under UTC-2 cannot be accepted as a global locked result, because that timezone shifted raw rows between weekly origin intervals. Keep `first observed M1 close` as a reversible display convention, but revalidate top/bottom under UTC separately.
- Next sequence: (1) rerun UTC and verify trigger 13:43 / eligibility 00:04 in the table; (2) then solve origin body timing as a separate session-boundary/data-feed question, without changing M1 event timestamps; (3) do not apply another global timezone change.

## User display-time rule — locked 2026-09-15

- The user always uses **Riyadh time (Asia/Riyadh, UTC+3)** in TradingView and in all discussion.
- All user-facing table, audit, report and comparison timestamps must be Riyadh time. Internal UTC may exist only as an implementation detail and must never require the user to convert a time.
- `--input-tz UTC` means only that the raw CSV timestamp labels are interpreted as UTC before conversion. It does **not** mean the user should view or report UTC; displayed output remains Riyadh through `--display-tz Asia/Riyadh`.

## Session update — 2026-09-15 (eligibility price root cause found; no code change yet)

- User correctly reports: target #12 OOB BUY eligibility time is right at **31 Aug 2026 00:04 Riyadh**, but displayed eligibility price `1.17112` is wrong versus the chart’s red eligibility level near `1.15776`.
- Direct raw-engine evidence:
  - Stored `1.17112` is the old **swing high** from the Week beginning 17 Aug. It is the swing that became confirmed; it is not the price level broken at eligibility.
  - The M1 confirmation occurs at 00:04 Riyadh because the code sees price break the prior Week’s low. That structural level in raw data is `1.15773`, close to the user’s chart level `1.15776`.
  - The actual selected 00:04 Riyadh raw M1 candle is O=1.15775, H=1.15775, L=1.15764, C=1.15765.
- Root cause: the table column called `eligible price` currently stores `event.swing_price` instead of the **eligibility break threshold**. Time and price came from two different semantic facts, producing a correct time but wrong price.
- Safe proposed repair: preserve the swing price as an audit field if needed, but display/store `eligible_threshold_price` as the prior Week low for a bullish eligibility (or prior Week high for bearish eligibility). This repair changes only displayed/audit eligibility price; it does not change zone creation, top/bottom, trigger time, eligibility time, MSS or lifecycle state.

## Locked-change reporting rule — 2026-09-15

- The user correctly flagged that switching raw `--input-tz` changed origin-box membership and invalidated the earlier apparent top/bottom success. This was not flagged promptly enough.
- From now on, before or immediately with any change, state which locked outputs can change: origin body, structure/MSS, OB list/ID, trigger, eligibility, impact, or display only. A validation result under a changed raw-time interpretation never silently preserves a prior lock.

## Session update — 2026-09-15 (zone top/bottom repair implemented)

- User requested the OB zone top/bottom issue be solved now, while retaining the now-verified Riyadh event clock.
- Implemented two independent, explicitly separated rules:
  1. **Events:** raw M1 labels are parsed with `--input-tz UTC`. Trigger and eligibility remain on this unshifted timeline.
  2. **Displayed zone body only:** default `--origin-body-offset-minutes -120` samples the source body from `[scheduled Week start - 120 minutes, scheduled Week end - 120 minutes)`. The displayed top is the CloseBid of that window's first observed M1 and the displayed bottom is its last observed display-candle close. The drawn box's left edge remains the scheduled Riyadh Weekly origin.
- This is a **display-body-only** change. It does not change Weekly swings/MSS, OB selection or IDs, type, trigger time/price, eligibility time, impact time, lifecycle or status. It changes only displayed top/bottom and their provenance fields.
- The ledger now writes `origin_body_source_offset_minutes`, `origin_body_source_window_start_utc`, and `origin_body_source_window_end_utc` so the source is auditable.
- The eligibility table-price repair was also implemented: `eligible_price` is now the actual structural threshold (prior Week low for a BUY eligibility; prior Week high for a SELL eligibility). The previously displayed swing price is retained as `eligible_swing_price` in the CSV for audit. This changes the displayed/audit eligibility price only; it does not change its time or lifecycle.
- Local full-CSV run passed. For the target **#12 OOB BUY**, expected Pine table values in Riyadh are: bottom `1.13689`, top `1.14278`, trigger `2026-07-30 13:43:00 @ 1.14822`, eligibility `2026-08-31 00:04:00 @ 1.15773`. The retained audit swing price is `1.17112`.
- Run this exact command:
  ```bat
  cd %USERPROFILE%\Desktop\ForexTesting
  python weekly_ob_generator.py EURUSD_m1_BidAndAsk.csv --input-tz UTC --box-body-minutes 60 --display-tz Asia/Riyadh
  ```
- User validation next: paste the fresh `weekly_ob_viewer.pine`, select the target OB in inspection mode, and compare only the four values above. If the trigger line is still `1.14825` rather than `1.14822`, report it as a remaining **trigger-price semantic/feed** discrepancy; do not alter the repaired zone body or time clock.

## Session update — 2026-09-15 (drawn OB #9: global body-offset defect found)

- User will skip rejected OBs for now. They are not drawn; inspect only drawn OBs, then revisit rejected records after universal drawn-OB fixes.
- Drawn `OB from last = 5` is current ID **#9 OOB SELL**. User confirms its trigger and eligibility time/price are sufficiently correct. Do not modify those rules.
- Direct full-CSV evidence for #9 (all user-facing times are Riyadh):
  - Current displayed box: bottom `1.15168`, top `1.15662`.
  - User's chart lines: approximately bottom `1.15075`, top `1.15665`.
  - Current global `-120` body window starts from Sunday 19:08 UTC (22:08 Riyadh), selecting first close `1.15168`. This is the bad bottom.
  - The scheduled Weekly interval starts at Sunday 21:00 UTC (Monday 00:00 Riyadh). Its first available M1 is 21:03 UTC: open `1.15072`, close `1.15082`. Either is within about 0.3 pip of the chart bottom, unlike the shifted source.
  - The shifted end correctly avoids next-Week pre-session rows: its last source close is Friday 20:58 UTC, `1.15662`, within about 0.3 pip of the chart top.
- Conclusion: the global `-120` offset that matched prior #12 is **not universal**. It wrongly shifts #9's start into pre-session data. Do not call it a locked universal zone-body fix. The code has not silently changed this body rule again; top/bottom remain pending a rule that handles both #9 and #12 from evidence.
- New diagnostics were implemented in the CSV: `scheduled_first_m1_time_utc`, `scheduled_first_m1_open`, `scheduled_first_m1_close`, `scheduled_last_m1_time_utc`, `scheduled_last_m1_close`, alongside the selected display-source fields. This exposes, per OB, whether an offset entered pre-session data.
- Impact display repair implemented and tested:
  - The real impact remains the exact M1 fact: #9 `2026-07-30 16:48 Riyadh`.
  - The Pine box end and red impact line are now placed at the **opening of the containing H1 candle**, `2026-07-30 16:00 Riyadh`, not at its close/next timeframe boundary.
  - CSV retains both `impact_time_riyadh` (exact M1) and `impact_draw_time_riyadh` (H1 display placement), plus `impact_draw_bucket_minutes`.
  - This changes **Pine impact/box-right display only**. It does not change impact detection, top/bottom calculation, MSS, OB ID/list, trigger, eligibility, or lifecycle.
- Next body solution must be evidence-based and must not use one global offset: compare #9 and #12's scheduled-start candidates against the chart, then define an explicit session-anchor policy. If neither candidate matches a chart price, that remaining difference is a feed/session-boundary discrepancy—not a price to invent.

## User report requested — drawn OB #9 only

- No CSV report is needed: Python now prints the required source candidates in `weekly_ob_ledger.csv`.
- After rerunning and pasting the new Pine, set `Inspect one OB only = on`, `OB from last = 5`, then send **one screenshot** of the H1 chart in Riyadh time that visibly includes:
  1. the correct black top and bottom lines;
  2. the red box;
  3. the new red impact line; and
  4. the crosshair/date label at the impact line (it should be 30 Jul 2026 16:00 Riyadh for the H1 display anchor).
- Also send the single CSV row for ID #9, or copy only these fields: `display_bottom`, `display_top`, `scheduled_first_m1_time_utc`, `scheduled_first_m1_open`, `scheduled_first_m1_close`, `scheduled_last_m1_time_utc`, `scheduled_last_m1_close`, `impact_time_riyadh`, and `impact_draw_time_riyadh`.
- No trigger or eligibility report is needed for this OB: the user already considers them adequately aligned.

## Session update — 2026-09-15 (OB #9: universal session body and timeframe-aware impact display)

- User correctly identified that the prior impact display repair only rounded the M1 impact to H1. That fixed H1 but was wrong on Weekly/Daily and early on 30m/15m. It was not timeframe-aware.
- Implemented the correct Pine method: for each impact, generated Pine checks every chart bar for `bar open <= exact M1 impact < bar close`, stores that chart bar's opening time, and uses it for the box right edge and impact line. Therefore the event belongs to the containing candle on **every displayed timeframe**: 5m, 15m, 30m, H1, Daily and Weekly. The raw M1 impact time remains unchanged in the table/CSV.
- Scope of this repair: **Pine impact/box-right placement only**. It does not change M1 impact detection, trigger, eligibility, zone top/bottom, Weekly swing/MSS, OB IDs, status or lifecycle.
- Universal body source correction implemented after #9 evidence:
  - Start at the scheduled Sunday Weekly open (default body offset is now `0`).
  - End at Friday close, exactly five days after that scheduled start. Do not use the following Sunday boundary because FXCM pre-session rows belong to the next Week, not the closing candle of this one.
  - This is an origin-body display change and may change displayed top/bottom for all OBs. It does **not** alter structure/MSS, OB list/ID, trigger, eligibility, impact detection or lifecycle.
- Local validation for #9 OOB SELL:
  - Old incorrect display bottom: `1.15168` (came from Sunday pre-session 22:08 Riyadh).
  - New display bottom: `1.15082` (first observed scheduled-session M1 close; raw first open is `1.15072`). Chart line is about `1.15075`; that exact value does not exist in the supplied Bid M1 row, so it must not be invented.
  - New display top: `1.15662` (last observed Friday close), about 0.3 pip from the chart line `1.15665`.
  - Exact impact remains `2026-07-30 16:48 Riyadh`. Chart anchoring is now dynamic: it will be 16:45 on a 5m chart, 16:30 on 30m, 16:00 on H1, and the opening time of the containing Daily/Weekly candle on those charts.
- Required user validation: rerun using the normal command and paste the fresh Pine. For #9, verify that the red vertical/box-right lands inside the candle containing 16:48 Riyadh on each timeframe, not at a fixed H1 time.

## Session update — 2026-09-15 (drawn OB #8 trigger provenance repaired)

- User inspected `OB from last = 6`, ID **#8 OOB SELL**, and correctly questioned table trigger `2026-06-05 16:00 Riyadh @ 1.16854`.
- Root cause: #8 started as an AIFOB and was later promoted to an IFOB/OOB. Its state changed, but it kept the old AIFOB trigger facts. `1.16854` was the old swing high, not the level that promoted/triggered the OOB.
- Implemented a promotion-specific trigger resolver. When an AIFOB becomes an IFOB, it now stores the actual armed opposite swing level that is broken and the first strict M1 crossing of that level.
- Verified #8 result from the full CSV:
  - Trigger level: **1.15759**, role `armed swing-low break level`.
  - Trigger time: **2026-06-05 16:51 Riyadh**.
  - Exact trigger M1: O `1.15801`, H `1.15805`, L `1.15726`, C `1.15752`; its low is strictly below the level, so it proves the crossing.
  - The old values `16:00 @ 1.16854` are withdrawn for #8.
- CSV now distinguishes `trigger_level_price`, `trigger_level_role`, `trigger_swing_price`, and the exact trigger M1 OHLC. Pine table header is now `Trigger (RYD / level)` to avoid calling a structural level the candle price.
- Scope: this changes trigger facts (time/level) for **promoted AIFOB → IFOB/OOB** records. It does not change their origin body, Weekly swings/MSS, OB IDs/list, eligibility, impact, rejection, spend or lifecycle decision. Verify this class before touching other trigger types.

## Inspection result — 2026-09-15 (drawn OB #7 OOB SELL)

- `OB from last = 7`, ID **#7 OOB SELL**, was created directly as an **IFOB**. It was **not** promoted from AIFOB or AOB.
- Its lifecycle was: `IFOB → OOB`. The stored trigger is consequently a direct-IFOB fact: prior-Week low break level `1.16761`, first strict M1 break at 14 May 2026 18:00 Riyadh.
- This record is useful as a separate class when validating trigger provenance: it tests the direct-IFOB resolver, whereas ID #8 tested the promoted-AIFOB resolver.

## Inspection result — 2026-09-15 (drawn OB #7 candle selection)

- The code selected the origin Week beginning **27 Apr 2026 Riyadh**. It did so through the direct-IFOB candidate range 27 Apr, 4 May and 11 May, then selected the most bullish eligible Weekly candle.
- In the supplied FXCM Bid data, 27 Apr is bullish: open `1.16894`, close `1.17449`. The 4 May Week is marginally bearish: open `1.17449`, close `1.17446`; 11 May is bearish. Therefore, under the current rule only 27 Apr qualifies, so it is selected.
- If the user’s intended OB candle is 4 May, the discrepancy is not yet proven to be a coding error alone. It can be: (1) a rule-definition difference (the intended rule chooses the nearest/last opposing candle rather than the most bullish eligible candle), or (2) a chart/feed difference that classifies the 4 May candle differently. Do not change the selector until the intended candle-selection rule is explicitly confirmed.

## Inspection result — 2026-09-15 (4 May Weekly boundary and gap test)

- The Week beginning **4 May 2026 00:00 Riyadh** ends at **11 May 2026 00:00 Riyadh**; its last observed source M1 is 10 May 23:56 Riyadh.
- Raw FXCM Bid continuity is exact at both relevant boundaries: 27 Apr Week close `1.17449` → 4 May first M1 open `1.17449`; 4 May Week close `1.17446` → 11 May first M1 open `1.17446`. Thus there is **no source weekly opening gap** to assign at either boundary.
- The apparent direction conflict is a convention conflict. The 4 May first M1 OpenBid is `1.17449`, but its first M1 CloseBid is `1.17427`; final source close is `1.17446`. Therefore it is slightly bearish under raw-open→last-close, but bullish under the locked displayed first-close→last-close convention.
- A controlled global test made candidate selection use first-close→last-close. It changed the structural record list from 13 to 15 and shifted IDs, so it was immediately rolled back. No locked calculation was changed.
- Gap policy for any future actual gap: record it at the **next Week's opening** as `next first observed M1 open − previous Week's last source close`; never use it to rewrite the previous Week's close or direction. Before changing the candidate selector, add an inspection-only comparison of raw-open and first-close candle direction for the selected OB and validate more than one drawn OB.

## Inspection update — 2026-09-15 (drawn OB #5)

- User validated that `OB from last = 9`, ID **#5 OOB BUY**, uses the correct origin candle and box.
- Therefore do not make a global candle-selection change based on ID #7. Treat the ID #7 wrong-origin report as an isolated exception until at least one further comparable failure proves a universal rule defect.
- Process clarified for the user: inspect drawn OOBs one by one in this order: origin candle, box boundaries, trigger, eligibility, then impact. Rejected records are skipped for now because they are not drawn.

## Session update — 2026-09-15 (drawn OB #5 trigger-price semantics repaired)

- User validated #5 origin. Its trigger time `8 Apr 2026 01:32 Riyadh` is correct and eligibility time/price are correct, but the table showed the wrong trigger price.
- Evidence: the old table price `1.16268` was the separate prior-Week high **break threshold**. The intended trigger price is the stored swing high, `1.16394` (chart black line). Both facts were already available; the table combined the confirmation time with the wrong price field.
- Implemented a table/ledger semantic repair: the Pine header is now `Trigger (RYD / swing)` and #5 displays `2026-04-08 01:32:00 @ 1.16394`. CSV writes `trigger_price` as the stored swing price and retains `trigger_break_level_price=1.16268` plus its role for audit.
- Scope: display/audit trigger-price semantics only. Trigger time, break detection, candle selection, zone boundaries, eligibility, impact, OB IDs/list and lifecycle are unchanged. Promoted #8 remains correct because its stored swing and promotion break level are the same `1.15759`.

## Guardrail — 2026-09-15 (no chart-price patching)

- User correctly challenged two consecutive trigger-price corrections. Neither correction inserted a user/chart price into Python.
- Two distinct facts always exist for an OB trigger: (1) the stored swing price that enables the OB and is the user-facing trigger price; and (2) a break/confirmation threshold used to locate the M1 trigger time. The prior implementation sometimes displayed fact (2) beside the time, while the user expects fact (1).
- Universal display rule now implemented: `Trigger (RYD / swing)` always shows the stored swing price. The CSV retains the break threshold in `trigger_break_level_price` and `trigger_break_level_role`. The trigger timestamp remains the exact M1 confirmation/break time.
- Why the two reports looked different: #8 was promoted and its new armed swing equals its promotion-break level (`1.15759`); #5 is a direct IFOB and its swing (`1.16394`) differs from its prior-Week break threshold (`1.16268`). This is expected under the two-fact model, not a manual exception.
- Required validation before declaring the rule fully locked: inspect one more direct IFOB and one AOB/AIFOB. Confirm table price equals the chart's stored swing point while the reported timestamp remains correct. If either fails, revisit the semantic definition, not individual numeric values.

## Inspection result — 2026-09-15 (drawn OB #3 OOB SELL lifecycle)

- `OB from last = 11`, ID **#3 OOB SELL**, was created directly as an IFOB; it was not promoted from AIFOB/AOB.
- Lifecycle in Riyadh time:
  1. Origin: Week beginning 9 Feb 2026 01:00.
  2. IFOB creation/trigger: 17 Feb 18:28. Stored enabling swing price `1.17652`; M1 confirmation used the separate prior-Week low break level `1.18086`.
  3. Eligibility: 23 Mar 14:06, after the low-swing event `1.14089`; stored eligibility threshold `1.16159`.
  4. It became OOB in the Week beginning 30 Mar when a qualifying swing high `1.16394` formed below the SELL zone bottom `1.18095`.
  5. First impact occurred during the Week beginning 13 Apr at exact M1 time 14 Apr 17:55.
- This is a direct-IFOB lifecycle example: `IFOB → eligible → OOB → later impact`. No calculation was changed by this inspection.

## Session update — 2026-09-15 (direct-IFOB trigger-time resolver repaired)

- User showed #3's reported trigger at 17 Feb 18:28 / `1.17652` was wrong as a combined fact. The correct chart mark is the stored swing level near `1.17655` and the H1 candle opening 19 Feb 16:00 Riyadh.
- Raw M1 proof: the stored #3 swing is `1.17652`; first strict M1 low below it is **19 Feb 2026 16:01 Riyadh**, with O `1.17675`, H `1.17678`, L `1.17645`, C `1.17648`. That M1 belongs to the chart's H1 16:00 candle.
- Root cause: the direct-IFOB resolver used the prior-Week structural threshold to determine trigger time. That condition establishes the IFOB, but the trigger fact must be the first strict M1 break of the stored enabling swing.
- Implemented universal direct-IFOB repair: direct IFOB trigger time now resolves from first strict M1 crossing of `trigger_swing_price`; table price remains that same swing. Prior-Week threshold is retained only as CSV audit evidence.
- Validation run: OB IDs/count/statuses were unchanged (13 records). Affected direct-IFOB trigger facts include #3 `19 Feb 16:01 @ 1.17652`, #5 `8 Apr 01:36 @ 1.16394`, and #7 `15 May 03:38 @ 1.16547`. Promoted #8 remains `5 Jun 16:51 @ 1.15759` because it uses its promotion-specific resolver.
- Scope: trigger time/price facts for direct IFOBs only. No changes to candle selection, boundaries, eligibility, impact, state transitions, OB list/IDs or status.

## Investigation update — 2026-09-15 (drawn OB #1 trigger still disputed)

- User suspects the remaining incorrect #1 trigger may be stale AIFOB facts after an AIFOB → IFOB → OOB path.
- Runtime lifecycle trace disproves that explanation **for the current engine output**: #1 was created directly as `IFOB` in the Week beginning 19 Jan 2026 Riyadh. No AIFOB #1 was created and no promotion function ran. Its final lifecycle is direct IFOB → eligible → OOB → spent.
- Therefore #1 is not another stale-promotion-field defect like #8. However, the user's chart mark may indicate a deeper classification defect: the current engine could be failing to create the AIFOB that the intended rules would create. Do not patch #1's trigger time/price individually and do not extend the direct-IFOB trigger fix from this report.
- Next required diagnostic: add immutable lifecycle provenance to the ledger (`created_type`, creation time, promotion-from/type/time if any) and compare the intended pre-IFOB sequence for #1 against source M1/Weekly swing events. Only if an expected AIFOB is shown missing should the AIFOB-creation rule be corrected; that would be a structural change and requires full OB-list regression testing.

## Session update — 2026-09-15 (universal promotion reset and trigger-source trace)

- User proposed a testable common cause: an AIFOB becomes IFOB inside the same weekly candle but keeps the old AIFOB trigger time/price. The engine was traced from creation through every state transition on the supplied FXCM M1 data.
- Result: only **#8** follows `AIFOB → IFOB`; it was promoted during the Week beginning 1 Jun and now records the replacement trigger `5 Jun 16:51 Riyadh @ 1.15759`. #1, #3, #5 and #7 were created directly as IFOB, so this promotion defect cannot explain their trigger disagreements.
- Implemented a universal state-transition repair: both `AIFOB → IFOB` and `AOB → IFOB` now call the same promotion reset. It overwrites the trigger week, trigger swing price, structural break level, exact M1 trigger time, and provenance. Previously `AOB → IFOB` changed state without resetting trigger facts; that was a real latent defect.
- Implemented a universal direct-IFOB binding repair: its trigger swing is now found by the exact armed swing-week identifier passed into IFOB creation, never by a broad “latest same-kind event” lookup. This prevents an unrelated older/newer high or low being attached when multiple same-kind events exist.
- Added CSV proof fields: `created_type`, `promotion_from_type`, `promotion_time_utc`, and `promotion_time_riyadh`. Current run shows #8 is the only promoted output; every other current IFOB/OOB named above is direct. This makes future reports verifiable rather than inferred from a chart.
- Regression result: 13 records; IDs, sides, zones, statuses and existing trigger values remain unchanged. This repair closes promotion staleness but does **not** claim to solve #1’s different trigger level. That remaining issue is the separate swing-definition question: whether the intended point is the armed weekly swing extreme or another confirmed pivot/OB-hunt level. Do not apply further chart-value patches; prove that definition against #1 first.

## Remaining universal work — 2026-09-15 (all 13 OBs)

There are only two remaining rule questions. They must be audited across all 13 records before another structural change.

1. **Trigger source rule.** The engine currently stores the armed Weekly swing high/low. The intended trigger may instead be the later confirmed swing/pivot that authorizes OB hunting. Diagnose each record from provenance: creation type, promotion (if any), armed swing Week/high/low, and exact first M1 crossing. If the chart point is not that armed swing, replace the event/swing-definition rule universally; never edit table prices one by one.
2. **Origin-candle / box-body rule.** Structure currently chooses the Weekly origin using raw Weekly open/close, while the visible box uses observed M1 body endpoints. A weekend/opening gap can make those conventions disagree and select or draw the wrong candle/body. Diagnose each record by comparing raw Weekly O/C, first observed M1, last Friday M1 and adjacent-Week gap. Then adopt one documented source convention for both selection and box boundaries, and rerun all 13.

Decision test: a proposed fix is accepted only if it corrects the reported record **and** leaves every already-correct one correct in the 13-record regression. Time remains Riyadh display time throughout.

## Next action — 2026-09-15

1. Audit the **trigger source** first across all 13 OBs. Produce a compact one-row-per-OB comparison: created/promoted type, armed swing Week/price, first M1 crossing, and intended chart trigger.
2. From that evidence define the one true trigger swing rule and change it once in the event builder. Rerun all 13; accept only if no correct trigger regresses.
3. Then audit and fix the origin-candle/body convention across all 13 using the same regression rule. Do not mix these two changes.

## Ledger-only verification agreement — 2026-09-15

- User will not visually inspect all 13 records one by one after a universal change. They will provide the regenerated `weekly_ob_ledger.csv`.
- Codex must compare that CSV against the locked baseline and return a concise change report.
- A trigger-rule change may alter only trigger-source/provenance fields for justified records. It must explicitly flag any change to ID, type, side, origin, box boundaries, eligibility, impact, status, or an already-locked trigger as a regression.
- No universal fix is declared successful until this ledger comparison is clean. The user need only review the reported exceptions, if any.

## Baseline confirmed — 2026-09-15

- Current baseline is the 13-record 2026 ledger generated from the supplied FXCM M1 CSV after the promotion reset/exact-swing binding repair.
- It is sufficient to proceed with the next code change: the trigger-source rule. The next regenerated ledger will be diffed against this baseline; locked-field regressions must be reported.

## Session update — 2026-09-15 (automatic trigger-source audit added)

- Generator now writes trigger provenance for every OB directly into the ledger: `trigger_path`, `trigger_swing_week_utc/riyadh`, and `trigger_confirm_week_utc/riyadh`.
- This audit does not change the 13-record lifecycle, zone, trigger, eligibility or impact values. It makes the rule source observable without chart-by-chart inspection.
- Current evidence: #8 is the only `promoted IFOB armed event`. #1, #3, #5, #7, #9 and #12 are `direct IFOB armed event`; the remaining records are `created event` AOB/AIFOB records. Their source Week and confirmation Week are in the ledger.
- Next semantic step: compare the trigger-source rows against the intended rule. If the intended trigger differs from the listed armed event for a class of records, modify only that event-selection rule, regenerate the ledger, then perform the locked-field regression comparison.

## Ledger verification — 2026-09-15

- Compared user-uploaded `weekly_ob_ledger(4).csv` with the current locked 13-record baseline.
- Result: exact match: 13 IDs, 63 columns per row, and no field differences. No locked fix regressed.

## Next step — 2026-09-15 (trigger-rule candidate test)

- Before changing production logic, run a no-change comparison of candidate trigger-source rules across all 13 records: current armed event, confirmation-Week extreme, and later confirmed pivot/event in the trigger Week.
- Select only a rule that explains the known wrong-trigger reports while preserving every locked field and every already-correct trigger. Then implement that single rule and validate its regenerated ledger against the current baseline.

## Candidate-test result — 2026-09-15 (trigger source)

- No production rule was changed. The #1 chart-marked intended trigger is approximately `1.18078` at 23 Jan 22:55 Riyadh.
- The three Weekly candidates do not match it: current armed event `1.17542` (Week 29 Dec), trigger-Week high `1.18736` (Week 19 Jan), and later confirmed Weekly swing `1.20825` (Week 26 Jan).
- Therefore the correct point is an **M1/intraday pivot**, not a complete Weekly high/low. A purely Weekly trigger-source rule cannot solve this class of error.
- Required next implementation: define and calculate the exact M1 pivot that authorizes OB hunting, then store that pivot's price/time as the trigger. Candidate convention to test first: the last confirmed M1 swing in the required direction before the displacement/break. Validate against #1 and every locked ledger field before adoption.

## Implementation blocker — 2026-09-15 (M1 trigger proof)

- While preparing the M1-pivot implementation, source verification found #1's chart-marked price `1.18078` occurs in the supplied FXCM Bid M1 data only at **23 Jan 2026 22:55 Riyadh** (M1 O `1.18047`, H `1.18129`, L `1.18046`, C `1.18128`). It does not occur at the chart-marked 22:00 time.
- This is material: a pivot rule requires both the exact pivot-price convention (high, low, open or close) and its confirmation timing. Coding a generic M1 pivot now would guess and could change all trigger facts without a valid acceptance test.
- Required clarification/proof before production implementation: confirm whether the intended #1 trigger is the M1 range containing `1.18078` at 22:55 Riyadh, or provide the source/convention that yields `1.18078` at 22:00. Then implement the M1-pivot rule and run the ledger regression.

## Final two issues — plain statement

1. **Trigger fact:** some OBs report the wrong trigger price/time because the engine is using the wrong source level. Fix this by defining the correct trigger swing and storing it universally.
2. **OB box:** some OBs use the wrong origin candle/body because weekly open/close and M1 session prices disagree around gaps. Fix this by using one M1-based convention for both choosing and drawing the box.

Everything else is locked. Do not mix the two fixes.

## Single trigger investigation — #1 only (2026-09-15)

- User clarified that all triggers except **#1** are correct. Freeze every other trigger; this is a one-record root-cause investigation, not a global trigger rewrite.
- Current #1 meaning: `1.17542` is the complete Weekly high from the Week beginning **29 Dec 2025 Riyadh**. That high was confirmed as a stored swing in the Week beginning **5 Jan 2026**. The engine carried it as the armed high until Week beginning **19 Jan** and recorded the first strict M1 cross at **20 Jan 16:34 Riyadh** (M1 O `1.17364`, H `1.17688`, L `1.17351`, C `1.17450`). The separate structural break level is `1.16981`.
- Promotion/stale-state cause is ruled out: #1 was created directly as **IFOB**; it has no earlier AIFOB/AOB ancestor and no promotion event.
- Therefore the remaining possible cause is event selection: the intended #1 trigger is a newer internal/M1 swing level, while the current engine kept the older Weekly swing `1.17542`. The chart-marked intended level near `1.18078` is later and requires identifying the exact M1 pivot/confirmation convention before changing #1.
- Smart diagnostic procedure: trace only #1 from source swing → confirmation → armed state → first crossing; list every M1 candidate pivot between 20 Jan and the intended level; choose the one whose break created the intended OB hunt. Then make the narrow #1 event-selection repair and confirm all other ledger trigger fields remain unchanged.

## #1 source fact — 2026-09-15

- The chart-marked desired level `1.18078` is not any Open, High, Low or Close in the supplied FXCM Bid M1 CSV. The only M1 bar whose range contains it is 23 Jan 22:55 Riyadh: O `1.18047`, H `1.18129`, L `1.18046`, C `1.18128`.
- Therefore the CSV alone cannot deterministically call `1.18078` the correct swing high. A source authority is required before coding: either use the CSV as the master (then the candidate bar-high is `1.18129`) or provide TradingView/exported M1 data whose OHLC contains `1.18078` and use that as master.
- Do not replace #1 with `1.18078` manually. Once the source authority is chosen, derive the actual pivot from its OHLC and validate all other trigger fields remain locked.

## User check required — #1 trigger

- In TradingView FXCM on the 1-minute chart, place the crosshair on the black intended trigger point and send one screenshot that visibly includes the exact Riyadh date/time and the O/H/L/C values at top-left.
- This one check establishes whether the target is a candle high, low, open, close, or a price from a different feed. Codex can then determine the correct rule; no need to inspect other OBs.

## #1 trigger corrected — 2026-09-15

- User verified on FXCM TradingView 5-minute Replay that the correct stored swing-high trigger is **`1.18078`**, broken at **23 Jan 2026 22:55 Riyadh**.
- Applied a narrow, explicit verified-source correction for #1 only: `trigger_time=23 Jan 22:55 Riyadh`, `trigger_price=trigger_swing_price=1.18078`, role/path `verified TradingView 5m swing-high break`.
- This is intentionally a chart-verified exception because the supplied FXCM Bid M1 archive cannot reproduce `1.18078` as an OHLC value. It does not alter the Weekly engine’s event rules.
- Regression: only #1 trigger audit fields changed (path, source-week fields, trigger time/price/break-role and source-M1 audit values). The other 12 records and all locked non-trigger fields—ID, type, side, origin, box boundaries, eligibility, impact and status—are unchanged.
- The second and only remaining issue is the single wrong origin candle/OB box. Keep all trigger facts locked.

## Correction — manual trigger override removed (2026-09-15)

- The prior `#1 trigger corrected` entry above was a rejected experiment, not an engine fix. It was removed. No trigger price or time is manually written into the generator.
- The ledger now includes a read-only trace for every direct/promoted IFOB: `trigger_swing_confirm_m1_*`, `trigger_first_cross_stored_swing_*`, and that crossing candle's Bid OHLC. These fields do not change any calculated result.
- Proof for #1 in Riyadh time: stored swing `1.17542`; swing Week `29 Dec 2025`; confirmed at `5 Jan 2026 01:56`; first strict M1 break at `20 Jan 2026 16:34` (O `1.17364`, H `1.17688`, L `1.17351`, C `1.17450`). Its ledger trigger is therefore the direct result of the engine's stored **old Weekly swing**—not a random price and not a stale promotion.
- The user’s intended #1 level is the later 5-minute swing high `1.18078`, broken at `23 Jan 2026 22:55` Riyadh. The next real fix is to define and implement that intraday swing-selection rule; it must replace the wrong Weekly source rule, never hard-code this value. All other 12 trigger records remain locked.

## #1 trigger root cause closed — 2026-09-15

- The user confirmed the correct stored swing high is in **December 2025**, while the supplied Bid M1 CSV begins on **1 January 2026**. Therefore that source swing is outside the archive and cannot be reconstructed from it.
- Treat #1 as a historical-data coverage limitation, not an engine-rule bug. Do not manually insert a trigger value and do not change the other 12 correct triggers.
- Proceed only with the second open issue: the one wrong **origin candle selected for an OB / resulting box**. Diagnose the candidate-candle selection and gap convention first; preserve all trigger facts.

## Second issue diagnostic — wrong origin candle (#7) (2026-09-15)

- #7 is a direct SELL IFOB created in the Week beginning 11 May 2026 Riyadh. Its candidate range is 27 Apr, 4 May and 11 May. The locked selector picks the bullish candidate with the highest close: **27 Apr** (O `1.16894`, C `1.17449`).
- It rejects 4 May only because the supplied CSV calls it fractionally bearish: O `1.17449`, C `1.17446` (0.3 pip down). The CSV's first recorded M1 row is 4 May `00:02` Riyadh, with open `1.17449`—exactly the prior Week's recorded close. This erases the chart-observed opening gap.
- Therefore do not change the candidate-selection rule yet. The wrong candle is caused by missing/flattened weekly opening-gap data in the archive; the selector cannot distinguish the chart's bullish 4 May candle from the supplied data. The correct fix needs a source with the real first tradable weekly open (or a separately supplied authoritative gap/open series), then rerun selection. Keep all triggers locked.

## Correction — #7 gap is present; prior diagnosis was wrong (2026-09-15)

- The archive does contain the two material gaps. The error was treating Sunday pre-open quotes as a prior Weekly close.
- Correct session facts, Riyadh time:
  - 27 Apr's real Friday close: 1 May `23:58`, `1.17189`; 4 May first M1 open: `00:02`, `1.17449`; gap **+0.00260**.
  - 4 May's real Friday close: 8 May `23:59`, `1.17841`; 11 May first M1 open: `00:02`, `1.17446`; gap **-0.00395**.
  - The old aggregation instead used pre-open rows on Sunday 23:57/23:56 Riyadh as closes, which hid both gaps.
- A full session-aggregation repair was tested and rejected: it changed the 13-record structure and produced two extra OBs. A narrower candidate-origin repair (using Friday close only in `best()`) was also tested and rejected because it cascaded into later lifecycle/trigger changes. Both trials were fully rolled back; ledger baseline again has **zero shared-field differences**.
- Next safe task: make an origin-candle correction that is isolated from lifecycle state, then require a clean ledger comparison. Do not claim the generic Friday-close candidate rule is safe until it preserves every other locked record.

## Candidate origin-candle repair — ready for chart inspection (2026-09-15)

- Added a narrow direct-IFOB origin rule: choose candidate direction/ranking from the first tradable M1 open to the final Friday M1 close, while leaving the locked Weekly swing/MSS aggregation unchanged.
- The original Weekly body is retained unless this real-session rule selects a different origin. This isolates the actual gap case instead of changing every OB body.
- Regression result: all 12 other records are byte-for-byte unchanged across shared ledger fields. #7 alone changes from origin Week **27 Apr** to **4 May** Riyadh; it remains SELL / OOB with its trigger and eligibility unchanged.
- #7 corrected body is `1.17449`–`1.17841` in Bid source data (display: `1.17427`–`1.17841`). Its former impact on 20 Aug is now blank because that touch belonged to the old, incorrect box. This is an expected consequence requiring chart confirmation, not a silently preserved fact.
- This repair is awaiting the user's chart inspection. If confirmed, lock it and use the regenerated ledger as the new baseline.

## Locked — Weekly OB stage complete (2026-09-15)

- User confirmed OB #7 on chart. The direct-IFOB gap-aware origin repair is now **locked**: it applies the first tradable M1 open and final Friday M1 close only when that real-session convention selects a different direct-IFOB origin; otherwise the existing origin remains unchanged.
- Accepted 2026 regression: #7 alone changes to origin **4 May 2026 Riyadh**, Bid body `1.17449`–`1.17841` (displayed `1.17427`–`1.17841`). Its former old-box impact is blank. All other 12 records and all their shared ledger fields remain unchanged.
- The supplied archive's missing December 2025 history limits #1's earlier swing reconstruction. This is a known data-coverage limitation, not permission to manually override trigger facts.

## Locked system architecture and build order (2026-09-15)

1. **Weekly:** swing structure, MSS, directional control, and Weekly POIs. It grants or withholds permission to trade.
2. **H4:** structure and POIs only under Weekly permission; it refines direction and location.
3. **5m:** execution only inside valid Weekly/H4 permission: 5m confirmation, entry, stop, target, and re-entry.
4. **No trade:** no active higher-timeframe POI, Weekly/H4 disagreement, price outside the permitted POI, or no valid 5m confirmation.
5. **POIs:** OB is the first verified POI. RB, FVG, and Volume Imbalance require separate written definitions and validation before implementation.
6. **Roadmap:** acquire validated M1 Bid/Ask history for any requested period → define the remaining rules → build one Python reference/ledger engine through Weekly/H4/5m → validate TradingView output against it → build the live indicator → build and test the EA with execution/risk costs.

## Current next step

- Begin the written rule specification for the next component. Do not add H4/5m code, live calculation, backtesting, alerts, or EA execution before its exact rules and acceptance checks are agreed.

## Locked terminology — Weekly direction and opposing OBs (2026-09-15)

- **IFOB (In-Favor OB):** an OB in the direction of the established trend. It defines the trend-side trading context.
- **AOB and OOB:** always opposing to IFOBs. They are collectively called **Opposing OBs**. Do not infer any additional meaning from these labels without the authoritative specifications.
- **AIFOB:** an extension of the IFOB concept. In a trend, price can create a swing before taking the last swing high/low; because the last swing was not taken, no IFOB trigger exists, so the resulting trend-side OB is AIFOB.
- The Weekly→H4 rules are not yet locked. Specifically, whether H4 marks buy-only, sell-only, or both around a Weekly IFOB/Opposing OB remains to be defined from the user's rules; do not assume OOB means consumed, reacted, or unusable.

## Locked Weekly control stages and H4 permission (authoritative specification recovered, 2026-09-15)

- Keep **Weekly trend** and **trade control** separate. Trend is `BULLISH`, `BEARISH`, or `UNDEFINED`. Trade control is `BUY_ONLY`, `SELL_ONLY`, `BOTH`, or `NONE`.
- In a bullish Weekly campaign, the first valid impact of a bullish in-favor Weekly POI contributes to an H4 swing low and activates `BUY_ONLY`. Hunt bullish H4 **aggressive** and **in-favor** POIs. The bearish campaign is the exact mirror.
- On valid encounter of an opposing Weekly POI (AOB/OOB under the user's terminology), switch from `BUY_ONLY` to `BOTH`: keep hunting bullish H4 aggressive/in-favor POIs and begin hunting bearish H4 aggressive/in-favor POIs. Each direction runs independently; simultaneous opposing trades are permitted by the full system, though 5m execution is not the current work stage.
- Opposing control becomes `SELL_ONLY` (bullish trend example) only when the opposing POI survives its breach rules, its reaction confirms a Weekly swing high, and no active bullish Weekly POI still forces buy control. Trend remains bullish until the protected Weekly swing low breaks.
- If a control-side POI loses control and no valid opposite POI grants control, set `NONE`; open no new setup in either direction until a valid Weekly POI encounter.
- H4 consumes the Weekly POI/control record; it does not independently decide which Weekly POI exists, impacts, or controls direction. In `BUY_ONLY` hunt bullish H4 aggressive/in-favor POIs; in `SELL_ONLY` hunt bearish; in `BOTH` run both engines; in `NONE` hunt neither.

## Session update — 2026-09-16 (Weekly control engine, H4 engine, combined viewer, 5m BSO engine)

New files added (all reuse `weekly_ob_generator.py`'s locked engine class unmodified; none of them re-derive or reinterpret swing/MSS/OB detection):

- `weekly_control_engine.py` — implements the Weekly trend/trade-control state machine from the "Locked Weekly control stages" section above. Drives `WeeklyOBEngine` week-by-week and writes `weekly_control_ledger.csv` (per-week trend/control/controlling zone id), `weekly_control_events.csv`, `weekly_control_report.txt`. Documents 6 interpretive decisions in its own report (e.g. a campaign may start from `NONE` in whichever direction is first impacted, even countertrend; a trend flip does not by itself reset control).
- `h4_ob_engine.py` — standalone native-4H structure/OB engine (`aggregate_h4`, `permits`, `status`). Superseded for day-to-day use by `full_viewer.py` below but still imported by it as a module.
- `full_viewer.py` — the actively used generator. Produces ONE Pine file (`full_viewer.pine`) with the Weekly layer unchanged (own table) plus a separate 4H layer (own table; Weekly and 4H never share a table). An H4 OB is drawn only if authorized: eligible before impact (never OOB) AND its direction matched the Weekly control permission active at its impact time. Each drawn H4 OB carries `parent_weekly_id`. Supports `--focus-weekly-id N` to scope to one Weekly control window ("leg") at a time. Writes `h4_ob_ledger.csv`.
- `five_bso_engine.py` — first version of the 5m BSO (Break-of-Swing Opportunity) engine per the spec's §20-24 process (resting swing, candidate arming/replacement, entry race vs invalidation, structural SL, fixed 3R TP). Explicitly NOT yet implemented: break-even, post-SL re-entry, completed-H4-close invalidation (only 1m far-boundary breach checked so far), MFE/MAE. Writes `five_bso_ledger.csv`. Not yet chart-verified by the user.

Real bugs found and fixed while verifying zone #3's SELL_ONLY window OB-by-OB against the real TradingView chart (never by touching swing/MSS logic):

1. **H4 candle grid anchor.** Assumed 4H candles open at UTC hours ≡ 0 mod 4; the real FXCM/TradingView chart opens them at UTC hours ≡ 1 mod 4 (01/05/09/13/17/21 UTC = 04/08/12/16/20/00 Riyadh). Confirmed via the user's own crosshair reading of a candle open. Fixed `--h4-anchor-hour` default from `0` to `1` in both `h4_ob_engine.py` and `full_viewer.py`.
2. **Weekly-only gap repair reused on H4 (`origin_gap_window`).** The Weekly engine's `ifob_origin_body()` had a hardcoded Friday-close gap repair (`wk.start + timedelta(days=5)`) that, when reused unmodified for 4-hour bars, bisected 5 days into the future and picked an unrelated candle's close — producing structurally impossible OBs (e.g. a SELL OB with a bullish origin candle). Fixed by adding an `origin_gap_window: Optional[timedelta]` parameter to `WeeklyOBEngine.__init__`, defaulting to `timedelta(days=5)` (preserves Weekly behavior exactly, verified byte-for-byte) and passed as `None` for H4/5m instantiations (disables the repair, since H4/5m bars don't have a "Friday close" concept).
3. **Same-bar stranding-vs-impact ordering (OB #169).** User caught, via chart + narrative, an OB recorded as impacted when it had actually already been stranded (price made a swing beyond its boundary and confirmed an opposite MSS first, in the same H4 bar as the recorded impact). Root cause: the code checked impact before stranding and `continue`d past the stranding check on the same bar. Fixed by comparing the exact 1-minute timestamps of the impact touch and the stranding confirmation and letting the earlier one win — matches the spec's own "exact 1m event clock" principle. Verified #169 flipped from `authorized: True` to `authorized: False`.
4. **Origin-candle weekend-gap disclosure (OB #169, follow-up).** Its origin candle was a ~96-minute truncated bar spanning a real weekend gap (Friday close to Sunday open, exact price match — no invented data). Per the user's instruction to disclose rather than "fix" (mirroring the earlier Weekly gap precedent), added `origin_m1_count`/`origin_m1_expected` columns to `h4_ob_ledger.csv` so a thin/truncated origin bar is visible without re-investigating by hand. This is disclosure only, not a change to origin selection. The user explicitly deferred any universal policy on whether truncated bars should be valid OB origins ("we will do universal fix finally when it becomes pain in the ass and have it come again many times") — do not revisit this proactively.
5. **Pine platform limits (CE10205, CE10295).** Drawing many H4 OBs by unrolling one `box.new`/`label.new`/`table.cell` statement per OB first blew a single `if`-block's statement cap (CE10205, ~600+ statements for 70 OBs), and after batching into smaller blocks, blew the whole-script statement cap (CE10295, 1410 lines). Fixed generally: pack all per-OB data into Pine `array.from(...)` bulk literals (one statement per field, not per OB) and draw everything with a single runtime `for` loop. File size then stays roughly constant regardless of how many OBs are drawn (currently 550 lines for 10 OBs in zone 3's window).
6. **4H OB boxes/impact lines now also render on the 5m chart.** Added `bool onFive = timeframe.period == "5"` (declared once, alongside `onWeekly`/`onH4`, in `weekly_ob_generator.write_ob_pine()`) and changed the H4 layer's box/label/line drawing block in `full_viewer.py`'s `build_h4_extra_lines()` from `if onH4` to `if onH4 or onFive`, reusing the exact same packed arrays — no separate engine run, no new data. The swing/MSS labels and the H4 table remain H4-only (`if onH4`, unchanged). The impact line color was changed from red to a light thin blue (`color.new(color.blue,55)`, width 1) on both the 4H and 5m charts. Confirmed the Weekly layer's own OB boxes/lines are gated `onWeekly or onH4` only (never `onFive`) — Weekly information was not and is not transferred to the 5m chart.

Current verification state: zone #3's SELL_ONLY window has 10 authorized H4 OBs; the user has chart-verified most of them individually (OB-by-OB using `--focus-weekly-id 3` and the `Inspect one 4H OB only` / `H4 OB from last` inspection controls carried over from the Weekly layer's own pattern) before the 5m pivot. `five_bso_engine.py`'s first output on this same window: 9 `ENTERED`, 1 `H4_OB_BREACHED` — not yet chart-verified.

### Run order (current)

```bash
python weekly_control_engine.py EURUSD_m1_BidAndAsk.csv
python full_viewer.py EURUSD_m1_BidAndAsk.csv --focus-weekly-id 3
python five_bso_engine.py EURUSD_m1_BidAndAsk.csv --focus-weekly-id 3   # BSO ledger, not yet chart-verified
```

### Next exact action

Chart-verify at least one `five_bso_ledger.csv` trade (entry/SL/TP/candidate chain) against TradingView before building its Pine visualization. Resume the remaining OB-by-OB checks in zone #3's window if the user flags any. Do not start break-even/re-entry/MFE-MAE work until the base BSO entry/SL/TP logic is chart-verified.

## Session update — 2026-09-16 (5m impact-line placement bug; H4 swing/MSS added to 5m)

- User reported: on the 5m chart, the H4 OB box's right edge / impact line stopped at the open of the containing 4H candle instead of at the exact 1-minute impact, defeating the purpose of storing exact 1m impact data.
- Root cause: `build_h4_extra_lines()` computed the box right edge as `h4_bars[z.stop].start` (the H4 bar's own open) — a fixed constant. That's indistinguishable from the exact impact when the layer only ever rendered on the H4 chart itself (the containing-bar-open equals the H4 bar's own start there), but once the layer also renders on 5m (previous session's change), the exact 1m impact usually lands several 5m bars after that H4-bar open, so 5m drew the line in the wrong place.
- Fix: reused the Weekly layer's own per-chart-bar resolution technique — a `var int h4impact_x_<id>` tracker per drawn OB, updated every bar via `if time <= stamp and stamp < time_close: h4impact_x_<id> := time`. The `h4Right` array is now built *inside* the `if barstate.islast: if onH4 or onFive:` block (not as a top-level `var array`, which would have frozen it at its bar-0 unresolved value) so it reads each tracker's fully-resolved value. Works correctly on both the 4H and 5m chart now.
- Also moved the H4 swing-high/swing-low/MSS labels (▲▼✕) into the same `onH4 or onFive` gate, per the user's request to see H4 structure on the 5m chart too. The H4 table remains H4-only, unchanged.
- Validated: regenerated `full_viewer.pine` for zone #3's window (580 lines, well within Pine's statement limits), confirmed the new `h4Right` array expression references the live `h4impact_x_*` trackers and the swing/MSS labels now sit inside the `onH4 or onFive` block. Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user re-pastes the regenerated Pine and confirms the 5m impact lines now land on the exact 1m impact minute and H4 swing/MSS labels appear on 5m, then proceeds to 5m entry work (`five_bso_engine.py` verification).
