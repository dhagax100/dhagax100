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

## 4. Next concrete step

Chart-verify the 6 Weekly FVG zones above (box position, type
IFVG/AFVG/OFVG, side, and especially the 2 OFVG zones' stranding cause and
the 5 IMPACT-ended zones) against the real TradingView chart -- the same
candle-by-candle discipline the OB and RB projects both used from their
own first Weekly deliverable onward. Do not proceed to H4/5m until this
passes. Also worth a specific look: whether 0 AFVG zones over this
dataset genuinely matches the chart, or whether the range/guard logic
needs a second look once real chart examples are in hand.
