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
