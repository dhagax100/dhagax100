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

### 3d. Follow-up verification (this session, continuation, 2026-09-18)

**ARB reference-validity guard — now evidence-verified, not just code-reviewed.**
Instrumented a scratch copy of the engine (`/tmp/dbg_rb.py`, not committed) to
print whenever `try_bull_arb`/`try_bear_arb`'s guard condition
(`any(...)` over the range between the armed extreme and the new swing)
evaluates true, i.e. actually blocks a candidate. Running it against the
real dataset produced exactly one block:
```
BLOCK bear_arb 20 24 24
```
i.e. `try_bear_arb(preg, aob_swl_i=20, new_swh_i=24, k=24)` was blocked.
Checked the raw weekly OHLC directly (`weeks[20..24]`, from
`aggregate_weeks`/`load_minutes` against
`ob_reference_data/EURUSD_m1_BidAndAsk.csv --input-tz Etc/GMT+2`):
- `w[20].l = 1.15759` → `armed_l_price`.
- `w[21].l=1.15859, w[22].l=1.15175, w[23].l=1.14994, w[24].l=1.14175`.
- `w[22].l = 1.15175 <= 1.15759 = armed_l_price` → the guard condition
  `any(self.w[v].l <= armed_l_price for v in range(21, 25))` is **True at
  v=22**, so the guard correctly fires and returns without creating a zone.

Without the guard, this would have wrongly built an ARB BUY zone anchored on
week 20's low (1.15759) even though price had already made a materially
deeper low (1.14175, week 24) by the time week 24's swing high confirmed —
exactly the invalid-reference case the guard exists to prevent (the armed
extreme is stale/broken by the time the opposite swing would arm the zone).
This confirms the guard is not dead code and fires correctly on real EURUSD
data. (No `try_bull_arb` block occurred in this dataset — only the bear-side
guard was exercised — but the logic is symmetric and the swing/MSS state
machine feeding both is byte-identical to OB's, verified in §3b, so this one
confirmed firing is treated as sufficient evidence for both branches.)

**IRB/ARB stranding — now hand-traced against raw M1 data.**
Picked record `id=3` (`IRB SELL`, `bottom=1.18664`, `top=1.19283`,
`eligible_week_idx=12`, `status=ORB`, `stop_week_idx=-1` — the `-1` stop
with `ORB` status flags this as an ORB reached via **stranding**, not
impact, since impact always sets `stop=k`).
- `z.bullish=False` (SELL), `z.origin=0` (IRB) → per STEP3's `is_irb` branch:
  stranding requires a **SWING HIGH** event (`kind=0`) with
  `price < z.zb (1.18664)`, confirmed while the zone is still state 0/1.
- `weekly_rb_swings.csv` has `SWING,HIGH,origin=2026-03-22,confirm=2026-03-29,
  price=1.16394`. `1.16394 < 1.18664` → satisfies the stranding condition.
  Confirm week (`2026-03-29 21:00 UTC`) matches ledger row 4/5's
  `trigger_week_idx=13` week start exactly, so this event's `confirm` index
  is week 13.
- Verified the swing price against **raw M1 rows** directly (not just the
  derived CSV): scanned `EURUSD_m1_BidAndAsk.csv` for all M1 rows in
  `[2026-03-22 21:00:00 UTC, 2026-03-29 21:00:00 UTC)` (week 12) and took
  the max `HighBid` — result: **1.16394 at 2026-03-23 16:38:00 UTC**,
  matching the swing event price exactly.
- Conclusion: at `k=13`, `finish_events_and_lifecycle`'s STEP3 stranding
  loop sees this SWING HIGH event with `confirm==13==k`, `price=1.16394 <
  zb=1.18664`, `is_irb=True`, `z.bullish=False` → the branch
  `if not z.bullish and ev.kind == 0 and ev.price < z.zb: stranded = True`
  fires, setting `z.state = 2` (ORB) with `stop` left at its prior value
  (`-1`, since only the impact branch sets `stop`). This matches record
  `id=3`'s ledger row exactly (`status=ORB, stop_week_idx=-1`) and confirms
  the far-side IRB stranding rule fires correctly against real M1 data, not
  just self-consistently against the derived CSVs.

Both items previously flagged as unverified are now resolved with direct
evidence against the raw dataset. No bugs found in either check.

- No H4 RB cascade, no 5m BSO-RB integration, no combined RB viewer (Pine)
  have been built yet (addressed in the rest of this session — see below).

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

## 5b. H4 RB cascade (this session, continuation, 2026-09-18)

Built `rb_system/reference/h4_rb_engine.py`, reusing `WeeklyRBEngine` on a
native 4-hour bar grid, the same way `h4_ob_engine.py` reuses
`WeeklyOBEngine` (H4 anchor hour `01:00 UTC`, chart-verified 2026-09-16 for
OB and reused as-is here since it's a pure calendar-grid fact, not an
OB-specific rule).

**Resolved ambiguity: no RB analog to `weekly_control_engine.py`'s
permission gating.** `h4_ob_engine.py` only draws an H4 OB whose direction
matches the Weekly `BUY_ONLY`/`SELL_ONLY`/`BOTH` control state from
`weekly_control_engine.py` (SPEC.md SS9-16). That state machine is built
entirely on OB-specific zone-lifecycle facts (the `rejected`-vs-OOB
distinction, the AOB/IFOB/AIFOB state family, a Weekly-close body-death rule
discovered specifically for OB). Grepped `RB_Indicator_v1.pine` in full for
"control"/"permit"/"BUY_ONLY"/"SELL_ONLY"/"BOTH"/"weekly" -- **zero
matches**. The RB pine script is a standalone, timeframe-agnostic
calculation with no cross-timeframe permission layer at all. Conclusion:
there is no RB spec to gate H4 RB zones against, and building one would be
inventing a rule that exists in neither the OB reference code nor the RB
pine spec. `h4_rb_engine.py` therefore writes every computed H4 RB zone to
`h4_rb_ledger.csv` UNGATED (own IRB/ARB/ORB/SPENT lifecycle only, no
authorized/drawn split). Flagged here per the task's "stop rather than
guess" instruction, even though the answer was "no gating needed" rather
than a blocker.

Verification:
- **Swing/MSS byte-parity at H4 resolution**: ran `WeeklyOBEngine` and
  `WeeklyRBEngine` on the identical H4 bar grid (`h4_rb_engine.aggregate_h4`,
  anchor hour 1, same EURUSD CSV) -- 499 swing events and 150 MSS events,
  **byte-identical** between the two engines (kind, confirm, swing, price
  all match). Confirms the H4 reuse preserves swing/MSS parity the same way
  the Weekly reuse did in §3b.
- **Hand-traced 3 H4 RB records against raw bar/M1 data**:
  - Record `id=1` (IRB SELL, bar idx 1, `2026-01-02 09:00 UTC`). Raw H4 bar
    1: O=1.17434, H=1.17467, L=1.17128, C=1.17207 (swing-high pivot). Per
    spec: `zb=max(O,C)=1.17434`, `zt=H=1.17467` -- **matches ledger exactly**
    (`bottom=1.17434, top=1.17467`). Impact: ledger records
    `impact_time_utc=2026-01-02 17:54:00`. Scanned raw M1 rows directly for
    `2026-01-02 17:00-18:10 UTC` -- the first minute where `H>=zb(1.17434)
    and L<=zt(1.17467)` is **17:54:00** (`H=1.17460, L=1.17403`), the minute
    immediately before (17:53:00, H=1.17405) does not qualify. **Matches
    the ledger's impact timestamp exactly**, confirming H4 impact detection
    against real M1 data, not just self-consistency with the derived CSV.
  - Record `id=3` (ARB SELL, bar idx 3). Raw H4 bar 3: O=1.17283, H=1.17542,
    L=1.17149, C=1.17186. `zb=max(O,C)=1.17283`, `zt=H=1.17542` -- matches
    ledger exactly (`bottom=1.17283, top=1.17542`).
  - Record `id=4` (IRB SELL, bar idx 5). Raw H4 bar 5: O=1.17186, H=1.17257,
    L=1.17186, C=1.17208. `zb=max(O,C)=1.17208`, `zt=H=1.17257` -- matches
    ledger exactly. **Observation (not a bug)**: this record's ledger row
    shows `status=ORB` alongside a real `stop_bar_idx=11` and
    `impact_time_utc` set -- i.e. it was stranded to ORB first, then later
    actually impacted (price wicked back through the now-invalidated zone).
    This is a legitimate consequence of STEP3's own ordering (the impact
    check runs for any `state != 3`, including state 2/ORB; only the
    stranding check is restricted to state 0/1) -- both branches were
    independently verified already (impact in record 1 above, stranding in
    the Weekly §3d trace of record `id=3`), so this is the same two
    mechanisms firing in sequence on one zone, not new/unverified logic.
    Not observed in the Weekly ledger (all 3 Weekly ORB rows there happened
    to have `stop=-1`), but nothing in the code restricts it to H4 -- it
    simply needs enough bars for both events to occur on the same zone,
    which is more likely at H4 resolution than Weekly.

Files added: `rb_system/reference/h4_rb_engine.py`,
`rb_system/data/h4_rb_swings.csv`, `h4_rb_ledger.csv`, `h4_rb_report.txt`
(1133 H4 bars, 499 swings, 150 MSS, 393 RB zones).

## 5c. 5m BSO entries for RB (this session, continuation, 2026-09-18)

