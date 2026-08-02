"""Retracement-into-the-confirmed-leg research, exactly as specified:

After MSS confirms (entry signal, stop = leg's origin swing -- the 100%
level), price keeps moving in the trade's favor and eventually prints a NEW
swing point in the trend's own direction (a fresh swing low after MSS-down,
a fresh swing high after MSS-up). That fresh swing is the 0% level -- the
far end of "the breaking leg." The leg is the price range between that fresh
extreme (0%) and the original stop (100%).

After the fresh extreme prints, does price pull back into that leg before
continuing to target? How far (0-25% / 25-50% / 50-75% / 75-100% / beyond
100%, i.e. the stop itself)? And if we waited for a limit fill at each of
those quartile levels instead of chasing the market, what would the
fill rate and win rate actually be?

This is a different question from entry_models.py's pullback test (that one
retraced into the pre-MSS reclaim leg, before any structural confirmation
existed). Here the retracement is INTO an already-confirmed MSS leg, so
whether adverse selection shows up here too is tested fresh, not assumed.

Swing/MSS detection runs on 5-minute and 15-minute candles (matching the
last round). Session levels, the sweep moment, and all execution/retracement
measurement use raw 1-minute bars throughout, for the same reasons as
mss_higher_timeframe.py.
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine
from mss_higher_timeframe import resample, map_events_to_1m, ASIAN_START_H, LONDON_KZ_START_H, LONDON_KZ_END_H, EXT_END_H

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR
COST = 1.0


def find_setup_days(raw):
    """Sweep detection, unchanged from every prior round."""
    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")
    out = []
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
        out.append({"date": day.date(), "side": side, "sweep_bar": sweep_bar,
                   "ext_end_bar": ext_end_bar, "a_hi": a_hi, "a_lo": a_lo})
    return out


def run_for_timeframe(raw, freq_str):
    freq = pd.Timedelta(freq_str)
    res = resample(raw, freq_str)
    o, h, l, c = res["open"].values, res["high"].values, res["low"].values, res["close"].values
    mss_events, _, log = run_engine(o, h, l, c)

    mapped_mss = map_events_to_1m(mss_events, res.index, raw.index, freq)
    down_mss = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "down"])
    up_mss = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "up"])

    # map every confirmed swing (not just MSS events) to a 1m bar, keeping
    # its kind and price, so we can find "the next swing low/high after bar X"
    log_events = [{"bar": log["confirm_idx"][i], "kind": log["kind"][i], "price": log["price"][i]}
                  for i in range(len(log["kind"]))]
    mapped_log = map_events_to_1m(log_events, res.index, raw.index, freq)
    lows_1m = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 1])
    highs_1m = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 0])

    raw_h, raw_l, raw_c = raw["high"].values, raw["low"].values, raw["close"].values
    setups = find_setup_days(raw)

    def next_after(sorted_list, bar):
        import bisect
        i = bisect.bisect_right([x[0] for x in sorted_list], bar)
        return sorted_list[i] if i < len(sorted_list) else None

    legs = []
    for s in setups:
        side, sweep_bar, window_end, target = s["side"], s["sweep_bar"], s["ext_end_bar"], (s["a_lo"] if s["side"] == "high" else s["a_hi"])
        direction = "short" if side == "high" else "long"
        pool = down_mss if direction == "short" else up_mss
        entries = [(b, p) for b, p in pool if sweep_bar < b <= window_end and p is not None]
        if not entries:
            continue
        entry_bar, stop_level = entries[0]

        extreme_pool = lows_1m if direction == "short" else highs_1m
        nxt = next_after(extreme_pool, entry_bar)
        if nxt is None or nxt[0] > window_end:
            continue
        leg_extreme_bar, leg_extreme = nxt
        leg_range = (stop_level - leg_extreme) if direction == "short" else (leg_extreme - stop_level)
        if leg_range <= 0.5 * PIP:
            continue

        seg_h = raw_h[leg_extreme_bar + 1:window_end + 1]
        seg_l = raw_l[leg_extreme_bar + 1:window_end + 1]
        if len(seg_h) == 0:
            continue

        if direction == "short":
            i_stop = int(np.argmax(seg_h >= stop_level)) if (seg_h >= stop_level).any() else None
            i_targ = int(np.argmax(seg_l <= target)) if (seg_l <= target).any() else None
        else:
            i_stop = int(np.argmax(seg_l <= stop_level)) if (seg_l <= stop_level).any() else None
            i_targ = int(np.argmax(seg_h >= target)) if (seg_h >= target).any() else None

        if i_stop is not None and (i_targ is None or i_stop <= i_targ):
            outcome, resolve_i = "LOSS", i_stop
        elif i_targ is not None:
            outcome, resolve_i = "WIN", i_targ
        else:
            outcome, resolve_i = "OPEN", len(seg_h) - 1

        if direction == "short":
            max_retrace_price = seg_h[:resolve_i + 1].max()
            max_retrace_pct = (max_retrace_price - leg_extreme) / leg_range * 100
        else:
            max_retrace_price = seg_l[:resolve_i + 1].min()
            max_retrace_pct = (leg_extreme - max_retrace_price) / leg_range * 100

        legs.append({
            "date": s["date"], "side": side, "direction": direction,
            "leg_extreme": leg_extreme, "stop_level": stop_level, "leg_range_pips": round(leg_range / PIP, 1),
            "outcome": outcome, "max_retrace_pct": round(float(max_retrace_pct), 1),
            "leg_extreme_bar": leg_extreme_bar, "window_end": window_end, "target": target,
        })
    return legs


def simulate_limit_entries(raw, legs, level_frac):
    """For each leg, would a limit order at level_frac (0=leg extreme,
    1=stop) have filled before resolution, and what's its own R outcome
    from the fill point forward (stop still at 100%, target unchanged)?"""
    raw_h, raw_l, raw_c = raw["high"].values, raw["low"].values, raw["close"].values
    rows = []
    for leg in legs:
        direction = leg["direction"]
        extreme, stop_level = leg["leg_extreme"], leg["stop_level"]
        limit = extreme + level_frac * (stop_level - extreme) if direction == "short" else extreme - level_frac * (extreme - stop_level)
        eb, we, target = leg["leg_extreme_bar"], leg["window_end"], leg["target"]
        seg_h = raw_h[eb + 1:we + 1]
        seg_l = raw_l[eb + 1:we + 1]
        if len(seg_h) == 0:
            continue
        if direction == "short":
            fill_mask = seg_h >= limit
        else:
            fill_mask = seg_l <= limit
        if not fill_mask.any():
            rows.append({"date": leg["date"], "filled": False, "outcome": None, "r_multiple": None})
            continue
        fi = int(np.argmax(fill_mask))
        fill_price = limit + COST * PIP if direction == "short" else limit - COST * PIP
        risk = (stop_level - fill_price) if direction == "short" else (fill_price - stop_level)
        if risk <= 0.2 * PIP:
            rows.append({"date": leg["date"], "filled": False, "outcome": None, "r_multiple": None})
            continue
        reward = (fill_price - target) if direction == "short" else (target - fill_price)

        h2, l2 = seg_h[fi + 1:], seg_l[fi + 1:]
        if len(h2) == 0:
            rows.append({"date": leg["date"], "filled": True, "outcome": "OPEN", "r_multiple": 0.0})
            continue
        if direction == "short":
            i_s = int(np.argmax(h2 >= stop_level)) if (h2 >= stop_level).any() else None
            i_t = int(np.argmax(l2 <= target)) if (l2 <= target).any() else None
        else:
            i_s = int(np.argmax(l2 <= stop_level)) if (l2 <= stop_level).any() else None
            i_t = int(np.argmax(h2 >= target)) if (h2 >= target).any() else None

        if i_s is not None and (i_t is None or i_s <= i_t):
            rows.append({"date": leg["date"], "filled": True, "outcome": "LOSS", "r_multiple": -1.0})
        elif i_t is not None:
            r = reward / risk if reward > 0 else 0.0
            rows.append({"date": leg["date"], "filled": True, "outcome": "WIN", "r_multiple": round(float(r), 3)})
        else:
            rows.append({"date": leg["date"], "filled": True, "outcome": "OPEN", "r_multiple": 0.0})
    return pd.DataFrame(rows)


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} 1-minute bars")

    pd.set_option("display.width", 160)
    report = {}
    for freq_str in ["5min", "15min"]:
        print(f"\n{'='*20} {freq_str} {'='*20}")
        legs = run_for_timeframe(raw, freq_str)
        ldf = pd.DataFrame(legs)
        print(f"Legs measured: {len(ldf)} (of setups where MSS fired AND a fresh leg-extreme swing formed in-window)")
        print("Outcome counts:", dict(ldf["outcome"].value_counts()))

        bins = [-1e9, 0, 25, 50, 75, 100, 1e9]
        labels = ["<0%", "0-25%", "25-50%", "50-75%", "75-100%", ">100% (stop)"]
        ldf["bucket"] = pd.cut(ldf["max_retrace_pct"], bins=bins, labels=labels)
        print("\nRetracement bucket, ALL legs:")
        print(ldf["bucket"].value_counts().reindex(labels).to_string())
        print("\nRetracement bucket, split by outcome:")
        print(pd.crosstab(ldf["bucket"], ldf["outcome"]).reindex(labels))
        print(f"\nMedian max retracement: {ldf['max_retrace_pct'].median():.1f}%  "
              f"(WIN days: {ldf.loc[ldf['outcome']=='WIN','max_retrace_pct'].median():.1f}%, "
              f"LOSS days: {ldf.loc[ldf['outcome']=='LOSS','max_retrace_pct'].median():.1f}%)")

        tf_report = {
            "n_legs": len(ldf), "outcome_counts": {k: int(v) for k, v in ldf["outcome"].value_counts().items()},
            "bucket_counts": {k: int(v) for k, v in ldf["bucket"].value_counts().reindex(labels).items()},
            "median_retrace_pct": round(float(ldf["max_retrace_pct"].median()), 1),
            "median_retrace_pct_win": round(float(ldf.loc[ldf["outcome"] == "WIN", "max_retrace_pct"].median()), 1),
            "median_retrace_pct_loss": round(float(ldf.loc[ldf["outcome"] == "LOSS", "max_retrace_pct"].median()), 1),
        }

        print("\n--- Limit-entry backtest at each quartile level ---")
        level_reports = {}
        for level in [0.0, 0.25, 0.5, 0.75]:
            sim = simulate_limit_entries(raw, legs, level)
            fill_rate = sim["filled"].mean() * 100
            filled = sim[sim["filled"]]
            win_rate = (filled["outcome"] == "WIN").mean() * 100 if not filled.empty else None
            mean_r = filled["r_multiple"].mean() if not filled.empty else None
            print(f"level={level:.2f}: fill_rate={fill_rate:.1f}%  n_filled={len(filled)}  "
                  f"win_rate={win_rate:.1f}%  mean_r={mean_r:.3f}" if win_rate is not None else
                  f"level={level:.2f}: fill_rate={fill_rate:.1f}%  n_filled=0")
            level_reports[str(level)] = {
                "fill_rate": round(float(fill_rate), 1), "n_filled": int(len(filled)),
                "win_rate": round(float(win_rate), 1) if win_rate is not None else None,
                "mean_r": round(float(mean_r), 3) if mean_r is not None else None,
                "total_r": round(float(filled["r_multiple"].sum()), 1) if not filled.empty else None,
            }
        tf_report["limit_entry_levels"] = level_reports
        report[freq_str] = tf_report

        os.makedirs(OUT_DIR, exist_ok=True)
        ldf.to_csv(os.path.join(OUT_DIR, f"mss_retracement_{freq_str}.csv"), index=False)

    with open(os.path.join(OUT_DIR, "mss_retracement_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("\nSaved mss_retracement_report.json")


if __name__ == "__main__":
    main()
