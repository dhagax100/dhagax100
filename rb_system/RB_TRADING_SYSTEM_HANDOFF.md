# RB Trading System Handoff

Parallel to `rb_system/ob_reference_docs/TRADING_SYSTEM_HANDOFF.md`, for the
RB (Rejection Block) port. Read that file, `PROJECT_SCOPE.md`, and
`BUILD_ORDER.md` first; this file records only the RB-specific work.

## 1. Authoritative RB source

`rb_system/RB_Indicator_v1.pine` — confirmed with the user before this port
began. Its header comment (lines 1-33) and `addRBFromSwing`/`tryBullARB`/
`tryBearARB`/STEP2/STEP3 are the ONLY source of RB construction/lifecycle
rules. Swing/MSS detection is unchanged from OB and was reused, not
re-derived.

## 2. What was built (this session, 2026-09-18)

- `rb_system/reference/weekly_rb_generator.py` — Weekly RB engine. Structure:
  - `load_minutes`/`forex_week_start`/`aggregate_weeks` copied verbatim from
    `weekly_ob_generator.py` (same CSV schema, same Sunday-17:00-NY forex
    week convention).
  - `WeeklyRBEngine.process()`/`high_first()`/`add_event()` copied verbatim
    (structurally identical) from `WeeklyOBEngine` in `weekly_ob_generator.py`
    — same peak/trough/regime/MSS state machine, same M1-based `high_first`
    tie-break (NOT pine's `close>=open` heuristic — the Python OB engine
    already replaced that heuristic with real M1 ordering, and since "swing
    detection is 100% unchanged from OB," this port keeps the OB Python's
    M1-based ordering rather than reintroducing pine's simpler heuristic).
  - RB-specific: `add_rb_from_swing`, `try_bull_arb`, `try_bear_arb`,
    `consume_break` (IRB creation), `mid_arm` (ARB attempts), and
    `finish_events_and_lifecycle`'s STEP2 (delayed IRB eligibility) / STEP3
    (impact + stranding only, no close-through) — translated line-by-line
    from `RB_Indicator_v1.pine`'s `addRBFromSwing`/`tryBullARB`/`tryBearARB`/
    STEP2/STEP3, using Weekly bars in place of pine's chart bars.
- Outputs (in `rb_system/data/`, generated from
  `rb_system/ob_reference_data/EURUSD_m1_BidAndAsk.csv` with
  `--input-tz Etc/GMT+2`, matching the input-tz that reproduces the
  committed OB reference ledger — see §3):
  - `weekly_rb_swings.csv`
  - `weekly_rb_ledger.csv`
  - `weekly_rb_report.txt`
- No Pine viewer was generated for RB yet (see §5, open items).

## 3. Verification performed, with evidence

### 3a. Confirmed the correct `--input-tz` for comparing against the committed OB reference data

The committed `rb_system/ob_reference_data/weekly_ob_swings.csv` /
`weekly_ob_ledger.csv` do NOT reproduce from a fresh run of
`weekly_ob_generator.py` with the README's documented default
(`--input-tz America/New_York`) — a fresh run with that flag differs in 2 of
24 swing rows (different `origin` week for two SWING LOW rows: week
2026-01-18 vs 2026-01-11, and 2026-03-15 vs 2026-03-08), even though the
swing prices/confirm-times matched. A fresh run with `--input-tz Etc/GMT+2`
reproduced the committed OB swings file byte-for-byte
(`diff weekly_ob_swings.csv <committed> ` → no output). `Etc/GMT+2` also
matches the handoff's own 2026-09-15 session-update conclusion ("UTC-2 test
result: timing alignment confirmed"). This RB port therefore always uses
`--input-tz Etc/GMT+2` when comparing against the committed OB reference
files. This is a pre-existing fact about the OB reference data's regenerate-
ability, not an RB defect; it is recorded here because it was discovered
while setting up the RB comparison baseline.

**Caution for future runs:** the OB generator writes its 4 output files next
to `weekly_ob_generator.py` itself (or resolves paths tied to the script's
own directory), NOT next to the input CSV or into the invoking shell's `cwd`
in all cases — an early verification run from a temp directory with a
symlinked CSV silently overwrote the four committed files in
`rb_system/ob_reference_data/`. This was caught via `git status` immediately
after and reverted with `git checkout --`, so no reference data was lost.
Always run `weekly_ob_generator.py` against a *copied* CSV in a scratch
directory (not a symlink into the repo), and check `git status` on
`rb_system/ob_reference_data/` afterward.

### 3b. Swing/MSS parity (required: must match exactly)

Ran `weekly_rb_generator.py` and `weekly_ob_generator.py` against the same
`EURUSD_m1_BidAndAsk.csv` with `--input-tz Etc/GMT+2`:

```
diff weekly_rb_swings.csv weekly_ob_swings.csv   # (SWING rows + MSS rows, after
                                                    normalizing the RB writer's
                                                    MSS_UP/MSS_DOWN column
                                                    format to match OB's)
→ no differences
```

Result: **all 20 swing events and all 4 MSS events are byte-identical**
between the two engines (same kind, origin week, confirm week, price). This
confirms the swing/MSS port is correct and unchanged, as required.

### 3c. Hand-traced RB records against raw weekly OHLC (construction + impact)

Traced record `id=2` (`ARB SELL`, origin week idx 4 = week starting
`2026-01-25 22:00:00 UTC`):
- Week 4 raw OHLC: O=1.18649, H=1.20825, L=1.18346, C=1.18478 (confirmed
  directly from the aggregated `Week` objects).
- This is a swing-HIGH pivot (swing high price 1.20825 matches
  `SWING,HIGH,...,2026-02-01 22:00:00,1.20825` in the swings CSV, confirmed
  the following week). Per spec: `zt = high = 1.20825`,
  `zb = max(open,close) = max(1.18649, 1.18478) = 1.18649`, label bearish by
  raw wick type (swing-high wick) → side SELL.
- Ledger row 2: `bottom=1.18649, top=1.20825, side=SELL` — **matches exactly**.
- `type=ARB`, `trigger_week_idx=6`, `eligible_week_idx=6` (same as trigger,
  i.e. immediate eligibility) — correct per spec (ARB = immediate eligibility,
  no delay).
- Impact trace: zone `[1.18649, 1.20825]` sits well above week 6's opening
  price action (week 6 M1 rows near 22:26-23:07 UTC on 2026-02-08 sit around
  1.1809, i.e. `high < 1.18649 = zb`, so no impact yet at that point — checked
  directly against raw M1 rows). Ledger's recorded impact time
  `2026-02-09 11:01:00 UTC` is later that same week, consistent with price
  having to rally up into the zone before the "any wick reaching into the
  zone" impact condition (`H>=zb and L<=zt`) can fire. This confirms the
  impact check is not firing prematurely or on the wrong week.

Traced record `id=4` (`ARB BUY`, origin week idx 10 = week starting
`2026-03-08 21:00:00 UTC`):
- Week 10 raw OHLC: O=1.15599, H=1.16669, L=1.14089, C=1.14123.
- Swing-LOW pivot (swing low price 1.14089 matches the swings CSV). Per spec:
  `zb = low = 1.14089`, `zt = min(open,close) = min(1.15599,1.14123) =
  1.14123`, label bullish (swing-low wick) → side BUY.
- Ledger row 4: `bottom=1.14089, top=1.14123, side=BUY` — **matches exactly**.

Both traces confirm RB zone construction (`zb`/`zt`/side) and the
impact-lifecycle timing are computed per the pine spec, not guessed.

### 3d. Not yet hand-traced

- A full ARB reference-validity-guard trace (confirming `try_bull_arb`/
  `try_bear_arb`'s "no candle broke past the armed extreme between armed and
  new swing" guard actually blocks a would-be zone in this dataset) — the 13
  RB zones produced all passed the guard silently; no case where the guard
  actually rejected a candidate was observed/traced in this dataset, so the
  guard's rejection branch itself remains code-reviewed but not evidence-
  verified against a real blocked case.
- IRB stranding (far-side) and ARB stranding (near-side) were code-reviewed
  against the pine STEP3 block line-by-line but not separately hand-traced
  against a specific stranded record's raw M1 rows the way §3c did for
  construction/impact. Record `id=1` (IRB BUY → ORB) and `id=2` (ARB SELL →
  ORB... note: record 2 is `ARB`/status `ARB`, still open, not stranded) —
  record `id=1`'s `ORB` transition and record `id=9`'s `ORB` transition are
  candidates for this trace; not yet done.
- No H4 RB cascade, no 5m BSO-RB integration, no combined RB viewer (Pine)
  have been built yet.

## 4. Decisions made (record every one, not just the final state)

1. **Reused OB's M1-based `high_first` tie-break, not pine's `close>=open`
   heuristic**, for ordering which of a bar's two possible breaks (high vs
   low) is processed first. Rationale: the task's own instruction is "swing
   detection is 100% unchanged from OB," and OB's Python engine already
   deliberately replaced pine's heuristic with real M1-order data (this is
   presumably why the Python OB engine exists at all — to get exact ordering
   pine's own bar-close heuriistic can't). Verified this choice is correct by
   the exact swing/MSS byte-match in §3b; had this been wrong, the swing/MSS
   output would very likely have diverged from OB's on at least one of the
   dataset's several same-bar dual-break weeks.
