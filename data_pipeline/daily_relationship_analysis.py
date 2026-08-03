"""Does yesterday's / day-before-yesterday's daily-candle relationship predict
which Asian side gets swept first today -- sell day vs buy day?

Brainstormed setups (sell is the base case, buy is the exact mirror):

  Setup 1 (timing): from today's Asian-session open (20:00 EST prior day)
    through the end of our Frankfurt+London trading session (05:00 EST),
    does price trade beyond YESTERDAY's full daily high (sell) / low (buy)?
    A fixed window, not sweep-time-bounded, so the signal is knowable
    without already having seen where today's sweep ended up landing.

  Setup 2 (candle relationship): did YESTERDAY's full candle body (both
    open and close) sit entirely below (sell) / above (buy) the day-before-
    yesterday's daily low / high -- a stronger continuation signal than
    just "yesterday's close was lower/higher than D-2's close", which
    `daily_context_features.py` already tested and found not significant.

Either setup predicts today opens, sweeps the Asian high first (sell) or
low first (buy), then hunts the opposite Asian level plus yesterday's own
extreme as an extended target. "Mixed" days -- where a setup predicts one
side but price actually sweeps the other side first -- are reported as
their own category, not folded into agree/disagree, per instruction.

Sweep-side/timing detection here scans the FULL window from Asian close
(00:00, the earliest an Asian extreme could possibly be swept) through the
extended window end (12:00), unlike the killzone-only (02:00-05:00) sweep
column in asian_london_sessions_*.csv, which has a disclosed blind spot for
sweeps completed inside the 00:00-02:00 gap (README.md, "Corrections,
daily-context filters..."). This script does not inherit that gap.

Two day universes are reported, per instruction:
  - "all_days": every day with usable Asian-range + 2-prior-trading-day data.
  - "winning_737": the pre-existing 737-day cohort (reversal_behavior_*.csv,
    reached_target == True) -- an OUTCOME-selected subset, kept only for
    reference/comparison. "all_days" is what item 7's rule validation
    actually uses: a rule can't be judged on a sample that has already
    excluded every day it would need to reject.

Item 7 (optimized-rule validation) deliberately stays away from R-multiples,
win rate, or any other P&L metric: those depend on choices -- stop-loss
distance, target, entry mechanic, position size -- that this round of
research doesn't fix, so "is this profitable" can't be honestly answered
yet. Instead it asks two behavioral questions with the same train
(2021-2023) / test (2024-2025) split used everywhere else in this project:
(1) does setup 1's ~82% directional accuracy hold up on the later chunk of
history it never touched, or was it a fluke of one period; (2) on the days
it correctly calls the side, does the resulting move behave differently --
more or less likely to run the full distance to the opposite Asian level --
than an ordinary day.
"""
import bisect
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt

PIP = opt.PIP
ASIAN_START_H = opt.ASIAN_START_H          # 20
LONDON_KZ_START_H = opt.LONDON_KZ_START_H  # 2
LONDON_KZ_END_H = opt.LONDON_KZ_END_H      # 5
EXTENDED_END_H = opt.EXTENDED_END_H        # 12
FRANKFURT_START_H = LONDON_KZ_START_H - 1  # 1 -- Frankfurt+London session start

DERIVED = opt.OUT_DIR


def prior_trading_days(avail_dates, day, n):
    """The n most recent AVAILABLE trading days strictly before `day` --
    same trading-day-aware lookup as daily_context_features.py, so a
    Monday's "day before yesterday" correctly skips the data-less weekend
    instead of landing on Saturday."""
    pos = bisect.bisect_left(avail_dates, day)
    if pos < n:
        return None
    return [avail_dates[pos - k] for k in range(1, n + 1)]


def session_bucket(hour):
    if hour is None:
        return "no_sweep"
    if hour < FRANKFURT_START_H:
        return "before_session"
    if hour < LONDON_KZ_END_H:
        return "in_session"
    return "after_session"


def combine_side(sell, buy):
    if sell and not buy:
        return "high"
    if buy and not sell:
        return "low"
    if sell and buy:
        return "conflict"
    return "none"


