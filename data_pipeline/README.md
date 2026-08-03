# Asian/London session data pipeline

Builds a per-day dataset of Asian-session liquidity sweeps and reversals for
EUR/USD, from 5 years of free 1-minute OHLC data, as the empirical base for
the session-liquidity EA.

## Pipeline

```
python3 download_data.py --pair eurusd --start-year 2021 --end-year 2025
python3 build_session_dataset.py --pair eurusd --start-year 2021 --end-year 2025
```

`download_data.py` pulls free 1-minute ASCII OHLC bars from HistData.com via
the `histdata` PyPI package into `raw/` (gitignored — regenerate rather than
commit; ~20MB/year). `build_session_dataset.py` reads `raw/` and writes two
files to `derived/` (committed, small):

- `daily_ohlc_<pair>_<start>_<end>.csv` — full calendar-day OHLC + rolling
  14-day ATR in pips, one row per day.
- `asian_london_sessions_<pair>_<start>_<end>.csv` — one row per trading day
  with the session/sweep/reversal variables described below.

Only the derived tables and the pipeline code are version-controlled. The raw
1-minute bars are the permanent source of truth for anything not yet captured
as a derived column — regenerate them locally with `download_data.py` rather
than re-deriving features by hand.

## Timezone

HistData's generic ASCII files are timestamped in **fixed EST (UTC-5),
without DST adjustment, all year round**. We use that column directly as the
reference clock — this avoids DST edge cases entirely, at the cost of Asian/
London session clock times drifting by an hour, real-world, across the March/
November DST changes. Flagged here as a known simplification, not hidden in
the code.

## Session window definitions (all times fixed EST per above)

| Window | Range | Rationale |
|---|---|---|
| Asian session | prior day 20:00 – current day 00:00 | Standard ICT Asian/Tokyo core hours |
| London killzone | 02:00 – 05:00 | Matches the reference strategy's "London's first two trading hours" entry window |
| Extended window | 02:00 – 12:00 | Used only to check whether a *delayed* reversal to the opposite Asian level eventually happens, beyond the killzone |

These are constants at the top of `build_session_dataset.py`
(`ASIAN_START_H`, `LONDON_KZ_START_H`, etc.) — change them and re-run rather
than treating them as fixed; they are a starting assumption, not a proven
optimum.

## Columns in `asian_london_sessions_*.csv`

- `date`, `day_of_week`
- `asian_bar_count`, `london_kz_bar_count`, `data_gap` — data-quality flags;
  `data_gap=True` means the session had materially fewer 1-minute bars than
  expected (holiday, feed gap) and downstream fields may be unreliable for
  that row.
- `asian_open/high/low/close`, `asian_high_time`, `asian_low_time`,
  `asian_high_before_low`, `asian_range_pips`
- `london_kz_open/high/low/close`, `london_kz_range_pips`
- `first_sweep_side` (`high` / `low` / `none`), `first_sweep_time`,
  `both_sides_swept_in_kz`
- `sweep_depth_pips` — max excursion past the swept level
- `sweep_close_beyond_level` — whether a candle *closed* past the level, not
  just wicked through it
- `reversal_reached_opposite` — did price go on to trade through the
  opposite Asian level within the extended window
- `reversal_time`, `minutes_to_reversal`
- `direction_if_faded` (`long`/`short`) — the trade direction implied by
  fading the first sweep
- `mfe_pips`, `mae_pips` — Maximum Favorable/Adverse Excursion for a
  hypothetical entry at the sweep bar's close, in the faded direction,
  measured up to the reversal (or to the end of the extended window if the
  reversal never happened)
- `atr14_pips_prior` — trailing 14-day ATR in pips, as of the prior day
- `low_liquidity_flag` — Asian range under 40% of its trailing 20-day
  median; a data-driven proxy for holiday/thin-liquidity days rather than a
  maintained holiday calendar (no holiday calendar is wired in yet — see
  Known limitations)

## Known limitations / not yet included

- **No news/economic calendar overlay.** High-impact news (NFP, CPI, central
  bank decisions) can dominate session behavior and isn't flagged in this
  version. Planned as a follow-up once the core pattern is validated, since
  it needs an additional external data source.
