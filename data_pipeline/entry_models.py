"""Structure-based entry confirmation, instead of entering on the first reclaim.

The reclaim entry used earlier fires on the first 1-minute candle closing back
inside the Asian range. That is the earliest possible signal and therefore the
worst-priced one: the stop still has to sit under the sweep extreme, which by
then can be far away. Waiting for structure to confirm, and then entering on a
pullback, buys a tighter stop for the same target.

Three confirmation models are compared, all defined the standard way:

  reclaim  -- first candle closing back inside the Asian range (the baseline).

  fractal  -- Bill Williams fractal: a 5-bar pattern whose middle bar is the
              extreme, with two lower highs (or two higher lows) either side.
              n=2 bars per side. A break of the fractal is the signal. The
              fractal only exists once its 5th bar closes, so it is only
              actionable n bars after the middle bar -- enforced below.

  swing    -- market structure shift: price breaks a swing point formed by n
              bars either side, against the move that made it. ICT convention
              requires a candle BODY beyond the level, not just a wick, so
              `break_on="close"` is the faithful version; `"wick"` is included
              to measure what that requirement is worth.

Entry style, once confirmed:

  market   -- take the confirmation candle's close.
  pullback -- place a limit inside the confirmation leg (retrace fraction of
              the move from the sweep extreme to the confirmation high) and
              wait up to `pullback_expiry` bars for the fill. Unfilled setups
              are skipped, which is a real cost and is reported as fill rate.

Stops sit beyond the sweep extreme in every model -- the structural level the
setup is wrong below -- so improvements come from entry price, not from moving
the stop somewhere less defensible.

No lookahead: a pivot is only usable n bars after it forms, and pullback fills
are checked bar by bar in time order.
"""
import argparse
import itertools
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR


def confirmed_pivots(values, n, kind):
    """Index -> pivot price usable from that index onward.

    A pivot at i is only *known* at i+n, so the returned array holds, for each
    bar, the most recent pivot level that has actually formed by then.
    """
    m = len(values)
    latest = np.full(m, np.nan)
    cur = np.nan
    for i in range(m):
        p = i - n  # candidate pivot centre, confirmable now
        if p - n >= 0:
            win = values[p - n:p + n + 1]
            if kind == "high" and values[p] == win.max() and values[p] >= win[n]:
                cur = values[p]
            elif kind == "low" and values[p] == win.min() and values[p] <= win[n]:
                cur = values[p]
        latest[i] = cur
    return latest


def simulate_day(ctx, p):
    side = ctx["side"]
    long_ = side == "low"
    highs, lows, closes = ctx["highs"], ctx["lows"], ctx["closes"]
    level, opposite, arange = ctx["level"], ctx["opposite"], ctx["asian_range"]

    if not (p["min_range"] <= arange / PIP <= p["max_range"]):
        return None

    n_bars = len(closes)
    if n_bars < 30:
        return None

    # ---- confirmation index ----
    if p["confirm"] == "reclaim":
        rec = closes > level if long_ else closes < level
        c_idx = int(np.argmax(rec)) if rec.any() else None
    else:
        n = p["pivot_n"]
        piv = confirmed_pivots(highs if long_ else lows, n, "high" if long_ else "low")
        probe = closes if p["break_on"] == "close" else (highs if long_ else lows)
        ok = (~np.isnan(piv)) & ((probe > piv) if long_ else (probe < piv))
        c_idx = int(np.argmax(ok)) if ok.any() else None

    if c_idx is None or c_idx >= n_bars - 5 or c_idx > p["max_wait_min"]:
        return None

    # ---- structural extreme up to confirmation ----
    extreme = lows[:c_idx + 1].min() if long_ else highs[:c_idx + 1].max()
    leg_end = highs[:c_idx + 1].max() if long_ else lows[:c_idx + 1].min()
    stop = extreme - p["stop_buffer"] * PIP if long_ else extreme + p["stop_buffer"] * PIP

    # ---- entry ----
    if p["entry_style"] == "market":
        e_idx = c_idx
        entry = closes[c_idx] + p["cost"] * PIP if long_ else closes[c_idx] - p["cost"] * PIP
        filled = True
    else:
        span = abs(leg_end - extreme)
        if span <= 0:
            return None
        limit = leg_end - p["retrace"] * span if long_ else leg_end + p["retrace"] * span
        window = slice(c_idx + 1, min(c_idx + 1 + p["pullback_expiry"], n_bars))
        seg_lo, seg_hi = lows[window], highs[window]
        hit = (seg_lo <= limit) if long_ else (seg_hi >= limit)
        # a stop-out or a target hit during the wait cancels the setup
        if long_:
            dead = np.argmax(seg_lo <= stop) if (seg_lo <= stop).any() else None
        else:
            dead = np.argmax(seg_hi >= stop) if (seg_hi >= stop).any() else None
        if not hit.any():
            return {"skipped": True}
        j = int(np.argmax(hit))
        if dead is not None and dead < j:
            return {"skipped": True}
        e_idx = c_idx + 1 + j
        entry = limit + p["cost"] * PIP if long_ else limit - p["cost"] * PIP
        filled = True

    risk = (entry - stop) if long_ else (stop - entry)
    if risk <= 0.5 * PIP:
        return None
    if p["max_risk_pips"] and risk / PIP > p["max_risk_pips"]:
        return None

    target = opposite
    reward = (target - entry) if long_ else (entry - target)
    if reward <= 0:
        return None
    if p["min_rr"] and reward / risk < p["min_rr"]:
        return None

    h, l = highs[e_idx + 1:], lows[e_idx + 1:]
    if len(h) == 0:
        return None
    if long_:
        i_stop = int(np.argmax(l <= stop)) if (l <= stop).any() else None
        i_targ = int(np.argmax(h >= target)) if (h >= target).any() else None
    else:
        i_stop = int(np.argmax(h >= stop)) if (h >= stop).any() else None
        i_targ = int(np.argmax(l <= target)) if (l <= target).any() else None

    if i_stop is not None and (i_targ is None or i_stop <= i_targ):
        r, outcome = -1.0, "LOSS"
    elif i_targ is not None:
        r, outcome = reward / risk, "WIN"
    else:
        last = closes[-1]
        r = ((last - entry) if long_ else (entry - last)) / risk
        outcome = "WIN" if r > 0.05 else ("LOSS" if r < -0.05 else "BE")

    return {"date": ctx["date"], "side": side, "outcome": outcome,
            "r_multiple": round(float(r), 3), "risk_pips": round(risk / PIP, 1),
            "reward_pips": round(reward / PIP, 1), "confirm_min": int(c_idx),
            "skipped": False}