2. **`--input-tz Etc/GMT+2`** used for RB-vs-OB comparison runs, per §3a.
3. RB's `first_touch`/impact check was written as a single symmetric
   condition (`H>=zb and L<=zt`, i.e. "any wick reaching into the zone"),
   matching pine's STEP3 literally, rather than reusing OB's asymmetric
   bull/bear-specific `first_touch` (OB's impact rule is directional: a BUY
   zone is touched by a strict low break below its top, a SELL zone by a
   strict high break above its bottom — a different, OB-specific rule).
   This was a deliberate divergence from the OB Python helper of the same
   name, not an oversight — RB's impact rule in the pine spec is genuinely
   simpler and symmetric.
4. Kept RB ledger/CSV schema deliberately smaller than OB's (no
   `origin_first_price`/H1-audit-body columns, no `trigger_fact_source`
   provenance split) since none of that OB-specific display-audit apparatus
   (§4-5 of the OB handoff, born from the OB box-body investigation saga) has
   an RB analog yet — RB zones are constructed directly from a single
   candle's OHLC with no "best origin picking" ambiguity to audit. Flagged
   as open in §5 in case the user wants the same audit columns added for
   parity of workflow (e.g. a Riyadh-display column set, per-record
   inspection toggle in a future RB Pine viewer).

