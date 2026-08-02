"""Same MSS-after-sweep research as mss_after_sweep.py / mss_trade_simulation.py,
but with the swing/MSS engine run on 5-minute or 15-minute candles (resampled
from the same 1-minute data) instead of 1-minute -- testing whether a wider,
less noisy timeframe gives the engine legs that are actually tradeable.

Two things stay fixed across all three timeframes, so the timeframe is the
only thing that changes between runs:
  - Asian/London session levels and the sweep moment itself are still
    computed from 1-minute data (this is about session structure, not MSS).
  - Trade execution (does price touch the stop or the target first) is
    checked against raw 1-minute bars, never against the coarser resampled
    bars -- a 15-minute bar's high and low can occur in either order, so
    using it for execution would introduce same-bar ambiguity the 1-minute
    data doesn't have. Only swing/MSS detection runs on the coarser candles.

A resampled bar's O/H/L/C isn't fully known until it closes (matching how
the indicator behaves live -- it recalculates once a candle completes), so
each MSS event's entry point maps to the LAST 1-minute bar inside that
resampled candle; the walk-forward stop/target check starts on the next
1-minute bar after that, exactly as in the 1-minute version.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine
from mss_trade_simulation import simulate_day

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR
ASIAN_START_H, LONDON_KZ_START_H, LONDON_KZ_END_H, EXT_END_H = 20, 2, 5, 12


def resample(raw: pd.DataFrame, freq: str) -> pd.DataFrame:
    r = raw.resample(freq, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    return r.dropna(subset=["open"])


def map_events_to_1m(events, res_index: pd.DatetimeIndex, raw_index: pd.DatetimeIndex, freq: pd.Timedelta):
    """Convert each event's resampled-bar index to the 1-minute bar index of
    that resampled candle's LAST constituent minute (when it's fully known)."""
    out = []
    raw_vals = raw_index.values
    for e in events:
        bar_start = res_index[e["bar"]]
        boundary = np.datetime64(bar_start + freq)
        pos = int(np.searchsorted(raw_vals, boundary)) - 1
        if pos < 0:
            continue
        out.append({**e, "bar_1m": pos})
    return out


def run_for_timeframe(raw: pd.DataFrame, freq_str: str):
    freq = pd.Timedelta(freq_str)
    res = resample(raw, freq_str)
    print(f"\n### {freq_str} candles: {len(res):,} bars (from {len(raw):,} 1-minute bars) ###")

    o, h, l, c = res["open"].values, res["high"].values, res["low"].values, res["close"].values
    mss_events, regime_at_bar = run_engine(o, h, l, c)
    print(f"{len(mss_events):,} MSS events on {freq_str} ({len(mss_events)/max(1,len(res)):.3f} per bar)")

    mapped = map_events_to_1m(mss_events, res.index, raw.index, freq)
    down = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped if e["dir"] == "down"])
    up = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped if e["dir"] == "up"])

    # regime-at-sweep lookup: nearest resampled bar at/just before the sweep
    def regime_before(sweep_time_1m):
        pos = int(np.searchsorted(res.index.values, np.datetime64(sweep_time_1m))) - 1
        return int(regime_at_bar[pos]) if pos >= 0 else 0

    raw_h, raw_l, raw_c = raw["high"].values, raw["low"].values, raw["close"].values
    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")

    rows = {"high": [], "low": []}
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

        pre_regime = regime_before(sweep_time)
        want_side = "down" if side == "high" else "up"
        pool = down if want_side == "down" else up
        entries = [(b, p) for b, p in pool if sweep_bar < b <= ext_end_bar and p is not None]

        if side == "high":
            trades = simulate_day(raw_h, raw_l, raw_c, sweep_bar, ext_end_bar, entries, a_lo, "short")
        else:
            trades = simulate_day(raw_h, raw_l, raw_c, sweep_bar, ext_end_bar, entries, a_hi, "long")

        rows[side].append({
            "date": day.date(), "pre_regime": pre_regime,
            "regime_matches": pre_regime == (1 if side == "high" else 2),
            "n_attempts": len(trades), "trades": trades,
        })

    report = {"freq": freq_str, "total_mss_events": len(mss_events),
              "avg_minutes_between_events": round(5 * 365 * 1440 / max(1, len(mss_events)), 1)}
    for side in ["high", "low"]:
        days_ = rows[side]
        n = len(days_)
        n_no_entry = sum(1 for d in days_ if d["n_attempts"] == 0)
        regime_match = sum(1 for d in days_ if d["regime_matches"])
        attempts = pd.Series([d["n_attempts"] for d in days_])
        flat = [t for d in days_ for t in d["trades"]]
        fdf = pd.DataFrame(flat)
        final = pd.Series([d["trades"][-1]["outcome"] if d["trades"] else "NO_ENTRY" for d in days_])
        day_r = pd.Series([sum(t["r_multiple"] for t in d["trades"]) for d in days_])

        print(f"\n--- side={side} ({freq_str}) ---")
        print(f"days={n}  no_entry={n_no_entry}  regime_match={regime_match}/{n} ({regime_match/n*100:.1f}%)")
        print(f"attempts/day: mean={attempts.mean():.2f} median={attempts.median():.0f} p90={attempts.quantile(.9):.0f}")
        print("final outcome/day:", dict(final.value_counts()))
        if not fdf.empty:
            print(f"individual attempts={len(fdf)}  win_rate={( fdf['outcome']=='WIN').mean()*100:.1f}%  "
                  f"median_stop_pips={fdf['risk_pips'].median():.1f}")
        print(f"mean total R per day (all re-entries): {day_r.mean():+.3f}")

        report[side] = {
            "n_days": n, "n_no_entry": n_no_entry, "regime_match_pct": round(regime_match / n * 100, 1),
            "attempts_mean": round(float(attempts.mean()), 2), "attempts_median": float(attempts.median()),
            "attempts_p90": float(attempts.quantile(0.9)),
            "final_outcome": {str(k): int(v) for k, v in final.value_counts().items()},
            "n_attempts_total": int(len(fdf)),
            "attempt_win_rate": round(float((fdf["outcome"] == "WIN").mean() * 100), 1) if not fdf.empty else None,
            "median_stop_pips": round(float(fdf["risk_pips"].median()), 1) if not fdf.empty else None,
            "mean_stop_pips": round(float(fdf["risk_pips"].mean()), 1) if not fdf.empty else None,
            "mean_r_per_day": round(float(day_r.mean()), 3),
            "median_r_per_day": round(float(day_r.median()), 3),
            "pct_days_positive_r": round(float((day_r > 0).mean() * 100), 1),
        }
        if not fdf.empty:
            fdf.to_csv(os.path.join(OUT_DIR, f"mss_trade_sim_{freq_str}_{side}.csv"), index=False)

    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="eurusd")
    ap.parse_args()

    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} 1-minute bars")

    all_reports = {}
    for freq_str in ["5min", "15min"]:
        all_reports[freq_str] = run_for_timeframe(raw, freq_str)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "mss_higher_timeframe_report.json"), "w") as f:
        json.dump(all_reports, f, indent=2, default=str)
    print("\nSaved mss_higher_timeframe_report.json")
