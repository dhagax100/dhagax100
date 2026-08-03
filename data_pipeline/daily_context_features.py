"""Does yesterday's price action predict whether today's sweep reaches
full target?

Two daily-level features, computed for every clean sweep day, mirrored by
side (sell-context = swept the Asian high, expects a fall to target;
buy-context = swept the Asian low, expects a rise to target):

1. "Yesterday's extreme taken": for a sell-context day, did TODAY's own
   price (from the Asian session open through the sweep moment) trade above
   YESTERDAY's full daily high? For a buy-context day, below yesterday's
   daily low? If yes, was that first done during the Asian session window
   (20:00 prior day - 00:00 today) or afterward (00:00 today through the
   sweep moment, which covers the gap hour plus the London killzone)?

   Definition of "yesterday": the complete previous CALENDAR day (00:00-
   24:00), same convention as derived/daily_ohlc_*.csv. Caveat, stated
   plainly: the Asian session (20:00-24:00 of that same calendar day) is
   itself part of "yesterday"'s 24-hour candle, so checking the Asian
   session against yesterday's FULL-day high has a mild look-ahead flavor
   for that specific overlap window (in true real time you would not yet
   know yesterday's final high during yesterday's own evening). This is a
   research/exploratory measurement, not a live-tradeable rule as stated.

2. "Yesterday's close vs the day before": did yesterday's daily candle
   close higher (bullish) or lower (bearish) than the day-before-
   yesterday's close?

Both are cross-tabbed against the already-known outcome split: reached
target (part of the 737) vs did not (part of the 530).
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt

DERIVED = os.path.join(os.path.dirname(__file__), "derived")
ASIAN_START_H = 20


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    daily = pd.read_csv(os.path.join(DERIVED, "daily_ohlc_eurusd_2021_2025.csv"), parse_dates=["ts"])
    daily = daily.set_index(daily["ts"].dt.date).sort_index()
    avail_dates = daily.index.to_numpy()  # sorted, ONLY days with actual trading data (no Saturdays)

    rb = pd.read_csv(os.path.join(DERIVED, "reversal_behavior_eurusd_2021_2025.csv"), parse_dates=["date"])
    rb["date"] = rb["date"].dt.date

    import bisect

    def prior_trading_days(day, n):
        """The n most recent AVAILABLE trading days strictly before `day`,
        skipping Saturdays (and any other day with zero trading data) --
        not a fixed calendar-day offset, which would wrongly skip Mondays
        (whose "day before yesterday" would otherwise land on a data-less
        Saturday) out of the analysis entirely."""
        pos = bisect.bisect_left(avail_dates, day)
        if pos < n:
            return None
        return [avail_dates[pos - k] for k in range(1, n + 1)]

    rows = []
    n_dropped_no_history = 0
    for _, r in rb.iterrows():
        day = r["date"]
        prior = prior_trading_days(day, 2)
        if prior is None:
            n_dropped_no_history += 1
            continue
        yday, dby = prior[0], prior[1]
        y = daily.loc[yday]
        d2 = daily.loc[dby]

        asian_start = pd.Timestamp(day) - pd.Timedelta(hours=24 - ASIAN_START_H)
        today_start = pd.Timestamp(day)
        sweep_time = pd.Timestamp(day) + pd.to_timedelta(r["sweep_time"] + ":00")

        pre = raw.loc[asian_start:sweep_time]
        asian_part = raw.loc[asian_start:today_start - pd.Timedelta(seconds=1)]
        london_part = raw.loc[today_start:sweep_time]

        if r["side"] == "high":
            level = y["high"]
            taken_asian = (asian_part["high"] > level).any() if len(asian_part) else False
            taken_london = (london_part["high"] > level).any() if len(london_part) else False
        else:
            level = y["low"]
            taken_asian = (asian_part["low"] < level).any() if len(asian_part) else False
            taken_london = (london_part["low"] < level).any() if len(london_part) else False

        if taken_asian:
            when = "asian"
        elif taken_london:
            when = "london"
        else:
            when = "never"

        if y["close"] > d2["close"]:
            yclose = "bullish"
        elif y["close"] < d2["close"]:
            yclose = "bearish"
        else:
            yclose = "flat"

        rows.append({
            "date": day, "side": r["side"], "reached_target": r["reached_target"],
            "asian_range_pips": r["asian_range_pips"],
            "yesterday_extreme_taken_when": when,
            "yesterday_close_vs_daybefore": yclose,
        })

    df = pd.DataFrame(rows)
    print(f"Days with usable yesterday+day-before data: {len(df)} (of {len(rb)} total clean sweep days, "
          f"{n_dropped_no_history} dropped for not having 2 prior trading days yet -- only happens near the very start of the 2021-2025 sample)")

    out = {"n_days_usable": len(df), "n_dropped_no_history": n_dropped_no_history, "sides": {}}
    for side, label in [("high", "sell-context (swept Asian high)"), ("low", "buy-context (swept Asian low)")]:
        s = df[df["side"] == side]
        won = s[s["reached_target"] == True]
        lost = s[s["reached_target"] == False]

        def rate_table(col):
            tab = pd.crosstab(s[col], s["reached_target"])
            tab["reach_rate_pct"] = (tab.get(True, 0) / (tab.get(True, 0) + tab.get(False, 0)) * 100).round(1)
            return tab

        print(f"\n=== {label} ===  n={len(s)}  (won={len(won)}, lost={len(lost)}, baseline reach rate={len(won)/len(s)*100:.1f}%)")
        t1 = rate_table("yesterday_extreme_taken_when")
        print("\nWhen was yesterday's extreme taken (relative to reach rate):")
        print(t1)
        t2 = rate_table("yesterday_close_vs_daybefore")
        print("\nYesterday's close vs day-before (relative to reach rate):")
        print(t2)

        out["sides"][side] = {
            "label": label, "n": int(len(s)), "n_won": int(len(won)), "n_lost": int(len(lost)),
            "baseline_reach_rate_pct": round(len(won) / len(s) * 100, 1),
            "extreme_taken_when": {
                str(k): {"won": int(v.get(True, 0)), "lost": int(v.get(False, 0)),
                        "reach_rate_pct": round(float(v.get(True, 0) / (v.get(True, 0) + v.get(False, 0)) * 100), 1) if (v.get(True, 0) + v.get(False, 0)) > 0 else None}
                for k, v in s.groupby("yesterday_extreme_taken_when")["reached_target"].value_counts().unstack(fill_value=0).iterrows()
            },
            "close_vs_daybefore": {
                str(k): {"won": int(v.get(True, 0)), "lost": int(v.get(False, 0)),
                        "reach_rate_pct": round(float(v.get(True, 0) / (v.get(True, 0) + v.get(False, 0)) * 100), 1) if (v.get(True, 0) + v.get(False, 0)) > 0 else None}
                for k, v in s.groupby("yesterday_close_vs_daybefore")["reached_target"].value_counts().unstack(fill_value=0).iterrows()
            },
        }

    df.to_csv(os.path.join(DERIVED, "daily_context_features.csv"), index=False)
    with open(os.path.join(DERIVED, "daily_context_features_report.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved daily_context_features.csv + report.json")


if __name__ == "__main__":
    main()