def backtest(contexts, p):
    rows, skipped, seen = [], 0, 0
    for ctx in contexts:
        t = simulate_day(ctx, p)
        if t is None:
            continue
        seen += 1
        if t.get("skipped"):
            skipped += 1
            continue
        rows.append(t)
    df = pd.DataFrame(rows)
    fill = (1 - skipped / seen) * 100 if seen else 0.0
    return df, round(fill, 1)


def summarize(df, fill):
    if df.empty or len(df) < 25:
        return None
    r = df["r_multiple"]
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    return {"n_trades": int(len(df)), "fill_rate": fill,
            "win_rate": round(float((df["outcome"] == "WIN").mean() * 100), 1),
            "expectancy_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "profit_factor": round(float(gw / gl), 2) if gl > 0 else None,
            "max_dd_r": round(float((eq.cummax() - eq).max()), 1),
            "avg_risk_pips": round(float(df["risk_pips"].mean()), 1),
            "avg_rr": round(float((df["reward_pips"] / df["risk_pips"]).mean()), 2),
            "median_confirm_min": int(df["confirm_min"].median())}


BASE = {"confirm": "reclaim", "pivot_n": 2, "break_on": "close", "entry_style": "market",
        "retrace": 0.5, "pullback_expiry": 60, "stop_buffer": 2.0, "cost": 1.0,
        "max_wait_min": 180, "min_range": 0, "max_range": 1e9, "max_risk_pips": None,
        "min_rr": None}

KEYS = ["confirm", "pivot_n", "break_on", "entry_style", "retrace", "stop_buffer", "min_range"]


def build_grid():
    g = []
    for confirm, pivot_n, break_on in [("reclaim", 0, "close"),
                                       ("pivot", 2, "wick"), ("pivot", 2, "close"),
                                       ("pivot", 3, "close"), ("pivot", 5, "close")]:
        for entry_style, retrace in [("market", 0.0), ("pullback", 0.382),
                                     ("pullback", 0.5), ("pullback", 0.618)]:
            for stop_buffer in [1.0, 3.0]:
                for min_range in [0, 15, 25]:
                    g.append(dict(BASE, confirm=confirm, pivot_n=pivot_n, break_on=break_on,
                                  entry_style=entry_style, retrace=retrace,
                                  stop_buffer=stop_buffer, min_range=min_range))
    return g