- **`low_liquidity_flag` is a statistical proxy, not a real holiday
  calendar** — only flagged 2 of 1,303 days in the 2021-2025 EUR/USD run, so
  treat it as a weak signal, not a reliable holiday filter.
- **MFE/MAE use the sweep bar's close as a proxy entry price**, not a
  structure-confirmed entry (market structure shift, order block, etc.) —
  those come in a later stage once the raw sweep/reversal pattern is
  validated, and will very likely change the real win rate / R:R.

## Mechanical backtest (`simulate_strategy.py`)

`build_session_dataset.py` is descriptive (what happened, looking at the
whole post-sweep window at once). `simulate_strategy.py` is a real,
path-dependent backtest: it walks the 1-minute bars in time order and
applies an actual entry/stop/target/breakeven rule, so a trade's outcome
depends on what happens *first* (stop vs. breakeven vs. target), not on
where price eventually ends up.

```
python3 simulate_strategy.py --pair eurusd
```

Rule tested: entry at the sweep bar's close; stop at the sweep bar's own
high/low (+1 pip buffer) -- known at entry time only, never a later/deeper
excursion, to avoid lookahead bias; target = opposite Asian level. Three
breakeven variants (`none`, move to breakeven at `1R`, move to breakeven at
`50pct` of the distance to target) are compared on a **2021-2023 TRAIN**
split only; the best by expectancy is then run once, untouched, on a
**2024-2025 TEST** split. Output: `derived/backtest_results.json` and
per-trade `derived/backtest_train_<rule>.csv` / `backtest_test_<rule>.csv`.

