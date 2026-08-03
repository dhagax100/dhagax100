"""The corrected, zone-gated version of the 1-minute re-entry simulation.

Fixes a real scoping gap in the previous round (winning_days_1m_reentry.py):
that script let 1-minute entries fire ANYWHERE in the post-sweep window,
not only while price was actually sitting inside the 50-100% zone of the
active 5-minute ladder. That's why the attempt counts looked too high --
some "attempts" were entries taken outside the zone the user actually
described. This version fixes that.

Two setups, run as one continuous state machine per day:

  Setup 1: after the sweep and the first 5m MSS confirmation, a ladder
  forms (0% = fresh extreme, 100% = the broken swing / stop). 1-minute
  entries are only allowed while price is between the 50% and 100% price
  levels of THIS ladder, and only if no trade is currently open. If an
  entry's stop is hit, that IS "the ladder's 100% level violated" -- by
  construction the same event.

  Setup 2: once setup 1's ladder is violated, we look for the next 5m MSS
  confirmation (exactly as in winning_days_second_leg.py) to build a SECOND
  ladder, and repeat: 1-minute entries only inside ITS 50-100% zone.

  If the second ladder is ALSO violated, we stop -- a third ladder was not
  part of what was specified, so those days are reported separately as
  "still unresolved by these two setups," not silently folded into a loss.

No lookahead: every price level used at any decision point is only ever
one that was already fully known at that point in time.
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
COST = 1.0


def zone_bounds(extreme, stop, direction):
    """Price bounds of the 50-100% region of a ladder. 100% is always the
    stop; 50% is the halfway price between the fresh extreme and the stop."""
    half = extreme + 0.5 * (stop - extreme) if direction == "short" else extreme - 0.5 * (extreme - stop)
    lo, hi = (half, stop) if direction == "short" else (stop, half)
    return lo, hi  # price interval; for short, zone is [half, stop] (higher prices); for long, [stop, half]


def in_zone(price, extreme, stop, direction):
    if direction == "short":
        half = extreme + 0.5 * (stop - extreme)
        return half <= price <= stop
    else:
        half = extreme - 0.5 * (extreme - stop)
        return stop <= price <= half


def run_ladder_entries(raw_h, raw_l, raw_c, entries, extreme, stop, extreme_bar, window_end, target, direction, cost=COST):
    """entries: full (bar, leg_price) MSS list for this direction, unfiltered.
    Restrict to those inside [extreme_bar, window_end] AND whose entry price
    sits in the ladder's 50-100% zone. Run sequential re-entry within just
    this ladder; stop the moment one attempt's stop is hit (== ladder
    violated) rather than searching for a same-ladder re-entry beyond that."""
    candidates = [(b, p) for b, p in entries if extreme_bar < b <= window_end]
    trades = []
    for e_bar, _unused_leg_price in candidates:
        entry_price_raw = raw_c[e_bar]
        if not in_zone(entry_price_raw, extreme, stop, direction):
            continue  # outside the 50-100% zone -- not a valid attempt under this setup
        entry_price = entry_price_raw - cost * PIP if direction == "short" else entry_price_raw + cost * PIP
        risk = (stop - entry_price) if direction == "short" else (entry_price - stop)
        if risk <= 0.2 * PIP:
            continue
        reward = (entry_price - target) if direction == "short" else (target - entry_price)

        h_seg = raw_h[e_bar + 1:window_end + 1]
        l_seg = raw_l[e_bar + 1:window_end + 1]
        if len(h_seg) == 0:
            break
        if direction == "short":
            i_stop = int(np.argmax(h_seg >= stop)) if (h_seg >= stop).any() else None
            i_targ = int(np.argmax(l_seg <= target)) if (l_seg <= target).any() else None
        else:
            i_stop = int(np.argmax(l_seg <= stop)) if (l_seg <= stop).any() else None
            i_targ = int(np.argmax(h_seg >= target)) if (h_seg >= target).any() else None

        if i_stop is not None and (i_targ is None or i_stop <= i_targ):
            trades.append({"entry_bar": e_bar, "outcome": "LOSS", "r_multiple": -1.0, "risk_pips": round(risk / PIP, 1)})
            return trades, "LADDER_VIOLATED", e_bar + 1 + i_stop
        elif i_targ is not None:
            r = reward / risk if reward > 0 else 0.0
            trades.append({"entry_bar": e_bar, "outcome": "WIN", "r_multiple": round(float(r), 3), "risk_pips": round(risk / PIP, 1)})
            return trades, "WIN", e_bar + 1 + i_targ
        else:
            trades.append({"entry_bar": e_bar, "outcome": "OPEN", "r_multiple": 0.0, "risk_pips": round(risk / PIP, 1)})
            return trades, "OPEN", window_end
    return trades, "ZONE_NEVER_REACHED_OR_NO_VALID_ENTRY", None


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} bars")

    won = pd.read_csv(os.path.join(OUT_DIR, "reversal_behavior_eurusd_2021_2025.csv"))
    won = won[won["reached_target"] == True]
    won_dates = set(won["date"].astype(str))

    o1, h1, l1, c1 = raw["open"].values, raw["high"].values, raw["low"].values, raw["close"].values
    mss_events_1m, _, _ = run_engine(o1, h1, l1, c1)
    down_1m = sorted([(e["bar"], e["leg_price"]) for e in mss_events_1m if e["dir"] == "down"])
    up_1m = sorted([(e["bar"], e["leg_price"]) for e in mss_events_1m if e["dir"] == "up"])

    freq_str = "5min"
    freq = pd.Timedelta(freq_str)
    res = resample(raw, freq_str)
    o5, h5, l5, c5 = res["open"].values, res["high"].values, res["low"].values, res["close"].values
    mss_events_5m, _, log = run_engine(o5, h5, l5, c5)
    mapped_mss = map_events_to_1m(mss_events_5m, res.index, raw.index, freq)
    down_5m = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "down"])
    up_5m = sorted([(e["bar_1m"], e["leg_price"]) for e in mapped_mss if e["dir"] == "up"])
    log_events = [{"bar": log["confirm_idx"][i], "kind": log["kind"][i], "price": log["price"][i]} for i in range(len(log["kind"]))]
    mapped_log = map_events_to_1m(log_events, res.index, raw.index, freq)
    lows_1m_swings = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 1])
    highs_1m_swings = sorted([(e["bar_1m"], e["price"]) for e in mapped_log if e["kind"] == 0])

    raw_h, raw_l, raw_c = raw["high"].values, raw["low"].values, raw["close"].values
    setups = [s for s in find_setup_days(raw) if str(s["date"]) in won_dates]

    def next_after(sorted_list, bar):
        import bisect
        i = bisect.bisect_right([x[0] for x in sorted_list], bar)
        return sorted_list[i] if i < len(sorted_list) else None

    day_results = {"high": [], "low": []}
    for s in setups:
        side, sweep_bar, window_end, target = s["side"], s["sweep_bar"], s["ext_end_bar"], (s["a_lo"] if s["side"] == "high" else s["a_hi"])
        direction = "short" if side == "high" else "long"
        pool5 = down_5m if direction == "short" else up_5m
        pool1 = down_1m if direction == "short" else up_1m
        extreme_pool = lows_1m_swings if direction == "short" else highs_1m_swings

        entries5 = [(b, p) for b, p in pool5 if sweep_bar < b <= window_end and p is not None]
        result = {"date": s["date"], "side": side, "asian_range_pips": round((s["a_hi"] - s["a_lo"]) / PIP, 1)}
        if not entries5:
            result["status"] = "NO_5M_MSS_AT_ALL"
            day_results[side].append(result)
            continue
        entry5_bar1, stop1 = entries5[0]
        nxt1 = next_after(extreme_pool, entry5_bar1)
        if nxt1 is None or nxt1[0] > window_end:
            result["status"] = "NO_LADDER1_EXTREME"
            day_results[side].append(result)
            continue
        extreme_bar1, extreme1 = nxt1
        leg_range1 = (stop1 - extreme1) if direction == "short" else (extreme1 - stop1)
        if leg_range1 <= 0.5 * PIP:
            result["status"] = "LADDER1_TOO_THIN"
            day_results[side].append(result)
            continue

        trades1, status1, breach_bar1 = run_ladder_entries(raw_h, raw_l, raw_c, pool1, extreme1, stop1, extreme_bar1, window_end, target, direction)
        result["setup1_trades"] = trades1
        result["setup1_status"] = status1

        all_trades = list(trades1)
        if status1 in ("WIN", "OPEN", "ZONE_NEVER_REACHED_OR_NO_VALID_ENTRY"):
            result["final_status"] = status1
            result["setup2_used"] = False
            if all_trades:  # at least one real attempt was taken this day -- record its R
                result["all_trades_r_sum"] = round(float(sum(t["r_multiple"] for t in all_trades)), 3)
            day_results[side].append(result)
            continue

        # setup 1's ladder was violated -- look for setup 2's ladder
        entries5_2 = [(b, p) for b, p in pool5 if breach_bar1 < b <= window_end and p is not None]
        if not entries5_2:
            result["final_status"] = "LADDER1_VIOLATED_NO_SETUP2_CONFIRMATION"
            result["setup2_used"] = False
            day_results[side].append(result)
            continue
        entry5_bar2, stop2 = entries5_2[0]
        nxt2 = next_after(extreme_pool, entry5_bar2)
        if nxt2 is None or nxt2[0] > window_end:
            result["final_status"] = "LADDER1_VIOLATED_SETUP2_NO_EXTREME"
            result["setup2_used"] = False
            day_results[side].append(result)
            continue
        extreme_bar2, extreme2 = nxt2
        leg_range2 = (stop2 - extreme2) if direction == "short" else (extreme2 - stop2)
        if leg_range2 <= 0.5 * PIP:
            result["final_status"] = "LADDER1_VIOLATED_SETUP2_TOO_THIN"
            result["setup2_used"] = False
            day_results[side].append(result)
            continue

        trades2, status2, breach_bar2 = run_ladder_entries(raw_h, raw_l, raw_c, pool1, extreme2, stop2, extreme_bar2, window_end, target, direction)
        result["setup2_trades"] = trades2
        result["setup2_status"] = status2
        result["setup2_used"] = True
        all_trades += trades2

        if status2 == "LADDER_VIOLATED":
            result["final_status"] = "BOTH_LADDERS_VIOLATED"
        else:
            result["final_status"] = status2  # WIN / OPEN / ZONE_NEVER_REACHED_OR_NO_VALID_ENTRY

        result["all_trades_r_sum"] = round(float(sum(t["r_multiple"] for t in all_trades)), 3)
        day_results[side].append(result)

    with open(os.path.join(OUT_DIR, "corrected_zone_simulation_raw.json"), "w") as f:
        json.dump(day_results, f, indent=2, default=str)

    report = {}
    for side in ["high", "low"]:
        rs = day_results[side]
        n = len(rs)
        final_counts = pd.Series([r.get("final_status", r.get("status")) for r in rs]).value_counts()
        all_attempts = [t for r in rs for t in r.get("setup1_trades", []) + r.get("setup2_trades", [])]
        wins = [t for t in all_attempts if t["outcome"] == "WIN"]
        losses = [t for t in all_attempts if t["outcome"] == "LOSS"]
        r_sums = [r["all_trades_r_sum"] for r in rs if "all_trades_r_sum" in r]

        print(f"\n=== {side} ===  n_days={n}")
        print("final status counts:")
        print(final_counts.to_string())
        print(f"total attempts across all days: {len(all_attempts)}  win={len(wins)}  loss={len(losses)}  "
              f"win_rate={len(wins)/len(all_attempts)*100:.1f}%" if all_attempts else "no attempts")
        if r_sums:
            print(f"mean total R per day (days with at least 1 attempt): {np.mean(r_sums):.3f}  median: {np.median(r_sums):.3f}")

        report[side] = {
            "n_days": n, "final_status_counts": {k: int(v) for k, v in final_counts.items()},
            "n_attempts": len(all_attempts), "n_wins": len(wins), "n_losses": len(losses),
            "attempt_win_rate_pct": round(len(wins) / len(all_attempts) * 100, 1) if all_attempts else None,
            "mean_r_per_day_with_attempts": round(float(np.mean(r_sums)), 3) if r_sums else None,
            "median_r_per_day_with_attempts": round(float(np.median(r_sums)), 3) if r_sums else None,
            "n_days_with_attempts": len(r_sums),
        }

    with open(os.path.join(OUT_DIR, "corrected_zone_simulation_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\nSaved corrected_zone_simulation_report.json + _raw.json")


if __name__ == "__main__":
    main()
