# Dhagax Dailies — Hand-off (2026-10-08)

You are picking up a running project. Read this file fully, then read
`DAILIES_LEARNING_LOG.txt` in full, before doing anything. Do not ask the
user what the assignment is — it's in this file and the log. Do not ask
for clarification on anything either document already answers. Do not
invent a mechanism, a number, or a rule and present it as settled — if
it isn't in the log or confirmed against real 1-minute data, it's a
guess, and guesses have caused real, costly regressions in this project
before (see the log's own "swing_spent" and "item #10 first attempt"
stories).

## What this is

A real ICT-style trading system for EURUSD, built from real 1-minute
market data (2021-2026), not simulated. Python generates Daily/4H/1H/5m
Order Block (OB), Rejection Block (RB), Fair Value Gap (FVG) and Volume
Imbalance (VI) zones, tracks which side ("CONTROL") is actively
tradeable at any moment (Daily-only — 4H/1H never drive control, they
only consume it), and finds real 5-minute entries against that. The
year under full test throughout is 2025.

## Files that matter

- **`DAILIES_LEARNING_LOG.txt`** — the rule book and full session
  history, newest first in the `SESSION LOG` section. Long, precise,
  corrected multiple times — later entries supersede earlier ones on
  the same topic. Read it in full, not skimmed.
- **`DAILIES_DAYBYDAY_REPORT.txt`** — the current locked full-year
  day-by-day report (Date/Bias/Setups/Entries, 4 columns). Bias is
  restricted to BUY/SELL/BOTH/NONE labels only (with transition times
  and short reasons in brackets); short zone codes (OB/RB/FVG), "origin"
  not "formed", R-multiple inline with SL/TP, no POI ID numbers in the
  Entries column. This exact style is locked — match it precisely if
  you regenerate any part of it.
- **`reference_daily/all_tf_combined_generator.py`** — the live engine.
  All CONTROL logic, 1H/4H gating, 5-minute entry matching live here.
- **`reference_daily/verify_day.py`** — the tool for checking any single
  day fast (~45-60s via `build_engines(csv_path, date_str, lead_months)`
  + `report_day(ctx, date_str)`), not the ~18-20 min full generator.
- **`reference_combined/weekly_combined_generator.py`** — zone-creation
  engine (OB/RB/FVG/VI eligibility, structure, MSS). Read this when a bug
  traces into zone *creation* rather than CONTROL logic.
- **Data** — the three tracked year-range CSVs under `data/` merge into
  one continuous file. The merged file itself is gitignored (too large,
  ~190MB) — rebuild it locally with the exact command in the
  `.gitignore` comment above its ignore line, or:
  ```
  (head -1 data/EURUSD_m1_BidAndAsk_2021-01-03_to_2022-12-30.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2021-01-03_to_2022-12-30.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2023-01-02_to_2024-12-31.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2025-01-02_to_2026-09-30.csv) \
    > data/EURUSD_m1_BidAndAsk_2021-01-03_to_2026-09-30.csv
  ```
  Do NOT use a plain `cat` — the source files have different header
  styles and each carries its own header row.

## Current state (commit history: `a551db5` → `d2310d1` → `32d0a56`,
branch `ict-trading-system`)

