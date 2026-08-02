"""The trade-level simulation the flip-count research should have been:
enter short on MSS-down, stop at the leg's own origin swing high (not the
engine's next internal marker -- see mss_engine.py's leg_price), and if that
specific stop is actually touched, look for the NEXT MSS-down after the
stop-out to re-enter. Mirror for MSS-up / long / Asian low.

This directly answers whether a real stop, at a real structural level, gets
hit before target -- and how many times a trade would genuinely need
re-arming, as opposed to the earlier flip-count metric which measured the
engine's internal regime oscillation, not any specific trade's risk.

No lookahead: only the leg_price/leg_idx known AT the moment each MSS-down
fires is used as that trade's stop; price is walked forward bar by bar from
the entry to find whichever of stop/target is touched first.
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR
COST = 1.0


def simulate_day(raw_h, raw_l, raw_c, sweep_bar, window_end_bar, entries, target, direction, cost=COST):
    """entries: list of (bar, leg_price) MSS events in the expected direction,
    sorted by bar, already restricted to (sweep_bar, window_end_bar]."""
    trades = []
    i = 0
    n = len(entries)
    while i < n:
        e_bar, stop_price = entries[i]
        if stop_price is None:
            i += 1
            continue
        entry_price = raw_c[e_bar] - cost * PIP if direction == "short" else raw_c[e_bar] + cost * PIP
        risk = (stop_price - entry_price) if direction == "short" else (entry_price - stop_price)
        if risk <= 0.2 * PIP:  # stop already behind price at entry -- skip, unusable
            i += 1
            continue
        reward = (entry_price - target) if direction == "short" else (target - entry_price)

        seg_end = window_end_bar
        h_seg = raw_h[e_bar + 1:seg_end + 1]
        l_seg = raw_l[e_bar + 1:seg_end + 1]
        if len(h_seg) == 0:
            break

        if direction == "short":
            i_stop = int(np.argmax(h_seg >= stop_price)) if (h_seg >= stop_price).any() else None
            i_targ = int(np.argmax(l_seg <= target)) if (l_seg <= target).any() else None
        else:
            i_stop = int(np.argmax(l_seg <= stop_price)) if (l_seg <= stop_price).any() else None
            i_targ = int(np.argmax(h_seg >= target)) if (h_seg >= target).any() else None

        if i_stop is not None and (i_targ is None or i_stop <= i_targ):
            r = -1.0
            stop_bar = e_bar + 1 + i_stop
            trades.append({"entry_bar": e_bar, "outcome": "LOSS", "r_multiple": r,
                          "risk_pips": round(risk / PIP, 1)})
            # look for the next MSS-down entry strictly after this stop-out
            i += 1
            while i < n and entries[i][0] <= stop_bar:
                i += 1
            continue
        elif i_targ is not None:
            r = reward / risk if reward > 0 else 0.0
            trades.append({"entry_bar": e_bar, "outcome": "WIN", "r_multiple": round(float(r), 3),
                          "risk_pips": round(risk / PIP, 1)})
            return trades  # day resolved
        else:
            # window ended with neither touched -- mark open/timeout, stop trying
            trades.append({"entry_bar": e_bar, "outcome": "OPEN", "r_multiple": 0.0,
                          "risk_pips": round(risk / PIP, 1)})
            return trades
    return trades


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    o, h, l, c = raw["open"].values, raw["high"].values, raw["low"].values, raw["close"].values
    print(f"Loaded {len(raw):,} bars, running engine...")
    mss_events, _, _ = run_engine(o, h, l, c)
    print(f"{len(mss_events):,} MSS events")

    down_bar = np.array([e["bar"] for e in mss_events if e["dir"] == "down"])
    down_leg = [e["leg_price"] for e in mss_events if e["dir"] == "down"]
    up_bar = np.array([e["bar"] for e in mss_events if e["dir"] == "up"])
    up_leg = [e["leg_price"] for e in mss_events if e["dir"] == "up"]

    ASIAN_START_H, LONDON_KZ_START_H, LONDON_KZ_END_H, EXT_END_H = 20, 2, 5, 12
    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")

    all_day_trades = {"high": [], "low": []}
    for day in days:
        if day.day_name() in ("Saturday", "Sunday"):
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
            trades = simulate_day(h, l, c, sweep_bar, ext_end_bar, entries, a_lo, "short")
            all_day_trades["high"].append({"date": day.date(), "n_attempts": len(trades), "trades": trades})
        else:
            mask = (up_bar > sweep_bar) & (up_bar <= ext_end_bar)
            entries = [(b, up_leg[k]) for k, b in enumerate(up_bar) if mask[k]]
            trades = simulate_day(h, l, c, sweep_bar, ext_end_bar, entries, a_hi, "long")
            all_day_trades["low"].append({"date": day.date(), "n_attempts": len(trades), "trades": trades})

    os.makedirs(OUT_DIR, exist_ok=True)
    report = {}
    pd.set_option("display.width", 160)
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

        print(f"\n=== side={side} ===")
        print(f"days: {n_days}, days with zero MSS-down/up entries at all: {n_no_entry}")
        print("attempts-per-day distribution:")
        print(attempts_per_day.describe(percentiles=[.5, .75, .9, .95]).round(2).to_string())
        print("final outcome per day (after re-entries):")
        print(final_counts.to_string())
        if not df.empty:
            wins = df[df["outcome"] == "WIN"]
            losses = df[df["outcome"] == "LOSS"]
            print(f"individual attempts: {len(df)}  win={len(wins)}  loss={len(losses)}  open={len(df)-len(wins)-len(losses)}")
            print(f"mean risk_pips per attempt: {df['risk_pips'].mean():.1f}")
            print(f"per-day summed R (each attempt = 1R risk): mean {day_final.merge(pd.DataFrame(flat).groupby('date')['r_multiple'].sum().reset_index(), on='date', how='left')['r_multiple'].fillna(0).mean():.3f}")

        report[side] = {
            "n_days": n_days, "n_no_entry": n_no_entry,
            "attempts_mean": round(float(attempts_per_day.mean()), 2),
            "attempts_median": float(attempts_per_day.median()),
            "attempts_p90": float(attempts_per_day.quantile(0.9)),
            "final_outcome_counts": {k: int(v) for k, v in final_counts.items()},
            "n_individual_attempts": int(len(df)) if not df.empty else 0,
            "attempt_win_rate": round(float((df["outcome"] == "WIN").mean() * 100), 1) if not df.empty else None,
            "mean_risk_pips": round(float(df["risk_pips"].mean()), 1) if not df.empty else None,
        }
        df.to_csv(os.path.join(OUT_DIR, f"mss_trade_sim_{side}.csv"), index=False)

    with open(os.path.join(OUT_DIR, "mss_trade_simulation_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("\nSaved mss_trade_simulation_report.json")


if __name__ == "__main__":
    main()
