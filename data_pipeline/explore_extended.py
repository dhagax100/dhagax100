"""Second-stage exploration, TRAIN only, after the first grid came back flat.

Two questions the first grid could not answer:

  1. How sensitive is the result to execution cost? The first grid showed a
     healthy edge at zero cost and none at 1 pip -- so the exact break-even
     cost is the single most decision-relevant number here.

  2. Is the edge capped by the target? Targeting the opposite Asian level caps
     reward at roughly one Asian range (median 17 pips), so a stop wide enough
     to survive the sweep forces reward:risk below 1. Letting the target run
     past the opposite level removes that cap -- worth testing before
     concluding the setup itself has no edge.

Everything here runs on TRAIN (2021-2023) only.
"""
import itertools
import os

import pandas as pd

import optimize_strategy as opt

OUT_DIR = opt.OUT_DIR


def run(contexts, p, cost):
    original = opt.COST_PIPS
    opt.COST_PIPS = cost
    try:
        return opt.summarize(opt.backtest(contexts, p))
    finally:
        opt.COST_PIPS = original


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    contexts = opt.build_contexts(raw)
    train = [c for c in contexts if c["date"] <= opt.TRAIN_END]
    print(f"TRAIN setup days: {len(train)}\n")
    pd.set_option("display.width", 220)

    # ---- 1. cost sensitivity -------------------------------------------------
    probes = {
        "immediate 8p stop, full target": dict(opt.BASE, entry="immediate",
                                               stop_mode="beyond_level", stop_pips=8, target_frac=1.0),
        "reclaim 12p stop, full target": dict(opt.BASE, entry="reclaim",
                                              stop_mode="beyond_level", stop_pips=12, target_frac=1.0),
        "immediate 25p stop, full target": dict(opt.BASE, entry="immediate",
                                                stop_mode="beyond_level", stop_pips=25, target_frac=1.0),
    }
    rows = []
    for name, p in probes.items():
        for cost in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0]:
            s = run(train, p, cost)
            if s:
                rows.append({"config": name, "cost_pips": cost, **s})
    cost_df = pd.DataFrame(rows)
    print("=== COST SENSITIVITY (TRAIN) ===")
    print(cost_df[["config", "cost_pips", "n_trades", "win_rate", "expectancy_r",
                   "profit_factor", "max_dd_r"]].to_string(index=False))
    cost_df.to_csv(os.path.join(OUT_DIR, "cost_sensitivity_train.csv"), index=False)

    # ---- 2. can a bigger target escape the Asian-range reward cap? -----------
    rows = []
    for entry, stop_pips, tf, min_range in itertools.product(
            ["immediate", "reclaim"], [8, 12, 15, 20],
            [1.0, 1.5, 2.0, 3.0], [0, 15, 20, 25]):
        p = dict(opt.BASE, entry=entry, stop_mode="beyond_level", stop_pips=stop_pips,
                 target_frac=tf, min_range=min_range)
        s = run(train, p, 1.0)
        if s:
            rows.append({"entry": entry, "stop_pips": stop_pips, "target_frac": tf,
                         "min_range": min_range, **s})
    ext = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)
    print("\n=== EXTENDED TARGETS + ASIAN-RANGE FILTER (TRAIN, cost 1.0 pip) ===")
    print("--- top 15 by expectancy ---")
    print(ext.head(15).to_string(index=False))
    print("\n--- of those, ones with maxDD <= 15R and n >= 150 ---")
    good = ext[(ext["max_dd_r"] <= 15) & (ext["n_trades"] >= 150)]
    print(good.head(10).to_string(index=False) if not good.empty else "  (none)")
    ext.to_csv(os.path.join(OUT_DIR, "extended_grid_train.csv"), index=False)
    print("\nSaved cost_sensitivity_train.csv, extended_grid_train.csv")


if __name__ == "__main__":
    main()