**Result**: none of the three breakeven variants produce a strong edge with
this stop placement. The best (`none`, i.e. no breakeven move) gets TEST
win rate 12.1%, expectancy +0.142R/trade, profit factor 1.16, but max
drawdown 54.65R -- far beyond what any prop firm or reasonable account
sizing would tolerate. Cross-referencing the 1,122 losing trades against
`progress_pct_of_asian_range` shows **53% of them were on days price
eventually reached the target anyway** -- the stop (sweep bar's own wick)
is simply too tight relative to normal EUR/USD noise in this window, not a
wrong directional read. This is a real, honest negative result: it argues
for a structural (market-structure-shift-based) entry and stop, not the
current purely mechanical one, as the priority next step -- it is not
evidence the underlying directional bias is wrong.

## Results on the initial EUR/USD 2021-2025 run

Of 1,295 data-quality-clean trading days:
- 97.8% had at least one side of the Asian range swept during the London
  killzone (i.e. an outright non-sweep day is rare — the sweep by itself is
  not a selective/rare signal).
- Of swept days, 58.2% went on to reach the *opposite* Asian level within
  the extended window (vs. 50% baseline).
- Median MAE (26.4 pips mean, 16.0 median) is comparable to or larger than
  median MFE (17.8 pips mean, 15.5 median) — a naive "enter right after the
  sweep, target the opposite side" trade would frequently be stopped out by
  adverse movement before reaching target, even on days that eventually
  "worked." This is the strongest argument yet for needing a structure-based
  entry trigger (market structure shift / order block) rather than trading
  the raw sweep signal directly.
- 28.6% of days saw *both* sides swept within the killzone — meaningfully
  choppy/two-way price action that a single-direction fade doesn't handle
  cleanly.

## Excursion research and validated strategy

Three scripts, run in this order, replace the naive first-pass backtest:

```
python3 analyze_reversal_behavior.py --pair eurusd   # measure, don't assume
python3 optimize_strategy.py --pair eurusd           # grid on TRAIN, one TEST look
python3 explore_extended.py                          # cost sensitivity + wider targets
python3 final_validation.py                          # fixed split + walk-forward
python3 monte_carlo_prop.py                          # prop-challenge simulation
```

### What the measurement found

Excursion beyond the swept level, to the actual turning point, separates the
two populations sharply:

| | median | 75th pct | 90th pct |
|---|---|---|---|
| Days that reached target (737) | 8.4 pips | 15.7 | 25.0 |
| Days that failed (530) | 44.1 pips | 64.8 | 88.1 |

So the earlier "stop on the sweep candle's wick" was wrong by construction --
it sat inside the noise band that both populations share. A stop 12 pips
beyond the level keeps 63% of winners while cutting 96% of losers.

Reversal behaviour on winning days:

* **100% of target-reaching days close a candle back inside the Asian range
  before running**, vs 85.3% of failing days. Requiring that "reclaim" is a
  free filter -- it discards ~15% of losers at zero cost to winners.
* The reclaim is fast: median 2 minutes after the sweep.
* Price stabs past the level a median of 3 times on winning days vs 5 on
  failing ones.
* After the reclaim, the worst adverse move before target is a median of 6.8
  pips (90th pct 22.6) -- that, not the sweep wick, is what a stop must survive.

### Selected configuration

Reclaim entry, stop 12 pips beyond the swept level, target the opposite Asian
level, skip days whose Asian range is under 25 pips, no breakeven move.

| | trades | win rate | expectancy | profit factor | max DD |
|---|---|---|---|---|---|
| TRAIN 2021-2023 | 167 | 33.5% | +0.092R | 1.14 | 13.4R |
| TEST 2024-2025 (one look) | 79 | 36.7% | +0.317R | 1.52 | 12.0R |
| **Walk-forward pooled** | **357** | **39.8%** | **+0.088R** | **1.15** | **21.1R** |

The walk-forward number is the one to trust: parameters are re-selected inside
each rolling window and traded forward blind, so no trade influenced its own
parameters. 4 of 7 folds were profitable.

### Caveats that matter

* **Execution cost decides everything.** At zero cost the tight-stop configs
  show +0.132R; at 1 pip they are negative. Break-even sits near 0.6-0.8 pips
  for those. Every result above already charges 1.0 pip.
* **The stop plateau is narrow** -- 8 and 12 pips agree, but 15 is flat and 20
  is negative. Treat stop distance as a live sensitivity, not a settled value.
* **21.1R drawdown is too large for a funded account** at 1% risk. Monte Carlo
  over the walk-forward trades (20,000 runs, +8% target / -10% trailing DD):
  1% risk gives a 56.0% pass rate but a 28.4% chance of breaching drawdown
  instead; 0.5% risk cuts blow-ups to 2.5% but the pass rate falls to 26.9%
  with 70.6% timing out.
* **No news filter yet**, and the DST simplification above still applies.

Conclusion: a real but modest edge, not yet a fundable one. The highest-value
next steps are a genuine market-structure entry trigger (the reclaim is a crude
proxy for a market structure shift), a news filter, and testing GBP/USD and
gold where wider session ranges make the fixed execution cost proportionally
cheaper.

## Entry confirmation models (`entry_models.py`, `diagnose_pullback.py`, `retrace_stop.py`)

Tests whether waiting for structural confirmation, and entering on a pullback,
beats entering on the first reclaim. Standard definitions used throughout:
Bill Williams fractal is the 5-bar pattern (2 bars either side of the extreme,
usable only once the 5th bar closes); MSS/BOS require a candle *body* beyond
the swing, not a wick, so `break_on="close"` is the faithful variant.

```
python3 entry_models.py        # fractal / swing / reclaim x market / pullback
python3 diagnose_pullback.py   # why pullback entries underperform
python3 retrace_stop.py        # retracement as the exit instead of the entry
```

### Result 1 -- structure confirmation does not beat the reclaim

Waiting raises the win rate (26.5% on the fastest entry up to ~34-36% on
swing n=5) but pushes the stop further from entry (9.2 -> 13.9 pips average),
and the extra win rate never pays for the worse reward:risk. Mean expectancy
by model was negative for every confirmation type; the best single configs
were reclaim-based.

### Result 2 -- pullback entries shrink the stop and lose money anyway

Pullback limits genuinely reduce risk, most on the reclaim model: **9.2 -> 6.3
pips, a 32% tighter stop**. Expectancy still fell across every model. The cause
is adverse selection, measured directly in `diagnose_pullback.py` on the 265
qualifying days:

| | days | win rate | mean R | total R |
|---|---|---|---|---|
| Never pulled back | 52 (19.6%) | 50.0% | +0.964 | **+50.1R** |
| Did pull back | 213 (80.4%) | 18.3% | -0.071 | **-15.2R** |

All of the profit sits in the fifth of setups a limit order would never have
filled; 40% of all winners never retraced. Price coming back to you is the
first sign the reversal is failing, not an opportunity.

### Result 3 -- retracement stops do not fix it either

One retracement-stop config produced the best single training expectancy of
anything tested (+0.154R) but the mode averaged **-0.294R** across its
configurations, by far the worst of the three stop modes, and that best config
carried a 37.3R drawdown -- the signature of a lucky parameter. Walk-forward
pooled to +0.054R at PF 1.09, worse than a stop under the sweep extreme.

### Walk-forward scoreboard across all three rounds

| Approach | OOS trades | win rate | expectancy | PF | max DD |
|---|---|---|---|---|---|
| Reclaim entry, stop beyond level | 357 | 39.8% | +0.088R | 1.15 | 21.1R |
| Structure confirmation models | 285 | 32.3% | +0.123R | 1.18 | 23.2R |
| Retracement-based stops | 385 | 36.4% | +0.054R | 1.09 | 30.5R |

Three genuinely different ideas landing in the same 1.09-1.18 profit-factor
band suggests the ceiling is set by the setup itself, not by entry mechanics.

### What this points at next

Winners run immediately and never look back; losers retrace. The tradeable
signal is therefore momentum right after the reclaim, not a better price -- so
the untested lever is a **quality filter before entry** (displacement on the
reclaim candle, whether the sweep took a genuine prior swing rather than a
random low, news exclusion), not a smarter entry trigger. And execution cost
keeps pointing at the same structural fix: run this on GBP/USD and gold, where
1 pip is a much smaller share of the session range.

## The user's own indicator, applied after the sweep (`mss_engine.py`, `mss_after_sweep.py`)

`mss_engine.py` is a faithful port of the swing-detection + regime/MSS logic
from the user's `ICT_Full_OB_v24_indicator_2.pine` (order-block engine
stripped out, not needed for this question). Ported piece-for-piece:

