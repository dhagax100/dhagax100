"""For the winning days whose FIRST 5-minute leg ended by hitting its own
stop (price ran past the 100% mark of the first ladder -- see
winning_days_retracement.py's ">100%"/LOSS-outcome group): does a SECOND
swing exceedance (a fresh MSS confirmation, in the same intended direction)
happen afterward, before the day's window ends? If so, build a second
0%-100% ladder from it exactly the same way as the first one, and measure
how deep price pulls back into THAT leg before the day finally resolves.

Same construction as run_for_timeframe in mss_retracement.py, just re-run
starting from the point where the first leg's stop was actually touched,
looking for the next confirmed swing exceedance after that point.
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine
from mss_higher_timeframe import resample, map_events_to_1m
from mss_retracement import find_setup_days

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} bars")

    won = pd.read_csv(os.path.join(OUT_DIR, "reversal_behavior_eurusd_2021_2025.csv"))
    won = won[won["reached_target"] == True]
    won_dates = set(won["date"].astype(str))

    freq_str = "5min"
    freq = pd.Timedelta(freq_str)
    res = resample(raw, freq_str)
    o, h, l, c = res["open"].values, res["high"].values, res["low"].values, res["close"].values
    mss_events, _, log = run_engine(o, h, l, c)
    mapped_mss = map_events_to_1m(mss_events, res.index, raw.index, freq)
    down_mss = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "down"])
    up_mss = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "up"])
    log_events = [{"bar": log["confirm_idx"][i], "kind": log["kind"][i], "price": log["price"][i]}
                  for i in range(len(log["kind"]))]
    mapped_log = map_events_to_1m(log_events, res.index, raw.index, freq)
    lows_1m = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 1])
    highs_1m = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 0])

    raw_h, raw_l, raw_c = raw["high"].values, raw["low"].values, raw["close"].values
    setups = [s for s in find_setup_days(raw) if str(s["date"]) in won_dates]

    def next_after(sorted_list, bar):
        import bisect
        i = bisect.bisect_right([x[0] for x in sorted_list], bar)
        return sorted_list[i] if i < len(sorted_list) else None

    results = {"high": [], "low": []}
    for s in setups:
        side, sweep_bar, window_end, target = s["side"], s["sweep_bar"], s["ext_end_bar"], (s["a_lo"] if s["side"] == "high" else s["a_hi"])
        direction = "short" if side == "high" else "long"
        pool = down_mss if direction == "short" else up_mss
        extreme_pool = lows_1m if direction == "short" else highs_1m

        entries = [(b, p) for b, p in pool if sweep_bar < b <= window_end and p is not None]
        if not entries:
            continue
        entry_bar1, stop1 = entries[0]
        nxt1 = next_after(extreme_pool, entry_bar1)
        if nxt1 is None or nxt1[0] > window_end:
            continue
        leg_extreme_bar1, leg_extreme1 = nxt1
        leg_range1 = (stop1 - leg_extreme1) if direction == "short" else (leg_extreme1 - stop1)
        if leg_range1 <= 0.5 * PIP:
            continue

        seg_h1 = raw_h[leg_extreme_bar1 + 1:window_end + 1]
        seg_l1 = raw_l[leg_extreme_bar1 + 1:window_end + 1]
        if len(seg_h1) == 0:
            continue
        if direction == "short":
            i_stop1 = int(np.argmax(seg_h1 >= stop1)) if (seg_h1 >= stop1).any() else None
            i_targ1 = int(np.argmax(seg_l1 <= target)) if (seg_l1 <= target).any() else None
        else:
            i_stop1 = int(np.argmax(seg_l1 <= stop1)) if (seg_l1 <= stop1).any() else None
            i_targ1 = int(np.argmax(seg_h1 >= target)) if (seg_h1 >= target).any() else None

        leg1_hit_stop = i_stop1 is not None and (i_targ1 is None or i_stop1 <= i_targ1)
        if not leg1_hit_stop:
            continue  # only care about days where leg 1's stop (the 100% level) was actually violated

        breach_bar1 = leg_extreme_bar1 + 1 + i_stop1
        row = {"date": s["date"], "side": side}

        entries2 = [(b, p) for b, p in pool if breach_bar1 < b <= window_end and p is not None]
        if not entries2:
            row["got_second_confirmation"] = False
            results[side].append(row)
            continue
        row["got_second_confirmation"] = True

        entry_bar2, stop2 = entries2[0]
        nxt2 = next_after(extreme_pool, entry_bar2)
        if nxt2 is None or nxt2[0] > window_end:
            row["second_leg_measurable"] = False
            results[side].append(row)
            continue
        leg_extreme_bar2, leg_extreme2 = nxt2
        leg_range2 = (stop2 - leg_extreme2) if direction == "short" else (leg_extreme2 - stop2)
        if leg_range2 <= 0.5 * PIP:
            row["second_leg_measurable"] = False
            results[side].append(row)
            continue

        seg_h2 = raw_h[leg_extreme_bar2 + 1:window_end + 1]
        seg_l2 = raw_l[leg_extreme_bar2 + 1:window_end + 1]
        if len(seg_h2) == 0:
            row["second_leg_measurable"] = False
            results[side].append(row)
            continue
        if direction == "short":
            i_stop2 = int(np.argmax(seg_h2 >= stop2)) if (seg_h2 >= stop2).any() else None
            i_targ2 = int(np.argmax(seg_l2 <= target)) if (seg_l2 <= target).any() else None
        else:
            i_stop2 = int(np.argmax(seg_l2 <= stop2)) if (seg_l2 <= stop2).any() else None
            i_targ2 = int(np.argmax(seg_h2 >= target)) if (seg_h2 >= target).any() else None

        if i_stop2 is not None and (i_targ2 is None or i_stop2 <= i_targ2):
            outcome2, resolve_i2 = "LOSS", i_stop2
        elif i_targ2 is not None:
            outcome2, resolve_i2 = "WIN", i_targ2
        else:
            outcome2, resolve_i2 = "OPEN", len(seg_h2) - 1

        if direction == "short":
            worst2 = seg_h2[:resolve_i2 + 1].max()
            max_retrace_pct2 = (worst2 - leg_extreme2) / leg_range2 * 100
        else:
            worst2 = seg_l2[:resolve_i2 + 1].min()
            max_retrace_pct2 = (leg_extreme2 - worst2) / leg_range2 * 100

        row["second_leg_measurable"] = True
        row["outcome2"] = outcome2
        row["max_retrace_pct2"] = round(float(max_retrace_pct2), 1)
        results[side].append(row)

    report = {"n_days_leg1_stopped": {}, "sides": {}}
    edges = [-1e9, 0, 25, 50, 75, 100, 1e9]
    labels = ["<0%", "0-25%", "25-50%", "50-75%", "75-100%", ">100%"]
    for side in ["high", "low"]:
        r = pd.DataFrame(results[side])
        n1 = len(r)
        n_got_2nd = int(r["got_second_confirmation"].sum())
        n_measurable = int(r.get("second_leg_measurable", pd.Series(dtype=bool)).sum()) if "second_leg_measurable" in r else 0
        measured = r[r.get("second_leg_measurable", False) == True] if "second_leg_measurable" in r else pd.DataFrame()

        side_report = {
            "n_days_leg1_stop_violated": n1,
            "n_got_second_swing_confirmation": n_got_2nd,
            "n_never_got_second_confirmation": n1 - n_got_2nd,
            "n_second_leg_measurable": int(len(measured)),
        }
        if not measured.empty:
            bucket = pd.cut(measured["max_retrace_pct2"], bins=edges, labels=labels)
            side_report["outcome2_counts"] = {k: int(v) for k, v in measured["outcome2"].value_counts().items()}
            side_report["retrace2_bucket"] = {k: int(v) for k, v in bucket.value_counts().reindex(labels).items()}
            side_report["retrace2_median"] = round(float(measured["max_retrace_pct2"].median()), 1)
        report["sides"][side] = side_report
        print(f"\n=== {side} ===")
        print(json.dumps(side_report, indent=2))
        r.to_csv(os.path.join(OUT_DIR, f"winning_days_second_leg_{side}.csv"), index=False)

    with open(os.path.join(OUT_DIR, "winning_days_second_leg_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\nSaved winning_days_second_leg_report.json")


if __name__ == "__main__":
    main()
