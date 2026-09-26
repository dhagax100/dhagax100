# FVG Trading System Handoff — FXCM EURUSD, 2026 data

**Purpose:** parallel project to `docs/TRADING_SYSTEM_HANDOFF.md` and
`docs_rb/RB_HANDOFF.md`, same discipline: give this file to whoever
continues the work; it must continue from the current state, not redesign
or silently "fix" anything.

## 1. What this is

Same architecture as the OB/RB projects (`reference/` + `reference_rb/`),
same EURUSD 2026 1-minute CSV, same Weekly control-gate engine -- but for
FVG (Fair Value Gap) POIs instead of OB/RB. Only the zone-construction
rules differ.

FVG's construction rules come from `FVG_Indicator_v1.pine` (a standalone
TradingView diagnostic the user supplied, source of truth for the FVG-
specific rules -- confirmed with the user before porting). New code lives
in `reference_fvg/weekly_fvg_generator.py`; its own module docstring has
the full rule set (IFVG/AFVG construction, eligibility, stranding,
close-through) copied almost verbatim from that pine file's own logic.

## 2. Session update — 2026-09-26 (first deliverable: Weekly FVG engine)

**Built `reference_fvg/weekly_fvg_generator.py`.** Structure, mirroring
`weekly_rb_generator.py`'s own template:

- **Swing/MSS detection is copied verbatim from `weekly_ob_generator.py`'s
  `WeeklyOBEngine`** -- not reimplemented, not approximated. Verified
  directly: same swing highs/lows/MSS prices and origin weeks as OB's own
  `weekly_ob_swings.csv` (column layout differs -- this file uses RB's own
  already-fixed `confirm_utc`/`confirm_riyadh` split, a real bug OB's
  original format had, documented in `docs_rb/RB_RULES_LEARNED.md`).