* Swing confirmation is a **one-bar break**, not an N-bar fractal: a swing low
  confirms the instant a bar's high exceeds the prior bar's high (stamped at
  the running lowest low since the last swing high), mirrored for swing highs.
  Confirmation lag is ~1 bar, not 5.
* Kind alternates strictly (no two same-direction swings in a row), and a
  block guard suppresses the noise burst after an outside bar breaks both
  sides at once.
* MSS fires only on a **regime flip** (up->down or down->up) when an armed
  swing is broken; breaking a swing *with* the current regime is silent
  continuation (BOS), matching the standard MSS/BOS distinction. Breaks on
  the wick, not a body close (the user's version is more permissive here than
  the ICT convention used in `entry_models.py`).

Run continuously across the whole 5-year series (`mss_after_sweep.py`),
matching how the indicator behaves live, not reset per day:

```
python3 mss_after_sweep.py
```

For every sweep day, looks for the expected-direction MSS (down after a high
sweep, up after a low sweep) between the sweep and the target/window-end.

### Results

* **The "sweep implies trend" premise holds most of the time, not always**:
  regime at the moment of sweep agrees with the assumed direction 75.2% of
  high-sweep days, 78.7% of low-sweep days.
* **The expected MSS fires on almost every single day** (99.8% / 100%),
  usually many times (median 22 flips before target/window-end). At one MSS
  event roughly every 13.9 minutes on 1-minute bars with 1-bar-break
  confirmation, that's not a selective signal -- a same-direction flip inside
  any multi-hour window is close to guaranteed by construction. This is also
  the likely reason the original reference strategy specified 1H MSS, not
  1-minute: on a higher timeframe the same logic would confirm far less
  often, and each confirmation would mean more.
* **The flip count itself is a strong, real signal.** Days that reach target
  average **11.9 flips** after the sweep; days that fail average **30.8** --
  a 2.6x separation (low-sweep mirror: 11.2 vs 30.6, near-identical). The
  histogram shows close to a clean threshold: under ~10 flips is almost
  entirely target-reaching days, over ~25 is almost entirely failures.

