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

## Session update — 2026-09-16 (H4 swing/MSS reverted off 5m; wick invalidation replaced; entry-machine visualization added)

- User confirmed the impact-line timing fix works (chart screenshot), but flagged that the H4 swing/MSS labels (▲▼✕) added to 5m in the previous update were unwanted noise: "I want the 5m has its own [structure]... but it would be too much... what if we only show the ones that actually matter." Reverted `struct_lines` in `full_viewer.py`'s `build_h4_extra_lines()` back to `if onH4` only. The 5m chart now shows only the H4 OB boxes + correctly-timed impact lines, nothing else from H4.
- User then asked for a full explanation of the entry (BSO) logic before deciding what "actually matters" to draw on 5m. Explained `five_bso_engine.py`'s `run_bso()` step by step: the 5m bar containing the H4 impact → the resting swing (first confirmed 5m swing of the opposite-to-entry kind, inside the H4 OB) → the candidate (the most recent opposite-kind swing at/before the resting swing — the level whose break triggers entry) → the entry race (candidate replacement by newer swings vs. the break itself vs. invalidation) → structural SL (extreme qualifying resting-kind swing between the impact bar and entry) → fixed 3R TP → exit (first SL/TP touch after entry, `AMBIGUOUS` if both hit the same minute).
- **Real bug fixed, user-caught**: the far-boundary invalidation was a raw 1-minute wick touch (`m.l < far_boundary` / `m.h > far_boundary`), which could kill a setup on a wick that price later reclaimed and respected the zone from. User: "we do not want to miss this." Replaced with two **confirmed** conditions, whichever comes first: (a) a fully completed H4 candle whose **close** breaches the far boundary, or (b) a confirmed 5m swing of the resting kind whose own price already exceeds the far boundary (faster than waiting a full H4 candle, but still a confirmed swing, not raw noise). `run_bso()` now takes `h4_bars`/`h4_bar_starts` and reports `invalidation_reason` (`h4_close` or `swing_exceed`) and `invalidated_riyadh` in the ledger. On zone #3's window this changed OB #194 from a raw-wick breach to a `swing_exceed` breach — same outcome (`H4_OB_BREACHED`) on this dataset, but now for the right reason, and the other 9 still reach `ENTERED` unchanged.
- **New: the "entry machine" visualization**, 5m-only (`onFive`), added to `full_viewer.py` via `build_bso_extra_lines()`: for every drawn H4 OB whose BSO reaches `ENTERED`, draws (1) a **blue** horizontal line at the entry/candidate price from the moment that candidate became the active trigger (`candidate_since` — tracks candidate replacements, not just the original resting-swing time) to the entry minute, then (2) a **red** line (SL hit first) or **green** line (TP hit first) at that price from entry to the exact exit minute. Nothing is drawn for OBs that never reach an entry. `full_viewer.py` now also writes `five_bso_ledger.csv` for the same focused window as `h4_ob_ledger.csv`, so both ledgers and the Pine file come from one run.
- Per the user's explicit instruction, break-even and post-SL re-entry stay deferred until **after** MFE/MAE excursion tracking is recorded — do not build those next without that sequencing.
- Validated: regenerated for zone #3's window (593 lines total, well within Pine limits) — 9 `ENTERED` (blue + red/green lines each), 1 `H4_OB_BREACHED` (`swing_exceed`, no lines). CSV spot-checked: all 9 entries have SL/TP on the structurally correct side of entry price for a SELL setup, and exit prices exactly equal the recorded SL/TP price. Not yet chart-verified by the user.
- Next: user re-pastes the regenerated Pine, confirms the blue/red/green lines land where expected on the 5m chart for at least one trade, then decide next step (MFE/MAE first, per the deferral above, before break-even/re-entry).

## Session update — 2026-09-16 (5m BSO inspect-one toggle + lineage table)

