# Dhagax Dailies — Optimization & Tuning Log

This is the permanent record of every edge-tuning idea, optimization candidate,
and system-improvement note the user raises. Every item gets logged here
first, before anything is coded. Nothing in this file is implemented yet
unless its status says so.

**Status values** (per item, update as work progresses):
- `logged` — recorded here, not yet investigated
- `data-collection` — actively gathering evidence (e.g. running a parallel
  non-decision-affecting comparison across history) before deciding
- `coded` — implemented in the engine, not yet verified against known cases
- `tested` — verified against specific known/real cases
- `confirmed` — proven to change results in the expected direction, or
  proven inconclusive/no-effect (either way, the open question is answered)
- `committed` — in a git commit
- `pushed` — on GitHub
- `deferred` — explicitly set aside by the user for a later stage (not
  abandoned, just sequenced after other work)

Every new tuning note the user raises, at any point, gets appended here as
the next numbered item — this file is never replaced, only grown.

---

## 1. 1H trading the opposing zone — impact-day-only restriction

**Idea:** Even when CONTROL grants full opposing-POI access (BOTH state, both
4H and 1H allowed to trade the opposing side), the user believes 1H is a weak
timeframe for this specific case and should ONLY be allowed to trade the
opposing zone on the zone's actual impact day — not on any later day the zone
remains valid.

**Relation to other notes:** Tied to the setup-grouping/categorization
optimization work (the 6-category 1H-A/B/C / 4H-A/B/C taxonomy discussed
earlier this project). Sequencing TBD — may land inside that grouping work,
or be tested standalone first.

**Status:** logged

---

## 2. Structural notes as an optimization signal

**Idea A — "wrong-side extreme before entry":** A trade taken off 1H or 4H
where price, before we even entered, took out the swing point on the
*opposite* side of the premium/discount mark from our trade direction — e.g.
for a SELL trade, price took the *swing low* before we entered. This already
exists as a structural note in current output; the ask is to mine it as an
optimization filter (exclude/flag trades carrying this note).

**Idea B — "prior candle's high/low taken post-entry":** Narrower signal —
after entry, price takes the *previous candle's* high or low. Worth
investigating but lower priority than Idea A.

**Status:** logged

---

## 3. News-based trade management

**Idea:** Three separate behaviors needed:
1. Some news events: do not trade AT ALL the day they release.
2. Some news events: trade freely before and after, but never place a new
   entry in the release window itself.
3. For trades already open going into a news release: active management
   rules (not just "don't enter new ones").

**Status:** logged — needs a news-event calendar/classification source
before this can be coded.

---

## 4. Body close in the 4H/1H POI after entry

**Idea:** After we've entered a trade off a 4H or 1H POI, a body close back
inside that same POI (post-entry) is believed to be a significant
optimization signal — likely an early-warning / management rule.

**Status:** logged

---

## 5. "1-pip-or-less overshoot then straight to SL" pattern

**Idea:** Some trades trigger (price exceeds the entry point) by 1 pip or
less, then go directly to SL with no favorable excursion. Identifying this
pattern early (or filtering it out) could save a meaningful number of losses.

**Status:** logged

---

## 6. Fake swing points from missing tick data

**Idea/Problem:** Confirmed engine limitation — OHLC-only 1-minute data
cannot determine which side (high or low) was touched first within a single
candle. Certain single candles with large bidirectional range create FALSE
swing points as a result, because the engine must pick an assumed order.
This is flagged as needing an **immediate** fix, not a later-stage one.

**Status:** logged — flagged URGENT by user (distinct from the other
later-stage items)

---

## 7. 24-hour trading except news hours

**Idea:** Question whether restricting to specific session windows is even
necessary — what if the system just traded all 24 hours, with the only
exclusion being news hours? Proposed as a late-stage experiment, not a
near-term priority.

**Status:** deferred (explicitly "later stages")

---

## 8. RR-based optimization (BE rules)

**Idea:** Confirmed finding from earlier study: a 2.5R breakeven-move rule
saves some losses (recalled study: 0 winners cut, 5 losers saved vs. no BE
rule). General category: more RR-threshold-based management rules to test.

**Status:** confirmed (2.5R BE finding specifically, from the earlier
Group 1/2/3 study) — not yet coded into the live engine as a standing rule

---

## 9. 1H abandonment rule effects (PDH/PDL handover)

**Idea:** Study the effect of the 1H abandonment rule — both the PDH/PDL
wick-chain mechanism and the handover to the impacted POI. User explicitly
connects this to Note 1 (impact-day-only opposing 1H trades): sequencing is
**Note 1 first**, collect data, THEN investigate free 1H trading in whichever
direction currently controls.

**Status:** logged — sequenced after Note 1

---

## 10. 1H "quick eligibility" via next-candle return (pre-formal-eligibility trading)

**Idea:** In the user's prior manual trading: once a 1H bearish POI (OB or
RB — not FVG, which needs 3 candles to form and therefore effectively always
has eligibility already satisfied by the time it could be impacted) is
triggered/created at swing-low exceedance, the formal eligibility rule
requires taking out the prior 1H candle's high first. But the user used to
trade it if the VERY NEXT candle after the trigger candle came straight back
into the zone — treating that as equivalent to a confirmed impact, with all
the same violation rules applying afterward.

**Ask:** Collect data three ways for 1H and 4H:
(a) without eligibility checked at all,
(b) with the "next-candle return" quick-eligibility rule,
(c) with the current formal eligibility rule (what the engine does today).

**Status:** logged

---

## 11. Re-examine item 10 or 14 (pre-session >15 pip impact) — which design wins

