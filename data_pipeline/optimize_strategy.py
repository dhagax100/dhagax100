"""Grid-search the Asian/London sweep-fade rule on TRAIN, validate once on TEST.

Built from the measured behaviour in analyze_reversal_behavior.py rather than
from a guess:

  * 100% of target-reaching days close a candle back inside the Asian range
    ("reclaim") before running to target, vs only 85.3% of failing days --
    so requiring a reclaim is a free filter that discards losers at no cost
    to winners.
  * Excursion beyond the swept level separates winners (median 8.4 pips) from
    losers (median 44.1 pips) very strongly -- so the stop needs room to
    breathe past the level, not to sit on the sweep candle's wick.

Conventions that keep this honest:
  * Path-dependent: bars are evaluated in time order; whichever of stop/target
    is touched first decides the trade.
  * Same-bar ambiguity resolves as a LOSS (pessimistic), never a win.
  * Execution cost (spread + entry slippage, COST_PIPS) is charged against
    every entry. This matters enormously here: a 1-pip cost is ~15% of a
    7-pip stop, so the tightest-stop configs are the ones it punishes most,
    and ignoring it would flatter exactly the configs least likely to survive
    live.
  * Nothing after 2023-12-31 is read while choosing parameters. TEST is
    evaluated once, at the end, with the already-fixed configuration.
  * The whole grid is reported, not just the winner, so the parameter surface
    can be inspected for a plateau (robust) vs a lone spike (overfit).
"""
import argparse
import itertools
import json
import os

import numpy as np
import pandas as pd

PIP = 0.0001
ASIAN_START_H = 20
LONDON_KZ_START_H = 2
LONDON_KZ_END_H = 5
EXTENDED_END_H = 12

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "derived")

TRAIN_END = pd.Timestamp("2023-12-31")
COST_PIPS = 1.0  # spread + entry slippage charged against every trade


def load_raw(pair, start_year, end_year):
    frames = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(RAW_DIR, f"DAT_ASCII_{pair.upper()}_M1_{year}.csv")
        frames.append(pd.read_csv(path, sep=";", header=None,
                                  names=["ts", "open", "high", "low", "close", "volume"]))
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    return df.sort_values("ts").drop_duplicates(subset="ts").set_index("ts")


def build_contexts(df):
    """One numpy context per setup day: bars from the sweep onward + levels."""
    days = pd.date_range(df.index.min().normalize(), df.index.max().normalize(), freq="D")
    contexts = []
    for day in days:
        if day.day_name() in ("Saturday", "Sunday"):
            continue
        asian_start = (day - pd.Timedelta(days=1)).replace(hour=ASIAN_START_H, minute=0, second=0)
        asian_end = day.replace(hour=0, minute=0, second=0)
        kz_start = day.replace(hour=LONDON_KZ_START_H, minute=0, second=0)
        kz_end = day.replace(hour=LONDON_KZ_END_H, minute=0, second=0)
        ext_end = day.replace(hour=EXTENDED_END_H, minute=0, second=0)

        asian = df.loc[asian_start:asian_end - pd.Timedelta(seconds=1)]
        kz = df.loc[kz_start:kz_end - pd.Timedelta(seconds=1)]
        if len(asian) < 200 or len(kz) < 150:
            continue

        a_hi, a_lo = asian["high"].max(), asian["low"].min()
        hi_m, lo_m = kz["high"] > a_hi, kz["low"] < a_lo
        hi_t = kz.index[hi_m][0] if hi_m.any() else pd.NaT
        lo_t = kz.index[lo_m][0] if lo_m.any() else pd.NaT
        if pd.isna(hi_t) and pd.isna(lo_t):
            continue
        if not pd.isna(hi_t) and (pd.isna(lo_t) or hi_t <= lo_t):
            side, sweep_time = "high", hi_t
        else:
            side, sweep_time = "low", lo_t

        post = df.loc[sweep_time:ext_end - pd.Timedelta(seconds=1)]
        if len(post) < 10:
            continue

        contexts.append({
            "date": day, "side": side,
            "highs": post["high"].values, "lows": post["low"].values, "closes": post["close"].values,
            "level": a_lo if side == "low" else a_hi,
            "opposite": a_hi if side == "low" else a_lo,
            "asian_range": a_hi - a_lo,
            "sweep_hour": sweep_time.hour,
        })
    return contexts


def _first_true(mask):
    return int(np.argmax(mask)) if mask.any() else None


