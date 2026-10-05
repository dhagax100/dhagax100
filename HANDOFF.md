# Dhagax Dailies — Hand-off

You are picking up a running project. Read this file fully before doing
anything. It tells you what the system is, where the rules live, how to
run it, and what you're expected to do next. Do not ask the user what
the assignment is — it's in this file. Do not ask for clarification on
anything this file or `DAILIES_LEARNING_LOG.txt` already answers.

## What this is

A real ICT-style trading system for EURUSD, built from real 1-minute
market data, not simulated or invented. Python generates Daily/4H/1H/5m
Order Block (OB), Rejection Block (RB), Fair Value Gap (FVG) and Volume
Imbalance (VI) zones, tracks which side ("CONTROL") is actively
tradeable at any moment, and finds real 5-minute entries against that.
The same code also emits a merged Pine Script v6 TradingView indicator,
but the day-by-day verification work (what you're being asked to
continue) is done directly against the Python output, not the chart.

**Everything here is derived from real price data and the user's own
direct teaching, verified repeatedly against raw 1-minute candles and
the user's own chart reading. Nothing is simulated, assumed, or
invented. If you are ever unsure whether something is a rule or a
guess, it must come from `DAILIES_LEARNING_LOG.txt` or be verified
against real data before you treat it as fact — never invent a
mechanism and present it as settled.**

## Files that matter

- `DAILIES_LEARNING_LOG.txt` — the rule book. Every concept the user has
  taught, every bug found and fixed, with dates and the user's own
  words quoted verbatim wherever possible. **Read this in full before
  doing any day's verification.** It is long because the rules are
  precise and have been corrected multiple times — later entries
  supersede earlier ones on the same topic; the `SESSION LOG` section
  (newest first) is the running history of how each rule was arrived
  at, including false starts that were caught and reverted. The `DAY
  REPORTING FORMAT — LOCKED` section near the top is the exact,
  mandatory format for every day's report — do not deviate from it.
- `DAILIES_TRADING_JOURNAL.txt` — the day-by-day journal of what
  actually happened, trade by trade, for every day already verified.
  Newest entries at the top. This is a record of completed work, not a
  spoiler to shortcut new work — January is already verified and
  closed; your job starts at the next unverified month.
- `reference_daily/all_tf_combined_generator.py` — the live generator.
  All CONTROL logic, 1H/4H gating, 5-minute entry matching, and the
  Pine output all live here. This is the file you'll most often be
  reading and, when a real bug is found, editing.
- `reference_daily/verify_day.py` — **the tool you run for every single
  day.** Fast-hybrid single-day verification (~45-60s instead of an
  ~18-20 minute full run) that still goes through the exact same code
  paths as the full generator — not an approximation. Usage:
  ```
  python3 reference_daily/verify_day.py 2025-02-03
  ```
  Add `--lead-months N` (default 2) if a month needs more lead-in for
  structure continuity. Never re-run the full multi-year generator just
  to check one day — this script exists specifically so you don't have
  to.
- `reference_combined/weekly_combined_generator.py`,
  `reference_daily/daily_combined_generator.py`,
  `reference/weekly_ob_generator.py`,
  `reference_rb/weekly_rb_generator.py`,
  `reference_fvg/weekly_fvg_generator.py`,
  `reference_vi/weekly_vi_generator.py` — the engine layers
  `all_tf_combined_generator.py` is built on (zone detection, swing
  structure, MSS, the OB/RB/FVG/VI mechanics themselves). You'll read
  these when a bug traces down into zone *creation* rather than CONTROL
  logic (this has happened — see the `guard_price` boundary bug in the
  learning log for a worked example of tracing a reporting discrepancy
  all the way down into a 3-candle gap condition).
- `data/EURUSD_m1_BidAndAsk_2021-01-03_to_2026-09-30.csv` — the real
  merged multi-year 1-minute price data (gitignored, rebuild locally if
  missing). Every result in this project traces back to this file;
  there is no other source of truth. **Do not use a plain `cat`** — the
  three source files have different header styles (quoted vs.
  unquoted) and each carries its own header row, so a naive `cat` puts
  two extra header rows in the middle of the data. Use this exact
  command instead (verified byte-identical to the tracked file):
  ```
  (head -1 data/EURUSD_m1_BidAndAsk_2021-01-03_to_2022-12-30.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2021-01-03_to_2022-12-30.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2023-01-02_to_2024-12-31.csv
   tail -n +2 data/EURUSD_m1_BidAndAsk_2025-01-02_to_2026-09-30.csv) \
    > data/EURUSD_m1_BidAndAsk_2021-01-03_to_2026-09-30.csv
  ```