This is a third, independent method landing on the same conclusion as the
excursion research and the pullback diagnosis: decisive, low-chop moves win;
choppy, back-and-forth ones fail. Turning "flip count so far" into an actual
entry filter needs the same discipline as everything else here -- threshold
and measurement window chosen on TRAIN only, validated once on TEST -- since
reading a cutoff straight off this histogram would be circular. Not yet done.

## Trading the leg-stop, not the flip count (`mss_trade_simulation.py`)

The flip-count research above measured the engine's own internal regime
oscillation, not any specific trade's risk -- a real question the user
raised directly. `mss_engine.py` was extended to attach, to every emitted
MSS event, `leg_price`/`leg_idx`: the swing on the opposite side that
immediately precedes, in the confirmed-event sequence, the swing this event
just broke -- the leg's actual origin, which is what a trade entered on that
MSS would use as its stop (not the engine's next internal marker, which can
be a much closer, freshly-formed level with no relation to the trade).

`mss_trade_simulation.py` simulates it for real: enter on MSS-down, stop at
that leg high; if hit, wait for the next MSS-down and re-enter; repeat until
target or window end.

```
python3 mss_trade_simulation.py
```

### Result: this is not tradeable as a per-flip mechanism

| | |
|---|---|
| Win rate per individual attempt | 9.5% (347/3,644) |
| Median stop distance | 4.0 pips |
| Median re-entries needed per day | 5 (up to 25) |
| Mean total R per day, all re-entries summed | -2.36R |

Median stop is only 4 pips because on 1-minute bars consecutive swing
highs/lows form only a few pips apart -- ordinary 1-minute noise clips it
repeatedly. The day still often resolves toward target overall (matching the
~58% reach rate found earlier), but the accumulated cost of a median 5
stop-outs along the way outweighs the eventual win almost every time.

This isn't evidence the directional setup is wrong -- it's evidence that
trading this exact engine's raw MSS on 1-minute bars, with a stop at each
leg's own (tiny) swing, is structurally unworkable. Points at the same two
levers already identified: run the engine on 1H (as the original reference
strategy specified) where legs are naturally wider, and/or use the flip
count as a pre-entry filter rather than a per-flip trigger.

## Same engine, three timeframes (`mss_higher_timeframe.py`)

Resamples the same 1-minute data to 5-minute and 15-minute candles, runs the
identical swing/MSS engine and leg-stop trade simulation on each, and compares
against the 1-minute baseline. Two things stay fixed across all three runs so
timeframe is the only variable: Asian/London session levels and the sweep
moment are always computed from 1-minute data; trade execution (does price
touch the stop or target first) is always checked against raw 1-minute bars,
never the coarser resampled candle, to avoid same-bar stop/target ambiguity.
Only swing/MSS detection itself runs on the coarser candles. A resampled
bar's O/H/L/C isn't used until that bar closes (matching how the indicator
recalculates live), so each event maps to the last 1-minute bar inside its
candle before execution starts.

```
python3 mss_higher_timeframe.py
```

### Result: clean, monotonic improvement at every step

| Timeframe | Win % / attempt | Median stop | Median re-entries/day | Mean R/day |
|---|---|---|---|---|
| 1m | 9.5% / 9.6% | 4.8p | 5 | -2.36 / -2.16 |
| 5m | 20.1% / 20.9% | 7.6p / 7.7p | 2 | -0.72 / -0.67 |
| 15m | 33.2% / 33.5% | 10.8p / 10.9p | 1 | -0.26 / -0.34 |

(pairs are sweep-high/short then sweep-low/long; both sides move together at
every step, which is itself evidence this is a real relationship and not
noise.) Regime-at-sweep match with the "sweep implies trend" assumption also
climbs with timeframe: 75-79% at 1m, 83-84% at 5m, 88-90% at 15m.

Still net negative at 15m -- not yet a working system on its own -- but the
trend recovered roughly 2R/day going from 1m to 15m, one step short of the
1H timeframe the original reference strategy actually specified. That's the
natural next test.

## Retracement into the confirmed MSS leg (`mss_retracement.py`)

