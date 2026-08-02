"""Act on the pullback diagnosis: use retracement as the EXIT, not the entry.

diagnose_pullback.py showed the edge is concentrated in setups that never come
back: days where a 50% pullback never filled won 50.0% and made +50.1R, while
days that did pull back won 18.3% and lost -15.2R. Waiting for a better price
therefore discards the trades worth taking.

The direct consequence: if retracing predicts failure, the stop belongs at a
retracement of the confirmation leg -- close enough to eject the retracers
cheaply -- rather than under the sweep extreme, which is where a "structural"
stop would put it but which forces you to sit through the very behaviour that
predicts a loss.

Stop modes compared, all entering at market on the reclaim:

  extreme   -- under the sweep extreme (the structural stop used so far)
  retrace_k -- at k of the way back down the leg from its high to the sweep
               extreme; k=1.0 is the extreme itself, smaller k is tighter
  fixed_p   -- a flat pip distance, for reference

Selection on TRAIN, then rolling walk-forward with re-selection per fold.
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR
COST = 1.0


def simulate(ctx, p):
    long_ = ctx["side"] == "low"
    highs, lows, closes = ctx["highs"], ctx["lows"], ctx["closes"]
    level, opposite, arange = ctx["level"], ctx["opposite"], ctx["asian_range"]
    if not (p["min_range"] <= arange / PIP <= p["max_range"]) or len(closes) < 30:
        return None

    rec = closes > level if long_ else closes < level
    if not rec.any():
        return None
    c = int(np.argmax(rec))
    if c >= len(closes) - 5:
        return None

    extreme = lows[:c + 1].min() if long_ else highs[:c + 1].max()
    leg_end = highs[:c + 1].max() if long_ else lows[:c + 1].min()
    entry = closes[c] + COST * PIP if long_ else closes[c] - COST * PIP
    span = abs(leg_end - extreme)

    if p["stop_mode"] == "extreme":
        stop = extreme - p["buffer"] * PIP if long_ else extreme + p["buffer"] * PIP
    elif p["stop_mode"] == "fixed":
        stop = entry - p["fixed_pips"] * PIP if long_ else entry + p["fixed_pips"] * PIP
    else:  # retrace
        if span <= 0:
            return None
        stop = (leg_end - p["k"] * span) if long_ else (leg_end + p["k"] * span)

    risk = (entry - stop) if long_ else (stop - entry)
    if risk <= 0.5 * PIP:
        return None
    reward = (opposite - entry) if long_ else (entry - opposite)
    if reward <= 0:
        return None

    h, l = highs[c + 1:], lows[c + 1:]
    if len(h) == 0:
        return None
    if long_:
        i_s = int(np.argmax(l <= stop)) if (l <= stop).any() else None
        i_t = int(np.argmax(h >= opposite)) if (h >= opposite).any() else None
    else:
        i_s = int(np.argmax(h >= stop)) if (h >= stop).any() else None
        i_t = int(np.argmax(l <= opposite)) if (l <= opposite).any() else None

    if i_s is not None and (i_t is None or i_s <= i_t):
        r, outcome = -1.0, "LOSS"
    elif i_t is not None:
        r, outcome = reward / risk, "WIN"
    else:
        last = closes[-1]
        r = ((last - entry) if long_ else (entry - last)) / risk
        outcome = "WIN" if r > 0.05 else ("LOSS" if r < -0.05 else "BE")

    return {"date": ctx["date"], "outcome": outcome, "r_multiple": round(float(r), 3),
            "risk_pips": round(risk / PIP, 1), "reward_pips": round(reward / PIP, 1)}


def backtest(ctxs, p):
    return pd.DataFrame([t for c in ctxs for t in [simulate(c, p)] if t is not None])


def summarize(df):
    if df.empty or len(df) < 25:
        return None
    r = df["r_multiple"]
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    return {"n_trades": int(len(df)),
            "win_rate": round(float((df["outcome"] == "WIN").mean() * 100), 1),
            "expectancy_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "profit_factor": round(float(gw / gl), 2) if gl > 0 else None,
            "max_dd_r": round(float((eq.cummax() - eq).max()), 1),
            "avg_risk_pips": round(float(df["risk_pips"].mean()), 1),
            "avg_rr": round(float((df["reward_pips"] / df["risk_pips"]).mean()), 2)}


BASE = {"stop_mode": "extreme", "buffer": 3.0, "k": 0.5, "fixed_pips": 10,
        "min_range": 25, "max_range": 1e9}
KEYS = ["stop_mode", "k", "buffer", "fixed_pips", "min_range"]


def build_grid():
    g = []
    for mr in [0, 15, 25]:
        for b in [1.0, 3.0]:
            g.append(dict(BASE, stop_mode="extreme", buffer=b, min_range=mr))
        for k in [0.236, 0.382, 0.5, 0.618, 0.786]:
            g.append(dict(BASE, stop_mode="retrace", k=k, min_range=mr))
        for fp in [6, 8, 10, 14, 20]:
            g.append(dict(BASE, stop_mode="fixed", fixed_pips=fp, min_range=mr))
    return g


def select(ctxs, grid, min_trades=120, max_dd=15.0):
    rows = []
    for p in grid:
        s = summarize(backtest(ctxs, p))
        if s:
            rows.append({**{k: p[k] for k in KEYS}, **s, "_p": p})
    if not rows:
        return None, None, pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)
    elig = df[(df["n_trades"] >= min_trades) & (df["max_dd_r"] <= max_dd)]
    pick = (elig if not elig.empty else df).iloc[0]
    return pick["_p"], {k: pick[k] for k in KEYS + ["n_trades", "win_rate", "expectancy_r",
                                                    "profit_factor", "max_dd_r",
                                                    "avg_risk_pips", "avg_rr"]}, df


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    ctxs = opt.build_contexts(raw)
    train = [c for c in ctxs if c["date"] <= opt.TRAIN_END]
    test = [c for c in ctxs if c["date"] > opt.TRAIN_END]
    pd.set_option("display.width", 220)

    grid = build_grid()
    _, _, table = select(train, grid)
    show = KEYS + ["n_trades", "win_rate", "expectancy_r", "profit_factor",
                   "max_dd_r", "avg_risk_pips", "avg_rr"]
    print(f"=== Stop-placement grid on TRAIN ({len(grid)} configs, cost {COST} pip) ===")
    print(table[show].head(14).to_string(index=False))

    print("\n--- mean expectancy by stop mode ---")
    print(table.groupby("stop_mode")["expectancy_r"].agg(["mean", "max", "count"]).round(3).to_string())

    best, best_sum, _ = select(train, grid)
    print(f"\nSELECTED on TRAIN: { {k: best[k] for k in KEYS} }")
    print("TRAIN:", best_sum)
    print("\nTEST (2024-2025), one look:", summarize(backtest(test, best)))

    print("\n=== Walk-forward (re-select each fold) ===")
    folds, oos = [], []
    for cut in pd.date_range("2022-07-01", "2025-07-01", freq="6MS"):
        nxt = cut + pd.DateOffset(months=6)
        tr = [c for c in ctxs if c["date"] < cut]
        te = [c for c in ctxs if cut <= c["date"] < nxt]
        if len(tr) < 200 or len(te) < 30:
            continue
        cfg, _, _ = select(tr, grid)
        if cfg is None:
            continue
        df = backtest(te, cfg)
        if df.empty:
            continue
        r = df["r_multiple"]
        folds.append({"fold": str(cut.date()), **{k: cfg[k] for k in KEYS}, "n": int(len(df)),
                      "win_rate": round(float((df["outcome"] == "WIN").mean() * 100), 1),
                      "expectancy_r": round(float(r.mean()), 3),
                      "total_r": round(float(r.sum()), 1)})
        oos.append(df)
        f = folds[-1]
        print(f"  {f['fold']}  {cfg['stop_mode']}"
              f"{'' if cfg['stop_mode']!='retrace' else ' k='+str(cfg['k'])}"
              f"{'' if cfg['stop_mode']!='fixed' else ' '+str(cfg['fixed_pips'])+'p'}"
              f" range>={cfg['min_range']}  n={f['n']:3d} win={f['win_rate']:5.1f}% "
              f"exp={f['expectancy_r']:+.3f}R tot={f['total_r']:+.1f}R")

    wf = pd.concat(oos, ignore_index=True).sort_values("date") if oos else pd.DataFrame()
    wf_sum = summarize(wf) if not wf.empty else None
    print("\nPooled walk-forward out-of-sample:", wf_sum)
    if folds:
        print(f"Profitable folds: {sum(1 for f in folds if f['total_r'] > 0)}/{len(folds)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    table[show].to_csv(os.path.join(OUT_DIR, "retrace_stop_grid.csv"), index=False)
    if not wf.empty:
        wf.to_csv(os.path.join(OUT_DIR, "retrace_stop_wf_trades.csv"), index=False)
    with open(os.path.join(OUT_DIR, "retrace_stop_results.json"), "w") as f:
        json.dump({"selected": {k: best[k] for k in KEYS}, "train": best_sum,
                   "test": summarize(backtest(test, best)), "folds": folds,
                   "pooled_wf": wf_sum,
                   "by_mode": table.groupby("stop_mode")["expectancy_r"].mean().round(3).to_dict(),
                   "grid_top": table[show].head(14).to_dict(orient="records")},
                  f, indent=2, default=str)
    print("\nSaved retrace_stop_results.json")


if __name__ == "__main__":
    main()