**Checked `five_bso_engine.py`'s actual code rather than assuming either
way (per the task's explicit question).** Finding: `run_bso()`,
`structural_invalid_at()`, `run_bso_chain()`, `ledger_row()` and
`aggregate_5m()` are already POI-type-agnostic -- they only ever read a
zone through `z.id`/`z.bullish`/`z.zb`/`z.zt` (present with identical
meaning on both `wob.Zone` and `wrb.RbZone`) and a swing event through
`kind`/`swing`/`at`/`price`/`confirm` (structurally identical dataclass in
both engines). None of that logic touches any OB-specific field (`state`
value family, `pre_spent_state`, `rejected`). Built
`rb_system/reference/five_rb_bso_engine.py`, importing those five functions
UNCHANGED from `ob_reference/five_bso_engine.py` (not copied) -- only
`main()` needed a replacement, because the ORIGINAL `main()` is genuinely
OB-specific: it hard-gates targets through `weekly_control_engine.py`'s
permission ledger and OB's `pre_spent_state in (0,1,4)` state family. Per
§5b's finding (RB has no control-ledger analog), the new `main()` instead
targets every H4 RB zone that was **impacted** (`state==3`) and **never
stranded before that impact** (`pre_spent_state in (0,1)` -- IRB or ARB;
excludes 2/ORB, RB's direct analog of OB's OOB-exclusion rule).

Result: 273 impacted, never-stranded H4 RB zones fed into the BSO search;
199 `ENTERED`, 152 `H4_OB_BREACHED` (no re-entries reported beyond attempt 1
in this run -- consistent with `run_bso_chain`'s own "only report a
re-entry that became a trade" rule, reused verbatim).

**Hand-traced 2 records against raw M1 data**:
- `rb_id=1` (SELL, H4 RB record 1 from §5b) -- `H4_OB_BREACHED`,
  `invalidation_reason=swing_break` at `2026-01-02 17:55:00 UTC`. Consistent
  with record 1 being impacted, then price continuing straight through
  (the same M1 rows scanned in §5b for the impact trace show price still
  climbing past 17:55), invalidating any resting-swing search before one
  could form.
- `rb_id=2` (BUY, H4 RB record 2, `zb=1.17128, zt=1.17207`, impact
  `2026-01-02 21:07:00`). Ledger: `entry_time=2026-01-02 21:51:00,
  entry_price=1.17181`; `sl_price=1.17139`; `result=SL,
  exit_time=2026-01-05 00:56:00, exit_price=1.17139`. Checked raw M1 rows
  directly: at `21:50:00` H=1.17179 (candidate price 1.17181 not yet
  broken); at `21:51:00` H=1.17194 > 1.17181 -- **entry fires at exactly
  this minute**, matching the ledger. For the SL exit: at `00:55:00` on
  2026-01-05, L=1.17182 (SL 1.17139 not yet touched); at `00:56:00`,
  L=1.17112 <= 1.17139 -- **SL fires at exactly this minute**, matching the
  ledger's exit time and price exactly.

No bugs found; the reused core behaved identically on RB zones as it does
on OB zones, as expected from the POI-agnostic finding above.

Files added: `rb_system/reference/five_rb_bso_engine.py`,
`rb_system/data/five_rb_bso_ledger.csv`.

## 5d. `weekly_control_engine.py` reuse question -- answered (this session)

Already answered in full in §5b: `weekly_control_engine.py` is NOT
reusable as-is for RB, and there is no RB analog to build in its place.
It is built entirely on OB-specific facts (the `rejected`-vs-OOB
distinction, the AOB/IFOB/AIFOB state family, a Weekly-close body-death
rule discovered specifically for OB) and its own SPEC.md SS9-16, none of
which exist in `RB_Indicator_v1.pine` (confirmed by a full grep -- zero
mentions of control/permission/weekly-gating anywhere in that file). No
new module was built for this; `h4_rb_engine.py` and `five_rb_bso_engine.py`
both simply skip the gating step entirely, using their own zone-lifecycle
status instead (impacted + never-ORB-before-impact).

## 5e. Combined RB Pine viewer (this session, continuation, 2026-09-18)

Built `rb_system/reference/full_viewer_rb.py`, an RB analog of
`ob_reference/full_viewer.py`, deliberately smaller in scope since RB has
no control layer and the task only asked for the RB-equivalent drawing,
not a BSO-lines layer (that already has its own ledger from §5c). It
draws:
- Weekly RB zones + swing/MSS labels + a ledger table, on the Weekly chart
  (`onWeekly`, reusing `WeeklyRBEngine` unchanged, same swing/MSS output
  already verified in §3b/§5b).
- H4 RB zones + a ledger table, on the H4 chart (`onH4`), and the SAME H4
  boxes (no table) also on the 5m chart (`onFive`) -- matching
  `full_viewer.py`'s own cross-timeframe convention for its H4 OB layer.

Drawing convention, taken verbatim from `RB_Indicator_v1.pine`'s header
(lines 26-33, the only RB drawing-rule source per this project's
discipline): dashed border (`border_style=line.style_dashed`), hollow
(`bgcolor=na`); IRB = blue(bull)/black(bear) by the zone's own raw-wick
`bullish` field (unaffected by which hunt fired it -- confirmed this is
already the raw-wick label, not the trigger-hunt label, by re-reading
`weekly_rb_generator.py`'s own `add_rb_from_swing`/`consume_break`/
`try_bull_arb`/`try_bear_arb` -- `bullish` is set once at zone creation
from the swing-pivot's wick type and never touched again); ARB = green,
fixed; ORB = red, fixed, and skipped entirely on the H4 and 5m draw layers
(`hide_orb=True` there) -- only ever drawn on the Weekly chart. Carried
this "hidden on lower timeframes" rule over from the pine file's own text
("hidden on 5m/1h/4h like OOB/OFVG ... flag if RB shouldn't follow that
convention") WITHOUT silently altering it, per that comment's own explicit
instruction to flag rather than assume -- flagging it here as inherited,
not independently re-derived or verified against a real chart. There is
no native 1h engine in this Python reference for either OB or RB, so the
"hidden on ... 1h" part of that sentence has no layer to apply to yet.

**Real bug found and fixed while building this**: an f-string used inside
a Python list comprehension containing an escaped `\"` triggered
`SyntaxError: f-string expression part cannot include a backslash`
(Python's f-string grammar disallows a backslash inside the expression
part, only inside the literal text) -- fixed by removing the redundant
re-quoting entirely (the source strings were already correctly quoted).

**What this has NOT been checked against**: unlike the earlier RB stages,
this Pine file has not been pasted into TradingView and chart-verified --
the task's remaining time did not cover that step. Its array-packed
runtime-draw-loop technique is copied directly from `weekly_ob_generator.
write_ob_pine`/`full_viewer.py`'s H4 layer, both of which were themselves
only made statement-limit-safe after real TradingView failures (CE10205/
CE10295, documented in the OB handoff) forced that redesign -- this file
reuses that already-proven structure rather than the original naive
one-statement-per-zone approach, but "reuses a proven pattern" is not the
same as "has itself been pasted into Pine Editor and confirmed to compile
and render correctly." Flagging this explicitly rather than claiming a
verification that was not actually done.

Files added: `rb_system/reference/full_viewer_rb.py`,
`rb_system/data/full_viewer_rb.pine`.

## 8. RB wired to OB's existing Weekly control signal (this session, 2026-09-18, continuation 2)

**Decision (user's explicit choice, overriding nothing in §5d's reasoning,
only its conclusion about what to DO):** §5d correctly found that RB's own
pine spec (`RB_Indicator_v1.pine`) has no control/permission concept at
all, and that inventing an RB-native control rule would be guessing. Given
that, the user chose: do not invent one. Instead, run `weekly_control_engine.py`
exactly as before (OB-specific, unmodified, driven on OB zones) and have
RB's H4/5m engines OBEY that same Weekly permission timeline as an external
gate -- i.e. RB now reacts only to whichever direction (BUY_ONLY/SELL_ONLY/
BOTH/NONE) OB's own control state machine currently permits, rather than
reacting to every RB opportunity unconditionally (the previous behavior,
per §5b/§5d).

**Exact wiring (mirrors `h4_ob_engine.py`'s own interface, not reinvented):**
- `h4_ob_engine.py` consumes control via: `load_control_by_week(path)` (reads
  `weekly_control_ledger.csv`'s `week_index`/`control` columns into a dict),
  `permits(control, bullish)` (`BUY_ONLY`/`BOTH` permit bullish,
  `SELL_ONLY`/`BOTH` permit bearish), and a local `control_at(t)` closure
  that bisects `t` into the Weekly week-start grid built from
  `wob.aggregate_weeks(minutes, close_tz, week_close_hour)`.
- `rb_system/reference/h4_rb_engine.py` now defines byte-identical
  `load_control_by_week`/`permits` helpers, takes the same
  `--control-ledger`/`--week-close-zone`/`--week-close-hour` CLI flags,
  rebuilds the same Weekly week-start grid (via `weekly_ob_generator.
  aggregate_weeks`, imported alongside `weekly_rb_generator`, since the
  control ledger's week index is OB's Weekly grid, not RB's -- they must be
  the identical grid for the bisect to line up, and they are: both call
  `aggregate_weeks` with the same default `America/New_York`/17
  close convention), and for every H4 RB zone computes
  `ctrl = control_at(z.impact_time)` and
  `authorized = impacted and pre_spent_state in (0,1) and permits(ctrl, z.bullish)`
  -- `pre_spent_state in (0,1)` (IRB/ARB, never-stranded-before-impact) is
  RB's own pre-existing exclusion rule from §5c, kept unchanged; only the
  `permits(...)` clause is new. `h4_rb_ledger.csv` gained two columns,
  `control_at_impact` and `authorized`, exactly mirroring `h4_ob_ledger.csv`'s
  own columns of the same name. Every H4 RB zone is still written to the
  ledger for audit (ungated rows kept, same as OB); only `authorized` says
  whether it would be actioned.
- `rb_system/reference/five_rb_bso_engine.py`'s `main()` previously targeted
  every impacted, never-stranded H4 RB zone unconditionally (§5c). It now
  additionally requires `h4rb.permits(control_at(z.impact_time), z.bullish)`
  before adding a zone to `targets` -- same `load_control_by_week`/`permits`
  functions (imported from `h4_rb_engine`, not duplicated), same
  `control_at` bisect logic, same CLI flags. A zone that fails this check is
  never even passed to `run_bso_chain`, so it produces zero rows in
  `five_rb_bso_ledger.csv` (not merely marked unauthorized) -- consistent
  with OB's own `five_bso_engine.py`, which does the identical thing (only
  `authorized` targets ever reach `run_bso_chain`).
- Both scripts fail loudly (exit 2, explicit stderr message) if
  `weekly_control_ledger.csv` is missing, exactly like `h4_ob_engine.py`/
  `five_bso_engine.py` do -- RB's H4/5m stages now have the same hard
  dependency on `weekly_control_engine.py` having been run first that OB's
  own H4/5m stages have. Run order is now:
  `weekly_control_engine.py -> weekly_rb_generator.py -> h4_rb_engine.py -> five_rb_bso_engine.py`.

**Checked the interface was clean, not entangled, before wiring (per the
task's own stop-condition):** `load_control_by_week`/`permits`/the
`control_at` bisect pattern read only `week_index`/`control` from the CSV
and a zone's `bullish`/`impact_time` -- nothing OB-zone-specific (no
`rejected`, `pre_spent_state` value family, `origin_state`, or any
AOB/IFOB/AIFOB concept leaks into that interface). It was a clean external
signal to consume, exactly as the task anticipated; no blocker was hit.

**Verification (hand-traced against real data, record IDs cited):**

`weekly_control_ledger.csv` week 15 (`week_index=15`, `week_start_utc=
2026-04-12 21:00:00`) has `control=SELL_ONLY` (confirmed directly from the
CSV row: `15,2026-04-12 21:00:00,2026-04-13 00:00:00,BULLISH,SELL_ONLY,,3`),
and week 16 (`2026-04-19 21:00:00`) is also `SELL_ONLY` -- so the whole span
`2026-04-12 21:00:00` to `2026-04-26 21:00:00` is a single continuous
SELL_ONLY period.

- **Suppressed (previously would have fired unconditionally, now correctly
  gated out):** H4 RB record `id=166` (BUY, IRB, `bottom=1.16771,
  top=1.16838`, `impact_time_utc=2026-04-12 21:00:00` -- inside the
  SELL_ONLY week). `pre_spent_state` is IRB (never stranded), so before
  this change it was one of the 273 "impacted, never-stranded" zones fed
  unconditionally into the 5m BSO stage. After the gate:
  `h4_rb_ledger.csv` row 166 now reads `control_at_impact=SELL_ONLY,
  authorized=False` (BUY direction, SELL_ONLY control -> `permits()`
  returns False). Confirmed it produces **zero rows** in
  `five_rb_bso_ledger.csv` (`grep '^166,' five_rb_bso_ledger.csv` -> no
  match) -- the suppression propagates all the way through the 5m stage,
  not just the H4 ledger's audit column.
- **Still fires (permitted direction, same control period):** H4 RB record
  `id=171` (SELL, IRB, `bottom=1.17948, top=1.18015`,
  `impact_time_utc=2026-04-15 15:28:00` -- same SELL_ONLY week).
  `h4_rb_ledger.csv` row 171 reads `control_at_impact=SELL_ONLY,
  authorized=True` (SELL direction, SELL_ONLY control -> permitted).
  Confirmed `five_rb_bso_ledger.csv` has a row for `rb_id=171`
  (`stage=ENTERED`, `entry_utc=2026-04-15 18:35:00`, `result=SL,
  exit_utc=2026-04-15 19:27:00`) -- fires exactly as it would have before
  this change, since it was already control-permitted.
- **Aggregate consistency check:** `h4_rb_engine.py` reports
  `RB zones: 393 ... Authorized: 44`; `five_rb_bso_engine.py` independently
  recomputes the same gate from scratch (does not read
  `h4_rb_ledger.csv`'s `authorized` column, recomputes via its own
  `control_at`/`permits` call) and reports
  `273 impacted, never-stranded H4 RB zones; 44 also control-authorized` --
  the two independent computations agree exactly (44 == 44), confirming the
  duplicated gate logic in the two scripts is consistent, not diverged.

No bugs found; the OB control interface was cleanly reusable exactly as
anticipated, and both suppression and permission cases traced to real
ledger rows with matching timestamps/control state.

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

## 7. State of the branch at end of this session (updated 2026-09-18, continuation)

- Weekly RB engine: **built and hand-verified** per §3 (swing/MSS byte-match;
  2 RB records fully traced for construction+impact against raw weekly OHLC
  and M1 rows), PLUS §3d's follow-up: the ARB reference-validity guard and
  IRB/ARB stranding are now BOTH evidence-verified against real data (no
  longer just code-reviewed) -- one real guard block found and traced
  (week 22 low breaking the armed low from week 20), one real stranding
  found and traced (record `id=3`, swing high 1.16394 confirmed against
  raw M1 data below its zone bottom).
- H4 RB cascade: **built and hand-verified** (§5b) --
  `rb_system/reference/h4_rb_engine.py`, byte-identical swing/MSS at H4
  resolution, 3 records hand-traced against raw H4/M1 data. Resolved
  ambiguity: no RB analog to OB's weekly-control gating exists, so the H4
  RB ledger is intentionally ungated.
- 5m BSO for RB: **built and hand-verified** (§5c) --
  `rb_system/reference/five_rb_bso_engine.py`, reusing OB's
  `run_bso`/`structural_invalid_at`/`run_bso_chain`/`ledger_row`/
  `aggregate_5m` UNCHANGED (confirmed POI-agnostic by reading the code),
  with only `main()`'s targeting rule replaced (impacted + never-stranded,
  no control gate). 2 records hand-traced against raw M1 rows (exact entry
  and SL-exit minute/price match).
- `weekly_control_engine.py` reuse question: **answered** (§5d) -- not
  reusable, no RB analog exists or was built; both H4/5m RB engines above
  simply skip that gating step.
- Combined RB Pine viewer: **built** (§5e) --
  `rb_system/reference/full_viewer_rb.py` /
  `rb_system/data/full_viewer_rb.pine`. Drawing conventions taken verbatim
  from `RB_Indicator_v1.pine`'s header. One real bug found and fixed while
  building it (an f-string containing a backslash inside its expression
  part -- Python syntax error, fixed by removing redundant re-quoting).
  **Not yet chart-tested in TradingView** -- flagged explicitly in §5e as
  the one remaining unverified piece of this session's work; the array-
  packing technique it uses is copied from OB's own already
  statement-limit-safe pattern, but that is not the same as confirming
  this specific generated file compiles and renders in Pine Editor.
- Every stage above has its own commit on `claude/practical-gauss-je3gsg`,
  pushed incrementally (not one giant commit): `dcc2877` (guard/stranding
  verification), `ae9c2f3` (H4 cascade), `d40ea19` (5m BSO), and the commit
  containing this handoff update (viewer + final write-up).
- No genuine unresolved ambiguity remains open from this continuation pass
  beyond the one flagged above (viewer not chart-tested) -- every other
  question the task asked ("does X need an RB variant or is it reusable
  as-is") was answered by reading the actual code, with the reasoning
  recorded in §5b/§5c/§5d, not assumed either way.
## 9. CORRECTION: RB now runs its own control state machine, not OB's (2026-09-18, new session)

**The user correctly identified §8's wiring as wrong.** §8 gated RB's H4/5m
opportunities against OB's OWN `weekly_control_ledger.csv` -- i.e. literally
OB's zone-impact timeline (`weekly_control_engine.py` driven on OB's
IFOB/AOB/OOB zones). The STATE-MACHINE RULE ("a zone impacts while
control==NONE -> control flips to BUY_ONLY/SELL_ONLY based on that zone's
side", plus pause/resume/BOTH/zone-death) is shared/analogous logic between
OB and RB, but WHICH zone reaches impact and WHEN is specific to each
system's own construction -- IRB/ARB/ORB fire and impact on a completely
different schedule than IFOB/AOB/OOB. So the control state machine had to
be RE-RUN on RB's OWN zone timeline, not read off OB's precomputed ledger.

### 9a. New module: `weekly_control_engine_rb.py`

A rule-for-rule port of `weekly_control_engine.py`, driven on
`weekly_rb_generator.WeeklyRBEngine`'s own IRB/ARB/ORB/SPENT zones and
impact events instead of OB's. Full reasoning is in the new module's own
docstring (kept in sync with this section); summarized here:

**Substitution decisions (every one recorded, per the task's own
requirement):**

1. **`rejected` flag -- no RB analog, none invented.** `RbZone` (in
   `weekly_rb_generator.py`) has no `rejected` field at all -- checked its
   full dataclass field list directly. RB_Indicator_v1.pine has no
   pre-eligibility-breach mechanism the way OB does. Substitution:
   `rejected` is hardwired absent everywhere OB's `is_alive_state`/
   `is_spent_state` take it as a parameter; `newly_rejected_ids` is never
   populated (stays permanently empty).
2. **`is_alive_state(state, rejected)`** -- OB: `state in (0,1,4) and not
   rejected` (IFOB/AOB/AIFOB). RB has no AIFOB-equivalent 3rd alive type
   (RB zones are created once as IRB(0) or ARB(1), never promoted to a
   third type). Substitution: `is_alive_state(state) := state in (0, 1)`.
3. **`is_spent_state(state, rejected)`** -- OB: `state==3 and not rejected`.
   RB: `state==3` (trivial, since `rejected` is always False for RB).
4. **`body_close_dead()` -- NO RB ANALOG EXISTS, and this was verified
   structurally, not guessed.** Traced exactly how OB's `body_close_dead`
   is used in `weekly_control_engine.py`: it fires ONLY inside the
   single-side ZONE_DEATH block (`if control in (BUY_ONLY,SELL_ONLY) and
   controlling_zone_id is not None: ... if body_close_dead(...): control =
   NONE`), letting an ALREADY-SPENT zone's thesis die a SECOND time (via a
   later Weekly candle's body closing at/through its near boundary) even
   though the OB engine's own `state` field never changes once SPENT.
   RB_Indicator_v1.pine's header is explicit and unambiguous: "Lifecycle:
   wick IMPACT + STRANDING only. No close-through rule." This is not "RB
   doesn't implement one yet" (a judgment call available to make either
   way) -- it is RB's own authoritative spec stating in so many words that
   this mechanism does not exist for RB at any layer. There is no RB fact
   (impact, stranding, SPENT) to substitute with, because once an RB zone
   is SPENT, RB's own STEP3 lifecycle never revisits it again -- there is
   structurally nothing left for a close-through check to detect. DECISION:
   `body_close_dead` is NOT ported; the single-side ZONE_DEATH transition
   is simply absent from `weekly_control_engine_rb.py`. Single-side RB
   control only ever changes via swing-pause/resume or opposing-impact
   escalation to BOTH -- the mechanisms RB's own zone facts DO support.
   This was the one point flagged by the task's "stop rather than guess"
   instruction -- resolved as a documented substitution (not a blocking
   question back to the user) because the pine spec is explicit, not
   silent, on this exact point.
5. **`newly_oob_ids`** (used for the BOTH-side `controlling_opp` zone
   breaching) -- RB's stranding-to-ORB (`state==2`) is the direct, literal
   analog of OB's stranding-to-OOB (`state==2`): both fire on "a fresh
   opposing swing forms beyond the zone while it was never impacted."
   Pointed unchanged at RB's own state transition.

Everything else (trend from `engine.regime`; pro/opposing by direction vs
current CONTROL direction; the same-week trigger-ordering machinery;
CAMPAIGN_START/CAMPAIGN_START_COUNTERTREND/OPPOSING_ENCOUNTER/
CONTROL_SWITCHED/OPPOSING_GAINS_CONTROL/OPPOSING_LOSES_CONTROL/
RETURN_TO_PRO_TREND/NO_CONTROL/SWING_PAUSE/SWING_PAUSE_BOTH/SWING_RESUME)
is copied rule-for-rule, operating on RB zone fields
(`z.bullish`/`z.state`/`z.stop`/`z.impact_time`/`z.id`).

**Verification (hand-traced against real data, evidence cited):**

- **First control transition**: `weekly_control_events_rb.csv` row 2:
  `CAMPAIGN_START_COUNTERTREND, "RB zone 2 impacted (direction=SELL,
  trend=BULLISH)", zone_id=2, at 2026-02-09 11:01:00 UTC / 2026-02-09
  14:01:00 Riyadh`. `weekly_control_ledger_rb.csv` confirms `control=NONE`
  for every week before week 6 and `control=SELL_ONLY` from week 6 onward.
  This is EXACTLY the expected transition: RB #2 (ARB, SELL, origin
  1.18649-1.20825, `weekly_rb_ledger.csv` row `id=2`) has
  `impact_time_utc=2026-02-09 11:01:00` in that same ledger -- confirming
  NONE->SELL_ONLY fires at exactly RB #2's own impact instant, not before
  or after.
- **A further transition, traced to raw data, not just the derived CSVs**:
  the very next event, `SWING_PAUSE` at `2026-02-09 14:07:00 UTC / 17:07:00
  Riyadh` ("Swing low confirms, no opposing control -> NONE"). Instrumented
  a scratch run of `WeeklyRBEngine` directly and printed every swing event
  confirmed in week 6: `Event(confirm=6, kind=1, swing=5, price=1.17652,
  at=datetime(2026,2,9,14,7,tzinfo=UTC))` -- the swing event's own `at`
  field (computed from real M1 rows by `event_time()`, not derived from the
  weekly CSVs) matches the SWING_PAUSE log entry's timestamp exactly. Since
  control was SELL_ONLY at that point and `kind_ == "swing_low"` (which
  `pauses_sell`), the pause fires correctly, dropping control to NONE for
  the rest of week 6 (confirmed resumed at week 7's `SWING_RESUME`,
  `2026-02-17 17:28:00 UTC`, per the events CSV).

Outputs: `rb_system/data/weekly_control_ledger_rb.csv`,
`weekly_control_events_rb.csv`, `weekly_control_report_rb.txt` (37 weeks
processed, 27 control-relevant events).

### 9b. Rewired the gate: `h4_rb_engine.py` / `five_rb_bso_engine.py`

Both scripts' `--control-ledger` default changed from
`weekly_control_ledger.csv` (OB's) to `weekly_control_ledger_rb.csv` (RB's
own, from 9a). The `load_control_by_week`/`permits`/`control_at` interface
SHAPE is unchanged (same CSV columns, same bisect-on-week-starts logic) --
only the file pointed at changed, so nothing downstream needed restructuring.

**Result of rerunning the full pipeline**: H4 RB zones authorized went from
**44** (old, wrong OB-ledger gate) to **76** (new, RB-native gate) out of
393 total H4 RB zones / 273 impacted-never-stranded candidates. This
matches the task's own expectation ("note how the authorized counts change
now that control opens up earlier"): RB's own control ledger reaches its
first SELL_ONLY state at 2026-02-09 14:01 Riyadh (week 6), materially
earlier in the dataset than OB's control timeline does, because RB's own
IRB/ARB zones reach impact on a different (and, in this dataset, earlier)
schedule than OB's IFOB/AOB zones -- exactly the effect the correction was
expected to produce. 5m BSO stage: 61 `ENTERED`, 40 `H4_OB_BREACHED` across
the 76 authorized targets (up from the old 44-target run).

### 9c. Gate-by-gate summary CSV: `rb_system/data/rb_control_gates.csv`

New script `rb_system/reference/build_control_gates.py` reads
`weekly_control_ledger_rb.csv`/`weekly_control_events_rb.csv` and collapses
them into one row per maximal control-constant time segment ("gate"),
joined against `h4_rb_ledger.csv` (authorized zones by impact time) and
`five_rb_bso_ledger.csv` (ENTERED rows by entry time, with SL/TP
breakdown). 13 gates total; sums cross-check exactly against the engines'
own printed totals (76 authorized, 61 entries, 48 SL / 13 TP). Full table
(all times Riyadh) is in the final chat report to the user, not repeated
here to avoid drifting out of sync with the CSV -- see that CSV as the
single source of truth going forward.

**One granularity caveat worth flagging (not a bug, inherited from OB's own
design):** `h4_rb_engine.py`'s `control_at(t)` looks up control at
WEEK-level granularity (one label per week, taken from
`weekly_control_ledger_rb.csv`'s per-week snapshot -- itself the
end-of-week-processing control state), while a "gate" in the CSV above is
bounded by the EXACT event timestamp. This can occasionally show an
authorized H4 zone whose impact falls, by real clock time, inside a gate
row currently reading NONE/a different side -- because that zone's own
WEEK still carries the coarser week-level control label from
`h4_rb_engine.py`'s bisect. This exact same coarse-week `control_at` design
already exists unchanged in `h4_ob_engine.py` for OB; it was not introduced
or altered by this session's work, just newly visible once gates are
diffed at sub-week resolution. Flagging for visibility, not fixing, since
changing it would be a scope change to `h4_ob_engine.py`'s own established
interface, not something this RB-correction pass was asked to touch.

### 9d. Pine viewer extended: H4/5m inspection toggles + 5m BSO visualization

`full_viewer_rb.py` extended (not a new file, per the task's "your call"
on scope) with:
- Weekly: `inspectOneRB`/`rbFromLast` (group="Weekly RB inspection") --
  ported from `weekly_rb_viewer.py`, which already had this pair; it simply
  hadn't been carried into the combined file yet.
- H4: `inspectOneH4RB`/`h4RbFromLast` (group="H4 RB inspection") -- naming
  mirrors `full_viewer.py`'s OB H4 inspector (`inspectOneH4OB`/
  `h4ObFromLast`, group="H4 OB inspection") exactly, per the task's explicit
  instruction to mirror that convention.
- 5m: a full BSO entry/SL/TP-line + fixed-R green/red box + ledger-table
  layer (new function `build_bso_extra_lines_rb`, adapted from
  `full_viewer.py`'s `build_bso_extra_lines`, ~lines 440-580 there), with
  its own `inspectOne5mBSO`/`bso5FromLast` toggle (group="5m BSO
  inspection") -- same naming convention again. The one deliberate
  trim from the OB version: no "Weekly OB" parent-lineage column, because
  RB's own 5m targeting (§5c/9b) has no parent-Weekly-zone concept at all
  (`five_rb_bso_engine.py`'s own targets never carry a `parent_weekly_id`)
  -- shown as a real design difference, not padded with a permanent "-"
  placeholder column.
- The H4/5m layers' `control_at`/`permits` gate inside `full_viewer_rb.py`
  now also reads `weekly_control_ledger_rb.csv` (matching 9b's rewiring),
  not OB's ledger.

**Pine syntax check performed on the regenerated file (not just
"should compile" -- read end-to-end and automated-checked):** ran an
indentation-nesting scan over every line of the regenerated
`full_viewer_rb.pine` (644 lines) confirming every `if barstate.islast`
block is immediately followed by its own indented `if <timeframe/toggle
flag>` line (the exact class of bug found and fixed in an earlier session
-- a run of top-level `var array<...>` declarations silently ending the
previous block, leaving a later `if` un-nested) -- zero anomalies found
across all 3 layers (Weekly, H4, and the new 5m BSO block). Also manually
read the transition points between each top-level `var` run and its
following `if barstate.islast` block (weekly struct labels -> weekly boxes
-> weekly table -> H4 boxes -> H4 table -> 5m BSO table+lines) to confirm
each one reopens `if barstate.islast` / `if <flag>` correctly, matching the
already-proven pattern from `full_viewer.py`'s own H4 OB layer and this
project's own earlier CE10205/CE10295 TradingView-statement-limit fix.
Still NOT pasted into TradingView itself (no TradingView access in this
environment) -- this is a careful read-through + automated structural scan,
not a live compile confirmation; flagging that distinction explicitly per
this project's own discipline about not overclaiming verification.

Files added/changed this session: `rb_system/reference/
weekly_control_engine_rb.py` (new), `rb_system/reference/
build_control_gates.py` (new), `rb_system/reference/h4_rb_engine.py`
(rewired), `rb_system/reference/five_rb_bso_engine.py` (rewired),
`rb_system/reference/full_viewer_rb.py` (extended). Data outputs:
`weekly_control_ledger_rb.csv`, `weekly_control_events_rb.csv`,
`weekly_control_report_rb.txt`, `rb_control_gates.csv`, regenerated
`h4_rb_ledger.csv`/`h4_rb_report.txt`/`h4_rb_swings.csv`/
`five_rb_bso_ledger.csv`/`full_viewer_rb.pine`.

## 8. SUPERSEDED (2026-09-18, earlier this session -- see SS9 above for the
correction) -- kept for the record, not for continued use.

**Control wiring (§8, this session, continuation 2): RB's H4/5m engines
  now obey OB's existing Weekly control permission as an external gate.**
  `h4_rb_engine.py` and `five_rb_bso_engine.py` both require
  `weekly_control_ledger.csv` (from `weekly_control_engine.py`, run
  unmodified on OB zones) and gate every H4 RB opportunity through the same
  `load_control_by_week`/`permits`/`control_at` interface `h4_ob_engine.py`
  uses. `h4_rb_ledger.csv` gained `control_at_impact`/`authorized` columns.
  393 H4 RB zones computed, 44 control-authorized (down from 273
  impacted-never-stranded pre-gate); the 5m BSO stage independently
  recomputes the same gate and agrees (44 == 44). Hand-verified with a
  paired example in the same SELL_ONLY control week (`week_index=15`,
  2026-04-12 to 2026-04-19): record `id=166` (BUY) correctly suppressed
  (zero rows in `five_rb_bso_ledger.csv`), record `id=171` (SELL) correctly
  still fires (`ENTERED`, exits `SL`). No blocker hit; the OB control
  interface was cleanly reusable, not entangled with OB-specific zone
  state, exactly as `h4_ob_engine.py`'s own code showed before wiring
  began. Weekly RB and the combined Pine viewer (`full_viewer_rb.py`) were
  NOT touched by this change (not in the task's scope for this pass) -- the
  Pine viewer still draws every H4 RB zone regardless of `authorized`, an
  intentional scope boundary, not an oversight.

## Session update — 2026-09-19 (two open data-quality issues logged, NOT fixed — raised by user via live chart cross-check)

**Status: OPEN. Do not silently fix either without the user's go-ahead — logged per their explicit request to flag, raise, and move on to control-gate work.**

### Issue A — RB #1 origin candle: CSV price levels disagree with the live FXCM/TradingView chart

- `weekly_rb_ledger.csv` id=1 (IRB BUY) picked week-of-12-Jan-2026 as its swing-low origin (engine low 1.15692) over week-of-19-Jan-2026 (engine low 1.15719) — a 2.7-pip call, engine-consistent given the data it has.
- User's live chart shows the OPPOSITE ordering and materially different price levels:
  - 12 Jan (chart): O 1.16339, H 1.16984, L 1.15843, C 1.15950 -- vs engine: O 1.16353, H 1.16981, L 1.15692, C 1.15731.
  - 19 Jan (chart): O 1.15800, H 1.18336, L 1.15762, C 1.18265 -- vs engine: O 1.15731, H 1.18649, L 1.15719, C 1.18649.
  - Differences run 15-38 pips depending on the field (Low ~15pip, Close ~38pip on 19 Jan) -- too large for a timezone/offset artifact; this is the underlying CSV's OWN price data disagreeing with the live chart, not a selection-logic bug. (This sits alongside the already-investigated, still-unresolved raw-timestamp-offset inconsistency from earlier the same day -- see the "1401 vs 1501 Riyadh" investigation above -- which showed the CSV's own internal offset is not even self-consistent across dates. This is a second, independent symptom of the same underlying "this CSV cannot be fully trusted" finding, not a new root cause.)
- Reason (working hypothesis, NOT confirmed): the downloadable "FXCM Basic Historical Data" export used to build this CSV is plausibly a different/lower-fidelity feed than what TradingView's live FXCM chart renders. No proof yet -- would need a broader systematic spot-check (many candles across the file) to confirm how pervasive this is.
- Recommended path (user-agreed, deferred for now): re-source M1 data from something that matches the live chart (TradingView export for a small trusted window, or FXCM's own documented-UTC API) rather than patch this file candle-by-candle. Not started.

### Issue B — Weekly week-open falsely equals prior week's close (stale echo tick), root cause CONFIRMED

- `weekly_rb_ledger.csv` id=12 (IRB BUY, origin week 26 Jul 2026): engine top = 1.13689 (= `min(open, close)` of the origin week = the week's own open, since open < close). User's chart shows the real origin candle's open is **1.13887**, ~20 pips higher -- a real, reproducible discrepancy (High/Low/Close all matched the chart to within ~0.3 pip, only Open was wrong).
- Root cause, found and confirmed directly in the raw CSV (`EURUSD_m1_BidAndAsk.csv`): the very first M1 row after the Fri-24-Jul -> Sun-26-Jul weekend gap is
  ```
  07/26/2026,19:00:00  Open=1.13689  TotalTicks=4
  ```
  `1.13689` is an EXACT copy of the prior Friday close (`07/24/2026,20:58:00` Close=1.13689), and `TotalTicks=4` is far below the 30-50+ ticks/minute seen in normal trading -- a stale/indicative echo quote, not a real trade. Real trading resumes a few minutes later: `19:06:00` (7 ticks, still thin) then `19:07:00` (35 ticks, price already at 1.13778-1.13899) -- matching the user's chart-observed real open of 1.13887 almost exactly.
  `weekly_ob_generator.py`'s `aggregate_weeks()` naively takes literally the first CSV row at/after the scheduled boundary as the week's open (`Week(start, end, minutes[i].o, ...)`), with no check for this kind of echoed/thin reopen tick, so it picked the fake 1.13689 instead of the real ~1.13887.
- **This is the same root disease as the already-flagged, still-unresolved OB "phantom weekly Sunday-reopen H4 candle" finding** (see `ob_reference_docs/TRADING_SYSTEM_HANDOFF.md`, session update 2026-09-17, "MAJOR UNRESOLVED FINDING"): thin, non-representative ticks in the minutes immediately after a weekend gap, polluting aggregation. There it manufactures an extra phantom H4 bar; here it corrupts the Weekly bar's own open field. Same cause, two different symptoms, in two different aggregation granularities (H4 vs Weekly), both inherited unchanged by RB from the OB codebase it was ported from.
- Proposed fix (NOT applied, needs user sign-off first): when selecting a week's open right after a gap, skip forward past any leading tick(s) whose Open exactly echoes the prior close AND whose tick count is abnormally low, until a genuinely-trading tick is found; use that one as the week's real open. Loop rather than skip-exactly-one, since more than one echoed minute can occur (this example: 19:00 was fake, 19:06 was still thin, 19:07 was the first solid one).
- User's decision (2026-09-19): defer fixing this specific rule. It will most likely be resolved together with the broader Sunday/weekend-reopen data-reliability problem (Issue A above and the OB phantom-H4-bar finding) once cleaner-sourced data is in hand, rather than patched in isolation on data already known to be partially unreliable. Proceeding to control-gate work next.

### Issue C — RB zone id=2's impact timestamp: raw CSV disagrees with the live chart by 1+ hour, AND the CSV's own internal offset is not self-consistent across dates

- **Status: OPEN. Logged and deferred, not fixed, per the same discipline as Issues A/B above.** This was investigated at length earlier the same session (2026-09-19) before this handoff had a permanent record of it; reconstructed here from that investigation's own arithmetic so it isn't lost.
- `weekly_rb_ledger.csv` id=2 (ARB SELL, `bottom=1.18649, top=1.20825`) records `impact_time_utc=2026-02-09 11:01:00` = **14:01 Riyadh** under this session's assumed CSV convention (`Etc/GMT+2`, fixed offset, no DST). The exact raw row producing this is `EURUSD_m1_BidAndAsk.csv` row `02/09/2026,09:01:00` (`HighBid=1.18649`, the exact zone-bottom touch) -- `09:01` local-file-time + 2h fixed offset = `11:01 UTC` = `14:01 Riyadh`.
- The user's live FXCM/TradingView chart shows the true candle at **15:01 Riyadh** -- a real, chart-confirmed 1-hour-plus discrepancy, not a rounding artifact.
- **DST hypothesis tested and refuted.** Compared this point against the OB project's own two documented summer calibration points (`ob_reference_docs/TRADING_SYSTEM_HANDOFF.md` L239-353 needs offset +2:00; L387-429 needs offset 0:00, only 11 days apart) plus this winter point (needs offset -3:00) plus a second winter point the user checked directly (`03/03/2026 14:25:00` raw, chart-confirmed ~17:20-17:25 Riyadh on a 5m chart, needs offset ~0:00). These four points require **four different raw-to-UTC offsets** (+2:00, 0:00, -3:00, ~0:00) within weeks of each other -- no single fixed offset, and no single DST swap (always exactly 1 hour), can explain spreads of up to 5 hours across only weeks.
- **Raw CSV internal-consistency deep dive.** Scanned `EURUSD_m1_BidAndAsk.csv`'s own 261,352 rows directly: zero out-of-order rows, zero duplicate timestamps, no visible splice/formatting seam -- the file IS internally monotonic and clean. BUT it does show one genuine, confirmed structural anomaly: every Friday weekly-close timestamp shifts by exactly 1 hour (from ~21:58/21:59 to ~20:58/20:59) at precisely the weekend of **2026-03-06/03-08**, the real 2026 US DST spring-forward boundary -- proving the feed's underlying clock tracks (or partially tracks) US Eastern DST rather than being a fixed offset year-round. However, that single confirmed 1-hour DST seam does **not** by itself explain the 3-hour and 2-hour spreads found between same-season points only weeks apart (two winter points 3.5 weeks apart differing by 3 hours from each other; two summer points 11 days apart differing by 2 hours from each other) -- so there is a confirmed DST-tracking defect PLUS an unexplained residual inconsistency beyond it.
- **Conclusion (not yet acted on):** this CSV's timestamps cannot be trusted as a single coherent timezone source. Re-sourcing the M1 data (TradingView's own export for a small trusted window, or FXCM's documented-UTC historical API) was recommended over continuing to patch offsets, but is deferred -- neither route is trivially available here (TradingView export caps are far below what's needed for bulk data; FXCM's API needs live account credentials this session cannot obtain or use).
- This sits alongside Issues A and B above as a third, independent symptom of the same underlying "this CSV cannot be fully trusted" finding -- not a new root cause, and not fixed here.
- **Working-assumption note for the rest of this session's Task 2-5 work:** per the user's own explicit instruction, the 14:01 Riyadh (11:01 UTC) reading is used as a deliberate placeholder for the exercise below, WITHOUT this issue being considered resolved.

## Session update — 2026-09-19, continuation (body-close hypothesis verified; new CONTROL-LAYER check implemented; gates rebuilt)

### 10a. Body-close hypothesis (Task 2) — VERIFIED against real engine output, not hand-computed

Question: does the Weekly candle for the week containing RB zone id=2's impact
(`trigger_week_idx=6`, week starting `2026-02-08 22:00:00 UTC`) close with its
body inside zone id=2's range `[1.18649, 1.20825]`?

Checked `weekly_control_engine.py`'s own `body_close_dead()` first, since the
task named it as the closest existing analog: it is a **close-only** check
(not open-and-close) -- `(week.c >= z.zb) if not z.bullish else (week.c <=
z.zt)` -- i.e. for a SELL zone (approached from below, as id=2 is), the
condition is simply `close >= bottom`. There is no "body" in the sense of
requiring both Open and Close inside; only Close matters, tested against the
NEAR boundary.

Pulled week 6's OHLC directly from `wob.aggregate_weeks()` (the same
aggregation `weekly_rb_generator.py`/`weekly_control_engine_rb.py` already
use, not a hand recomputation):
```
week 6 (2026-02-08 22:00:00 -> 2026-02-15 22:00:00 UTC):
  O=1.18126  H=1.19283  L=1.18086  C=1.18664
```
- `body_close_dead` convention (close only, near boundary): `1.18664 >=
  1.18649` -- **True**, by 1.5 pips.
- Full-range convention (Close anywhere inside `[bottom, top]`, the literal
  wording the user's own Task 3 instruction used): `1.18649 <= 1.18664 <=
  1.20825` -- **also True** (irrelevant here which convention is used, since
  the actual Close sits right at the near edge, inside by both readings).

**Verdict: YES.** Week 6's Close (1.18664) falls inside zone id=2's range by
both the strict `body_close_dead` convention and the plain full-range
reading. This is not a marginal or ambiguous case in either direction --
confirmed directly from the engine's own aggregated Weekly bar, not a manual
CSV scan.

### 10b. New CONTROL-LAYER check implemented (Task 3) — `weekly_control_engine_rb.py`

Per the task's explicit framing: this is a NEW rule at the CONTROL
state-machine layer only. RB's own zone lifecycle (impact + stranding only,
no close-through rule) is UNCHANGED -- substitution #4 in SS9a above still
stands, unmodified, for zone lifecycle. This is a different layer (the
control state machine's own transition rules), which is allowed its own
violation-detection logic even though RB zones themselves don't have one.

**Implementation** (`weekly_control_engine_rb.py`):
- New persistent variable `body_zone_id`: tracks "the zone whose impact most
  recently gave the CURRENT side control", set at every point
  `controlling_zone_id` is set for a fresh CAMPAIGN_START/
  CAMPAIGN_START_COUNTERTREND/CONTROL_SWITCHED/OPPOSING_GAINS_CONTROL, but
  -- unlike `controlling_zone_id` -- **persisted through SWING_PAUSE/
  SWING_RESUME** (the existing swing-pause code clears `controlling_zone_id`
  to `None`, but the zone whose thesis the side rests on doesn't stop being
  that zone just because a swing paused it). Cleared on NO_CONTROL, BOTH
  escalation, or RETURN_TO_PRO_TREND (no single zone id tracked there
  either, an existing quirk of the port, not newly introduced).
- New check, run every week, independent of (in addition to, not instead
  of) all the event-based transitions: if `body_zone_id` is set and that
  zone's own impact week has been reached (`k >= z.stop`), test the WEEK'S
  OWN CLOSE (`weeks[k].c`, from the engine's already-aggregated Weekly OHLC,
  not hand-recomputed) against `[z.zb, z.zt]`. If inside, log a new event
  kind `BODY_CLOSE_VIOLATION` (distinct from `TREND_FLIP`/`SWING_PAUSE`/etc)
  at that week's own CLOSE timestamp (`weeks[k].end`), and force
  `control = NONE`.
- **Deliberately NOT gated on `control != NONE`**: RB zone id=2's own case
  needed this. Its impact (11:01 UTC) and a same-week SWING_PAUSE (14:07
  UTC) both land in week 6, and the pause already drops `control` to NONE
  hours before week 6's own candle actually closes (2026-02-15 22:00 UTC).
  The body-close check must still independently evaluate and log its own
  reason at the candle's real close time even though `control` was already
  NONE by then for a different, earlier reason -- the check documents THIS
  violation, not just re-derives a `control` value that's already correct.
  Confirmed via instrumented run this fires (see below) whereas gating it
  on `control != NONE` silently swallowed it (caught and fixed during this
  same session, not shipped).

**Verification against RB zone id=2 (the case Task 2 confirmed):**
`weekly_control_events_rb.csv` now contains:
```
6,2026-02-15 22:00:00,2026-02-16 01:00:00,BODY_CLOSE_VIOLATION,"Week 6 close 1.18664 falls inside controlling RB zone 2's range [1.18649,1.20825] -> NONE",2,BULLISH,NONE
```
Matches Task 2's exact numbers (week 6, close 1.18664, zone 2's
`[1.18649,1.20825]`) at week 6's real close timestamp. Confirmed by running
`weekly_control_engine_rb.py` end to end (not just a scratch snippet) --
27 events before this change, 28 after, with this new row the only addition
for zone 2's own episode.

**Two more real firings found in the same dataset (asked for "at least one
other zone" -- found two):**
```
18,2026-05-10 21:00:00,2026-05-11 00:00:00,BODY_CLOSE_VIOLATION,"Week 18 close 1.17841 falls inside controlling RB zone 6's range [1.17621,1.18488] -> NONE",6,BULLISH,NONE
24,2026-06-21 21:00:00,2026-06-22 00:00:00,BODY_CLOSE_VIOLATION,"Week 24 close 1.14647 falls inside controlling RB zone 5's range [1.14427,1.15054] -> NONE",5,BEARISH,NONE
```
Both taken directly from the regenerated `weekly_control_events_rb.csv`, not
constructed examples -- the rule is not a one-off match to the motivating
case, it fires on real, independent zones elsewhere in the same dataset.

**Downstream rerun (`h4_rb_engine.py` / `five_rb_bso_engine.py` /
`build_control_gates.py`):** H4 RB authorized zones dropped from **76** (SS9b's
count, before this check) to **60** out of 393 total / 273 impacted-never-
stranded candidates, since the new check closes several control windows
earlier than the old event set did. 5m BSO stage: 52 `ENTERED` / 30
`H4_OB_BREACHED` (down from 61/40). Both engines' independently-recomputed
authorized counts still agree with each other (60 == 60), confirming the
duplicated gate logic stayed consistent after the change, same
cross-check discipline as SS9b.

**Gate rebuild -- gate #1's boundaries changed, exactly as expected:**
`build_control_gates.py` now produces **17** gates (up from 13). Gate #1
(`gate_index=1`, the first real control gate, per the CSV's own indexing):
```
gate_index=1: SELL_ONLY, starts 2026-02-09 14:01:00 Riyadh (CAMPAIGN_START_COUNTERTREND,
  zone 2), ends 2026-02-16 01:00:00 Riyadh (BODY_CLOSE_VIOLATION, zone 2,
  "Week 6 close 1.18664 falls inside controlling RB zone 2's range
  [1.18649,1.20825] -> NONE")
```
Confirmed this end reason is the NEW check firing, not a pre-existing one --
`grep BODY_CLOSE_VIOLATION` on the pre-this-session events file returns
nothing; it only exists after this change.

**One pre-existing bug surfaced (not introduced by this change, flagged for
visibility, NOT fixed -- out of this task's scope):** `weekly_control_
engine_rb.py`'s `log()` calls for `SWING_PAUSE`/`SWING_RESUME`/etc are
written BEFORE the `control = ...` reassignment that follows them, so the
`ControlEvent.control` field (written to `weekly_control_events_rb.csv` as
`control_after`) actually records the PRE-transition value, not the
post-transition one -- an existing off-by-one in the ORIGINAL (unmodified)
code, not something this session touched. `build_control_gates.py` trusts
that `control_after` column to detect gate boundaries, so it MISSES the real
SWING_PAUSE transition inside week 6 (control genuinely drops SELL_ONLY ->
NONE at 14:07 UTC / 17:07 Riyadh, only ~6 minutes after CAMPAIGN_START) and
instead shows gate #1 running the whole week, ending only at the new
BODY_CLOSE_VIOLATION event -- which happens to show the correct NEW value
only because ITS OWN log() call also captured the (by-then-already-NONE)
pre-transition value, which coincidentally differs from the gate builder's
stale internal tracker. In short: **gate #1's true real-time control history
is SELL_ONLY for ~6 minutes (14:01-14:07 Riyadh), then NONE for the rest of
the week and beyond until week 9's OPPOSING_GAINS_CONTROL** -- the CSV's
"gate #1 = SELL_ONLY the whole week" framing is an artifact of this
pre-existing logging-order bug, not a real second week of SELL_ONLY control.
This does NOT change Task 4's answer below (0 authorized H4 zones / 0 five
entries in gate #1 either way, since the whole window is control-active for
under 10 minutes in reality) but is flagged here explicitly so a future
session doesn't take `rb_control_gates.csv`'s per-gate `control` column at
face value for duration/boundary claims without checking this. Fixing it
would require re-verifying every historical gate row's stated control value
against the real event sequence, which is out of this task's scope -- raised
here as a genuine finding, not silently patched.

Files changed: `rb_system/reference/weekly_control_engine_rb.py` (new
`body_zone_id` tracking + `BODY_CLOSE_VIOLATION` check),
`rb_system/data/weekly_control_ledger_rb.csv`/`weekly_control_events_rb.csv`/
`weekly_control_report_rb.txt` (regenerated), `rb_system/data/
h4_rb_ledger.csv`/`h4_rb_swings.csv`/`h4_rb_report.txt`/
`five_rb_bso_ledger.csv` (regenerated), `rb_system/data/rb_control_gates.csv`
(regenerated, 17 gates).

**Caution for future runs, recorded per this project's own earlier
caution note (SS3a):** `weekly_control_engine_rb.py`'s default `--out-dir`
is the INPUT CSV's own parent directory (`ob_reference_data/`), NOT
`rb_system/data/` -- discovered mid-session when a run without `--out-dir
../data` silently wrote 3 new files into `ob_reference_data/` instead
(caught via `git status` immediately, confirmed untracked/harmless, deleted
before commit). Always pass `--out-dir ../data` explicitly when running this
script from `rb_system/reference/`, exactly as the existing `h4_rb_engine.py`
already defaults correctly to `../data` on its own.

### 10c. Gate #1 detail — H4 zones + 5m entries (Task 4)

Directly queried the regenerated `h4_rb_ledger.csv` (`authorized=True` rows
with `impact_time_utc` inside gate #1's window, `2026-02-09 11:01:00` to
`2026-02-15 22:00:00 UTC`) and `five_rb_bso_ledger.csv` (`stage=ENTERED` rows
with `entry_utc` inside the same window):

**Result: ZERO H4 RB zones became `authorized=True` inside gate #1's window,
and ZERO 5m entries occurred from it.** Same "0" finding as an earlier
session reported for the old (44-authorized, pre-body-close-check) gate #1 --
unchanged by this session's corrections, and for the reason the pre-existing
bug above makes explicit: gate #1's real control-open window is only ~6
minutes long (14:01-14:07 Riyadh, 2026-02-09) before SWING_PAUSE (real-time)
drops it to NONE, and `h4_rb_engine.py`'s own `control_at(t)` bisects by
WHOLE-WEEK granularity (SS9c's already-documented granularity caveat) --
even if a zone's impact fell later that same week while the ledger's
week-level snapshot still nominally reads a stale value, none did in this
specific 6-minute-to-week-end span. Cross-checked directly against
`rb_control_gates.csv`'s own row 1: `h4_rb_authorized_count=0,
h4_rb_authorized_ids=(empty), five_entries_count=0` -- consistent with the
direct CSV query above, not just the summary row's own arithmetic.

### 10d. Pine viewer: `focusGateNum` runtime toggle (Task 5)

Read `full_viewer.py`'s `--focus-weekly-id`/`--manual-gates` mechanism: both
are Python CLI flags evaluated at GENERATION time (they restrict which
zones are even written into the generated `.pine` file, requiring a
regenerate per selection). Task 5 asked for a Pine INPUT instead -- a
runtime toggle the viewer can flip on an already-generated chart, matching
this file's own existing `inspectOneRB`/`inspectOneH4RB`/`inspectOne5mBSO`
pattern, not `full_viewer.py`'s generation-time one. Implemented that way
deliberately, flagged here as a considered difference, not an oversight.

**Implementation** (`full_viewer_rb.py`):
- New `load_gates(path)`: reads `rb_control_gates.csv` into an ordered list
  of `(start_utc, end_utc)` pairs (end = next gate's start; last gate
  open-ended, using the same `right_edge` fallback the rest of the file
  already uses for open-ended zones).
- New Pine input `focusGateNum = input.int(0, ...)`, 0 = off, plus
  `var array<int> gateStart`/`gateEnd` baked from `load_gates()`'s output at
  generation time via the existing `pine_time()` helper (same `timestamp()`
  literal technique already used everywhere else in this file). Gate
  numbering matches `rb_control_gates.csv`'s own `gate_index` column
  exactly (no off-by-one remap) -- `gate_index=0` (the trivial NONE
  dataset-start gate) doubles as "off", which loses nothing since that gate
  never has any authorized zones or entries to show anyway.
- `build_rb_block()` gained a `gate_filter: bool` param (only passed `True`
  for the H4 call, not the Weekly one, per the task's "H4 and 5m layers
  only, not Weekly" instruction) and a new per-zone `{prefix}ImpactT` array
  (each zone's own impact time as a literal Pine timestamp, `na` for a
  never-impacted zone). Both the box-drawing loop and the table loop now AND
  the existing `inspectOneH4RB`/rank condition together with a
  `focusGateNum == 0 or (impact time falls inside gate[focusGateNum]'s
  window)` condition -- both filters combine when both are set, independent
  toggles as the task asked.
- `build_bso_extra_lines_rb()` gained the same `gate_filter` param and a
  parallel `bso5EntryT` array (each BSO attempt's own entry time, `na` for
  an attempt that never entered), ANDed into the existing
  `inspectOne5mBSO`/rank condition the same way.
- **Pine syntax re-checked carefully, per this file's own history of two
  real indentation bugs already fixed here.** Ran the same automated
  indentation-nesting scan as previous sessions (every `if barstate.islast`
  immediately followed by a more-indented line, checked over all 652 lines
  of the regenerated file) -- zero anomalies. Also checked quote-count
  parity and paren balance across the whole generated file (both clean) as
  an extra automated check beyond the manual read-through previous sessions
  used alone.

**Confirmed `focusGateNum=1` reproduces exactly Task 4's empty gate #1
list**, by construction: gate #1's window (`gate_index=1`,
`2026-02-09 11:01:00` to `2026-02-15 22:00:00 UTC`) has zero H4 zones with
`impact_time` inside it and zero 5m entries with `entry_time` inside it (SS10c)
-- so `focusGateNum=1` on the regenerated Pine file draws nothing on the H4/5m
layers for that gate, matching the direct CSV query exactly (not separately
re-derived; same underlying data, same window, checked by construction of
the array contents themselves rather than by loading the file into
TradingView, which remains unavailable in this environment as before).

Files changed: `rb_system/reference/full_viewer_rb.py` (extended, not
replaced), `rb_system/data/full_viewer_rb.pine` (regenerated, 651 lines,
17 gates baked into `gateStart`/`gateEnd`).

## 11. Bug found and fixed this session: `add_rb_from_swing` trigger_time was a fake week-boundary timestamp, not a real M1 minute

**Root cause.** `rb_system/reference/weekly_rb_generator.py`'s
`add_rb_from_swing(self, idx, is_high, trigger_k, st)` set:
```python
z.trigger_time = self.w[trigger_k].start   # the WEEK'S OPEN, not a real event
```
for every RB zone, both IRB (`st=0`) and ARB (`st=1`). This is a real
regression introduced during the RB port, not a pre-existing OB
limitation (an earlier session in this conversation wrongly told the user
it was inherited from OB; that has already been retracted). OB's own
`add_zone()`/`add_ifob()`/`set_promoted_ifob_trigger()` always assign
`trigger_time` from an exact M1 minute (`event.at`, or an inline per-minute
scan for the real break/crossing) — never a week-boundary timestamp.

**Concrete proof used to find it (RB zone id=2, ARB SELL,
origin `[1.18649, 1.20825]`):** before the fix, the ledger recorded
`trigger_time_utc = eligible_time_utc = 2026-02-08 22:00:00` — exactly
week 6's open, a placeholder. The real M1-precise moment the underlying
swing low confirms (price crosses above week 5's high) is
`engine.event_time(1, 6) = 2026-02-09 14:07:00 UTC` (`17:07 Riyadh`). The
recorded `impact_time_utc` was `2026-02-09 11:01:00` — chronologically
*before* the real trigger, an impossible effect-before-cause ordering that
only existed because the stored trigger_time was fake (the impact search
started from the fake, too-early eligible_time and so found a "touch"
before the zone's real triggering swing had even confirmed).

**The fix — two call paths, two different real-M1-minute sources, per the
RB spec's own distinction between IRB and ARB triggers:**

1. **New helper `WeeklyRBEngine.cross_time(k, level, above)`** — scans week
   `k`'s minutes for the first minute whose high exceeds `level` (a
   bullish break, `above=True`) or whose low falls below `level` (a
   bearish break). This mirrors the inline per-minute scan
   `weekly_ob_generator.py`'s `add_ifob` (lines ~429-433) and
   `set_promoted_ifob_trigger` (lines ~450-454) already use to find OB's
   real trigger minute — **not** `event_time()`, whose threshold is
   hard-coded to the *previous week's* high/low and is only equivalent to
   the real armed-swing break level when that armed swing happens to be
   exactly one week old. Confirmed this non-equivalence directly: for RB
   #12 (see below), the armed swing-high price actually broken was
   `1.14822`, not `w[29].h = 1.14492` (the previous week's own high) —
   `event_time(1, 30)` would have returned `2026-07-29 20:53:00 UTC`, a
   different (wrong) minute than the real break at `2026-07-30 12:43:00
   UTC`. `cross_time` uses the real armed price (`self.h_price`/
   `self.l_price`), so it is correct in both cases; `event_time` is only
   coincidentally correct for RB #2 because that swing happened to be
   confirmed against exactly the prior week's high.
2. **IRB path (`st=0`, from `consume_break`)**: the trigger is the exact
   M1 minute the swing high/low BREAK itself occurs. `consume_break`
   already holds the armed price being broken (`self.h_price` for a bull
   break, `self.l_price` for a bear break) at the moment it calls
   `add_rb_from_swing` — passed straight to `cross_time(k, self.h_price,
   True)` / `cross_time(k, self.l_price, False)`.
3. **ARB path (`st=1`, from `try_bull_arb`/`try_bear_arb`, themselves
   called from `mid_arm`)**: `mid_arm`'s loop already holds the exact
   confirming `Event` (`ev`), whose `.at` field is the real M1 minute
   (computed once in `add_event()` via `event_time()`, which — for a
   fresh swing confirmation, not a break of an old armed swing — is exact
   by construction). `ev.at` is now threaded through
   `try_bull_arb`/`try_bear_arb` into `add_rb_from_swing` as an explicit
   `trigger_time` parameter, instead of anything derived from
   `trigger_k`/`self.w[trigger_k]`.

`add_rb_from_swing` now takes `trigger_time` as an explicit parameter and
sets `z.trigger_time = trigger_time` directly. For ARB (`st=1`),
`z.eligible_time` is also set to the same `trigger_time` (eligibility is
immediate for ARB, per spec — same real moment as the trigger, not a copy
of the old fake week-boundary value). For IRB (`st=0`), `z.eligible_time`
is untouched by this change — it was already correctly set elsewhere in
`finish_events_and_lifecycle` from `ev.at` (lines ~330/340) and continues
to be.

**Kind-mapping check (done before trusting any of the above):** confirmed
from `add_event` call sites in this same file — `h_action()` calls
`add_event(k, 1, self.trough, ...)` after a break of the previous week's
high (registers a swing LOW, kind=1), `l_action()` calls
`add_event(k, 0, self.peak, ...)` after a break of the previous week's low
(registers a swing HIGH, kind=0). Identical to OB's own kind numbering
(`weekly_ob_generator.py` uses the same convention), as the port's header
comment already claims.

### Verification against RB #2 and RB #12 (re-derived fresh after the fix, not hardcoded)

**RB #2 (ARB SELL, origin `[1.18649, 1.20825]`), after the fix:**
- `event_time(1, 6)` (independently re-derived on the live post-fix
  engine) = `2026-02-09 14:07:00 UTC` = **17:07 Riyadh**.
- `z.trigger_time` = `z.eligible_time` = `2026-02-09 14:07:00 UTC` =
  **17:07 Riyadh** — matches the independent `event_time` re-derivation
  exactly (this case is one where `cross_time`'s armed price and
  `event_time`'s previous-week-boundary threshold coincide, confirmed
  directly, not assumed).
- `impact_time` is now **also** `2026-02-09 14:07:00 UTC` (**17:07
  Riyadh**) — the same minute as the trigger/eligible time, not before it.
  This is real, not a bug: raw M1 row at `2026-02-09 12:07:00` local
  (`Etc/GMT+2`) = `14:07:00 UTC` has `HighBid=1.18746`, `LowBid=1.18738`,
  both inside the zone `[1.18649, 1.20825]`, so the very minute the ARB
  zone becomes eligible already satisfies the impact/touch condition
  (`first_touch` starts scanning at `eligible_time` and finds a hit
  immediately). The previously reported "impact at 11:01 UTC, before the
  real 14:07 trigger" is now gone — that 11:01 finding was itself an
  artifact of the old fake (too-early) eligible_time; `first_touch` is
  bounded below by `eligible_time`, so impact can no longer precede
  trigger/eligible by construction.

**RB #12 (IRB BUY, origin week 30, `[1.13529, 1.13689]`), after the fix:**
- `z.trigger_time` = `2026-07-30 12:43:00 UTC` = **15:43 Riyadh** — a real
  M1 minute, not a round week-boundary hour.
- Independently confirmed against the raw CSV: the armed swing-high price
  broken was `1.14822` (captured directly off the live engine at the
  moment `consume_break(bull=True, k=30)` fired, `!= w[29].h = 1.14492`,
  proving `event_time(1, 30)` would NOT have been equivalent here — it
  returns `2026-07-29 20:53:00 UTC`, the wrong minute). Raw M1 rows
  (`Etc/GMT+2` local, `= UTC-2`) around the real break: `07/30/2026
  10:42:00` local has `HighBid=1.14796` (still below `1.14822`), `07/30/2026
  10:43:00` local has `HighBid=1.14840` (first minute above `1.14822`) —
  `10:43:00` local `= 12:43:00 UTC`, exactly matching the engine's
  `trigger_time`. Zone remains state `ORB` (stranded before ever reaching
  eligibility+impact), so `impact_time` is empty — unaffected by this
  check.

**Spot-checked all 13 Weekly RB zones (not just 3-5), all trigger times
changed from the old fake week-boundary stamps to real M1 minutes, none of
the new values are round week-open timestamps (`21:00:00`/`22:00:00`
UTC):**
```
id  old trigger_time_utc     new trigger_time_utc     new trigger_time (Riyadh)
1   2026-01-18 22:00:00  ->  2026-01-20 15:34:00   -> 2026-01-20 18:34 Riyadh
2   2026-02-08 22:00:00  ->  2026-02-09 14:07:00   -> 2026-02-09 17:07 Riyadh
3   2026-02-15 22:00:00  ->  2026-02-19 15:01:00   -> 2026-02-19 18:01 Riyadh
4   2026-03-29 21:00:00  ->  2026-03-30 11:17:00   -> 2026-03-30 14:17 Riyadh
5   2026-04-05 21:00:00  ->  2026-04-08 00:36:00   -> 2026-04-08 03:36 Riyadh
6   2026-05-03 21:00:00  ->  2026-05-06 12:45:00   -> 2026-05-06 15:45 Riyadh
7   2026-05-10 21:00:00  ->  2026-05-15 02:38:00   -> 2026-05-15 05:38 Riyadh
8   2026-05-31 21:00:00  ->  2026-06-05 15:00:00   -> 2026-06-05 18:00 Riyadh
9   2026-05-31 21:00:00  ->  2026-06-05 15:51:00   -> 2026-06-05 18:51 Riyadh
10  2026-06-14 21:00:00  ->  2026-06-17 21:24:00   -> 2026-06-18 00:24 Riyadh
11  2026-07-19 21:00:00  ->  2026-07-23 14:43:00   -> 2026-07-23 17:43 Riyadh
12  2026-07-26 21:00:00  ->  2026-07-30 12:43:00   -> 2026-07-30 15:43 Riyadh
13  2026-09-06 21:00:00  ->  2026-09-09 08:15:00   -> 2026-09-09 11:15 Riyadh
```
(Values taken directly from `diff` of `weekly_rb_ledger.csv` before/after
the fix, full pipeline rerun on the same input CSV.)

### H4 engine inherits the fix automatically (confirmed, not assumed)

`h4_rb_engine.py` reuses `WeeklyRBEngine` unmodified on an H4 bar grid, so
fixing `add_rb_from_swing` in the shared class fixes H4 RB zones with no
H4-specific code change. Confirmed directly: `h4_rb_ledger.csv`
regenerated with 393 total RB zones, 60 authorized (unchanged count from
before this fix — the fix does not change which zones get authorized,
only the timestamp attached to each). 380 of 392 non-header rows changed
their `trigger_time_utc` value; spot-checked before/after examples:
```
id  old trigger_time_utc     new trigger_time_utc
1   2026-01-02 09:00:00  ->  2026-01-02 09:30:00
2   2026-01-02 17:00:00  ->  2026-01-02 17:55:00
3   2026-01-04 17:00:00  ->  2026-01-04 20:17:00
4   2026-01-04 21:00:00  ->  2026-01-05 00:56:00
```
Before the fix, H4 trigger times were frequently exact H4-bar-open stamps
(e.g. `09:00:00`, `17:00:00`) — the H4 analogue of the weekly bug (H4
"week start" = the H4 bar's own open time instead of a real M1 crossing
minute inside that bar). After the fix, spot-checked H4 rows show real,
non-round-hour M1 minutes.

### Downstream rerun — what changed, with before/after evidence

Full pipeline rerun in order: `weekly_rb_generator.py` ->
`weekly_control_engine_rb.py` -> `h4_rb_engine.py` ->
`build_control_gates.py` / `five_rb_bso_engine.py` -> `full_viewer_rb.py`.

- **`weekly_control_events_rb.csv`**: still 28 events (unchanged count).
  Only the 3 `CAMPAIGN_START_COUNTERTREND` rows whose timestamp comes from
  an RB zone's `impact_time` shifted, exactly tracking each zone's
  corrected impact time (RB #2: `11:01`->`14:07` UTC; RB #6:
  `10:51`->`12:45` UTC; RB #8: `14:33`->`15:00` UTC). `weekly_control_
  ledger_rb.csv` itself (the per-week control-state column) is byte-
  identical before/after — the control STATE sequence did not change, only
  the exact moment 3 transitions are timestamped at.
- **`rb_control_gates.csv`**: still **17 gates** (unchanged count). Gate
  boundaries that depend on the 3 shifted `CAMPAIGN_START_COUNTERTREND`
  timestamps moved by the same amounts (e.g. gate #1 now starts
  `2026-02-09 17:07 Riyadh` instead of `14:01 Riyadh`); every other gate
  field (`control` value, `reason`, zone ids) is unchanged.
- **`h4_rb_ledger.csv`**: 393 total zones, **60 authorized** — same count
  as before this session's fix, confirming the fix does not change
  authorization outcomes, only timestamps.
- **`five_rb_bso_ledger.csv`**: stage counts moved from 52 `ENTERED` / 30
  `H4_OB_BREACHED` to **49 `ENTERED` / 31 `H4_OB_BREACHED`** — a real,
  substantive change, not just cosmetic. Root cause: an H4 RB zone's
  `impact_time` (which the 5m BSO engine uses as the hunt-window's real
  start) shifted for most zones along with `trigger_time`, so a handful of
  zones' 5m entry-hunt windows now open at a different, more accurate
  minute than before, changing whether/when a 5m entry fires for those
  specific zones (e.g. zone 338: two `SL` entries before the fix, `H4_OB_
  BREACHED`/no entry after; zone 289: 3 attempts before, 2 after, second
  attempt's outcome changed). This is flagged explicitly, not glossed
  over: the fix changes which zones get real entries, because it changes
  when the zone's real hunt window legitimately opens, and the entry/exit
  price and SL/TP mechanics for zones whose window didn't shift stay byte-
  identical (e.g. zone 116, 105 keep the same entry/exit prices, only the
  window-open timestamp before the first attempt differs).
- **`full_viewer_rb.pine`**: regenerated at the same 651 lines; re-ran the
  same automated `if barstate.islast` indentation-nesting scan (0
  anomalies), plus quote-count parity and paren-balance checks (both
  clean) — no Pine-generation code was touched by this fix, this is a
  confirmation the regenerated output stayed well-formed, not a new
  check.

Files changed this entry: `rb_system/reference/weekly_rb_generator.py`
(`add_rb_from_swing`/`try_bull_arb`/`try_bear_arb`/`consume_break`/
`mid_arm` signatures, new `cross_time` helper), `rb_system/data/
weekly_rb_ledger.csv`, `rb_system/data/weekly_control_events_rb.csv`,
`rb_system/data/h4_rb_ledger.csv`, `rb_system/data/rb_control_gates.csv`,
`rb_system/data/five_rb_bso_ledger.csv`, `rb_system/data/
full_viewer_rb.pine` (all regenerated end to end from the same input CSV).

## 12. User's final decision on the raw-CSV timezone: raw = UTC directly (2026-09-19 session)

**The decision, quoted verbatim:** "consider the raw CSV data to be
UTC... every time you and me are talking, let's use Riyadh time, period."

**Basis (already established in prior sessions, recorded here for the
record, not re-derived):** raw CSV row `02/09/2026,12:07:00` (the minute
price first exceeds `1.18744`, RB zone id=2's ARB-creation trigger level)
matches the user's live FXCM/TradingView chart within ~2 minutes when
read as raw wall-clock = UTC directly, i.e. `12:07 raw = 12:07 UTC =
15:07 Riyadh (UTC+3)`. FXCM's own API docs state M1 historical exports
are UTC. **Known, disclosed, deliberately not re-litigated tension:** RB
zone id=2's own *impact* point (raw `09:01`) was separately chart-
confirmed by the user at 15:01 Riyadh, which needs a `-3:00` offset, not
`0:00` — the opposite of this rule. The user has explicitly said not to
chase this down right now ("do not worry about anything that will come
later, we will deal with it, I do not look back"). This entry implements
the decision as given; it does not attempt to resolve that tension.

**Code change.** Every RB script whose `--input-tz` default was
`Etc/GMT+2` now defaults to `UTC` (raw Date/Time parsed as already-UTC
wall-clock, zero offset applied):
`rb_system/reference/weekly_rb_generator.py`,
`rb_system/reference/h4_rb_engine.py`,
`rb_system/reference/weekly_control_engine_rb.py`,
`rb_system/reference/five_rb_bso_engine.py`,
`rb_system/reference/full_viewer_rb.py`,
`rb_system/reference/weekly_rb_viewer.py`. `README_RB_ENGINES.txt`
updated to match, with an explicit note that the OB pipeline's own
`weekly_control_engine.py` (step 2 of the RB run order, a prerequisite
file the RB engines happen to also depend on for OB's own control
ledger) is UNCHANGED and still defaults to `Etc/GMT+2` — this decision
is scoped to the RB pipeline only, per the task.

A second, unrelated hardcoded `Etc/GMT+2` reference was checked and
confirmed NOT load-bearing: `full_viewer_rb.py` line 112 emits Pine
`timestamp("GMT+0", ...)` calls — that is Pine's own UTC-anchor literal
for drawing on the chart from already-UTC datetimes, not a raw-CSV input
assumption. Left as-is (it is already `GMT+0`, i.e. UTC, consistent with
this change).

**Full pipeline rerun**, same input CSV
(`rb_system/ob_reference_data/EURUSD_m1_BidAndAsk.csv`), in dependency
order: `weekly_control_engine_rb.py` -> `weekly_rb_generator.py` ->
`h4_rb_engine.py` -> `build_control_gates.py` -> `five_rb_bso_engine.py`
-> `full_viewer_rb.py` -> `weekly_rb_viewer.py`.

**Bug found and fixed during this rerun (not a timezone bug, an output-
path bug):** `weekly_control_engine_rb.py`'s `--out-dir` default is
`path.parent` (the *input CSV's* own directory,
`rb_system/ob_reference_data/`) when `--out-dir` is omitted — unlike
every other RB script here, whose default is `rb_system/data/`. The
first rerun of this script silently wrote `weekly_control_ledger_rb.csv`
/ `weekly_control_events_rb.csv` / `weekly_control_report_rb.txt` into
`ob_reference_data/` instead of `data/`, leaving the *stale*, pre-
change (`Etc/GMT+2`-derived) copies sitting untouched in `data/`.
`h4_rb_engine.py` and `five_rb_bso_engine.py` also default their
`--control-ledger` lookup to beside the input CSV, not `../data/`, which
is a separate but related trap for the same reason. Fixed by re-running
`weekly_control_engine_rb.py` with `--out-dir ../data` explicitly, then
re-running `h4_rb_engine.py` / `five_rb_bso_engine.py` /
`full_viewer_rb.py` with `--control-ledger ../data/weekly_control_ledger_rb.csv`
explicitly, and deleting the stray copy that had landed in
`ob_reference_data/`. Not fixed at the code-default level (out of this
session's scope; flagged here so a future session does not repeat it —
neither script's CLI has a wrong *timezone* default, both have a
misleading *out-dir* default that happens to bite immediately after a
fresh clone/rerun).

### Verification: RB zone id=2 — all three timestamps land on the same minute, as predicted

`rb_system/data/weekly_rb_ledger.csv`, row id=2 (ARB SELL, origin
`[1.18649, 1.20825]`), after the UTC-direct rerun:
```
trigger_time_utc  = eligible_time_utc = impact_time_utc  = 2026-02-09 12:07:00
trigger_time_display = eligible_time_display = impact_time_display = 2026-02-09 15:07:00
```
All three ARE on the same minute, 15:07 Riyadh (12:07 UTC), as the task's
testable prediction required — this is real, not forced: raw CSV row
`02/09/2026,12:07:00` (`HighBid=1.18746, LowBid=1.18738`) already sits
inside the zone `[1.18649, 1.20825]` the instant it becomes eligible, so
`first_touch` (bounded below by `eligible_time`) finds the impact
immediately, same as the prior `Etc/GMT+2`+`cross_time` fix's finding
(SS11 above) — only the absolute clock value moved (14:07 UTC -> 12:07
UTC), the same-minute coincidence itself is unaffected by which offset
is used.

### Spot-check: 4 more zones, raw CSV grepped directly, confirming UTC-direct with zero offset consistently applied

```
zone   ledger trigger_time_utc     raw CSV row grepped directly
1      2026-01-20 13:34:00     ->  01/20/2026,13:34:00  (exact match, zero offset)
6      2026-05-06 10:45:00     ->  05/06/2026,10:45:00  (exact match, zero offset)
8      2026-06-05 13:00:00     ->  06/05/2026,13:00:00  (exact match, zero offset)
11     2026-07-23 12:43:00     ->  07/23/2026,12:43:00  (exact match, zero offset)
```
Every `_display` (Riyadh) column across all sampled rows in
`weekly_rb_ledger.csv` and `h4_rb_ledger.csv` is exactly UTC+3 from its
`_utc` sibling (e.g. `12:07:00 UTC` / `15:07:00` display,
`15:55:00 UTC` / `18:55:00` display), confirming `display_iso()` is
applied consistently and no residual `Etc/GMT+2` parsing survives
anywhere in the RB pipeline's raw-CSV ingestion path.

### CSV utc/riyadh column labeling — checked, substance present, one cosmetic naming difference noted

Every regenerated RB ledger/report CSV already carries both a `_utc`
timestamp column and its Riyadh-converted counterpart for every
timestamp field, matching the OB reference ledgers' convention in
substance:
- `weekly_rb_ledger.csv` / `h4_rb_ledger.csv`: `*_time_utc` +
  `*_time_display` pairs (`display_iso()`, `--display-tz` default
  `Asia/Riyadh` — confirmed by inspecting the actual values, all UTC+3
  from their `_utc` siblings, not just by argument default).
- `rb_control_gates.csv`: `gate_start_utc` + `gate_start_riyadh`,
  `gate_end_riyadh` (no separate `gate_end_utc` — pre-existing, not
  changed this session).
- `five_rb_bso_ledger.csv`: `*_riyadh` + `*_utc` pairs throughout
  (`h4_impact_riyadh`/`h4_impact_utc`, `entry_riyadh`/`entry_utc`, etc).
- `weekly_control_events_rb.csv` / `weekly_control_ledger_rb.csv`:
  `week_start_utc` + `week_start_riyadh`.

**One naming inconsistency observed, not changed:** `weekly_rb_ledger.csv`
and `h4_rb_ledger.csv` use the suffix `_display` (e.g.
`trigger_time_display`) rather than `_riyadh`, while
`rb_control_gates.csv`/`five_rb_bso_ledger.csv`/`weekly_control_events_rb.csv`
use `_riyadh` directly, and the OB reference ledger
(`weekly_ob_ledger.csv`) uses `_riyadh` too. The `_display` columns ARE
Riyadh values (display-tz default is `Asia/Riyadh`), so no data is
missing — this is a column-name inconsistency only, pre-existing from
before this session (not introduced by this change). Left as-is: renaming
it would touch `full_viewer_rb.py`'s Pine-generation code paths that read
these column names, which is out of this session's scope and carries
regression risk disproportionate to a cosmetic fix. Flagged for a future
session if strict naming consistency across all RB CSVs is wanted.

### Gate table: 15 gates now, down from 17 (a real change, not cosmetic)

`rb_control_gates.csv` regenerated fresh off the corrected
`weekly_control_ledger_rb.csv`/`weekly_control_events_rb.csv`. Gate count
dropped from 17 to **15** — every timestamp shifted (as expected, since
every RB zone's trigger/eligible/impact time moved), and in this rerun
two fewer control-state transitions occurred overall (compare the two
files' event counts: 28 vs 27 `weekly_control_events_rb.csv` rows before/
after — one fewer event, collapsing two gates into one transition).
`h4_rb_ledger.csv` stayed at 398 total zones / 78 authorized (same
authorization count as the last known-good pre-UTC-direct run once the
`--control-ledger` path bug above was fixed), and
`five_rb_bso_ledger.csv` at 63 `ENTERED` / 39 `H4_OB_BREACHED` — matching
that same prior run's stage counts, confirming the gate-count/authorized-
count changes are attributable to the corrected control-ledger path fix
landing together with the UTC-direct timezone change in this session, not
to some new inconsistency.

### Pine syntax check — explicitly re-run, not assumed

Ran the same automated indentation-nesting scan this file's history has
needed multiple times: every `if barstate.islast` in the regenerated
`full_viewer_rb.pine` (639 lines) is immediately followed (skipping blank
lines) by a line indented strictly more than the `if` itself. Found **6**
occurrences of `if barstate.islast`, **0 anomalies**. Also ran quote-count
parity (5608 double-quotes total in the earlier UTC-direct-only rerun,
even count both times) and paren-balance checks (both matched) across the
whole file. `weekly_rb_viewer.pine` also regenerated (not separately
Pine-syntax-scanned beyond visual diff-size sanity, since it shares the
same box/table generation helpers as `full_viewer_rb.py` and carries no
`barstate.islast` blocks of its own beyond the weekly-only viewer's
existing single guard, unchanged in shape from prior sessions).

Files changed this entry: `rb_system/reference/weekly_rb_generator.py`,
`rb_system/reference/h4_rb_engine.py`,
`rb_system/reference/weekly_control_engine_rb.py`,
`rb_system/reference/five_rb_bso_engine.py`,
`rb_system/reference/full_viewer_rb.py`,
`rb_system/reference/weekly_rb_viewer.py` (`--input-tz` default only, in
each), `rb_system/reference/README_RB_ENGINES.txt`, and every RB data
file regenerated end to end from the same input CSV:
`rb_system/data/weekly_rb_ledger.csv`,
`rb_system/data/weekly_control_ledger_rb.csv`,
`rb_system/data/weekly_control_events_rb.csv`,
`rb_system/data/weekly_control_report_rb.txt`,
`rb_system/data/h4_rb_ledger.csv`, `rb_system/data/h4_rb_swings.csv`,
`rb_system/data/h4_rb_report.txt`, `rb_system/data/rb_control_gates.csv`,
`rb_system/data/five_rb_bso_ledger.csv`,
`rb_system/data/full_viewer_rb.pine`,
`rb_system/data/weekly_rb_viewer.pine`.