A different question from `entry_models.py`'s pullback test: that one measured
retracement into the pre-MSS reclaim (before any structural confirmation
existed). This measures retracement AFTER MSS already confirmed and price
already printed a fresh swing extreme in the trade's favor -- i.e. a pullback
into an already-validated leg, not a pullback that might mean the setup never
really started.

Definition, exactly as specified: after the first tradeable MSS event, find
the next confirmed swing point in the trend's own direction (a fresh low
after MSS-down, a fresh high after MSS-up) -- that is the 0% level. The
original MSS stop (the leg's origin swing, per `mss_engine.py`'s `leg_price`)
is the 100% level. The leg is the price range between them, split into
quarters.

```
python3 mss_retracement.py
```

### Result: retracement depth predicts outcome, and a deeper limit entry pays off

Median retracement into the leg: **104.0%** overall at 5m (100.9% at 15m) --
most first attempts eventually exceed the stop and lose, consistent with
earlier rounds. But split by outcome, the picture is informative: **days that
reach target retrace a median of 52.7% (5m) / 45.6% (15m)** before turning
and running, versus ~108-110% (i.e. the stop) on days that fail. A real,
roughly-halfway pullback is normal on a winning day, not a warning sign.

Limit-entry backtest at each quartile (stop still at 100%, target unchanged),
summed across every setup:

| Level | 5m total R | 15m total R |
|---|---|---|
| 0% (market, no wait) | -416.6R | -518.5R |
| 25% | -193.0R | -383.2R |
| 50% | **+136.7R** | -185.1R |
| 75% | **+660.4R** | **+310.6R** |

This is the **opposite** conclusion from `entry_models.py`'s pullback test,
and for a coherent reason: there, waiting for a better price meant waiting on
an unconfirmed signal, and the setups that pulled back were disproportionately
the ones that failed. Here MSS has already confirmed and price has already
run to a fresh extreme before retracement is even measured, so a pullback at
this stage is normal continuation-leg behavior. Win rate drops sharply going
deeper (30%->12% at 5m) and fill rate drops too, but the tighter stop's
reward:risk gain outweighs both, in the total across all setups, not just the
per-trade average.

**Flagged, not adopted**: pushing further (85-95%) initially climbs higher
(5m peaks near +999R around 85%) then reverses hard -- 5m's 95% level falls to
-18.6R on only 57 fills, 15m's 95% level shows a suspicious +4.7R average on
164 fills, the signature of a couple of outsized trades dominating a small
sample rather than a real edge. Reading an "optimal" level off this
exploratory grid would be circular. The 0/25/50/75% result is solid because
those levels were fixed before looking at outcomes; finding the true optimum
needs the same train-2021-2023/test-2024-2025 discipline as every other round
here, not a number read off this chart.

## Characterizing the 737 winning days: how far price runs before it turns

`python3 characterize_winning_days.py` -- pure measurement of the 737 days
where a sweep of one Asian side reached the opposite side (350 swept-high/
fell-to-target, 387 swept-low/rose-to-target). Answers "how many pips does
price run past the level before it finally turns."

* **Overshoot beyond the level**: median 9.3 pips (high) / 7.8 pips (low)
  before the final turn, but with a long tail -- 25% of days turn within
  4 pips, 10% run past 24-25 pips, worst case 63-78 pips.
* **Total one-direction swing** (Asian range + overshoot): median ~27 pips
  both sides, 90th pct ~49-50 pips.
* **Timing**: the turn itself comes fairly fast (median 28-38 minutes after
  the sweep), but the run from that turn to target takes much longer (median
  92-108 minutes) -- most of the trade's duration is the profitable leg, not
  the overshoot.
* **Choppiness**: a typical winning day pokes back past the level 3-4 separate
  times before its final turn; 10% of days do it 10+ times.
* **100% of winning days, on both sides, close at least one candle back
  inside the Asian range before running to target** -- reclaiming the range
  is a near-universal feature of how these days behave, confirming the
  reclaim-based entry rule used in `final_validation.py` isn't an arbitrary
  filter.
* Overshoot size barely correlates with the night's own Asian range size
  (r=0.15 high, r=0.08 low) -- a big range doesn't predict a big overshoot.
* Short and long setups are close to mirror images of each other on every
  metric -- no meaningful asymmetry between the two directions.

