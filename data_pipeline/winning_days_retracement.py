"""Two follow-up questions on top of the 737 winning-day cohort:

1. Of the 530 days that did NOT reach target (would have been losses), how
   many still reclaimed back inside the Asian range vs never did? Contrasted
   with the 737 winning days, where the answer was already known to be 100%.

2. Restricted to ONLY the 737 winning days, run swing-high/swing-low
   detection on the 5-minute chart, exactly as in mss_retracement.py: after
   the sweep, MSS eventually confirms (guaranteed on these days, since they
   all reversed) using a broken swing as the "100%" reference (swing high
   for a down-MSS/short setup, swing low for an up-MSS/long setup mirrored),
   and a fresh extreme that follows it as the "0%" reference. Report the
   distribution of how deep price's pullback into that 0-100% leg actually
   reached on every one of these days, before continuing to target -- not a
   backtest, a pure measurement of retracement depth reached.
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_retracement import run_for_timeframe

DERIVED = os.path.join(os.path.dirname(__file__), "derived")


def reclaim_breakdown():
    df = pd.read_csv(os.path.join(DERIVED, "reversal_behavior_eurusd_2021_2025.csv"))
    out = {}
    for label, mask in [("won_737", df["reached_target"] == True), ("lost_530", df["reached_target"] == False)]:
        d = df[mask]
        row = {"n": int(len(d)), "reclaimed": int(d["reclaimed"].sum()), "not_reclaimed": int((~d["reclaimed"]).sum())}
        row["reclaim_pct"] = round(row["reclaimed"] / row["n"] * 100, 1)
        by_side = {}
        for side in ["high", "low"]:
            s = d[d["side"] == side]
            by_side[side] = {"n": int(len(s)), "reclaimed": int(s["reclaimed"].sum()), "not_reclaimed": int((~s["reclaimed"]).sum())}
        row["by_side"] = by_side
        out[label] = row
    return out


def pct_stats(x):
    x = np.asarray(x, dtype=float)
    return {
        "n": int(len(x)), "mean": round(float(np.mean(x)), 1), "median": round(float(np.median(x)), 1),
        "p10": round(float(np.percentile(x, 10)), 1), "p25": round(float(np.percentile(x, 25)), 1),
        "p75": round(float(np.percentile(x, 75)), 1), "p90": round(float(np.percentile(x, 90)), 1),
        "min": round(float(np.min(x)), 1), "max": round(float(np.max(x)), 1),
    }


def retracement_on_winning_days():
    raw = opt.load_raw("eurusd", 2021, 2025)
    won = pd.read_csv(os.path.join(DERIVED, "reversal_behavior_eurusd_2021_2025.csv"))
    won = won[won["reached_target"] == True]
    won_dates = set(won["date"].astype(str))
    n_target = len(won_dates)

    legs = run_for_timeframe(raw, "5min")
    ldf = pd.DataFrame(legs)
    ldf["date"] = ldf["date"].astype(str)
    ldf = ldf[ldf["date"].isin(won_dates)].copy()

    out = {"n_winning_days": n_target, "n_with_mss_leg_measured": int(len(ldf))}
    edges = [-1e9, 0, 25, 50, 75, 100, 1e9]
    labels = ["<0% (never pulled back)", "0-25%", "25-50%", "50-75%", "75-100%", ">100% (all the way to stop)"]

    for side, direction, desc in [("high", "short", "swept high -> MSS down (0%=fresh low, 100%=prior swing high)"),
                                  ("low", "long", "swept low -> MSS up (0%=fresh high, 100%=prior swing low)")]:
        s = ldf[ldf["side"] == side]
        vals = s["max_retrace_pct"].values
        bucket_counts = pd.cut(vals, bins=edges, labels=labels).value_counts().reindex(labels).fillna(0).astype(int)
        out[side] = {
            "desc": desc, "n": int(len(s)),
            "coverage_pct_of_side_total": round(len(s) / len(won[won["side"] == side]) * 100, 1),
            "stats": pct_stats(vals),
            "histogram": {"labels": labels, "counts": [int(c) for c in bucket_counts.values]},
        }
    return out


def main():
    report = {"reclaim_breakdown": reclaim_breakdown(), "retracement_on_winning_days": retracement_on_winning_days()}
    path = os.path.join(DERIVED, "winning_days_retracement_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