**Idea:** The user is unsure which prior fix item (10 or 14 — confirmed this
session: it was **item 10**) addressed "price impacts the 4H/1H setup before
trading hours and moves more than 15 pips, causing entry in a bad spot." The
engine's existing safeguard (always choosing the extreme swing after impact
for SL placement) already prevents an exposed/mid-air SL. The open question:
**which is actually the better-performing choice** —
(a) enter at trading-hour start regardless of resulting SL size, or
(b) require price to retrace to a premium/discount mark before entering
(the SL-cap mechanism currently implemented as item 10, v3: arms a candidate
only while its SL stays ≤ 15 pips).

**Status:** `data-collection` / open question — item 10 (the SL-cap
mechanism) is coded, committed, and pushed as of 2026-10-08, but PROVEN (via
direct testing against the 6 known 2025 cases) to produce zero difference
from the plain trading-hour-start approach on every case checked so far,
because all 6 already had natural SL sizes under the 15-pip cap. No case
has yet been found where the two approaches actually diverge — this
question remains genuinely unresolved pending the 2025/2026 full-year
backtest now in progress, which may surface a real divergent case.

---

## 12. Multiple trades off the same POI (same session/hour/day) — clustering risk

**Idea:** Taking multiple trades from the same POI within the same session,
hour, or day needs careful study — the user's observation is that most
losing trades come in **consecutive clusters**, suggesting a
correlation/clustering risk that a simple "one trade per POI" or cooldown
rule might fix.

**Status:** logged

---

## 13. Re-entry after TP from the same POI

**Idea:** Whether to allow a new trade from the same POI after it has
already hit TP once. Explicitly lower priority.

**Status:** deferred ("will wait for later stages")

---

## 14. Trade duration / time-in-trade optimization

**Idea:** Record the time-in-trade (entry to exit) for every trade, win or
loss, to find the optimal maximum holding period. Specific concern: trades
that remain open overnight into a session with an OPPOSING control state.
Use the existing entry/SL/TP timestamp fields already in the per-trade
ledger to compute this.

**Status:** logged — the underlying data (entry/exit timestamps) already
exists in the comprehensive per-trade CSV; this is purely an analysis task,
no new engine logic needed.

---

## 15. BE-on-opposing-setup-impact during BOTH-control

**Idea:** When CONTROL is in a BOTH state (both sides tradeable) and we are
already in a trade on one side, should we move to breakeven as soon as price
hits a setup for the OTHER side (i.e., the market is now showing interest in
the opposite direction)? Open question: should this apply always in BOTH
state, or only specifically when we are in the trade AGAINST the prevailing
trend and price hits a setup FOR the trend-aligned side?

**Status:** logged

---

## 16. "1H candle opens inside POI = dead zone" rule — re-examine for OB specifically

**Idea:** Current rule: if a 1H candle opens inside a POI, that POI is
considered dead/invalidated. User's observation: this has looked wrong many
times, specifically for **1H Order Blocks** (not necessarily RBs). Ask:
collect data for BOTH 1H OBs and 1H RBs under this "open-inside-POI" rule,
expecting OBs specifically to show good results if the rule is relaxed or
removed for them.

**Status:** logged

---

## 17. GBPUSD co-trading, SMT, and integration

**Idea — three parts:**
(a) **Co-backtest:** trade GBPUSD alongside EURUSD, entering both trades
when both set up, and study the combined results.
(b) **SMT (Smart Money Technique) divergence:** use GBPUSD's liquidity
grabs as a confirmation/trigger for EURUSD trades — e.g. do NOT take a
EURUSD sell off an Asian-session high sweep in London unless GBPUSD also
swept its own Asian high (divergence/confirmation logic).
(c) **Integration/exclusivity:** when both pairs offer a qualifying setup at
the same time, take only the FIRST one that actually triggers an entry —
never hold two simultaneous open trades across the pair.

**Status:** logged — large scope item, likely its own project phase

---

## 18. Last-30-minutes-of-4H / last-15-minutes-of-1H entry window exclusion

**Idea:** Trades entered very late in a 4H or 1H candle's life (observed:
roughly the last 5 minutes of a 4H candle) tend to be losers, and specifically
tend to close back inside the POI zone (a technical violation) — but only
AFTER we'd already been stopped out, so the violation doesn't help us, it
just confirms we were taken out right before the zone would have been voided
anyway. Proposed optimization: exclude entries triggered inside the last
~30 minutes of a 4H candle, or the last ~15 minutes of a 1H candle.

**Status:** logged

---

## 19. Remove the session liquidity grab rule entirely

**Idea:** Test what happens if the session liquidity sweep requirement is
removed altogether from the entry conditions. Explicitly a later-stage
experiment.

**Status:** deferred ("dealt with later in time")

---

## 20. Hourly performance filter

**Idea:** Measure the performance of each individual trading hour
(presumably Riyadh-time entry hour, matching the existing `entry_hour_riyadh`
field already in the per-trade CSV) and drop/filter out the
consistently-losing hours. Directly builds on the earlier Group
1/2/3-style entry-hour study (recalled finding: NY last hour = 0% win rate
across 21 trades).

**Status:** logged — the underlying data (`entry_hour_riyadh`) already
exists in the comprehensive per-trade CSV; this is primarily an analysis
task once enough years of data exist.

---

## Appendix: sequencing notes from the user

- Note 1 (1H impact-day-only opposing trades) should be investigated before
  Note 9 (1H abandonment rule effects), per explicit instruction.
- Notes 7, 13, 17 (partially), and 19 are explicitly deferred to later
  stages, not near-term.
- Note 6 (fake swing points from missing tick data) is flagged as needing
  IMMEDIATE attention — distinct priority from everything else in this file.
- Notes 14 and 20 need no new engine code — they're pure analysis tasks
  once the comprehensive per-trade CSV exists across enough years (the
  2025/2026, then eventually 2011-2024, backtest currently in progress).