Dashboard: `winning_days_dashboard.html` (published as an Artifact).

## Follow-ups: reclaim on losing days, and pullback depth on winning days

`python3 winning_days_retracement.py`

**Reclaim status on the 530 days that did NOT reach target**: 452 (85.3%)
still reclaimed the Asian range at some point; 78 (14.7%) never did. So
reclaiming is common even on losing days -- it rules out the 15% that never
reclaim (those never won either), but on its own it doesn't separate winners
from losers, since 85% of losers reclaim too. This matters because the
reclaim-based entry rule (`final_validation.py`) only filters out that ~15%,
not the much larger group of losers that also reclaim before failing.

**Retracement depth on the 737 winning days, 5-minute chart, restricted to
only these days** (735 of 737 had a measurable MSS leg): once the reversal
confirms (a swing break on the 5m chart) and a fresh extreme prints, price
pulls back toward the old broken swing point (the leg's 0%-to-100% ladder,
same construction as `mss_retracement.py`) by a **median of 90-100%** before
finally continuing to target -- and 44-48% of the time it pulls back even
**past** the old swing point (>100%). Shallow pullbacks under 25% happen on
only ~8% of days. So on days that are already known to work, deep,
uncomfortable-looking pullbacks are the normal behavior, not rare
exceptions -- consistent with why the 75% limit-entry level outperformed
shallower levels in the earlier all-setups backtest.

Dashboard: `reclaim_retracement_dashboard.html` (published as an Artifact).

## 1-minute enter/stop/re-enter, restricted to the 558 deep-pullback days

`python3 winning_days_1m_reentry.py` -- restricted to the 558 (date, side)
setups where the 5-minute pullback reached >=50% of the ladder (previous
section), drop to the 1-minute chart and run the exact enter/stop/re-enter
mechanic from `mss_trade_simulation.py` (enter on a 1-minute swing
exceedance, stop at that leg's own origin swing, re-enter on the next
exceedance if stopped, repeat until target or window end).

* **Win rate per individual attempt roughly triples**: 25.2% (high side) /
  26.3% (low side), vs 9.5%/9.6% on the full, unrestricted day set.
* **Fewer tries needed**: median 3 attempts per day to finally win, vs 5.
* **Mean total R per day flips positive**: +1.96R (high) / +2.39R (low),
  vs roughly -2.3R/day unrestricted -- adding up every losing attempt plus
  the eventual win, the average day nets a profit in this subset.
* 99.3% of these days (555 of 559) still resolve to an eventual win within
  the simulation window.
* Even winning attempts are not a clean ride: of attempts that win, roughly
  half still retest 50% or more of the way to the stop before turning
  around -- winning here still usually means enduring a scary-looking move
  against you first.

**Caveat, stated plainly**: this is still measured only on days already
known (in hindsight) to reach target. The 50%+ pullback condition itself is
realistically observable live, but the underlying day-selection is not --
this is a promising lead, not yet a walk-forward-validated result.

Dashboard: `reentry_558_dashboard.html` (published as an Artifact).

## Which attempt number actually wins, and the second 5-minute ladder

Two follow-ups on the 558-day deep-pullback subset, `winning_days_second_leg.py`:

**Which attempt (1st, 2nd, 3rd...) finally wins**, on the 1-minute
enter/stop/re-enter routine: only 21% of days win clean on attempt 1; another
20% need exactly one stop-out first (win on attempt 2); the rest (59%) need
three or more tries, with a real tail out past 10 attempts. Full breakdown
by exact attempt number saved in the dashboard/report.

**The second 5-minute ladder**: of the 735 measured winning-day legs, 356
had their first ladder's stop actually hit (the ">100%" outcome). Of those
356, **100%** went on to find a new confirmed swing point and build a second
ladder before the window ran out -- on these already-known-winning days, a
broken first leg is never the end of the story. But the second ladder is
roughly a coin flip on its own (51.8% reach target, the rest get stopped
too), and when it pulls back, it pulls back just as deep as the first leg
did (median ~90-100%, ~44% exceed 100% again) -- the same rough pattern
repeats rather than settling down.

Dashboard (glossary of every term included): `attempts_and_second_leg_dashboard.html`.