def build_features():
    raw = opt.load_raw("eurusd", 2021, 2025)

    daily = pd.read_csv(os.path.join(DERIVED, "daily_ohlc_eurusd_2021_2025.csv"), parse_dates=["ts"])
    daily = daily.set_index(daily["ts"].dt.date).sort_index()
    avail_dates = daily.index.to_numpy()

    sess = pd.read_csv(os.path.join(DERIVED, "asian_london_sessions_eurusd_2021_2025.csv"), parse_dates=["date"])
    sess = sess[sess["data_gap"] == False].copy()
    sess["date"] = sess["date"].dt.date

    rows = []
    n_dropped = 0
    for _, r in sess.iterrows():
        day = r["date"]
        prior = prior_trading_days(avail_dates, day, 2)
        if prior is None:
            n_dropped += 1
            continue
        yday, dby = prior[0], prior[1]
        y = daily.loc[yday]
        d2 = daily.loc[dby]

        asian_open_ts = pd.Timestamp(day) - pd.Timedelta(hours=24 - ASIAN_START_H)
        kz_end_ts = pd.Timestamp(day).replace(hour=LONDON_KZ_END_H)
        asian_close_ts = pd.Timestamp(day)
        ext_end_ts = pd.Timestamp(day).replace(hour=EXTENDED_END_H)

        window = raw.loc[asian_open_ts:kz_end_ts - pd.Timedelta(seconds=1)]
        setup1_sell = bool(len(window) and (window["high"] > y["high"]).any())
        setup1_buy = bool(len(window) and (window["low"] < y["low"]).any())

        y_body_lo, y_body_hi = min(y["open"], y["close"]), max(y["open"], y["close"])
        setup2_sell = bool(y_body_hi < d2["low"])
        setup2_buy = bool(y_body_lo > d2["high"])

        asian_high, asian_low = r["asian_high"], r["asian_low"]
        post = raw.loc[asian_close_ts:ext_end_ts - pd.Timedelta(seconds=1)]
        hi_mask = post["high"] > asian_high
        lo_mask = post["low"] < asian_low
        hi_t = post.index[hi_mask][0] if hi_mask.any() else None
        lo_t = post.index[lo_mask][0] if lo_mask.any() else None
        if hi_t is None and lo_t is None:
            actual_side, actual_time = None, None
        elif hi_t is not None and (lo_t is None or hi_t <= lo_t):
            actual_side, actual_time = "high", hi_t
        else:
            actual_side, actual_time = "low", lo_t
        actual_hour = actual_time.hour if actual_time is not None else None

        reached_yday_extreme = None
        if actual_side == "high":
            reached_yday_extreme = bool((post.loc[actual_time:]["low"] <= y["low"]).any())
        elif actual_side == "low":
            reached_yday_extreme = bool((post.loc[actual_time:]["high"] >= y["high"]).any())

        predicted_setup1 = combine_side(setup1_sell, setup1_buy)
        predicted_setup2 = combine_side(setup2_sell, setup2_buy)
        predicted_combined = combine_side(setup1_sell or setup2_sell, setup1_buy or setup2_buy)

        def mixed_agree(predicted):
            mixed = bool(predicted in ("high", "low") and actual_side in ("high", "low") and predicted != actual_side)
            agree = bool(predicted in ("high", "low") and actual_side in ("high", "low") and predicted == actual_side)
            return mixed, agree

        mixed_combined, agree_combined = mixed_agree(predicted_combined)

        rows.append({
            "date": day, "day_of_week": r["day_of_week"],
            "asian_high": asian_high, "asian_low": asian_low, "asian_range_pips": r["asian_range_pips"],
            "yday_high": y["high"], "yday_low": y["low"], "yday_open": y["open"], "yday_close": y["close"],
            "dby_high": d2["high"], "dby_low": d2["low"],
            "setup1_sell": setup1_sell, "setup1_buy": setup1_buy,
            "setup2_sell": setup2_sell, "setup2_buy": setup2_buy,
            "predicted_side_setup1": predicted_setup1,
            "predicted_side_setup2": predicted_setup2,
            "predicted_side": predicted_combined,
            "actual_side": actual_side,
            "actual_sweep_time": actual_time.strftime("%H:%M") if actual_time is not None else None,
            "actual_sweep_hour": actual_hour,
            "session_bucket": session_bucket(actual_hour),
            "reached_yesterday_extreme": reached_yday_extreme,
            "mixed_day": mixed_combined, "agree_day": agree_combined,
        })

    feat = pd.DataFrame(rows)
    feat_path = os.path.join(DERIVED, "daily_relationship_features.csv")
    feat.to_csv(feat_path, index=False)
    print(f"Wrote {feat_path} ({len(feat)} rows, {n_dropped} dropped for insufficient prior-day history)")
    return feat


def directional_accuracy(df, pred_col):
    d = df[df[pred_col].isin(["high", "low"])]
    n = len(d)
    if n == 0:
        return {"n": 0, "accuracy_pct": None}
    n_hit = int((d[pred_col] == d["actual_side"]).sum())
    return {"n": n, "accuracy_pct": round(n_hit / n * 100, 1)}