def run_trade(ctx, p):
    """Simulate one day under config p. Returns None if no trade is taken."""
    side = ctx["side"]
    long_ = side == "low"
    highs, lows, closes = ctx["highs"], ctx["lows"], ctx["closes"]
    level, opposite, arange = ctx["level"], ctx["opposite"], ctx["asian_range"]

    arange_pips = arange / PIP
    if not (p["min_range"] <= arange_pips <= p["max_range"]):
        return None

    # --- entry ---
    if p["entry"] == "immediate":
        e_idx = 0
    else:  # "reclaim": first candle CLOSING back inside the Asian range
        rec = closes > level if long_ else closes < level
        e_idx = _first_true(rec)
        if e_idx is None or e_idx >= len(closes) - 2:
            return None
        if e_idx > p["max_wait_min"]:
            return None
    # fill is worse than the quoted close by spread + slippage
    entry = closes[e_idx] + COST_PIPS * PIP if long_ else closes[e_idx] - COST_PIPS * PIP

    # --- stop: measured from the swept level, so it breathes with the sweep ---
    seg_lo = lows[:e_idx + 1].min() if long_ else None
    seg_hi = highs[:e_idx + 1].max() if not long_ else None
    if p["stop_mode"] == "beyond_level":
        stop = level - p["stop_pips"] * PIP if long_ else level + p["stop_pips"] * PIP
    elif p["stop_mode"] == "beyond_extreme":
        stop = seg_lo - p["stop_pips"] * PIP if long_ else seg_hi + p["stop_pips"] * PIP
    else:  # "range_frac": stop scales with that day's Asian range
        pad = arange * p["stop_frac"]
        stop = level - pad if long_ else level + pad

    risk = (entry - stop) if long_ else (stop - entry)
    if risk <= 0.2 * PIP:
        return None
    if p["max_risk_pips"] and risk / PIP > p["max_risk_pips"]:
        return None

    # --- target ---
    target = entry + (opposite - entry) * p["target_frac"] if long_ else entry - (entry - opposite) * p["target_frac"]
    reward = (target - entry) if long_ else (entry - target)
    if reward <= 0:
        return None
    if p["min_rr"] and reward / risk < p["min_rr"]:
        return None

    h, l = highs[e_idx + 1:], lows[e_idx + 1:]
    if len(h) == 0:
        return None

    if long_:
        i_stop = _first_true(l <= stop)
        i_targ = _first_true(h >= target)
    else:
        i_stop = _first_true(h >= stop)
        i_targ = _first_true(l <= target)

    # breakeven: once price has run be_trigger x risk in our favour, stop -> entry
    if p["be_at_r"]:
        be_px = entry + p["be_at_r"] * risk if long_ else entry - p["be_at_r"] * risk
        i_be = _first_true(h >= be_px) if long_ else _first_true(l <= be_px)
        if i_be is not None and (i_stop is None or i_be < i_stop):
            tail = (l[i_be:] <= entry) if long_ else (h[i_be:] >= entry)
            j = _first_true(tail)
            if j is not None:
                i_be_stop = i_be + j
                if i_stop is None or i_be_stop < i_stop:
                    i_stop, stop = i_be_stop, entry

    # same-bar ambiguity resolves against us
    if i_stop is not None and (i_targ is None or i_stop <= i_targ):
        r = ((stop - entry) if long_ else (entry - stop)) / risk
        outcome = "BE" if abs(r) < 1e-9 else "LOSS"
    elif i_targ is not None:
        r, outcome = reward / risk, "WIN"
    else:
        last = closes[-1]
        r = ((last - entry) if long_ else (entry - last)) / risk
        outcome = "WIN" if r > 0.05 else ("LOSS" if r < -0.05 else "BE")

    return {"date": ctx["date"], "side": side, "outcome": outcome,
            "r_multiple": round(float(r), 3), "risk_pips": round(risk / PIP, 1),
            "reward_pips": round(reward / PIP, 1)}


def backtest(contexts, p):
    return pd.DataFrame([t for ctx in contexts for t in [run_trade(ctx, p)] if t is not None])


def summarize(trades):
    if trades.empty or len(trades) < 20:
        return None
    n = len(trades)
    r = trades["r_multiple"]
    gw = r[r > 0].sum()
    gl = -r[r < 0].sum()
    eq = r.cumsum()
    return {
        "n_trades": int(n),
        "win_rate": round(float((trades["outcome"] == "WIN").mean() * 100), 1),
        "expectancy_r": round(float(r.mean()), 3),
        "total_r": round(float(r.sum()), 1),
        "profit_factor": round(float(gw / gl), 2) if gl > 0 else None,
        "max_dd_r": round(float((eq.cummax() - eq).max()), 1),
        "avg_risk_pips": round(float(trades["risk_pips"].mean()), 1),
        "avg_rr": round(float((trades["reward_pips"] / trades["risk_pips"]).mean()), 2),
    }


