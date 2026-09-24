# RB Control-Gate Rules — Learned Log

Running record of what the control-gate walkthrough has actually taught,
gate by gate, through 2026. This is NOT the dev handoff doc
(`RB_HANDOFF.md` — code changes, bugs, run commands). This file is the
knowledge base: confirmed rules, carried-over OB rules, and RB-specific
rules, so later gates can be checked against everything learned so far
instead of re-deriving it each time.

Format per gate: **claim → verification method → confirmed rule(s)**.
Rules inherited from OB unchanged are marked `[OB]`. Rules that are new,
or that apply differently in RB, are marked `[RB-NEW]` or `[RB-DIFF]`.

---

## Real bug caught by the user from a chart replay (2026-09-20)

Gate 2's end / gate 3's start was first encoded at the week-of-02-16's
own close (2026-02-23 01:00 Riyadh), using a structural
close-below-prior-week's-low fact as the trigger. **This was wrong.**
User clarified the actual rule: **MSS does not require a close — a
1-pip wick exceedance of the protecting swing point is enough, real-time,
on whatever timeframe it happens** (mid-week, mid-day, mid-hour). The
swing protecting gate 2's BUY leg is AIRB #3's own anchor low (1.17652);
the first real M1 wick below it is **2026-02-19 16:01 Riyadh** (low
1.17645), 4 days before the week's own close. Under the wrong boundary,
a real H4 RB (#91) got authorized BUY on 2026-02-20 18:12 Riyadh — a
live trading mistake, caught by the user replaying the chart, since the
real-time MSS-down had already confirmed the day before. Fixed: gate
2/3's boundary moved to 2026-02-19 16:01 Riyadh; H4 RB #91 now correctly
shows `authorized=False`.

`[RB-NEW]` **MSS confirmation rule, corrected**: real-time wick
exceedance of a protecting swing point (even 1 pip), not a close, not
delayed to any candle's own close on any timeframe. This generalizes
the earlier "gates react in real time" finding (from the 1.16162 vs
14:06 stop-event check) into an explicit, reusable rule: any future gate
boundary describable as "trend flips" or "MSS" must be checked for the
first wick (not close) breach of the relevant protecting swing, not a
candle-close event on any timeframe.

## Real bug caught by the user questioning a swing-confirm timestamp (2026-09-24)

Asked whether a swing high was confirmed at 2026-03-30 12:17 Riyadh; I first
said no, reading `weekly_rb_swings.csv`'s `confirm_riyadh` column, which
showed 2026-03-30 00:00 (week-open) for that swing. User correctly pushed
back: that column was never the real confirmation minute -- it's just the
containing week's scheduled boundary. Checked `write_ledger()` in
`weekly_rb_generator.py`: it wrote `engine.w[e.confirm].start` (a SWING's
confirm week label) and `engine.w[x.at].start` (an MSS's break week label)
instead of the engine's own stored exact-minute facts. Re-ran the engine
directly and confirmed the real minute for that swing high (1.16394) is
2026-03-30 12:17 -- exactly the RB #5/#6 trigger minute already logged
above, and independently reproduces the MSS_DOWN gate-2/3 boundary
(2026-02-19 16:01) already hand-verified for the real bug entry below.

`[RB-NEW]` **Fixed**: `weekly_rb_swings.csv`'s `confirm_utc`/`confirm_riyadh`
now use the SWING `Event.at` (already an exact 1m timestamp, just never
exported) directly, and the MSS row now computes its exact break minute via
`engine.break_time(x.at, x.up, x.price)` (same helper the RB trigger-timing
code already uses) instead of printing the week's own open time. `origin_*`
columns are untouched -- those correctly label which week's candle the
pivot itself sits on, a week-level fact, not a confirmation-timing one.

Note: `reference/weekly_ob_generator.py`'s own `weekly_ob_swings.csv`
export (OB project, lines ~810-813) has the identical defect, unfixed --
flagged, not touched, since that engine is marked locked/complete.

## Real bug caught by the user from the H4 table (2026-09-23)

H4 RB #143 (SELL, gate 5, 2026-03-23) showed `Parent W: -` (blank). User
clarified: the parent shown for a control gate with no anchor-impact zone
should never be blank -- it's **the last RB zone on the current bias side**,
whether or not that zone has itself been impacted yet. "If RB2 was the last
selling RB, then in this 4h sell that RB2 is in charge." Checked
`weekly_rb_ledger.csv`: by 2026-02-19 16:01 Riyadh (gate 3's start), zone #4
(Weekly ORB, SELL, zb=1.18722/zt=1.19283) had just been confirmed at that
exact same MSS-down minute -- the newest SELL zone in existence, superseding
RB2 (dead since gate 1). No newer SELL zone is born until zone #6 (origin
week 2026-03-23, after gate 5 ends), so zone #4 stays the sell parent
through gates 3, 4 (sell side), and 5.

`[RB-NEW]` **Parent-in-charge rule**: a control gate's displayed parent is
the most recently created RB zone sharing that gate's bias direction, not
necessarily the zone whose impact/MSS event opened the gate. An "anchor
zone" gate (one triggered by a specific zone's impact, e.g. gate 1/RB2 or
gate 4's BUY/RB1) still uses that triggering zone directly; a "no anchor"
gate (triggered by a structural/MSS event with no zone impact, e.g. gates
3/5) must look up the last same-direction zone instead of leaving the
parent blank.

## Carried over from OB (assumed true until RB data contradicts it)

- `[OB]` **Weekly-close body-breach kills a POI.** If the containing
  week's own close is inside or through the zone (`close >= zb` for a
  bearish zone measured against its bottom, mirrored for bullish), the
  zone dies at that week's close. SPEC.md SS14. — Confirmed still true
  for RB via gate 1 (zone #2 dies at 2026-02-16 close, 1.18722 >= zb
  1.18609).
- `[OB]` **Trend and control are independent.** A COUNTERTREND gate
  (trend up, gate SELL_ONLY or vice versa) is not itself invalid —
  SPEC.md SS9. — Confirmed still true for RB via gate 1 (trend up per
  2025 carryover, gate is SELL_ONLY on a bearish ARB).
- `[OB]` Control gates are checked two ways: (1) **event-level** — swing
  point creation, POI reaction, MSS; (2) **candle-close behavior** —
  especially close behavior around candles that sit inside a POI. Both
  checks are required per gate, not just one.

## RB-specific rules confirmed so far

- `[RB-NEW]` RB zone = the **wick** of a single known swing-pivot candle
  (never scanned/picked from a range, unlike OB's zone selection).
- `[RB-NEW]` IRB mirrors IFOB (delayed eligibility, arms on next
  same-direction swing); ARB mirrors AOB (immediate eligibility,
  `eligible_time = trigger_time` at creation); AIRB mirrors AIFOB
  (speculative at mid-arm, promotable in place to IRB on a real break).
- `[RB-NEW]` Bull/bear label follows the **raw wick type** (swing-high
  wick always bearish, swing-low wick always bullish), independent of
  which hunt direction created the zone.
- `[RB-DIFF]` Lifecycle stranding rule is simpler than OB: **wick impact
  + stranding only, no close-through rule** for RB zone death by touch —
  separate from the Weekly-close body-breach rule above, which still
  applies the same way it does in OB.

---

## Gate 1 — 2026-02-09 15:07 Riyadh → 2026-02-16 01:00 Riyadh (SELL_ONLY)

**Claim (user-supplied):** RB zone #2 (Weekly, ARB, bearish,
top=1.20825, bottom=1.18609) is the first RB ever impacted. Trigger,
eligible, and impact are the same minute (2026-02-09 15:07 Riyadh).
Trend was UP (2025 carryover, not derivable from 2026-only data) →
countertrend SELL_ONLY start. Zone dies at its own containing week's
close (2026-02-16 01:00 Riyadh close = 1.18722, inside the zone).

**Verification:** all three sub-claims checked directly against
`weekly_rb_ledger.csv` and the week's own OHLC before any code was
written — all confirmed true.

**Result:** gate 1 = SELL_ONLY, 2026-02-09 15:07 → 2026-02-16 01:00
Riyadh, then NONE. Within this window: 5 H4 RBs authorized (post-DST-fix;
was 6 pre-fix), all SELL, all parent zone #2. 8 total 5m entry attempts
(post-fix; was 10 pre-fix): 5 ENTERED, 3 H4_RB_BREACHED.

**Not yet chart-verified** against the real TradingView chart with the
corrected (post-DST-fix) numbers — pending.

---

## Gates 2-5 — 2026-02-16 01:00 Riyadh → 2026-03-23 14:06 Riyadh

**Claim (user-supplied), verified sub-claim by sub-claim against the real
ledger/swing/M1 data before any code was written:**

- **Gate 2, BUY_ONLY** (2026-02-16 → 02-23 Riyadh, parent zone #3 AIRB):
  RB2 dead → control reverts to the underlying UP trend at week open.
  Zone #3 (AIRB, BUY, zb=1.17652/zt=1.18095) impacted mid-week
  (2026-02-17 18:28 Riyadh) without ending BUY_ONLY — confirmed an AIRB
  touch alone does not flip control.
- **Gate 3, SELL_ONLY, no anchor zone** (2026-02-23 → 03-03 17:24 Riyadh):
  A **new** rule, distinct from gate 1's Weekly-close-body-breach rule —
  **structural break-of-structure**: the week-of-2026-02-16's own close
  (1.17921) is below the *prior* week's low (1.18086, week-of-02-09).
  Confirmed directly. Read as AIRB #3 failing + trend flip; no live SELL
  RB exists to anchor the campaign (RB2 already dead), so SELL_ONLY here
  has no parent zone.
- **Gate 4, BOTH** (2026-03-03 17:24 → 17:26 Riyadh, only 2 minutes):
  RB1 (W ORB #1, BUY, zb=1.15692/zt=1.15797) impacted 2026-03-03 17:24
  Riyadh, opening BOTH.
- **Gate 5, SELL_ONLY, no anchor zone** (resumes 2026-03-03 17:26 Riyadh):
  2 minutes after RB1's impact, price breaks below RB1's own anchor low
  (1.15692, confirmed swing week-of-2026-01-19) — low 1.15667 at
  2026-03-03 17:26 Riyadh. Confirmed near-immediate.
- **Stop, 2026-03-23 14:06 Riyadh**: user initially cited price 1.16162,
  but direct data check showed price had already exceeded the prior
  week's high (1.16159, week-of-03-16) earlier that same day, at 14:06
  Riyadh (high 1.1619) — **user confirmed 14:06/1.1619 is correct**, not
  the later 1.16162 print, and not the engine's own formally-confirmed
  SWING HIGH (which lags to 1.16394, week-of-03-30).

**`[RB-NEW]` Real, important rule difference confirmed here**: the
control-gate "stop" trigger uses the **first real-time tick that exceeds
the prior week's high/low** — NOT the engine's formal, delayed
two-sided-confirmed SWING event. This is the "event vs. candle reaction"
distinction the user set up from the start; gates react in real time,
the Weekly RB zone engine's own SWING/MSS detection is deliberately
slower/confirmed. Any future gate-boundary claim citing a "swing"
must be checked against BOTH definitions before encoding, since they
can disagree by up to a week and a meaningfully different price.

**Result**: `build_manual_rb_gates()` in `full_rb_viewer.py` now encodes
gates 1-5, then NONE from 2026-03-23 14:06 Riyadh onward (next gate not
yet given). 25 H4 RBs authorized across the known window (up from gate
1's 5): 5 BUY (gate 2, parent #3), 20 SELL (5 parent #2 from gate 1, 15
parentless from gates 3/5). Cross-checked every authorized row's side
against its own control_at_impact column — zero mismatches. 29 total 5m
entries (14 ENTERED, 15 H4_RB_BREACHED).

## Open questions / not yet tested by real gate data

- Does RB ever need its own countertrend/trend-alignment nuance beyond
  the OB SS9 rule, or does it inherit it exactly?
- Does AIRB promotion-in-place ever interact with a control gate boundary
  (e.g. promoted mid-gate vs. promoted after a gate closes)?
- Whether RB's simpler "wick impact + stranding only" lifecycle ever
  produces a gate-relevant case OB's close-through rule would have
  caught (or vice versa) — no case has surfaced yet.