- **FVG zone construction is a genuine 3-candle range scan** -- unlike RB
  (a single anchor candle's wick), every qualifying 3-week gap window in
  the relevant range becomes its own zone. IFVG created (a) at the same
  break-confirmation range OB's own `add_ifob`/RB's own IRB creation uses,
  and (b) continuously, one more week at a time, for as long as the
  current regime persists (the pine source's own "STEP 1b" -- genuinely
  new, no OB/RB analog). AFVG created at MID-ARM from the range an AOB/ARB
  is picked from, gated by a per-gap near-side straddle guard.

**Real bug found in the supplied pine source and NOT ported, per explicit
user direction ("we had wrong stranding rules in RB. I do not want that
mistake now"):** the pine's own stranding check branches by zone origin
(`isIfvgLike`), and its AFVG branch uses a swapped condition
(`bullish+HIGH below zb` / `bearish+LOW above zt`) -- the EXACT SAME
invented, wrong condition RB had before its 2026-09-24 fix. OB's real
stranding rule (checked directly in `weekly_ob_generator.py`) uses ONE
single condition for every zone type, no origin branching at all. Fixed
before ever shipping: `weekly_fvg_generator.py` uses OB's single unified
condition for both IFVG and AFVG from the start. Verified with 5 synthetic
unit tests (not just real-data silence, since 0 real AFVGs formed on this
dataset at Weekly granularity -- see below): confirmed the old/wrong
condition does NOT strand an AFVG zone, and the correct condition does.

**Genuinely new rule, accepted by the user before porting:**
close-through invalidation, IFVG only (origin 0, still state 0) -- if the
containing week's own close lands back through the gap's far edge once
eligible, the zone is immediately SPENT. Absent from both OB and RB.
Verified: fires for IFVG, correctly exempt for AFVG (tested synthetically
-- 0 real close-through events occurred in this particular dataset at
Weekly granularity, so real-data silence alone would not have proven this
worked).

**Verified so far (mechanical, not yet chart-confirmed by the user):**
- Ran clean against the full EURUSD 2026 CSV: 37 weeks, 10 swing highs,
  10 swing lows, 2 MSS-up, 2 MSS-down (all matching OB/RB exactly).
- 6 FVG zones created: 4 IFVG, 0 AFVG, 2 OFVG (stranded), 0 SPENT-by-name
  (matches OB/RB's own display convention -- a spent zone shows under its
  pre-spent type). 5 zones ended by IMPACT, 0 by CLOSE_THROUGH on this
  particular dataset (see 5 synthetic tests above for why this is
  believed correct despite zero real-data exercise of the rule).
- 0 AFVG zones is plausible, not necessarily a bug: a genuine 3-candle gap
  (one week's high/low entirely clear of another week's low/high) is a
  much rarer shape on WEEKLY bars than on the lower timeframes the pine
  source was designed for (5m/1h/4h/Daily) -- Weekly candles are wide and
  usually overlap. Confirmed directly: the AFVG reference-validity guard
  DID pass 6 times across the dataset, but no 3-week window happened to
  have the right gap shape when it did. Flag this for the user's own
  chart review, since it's a plausible-but-unconfirmed reading of thin
  data, not a proven-correct one.
- Pine output (`weekly_fvg_viewer.pine`) is array-packed from the start
  (same CE10295/CE10205/CE10123 avoidance discipline as every other layer
  in this project).
- **Not yet chart-verified against the real TradingView chart.** No FVG
  zone's exact box position, type, or lifecycle has been checked against
  a chart screenshot yet -- this is the immediate next step before
  trusting any of the 6 zones above, same discipline OB and RB both
  required from their own first Weekly deliverable onward.

## 3. Run order (current)

```
cd reference_fvg
python3 weekly_fvg_generator.py <path-to-EURUSD_m1_BidAndAsk.csv>
```

Produces, next to the CSV:
- `weekly_fvg_ledger.csv` -- one row per FVG zone, full audit trail
  (left-candle week, trigger/eligible/impact timestamps, type, side, box
  coordinates, and `stop_reason`: IMPACT or CLOSE_THROUGH)
- `weekly_fvg_swings.csv` -- swing/MSS facts (identical facts to
  `weekly_ob_swings.csv`/`weekly_rb_swings.csv` on the same input)
- `weekly_fvg_viewer.pine` -- paste into TradingView Pine Editor, attach to
  EURUSD/FXCM Weekly chart
- `weekly_fvg_report.txt` -- coverage, lifecycle counts, spent-reason
  breakdown

## 4. Session update — 2026-09-26 (STRUCTURAL_BREACH added; trigger-timestamp precision fix)

**Fourth death cause added, per explicit user direction:** a POI stops
being used the instant its supporting swing point is exceeded, in real
time, full stop -- independent of eligibility, independent of stranding's
own formal-confirmation timing. Mirrors `five_bso_engine.py`'s own
`structural_invalid_at()` "swing_break" concept (already used for OB/RB's
H4-layer trade invalidation), applied here directly at the Weekly zone's
own lifecycle for the first time -- OB/RB's own Weekly zones never had
this. Each zone snapshots its own `protect_level` (a LOW for a bullish
zone, a HIGH for a bearish one -- whichever was the latest confirmed swing
of that kind at creation). Verified with 2 new synthetic tests. Full
dataset re-run: same 6 zones, same counts -- 0 real STRUCTURAL_BREACH
events this dataset, flagged as unconfirmed by real data same as AFVG=0
and CLOSE_THROUGH=0 already were.

**Real correction to close-through's own definition, mid-session:** the
first version required only that the close reach the NEAR edge (matching
OB/RB's own "body close" convention) -- user corrected this: FVG's
close-through must reach the FAR edge (fully past the whole zone, not
merely into it), confirmed directly against `five_bso_engine.py`'s own
existing comment ("every POI except FVG invalidates on a body close
either inside its zone or through it") -- FVG was already flagged there as
the deliberate exception, before this session ever touched it. The reason
this specific (strict) form is correct for FVG and not for OB/RB: FVG's
own plain wick-impact rule already kills a zone the instant ANY wick
touches it, so "the body closes fully inside the zone" is geometrically
impossible to observe without impact having already fired first. The only
case close-through can still catch is a full bypass -- price closing
completely past the zone without ever wicking into it -- which requires
the far-edge threshold, not the near-edge one.

**Trigger-timestamp precision fix:** the continuous-scan IFVG creation
path (no break or swing event to time against) fell back to the
week's scheduled open -- inconsistent with the project's "always pin to
an exact minute" discipline used everywhere else. Fixed: `week_extreme_time()`
finds the exact minute the completing week's own low/high actually
printed, same technique `event_time()`/`high_first()` already use.

## 5. Session update — 2026-09-26 (12-gate control history derived; H4+5m layers built)

**Full control-gate history derived via a genuine minute-by-minute walk**
with the user (not a first-guess table): 12 gates, 2026-01-02 (leading
NONE) through 2026-09-11 22:05 (end of data, trailing NONE). See
`docs_fvg/FVG_RULES_LEARNED.md` for the full gate table and the two real
corrections found along the way:

1. **Anchor break must use the controlling zone's supporting swing point
   (`protect_level`), not its own box edge.** A wick merely touching the
   zone's own zb/zt isn't a real violation -- it's just price revisiting
   it. Mechanically copied from RB's control-engine convention at first
   (RB checks the zone's own box), which is actually fine for RB only
   because RB's box edge IS its supporting swing's price by construction
   (RB zones are built directly from a swing-pivot candle's wick). FVG's
   box comes from a 3-candle gap, unrelated to any swing extreme -- so the
   same shortcut is wrong for FVG specifically. Not an RB bug; a
   consequence of FVG's different construction rule forcing a distinction
   RB never had to make.
2. **A swing-pause resume must be CANCELLED if an MSS against the paused
   side confirms before the matching resume-swing** -- the underlying
   trend itself broke, not just the pause; there's nothing left to resume
   to. This may be a real, so-far-undetected gap in RB's own shipped
   control engine too (flagged as a genuine follow-up item, not yet
   checked).

**New: `reference_fvg/full_fvg_viewer.py`** -- combined Weekly+H4+5m FVG
viewer, mirroring `full_rb_viewer.py`'s structure exactly. Reuses
`h4_ob_engine`/`five_bso_engine`/`full_viewer` unchanged. Two real RB
mistakes deliberately avoided from the start: the H4 swing/MSS window is
scoped to the real gates span (not the trailing open-ended NONE's end),
and the gate table itself already carries both corrections above, not a
first-guess table needing a later fix.

**Result:** 221 H4 FVGs computed, 30 authorized, 50 5m entries (46
ENTERED, 4 H4_FVG_BREACHED). Each layer (Weekly/H4/5m) has its own
separate table and its own "inspect one" toggle.

## 6. Session update — 2026-09-26 (2026 dataset closed out -- with real caveats vs OB/RB)

**Full entry history, all 46 entries, start to finish:**
- 11 wins (TP, +3.00R each), 35 losses (SL, -1.00R each). Win rate 23.9%.
- **Net: -2.00R** over the full dataset (2026-02-02 16:03 through 09-11
  22:05 end of data).
- Side split: 42 SELL, 4 BUY -- heavily one-sided (BUY control windows
  were mostly short pauses/BOTH resolutions; SELL ran the long stretches).

**Terminal state at end of data:** control = NONE, SELL parent = Zone #5,
BUY parent = Zone #3, Zone #6 (BUY) never became a parent at all (died by
stranding before ever being impacted).

**Follow-up analysis done this session** (see `docs_fvg/FVG_RULES_LEARNED.md`
for the numbers): kill-zone entry-time analysis (London/NY), the "2nd
entry of a 3+-attempt POI" filter (0% win rate, -12R across all three
systems combined -- a real, actionable finding), a plain breakeven-at-1R
rule (simulated properly, net NEGATIVE -8R -- rejected), a breakeven-at-2R
rule on the kill-zone+filtered subset (net +1R -- worth keeping), and a
first-pass cross-POI control-gate reconciliation (OB and RB directly
conflict in direction for 22 of 150 shared days, always OB=SELL vs
RB=BUY, never the reverse).

**Honest gaps versus OB/RB's own closeouts -- do not claim more than this
is:**
1. **Not yet chart-verified against the real TradingView chart at all** --
   neither the 6 Weekly zones, nor the 30 authorized H4 zones, nor any of
   the 46 entries have been checked against a real chart screenshot. OB
   and RB both required this before being trusted; FVG has not had it yet.
2. **No automated control-gate engine exists for FVG** (RB has
   `weekly_rb_control_engine.py`, independently validated against its own
   34-gate table). FVG's 12-gate table is hand-derived only, with no
   second, independent derivation to cross-check it against.
3. **The two control-gate corrections above (protect_level anchor-break,
   MSS-cancelled resume) have not been checked against RB's own control
   engine**, which may carry the identical gaps -- flagged, not yet acted
   on.

**How to close out this FVG/dataset and hand off cleanly:**
1. Nothing needs to be "closed" in code -- no open position, no armed
   zone, no pending FVG at the end of the CSV. The engine's own state at
   the last processed minute already IS the terminal state.
2. When new data is appended, rerun the full pipeline
   (`weekly_fvg_generator.py` -> `full_fvg_viewer.py`) end-to-end, since
   the engines are stateless recomputations over the whole file. Chart-
   verification and an automated control-engine cross-check are still
   owed on the EXISTING 2026-01-02 -> 09-11 span before extending it --
   don't treat this span as "already locked" the way OB/RB's own spans
   are, since it hasn't had the same verification depth yet.
3. This file and `docs_fvg/FVG_RULES_LEARNED.md` are the continuity
   record.