BASE = {"entry": "reclaim", "max_wait_min": 120, "stop_mode": "beyond_level", "stop_pips": 15,
        "stop_frac": 0.5, "target_frac": 1.0, "be_at_r": None, "min_range": 0, "max_range": 1e9,
        "max_risk_pips": None, "min_rr": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="eurusd")
    args = ap.parse_args()

    print("Loading raw 1-minute data and building day contexts...")
    raw = load_raw(args.pair, 2021, 2025)
    contexts = build_contexts(raw)
    train_ctx = [c for c in contexts if c["date"] <= TRAIN_END]
    test_ctx = [c for c in contexts if c["date"] > TRAIN_END]
    print(f"{len(contexts)} setup days | TRAIN {len(train_ctx)} | TEST {len(test_ctx)}\n")

    keys = ["entry", "stop_mode", "stop_pips", "target_frac", "be_at_r", "min_rr"]
    grid = []
    for entry, stop_mode, stop_pips, target_frac, be_at_r in itertools.product(
            ["immediate", "reclaim"], ["beyond_level", "beyond_extreme"],
            [3, 5, 8, 12, 15, 20, 25, 30], [0.5, 0.75, 1.0], [None, 1.0]):
        grid.append(dict(BASE, entry=entry, stop_mode=stop_mode, stop_pips=stop_pips,
                         target_frac=target_frac, be_at_r=be_at_r))

    print(f"=== Grid-searching {len(grid)} configs on TRAIN (2021-2023) ONLY "
          f"| cost {COST_PIPS} pip/trade ===")
    rows = []
    for p in grid:
        s = summarize(backtest(train_ctx, p))
        if s:
            rows.append({**{k: p[k] for k in keys}, **s})
    res = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)
    pd.set_option("display.width", 220)
    print("\n--- Top 12 by raw expectancy ---")
    print(res.head(12).to_string(index=False))

    # Selection criterion, fixed BEFORE looking at TEST and chosen to reflect the
    # actual goal (prop-firm viability): best expectancy among configs that are
    # tradeable -- enough trades to be significant, and a drawdown a funded
    # account could survive.
    elig = res[(res["n_trades"] >= 150) & (res["max_dd_r"] <= 15)]
    print(f"\n--- Eligible under selection rule (n>=150, maxDD<=15R): {len(elig)} configs ---")
    print(elig.head(10).to_string(index=False))
    if elig.empty:
        elig = res
    best_row = elig.iloc[0]

    best = dict(BASE, entry=best_row["entry"], stop_mode=best_row["stop_mode"],
                stop_pips=int(best_row["stop_pips"]), target_frac=float(best_row["target_frac"]),
                be_at_r=None if pd.isna(best_row["be_at_r"]) else float(best_row["be_at_r"]))
    print(f"\nSELECTED on TRAIN: {dict((k, best[k]) for k in keys)}")

    # robustness: is the winner on a plateau, or a lone spike?
    nb = res[(res["entry"] == best_row["entry"]) & (res["stop_mode"] == best_row["stop_mode"]) &
             (res["target_frac"] == best_row["target_frac"]) &
             (res["be_at_r"].isna() if pd.isna(best_row["be_at_r"]) else res["be_at_r"] == best_row["be_at_r"])]
    print("\n=== Plateau check: same config, stop distance swept ===")
    print(nb[["stop_pips", "n_trades", "win_rate", "expectancy_r", "profit_factor", "max_dd_r"]]
          .sort_values("stop_pips").to_string(index=False))

    print("\n=== TEST (2024-2025), evaluated once with the config fixed above ===")
    test_trades = backtest(test_ctx, best)
    test_sum = summarize(test_trades)
    print(test_sum)

    train_trades = backtest(train_ctx, best)
    os.makedirs(OUT_DIR, exist_ok=True)
    train_trades.to_csv(os.path.join(OUT_DIR, "opt_trades_train.csv"), index=False)
    test_trades.to_csv(os.path.join(OUT_DIR, "opt_trades_test.csv"), index=False)
    res.to_csv(os.path.join(OUT_DIR, "opt_grid_train.csv"), index=False)

    with open(os.path.join(OUT_DIR, "opt_results.json"), "w") as f:
        json.dump({"best_config": {k: (None if pd.isna(v) else v) for k, v in best.items()},
                   "train_summary": summarize(train_trades), "test_summary": test_sum,
                   "plateau": nb.sort_values("stop_pips").to_dict(orient="records"),
                   "grid_top": res.head(15).to_dict(orient="records")}, f, indent=2, default=str)
    print("\nSaved opt_results.json, opt_grid_train.csv, opt_trades_{train,test}.csv")


if __name__ == "__main__":
    main()