- User confirmed the entry-machine lines land correctly (chart screenshot), and asked for two more things: (1) a per-attempt inspect toggle for the 5m chart, same as the existing "Inspect one 4H OB only" / "H4 OB from last" pattern, so each 5m BSO attempt can be isolated one at a time while the user reports back on each; (2) a table that shows only on the 5m chart, reporting the full lineage: Weekly OB (grandparent) → 4H OB (parent) → 5m entry (child) info.
- Implemented both in `build_bso_extra_lines()` (`full_viewer.py`): new `Inspect one 5m BSO only` / `5m BSO from last` inputs gate both the table row and the blue/red/green lines together (same rank-based mechanism as the H4 inspector: `bRank = array.size(...) - i`, `if not inspectOne5mBSO or bRank == bso5FromLast`). New top-left table (`onFive` only, 9 columns): Weekly OB, 4H OB, Side, Resting (Riyadh), Entry (Riyadh/price), SL, TP, Result, Exit (Riyadh/price). One row per BSO attempt in the focused window, not just the ones that reached an entry — an attempt that never entered (e.g. `H4_OB_BREACHED`) gets a row with the stage name in the Result column and no lines, instead of silently vanishing.
- `bso_results` tuples changed from `(z, it, res)` to `(z, it, parent_id, res)` throughout `full_viewer.py` (the parent Weekly zone id is what the table's "Weekly OB" column reads).
- Validated: regenerated for zone #3's window — 627 lines total, well within Pine limits. Confirmed OB #194 (the one `H4_OB_BREACHED` attempt) correctly shows `na` in both `bso5BLeft`/`bso5CLeft` (no lines drawn) and `"H4_OB_BREACHED"` in `bso5Result`, while the other 9 have real timestamps/prices. Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user re-pastes the regenerated Pine, tries the new 5m BSO inspect-one toggle and reviews the lineage table, then reports back per-attempt findings (per their own stated plan: "I will give you report on each one and we will fix the brokens").

## Per-attempt 5m BSO verification log (zone #3's window, 10 attempts, chart-confirmed one at a time)

- **5m BSO from last = 1 (OB #197, SELL)**: confirmed correct by the user (chart screenshot). Noted a small visual offset between the blue entry line and the red SL line's exact pixel placement, but the user said "no worries now" -- explicitly not asking for a fix at this time. Not a structural/logic defect report; do not investigate or change anything from this note alone. Revisit only if the user raises it again or it turns out to affect a real value (not just line rendering).
- **5m BSO from last = 2 (OB #194, H4_OB_BREACHED)**: user acknowledged as the "second" while reporting on the third; no defect raised.
- **5m BSO from last = 3 (OB #192, SELL)**: user raised three notes (see the next section for the full investigation and fixes). Not yet re-confirmed after those fixes.
- Remaining attempts not yet individually confirmed. Continue one at a time as the user reports back. Note: the ranking/count has since changed (13 attempts, not 10) after the re-entry work below -- re-share the regenerated Pine before continuing the from-last walkthrough.

## Session update — 2026-09-16 (OB #192 investigation: impact-time evidence, blue-line visibility fix, universal post-SL re-entry)

User's three notes on OB #192 (5m BSO from last = 3 at the time):

1. **"the red line I drew is the first actual impact of the 4H OB, I do not know why it is not considered"** -- investigated directly against raw M1 data. OB #192's zone is `1.16433-1.16479`. Walked every 1-minute candle from 26 May 11:00 through 13:14 Riyadh: nothing touches that band until **12:55** (`H=1.16437`), which exactly matches the recorded `impact_riyadh`. The nearest earlier approach is 12:34 (`H=1.16431`, still short). Reported this evidence back to the user and asked them to re-check their red line's exact placement (crosshair on 12:55) -- **awaiting user's re-check, not yet resolved either way**. No code changed for this item; it may turn out to be a chart misread (there is real precedent for that in this project) or may turn up something once the user re-verifies the exact candle.
2. **"the entry blue line is not visible to verify the stop order swing point placement"** -- real bug, fixed. Root cause: `candidate_since` meant "when this candidate became the one being watched" (the resting swing's confirm time, or a later replacement's confirm time) -- for #192 that window was only 3 minutes (13:02-13:05), well under one 5m bar, so the line was too short to see. Redefined `candidate_since` to the candidate swing's own bar formation time (`five_bar_starts[current.swing]`) in both `run_bso()`'s initial assignment and its replacement-loop reassignment. #192 went from a 3-minute span to 15 minutes (12:50-13:05); all other attempts' blue lines got longer/more meaningful too. Validated by regenerating and diffing `candidate_since_riyadh` across all attempts in zone #3's window.
3. **"we need to add re-entry rule here and make it universal. if price hits SL, and 4h OB is not breached yet we will trade, again and again until either it is breached or 4h swing point is confirmed"** -- SPEC.md SS27, previously deferred, now implemented as a universal rule. Before implementing, asked the user to choose between two candidate stop conditions (a confirmed 4H swing specifically breaching the far boundary, vs. any new 4H swing at all regardless of direction) rather than guess on a rule they explicitly wanted universal. **User chose: any new 4H swing point at all** (either kind -- high or low). Implemented as `five_bso_engine.py`'s `first_h4_swing_after()` (the confirm time of the first native-4H swing, of either kind, after the H4 OB's own impact -- a hard ceiling on future attempts) and `run_bso_chain()` (loops `run_bso()`, re-arming and searching again from the previous attempt's SL exit time, as long as that exit is before the swing-stop ceiling; stops on the first attempt that resolves to anything other than a plain SL). An attempt already in progress when the swing-stop ceiling passes is allowed to reach its own natural conclusion -- the ceiling only blocks *starting* a new attempt after it.
   - `five_bso_ledger.csv` and `full_viewer.py`'s 5m BSO table/inspector both now index per **attempt**, not per H4 OB -- an OB that re-entered contributes more than one row, labelled `(re-entry N)`. Zone #3's window went from 10 attempts to 13: OB #173 re-entered into a second breach, OB #192 and OB #197 each re-entered into a winning TP after their first SL.
   - Not yet chart-verified by the user for any of the 3 new re-entry rows.

All three fixes/changes validated by direct Python re-runs (raw M1 comparison for #1, before/after `candidate_since_riyadh` diff for #2, full ledger diff showing exactly 3 new rows with sane `swing_stop_riyadh`/`attempt` values for #3) and committed/pushed to `ict-trading-system`. Files sent to the user each time per their standing instruction to always receive the updated `.py` files in chat.

Next: user regenerates and re-pastes the Pine (note the "5m BSO from last" numbering has shifted -- 13 attempts now, not 10), re-checks OB #192's impact time against 12:55 Riyadh specifically, confirms the blue line is now visible, and starts chart-verifying the new re-entry rows alongside the remaining original attempts.

## Session update — 2026-09-16 (OB #192 impact-time: likely feed difference, set aside; real re-entry bug found and fixed)

- User re-checked OB #192's impact-time question directly against the chart: their own manual read of the 12:35 5m candle's high (1.16434) didn't match either our bid (max 1.16425 in that 5m window) or ask (max 1.16433) computation from the raw CSV. User's conclusion: **"this might be price difference. forget it now."** -- setting this aside as a likely feed/quote-construction difference (same class of previously-accepted discrepancy as the Weekly-stage investigations), not a defect to chase further. No code changed for this item.
- **Real bug found and fixed, user-caught, on OB #197's re-entry**: with `Inspect one 5m BSO only` the user compared attempt 1 (correct: entry 05-29 16:51, SL 17:49) against attempt 2 (entry 06-01 00:03, TP 06-05 17:43) and flagged the second as a "fake" trade -- by 06-01 the Weekly SELL swing low had already been confirmed, well past when we should have stopped re-entering.
  - Root cause confirmed directly from the ledger: attempt 2's resting swing formed at **05-31 23:25**, an hour *after* its own `swing_stop_riyadh` ceiling of **05-31 22:17**. `run_bso_chain()` only compared the *previous* attempt's exit time against the ceiling before launching the next search -- it never re-checked whether the *new* attempt's own resting swing landed past the ceiling once actually found. Since the search only advances to the previous exit time, a slow-forming resting swing could (and did) print well past the ceiling and still get accepted as a live trade.
  - Fix: each **re-entry** (`attempt_no > 1` only) is now validated after being computed -- if its resting swing is at/after `swing_stop_at`, it's converted to a disallowed `SWING_STOP_REACHED` stage instead of being accepted as ENTERED.
  - **Caught my own regression before shipping it**: the first version of this fix applied the check to *every* attempt including attempt 1, which immediately flipped 4 other already-validated original entries (OB #159, #181, #186, #190) to `SWING_STOP_REACHED` too -- because a 4H swing forms constantly, so almost any OB has one within hours of impact. Re-ran and caught this via the stage-breakdown count jumping from 1 disallowed attempt to 5 before appending anything to the ledger. Restricted the check to `attempt_no > 1`; re-ran and confirmed exactly 1 disallowed attempt (OB #197's #2) with all 10 original attempt-1s restored to their prior results.
  - Validated: zone #3's window now shows 10 `ENTERED`, 2 `H4_OB_BREACHED`, 1 `SWING_STOP_REACHED` (13 total attempts, same count as before -- only the stage of #197's second attempt changed). Confirmed in the generated Pine that `bso5BLeft`/etc for that attempt's array index is `na` (no blue/red/green lines drawn for it), while the table row still shows it with `SWING_STOP_REACHED` in Result (disclosed, not dropped).
- Also moved the 5m BSO table from top-left to top-right per the user's request. Confirmed no collision with the Weekly ledger table (also top-right) since the two never render on the same chart timeframe (`onWeekly` vs `onFive`).
- Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user regenerates and re-pastes the Pine, confirms OB #197 now shows only its original SL attempt with no fake re-entry, confirms the table now renders top-right, and continues the per-attempt chart verification.

## Session update — 2026-09-16 (re-entry reporting rule: no row at all for a failed re-entry)

- User saw the disclosed `SWING_STOP_REACHED` table row for OB #197's disallowed re-entry and said: "there should be no re-entry report not even in table if there is no second opportunity after SL." Overrides the earlier disclosure-not-drop instinct specifically for this case.
- Implemented in `run_bso_chain()`: a re-entry (`attempt_no > 1`) that never actually reaches `ENTERED` -- for any reason (breached, swing-stop-reached, no resting swing, etc.) -- is no longer appended to the returned attempts list at all. It's still computed and used internally to decide the chain should stop there; it just produces no ledger row and no table row. The OB's original first attempt is always reported regardless of its own outcome (that's the OB's own result, not a re-entry, so it stays visible the same way OB #194's `H4_OB_BREACHED` always has).
- Validated: zone #3's window went from 13 total rows to 11 -- OB #173's failed re-entry (was `H4_OB_BREACHED`) and OB #197's disallowed re-entry (was `SWING_STOP_REACHED`) both dropped entirely; OB #192's genuine winning re-entry (attempt 2, TP) and OB #194's original breach both correctly still show, since neither is a "failed re-entry."
- Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user regenerates, confirms OB #197 and OB #173 show only their single original attempt with nothing else in the table, and continues the per-attempt chart walkthrough.

## Session update — 2026-09-16 (self-caught mistake corrected: swing-stop ceiling restored to the original entry; SL pips added)

- User confirmed OB #197's entry (attempt 1) correct, asked for one display change: the 5m BSO table's SL column should show risk in pips ahead of the price, separated by `/` (e.g. `6.5/1.16527`). Implemented in `full_viewer.py` (`risk / 0.0001` for EURUSD's 0.0001-per-pip convention, one decimal place).
- Second report, on **OB #190**: user drew a marker showing the 4H OB looked breached shortly after impact, yet the system still produced an entry almost a week later. Investigated directly: OB #190 impacted 2026-05-22 16:09, but its resting swing didn't form until **2026-05-28 13:34** -- nearly 6 days later -- while a new native 4H swing had already confirmed within the hour, at **2026-05-22 17:01**.
- **This exposed a mistake I need to own.** Earlier today (see the swing-stop-ceiling session update above), I built the ceiling check to apply to *every* attempt, saw it flag OB #159/#181/#186/#190's original entries, assumed without checking that this was a false-positive regression ("a 4H swing forms constantly, so this would veto valid entries"), and restricted the check to re-entries only (`attempt_no > 1`) on that unverified assumption. OB #190's report proved that assumption wrong. Checked the data for all three previously-"reverted" OBs directly: #159 (resting 12 hours after its own swing-stop ceiling), #181 (~15.5 hours after), #186 (~4.5 days after) -- the exact same staleness pattern as #190, confirming all four were genuine defects, not false positives. Cross-checked the 6 OBs that were never flagged (#167, #173, #175, #192, #194, #197): every one has its resting swing form *before* any subsequent 4H swing, so restoring the check doesn't touch them.
- Fix: removed the `attempt_no > 1` restriction -- the swing-stop ceiling now applies to the original attempt too, exactly as it did in my first (wrongly reverted) version, now backed by verified evidence instead of an assumption.
- Validated: zone #3's window -- #159, #181, #186, #190 all move from a stale `ENTERED`/SL to `SWING_STOP_REACHED` (still reported in the table, since it's the OB's own original result; only *failed re-entries* get dropped entirely per the separate rule from earlier). The 6 unaffected OBs, plus OB #192's genuine re-entry, are unchanged. 11 rows total (same count as before -- only 4 of the attempt-1 stages changed).
- Lesson for future work in this file: when a check flags something and the explanation "that must be a false positive" isn't backed by pulling the actual data for the specific flagged cases, don't revert on that basis alone -- check first, exactly as this project's own long-standing discipline (evidence before code changes) already requires.
- Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user regenerates, confirms OB #190 (and #159/#181/#186) no longer show a stale entry, confirms the SL column's new pips/price format, and continues the per-attempt chart walkthrough.

## Session update — 2026-09-16 (invalidation rule replaced with a precise MSS-based one; two crude approximations corrected)

- User, reviewing OB #186 (now `SWING_STOP_REACHED`): "I think we do not have swing point breach unless you confuse it [with] OB box breach... this is what I was talking about when I said we will keep trading if price exceeded the OB box zone but did not break the supporting swing or confirm another 4h swing before entry or closed body inside the OB zone."
- This corrected TWO separate approximations that had accumulated over the day, both wrong in the same direction (too generic):
  1. The 5m "swing exceeds the far boundary" condition (from the earlier wick-invalidation fix) was a crude proxy for a structural break, not the real thing.
  2. The re-entry ceiling ("any new 4H swing at all, either direction") was even further off -- a 4H swing forms constantly and has no necessary relationship to whether *this* OB's own structure is still intact.
- Asked the user two clarifying questions before touching code (per this project's standing discipline -- a business rule redefinition, not a bug, so guessing would have meant building the wrong thing a third time):
  1. Which swing is "the supporting swing"? Answer: "we have downtrend, IFOB with swing high above it that if broken will change MSS to up. that is it." -- i.e. the specific 4H swing whose break flips the native MSS state against the OB's bias, not just any swing.
  2. Does "closed body inside the OB zone" mean a separate condition from "closed body outside"? Answer: "all POIs except FVG invalidate if candle closes inside or outside (after going through it) its zone. if 4h candle closes body in the 4h OB, that is invalidation" -- i.e. a single widened condition: a completed 4H candle closing its body ANYWHERE at or beyond the near boundary (inside the zone counts exactly the same as beyond it).
- Implemented in `five_bso_engine.py` as one canonical `structural_invalid_at()`, replacing both approximations:
  - `mss_confirm_time()`: exact 1m confirmation time for a native-4H MSS event, resolved the same way the locked engine itself finds a promoted trigger's exact minute (scan the confirming H4 bar's own minutes for the first strict cross of the broken swing's price) -- MSS objects only carry a bar index (`.at: int`), not a datetime, unlike `Event.at`, so this had to be computed fresh.
  - `structural_invalid_at()`: returns `(time, reason)`, whichever of `h4_close` (a completed H4 candle's body closes at/beyond the **near** boundary -- the side price approaches from; previously the check used the **far** boundary, which only caught full breakouts, not mitigation-by-close-inside) or `mss_break` (a confirmed MSS against the OB's own bias -- `mss.up != z.bullish`) happens first, computed once from the OB's own impact time.
  - This single value now drives BOTH `run_bso()`'s within-attempt invalidation and `run_bso_chain()`'s re-entry ceiling -- previously two separate, cruder mechanisms. `run_bso()` simplified: no longer takes `h4_bars`/`h4_bar_starts` or computes anything itself, just receives the precomputed value.
  - `full_viewer.py` mirrors the same call (`bso.structural_invalid_at(...)`), and its per-attempt table/ledger now report `invalidation_reason` as `h4_close` or `mss_break`.
- Validated on zone #3's window: #159 and #181 keep `H4_OB_BREACHED` (now with an exact reason instead of a guess). #186 and #190 both come back `H4_OB_BREACHED` via `mss_break` at the **exact same timestamp** (2026-05-22 16:11:00) -- not a bug: one bullish 4H MSS correctly invalidates every still-pending SELL OB that depended on that same swing high staying intact. **#194 flips from breached to entered** under the corrected rule -- the old crude "5m swing exceeds far boundary" check was wrongly invalidating it; needs a fresh chart check since this is a reversal, not just a refinement.
- Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user regenerates, re-checks OB #186/#190's MSS-break reasoning against the chart, and specifically checks OB #194 since its verdict flipped.

## Session update — 2026-09-16 (correction: the #186/#190 "same MSS, not a bug" note above was itself wrong)

- **Correcting the previous entry's claim.** It asserted #186 and #190 sharing the same `mss_break` timestamp was "not a bug... one bullish MSS correctly invalidates every pending SELL OB" -- stated without actually checking the swing's price against each OB's own zone. That assertion was itself made the same way the earlier "false positive" mistake was: plausible-sounding, unverified.
- User regenerated, still saw #186 breached (via an old cached Pine showing the now-removed `SWING_STOP_REACHED` label, but the underlying verdict -- no entry -- was unchanged in the current code too) and asked for a deep investigation.
- Investigated directly: the shared MSS at 2026-05-22 16:11:00 breaks a swing priced at **1.16166**. #190's zone is `1.16140-1.16147` -- that swing sits genuinely above it, a legitimate protecting swing. **#186's zone is `1.16218-1.16233` -- that same swing sits below #186's zone entirely.** Price never even traded back up near #186 when that MSS confirmed. `structural_invalid_at()` had no check that the broken swing was structurally related to the specific OB being evaluated -- it just took the first opposing MSS anywhere after impact.
- Fixed: filter MSS candidates to only those whose broken-swing price sits on the OB's own protecting side (above `zt` for SELL, below `zb` for BUY) -- directly implementing the user's own description ("a swing high ABOVE it").
- Re-verified #186 against raw H4 OHLC after the fix: it is **still correctly** `H4_OB_BREACHED`, but now via `h4_close` -- the 2026-05-25 00:00 Riyadh H4 candle (`O=1.16354 H=1.16486 L=1.16272 C=1.16363`) closed its body at 1.16363, fully above the zone's top (1.16233), a genuine close-through-and-beyond a full day before #186's resting swing even formed on 05-26. #190 is independently re-confirmed legitimate under the new filter (its zone genuinely sits below the broken swing).
- Lesson, again: a plausible explanation for a surprising result ("that's probably fine, structurally makes sense") is not verification. Pull the actual numbers for the specific case before writing "not a bug" into this file.
- Not yet re-confirmed on the actual TradingView chart by the user.
- Next: user regenerates with the newest files, re-checks #186 specifically against the 2026-05-25 00:00 Riyadh H4 candle's close, and continues the per-attempt walkthrough.

## Session update — 2026-09-16 (real defect found: resting swing was wrongly required to print strictly inside the OB zone; requirement dropped)

- User pushed back on the h4_close evidence above, correctly: "we are not even in 25th of May, that one was totally wrong because it came days after the 4h OB was breached, it shouldn't exist at all. I am talking about the entry after the impact of the 4h OB, this one which occurred on 21 May 2026. there is no record of it." -- i.e. the real complaint was never about the 25 May candle; it's that #186 has NO recorded entry attempt anywhere near its own 21 May impact at all.
- Investigated directly: enumerated every confirmed 5m swing high after impact and checked which ones fall inside #186's zone (`1.16218-1.16233`, only 15 pips wide). **None do**, for 5 days. The closest approaches were 1.16237 (4 pips above the top) at 21:42 and 1.16211 (7 pips below the bottom) at 22:54, both on 21 May itself -- real, close reactions that the strict `z.zb <= ev.price <= z.zt` containment check in `run_bso()`'s resting-swing search was excluding. The first swing that ever lands strictly inside the narrow zone is 26 May -- explaining exactly why #186's only recorded attempt was that stale, 5-day-late one.
- User's rule, stated plainly: "simply the swing rest is not strict to inside OB box zone. it can be outside. we only want to happen after impact and before breaching the supporting zone or closing the 4h candle with body." I.e. no zone-containment requirement on the resting swing at all -- only two bounds: after impact, before `structural_invalid_at()` (the h4_close/mss_break rule from the previous update).
- Fixed: removed the containment filter from `run_bso()`'s resting-swing search entirely. It's now simply the first swing of the needed kind confirmed after impact. The "before breaching" bound was already enforced by `run_bso_chain()` (which rejects any resting swing at/after `invalidated_at`), so no new check was needed there.
- Validated: #186 now enters at 2026-05-21 21:43 (barely an hour after its own impact) and wins to TP by 2026-05-22 10:02 -- exactly the entry the user expected to see recorded. Zone #3's window overall: 11 attempts -> 15, 6 `ENTERED` -> 14 `ENTERED`. Several OBs (#159, #181, #194) now show multiple genuine re-entries they didn't have before, since entries now happen much sooner after impact, leaving more room before each OB's own invalidation ceiling. This is a substantially more active dataset than any prior run in this project -- expect the per-attempt chart walkthrough to effectively restart.
- Not yet chart-verified by the user.
- Next: user regenerates with the newest files, confirms OB #186's new entry (21:43 on 21 May, TP) against the chart, and resumes the per-attempt walkthrough on this much larger attempt set.

## Session update — 2026-09-16 (two compounding bugs: OB #194 entered after its own impact candle closed through the zone)

- User, reviewing OB #194's re-entry (attempt 2): "the re-entry here is in the 4h candle after the 4h candle that impacted the OB closed with body. the 1st trade is exactly at the open of the next 4h candle at 0400 after the 0000 candle that impacted the OB closed with body. so technically, these two trades do not exist and they are invalid. are you applying the 4h candle body close rule here or you just relaxed the 5m swing resting and used the 4h supporting swing as breach only?" -- a direct, specific question about which rule was actually running, not a vague complaint.
- Investigated directly and found the answer was neither -- both rules were supposed to be active, but the h4_close half had a real bug. OB #194's own impact-containing 4H candle (2026-05-27 00:00-04:00 Riyadh) closes at **1.16377** -- above both `zb` (1.16293) and `zt` (1.16360). The OB was impacted (01:01) and closed fully through the zone on the SAME 4H candle. That should have invalidated it immediately, yet the system produced an entry at 04:00:00 and a re-entry after.
- Two compounding bugs, both real:
  1. `structural_invalid_at()`'s h4_close scan started at `bisect_left(h4_bar_starts, it)` -- the first bar starting AT OR AFTER the impact. Since impact almost always falls mid-candle (01:01, not 00:00 or 04:00), this skipped the very candle containing the impact entirely -- exactly the candle most likely to close through the zone right as the OB gets touched. Fixed to start from the bar that CONTAINS `it` (`bisect_right - 1`), the same pattern `run_bso()` already uses for `start5`.
  2. Even after that fix, `structural_invalid_at()` correctly computed `invalidated_at = 2026-05-27 04:00:00` -- but that's the *exact same minute* as the entry. `run_bso()`'s entry-race loop checked "did price break the candidate" BEFORE "are we invalidated" within that shared minute, so the break check won the tie and let the entry through anyway. Fixed by reordering: invalidation is now checked first, every iteration.
- Validated: OB #194 now correctly shows `H4_OB_BREACHED` via `h4_close` at exactly 2026-05-27 04:00:00 -- no entry, no re-entry, matching the user's exact expectation. Zone #3's window: 13 attempts -> 13 total rows, but `ENTERED` 12 -> 11 and `H4_OB_BREACHED` 1 -> 2 (both of #194's previously-counted attempts collapse into one correctly-disallowed record). All other OBs' verdicts checked and unchanged.
- Not yet chart-verified by the user.
- Next: user regenerates with the newest files, confirms OB #194 now shows no entries at all, and continues the per-attempt walkthrough.

## KNOWN ISSUE — recurring ~3-pip feed discrepancy between our computed prices and the user's live TradingView chart (flagged 2026-09-16, unresolved)

- The user has now hit this twice (OB #192's near-miss impact investigation, and OB #181's 07:10-07:20 "right impact" investigation): a value we compute from the raw CSV and mark on the generated Pine is consistently **off from what the user's live FXCM TradingView chart shows by roughly 3 pips**. For OB #181 specifically: our raw bid data peaks at 1.16258 during the window the user pointed at, one pip short of the zone boundary (1.16259); the user's chart evidently shows this as an actual touch.
- **User's explicit instruction:** document this clearly now; do not attempt to fix it yet -- "we will deal with it when time is appropriate." Do not silently work around it, guess at a correction factor, or re-litigate it on every future near-miss without being asked. When a future investigation turns up a small (~1-4 pip) discrepancy between our raw-CSV numbers and the user's live chart reading, treat this as the known, already-flagged cause rather than a fresh mystery -- state the numbers, note the likely feed/quote-construction difference, and move on unless the user asks to dig into the root cause.
- Not yet diagnosed: whether this is a bid-vs-ask quote-side mismatch (the CSV column selected is Bid; the live chart may be showing something else depending on FXCM's default), a genuinely different historical vs. live feed reconstruction, or a display/rounding difference. No investigation has isolated the exact mechanism yet.

## Session update — 2026-09-16 (OB #167: real weekend-gap reopening, not a bug -- explained, not fixed)

- User: "make sense of 3rd May having a trade while it was Sunday" -- OB #167's resting swing (22:51) and entry (23:31) are both timestamped 2026-05-03, which is indeed a Sunday.
- Investigated directly and confirmed this is real, genuine market data, not a synthetic artifact or a timestamp bug:
  - The raw CSV has a real gap immediately before it: the previous row is Friday 2026-05-01 23:58 Riyadh (close `1.17189`), and the next row is Sunday 2026-05-03 22:24 Riyadh (open `1.17189` -- an exact match to the prior close, the same clean, non-invented gap-open pattern already established and accepted throughout this project's earlier Weekly-gap work). That's a genuine ~46.5-hour weekend closure, exactly as expected for FX.
  - The Sunday-evening rows themselves are real tick-backed data (`ticks` counts of 1-26 per minute, prices genuinely moving, e.g. 1.17189 -> 1.17334 in the first minute) -- not flat/duplicated placeholder rows.
  - This is simply the market's normal weekend reopening. FX trading resumes Sunday evening in most of the world (Sydney/early Asian session) even though the "officially" quoted convention is "5pm New York Sunday" -- which, converted to Riyadh (UTC+3, well ahead of New York), lands in the very early hours of the *next* calendar day there. A Sunday-evening candle on an FXCM Riyadh-time chart is completely normal, not an anomaly.
  - One real, minor finding from this check: this project's own Weekly boundary (`America/New_York` 17:00, i.e. Riyadh **00:00 Monday**) places this reopening session in the tail of the *previous* week rather than the start of a new one -- the actual feed's first reopening tick (22:24 Riyadh Sunday) arrives about 1.5 hours before our modeled week-start boundary. This doesn't affect OB #167's own validity (H4/5m structure uses its own native time grid, not the Weekly boundary), but it's a real, small mismatch between our modeled week-open convention and this feed's actual reopening timing -- noted here, not chased further unless it recurs somewhere that actually matters (e.g. right at a Weekly-control transition).
- No code changed. This was an evidence-based explanation, not a defect.

## Locked rule — same-candle impact-and-blow-through entries stay valid until the candle's confirmed close (2026-09-16)

- User flagged OB #159's two entries (05:06 and 07:12 on 2026-04-27) as invalid, believing they came after the OB's own supporting structure had already broken. Investigated: OB #159's impact-containing 4H candle (04:00-08:00) opens already inside the zone (`1.17156`), never returns, and closes at `1.17263` -- fully above `zt` (`1.17188`), a genuine one-candle sweep-and-blow-through. `structural_invalid_at()` correctly computes `h4_close` invalidation at **08:00:00**, the candle's own close. Both entries (05:06, 07:12) happen chronologically *before* that close.
- This is a materially different situation from the OB #194 bug two updates above: there, invalidation and entry landed on the *exact same minute* (a real ordering bug, fixed). Here, the entries genuinely precede the candle's close by 1-3 hours -- there was no tie, and no bug in the mechanical sense.
- Asked the user directly: should the WHOLE impacting candle be retroactively off-limits once we know (from its own eventual close) that it blows through the zone -- even for entries that happened before that close was confirmed -- or does invalidation only take effect from the moment the close is actually known?
- **User's answer: only from the confirmed close onward.** Current behavior is correct and is now locked as the rule: an entry taken before an invalidating candle's own close remains valid, since the close wasn't knowable at that moment (matches this project's own long-standing "exact 1m event clock, no lookahead" discipline). Do not revisit this for a similar-looking same-candle case without new evidence -- this is a decided rule, not an open question.
- At the time of that update, no code changed and OB #159's two attempts stood as correctly computed. **This was revised in the very next update below** -- a separate, independent mechanism (swing_break) turned out to invalidate #159 much earlier than either the locked h4_close decision or that "no code changed" note anticipated. The locked h4_close decision above (invalidation only from a candle's confirmed close, never retroactively) remains correct and unchanged -- it's still true that h4_close alone doesn't invalidate #159 before 08:00. What changed is that swing_break, a *different* rule, independently fires much earlier.
- The "gap" the user also mentioned for this OB is the same normal Friday(24th)->Sunday(26th) weekend closure documented in the #167 update just above -- not a new or separate issue.

## Session update — 2026-09-16 (swing-break invalidation generalized beyond formal MSS -- real bug, two OBs affected)

- User: "are you focusing only on one invalidation rule and looking the other for the other? what about exceeding the supporting swing point mid candle, we stop trading here the minute that happens." Asked me to verify the mss_break mechanism was actually behaving as "instant, mid-candle" and not secretly delayed like h4_close. Verified directly on OB #190: `structural_invalid_at()` returns `mss_break` at 2026-05-22 **16:11:00**, and the confirming 4H candle spans 16:00-20:00 -- genuinely 11 minutes in, nowhere near that candle's close. Confirmed both `run_bso()`'s entry race and `run_bso_chain()`'s ceiling check use that exact timestamp directly, not any candle boundary. Reported this back as evidence the two rules are correctly, intentionally different (h4_close needs a confirmed close; swing_break is knowable instantly).
- User's follow-up caught the actual gap: "well, it is not necessarily mss-break, got it? for example, here, 190 is AOB, meaning we are uptrend, so price took the supporting swing high, this is not MSS to up and it does not have to be, but our whole pull back leg is blown and our OB is no longer there."
- Investigated: the old `mss_break` mechanism only fired when the core engine's own regime-tracking happened to *also* classify the swing break as a formal MSS. For #190 this was true, but by coincidence -- the engine was still in a "down" regime at that exact moment. The real, general point: a SELL OB sitting inside an *already-local-uptrend* pullback has no down-regime left to shift FROM, so the core engine would never register "MSS to up" for a plain continuation swing there -- even though the specific swing supporting that OB was genuinely taken out.
- Fixed by replacing the MSS-dependent check with a direct, MSS-independent one: the swing currently protecting an OB is simply the last confirmed native-4H swing of the protecting kind (high for SELL, low for BUY) at or before impact; invalidation is the exact 1-minute moment price first crosses that swing's own price afterward. Same "instant, mid-candle" causal treatment as before, just no longer gated on formal MSS classification. `structural_invalid_at()` now takes `h4_engine.events` (every swing) instead of `h4_engine.msses`; `mss_confirm_time()` was removed as dead code.
- Validated: #190 unchanged (still 16:11:00, `swing_break` instead of `mss_break` -- same number, correct reasoning now). Found a second, genuinely new case this generalization catches: **OB #159's protecting swing high (1.17227, confirmed the night before at 22:05) is crossed exactly ONE MINUTE after its own impact** -- 2026-04-27 04:01:00, `H=1.17256` vs the swing's `1.17227`. #159's pullback leg was blown through almost instantly. This directly supersedes the "no code changed, #159's two entries stand" conclusion in the update immediately above -- #159 now correctly shows `H4_OB_BREACHED` (via `swing_break`) instead of two entries. The locked h4_close-only decision from that update is untouched; this is a different, independent rule catching a case h4_close alone never could have.
- Not yet chart-verified by the user.
- Next: user regenerates, re-checks OB #159 (should now show no entries, invalidated 1 minute after impact) and OB #190 (unchanged verdict, new reason label), and continues the per-attempt walkthrough.

## Session update — 2026-09-16 (zone #3's window declared done; MFE/MAE added; forward plan agreed)

- User confirmed zone #3's SELL_ONLY window is otherwise fully correct now -- the only two open items are the Sunday-reopening question (already explained as real, §"OB #167" update above) and the two early-impact near-misses attributed to the known ~3-pip feed discrepancy (already flagged as a documented, deferred known issue). Asked for a forward plan.
- **Plan agreed, in order:** (1) MFE/MAE tracking -- done this update; (2) break-even (SPEC.md SS25), now that MFE/MAE data exists to inform it; (3) post-SL re-entry is already built, no further work; (4) expand beyond zone #3 -- verify at least one BUY_ONLY leg and one more SELL_ONLY leg the same OB-by-OB, entry-by-entry way, since everything validated so far is proven on only one leg; (5) full historical backtest across the whole dataset once multiple legs are individually verified; (6) the live/real-time engine -- everything built so far is the historical Python+static-Pine path only, explicitly not the final live indicator per the original handoff's own architecture split (section 2); (7) EA/execution, only after the live indicator is validated against this same reference engine.
- Implemented MFE/MAE (SPEC.md SS34) in `five_bso_engine.py`'s `run_bso()`: for every ENTERED attempt, tracks the best (MFE) and worst (MAE) price reached between entry (exclusive) and exit (inclusive) -- same 1m-OHLC-ordering exclusion rule already used for exit resolution. Reported as pips in the ledger (`mfe_pips`/`mae_pips` columns) and as one combined "MFE/MAE (pips)" table column in `full_viewer.py`, per the user's explicit "assign it to one column" instruction.
- Also added, per the user's request ("it would be amazing if you can draw the order mark with the green on the profit side and red on the loss side starting from the entry and stopping on whichever comes first, win or loss"): a filled box from (entry time, entry price) to (exit time, exit price), green if TP hit first, red if SL hit first. **Correction mid-turn**: my first version replaced the existing SL/TP horizontal lines with this box; the user immediately corrected -- "I did not say replace the lines of TP and SL. we need them as well" -- so the box was added alongside the existing lines, not instead of them. Both now render together.
- Validated: regenerated for zone #3's window (637 lines, well within Pine limits). Spot-checked MFE/MAE for OB #167 (TP win): 38.9 pips favorable excursion, 2.0 pips adverse -- sane numbers for a winning trade. Both the SL/TP lines and the new box confirmed present in the generated Pine.
- Chart-verified by the user (OB #167, the same TP win used as the spot-check above): table and lines render correctly, but two things needed fixing.

## Session update — 2026-09-16 (two-sided MFE/MAE excursion box; five_bso_ledger.csv made a full trade database)

- User feedback on the chart-verified render: (1) "the box should always have the two sides, for example here we want to see the red part above to see it from the entry intersecting with the green until the SL" -- the single win/loss-colored box (green-only for a TP, red-only for an SL) was hiding the actual MFE/MAE excursion; a TP winner that nearly stopped out first looked identical to one that never came close. (2) Asked me to explain MFE/MAE concretely. (3) Asked for `five_bso_ledger.csv` (and the weekly/4H CSVs) to carry "every single tiny detail" needed to use them as a real trade database.
- Fixed the box: it now always draws **two** boxes per entered attempt, both anchored at (entry time, entry price), regardless of outcome (including OPEN/AMBIGUOUS, not just SL/TP): a GREEN box up to the actual MFE price reached, and a RED box up to the actual MAE price reached, ending at `excursion_end_time` (the exit minute when resolved, or the last minute of available data if still OPEN -- new field on `run_bso()`'s return). The original SL/TP horizontal line (entry to exit, at the exit price, red/green) is untouched, per the earlier "keep the lines too" correction. Concretely for OB #167 (SELL, entry 1.17454, SL 1.17579, TP 1.17079, won): the green box runs from 1.17454 down to 1.17065 (38.9 pips), the red box from 1.17454 up to 1.17474 (2.0 pips) -- meaning price briefly went 2 pips against the entry before reversing hard and running the full 38.9 pips to TP. The red box is what makes that near-miss visible; the old single-color box could not show it at all.
- MFE/MAE explanation given to the user directly: **MFE (Maximum Favorable Excursion)** is the best price the trade ever reached in its favor after entry, whether or not the trade actually captured it. **MAE (Maximum Adverse Excursion)** is the worst price it ever reached against the entry. Both are measured from entry (exclusive) to exit (inclusive), or through all available data if still OPEN. They answer a question the win/loss result alone can't: how much room did this trade actually have, and how close did it come to failing, even on a winner? A trade that wins with MAE near its full risk (e.g. OB #167's 2.0 pips out of 4.4 pips risk -- not this close, but the shape of the question) is fragile in a way a trade that wins cleanly with near-zero MAE is not; that distinction is invisible in the SL/TP/result columns alone.
- `five_bso_ledger.csv` rebuilt as a self-sufficient trade database: added `h4_ob_bottom`/`h4_ob_top` (the parent zone's own levels, no join needed for the common case), a UTC ISO twin next to every existing Riyadh-display timestamp (machine-sortable/parseable without a timezone table), `mfe_price`/`mae_price` (the raw levels, not just pips), `mfe_r`/`mae_r` (MFE/MAE expressed as a multiple of that trade's own risk -- e.g. "how many R was on the table at best/worst"), `entry_weekday_riyadh`/`entry_hour_riyadh` (raw material for the entry-time-window optimization the user flagged as a future idea, not yet started), `duration_minutes`, and `r_multiple_result` (the realized R: +3.00 for TP, -1.00 for SL, blank for AMBIGUOUS/OPEN where no single R applies -- fixed by this system's own 3R-TP/1R-SL design). 37 columns total now (was 21). Both `five_bso_engine.py`'s own `main()` and `full_viewer.py` now write this via one shared `ledger_row()`/`LEDGER_FIELDS` helper in `five_bso_engine.py`, so the two CSV writers can no longer drift apart.
- Did not touch `weekly_ob_ledger.csv` (already very detailed, and is the locked Weekly engine's own output -- not part of this request) or `h4_ob_ledger.csv` (already carries origin OHLC, direction, and M1 coverage detail); the user's "these trades" framing and the concrete example both pointed at the 5m BSO ledger specifically.
- Validated: regenerated for zone #3's window (642 Pine lines, well within limits); spot-checked the CSV row for OB #167 above -- all 37 fields populated correctly, `mfe_r`=3.11, `mae_r`=0.16, `r_multiple_result`=3.00.
- Chart-verified by the user on two more attempts (a TP win and a re-entry TP win). Two more issues found: (1) "the boxs does not happen to be exactly on the entry, tp or sl lines" -- the MFE/MAE-price box edges didn't coincide with the SL/TP levels already drawn/tabled elsewhere on the chart. (2) "if the price hit SL first, the green part should cover the 3rr range for consistency" -- on a losing trade the green (favorable) side only reached wherever MFE actually got to, which could be a small sliver, making losing and winning trades visually inconsistent.

## Session update — 2026-09-16 (order-mark box switched from actual MFE/MAE to a fixed risk/reward frame)

- Root cause of both issues: the box was using the trade's *actual* mfe_price/mae_price as its edges. Those are, by definition, usually short of the full SL/TP distance -- so the box rarely touched the SL/TP lines, and on a loser the reward side could be tiny. Both complaints point at the same fix: use the same `sl_price`/`tp_price` the SL/TP table column and horizontal line already use, not the excursion.
- Fixed: the box is now a fixed risk/reward frame, identical in shape for every entered attempt regardless of outcome -- GREEN from entry_price to tp_price (the full 3R reward target), RED from entry_price to sl_price (the 1R risk), both spanning entry time to `excursion_end_time`. Verified directly on OB #192 attempt 1 (entry 1.16396, SL 1.16437, TP 1.16273): green box is exactly [1.16273, 1.16396], red box exactly [1.16396, 1.16437] -- edges now pixel-identical to the existing SL/TP references, on a losing attempt too.
- The actual MFE/MAE data is untouched and still lives in its own "MFE/MAE (pips)" table column -- this change only affects what the box draws, not what's computed or reported. The box now answers "what was this trade's risk/reward plan", the table column answers "what actually happened".
- Validated: regenerated for zone #3's window, spot-checked the array values directly in the generated Pine (see above). Not yet re-chart-verified by the user.
- Next: user regenerates, confirms the box now lines up exactly with the SL/TP lines on both a winner and a loser, then work begins on break-even (stage 2 of the agreed forward plan).

## MILESTONE LOCKED — 2026-09-16 (`ict-trading-system` @ `ec79757`)

User: "we lock everything we have achieved so far. then let us move forward." Everything below is chart-verified and locked as the correct baseline; do not silently re-derive or second-guess it without new evidence -- append a new dated correction the same way earlier locked items in this file were corrected, never edit history quietly.

- **Weekly layer** (`weekly_ob_generator.py`, locked, unmodified all session): swing/MSS detection, OB lifecycle (trigger/eligible/impact/spent/OOB/rejected), origin-candle body resolution.
- **Weekly direction-control state machine** (`weekly_control_engine.py`, SPEC.md SS9-16): trend flips, campaign start, opposing-encounter/BOTH, CONTROL_SWITCHED (old side exhausted -> new zone's direction), OPPOSING_GAINS/LOSES_CONTROL, RETURN_TO_PRO_TREND, NO_CONTROL. First pass, explicitly still marked unverified in its own docstring beyond zone #3's window -- verifying more legs is plan step 4, not yet started.
- **H4 OB layer** (`h4_ob_engine.py`/shared in `full_viewer.py`): impacted+authorized gating against Weekly control permission.
- **5m BSO entry engine** (`five_bso_engine.py`), fully walked and chart-verified OB-by-OB across zone #3's entire SELL_ONLY window:
  - Resting-swing + candidate-swing entry race, candidate replacement.
  - `structural_invalid_at()`: two independent invalidation causes, whichever fires first -- `h4_close` (a fully completed H4 candle body-closes at/beyond the near boundary; only from that candle's own confirmed close, never retroactive -- locked rule from OB #159) and `swing_break` (the specific 4H swing protecting the OB gets exceeded, at the exact 1-minute crossing, independent of formal MSS classification -- generalized fix from OB #190/#159).
  - Structural SL (extreme of qualifying resting-kind swings), fixed 3R TP.
  - Post-SL re-entry chaining (`run_bso_chain`), universal per-attempt ceiling check (OB #197 fix).
  - MFE/MAE tracking, reported as pips, raw price, and R-multiples.
  - `five_bso_ledger.csv`: 37-column self-sufficient trade database (UTC timestamp twins, zone levels, MFE/MAE in three forms, entry weekday/hour, duration, realized R).
  - Pine visualization: blue candidate line, SL/TP exit-level line, and a fixed risk/reward box (green to TP, red to SL) -- all three chart-verified.
- **Known, deliberately deferred, documented above in this file -- not re-litigated without new evidence:**
  - ~3-pip feed discrepancy vs. the live FXCM TradingView chart (flagged, not fixed).
  - Break-even (SPEC.md SS25): not implemented. Every trade's effective stop is still its original SL.
  - The entry-time-window optimization idea (choosing "winning times only"): not started, only flagged.
- **Not yet built at all:** live/real-time engine, EA/execution (plan steps 6-7). Everything so far is the historical Python-reference + static-Pine-viewer path only.

Next up, per the previously agreed forward plan: the user is now asking about the Weekly control state machine's mechanics past zone #3's own window (see the session update immediately following this one).

## Session update — 2026-09-16 (explained: what happens after SELL_ONLY stops, until new direction control)

- User asked for a short, plain-words walkthrough: once we stop selling (zone #3's premise dies on a swing low confirming a bullish break), what happens next, up to the point a new direction control is established, and what's the next concrete stop.
- Answered from `weekly_control_engine.py`'s actual logic (SPEC.md SS16), not from memory -- traced `weekly_control_ledger.csv`/`weekly_control_events.csv` for zone #3's real transition:
  - Zone #3's SELL_ONLY campaign does not end the instant the swing low confirms. It ends only when BOTH (a) the old (sell) side has nothing alive left, AND (b) an opposite-direction (buy) Weekly zone actually gets IMPACTED by price -- that second event is `CONTROL_SWITCHED`, and it's what flips control, not the swing confirmation by itself. Until a buy zone is impacted, the ledger keeps showing SELL_ONLY / zone #3 (the locked "keep selling until we come across another OB" rule) -- there is no NONE gap in between here, because the code's case 2 only switches control when it finds the next opposing impact, whatever the interval.
  - Concretely, in the real data: zone #3's SELL_ONLY control runs weeks 15-21 (2026-04-13 through 2026-05-25). At week 22 (2026-06-01), zone #5 (a BUY-direction Weekly OB) gets impacted -> `CONTROL_SWITCHED`, control becomes BUY_ONLY, `controlling_zone_id` becomes 5.
  - **The next stop is therefore zone #5's impact, 2026-06-01** -- the first BUY_ONLY control window right after zone #3. That's the next OB-by-OB walkthrough leg (plan step 4: "verify at least one BUY_ONLY leg"), symmetric to how zone #3 was just verified.
- No code changed; this was explanation grounded in the actual engine and real ledger output, not new logic.

## Session update — 2026-09-16 (real gap found: SPEC.md SS16 "no-control" state is not implemented -- the true reason zone #3's SELL_ONLY stopped)

- User pushed back twice on my explanation of why zone #3's SELL_ONLY control ended, correctly refusing my first two answers (code-internals framing: "zone 3 already SPENT" / `is_alive()`) until pointing directly at a specific chart candle: **2026-05-29 17:51:00 Riyadh**, claiming this is a confirmed swing low.
- Verified directly against the locked engine's own `engine.events`: this is real. A swing LOW (origin week of 2026-05-18, price 1.15759) confirms at exactly that minute. My first response to the chart screenshot wrongly said it didn't line up -- I'd compared the swing's own historical price (1.15759) against zone #5's zone (1.15005-1.15348) and called it a mismatch. That comparison was wrong: the price visible on the chart at the confirmation minute is just where the market was trading right then, not the swing's own price. Corrected once shown the exact per-minute match.
- User then asked *why* a confirmed swing low would end a sell campaign, and what happens next. Traced this to **SPEC.md SS16 "No-control state"** -- an exact match: "A bearish POI controls... price moves downward... does not encounter any bullish POI... forms a confirmed Weekly swing low... the bearish POI has lost directional control... no bullish POI caused the reaction... Required result: change control to NONE... wait until price encounters a valid Weekly POI of either direction."
- **Real gap in `weekly_control_engine.py`, confirmed against the actual run**: this NONE state is never entered. The code keeps `weekly_control_ledger.csv` showing SELL_ONLY/zone-3 straight through 2026-05-29's swing-low confirmation, all the way to 2026-06-05 when zone #5 (a real BUY Weekly OB) finally gets impacted -- at which point it jumps straight to BUY_ONLY via the `CONTROL_SWITCHED` ("old side exhausted") path (case 2 in the code), never passing through NONE. This is exactly the case the module's own docstring already flags as unimplemented (case 5's comment: "SPEC.md SS16's actual no-control case ... is a different, more specific check this module does not yet implement -- do not approximate it with 'is the founding zone spent'").
- So the CORRECT sequence per spec should be: SELL_ONLY (zone 3) -> **NONE** at 2026-05-29 17:51:00 (swing low confirms, no POI behind the reaction) -> **BUY_ONLY** (zone 5) at 2026-06-05 18:37:00 (a real POI finally gets impacted). The code currently shows SELL_ONLY -> BUY_ONLY directly, skipping the ~6-day NONE gap entirely, and for the wrong reason (zone exhaustion, not the swing-low no-control rule).
- **Not fixed yet, per the user's explicit instruction ("do not rush, we will find every scenario in the way")**: this is the first real, concrete SS16 case found in the dataset. Flagging it precisely rather than patching blind. When we're ready to implement SS16 properly, this is the exact test case to validate against: the NONE window should be 2026-05-29 17:51:00 through 2026-06-05 18:37:00.
- User then asked directly whether selling actually resumes somewhere inside that NONE window, before zone #5 gets touched, per the user's own stated logic: "it is simply the swing low that caused the sell to stop is taken." My first attempt at this answered a different question entirely (an unrelated H4 SELL OB the user never asked about) -- wrong, corrected below without the H4 tangent.
- Checked the raw 1-minute data directly for when price first trades below 1.15759 (the swing low that triggered NONE) after it confirmed: **2026-06-05, 16:51:00 Riyadh, low 1.15726**. That is the exact minute selling resumes, per the user's own rule -- not an H4 OB, not a separate mechanism, just the same swing low that caused NONE getting taken out.
- Full corrected sequence, all three points now minute-exact and chart-verifiable:
  - **2026-05-29 17:51:00** -- swing low confirms (1.15759) -> control should drop to NONE (SS16, still not implemented -- see above).
  - **2026-06-05 16:51:00** -- that same swing low gets broken (price trades to 1.15726) -> selling resumes.
  - **2026-06-05 18:37:00** -- only 1h46m later, price reverses and zone #5 gets impacted -> buying takes over.
- Not yet implemented in code (same reason as above -- do not rush, per the user). This is now the precise three-point test case for SS16 plus its resume-on-swing-break mirror, once we're ready to build it.

## Session update — 2026-09-16 (real bug found: `weekly_control_engine.py` reads zone state with lookahead, not as-of-week)

- User asked whether buying genuinely takes full control at zone #5's impact, or whether it should go to BOTH (§12), and why -- pushing on whether a live SELL zone existed at that moment to contest it.
- Checked: **zone #8** (SELL, origin 2026-05-25, zone 1.16354-1.16522) is not rejected and not yet spent -- genuinely still open the moment zone #5 gets impacted (2026-06-05 18:37). Per SS12, an opposing POI encountered while the old side is still alive should produce BOTH, not a direct switch.
- The actual code produces `CONTROL_SWITCHED` straight to BUY_ONLY instead, and the reason is a real, previously-undetected bug: `run()`'s FIRST loop (`for k in range(len(weeks)): engine.process(k)`) processes the ENTIRE dataset, all the way to the end, purely to capture `trend_at` per week -- before the SECOND, narrative control loop (`for k in range(n)`) even starts. Because `engine.zones` are the same mutable objects throughout, every `is_alive()` check inside the control loop (cases 2/3/4) is reading each zone's FINAL, end-of-dataset state, not its state as of the week actually being processed. Confirmed directly: a debug-instrumented run showed zone #8's state as SPENT at the exact moment case 2 evaluates it for week 22 -- but zone #8 doesn't actually get impacted until **2026-08-19**, two and a half months later. Re-run with the engine genuinely stopped at week 22 (no lookahead): zone #8's true state there is IFOB (triggered, alive, not yet eligible or spent). The two states disagree, and `is_alive()` gives the opposite answer for each (SPENT -> False -> direct switch; IFOB -> True -> BOTH) -- this is not a cosmetic issue, it flips the actual outcome for this transition.
- One separate, honest caveat, not yet resolved: zone #8 isn't *eligible* until 2026-06-15 (ten days after zone #5's impact) -- at week 22 it's only triggered. Whether a merely-triggered (not-yet-eligible) zone should count as "still forcing control" is a real, distinct SPEC question from the lookahead bug -- `is_alive()`'s current definition (state in (0,1,4), i.e. triggered/eligible/AIFOB all count) says yes; that may or may not match the true intent. Not settled here.
- **Not fixed yet, per the same "do not rush" instruction.** This bug likely affects every `CONTROL_SWITCHED`/`OPPOSING_ENCOUNTER`/`OPPOSING_GAINS_CONTROL` decision the module has ever made across the whole dataset, not just this one transition -- worth treating as a priority once we're ready to touch `weekly_control_engine.py` again, since it undermines trust in every BOTH-vs-direct-switch call the module makes. The fix is straightforward in shape (snapshot each zone's state per week, or restructure so the control loop's zone reads never see beyond week k) but is not attempted here.

## Session update — 2026-09-16 (lookahead bug FIXED in code -- but the result contradicts the chart-verified zone #3 window; NOT confirmed correct)

- User asked directly to fix the lookahead bug now. Fixed in `weekly_control_engine.py`: the two-pass structure (process the whole dataset for `trend_at`, then run the control loop reading the same, now-final zone objects) is replaced with a single pass that snapshots every zone's `(state, rejected)` immediately after processing each week (`state_by_week`). Every `is_alive()`-style check (cases 2, 3, 4, and the OOB/rejection-transition detector) now reads that week's snapshot instead of the live, fully-mutated Zone object. `bullish`/`candle`/`created_state`/`id` are untouched -- those are fixed at zone creation and were never part of the bug.
- **The fix is real and the mechanism is confirmed correct, but its output is a much bigger change than the one transition it was found on.** Re-running the whole dataset with the fix: zone #1 (BUY, the original countertrend campaign from week 9) now shows as **never actually losing control**. It flashes through BOTH for exactly one week when zone #3 (SELL) gets impacted at week 15, then immediately snaps straight back to full BUY_ONLY (via `OPPOSING_GAINS_CONTROL`, because zone #1 turns out to already be SPENT very early with its own confirming bullish swing at week 13) -- and stays BUY_ONLY all the way through week 29, past the entire span this project spent the whole earlier session chart-verifying as zone #3's SELL_ONLY window.
- **This has NOT been pushed as a validated fix.** Committed and pushed the CODE change (`weekly_control_engine.py` itself, with an explicit warning in its commit message and its own interpretive-decisions report text), but the resulting control history is explicitly flagged as unconfirmed. Two possibilities, not yet distinguished:
  1. The chart-verified zone #3 SELL_ONLY window was wrong all along, and the old lookahead bug happened to produce a "correct-looking" answer purely by coincidence at the specific point checked.
  2. The lookahead fix is correct as far as it goes, but has now exposed a SECOND, different bug or open SPEC question -- most likely that `is_alive()`/`is_spent_state()`'s definition of "still forcing control" is too permissive (e.g. a zone counting as spent-with-confirmed-swing shouldn't automatically hand back full control the instant the current opposing zone is momentarily impacted, without some other condition SPEC actually requires).
- **Next, before anything else built on this module is trusted**: user to check the real chart around week 13 (2026-03-30, where zone #1's confirming bullish swing lands) and the whole zone #1/#3 stretch, to determine which of the two possibilities above is true. Do not silently re-adopt either the old or the new control history as correct until that's settled.

## Session update — 2026-09-16 (pre-zone-3 explicitly written off; post-zone-3 control sequence discovered with the fix)

- User resolved possibility #1/#2 above directly from the chart, without needing the code: zone #1's own supporting swing was breached the SAME WEEK it reacted (so its BUY thesis was dead almost immediately, not a genuine ongoing campaign), and zone #2 was rejected as an OB outright. **No real trading opportunity existed from the start of the dataset through zone #3** -- explicit instruction: treat that whole stretch as None and stop investigating it. What matters is continuing the verified logic from zone #3 forward without losing it.
- Added `--reset-to-none-at-week` to `weekly_control_engine.py`: forces control to NONE immediately before a given week, then lets the normal (now lookahead-fixed) state machine run from there untouched. This is an explicit, visible override for a period whose root cause isn't understood yet (the locked OB engine's own state classification doesn't distinguish "reacted, then immediately invalidated" from plain SPENT) -- not a fix for that question, just a clean way to keep going from a point we do trust.
- **Re-ran from zone #3 (`--reset-to-none-at-week 15`) with the lookahead fix in place. Full discovered sequence:**
  1. Zone #3 impacted (week 15, 2026-04-13) -> **SELL_ONLY**, clean campaign start.
  2. Zone #5 (BUY) impacted (week 22, 2026-06-01) -> **BOTH**, because zone #8 (SELL, alive since 2026-05-25, still untouched) blocks a clean handover.
  3. Same week: resolves back to **SELL_ONLY (zone #3 reclaims)** -- zone #8 still blocks BUY from taking full control, but nothing blocks SELL anymore (zone #5 used itself up the instant it was touched).
  4. **No further control change for the rest of the dataset** -- SELL_ONLY holds straight through week 36 (the end of the data). No BUY_ONLY window opens at all in this corrected run.
- This directly contradicts the working assumption from earlier this session (that zone #5 would open a BUY_ONLY window worth its own OB-by-OB walkthrough, plan step 4). **Not yet chart-verified.** Needs the user to check 2026-05-25 (zone #8's formation) and 2026-06-01 (the BOTH-then-back-to-SELL moment) against the real chart before this sequence is trusted, same discipline as every other finding here.

## Session update — 2026-09-16 (user-verified gate-by-gate sequence, zone #3 through the present -- confirmed correct, no code involved)

- User pushed back hard on the pace ("stop rushing and running everything at once") and instead walked the whole sequence by eye on the chart, gate by gate, including a rule not yet in any code: **a Weekly-close POI breach can kill a campaign immediately, without waiting for a confirmed swing** -- specifically, if the reacting Weekly candle's body closes *inside* an opposing zone (not rejected back out) rather than fully through it, that zone is dead right then, and control reverts to whichever side was already in force. This is a real refinement of SS11's "Weekly-close POI breach" (until now only understood via the H4-level h4_close analogy: a full close *through* the zone) -- a body close merely *inside*, without a clean reject, is now confirmed to be enough on its own, at the Weekly level, to kill the opposing thesis before any swing ever confirms.
- Verified the user's entire narrative directly against raw data -- the locked swing engine's own events and real weekly-candle OHLC, deliberately NOT the still-unverified `weekly_control_engine.py` automated logic. Every gate matched exactly:
  1. **2026-05-29 17:51**, price 1.15759 -- swing low confirms -> NONE (already logged above).
  2. **2026-06-05 16:51**, price 1.15726 -- that low breaks -> resume SELL (already logged above).
  3. **2026-06-05 18:37** -- zone #5 (BUY) impacted -> BOTH (already logged above).
  4. **Week of 2026-06-01 closes** (O 1.16522, L 1.15057, C 1.15072) -- body closes INSIDE zone #5's range (1.15005-1.15348), not rejected back above it -> per the user's rule, buy is dead immediately, no swing wait needed -> back to SELL_ONLY. New finding, not previously verified.
  5. **2026-06-15 00:29**, price 1.14994 -- the very next weekly candle after that confirms a fresh swing low (unrelated to zone #5, which is already dead) -> NONE.
  6. **2026-06-17 22:24**, price 1.14984 -- same week, that same low gets broken -- sell was already in force before this NONE and nothing else contests it -> resume SELL. (This exact minute/price also happens to be zone #9's own trigger, per `weekly_ob_ledger.csv` -- a SELL zone's trigger being the same swing-low break that resumes the sell campaign is expected, not a coincidence needing separate explanation.)
  7. **2026-07-14 15:30**, price 1.13242 -- SELL continues until this swing low confirms -> NONE. This is the exact candle in the user's screenshot -- timestamp match confirmed to the minute.
- **Current state, live in the data: NONE**, as of 2026-07-14 15:30, waiting for the next valid Weekly POI either direction -- structurally identical to gate 1.
- This whole sequence was verified WITHOUT running `weekly_control_engine.py` at all, and without needing the still-open lookahead-fix/reset-override questions logged above -- it only needed the locked swing/OB facts and real price, checked by hand, one gate at a time. This is the correct way to keep moving forward: verify from raw facts first, and only fold a finding back into the automated engine once it's independently confirmed this way -- the body-close-kills-immediately rule (gate 4) is not yet implemented in `weekly_control_engine.py` and should be, once we're ready to touch that module again.

## Session update — 2026-09-16 (rendered the whole verified gate sequence: H4 OBs, table, 5m entries, table -- like zone #3)

- User asked to visualize the entire verified sequence end to end, same as zone #3's own walkthrough: mark H4 OBs correctly per gate (nothing during NONE, sell only during SELL_ONLY, both sides during BOTH), with their 5m entries, boxes and tables.
- Added `--manual-gates` to `full_viewer.py`: a small, explicitly-documented table (`build_manual_gates()`) encoding the exact verified sequence from the entry above -- 8 rows, each `(start, end, control, sell_parent, buy_parent)` -- used to authorize H4 OBs instead of `weekly_control_ledger.csv` for the window it covers (falls back to the normal ledger lookup outside it, so this doesn't disturb anything before zone #3). Necessary because `weekly_control_engine.py` doesn't yet implement SS16's NONE state or the Weekly-close-body-inside-zone kill rule found this session -- its own control column is wrong for this whole stretch.
- Ran `full_viewer.py --manual-gates`: **20 H4 OBs authorized** across the whole zone-3-to-present window, **all correctly SELL-side**, all landing inside a SELL_ONLY gate, **zero authorized during either NONE gate** -- verified directly against `h4_ob_ledger.csv` with an independent gate-membership check, no violations. No H4 OB happened to land inside the ~2.5-day BOTH window, so nothing to show there this time -- not a bug, just how the H4-level impacts happened to fall. 24 5m BSO attempts computed and rendered (candidate/SL-TP lines, the fixed risk/reward box, and the ledger table) across those 20 OBs, same rendering as zone #3's own walkthrough. Pine output: 784 lines, well within limits.
- Sent the generated `full_viewer.pine`, `h4_ob_ledger.csv`, and `five_bso_ledger.csv` directly (not just the `.py` source) so the result can be inspected without regenerating.
- Not yet chart-verified by the user -- this is the tool to do that walkthrough with, not a claim the render itself is correct beyond what's already been hand-verified for its control gating.

## Session update — 2026-09-16 (delivery mix-up, then a real CE10295 bug found and fixed)

- User reported the delivered Pine file looked identical to the old zone-#3-only one. Checked the file the user actually had (they attached it): 642 lines, only `#159`-`#197`, MD5 `2cffd543...` -- a stale copy from several turns earlier, not what was just generated (784 lines, 20 OBs including `#213`-`#258`, MD5 `5e2bbb4d...`). Re-sent under a distinct filename (`full_viewer_manual_gates.pine`) to avoid another mix-up.
- User then pasted the re-sent file into Pine Editor and hit a real compile error: **CE10295, "main body is too long."** This was not a delivery mistake -- a genuine bug. Root cause: `build_h4_extra_lines`'s Weekly-structure labels (H4 swing-high/swing-low/MSS markers) were drawn with one `label.new` statement per event, unlike the OB boxes/lines right next to them in the same function (already array-packed specifically to avoid this failure mode, per that code's own docstring history). Zone #3's original ~6-week window never had enough H4 swing/MSS events to hit Pine's statement ceiling; the wider ~13-week `--manual-gates` window did.
- Fixed: packed those labels into arrays (`h4StructX/Y/Txt/Col`) drawn by one small loop, same pattern as everything else in the file. Re-ran `--manual-gates`: **566 lines** (down from 784, smaller than even the original 642-line file), same 20 H4 OBs, same authorization results. Not yet confirmed to compile clean in Pine Editor by the user.
- Lesson for this file going forward: any NEW unrolled-per-item Pine statement generator (one `label.new`/`box.new`/etc. per data point, not wrapped in an array + loop) will eventually blow CE10295 the moment its input set grows past whatever happened to fit in whichever window was tested first. Check for this pattern before trusting any newly widened render.
- **The CE10295 fix itself introduced a second real bug**, caught by the user's very next Pine Editor screenshot: **CE10013, "mismatched input 'if', expecting end of line without line continuation."** The four new `var array<...> h4Struct*` declarations had been inserted textually between `if onH4 or onFive`'s indented body and its sibling `if onH4` line. Pine's block parsing is indentation-driven; the zero-indent `var` lines implicitly closed the enclosing `if barstate.islast` block early, leaving the following indented `if onH4` orphaned with no block to belong to. Fixed by moving those four declarations up to sit with the rest of the top-level `var array` declarations, before `if barstate.islast` opens -- matching where every other array in this function is declared. Verified directly in the regenerated Pine text: the declarations now sit above `if barstate.islast`, and `if onH4` is a clean sibling of `if onH4 or onFive` again. Still 566 lines, same 20 H4 OBs. Not yet confirmed to compile clean by the user -- two real syntax bugs from one fix in a row means this needs an actual compile check, not just another visual read of the generated text, before trusting it further.

## Session update — 2026-09-16 (the actual CE10295 source: `write_ob_pine`'s own Weekly-layer rendering, not the H4 layer)

- User reported CE10295 again, unchanged, after the CE10013 fix. Correctly called out that this had already been solved once and needed a real fix, not another guess: "you know we solved this earlier get it done." Investigated properly instead of re-guessing at the H4 layer (already fixed and verified correct).
- Root cause found in `weekly_ob_generator.py`'s `write_ob_pine()` -- the locked module's OWN Pine-rendering function, separate from anything in `full_viewer.py`. It was NEVER array-packed: one `label.new` per swing-high/swing-low/MSS event, one `box.new`+`label.new`+`line.new` block per OB, one `table.cell` row per table zone (capped), and -- the single worst offender -- a SECOND table loop unrolling one 10-column row per zone in the ENTIRE dataset, completely uncapped, just so "inspect one OB" mode could pick any zone by rank at runtime. Zone #3's narrow window never had enough Weekly zones/swings to hit Pine's statement ceiling; the wider `--manual-gates` window did. The earlier H4-layer fix was real and correct, but was never the actual bottleneck for this failure.
- Fixed the same way as the H4 layer: every one of these packed into arrays, drawn by one small runtime loop each. Only the Pine TEXT GENERATION changed -- no swing/OB/MSS detection logic in this locked module was touched; `engine.process()`, `.events`, `.msses`, `.zones` etc. are untouched.
- Learned from the CE10013 regression immediately prior: every new `var array` is declared in ONE place, before `if barstate.islast` opens, never inserted between an if-block's body and a sibling if-line. Verified this directly in the regenerated Pine text (`if barstate.islast` / `if onWeekly` / `if onWeekly or onH4` / `if onWeekly` nest cleanly, each block's indentation checked line by line) before sending anything.
- Re-ran `--manual-gates`: **289 lines** (down from 566 -- the Weekly layer was the dominant contributor all along, not the H4 layer). Same 20 H4 OBs, same 24 5m BSO rows, same authorization results -- confirmed the underlying computed facts are unchanged, only the rendering shrank. Not yet confirmed to compile clean in Pine Editor by the user.

## Session update — 2026-09-17 (compile succeeded; four new findings from live chart review; swing-low/down-MSS visibility fix applied, not proven)

- File compiled clean. User began an entry-by-entry review of the whole `--manual-gates` render (entries 1-8 all independently confirmed correct against the real chart, including one H4_OB_BREACHED case) -- the render itself is validated as far as trade mechanics go.
- **Real bug found (OB #213/#215, same box re-armed twice):** the locked core engine re-arms the same origin candle (2026-06-09 12:00, zb 1.15503 / zt 1.15733) as a fresh OB more than once -- once as zone #213 (trigger from a swing low confirming at the 04:00 candle) and again as zone #215 (trigger from a swing high confirming at the 12:00 candle). That re-arming is intentional, normal engine behavior, not a bug. The actual bug: our `structural_invalid_at()` runs per zone ID and only scans forward from that zone's own impact time. Traced with exact candles: zone #213 impacts 06:52 (04:00-08:00 candle, closes 1.15461, not yet a breach); the very next candle (08:00-12:00) wicks into the zone (respecting it -- two genuinely valid entries there, both before its 12:00 close) but **closes at 1.15533, at/through the near boundary (zb) -- the real breach, confirmed at 12:00:00**; zone #215 then impacts at 12:45, in the candle *after* that breach, and gets treated as a brand-new, fully authorized OB -- trading 2 SL + 1 TP on a box that was already structurally dead. **Not fixed yet** -- needs `structural_invalid_at`/the authorization pipeline to track invalidation per physical box/origin-candle, not per zone ID, so a re-armed instance inherits the box's real death time. Flagged, not touched, pending the user's go-ahead (still working through more entries).
- **MSS-placement finding (from the prior session) reaffirmed with a recommendation**: the "✕" mark for a swing high at 2026-07-01 16:00 (price 1.14113) sits on the swing's own origin candle, even though the confirmed break happened almost a day later (2026-07-02 08:00). Recommended moving MSS labels to draw at the confirmation bar (`m.at`) instead of the broken-swing's origin bar (`m.broken`), in both the H4 layer and the (also affected) locked Weekly layer. Not yet actioned -- still the user's call given the Weekly side is a previously "locked" convention.
- **Missing 4H OB (origin 2026-07-08 04:00, zb 1.14077/zt 1.14140, zone #255) reconfirmed correct**: genuinely rejected by the locked engine -- the candle immediately before it already traded down to 1.13998, below this zone's own bottom, before the zone could ever form as a fresh OB. Not a bug.
- **Swing-low / down-MSS visibility on the H4 chart**: exhaustively checked for a code bug -- ruled out missing data (raw counts confirmed present), packing/alignment (verified byte-for-byte against the actual delivered file's own arrays), Pine's 100,000-element array cap and per-script label-count cap (searched Pine's own docs; total labels ~276, nowhere close to either limit), and Unicode corruption (codepoints confirmed correct: U+25B2/U+25BC/U+2715). Applied a best-guess visibility fix first (black -> maroon), explicitly flagged as unproven.

## Session update — 2026-09-17 (the real bug found: `var` array baked `na` from `lowGap` at bar 0)

- User tested the maroon fix directly and reported zero change -- still nothing shown at all. That result is what broke the case open: if it were a contrast problem, maroon on a white background would show *something*; total invisibility in every color means the label was never being created with a valid position in the first place.
- **Root cause, confirmed**: `h4StructY` (and the Weekly layer's own `structY`) are declared `var`, so Pine evaluates their `array.from(...)` expression exactly ONCE, on the chart's very first historical bar. `lowGap` (`ta.atr(14) * 0.08`) is still `na` at that point -- ATR(14) needs 14 bars of history that don't exist yet at bar 0. Every entry that baked `"price - lowGap"` directly into the array literal (every swing low and every down-MSS) was therefore permanently set to `na` the instant that line first ran, and never recalculated on later bars even once `lowGap` became a real number. `label.new()` given `na` for its price silently draws nothing -- no error, no warning, just invisible, regardless of textcolor. Swing highs and up-MSS never referenced `lowGap`, so they were plain float literals, unaffected by any of this -- exactly the asymmetry reported from the very first screenshot.
- This is the same class of mistake already known and avoided elsewhere in this same file: `h4Right` (which depends on the `impact_x_<id>` watcher variables) is deliberately NOT a `var` array, and is instead recomputed fresh inside `if barstate.islast`, specifically because its inputs are bar-dependent. The struct-label arrays needed the identical treatment and didn't get it in the CE10295 fix.
- **Fixed** in both `full_viewer.py`'s H4 layer and `weekly_ob_generator.py`'s own Weekly layer (same construction, same bug, not yet reported there but fixed proactively): store only the raw price (a safe literal, fine in a `var` array) plus a new bool flag (`h4StructLow`/`structLow`) marking which entries need the offset, and apply `"- lowGap"` at DRAW TIME inside the loop instead of at array-literal time -- by then `lowGap` has a real value. Verified structurally in the regenerated Pine text (293 lines, same 20 H4 OBs, same 24 5m BSO rows). The maroon color change is kept (still a reasonable choice on the denser H4 timeframe) but the actual fix was the `na`-at-bar-0 bug, not the color.
- Not yet confirmed on the real chart by the user -- this is now a genuinely different kind of fix (a provable logic bug, not a hypothesis) and should actually resolve it.

## Session update — 2026-09-17 (na-bug fix confirmed working; color reverted; real AOB re-arm bug found and fixed)

- User confirmed on the real chart: swing lows and down-MSS labels now render. The `na`-at-bar-0 fix above was the real bug.
- Color reverted from maroon back to `color.black` (matching the Weekly layer's locked blue-high/black-low+down-MSS convention) in `full_viewer.py`'s `build_h4_extra_lines()`. The maroon change was an unproven hypothesis fix from before the real bug was found and had already served its purpose (proving it wasn't a contrast issue); no reason to keep it once the real fix landed.
- User initially reported this reverted color as still not visible; this turned out to be a stale-file issue on the user's machine (old `full_viewer.py` still had `maroon` on disk, confirmed via `findstr /n "maroon"` in their terminal) -- not a code bug. User elected to leave color as-is for now and move to the other open issues rather than re-chase the delivery problem.
- **OB re-arm bug -- real root cause found and fixed.** User's report: one physical 4H OB box got two separate zone IDs and was traded twice independently (one attempt with 1 SL, another later attempt with 2 SL + 1 TP, after the box had already been violated).
  - Root cause: `weekly_ob_generator.py`'s `try_bull_aob()`/`try_bear_aob()` (the AOB zone-creation paths) never guarded against reusing an origin candle already claimed by an earlier zone. Every OTHER zone-creation path in the same class (`try_bull_aifob`, `try_bear_aifob`, `add_ifob`) already guards with `not self.claimed(best, bull)` before calling `add_zone()` -- the AOB path was simply missing this check, so the same origin candle could get a second zone stamped on it once the arming conditions (`armed_h`/`armed_l` swing structure) re-triggered.
  - Since `five_bso_engine.py` reuses this exact same `WeeklyOBEngine` class verbatim for the H4 layer (`wob.WeeklyOBEngine(minutes, h4_bars, origin_gap_window=None)`), the same gap produced duplicate H4 OBs on the same physical box -- this was NOT primarily an invalidation-scan gap in `structural_invalid_at()` as first diagnosed; that diagnosis was wrong. The real bug was upstream, at zone creation.
  - Fix: added `not self.claimed(best, False)` / `not self.claimed(best, True)` to `try_bull_aob()`/`try_bear_aob()`, matching the existing pattern.
  - Verified: total H4 OBs computed dropped from 360 to 355 after the fix; `h4_ob_ledger.csv` now has zero `(origin_utc, side)` duplicates (checked programmatically -- previously had at least one, matching OB #213/#215). `--manual-gates` render dropped from 20 to 19 shown H4 OBs and from 24 to 23 5m BSO rows, consistent with exactly one duplicate zone removed from that window.
  - Not yet confirmed on the real chart by the user.
- Remaining open issue: MSS-placement bug (drawn at `m.broken` -- the bar where structure breaks -- instead of `m.at` -- the bar that caused it). Still awaiting the user's decision, since it affects the "locked" Weekly-chart convention too, not just the H4 layer.

## Session update — 2026-09-17 (MSS-placement bug confirmed with real chart evidence and fixed)

- User walked a specific pair of H4 candles (2026-07-05 20:00 and 2026-07-06 00:00 Riyadh) from the real chart. Traced the exact engine data for that window (weekend-reopen candle, confirmed real via raw 1m data -- market reopens with sparse ticks at 2026-07-05 22:11 RYD, not a phantom bar). Calibration check: engine OHLC for the 2026-07-03 20:00 RYD candle matched the user's own chart hover reading to within ~0.00003 (feed rounding), confirming the index mapping between the engine's H4 bars and the real chart is correct.
- User reported the X (MSS) marks were sitting in odd places relative to their candles -- confirmed by identifying two real MSS events in that window:
  - MSS #1 (down-break): `at`=bar 820 (2026-07-05 20:00, the real breaking candle) vs `broken`=bar 819 (2026-07-03 20:00, the old swing candle) -- was drawn at 819, should be at 820.
  - MSS #2 (up-break): `at`=bar 826 (2026-07-06 20:00, the real breaking candle, over a day later) vs `broken`=bar 820 -- was drawn at 820, should be at 826.
- Root cause confirmed: both `full_viewer.py` and `weekly_ob_generator.py` keyed the X mark's X-position off `m.broken` (the MSS dataclass field for the OLD swing candle whose level got exceeded) instead of `m.at` (the confirm bar passed into `consume_break()`, i.e. the candle that actually caused the break). The Y position (`m.price`, the broken level itself) was always correct -- only the X (which candle) was wrong.
- Fixed in both files: `h4_bars[m.broken].start` / `engine.w[m.broken].start` -> `h4_bars[m.at].start` / `engine.w[m.at].start`. Also fixed the H4 layer's window-scoping filter (`in_window(h4_bars[m.broken].start)` -> `in_window(h4_bars[m.at].start)`) so an MSS is scoped into/out of the `--manual-gates` window by where it's actually drawn, not by its old swing candle's time.
- Regenerated cleanly (weekly_ob_generator.py -> weekly_control_engine.py -> full_viewer.py --manual-gates), same OB/BSO counts as before this fix (355 H4 OBs, 19 shown, 23 5m BSO rows) since this only moves X-mark positions, doesn't change zone logic.
- Not yet confirmed on the real chart by the user.
- Remaining open items: none currently open besides real-chart confirmation of this fix. The three issues from the "well, you need to fix the swing low and MSS to down first, then we will go to other 3 issues" instruction are now all addressed: (1) swing-low/down-MSS visibility -- fixed, confirmed; (2) OB re-arm bug -- fixed, pending confirmation; (3) MSS placement -- fixed, pending confirmation; (4) missing OB #255 -- confirmed correct, not a bug, closed earlier.

## Session update — 2026-09-17 (MAJOR UNRESOLVED FINDING: engine manufactures a phantom weekly Sunday-reopen H4 candle that does not exist on the real chart)

**Status: NOT FIXED. Flagged for the next session. Do not silently "fix" this -- it needs a policy decision from the user first (see below).**

- While pinning down the MSS-placement bug above, the user gave exact OHLC readings for the H4 candles immediately before and after a weekend on their real TradingView chart: "20 candle" = 2026-07-03 20:00 RYD (Friday, O1.14375 H1.14421 L1.14328 C1.14329) and "0 candle" = 2026-07-06 00:00 RYD (Monday, O1.14382 H1.14410 L1.14322 C1.14381). Both matched this engine's own computed bars for those exact slots to within ~0.00003 (feed rounding) -- good calibration, index mapping is correct for those two bars.
- The user was explicit: **on the real chart these two candles are directly adjacent -- there is no candle between them.** "Sunday does not exist at all."
- This engine's `h4_ob_engine.aggregate_h4()` computes an EXTRA H4 bar between them every single week: a "weekend reopen" bar spanning 2026-07-05 20:00-00:00 RYD (Sunday), built from real 1-minute ticks present in the source CSV starting at 22:11 RYD that Sunday (109 of the bar's 240 minutes have real data -- not empty, not a glitch tick or two).
- **This is not a one-off.** Checked programmatically across the full dataset: every one of the 36 weekend gaps in the CSV produces a similar thin H4 bar (roughly 20-180 minutes of real data out of 240, reopening consistently around 21:00-23:00 RYD each Sunday). Out of 1130 total H4 bars in the dataset, up to 36 of them may be these phantom weekly bars the real chart doesn't show.
- **Why this matters:** every H4 swing high/low, MSS, and OB computed by this engine is indexed and time-positioned off `h4_bars`. If the real broker/TradingView chart genuinely has no candle in these Sunday slots, then every label this engine draws using one of these 36 bars (as its own event OR as neighboring context for peak/trough tracking across a weekend) is drawn at a time/x-position with no matching candle on the real chart -- it will appear to "float" in empty space, exactly the kind of "odd, not close to the candle" symptom the user has now reported multiple times this session before this was traced back to its root cause.
- **Open question, NOT decided:** why does the real chart have no candle there when the CSV clearly has real ticks? Two live hypotheses, neither confirmed:
  1. The CSV (from FXCM's own historical-data download, per the user's open browser tab "FXCM Basic Historical Data") includes early Sunday indicative/pre-market ticks that FXCM's own TradingView live feed does not consider part of the official tradable session, and so never renders as a candle.
  2. TradingView's own H4 candle grid anchors or filters weekend-adjacent bars differently than this engine's `aggregate_h4()` does (e.g. requires a minimum tick/volume threshold per bar, or anchors the week's first H4 bar to the first FULL 4-hour window after reopen rather than the calendar-aligned grid slot).
- **Not fixed, on purpose.** Fixing this requires deciding what should happen to these ~36 bars' worth of real tick data: dropped entirely before aggregation (matching the real chart, but discarding real price action), merged into the following Monday bar (extends that bar's effective window, changes its OHLC), or something else -- this is a policy/definition decision, not a bug with one obviously correct fix, and changing `aggregate_h4()`'s weekend handling would shift EVERY H4 bar index after each of these 36 occurrences, invalidating every H4 OB ID, swing event, and MSS this session has verified against the chart so far (including the OB re-arm and MSS-placement fixes above, which were verified using the CURRENT bar indexing).
- **Recommended next step for whoever picks this up:** get the user to confirm, candle by candle, exactly which H4 slots exist on their real chart around 2-3 more weekend boundaries (not just this one), to nail down hypothesis (1) vs (2) above before touching `aggregate_h4()`. Once the real rule is known, expect a full re-verification pass of the manual-gates window (and likely the whole dataset) since bar indices will shift.

## Session update — 2026-09-17 (CORRECTION: MSS X-mark placement fix from earlier today was wrong, reverted)

**The "Fix MSS marker placement" commit earlier in this session (moving the X mark from `m.broken` to `m.at`) was a mistake and has been reverted.**

- Context: while asking about a genuinely unrelated question (the MSS-to-up/MSS-to-down report), the user explicitly stated the correct, original convention: the X mark goes on the swing point that got exceeded (the arrow that formed it), not on the candle/price that did the exceeding. "If it is exceeded and the trend shifts, put a cross on that swing high arrow, not the price or time that it gets exceeded."
- Checked directly against the ORIGINAL locked code: `write_ob_pine` in the very first commit (`c2bcde7`, unmodified since) already used `engine.w[m.broken].start` -- exactly what the user describes. The earlier "fix" this session (switching to `m.at`) was a misdiagnosis of an unrelated complaint and silently broke the original, correct convention.
- **Root lesson for whoever continues this:** the swing/MSS detection logic (`process()`, `h_action`, `l_action`, `consume_break`, `add_event`) has been verified BYTE-FOR-BYTE IDENTICAL to the original first commit -- diffed directly, zero differences outside one explanatory comment. This has never drifted. Any apparent "wrong" MSS/swing placement is therefore almost certainly a RENDERING issue (which field gets used for X position, `var` array timing bugs, window/cap truncation) -- never assume the underlying detection algorithm itself needs "fixing" without checking it against the original commit first, the way this correction did.
- Reverted in both `full_viewer.py` (H4 layer) and `weekly_ob_generator.py` (Weekly layer). Verified: all 4 Weekly MSS and all 64 in-window (`--manual-gates`) H4 MSS marks now resolve to `m.broken`'s timestamp in the generated Pine text -- confirmed programmatically, not just visually.
- Also confirmed for the user in this same exchange: the H4 layer's swing/MSS detection uses the exact same `WeeklyOBEngine` class and logic as the Weekly layer, just applied to H4 bars instead of Weekly bars -- there is no separate/different H4 algorithm, and there never has been.
- **Confirmed and LOCKED by the user on the real chart.** MSS X marks now correctly sit on the swing arrow they invalidate, matching the original convention.

## Session update — 2026-09-17 (real engine change, user-directed: MSS candle can now be its own IFOB origin)

**This is a genuine change to core zone-creation logic, not a rendering fix.** User-directed and explicitly reasoned through together before implementation.

- **The issue**: `add_ifob()` always passed `skip=k`, permanently barring the MSS/trigger candle from ever being its own IFOB origin -- even in a clean one-candle-leg case where that candle is legitimately the best (often only) candidate. Concrete example found and traced: candle 2026-06-10 16:00 confirms a swing high AND breaks the prior swing low (MSS to down) on the same bar, is bullish, and is genuinely "the whole leg" per standard ICT convention -- but got excluded from its own origin search, and no OB was created there at all. The hunt only succeeded three candles later (2026-06-11 04:00), landing on a different, later candle instead.
- **User's own account of why `skip=k` existed**: originally meant to protect against a candle whose own supporting swing gets immediately violated right after -- not a blanket "never allow this" rule.
- **First proposed fix was wrong** (peeking at `self.w[k+1]` while still processing bar `k`) -- user caught this immediately as a lookahead bug, the same class of bug already found and fixed in `weekly_control_engine.py` earlier this session. Correctly flagged before any code was touched.
- **Corrected, causal fix, implemented:**
  - `add_ifob()` no longer passes `skip=k` -- the trigger candle competes normally in the origin search.
  - New `Zone.same_bar_origin_guard` field: set only when the trigger candle wins its own origin search (`best == k`), storing the swing index it depends on for protection.
  - `finish_events_and_lifecycle()` resolves this guard exactly once, on the bar immediately following creation -- checking only data that exists by the time that next bar is actually processed in normal forward order. This is a one-bar-deferred check, not a lookahead: it never runs before that bar has itself been reached. If that bar breaches the protecting swing, the zone is rejected immediately (`z.rejected = True`), exactly like any other zone whose support fails before it becomes eligible. The existing eligibility-rejection check (`self.w[k-1].h > z.zt`, unchanged) still applies afterward as the second line of defense, same as before.
- **Verified across the full dataset** (not just the one example): 19 same-bar-origin zones got created in total; 8 survived the guard, 11 were correctly rejected by it -- both branches of the new logic are proven exercised, not just the success path.
- **Target case confirmed**: zone with origin 2026-06-10 16:00 now exists (SELL IFOB, bottom 1.15481, top 1.15535, matching that candle's own body exactly) and is authorized.
- **Impact on existing numbers**: H4 OBs computed 355 -> 359 (+4 across the full dataset); `--manual-gates` window 19 -> 21 shown, 23 -> 25 5m BSO rows. Weekly-level output (`weekly_ob_swings.csv`) still only has 4 MSS events total (unaffected -- the Weekly layer evidently never hit this exact same-bar-origin scenario in this dataset), so the original Weekly-level report from earlier in this session is unchanged.
- Not yet confirmed on the real chart by the user.

## Session update — 2026-09-17 (control gates extended to the edge of the dataset; SELL-resume rule revised)

**Full verified control-gate chain, zone 3's original impact through the edge of the CSV (2026-09-11 22:05, last 1m bar).** All times Riyadh.

| Control | From | Trigger |
|---|---|---|
| SELL only (zone 3) | 04-14 17:55 | zone 3 impacted |
| NONE | 05-29 17:51 | swing low confirmed |
| SELL only (zone 3) | 06-05 16:51 | that swing low taken out (old rule -- kept as-is, chart-verified, not revisited) |
| BOTH (3/5) | 06-05 18:37 | opposing zone 5 impacted |
| SELL only (zone 3) | 06-08 00:00 | buy side (zone 5) exhausted |
| NONE | 06-15 00:29 | swing low confirmed |
| SELL only (zone 3) | 06-17 22:24 | that swing low taken out (old rule -- kept as-is; new rule happens to land on the identical minute here, so no conflict) |
| NONE | 07-14 15:30 | swing low confirmed |
| SELL only (zone 3) | **07-23 15:43** | **swing high confirmed (NEW rule, see below)** |
| NONE | 07-29 21:53 | new swing low confirmed, no buying zone in control |
| SELL only (zone 9) | 07-30 16:48 | first zone reaction from a plain NONE (zone 9 impacted; no opposing zone ever reacted first) |
| NONE | **08-24 00:00** | last tradable SELL zone died (see below) |
| -- | 08-24 00:00 through 09-11 22:05 (end of data) | stays at NONE, no further control gate |

**Rule revision, user-directed:** the earlier "SELL resumes when the swing low that caused NONE gets taken out" rule is WRONG and is abandoned. Replaced with: **SELL resumes the moment a Weekly swing HIGH confirms** (not when the swing low gets broken). Verified against the two already-chart-confirmed transitions before applying it:
- 05-29 NONE -> 06-05 16:51: old rule gives 16:51 (matches chart); new rule gives 16:00 (51 min off). User confirmed this doesn't change anything material (no different 4H structures or 5m entries resulted either way) -- so the already-verified 16:51 timestamp is kept as-is, not retroactively changed.
- 06-15 NONE -> 06-17 22:24: old and new rules land on the exact same minute -- no conflict either way.
- 07-14 NONE onward: this is where the rule change actually matters. Old rule ("swing low taken out", i.e. price back below 1.13242) **never fires again in the rest of the dataset** -- under the old rule we'd have stayed at NONE for good. New rule (swing high 1.14822 confirms) fires at **2026-07-23 15:43**, verified directly against the user's own chart screenshot of that exact candle.

**New standing rules for SELL_ONLY / BOTH, user-directed, all three checked in parallel and whichever fires first wins:**
1. Opposing BUY zone gets impacted -> BOTH.
2. A NEW swing low confirms, with no buying zone in control -> NONE. (If a buying zone IS already in control i.e. we're in BOTH, that same swing-low confirmation instead hands FULL control to BUY, not NONE.)
3. The swing high currently supporting this SELL leg gets taken out, with no buying zone in control -> NONE. (Same BOTH exception: if a buying zone is in control when this happens, BUY keeps control instead.)

**New mechanism established for exiting a plain NONE with no active campaign**: the first zone (either side) to get a real impact while nobody controls takes over -- same mechanism that originally gave zone #1 its BUY control at the very start of the dataset. This is distinct from rule 3's "swing high confirmed" resumption, which only applies when resuming a campaign that already has a live supporting swing high in play. Applied here: zone #9 (origin 2026-06-08, SELL) is the first zone to react from the 07-29 21:53 NONE, at 07-30 16:48 -- no swing high confirms anywhere near that time (the next one is out in late August), so the first-reaction mechanism, not rule 3, is what actually governs this specific transition.

**Zone-death mechanics newly applied at the WEEKLY-zone level (previously only demonstrated at H4-OB level this session)**: the same "Weekly candle body closing inside vs. through an opposing zone" rule applies to these Weekly zones' own tradability, independent of the control gate itself:
- **Zone #9 dies 2026-08-03 00:00** -- its own containing week (07-27 to 08-03) closes at 1.15441, INSIDE its box (zb 1.15072 / zt 1.15693), no clean wick-reject. Kills its thesis; the 07-30 16:48 entry (already triggered before this close) stands, but no further new entries off zone #9 after this point. Selling effectively goes idle (no tradable zone), even though the control gate itself hadn't changed yet.
- **Zone #8 (origin 2026-06-08 lineage... actually separate zone, same SELL side) reacts 2026-08-19 15:49** -- selling resumes (a valid zone touched).
- **Zone #8 dies 2026-08-24 00:00** -- its own containing week (08-17 to 08-24, the SAME week it got impacted in) closes at 1.16718, a FULL BODY BREACH above its own zt (1.16522) -- not just inside, all the way through. Kills it outright.
- With no tradable SELL zone left standing anywhere, **control drops to NONE at 2026-08-24 00:00** -- this new "ran out of tradable zones" mechanism is what actually ends this SELL leg, earlier and cleaner than the swing-low-confirmation mechanism (which would have given 09-09 09:15 instead, a full two weeks later). User-directed: this zone-death mechanism supersedes the swing-low mechanism when it fires first.

**Data ends 2026-09-11 22:05 Riyadh (last 1-minute bar in the CSV).** Per the user: no further control gate exists after 08-24 00:00 -- price stays at NONE through the end of available data. Recorded as the final state, not further investigated (nothing left to check -- no data past this point).

None of this chain beyond zone 3's original 04-14 window has been independently chart-verified end-to-end the way the manual-gates table was earlier -- the newer entries (07-23 onward) were derived live in this session, checked against the user's own chart screenshots at each step (07-23 15:43 and 06-05 16:51 both directly confirmed), but not yet turned into a `--manual-gates`-style hardcoded table or run through 4H/5m entry-by-entry verification the way the 04-14 to 08-04 window was.

**What changed from the previous session's plan**: the previous session ended with the `--manual-gates` window fixed at 04-14 to 08-04 (NONE, open-ended) as the extent of verified work, plus four systemic bug fixes (swing-low na-bug, OB re-arm, MSS placement -- later corrected back after a wrong mid-session "fix" -- and the same-bar-origin IFOB guard). This session extended the verified control-gate chain all the way to the edge of the dataset (09-11 22:05), revised the SELL-resume-from-NONE rule from "swing low taken out" to "swing high confirmed", established a new "first zone reaction from a plain NONE" mechanism, and applied the Weekly-close body-inside/through zone-death rule directly to the control-gate level for the first time (previously only used at H4-OB level). The `--manual-gates` table in `full_viewer.py` has NOT yet been updated to reflect any of this session's new gates (07-23 onward) -- it still stops at 08-04 NONE. That's the next concrete task for whoever continues this: encode gates 07-23 onward into `build_manual_gates()` and re-render/verify them against the chart the same way 04-14 to 08-04 was.