def describe_universe(df):
    n = len(df)

    def rate(mask):
        return round(float(mask.sum() / n * 100), 1) if n else None

    base = df[df["actual_side"].isin(["high", "low"])]

    out = {
        "n_days": n,
        "setup1_sell_rate_pct": rate(df["setup1_sell"]),
        "setup1_buy_rate_pct": rate(df["setup1_buy"]),
        "setup2_sell_rate_pct": rate(df["setup2_sell"]),
        "setup2_buy_rate_pct": rate(df["setup2_buy"]),
        "predicted_side_counts": {str(k): int(v) for k, v in df["predicted_side"].value_counts().items()},
        "actual_side_counts": {str(k): int(v) for k, v in df["actual_side"].value_counts(dropna=False).items()},
        "baseline_actual_high_rate_pct": round(float((base["actual_side"] == "high").mean() * 100), 1) if len(base) else None,
        "directional_accuracy_setup1_only": directional_accuracy(df, "predicted_side_setup1"),
        "directional_accuracy_setup2_only": directional_accuracy(df, "predicted_side_setup2"),
        "directional_accuracy_combined": directional_accuracy(df, "predicted_side"),
        "mixed_day_n": int(df["mixed_day"].sum()),
        "mixed_day_rate_pct": rate(df["mixed_day"]),
        "agree_day_n": int(df["agree_day"].sum()),
        "agree_day_rate_pct": rate(df["agree_day"]),
    }

    sb = df["session_bucket"].value_counts()
    out["sweep_timing"] = {str(k): int(v) for k, v in sb.items()}

    hourly = df.loc[df["actual_sweep_hour"].notna() & (df["actual_sweep_hour"] < LONDON_KZ_END_H), "actual_sweep_hour"]
    out["hourly_sweep_histogram"] = {str(int(k)): int(v) for k, v in hourly.value_counts().sort_index().items()}

    reach = df["reached_yesterday_extreme"].dropna()
    out["reached_yesterday_extreme_rate_pct"] = round(float(reach.mean() * 100), 1) if len(reach) else None
    return out


TRAIN_END = pd.Timestamp("2023-12-31").date()


def reach_group(df):
    """Pure behavioral outcome -- did price go on to fully reach the
    opposite Asian level -- with NO stop-loss, target distance, position
    size, or R-multiple assumption baked in anywhere. Deliberately kept out
    of item 7: that P&L framing depends on choices (stop tightness, target,
    entry mechanic) this round of research doesn't fix, so it can't honestly
    be measured yet -- see README caveat."""
    n = len(df)
    return {"n": int(n), "reach_rate_pct": round(float(df["reached_target"].mean() * 100), 1)} if n else {"n": 0}


def pattern_stability(feat, rb):
    """Is setup 1's behavior a stable, repeatable pattern, or a fluke of
    one stretch of history? Split the five years into an earlier chunk
    (2021-2023, "train") and a later chunk (2024-2025, "test") the same
    way the rest of this project does, and check whether setup 1's numbers
    look the same in both -- no rule was tuned on either chunk here, this
    is purely "does the pattern repeat when you look somewhere else."
    """
    feat = feat.copy()
    feat["split"] = feat["date"].apply(lambda d: "train" if d <= TRAIN_END else "test")

    accuracy_by_split = {}
    for split in ["train", "test"]:
        s = feat[feat["split"] == split]
        accuracy_by_split[split] = {
            "n_days": int(len(s)),
            "directional_accuracy_setup1": directional_accuracy(s, "predicted_side_setup1"),
            "mixed_day_rate_pct": round(float(s["mixed_day"].mean() * 100), 1),
        }

    # Second, separate question: on the days setup 1 correctly calls the
    # side, does the resulting move behave any differently -- specifically,
    # is it MORE or LESS likely to run the full distance to the opposite
    # Asian level -- than an ordinary day? Still no R-multiple: "reached
    # target" here just means "touched the opposite Asian level," a fixed
    # price landmark, not a chosen stop/target.
    m = rb.merge(feat[["date", "predicted_side_setup1", "mixed_day", "split"]], on="date", how="left")
    reach_by_signal = {}
    for split in ["train", "test", "all"]:
        s = m if split == "all" else m[m["split"] == split]
        agreed = s[(s["predicted_side_setup1"] == s["side"]) & (s["predicted_side_setup1"].isin(["high", "low"]))]
        reach_by_signal[split] = {
            "baseline_all_sweep_days": reach_group(s),
            "setup1_agreed": reach_group(agreed),
            "mixed_setup1_wrong": reach_group(s[s["mixed_day"] == True]),
            "no_signal": reach_group(s[s["predicted_side_setup1"] == "none"]),
        }

    return {"directional_accuracy_train_vs_test": accuracy_by_split, "reach_rate_by_signal": reach_by_signal}


def main():
    feat = build_features()

    rb = pd.read_csv(os.path.join(DERIVED, "reversal_behavior_eurusd_2021_2025.csv"), parse_dates=["date"])
    rb["date"] = rb["date"].dt.date
    winning_dates = set(rb.loc[rb["reached_target"] == True, "date"])
    assert len(winning_dates) == 737, f"expected 737 winning days, got {len(winning_dates)}"

    report = {
        "all_days": describe_universe(feat),
        "winning_737": describe_universe(feat[feat["date"].isin(winning_dates)]),
        "item7_pattern_stability_no_pnl_assumptions": pattern_stability(feat, rb),
    }

    report_path = os.path.join(DERIVED, "daily_relationship_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote {report_path}")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
