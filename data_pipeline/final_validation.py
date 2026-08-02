"""Final validation: fixed-split TEST + rolling walk-forward analysis.

Two independent checks on the configuration the TRAIN grids pointed to:

  A. Fixed split -- select on 2021-2023 by a rule stated before looking at
     TEST (>=150 trades, max drawdown <=15R, then highest expectancy), then
     evaluate once on 2024-2025.

  B. Walk-forward -- re-select parameters inside each rolling window and trade
     only the following 6 months, repeatedly. Every trade collected this way
     was taken with parameters chosen without seeing it. This is the check
     that actually catches curve-fitting: a config that only works because it
     was tuned on the same data will fall apart once each fold has to re-pick
     its own parameters and trade forward blind.

Execution cost is charged on every trade (optimize_strategy.COST_PIPS).
"""
import itertools
import json
import os

import pandas as pd

import optimize_strategy as opt

OUT_DIR = opt.OUT_DIR

# Focused grid, informed by the earlier exploration -- deliberately small so
# each walk-forward fold selects from few candidates (a big grid inside a fold
# just re-imports the overfitting the walk-forward is meant to detect).
GRID = [dict(opt.BASE, entry=e, stop_mode="beyond_level", stop_pips=sp,
             target_frac=tf, min_range=mr)
        for e, sp, tf, mr in itertools.product(
            ["reclaim", "immediate"], [8, 12, 15, 20], [1.0, 1.5, 2.0], [0, 15, 25])]

KEYS = ["entry", "stop_pips", "target_frac", "min_range"]


def select(contexts, grid=GRID, min_trades=150, max_dd=15.0):
    """Apply the fixed selection rule. Returns (config, summary, table)."""
    rows = []
    for p in grid:
        s = opt.summarize(opt.backtest(contexts, p))
        if s:
            rows.append({**{k: p[k] for k in KEYS}, **s, "_p": p})
    if not rows:
        return None, None, pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)
    elig = df[(df["n_trades"] >= min_trades) & (df["max_dd_r"] <= max_dd)]
    pick = (elig if not elig.empty else df).iloc[0]
    return pick["_p"], {k: pick[k] for k in KEYS + ["n_trades", "win_rate", "expectancy_r",
                                                    "profit_factor", "max_dd_r", "avg_rr"]}, df


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    contexts = opt.build_contexts(raw)
    train = [c for c in contexts if c["date"] <= opt.TRAIN_END]
    test = [c for c in contexts if c["date"] > opt.TRAIN_END]
    pd.set_option("display.width", 220)
    print(f"setup days: {len(contexts)} | TRAIN {len(train)} | TEST {len(test)} "
          f"| cost {opt.COST_PIPS} pip\n")

    # ---------- A. fixed split ----------
    best, best_sum, table = select(train)
    print("=== A. Fixed split ===")
    print("Selected on TRAIN:", {k: best[k] for k in KEYS})
    print("TRAIN:", best_sum)

    nb = table[(table["entry"] == best["entry"]) & (table["target_frac"] == best["target_frac"]) &
               (table["min_range"] == best["min_range"])]
    print("\nPlateau check (stop distance swept, all else fixed):")
    print(nb[["stop_pips", "n_trades", "win_rate", "expectancy_r", "profit_factor",
              "max_dd_r"]].sort_values("stop_pips").to_string(index=False))

    test_trades = opt.backtest(test, best)
    test_sum = opt.summarize(test_trades)
    print("\nTEST (2024-2025), evaluated once:", test_sum)

    # ---------- B. walk-forward ----------
    print("\n=== B. Walk-forward (re-select each fold, trade the next 6 months blind) ===")
    folds, oos = [], []
    boundaries = pd.date_range("2022-07-01", "2025-07-01", freq="6MS")
    for cut in boundaries:
        nxt = cut + pd.DateOffset(months=6)
        tr = [c for c in contexts if c["date"] < cut]
        te = [c for c in contexts if cut <= c["date"] < nxt]
        if len(tr) < 200 or len(te) < 30:
            continue
        cfg, cfg_sum, _ = select(tr)
        if cfg is None:
            continue
        trades = opt.backtest(te, cfg)
        s = opt.summarize(trades)
        if s is None and not trades.empty:  # small fold: summarize needs >=20 trades
            r = trades["r_multiple"]
            s = {"n_trades": len(trades), "win_rate": round(float((trades["outcome"] == "WIN").mean() * 100), 1),
                 "expectancy_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1)}
        if s is None:
            continue
        folds.append({"fold_start": str(cut.date()), "fold_end": str(nxt.date()),
                      "train_days": len(tr), **{k: cfg[k] for k in KEYS},
                      "oos_n": s["n_trades"], "oos_win_rate": s["win_rate"],
                      "oos_expectancy_r": s["expectancy_r"], "oos_total_r": s["total_r"]})
        oos.append(trades)
        print(f"  {cut.date()} -> {nxt.date()}  cfg={ {k: cfg[k] for k in KEYS} }  "
              f"n={s['n_trades']:3d} win={s['win_rate']:5.1f}% exp={s['expectancy_r']:+.3f}R "
              f"total={s['total_r']:+.1f}R")

    wf = pd.concat(oos, ignore_index=True).sort_values("date") if oos else pd.DataFrame()
    wf_sum = opt.summarize(wf) if not wf.empty else None
    print("\nAll walk-forward out-of-sample trades pooled:", wf_sum)
    if wf_sum:
        pos = sum(1 for f in folds if f["oos_total_r"] > 0)
        print(f"Profitable folds: {pos}/{len(folds)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    if not wf.empty:
        wf.to_csv(os.path.join(OUT_DIR, "walkforward_trades.csv"), index=False)
    test_trades.to_csv(os.path.join(OUT_DIR, "final_test_trades.csv"), index=False)
    opt.backtest(train, best).to_csv(os.path.join(OUT_DIR, "final_train_trades.csv"), index=False)
    with open(os.path.join(OUT_DIR, "final_validation.json"), "w") as f:
        json.dump({"cost_pips": opt.COST_PIPS,
                   "selected_config": {k: best[k] for k in KEYS},
                   "train_summary": best_sum, "test_summary": test_sum,
                   "plateau": nb[["stop_pips", "n_trades", "win_rate", "expectancy_r",
                                  "profit_factor", "max_dd_r"]].sort_values("stop_pips")
                                 .to_dict(orient="records"),
                   "walkforward_folds": folds, "walkforward_pooled": wf_sum},
                  f, indent=2, default=str)
    print("\nSaved final_validation.json, walkforward_trades.csv, final_{train,test}_trades.csv")


if __name__ == "__main__":
    main()
