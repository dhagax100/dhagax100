"""Does yesterday's / day-before-yesterday's daily-candle relationship predict
which Asian side gets swept first today -- sell day vs buy day?

Three candles: candle 2 = day before yesterday (closed, fixed), candle 1 =
yesterday (also closed), candle 0 = today (live, what we trade).

  Setup 1 (reversal), EXPANDED -- fires from EITHER of two sources, both the
    same *kind* of signal (an unconfirmed break predicting a reversal),
    just found a day apart:
      1a. today's live price trades beyond candle 1's (yesterday's) full
          daily high (sell) / low (buy) -- the original definition.
      1b. candle 1 only WICKED beyond candle 2's high/low without closing
          beyond it (unconfirmed) -- known before today even opens.
    Predicts: the Asian high sweeps first (sell) or Asian low sweeps first
    (buy), then price hunts the opposite Asian level.

  Setup 2 (continuation): candle 1 traded beyond candle 2's high/low AND
    CLOSED with its body beyond that same level (confirmed, not just a
    wick). Predicts a "keep going" day: sweep the opposite Asian level
    first as a shakeout (Asian low for a buy-continuation, Asian high for
    a sell-continuation), then continue toward the same-direction Asian
    level and candle 1's own high/low (PDH/PDL). If today also closes with
    body beyond candle 1's high/low, the same call repeats tomorrow using
    today as the new candle 1 -- a chain that only breaks the day a candle
    wicks through without closing beyond (at which point it becomes a
    setup-1b reversal signal instead).

  A day where candle 1's wick reaches beyond candle 2 on BOTH sides (high
  AND low) is thrown out of both setups entirely -- too ambiguous to call.

Either setup predicts today opens, sweeps the Asian high first (sell) or
low first (buy), then hunts the opposite Asian level plus yesterday's own
extreme as an extended target. "Mixed" days -- where a setup predicts one
side but price actually sweeps the other side first -- are reported as
their own category, not folded into agree/disagree, per instruction.

`rule2_scenarios()` reports the specific edge cases requested: days where
setup 2 is clean with no setup-1 signal in play at all; days where setup 2's
continuation story is invalidated because today broke both the Asian low
and candle 1's own low (or the mirror); the both-sides-engulfed exclusion
count; setup 1's accuracy broken down by source (1a vs 1b); and setup 2's
wrong-side-swept-first rate.

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
        setup1a_sell = bool(len(window) and (window["high"] > y["high"]).any())
        setup1a_buy = bool(len(window) and (window["low"] < y["low"]).any())

        # Candle 1 (yesterday) vs candle 2 (day before yesterday): did
        # candle 1 wick beyond candle 2's high/low, and did it CLOSE beyond
        # that same level (confirmed) or only wick through it (unconfirmed)?
        yday_wick_above_d2 = bool(y["high"] > d2["high"])
        yday_wick_below_d2 = bool(y["low"] < d2["low"])
        yday_engulfs_d2 = yday_wick_above_d2 and yday_wick_below_d2
        yday_closes_above_d2 = bool(y["close"] > d2["high"])
        yday_closes_below_d2 = bool(y["close"] < d2["low"])

        # Setup 2 (continuation): confirmed break -- body closed beyond it.
        setup2_buy = bool(yday_wick_above_d2 and yday_closes_above_d2 and not yday_engulfs_d2)
        setup2_sell = bool(yday_wick_below_d2 and yday_closes_below_d2 and not yday_engulfs_d2)

        # Setup 1b: unconfirmed break -- wicked beyond candle 2 but closed
        # back on the near side. Same kind of signal as 1a, folded into
        # setup 1 below.
        setup1b_sell = bool(yday_wick_above_d2 and not yday_closes_above_d2 and not yday_engulfs_d2)
        setup1b_buy = bool(yday_wick_below_d2 and not yday_closes_below_d2 and not yday_engulfs_d2)

        # setup1_sell/buy stays the ORIGINAL, 1a-only definition -- item 7's
        # already-validated 82.3% accuracy and its train/test stability are
        # about THIS. setup1_expanded_* (1a OR 1b) is a separate, diagnostic
        # column: item 8 tests whether folding 1b in helps or hurts, and the
        # answer (README, item 8) is that it hurts -- so it's kept as an
        # alternative to compare against, not adopted as the real Rule 1.
        setup1_sell = setup1a_sell
        setup1_buy = setup1a_buy
        setup1_expanded_sell = setup1a_sell or setup1b_sell
        setup1_expanded_buy = setup1a_buy or setup1b_buy

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
        predicted_setup1_expanded = combine_side(setup1_expanded_sell, setup1_expanded_buy)
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
            "setup1a_sell": setup1a_sell, "setup1a_buy": setup1a_buy,
            "setup1b_sell": setup1b_sell, "setup1b_buy": setup1b_buy,
            "setup1_expanded_sell": setup1_expanded_sell, "setup1_expanded_buy": setup1_expanded_buy,
            "setup2_sell": setup2_sell, "setup2_buy": setup2_buy,
            "yday_engulfs_d2": yday_engulfs_d2,
            "predicted_side_setup1": predicted_setup1,
            "predicted_side_setup1_expanded": predicted_setup1_expanded,
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


def rule2_scenarios(feat):
    """The specific edge-case scenarios requested: where setup 1 (expanded)
    and setup 2 (continuation) can point at different things, and the cases
    that make one or the other inapplicable for a given day. Reported as
    plain 5-year counts, not train/test -- these are diagnostics on the
    rule definitions themselves, not a claim about profitability."""
    n = len(feat)

    def rate(mask):
        return round(float(mask.sum() / n * 100), 1) if n else None

    out = {}

    out["yday_engulfs_d2_excluded"] = {
        "n": int(feat["yday_engulfs_d2"].sum()), "rate_pct": rate(feat["yday_engulfs_d2"]),
    }

    r2_buy = feat[feat["setup2_buy"]]
    r2_sell = feat[feat["setup2_sell"]]

    # Scenario 1: setup 2 fires, today's actual sweep matches it cleanly
    # (AL first for buy-continuation, AH first for sell-continuation), and
    # setup 1 doesn't fire at all that day -- no conflict, no room for it.
    clean_buy = r2_buy[(r2_buy["actual_side"] == "low") & (~r2_buy["setup1_expanded_sell"]) & (~r2_buy["setup1_expanded_buy"])]
    clean_sell = r2_sell[(r2_sell["actual_side"] == "high") & (~r2_sell["setup1_expanded_sell"]) & (~r2_sell["setup1_expanded_buy"])]
    out["rule2_clean_no_rule1_in_play"] = {
        "buy_continuation": {"n": int(len(clean_buy)), "of_rule2_buy_days": int(len(r2_buy))},
        "sell_continuation": {"n": int(len(clean_sell)), "of_rule2_sell_days": int(len(r2_sell))},
    }

    # Scenario 2: setup 2 (continuation) was the call, but today's price
    # broke BOTH the Asian low/high AND candle 1's own low/high (PDL/PDH)
    # -- not just the shakeout setup 2 expects. setup1a_buy/sell already IS
    # "today traded beyond PDL/PDH."
    invalidated_buy = r2_buy[r2_buy["setup1a_buy"]]
    invalidated_sell = r2_sell[r2_sell["setup1a_sell"]]
    out["rule2_continuation_invalidated_by_pdl_pdh_break"] = {
        "buy_continuation": {"n": int(len(invalidated_buy)), "of_rule2_buy_days": int(len(r2_buy))},
        "sell_continuation": {"n": int(len(invalidated_sell)), "of_rule2_sell_days": int(len(r2_sell))},
    }

    # Scenario 5: setup 2 was the call, but the actual first sweep was the
    # opposite side entirely -- a flat-wrong call for setup 2.
    wrong_buy = r2_buy[r2_buy["actual_side"] == "high"]
    wrong_sell = r2_sell[r2_sell["actual_side"] == "low"]
    out["rule2_wrong_side_swept_first"] = {
        "buy_continuation_but_AH_first": {"n": int(len(wrong_buy)), "of_rule2_buy_days": int(len(r2_buy))},
        "sell_continuation_but_AL_first": {"n": int(len(wrong_sell)), "of_rule2_sell_days": int(len(r2_sell))},
    }

    # Scenario 4: setup 1 (expanded) accuracy broken down by which source
    # fired -- today's live PDH/PDL break (1a, the original) vs yesterday's
    # unconfirmed wick against candle 2 (1b, the new source) -- to see
    # whether the expansion is pulling its weight or diluting the signal.
    def source_accuracy(sell_col, buy_col):
        d = feat[feat[sell_col] | feat[buy_col]].copy()
        d["_side"] = [combine_side(s, b) for s, b in zip(d[sell_col], d[buy_col])]
        return directional_accuracy(d, "_side")

    out["rule1_accuracy_by_source"] = {
        "1a_today_live_break": source_accuracy("setup1a_sell", "setup1a_buy"),
        "1b_yesterday_wick_vs_candle2_only": source_accuracy("setup1b_sell", "setup1b_buy"),
        "1_expanded_combined": directional_accuracy(feat, "predicted_side_setup1_expanded"),
    }

    # How often do setup 1 (expanded) and setup 2 (continuation) even
    # overlap on the same day, and when they do, do they agree or conflict?
    has1 = feat["predicted_side_setup1_expanded"].isin(["high", "low"])
    has2 = feat["predicted_side_setup2"].isin(["high", "low"])
    same = feat["predicted_side_setup1_expanded"] == feat["predicted_side_setup2"]
    out["rule1_rule2_overlap"] = {
        "both_fire_agree": int((has1 & has2 & same).sum()),
        "both_fire_conflict": int((has1 & has2 & ~same).sum()),
        "only_rule1_fires": int((has1 & ~has2).sum()),
        "only_rule2_fires": int((~has1 & has2).sum()),
        "neither_fires": int((~has1 & ~has2).sum()),
    }

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
    # setup 1's own mixed/agree, computed fresh here rather than reusing the
    # feat-level "mixed_day"/"agree_day" columns -- those are about the
    # setup1-OR-setup2 FUSED prediction, so now that setup 2 fires on ~40%
    # of days instead of ~1%, they no longer mean "setup 1 was mixed."
    feat = feat.copy()
    feat["split"] = feat["date"].apply(lambda d: "train" if d <= TRAIN_END else "test")
    feat["setup1_has_signal"] = feat["predicted_side_setup1"].isin(["high", "low"])
    feat["setup1_mixed"] = feat["setup1_has_signal"] & (feat["predicted_side_setup1"] != feat["actual_side"])

    accuracy_by_split = {}
    for split in ["train", "test"]:
        s = feat[feat["split"] == split]
        accuracy_by_split[split] = {
            "n_days": int(len(s)),
            "directional_accuracy_setup1": directional_accuracy(s, "predicted_side_setup1"),
            "mixed_day_rate_pct": round(float(s["setup1_mixed"].mean() * 100), 1),
        }

    # Second, separate question: on the days setup 1 correctly calls the
    # side, does the resulting move behave any differently -- specifically,
    # is it MORE or LESS likely to run the full distance to the opposite
    # Asian level -- than an ordinary day? Still no R-multiple: "reached
    # target" here just means "touched the opposite Asian level," a fixed
    # price landmark, not a chosen stop/target.
    m = rb.merge(feat[["date", "predicted_side_setup1", "setup1_mixed", "split"]], on="date", how="left")
    reach_by_signal = {}
    for split in ["train", "test", "all"]:
        s = m if split == "all" else m[m["split"] == split]
        agreed = s[(s["predicted_side_setup1"] == s["side"]) & (s["predicted_side_setup1"].isin(["high", "low"]))]
        reach_by_signal[split] = {
            "baseline_all_sweep_days": reach_group(s),
            "setup1_agreed": reach_group(agreed),
            "mixed_setup1_wrong": reach_group(s[s["setup1_mixed"] == True]),
            "no_signal": reach_group(s[s["predicted_side_setup1"] == "none"]),
        }

    return {"directional_accuracy_train_vs_test": accuracy_by_split, "reach_rate_by_signal": reach_by_signal}


def day_partition(feat, rb):
    """Every one of the 1,294 days, sorted into exactly one bucket -- not a
    prediction test, a behavioral census. "Yesterday vs candle 2" only ever
    lands in one of four states for a given day (engulfed / rule 2 /
    setup 1b / silent), so partitioning on that first and then splitting
    the "silent" remainder by whether setup 1a fired gives a clean,
    non-overlapping split of all five years."""
    feat = feat.copy()
    rb2 = rb.copy()
    feat["date"] = feat["date"].astype(str)
    rb2["date"] = rb2["date"].astype(str)
    m = feat.merge(rb2[["date", "reached_target"]], on="date", how="left")

    engulf = feat["yday_engulfs_d2"]
    rule2 = feat["setup2_sell"] | feat["setup2_buy"]
    oneb = feat["setup1b_sell"] | feat["setup1b_buy"]
    onea = feat["setup1a_sell"] | feat["setup1a_buy"]
    engine_b_silent = ~engulf & ~rule2 & ~oneb

    buckets = {
        "engulfed": engulf,
        "rule2_confirmed_continuation": rule2,
        "1b_unconfirmed_wick_vs_candle2": oneb,
        "1a_only_todays_price_vs_yesterday": engine_b_silent & onea,
        "nothing_fired": engine_b_silent & ~onea,
    }

    out = {}
    n = len(feat)
    for name, mask in buckets.items():
        d = m[mask]
        nd = len(d)
        reach = d["reached_target"]
        out[name] = {
            "n_days": int(nd),
            "rate_pct": round(nd / n * 100, 1),
            "actual_side_counts": {str(k): int(v) for k, v in d["actual_side"].value_counts(dropna=False).items()},
            "reach_rate_pct": round(float(reach.mean() * 100), 1) if reach.notna().sum() else None,
            "reach_rate_n": int(reach.notna().sum()),
        }
    assert sum(b["n_days"] for b in out.values()) == n
    return out


def rule1_rule2_conflict_detail(feat):
    """Elaborates the agree/conflict stat: on days where setup 1 (expanded)
    AND setup 2 both give a clean single-side call, which source inside
    setup 1 (1a or 1b) is actually driving it, and what direction pairing
    shows up."""
    has1 = feat["predicted_side_setup1"].isin(["high", "low"])
    has2 = feat["predicted_side_setup2"].isin(["high", "low"])
    both = feat[has1 & has2]

    def source(row):
        a = bool(row["setup1a_sell"] or row["setup1a_buy"])
        b = bool(row["setup1b_sell"] or row["setup1b_buy"])
        if a and b:
            return "both_1a_and_1b"
        if a:
            return "1a"
        if b:
            return "1b"
        return "neither"  # shouldn't happen given has1 is true

    src = both.apply(source, axis=1)
    pairs = both.groupby([both["predicted_side_setup1"], both["predicted_side_setup2"]]).size()
    return {
        "n_both_fire": int(len(both)),
        "source_of_setup1_side": {str(k): int(v) for k, v in src.value_counts().items()},
        "direction_pairs": {f"{a}_{b}": int(v) for (a, b), v in pairs.items()},
    }


def setup1_expanded_stability(feat):
    """Same train/test check as item 7, run on setup1_expanded (1a OR 1b)
    instead of the original 1a-only setup 1 -- does folding in source 1b
    hold up across both halves of history the way 1a alone does, or does it
    break the stability that made 1a convincing?"""
    feat = feat.copy()
    feat["split"] = feat["date"].apply(lambda d: "train" if d <= TRAIN_END else "test")
    out = {}
    for split in ["train", "test"]:
        s = feat[feat["split"] == split]
        out[split] = {
            "n_days": int(len(s)),
            "directional_accuracy_setup1_expanded": directional_accuracy(s, "predicted_side_setup1_expanded"),
        }
    return out


def setup2_stability(feat):
    """Same train/test check as setup 1, now run on the corrected setup 2
    (continuation) definition -- is its accuracy real, or a fluke of one
    stretch of history?"""
    feat = feat.copy()
    feat["split"] = feat["date"].apply(lambda d: "train" if d <= TRAIN_END else "test")
    out = {}
    for split in ["train", "test"]:
        s = feat[feat["split"] == split]
        out[split] = {
            "n_days": int(len(s)),
            "directional_accuracy_setup2": directional_accuracy(s, "predicted_side_setup2"),
        }
    return out


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
        "item8_rule2_corrected_and_conflict_scenarios": rule2_scenarios(feat),
        "item8_setup1_expanded_train_vs_test": setup1_expanded_stability(feat),
        "item8_setup2_train_vs_test": setup2_stability(feat),
        "item9_rule1_rule2_conflict_detail": rule1_rule2_conflict_detail(feat),
        "item9_day_partition": day_partition(feat, rb),
    }

    report_path = os.path.join(DERIVED, "daily_relationship_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote {report_path}")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