## The locked day-report format

Every day you report MUST use this exact 4-column table (full spec and
worked examples in `DAILIES_LEARNING_LOG.txt`'s `DAY REPORTING FORMAT`
section):

| Control window | Setups allowed | POI of interest | Entry info |

Strict rules, non-negotiable:
- Never report the side that isn't currently allowed, not even as "it
  was rejected."
- Never state a non-event ("1H not abandoned") unless something
  actually changed.
- Only list a POI if its side AND its specific resource (4H or 1H) are
  BOTH actually live that moment — otherwise drop it entirely, don't
  mention it.
- Never report anything outside the real trading window
  (`atc.trading_window()` — 11:00-19:00 Riyadh summer / 11:00-20:00
  winter, real NY DST transition dates, not a fixed guess).
- Always name the exact timeframe + side ("1H sell"), never "a POI."
- BUY's own check is "discount," SELL's is "premium" — never swap these.

## How to work a day

1. Run `python3 reference_daily/verify_day.py <date>`.
2. Read its full output: candidates, any ENTERED attempt's full detail,
   the control checkpoint timeline for that day (with reasons), and the
   1H abandonment ceiling for both sides.
3. Translate that into the locked table format. If control changes
   mid-window, give one row per control segment.
4. If a trade entered, give full entry detail (price, SL, TP, result,
   exit time) in the Entry info column.
5. If something in the output looks structurally wrong (a zone you'd
   expect to see doesn't appear, a control transition doesn't match
   what the real price action should produce), investigate it the way
   the learning log's own worked examples do: trace it down to the
   actual code and real candle data, don't guess and don't paper over
   it. Several real bugs this project has had were found exactly this
   way — by someone (the user or a prior AI) noticing a report didn't
   match what the real chart showed, and refusing to accept "the code
   says so" as an explanation on its own.
6. Log the day in `DAILIES_TRADING_JOURNAL.txt` (new entry at the TOP,
   same format as the existing entries — short, plain, no fluff).
7. If you find and fix a real bug: write it into
   `DAILIES_LEARNING_LOG.txt`'s `SESSION LOG` (newest entry at the top)
   AND into whichever conceptual section of the file it belongs to, the
   same way every prior fix is documented there — what was wrong,
   real evidence (exact zone IDs, exact prices, exact times), what the
   fix was, and that you re-verified nothing else regressed. This log
   is the only thing standing between "settled" and "re-litigated for
   the tenth time" — treat it as load-bearing, not optional paperwork.

## Standing rules (apply to you too)

- **Never commit or push without the user explicitly saying so in that
  exact turn.** A general "go ahead" earlier in the conversation does
  not carry forward. This was tested hard earlier in this project's
  history and the rule held every single time — do not be the one who
  breaks it.
- **Never guess and present it as fact.** If you don't know something,
  say so and investigate with real data, or ask the user. A real,
  damaging incident already happened earlier in this project where an
  AI (a prior instance of you, functionally) invented a mechanism
  (treating "swing_spent" as a trend-control death trigger) that was
  never taught, implemented it, and it silently changed already-
  validated results across weeks of history before being caught by the
  user and fully reverted. Read that story in the learning log's
  2026-10-05 session entries in full before you touch CONTROL logic —
  it is the clearest possible illustration of the cost of inventing
  something instead of verifying it.
- **Before claiming a bug is fixed, re-verify the full previously-
  validated day range, not just the day that exposed it.** A fix to
  one shared function can silently ripple through the entire dataset.
  This project's own history has at least two cases of exactly that.
- Before any day-by-day walkthrough, confirm you understand CONTROL is
  Daily-only — 4H/1H never drive control, they only consume whatever
  control currently says, plus their own separate conditions
  (authorization, premium/discount, 1H's own PDL/PDH abandonment
  chain). This was wrong once early in the project and fixing it was a
  major architectural correction — don't reintroduce the mistake.

## Your task right now

January 2025 (days 2-31, skipping weekends) is fully verified, reported
day-by-day in the locked format, and logged. **Your job starts at
February 2025, day by day, in the same format, with the same rigor.**
Work through it exactly the way January was worked through: run
`verify_day.py` for each trading day, report it in the locked table
format, log it, flag anything that looks wrong and investigate it for
real before accepting or rejecting it. At the end of the month, give a
short overall performance summary (trades, results, nothing more
elaborate than that) the same way January's closing summary was given.

Do not ask the user "what would you like me to do with this hand-off" —
this file is the answer. Begin with February 2, 2025.