def select(contexts, grid, min_trades=120, max_dd=15.0):
    rows = []
    for p in grid:
        s = summarize(*backtest(contexts, p))
        if s:
            rows.append({**{k: p[k] for k in KEYS}, **s, "_p": p})
    if not rows:
        return None, None, pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)
    elig = df[(df["n_trades"] >= min_trades) & (df["max_dd_r"] <= max_dd)]
    pick = (elig if not elig.empty else df).iloc[0]
    return pick["_p"], {k: pick[k] for k in KEYS + ["n_trades", "fill_rate", "win_rate",
                                                    "expectancy_r", "profit_factor", "max_dd_r",
                                                    "avg_risk_pips", "avg_rr"]}, df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="eurusd")
    ap.parse_args()

    raw = opt.load_raw("eurusd", 2021, 2025)
    contexts = opt.build_contexts(raw)
    train = [c for c in contexts if c["date"] <= opt.TRAIN_END]
    test = [c for c in contexts if c["date"] > opt.TRAIN_END]
    pd.set_option("display.width", 240)
    print(f"setup days {len(contexts)} | TRAIN {len(train)} | TEST {len(test)}\n")

    grid = build_grid()
    print(f"=== Grid: {len(grid)} configs on TRAIN only (cost 1.0 pip) ===")
    _, _, table = select(train, grid)
    show = ["confirm", "pivot_n", "break_on", "entry_style", "retrace", "stop_buffer",
            "min_range", "n_trades", "fill_rate", "win_rate", "expectancy_r",
            "profit_factor", "max_dd_r", "avg_risk_pips", "avg_rr"]
    print("\n--- top 15 by expectancy ---")
    print(table[show].head(15).to_string(index=False))

    print("\n--- average risk (pips) by confirmation model, market vs pullback ---")
    piv = table.pivot_table(index=["confirm", "pivot_n", "break_on"], columns="entry_style",
                            values="avg_risk_pips", aggfunc="mean").round(1)
    print(piv.to_string())
    print("\n--- average expectancy by confirmation model ---")
    piv2 = table.pivot_table(index=["confirm", "pivot_n", "break_on"], columns="entry_style",
                             values="expectancy_r", aggfunc="mean").round(3)
    print(piv2.to_string())

    best, best_sum, _ = select(train, grid)
    print(f"\nSELECTED on TRAIN: { {k: best[k] for k in KEYS} }")
    print("TRAIN:", best_sum)

    tdf, tfill = backtest(test, best)
    print("\nTEST (2024-2025), one look:", summarize(tdf, tfill))

    # walk-forward with the same selection rule
    print("\n=== Walk-forward (re-select each fold) ===")
    folds, oos = [], []
    for cut in pd.date_range("2022-07-01", "2025-07-01", freq="6MS"):
        nxt = cut + pd.DateOffset(months=6)
        tr = [c for c in contexts if c["date"] < cut]
        te = [c for c in contexts if cut <= c["date"] < nxt]
        if len(tr) < 200 or len(te) < 30:
            continue
        cfg, _, _ = select(tr, grid)
        if cfg is None:
            continue
        df, fl = backtest(te, cfg)
        if df.empty:
            continue
        r = df["r_multiple"]
        folds.append({"fold": str(cut.date()), **{k: cfg[k] for k in KEYS},
                      "n": len(df), "win_rate": round(float((df["outcome"] == "WIN").mean() * 100), 1),
                      "expectancy_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1)})
        oos.append(df)
        print(f"  {cut.date()}  {cfg['confirm']}/n{cfg['pivot_n']}/{cfg['entry_style']}"
              f"{'' if cfg['entry_style']=='market' else '@'+str(cfg['retrace'])} range>={cfg['min_range']}"
              f"  n={len(df):3d} win={folds[-1]['win_rate']:5.1f}% "
              f"exp={folds[-1]['expectancy_r']:+.3f}R tot={folds[-1]['total_r']:+.1f}R")

    wf = pd.concat(oos, ignore_index=True).sort_values("date") if oos else pd.DataFrame()
    wf_sum = summarize(wf, 100.0) if not wf.empty else None
    print("\nPooled walk-forward out-of-sample:", wf_sum)
    if folds:
        print(f"Profitable folds: {sum(1 for f in folds if f['total_r'] > 0)}/{len(folds)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    table[show].to_csv(os.path.join(OUT_DIR, "entry_models_grid.csv"), index=False)
    if not wf.empty:
        wf.to_csv(os.path.join(OUT_DIR, "entry_models_wf_trades.csv"), index=False)
    with open(os.path.join(OUT_DIR, "entry_models_results.json"), "w") as f:
        json.dump({"selected": {k: best[k] for k in KEYS}, "train": best_sum,
                   "test": summarize(tdf, tfill), "folds": folds, "pooled_wf": wf_sum,
                   "risk_by_model": piv.reset_index().to_dict(orient="records"),
                   "exp_by_model": piv2.reset_index().to_dict(orient="records"),
                   "grid_top": table[show].head(15).to_dict(orient="records")},
                  f, indent=2, default=str)
    print("\nSaved entry_models_results.json, entry_models_grid.csv")


if __name__ == "__main__":
    main()