A 27-item consolidated fix list was worked through this session (full
detail and evidence for every one is in the log's two most recent
2026-10-07 session entries, plus a 2026-10-08 entry for what's below).
Status, exactly as of this hand-off:

**Committed, verified, stable (items 1-6, 11, 11b, 12, 22, 25):**
SL-anchor real-extreme fix, BOTH-state proactive-flip fix, weekend-
checkpoint report-scan fix, week-close boundary fix, stillborn-trend
proactive-flip fix, the same-minute swing_break bisect fix (item 12 —
explains items 14's original two cited trades and item 15 too), the
10-day month-end trailing pad (item 22), prior-4H-candle tracking
(item 11, data-collection note, verified null on this dataset), the
pre-entry prior-candle disqualifier (item 11b, verified correct via
unit test, also a verified null result on this dataset), and the
instant-stop note (item 25, 2-pip threshold, also a null result —
smallest real SL anywhere in 2025 is 2.8 pips).

**Coded but DISABLED, unresolved — item 10 (premium/discount-region
mechanism for pre-session-impacted POIs):** `ITEM10_ENABLED = False` in
`all_tf_combined_generator.py` right now. Two different implementations
of this have been built and tested against the SAME 19 known real 2025
zones whose impact genuinely precedes that day's trading window:
1. First attempt (2026-10-07): armed an entry the instant any swing
   confirmed after price stopped extending, with no real "wait" at all
   — confirmed WRONG by the user, since it produced early/chasing
   entries, the opposite of the intended design.
2. Second attempt (2026-10-08): required price to retrace to the
   midpoint of [extreme, next swing] before arming — coded correctly,
   verified via debug trace to genuinely compute and check that
   midpoint, but proven to change ZERO of the 6 known real-outcome-
   changing cases, because in every one, the confirming swing already
   satisfies that midpoint the instant it confirms. A real, verified
   null result, not a bug.
3. Third attempt, SAME SESSION, user's own redesign (2026-10-08): gate
   directly on the resulting SL SIZE instead of a retracement proxy —
   only arm a candidate if `abs(extreme_since_impact - candidate_price)`
   is <= `PREMIUM_MAX_SL_PIPS` (15.0, the user's own figure, open to
   change), re-validated continuously as the extreme ratchets. This is
   the CURRENT code in `run_5m_bso_premium()`. Checked against the same
   6 known cases: EVERY one already has a natural SL under 15 pips
   (2.9-13.6 pips), so the cap still changes nothing on this specific
   known test set — not because it's wrong, but because no known
   example yet proves it right either.

**OPEN QUESTION, not yet resolved — do this next if the user asks you
to continue item 10:** of the 19 known pre-session-impacted 2025 zones,
13 "reproduce" the plain baseline's own result exactly (just with
different, often earlier, entry timing) — these have NOT been
individually checked for whether any of them carries a genuinely
oversized SL under the OLD, disabled mechanism, vs. whether item 10's
current SL-cap logic would have excluded them. Finding even ONE real
case where the cap changes an outcome (removes an oversized-SL trade,
or produces a materially different entry) would validate the design;
finding none across all 19 means the premise (a real oversized-SL
pre-session case exists in 2025 data) may simply not hold this year,
and the user should decide whether to keep the mechanism dormant,
lower the pip cap, or drop the feature. **Do not re-enable
`ITEM10_ENABLED` without the user's explicit go-ahead on this
specific question** — they were mid-investigation when this hand-off
was written and have not yet decided.

**Designed, specified, NOT yet coded — item 14 (RB aggressive-zone
eligibility guard):** a real, confirmed asymmetry — OB's Aggressive-
zone eligibility code requires the confirming swing to clear the zone's
own boundary (or it's rejected outright); RB's equivalent code has no
such guard. The exact fix (mirroring OB's `ok = ...` check into RB's two
eligibility blocks in `reference_combined/weekly_combined_generator.py`,
~lines 981-985 bullish / ~1014-1018 bearish) was fully designed and
explained to the user in this session's chat, confirmed safe (can only
ever REMOVE already-granted RB eligibility in the narrow case OB already
filters, never grant new eligibility), but the user said "let's run it"
and then the task was interrupted before any code was written. **This
is ready to implement exactly as designed** — see the log's final
session entry for the precise before/after code block.

**Explicitly deferred/put-aside by the user, do not touch without being
asked:** items 13, 19, 20, 21, 23, 26, 27. Each has its own real
evidence and status already recorded in the log — do not re-raise them
proactively, and do not guess at a fix for any of them.

## Standing rules (apply to you too — tested hard, held every time)

- **Never commit or push without the user explicitly saying so in that
  exact turn.** A general "go ahead" earlier in the conversation does
  not carry forward.
- **Never guess and present it as fact.** Investigate with real data or
  ask. This project has a real, costly history of exactly this failure
  mode (see the log's "swing_spent" story and item #10's first two
  attempts above) — always verify before claiming something is fixed.
- **Before claiming a bug is fixed, re-verify the full previously-
  validated range, not just the one case that exposed it.**
- **A fix only counts as validated once you've found a REAL case where
  it changes the right thing** — a fix that's merely "coded correctly"
  but never shown to change a known bad outcome (see item 10's history
  above) should be reported exactly that honestly, not oversold.
- CONTROL is Daily-only. 4H/1H never drive it, only consume it.

## Your task right now

The user is migrating to a new AI session to continue this work because
of a usage limit, not because the work is finished. They want this
hand-off to let a fresh AI reproduce the SAME full-year 2025 backtest
and answer status questions (what's fixed, what's pending, what's put
aside, what are entry notes, what is 1H abandonment, etc.) correctly
from this file and the log — the user will verify your first fresh
backtest's numbers privately against their own saved copy before trusting
anything further, so compute them for real, don't guess or recall a
number from this file (no result numbers are given here on purpose).

Do not ask the user "what would you like me to do with this hand-off"
— this file is the answer. Start by: (1) reading this file and the
full learning log, (2) rebuilding the merged CSV if needed, (3) running
a fresh full-year 2025 verification using `reference_daily/verify_day.py`
(one engine build per month, every calendar day looped, 10-day trailing
pad past month-end, matching the pattern described throughout the log's
2026-10-07 session entries) with the CURRENT code exactly as committed
(item 10 disabled, everything else active), and reporting the resulting
trade count / TP / SL / net R and max losing streak back to the user.
Then ask the user which of item 10 (the open question above) or item 14
(ready to code) they want you to continue with.
