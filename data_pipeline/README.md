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
