"""Mechanical, path-dependent backtest of the Asian/London sweep-fade setup.

Unlike the descriptive MFE/MAE summary in build_session_dataset.py (which
looks at the whole post-sweep window at once), this walks the 1-minute bars
in real time order and applies an entry/stop/target/breakeven rule exactly
as a live EA would -- so a day's outcome depends on what happens FIRST
(stop hit vs. breakeven trigger vs. target hit), not on where price
eventually ends up.

Stop-loss uses ONLY the sweep bar's own high/low (known at entry time) --
never a later, deeper excursion -- to avoid lookahead bias.

Train/test split is by calendar time (2021-2023 train, 2024-2025 test), not
random, since shuffling would leak future information into training. All
breakeven-rule tuning happens on TRAIN only; TEST is touched exactly once,
after the rule is fixed.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

PIP = 0.0001
STOP_BUFFER_PIPS = 1.0  # spread/slippage buffer beyond the sweep bar's wick

ASIAN_START_H = 20
LONDON_KZ_START_H = 2
LONDON_KZ_END_H = 5
EXTENDED_END_H = 12

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "derived")


def load_raw(pair: str, start_year: int, end_year: int) -> pd.DataFrame:
    frames = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(RAW_DIR, f"DAT_ASCII_{pair.upper()}_M1_{year}.csv")
        df = pd.read_csv(path, sep=";", header=None, names=["ts", "open", "high", "low", "close", "volume"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    return df.sort_values("ts").drop_duplicates(subset="ts").set_index("ts")


def find_setup(df: pd.DataFrame, day: pd.Timestamp):
    """Identify the sweep for one day, using only same-day/prior info."""
    asian_start = (day - pd.Timedelta(days=1)).replace(hour=ASIAN_START_H, minute=0, second=0)
    asian_end = day.replace(hour=0, minute=0, second=0)
    kz_start = day.replace(hour=LONDON_KZ_START_H, minute=0, second=0)
    kz_end = day.replace(hour=LONDON_KZ_END_H, minute=0, second=0)
    ext_end = day.replace(hour=EXTENDED_END_H, minute=0, second=0)

    asian = df.loc[asian_start:asian_end - pd.Timedelta(seconds=1)]
    kz = df.loc[kz_start:kz_end - pd.Timedelta(seconds=1)]
    if asian.empty or len(asian) < 200 or len(kz) < 150:
        return None

    asian_high, asian_low = asian["high"].max(), asian["low"].min()
    swept_high_mask = kz["high"] > asian_high
    swept_low_mask = kz["low"] < asian_low
    high_t = kz.index[swept_high_mask][0] if swept_high_mask.any() else pd.NaT
    low_t = kz.index[swept_low_mask][0] if swept_low_mask.any() else pd.NaT

    if pd.isna(high_t) and pd.isna(low_t):
        return None
    if not pd.isna(high_t) and (pd.isna(low_t) or high_t <= low_t):
        side, sweep_time = "high", high_t
    else:
        side, sweep_time = "low", low_t

    sweep_bar = df.loc[sweep_time]
    direction = "short" if side == "high" else "long"
    entry_price = sweep_bar["close"]
    target_price = asian_low if side == "high" else asian_high

    if direction == "long":
        stop_price = sweep_bar["low"] - STOP_BUFFER_PIPS * PIP
    else:
        stop_price = sweep_bar["high"] + STOP_BUFFER_PIPS * PIP

    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return None

    return {
        "date": day.date(), "direction": direction, "sweep_time": sweep_time,
        "entry_price": entry_price, "stop_price": stop_price, "target_price": target_price,
        "risk_price": risk, "window_end": ext_end,
    }


def simulate_trade(df: pd.DataFrame, setup: dict, be_rule: str):
    """Walk bars AFTER the entry bar in time order; first trigger wins."""
    path = df.loc[setup["sweep_time"]:setup["window_end"] - pd.Timedelta(seconds=1)].iloc[1:]
    direction = setup["direction"]
    entry, stop, target, risk = setup["entry_price"], setup["stop_price"], setup["target_price"], setup["risk_price"]

    be_armed = False
    if be_rule == "1R":
        be_trigger = entry + risk if direction == "long" else entry - risk
    elif be_rule == "50pct":
        be_trigger = entry + 0.5 * abs(target - entry) if direction == "long" else entry - 0.5 * abs(target - entry)
    else:
        be_trigger = None  # "none"

    for ts, bar in path.iterrows():
        lo, hi = bar["low"], bar["high"]
        if direction == "long":
            # check BE arming first using this bar's favorable extent
            if be_trigger is not None and not be_armed and hi >= be_trigger:
                be_armed = True
                stop = entry  # move stop to breakeven
            if lo <= stop:
                r = (stop - entry) / risk
                return {"outcome": "BE" if abs(r) < 1e-9 else "LOSS", "r_multiple": round(r, 3), "exit_time": ts}
            if hi >= target:
                r = (target - entry) / risk
                return {"outcome": "WIN", "r_multiple": round(r, 3), "exit_time": ts}
        else:
            if be_trigger is not None and not be_armed and lo <= be_trigger:
                be_armed = True
                stop = entry
            if hi >= stop:
                r = (entry - stop) / risk
                return {"outcome": "BE" if abs(r) < 1e-9 else "LOSS", "r_multiple": round(r, 3), "exit_time": ts}
            if lo <= target:
                r = (entry - target) / risk
                return {"outcome": "WIN", "r_multiple": round(r, 3), "exit_time": ts}

    # window ended with neither stop nor target hit -- close at last available price
    last_close = path["close"].iloc[-1] if len(path) else entry
    r = (last_close - entry) / risk if direction == "long" else (entry - last_close) / risk
    outcome = "WIN" if r > 0.1 else ("LOSS" if r < -0.1 else "BE")
    return {"outcome": outcome, "r_multiple": round(r, 3), "exit_time": setup["window_end"]}


def run_backtest(df: pd.DataFrame, be_rule: str, start: str, end: str) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    rows = []
    for d in days:
        if d.day_name() in ("Saturday", "Sunday"):
            continue
        setup = find_setup(df, d)
        if setup is None:
            continue
        result = simulate_trade(df, setup, be_rule)
        rows.append({"date": setup["date"], "direction": setup["direction"], **result})
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    n = len(trades)
    wins = (trades["outcome"] == "WIN").sum()
    losses = (trades["outcome"] == "LOSS").sum()
    bes = (trades["outcome"] == "BE").sum()
    total_r = trades["r_multiple"].sum()
    gross_win_r = trades.loc[trades["r_multiple"] > 0, "r_multiple"].sum()
    gross_loss_r = -trades.loc[trades["r_multiple"] < 0, "r_multiple"].sum()
    equity = trades["r_multiple"].cumsum()
    running_max = equity.cummax()
    max_dd = (running_max - equity).max()
    return {
        "n_trades": int(n),
        "win_rate": round(wins / n * 100, 1),
        "loss_rate": round(losses / n * 100, 1),
        "be_rate": round(bes / n * 100, 1),
        "expectancy_r": round(total_r / n, 3),
        "total_r": round(float(total_r), 2),
        "profit_factor": round(float(gross_win_r / gross_loss_r), 2) if gross_loss_r > 0 else None,
        "max_drawdown_r": round(float(max_dd), 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="eurusd")
    args = parser.parse_args()

    print("Loading raw 1-minute data...")
    raw = load_raw(args.pair, 2021, 2025)

    TRAIN = ("2021-01-01", "2023-12-31")
    TEST = ("2024-01-01", "2025-12-31")

    print("\n=== Tuning breakeven rule on TRAIN (2021-2023) only ===")
    train_results = {}
    for be_rule in ["none", "1R", "50pct"]:
        trades = run_backtest(raw, be_rule, *TRAIN)
        summary = summarize(trades)
        train_results[be_rule] = summary
        print(f"{be_rule:8s}", summary)

    best_rule = max(train_results, key=lambda k: train_results[k]["expectancy_r"])
    print(f"\nBest rule on TRAIN by expectancy: {best_rule}")

    print(f"\n=== Validating '{best_rule}' on TEST (2024-2025), touched once ===")
    test_trades = run_backtest(raw, best_rule, *TEST)
    test_summary = summarize(test_trades)
    print(test_summary)

    train_trades = run_backtest(raw, best_rule, *TRAIN)

    os.makedirs(OUT_DIR, exist_ok=True)
    train_trades.to_csv(os.path.join(OUT_DIR, f"backtest_train_{best_rule}.csv"), index=False)
    test_trades.to_csv(os.path.join(OUT_DIR, f"backtest_test_{best_rule}.csv"), index=False)

    out = {
        "best_rule": best_rule,
        "stop_buffer_pips": STOP_BUFFER_PIPS,
        "train_period": TRAIN, "test_period": TEST,
        "train_all_rules": train_results,
        "train_summary": summarize(train_trades),
        "test_summary": test_summary,
    }
    with open(os.path.join(OUT_DIR, "backtest_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\nSaved backtest_results.json,", f"backtest_train_{best_rule}.csv,", f"backtest_test_{best_rule}.csv")
