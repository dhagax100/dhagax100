"""Comprehensive behavioural characterization of the 737 days where a
sweep of one Asian session side went on to reach the opposite side
(the "winning" cohort already identified in analyze_reversal_behavior.py).

Answers, split by sweep direction (high-swept -> falls to target,
low-swept -> rises to target):
  - how many pips price runs BEYOND the swept level before it turns
    (the overshoot / excursion -- the "how far up before down" question)
  - that overshoot normalized against the night's own Asian range
  - the full up-and-down extent of the move (opposite extreme to overshoot
    extreme) as one number
  - how long the overshoot takes, and how long the reversal leg to target
    then takes
  - how many separate pokes past the level happen before the final turn
  - how often and how fast price reclaims back inside the Asian range

Pure measurement -- no strategy rule chosen here. Output feeds a dashboard.
"""
import json
import os

import numpy as np
import pandas as pd

DERIVED = os.path.join(os.path.dirname(__file__), "derived")


def pct(a, q):
    return float(np.percentile(a, q))


def describe_group(s):
    x = s.dropna().values.astype(float)
    return {
        "n": int(len(x)),
        "mean": round(float(np.mean(x)), 2),
        "median": round(pct(x, 50), 2),
        "p10": round(pct(x, 10), 2),
        "p25": round(pct(x, 25), 2),
        "p75": round(pct(x, 75), 2),
        "p90": round(pct(x, 90), 2),
        "p95": round(pct(x, 95), 2),
        "min": round(float(np.min(x)), 2),
        "max": round(float(np.max(x)), 2),
        "std": round(float(np.std(x)), 2),
    }


def bucket_counts(x, edges):
    labels = []
    counts = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        lbl = f"{lo}-{hi}p" if hi < 10**8 else f"{lo}p+"
        labels.append(lbl)
        mask = (x >= lo) & (x < hi)
        counts.append(int(mask.sum()))
    return labels, counts


def main():
    df = pd.read_csv(os.path.join(DERIVED, "reversal_behavior_eurusd_2021_2025.csv"))
    sess = pd.read_csv(os.path.join(DERIVED, "asian_london_sessions_eurusd_2021_2025.csv"))
    w = df[df["reached_target"] == True].copy()
    assert len(w) == 737, f"expected 737 winning days, got {len(w)}"

    w["total_swing_pips"] = w["asian_range_pips"] + w["excursion_beyond_level_pips"]

    sess = sess.rename(columns={"date": "date"})
    merged = w.merge(sess[["date", "mfe_pips", "mae_pips", "sweep_depth_pips"]], on="date", how="left")

    out = {"n_total": 737, "sides": {}}

    for side, label in [("high", "swept high -> fell to target (short setups)"),
                        ("low", "swept low -> rose to target (long setups)")]:
        s = merged[merged["side"] == side]
        metrics = {
            "label": label,
            "n": int(len(s)),
            "pct_of_737": round(len(s) / 737 * 100, 1),
            "overshoot_pips": describe_group(s["excursion_beyond_level_pips"]),
            "overshoot_pct_of_asian_range": describe_group(s["excursion_pct_of_asian_range"]),
            "total_swing_pips": describe_group(s["total_swing_pips"]),
            "asian_range_pips": describe_group(s["asian_range_pips"]),
            "minutes_to_turn": describe_group(s["minutes_sweep_to_turn"]),
            "minutes_turn_to_target": describe_group(s["minutes_turn_to_target"]),
            "n_pokes": describe_group(s["n_pokes"]),
            "reclaim_rate_pct": round(float(s["reclaimed"].mean() * 100), 1),
            "minutes_to_reclaim_given_reclaimed": describe_group(s.loc[s["reclaimed"] == True, "minutes_sweep_to_reclaim"]),
            "corr_overshoot_vs_asian_range": round(float(np.corrcoef(s["excursion_beyond_level_pips"], s["asian_range_pips"])[0, 1]), 3),
        }
        edges = [0, 5, 10, 15, 25, 40, 10**9]
        labels, counts = bucket_counts(s["excursion_beyond_level_pips"].values, edges)
        metrics["overshoot_histogram"] = {"labels": labels, "counts": counts}
        out["sides"][side] = metrics

    out_path = os.path.join(DERIVED, "winning_days_characterization.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {out_path}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
