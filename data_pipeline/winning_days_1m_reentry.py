"""Restricted to the 558 days where the 5-minute pullback landed 50% or
deeper on the ladder (see winning_days_retracement.py): drop to the
1-minute chart and run the exact same swing/MSS entry+re-entry mechanic as
mss_trade_simulation.py (enter on a 1m swing exceedance, stop at that leg's
own origin swing -- "the top of the 1m ladder" -- re-enter on the next 1m
swing exceedance if stopped, repeat until target or the window ends).

New on top of that: for every individual attempt (every leg in the chain),
measure how far price retests back toward the stop (0% = entry, 100% = stop)
before that attempt resolves -- the same 0-100% ladder idea as before, now
applied to each attempt's own small leg, not just the first one.
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine
from mss_retracement import run_for_timeframe

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR
COST = 1.0
ASIAN_START_H, LONDON_KZ_START_H, LONDON_KZ_END_H, EXT_END_H = 20, 2, 5, 12


def select_558_days(raw):
    won = pd.read_csv(os.path.join(OUT_DIR, "reversal_behavior_eurusd_2021_2025.csv"))
    won = won[won["reached_target"] == True]
    won_dates = set(won["date"].astype(str))
    legs = run_for_timeframe(raw, "5min")
    ldf = pd.DataFrame(legs)
    ldf["date"] = ldf["date"].astype(str)
    ldf = ldf[ldf["date"].isin(won_dates)]
    deep = ldf[ldf["max_retrace_pct"] >= 50]
    return set(zip(deep["date"], deep["side"]))


def simulate_day_with_retrace(raw_h, raw_l, raw_c, sweep_bar, window_end_bar, entries, target, direction, cost=COST):
    trades = []
    i, n = 0, len(entries)
    while i < n:
        e_bar, stop_price = entries[i]
        if stop_price is None:
            i += 1
            continue
        entry_price = raw_c[e_bar] - cost * PIP if direction == "short" else raw_c[e_bar] + cost * PIP
        risk = (stop_price - entry_price) if direction == "short" else (entry_price - stop_price)
        if risk <= 0.2 * PIP:
            i += 1
            continue
        reward = (entry_price - target) if direction == "short" else (target - entry_price)

        h_seg = raw_h[e_bar + 1:window_end_bar + 1]
        l_seg = raw_l[e_bar + 1:window_end_bar + 1]
        if len(h_seg) == 0:
            break

        if direction == "short":
            i_stop = int(np.argmax(h_seg >= stop_price)) if (h_seg >= stop_price).any() else None
            i_targ = int(np.argmax(l_seg <= target)) if (l_seg <= target).any() else None
        else:
            i_stop = int(np.argmax(l_seg <= stop_price)) if (l_seg <= stop_price).any() else None
            i_targ = int(np.argmax(h_seg >= target)) if (h_seg >= target).any() else None

        if i_stop is not None and (i_targ is None or i_stop <= i_targ):
            resolve_i, outcome, r = i_stop, "LOSS", -1.0
        elif i_targ is not None:
            resolve_i, outcome, r = i_targ, "WIN", round(float(reward / risk if reward > 0 else 0.0), 3)
        else:
            resolve_i, outcome, r = len(h_seg) - 1, "OPEN", 0.0

        if direction == "short":
            worst = h_seg[:resolve_i + 1].max()
            retrace_pct = (worst - entry_price) / risk * 100
        else:
            worst = l_seg[:resolve_i + 1].min()
            retrace_pct = (entry_price - worst) / risk * 100

        trades.append({"entry_bar": e_bar, "outcome": outcome, "r_multiple": r,
                       "risk_pips": round(risk / PIP, 1), "retrace_pct": round(float(retrace_pct), 1)})

        if outcome == "LOSS":
            stop_bar = e_bar + 1 + i_stop
            i += 1
            while i < n and entries[i][0] <= stop_bar:
                i += 1
            continue
        else:
            return trades
    return trades


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} bars")
    keep = select_558_days(raw)
    print(f"Restricting to {len(keep)} (date, side) pairs with 5m retracement >= 50%")

    o, h, l, c = raw["open"].values, raw["high"].values, raw["low"].values, raw["close"].values
    mss_events, _, _ = run_engine(o, h, l, c)
    down_bar = np.array([e["bar"] for e in mss_events if e["dir"] == "down"])
    down_leg = [e["leg_price"] for e in mss_events if e["dir"] == "down"]
    up_bar = np.array([e["bar"] for e in mss_events if e["dir"] == "up"])
    up_leg = [e["leg_price"] for e in mss_events if e["dir"] == "up"]

    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")
    all_day_trades = {"high": [], "low": []}
    for day in days:
        if day.day_name() in ("Saturday", "Sunday"):
            continue
        date_str = str(day.date())
        if (date_str, "high") not in keep and (date_str, "low") not in keep:
            continue
        asian_start = (day - pd.Timedelta(days=1)).replace(hour=ASIAN_START_H, minute=0, second=0)
        asian_end = day.replace(hour=0, minute=0, second=0)
        kz_start = day.replace(hour=LONDON_KZ_START_H, minute=0, second=0)
        kz_end = day.replace(hour=LONDON_KZ_END_H, minute=0, second=0)
        ext_end = day.replace(hour=EXT_END_H, minute=0, second=0)
        asian = raw.loc[asian_start:asian_end - pd.Timedelta(seconds=1)]
        kz = raw.loc[kz_start:kz_end - pd.Timedelta(seconds=1)]
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
        if (date_str, side) not in keep:
            continue
        try:
            sweep_bar = raw.index.get_loc(sweep_time)
            ext_end_bar = raw.index.get_indexer([ext_end], method="ffill")[0]
        except KeyError:
            continue
        if sweep_bar >= len(raw) - 5:
            continue

        if side == "high":
            mask = (down_bar > sweep_bar) & (down_bar <= ext_end_bar)
            entries = [(b, down_leg[k]) for k, b in enumerate(down_bar) if mask[k]]
            trades = simulate_day_with_retrace(h, l, c, sweep_bar, ext_end_bar, entries, a_lo, "short")
            all_day_trades["high"].append({"date": date_str, "n_attempts": len(trades), "trades": trades})
        else:
            mask = (up_bar > sweep_bar) & (up_bar <= ext_end_bar)
            entries = [(b, up_leg[k]) for k, b in enumerate(up_bar) if mask[k]]
            trades = simulate_day_with_retrace(h, l, c, sweep_bar, ext_end_bar, entries, a_hi, "long")
            all_day_trades["low"].append({"date": date_str, "n_attempts": len(trades), "trades": trades})

    report = {}
    edges = [-1e9, 0, 25, 50, 75, 100, 1e9]
    labels = ["<0%", "0-25%", "25-50%", "50-75%", "75-100%", ">100%"]
    for side in ["high", "low"]:
        days_ = all_day_trades[side]
        flat = [{"date": d["date"], **t} for d in days_ for t in d["trades"]]
        df = pd.DataFrame(flat)
        n_days = len(days_)
        n_no_entry = sum(1 for d in days_ if d["n_attempts"] == 0)
        attempts_per_day = pd.Series([d["n_attempts"] for d in days_])
        day_final = pd.DataFrame([{"date": d["date"], "final": d["trades"][-1]["outcome"] if d["trades"] else "NO_ENTRY",
                                   "n_attempts": d["n_attempts"]} for d in days_])
        final_counts = day_final["final"].value_counts()

        print(f"\n=== side={side}  days={n_days}  no_entry={n_no_entry} ===")
        print("attempts/day:", attempts_per_day.describe(percentiles=[.5, .75, .9]).round(2).to_dict())
        print("final outcome per day:", final_counts.to_dict())

        r = {"n_days": n_days, "n_no_entry": n_no_entry,
            "attempts_median": float(attempts_per_day.median()),
            "attempts_p90": float(attempts_per_day.quantile(0.9)),
            "final_outcome_counts": {k: int(v) for k, v in final_counts.items()}}

        if not df.empty:
            wins, losses = df[df["outcome"] == "WIN"], df[df["outcome"] == "LOSS"]
            print(f"attempts={len(df)} win={len(wins)} loss={len(losses)} open={len(df)-len(wins)-len(losses)}  "
                  f"win_rate={len(wins)/len(df)*100:.1f}%  mean_risk={df['risk_pips'].mean():.1f}p")
            bucket = pd.cut(df["retrace_pct"], bins=edges, labels=labels)
            print("retest-level bucket (all attempts):", bucket.value_counts().reindex(labels).to_dict())
            print("retest-level bucket (WIN attempts only):", pd.cut(wins["retrace_pct"], bins=edges, labels=labels).value_counts().reindex(labels).to_dict())
            r["n_attempts"] = int(len(df))
            r["attempt_win_rate"] = round(float(len(wins) / len(df) * 100), 1)
            r["mean_risk_pips"] = round(float(df["risk_pips"].mean()), 1)
            r["retrace_bucket_all"] = {k: int(v) for k, v in bucket.value_counts().reindex(labels).items()}
            r["retrace_bucket_wins"] = {k: int(v) for k, v in pd.cut(wins["retrace_pct"], bins=edges, labels=labels).value_counts().reindex(labels).items()}
        report[side] = r
        df.to_csv(os.path.join(OUT_DIR, f"winning_days_1m_reentry_{side}.csv"), index=False)

    with open(os.path.join(OUT_DIR, "winning_days_1m_reentry_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("\nSaved winning_days_1m_reentry_report.json")


if __name__ == "__main__":
    main()