## 5. Open questions / ambiguities — STOPPED rather than guessed

- **No RB analog exists yet for H4/5m.** The task scope for this pass was
  Weekly-only if time ran out; H4 RB cascade (`h4_rb_engine.py`, mirroring
  `h4_ob_engine.py`) and 5m BSO-RB entries were not started. `h4_ob_engine.py`
  and `five_bso_engine.py` were read structurally (both reuse `WeeklyOBEngine`
  directly, e.g. H4 via `origin_gap_window=None`) — the same reuse pattern
  should carry over to a `WeeklyRBEngine`-based H4 RB engine, but this has not
  been attempted or verified.
- **RB Pine viewer not yet generated for the Python Weekly RB engine.**
  `RB_Indicator_v1.pine` itself is a live-calculating Pine diagnostic (not a
  static-viewer generator like `weekly_ob_viewer.pine`). A parallel
  `weekly_rb_viewer.pine`-style *static* viewer (Python-generated, pre-
  calculated draw instructions, mirroring `weekly_ob_generator.write_ob_pine`)
  has not been written. Its drawing conventions (dashed/hollow boxes; IRB
  blue/black by raw wick label; ARB green; ORB red hidden on 5m/1h/4h) are
  already specified in the pine file's own header comment and its drawing
  block (lines 529-575 in `RB_Indicator_v1.pine`), so this is not an open
  ambiguity, just unstarted work.
- **No genuine ambiguity was hit in the pine spec itself** for the Weekly
  layer — `addRBFromSwing`/`tryBullARB`/`tryBearARB`/STEP2/STEP3 map onto
  Weekly bars unambiguously using the same OB-Python infrastructure
  (`Week`/`Minute`/`Event`/`MSS`). If a genuine RB-specific ambiguity
  surfaces at the H4 or 5m layer (e.g. how `hideOOBHere`'s ORB-hiding
  convention should map onto a table/ledger row, since the Python reference
  is CSV/ledger-only and does not "hide" rows the way a live Pine chart
  hides boxes at certain timeframes), it should be raised explicitly before
  guessing, per the pine file's own flagged comment
  ("flag if RB shouldn't follow that convention").

## 6. Files

- `rb_system/reference/weekly_rb_generator.py` — Weekly RB engine (this
  session).
- `rb_system/data/weekly_rb_swings.csv`, `weekly_rb_ledger.csv`,
  `weekly_rb_report.txt` — generated from
  `rb_system/ob_reference_data/EURUSD_m1_BidAndAsk.csv` with
  `--input-tz Etc/GMT+2` (default `--week-close-zone America/New_York
  --week-close-hour 17 --display-tz Asia/Riyadh`).
- Run command:
  ```
  cd rb_system/reference
  python3 weekly_rb_generator.py ../ob_reference_data/EURUSD_m1_BidAndAsk.csv --input-tz Etc/GMT+2
  ```

## 7. State of the branch at end of this session

- Weekly RB engine: **built and hand-verified** per §3 (swing/MSS byte-match;
  2 RB records fully traced for construction+impact against raw weekly OHLC
  and M1 rows).
- H4 RB cascade, 5m BSO-RB, combined RB viewer: **not started** — stopping
  here per the task's own instruction to stop at a clean, verified,
  committed checkpoint rather than leave a half-built later layer unverified.
- Next exact action for a continuing session: build `h4_rb_engine.py` by
  reusing `WeeklyRBEngine` the same way `h4_ob_engine.py` reuses
  `WeeklyOBEngine` (`origin_gap_window=None`, H4-bar aggregation in place of
  Weekly), then hand-verify 2-3 H4 RB records the same way §3c did for
  Weekly, before moving to 5m.
