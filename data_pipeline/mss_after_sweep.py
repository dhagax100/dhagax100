"""For every sweep day, run the user's own swing/MSS engine (mss_engine.py)
continuously across the whole 5-year series, then ask exactly what was asked:

  Sweep of Asian HIGH first (their framing: implies the preceding leg was up)
    -> after the sweep, look for MSS DOWN (a swing low broken while regime
       was "up") -- this is the reversal-down signal, aligned with the short
       target at the Asian low.

  Sweep of Asian LOW first, mirrored -> look for MSS UP, target Asian high.

Reported per side:
  - what regime the engine actually says we're in at the moment of the sweep
    (tests the "sweep direction implies trend direction" assumption against
    the indicator itself, rather than assuming it)
  - how many days never see the expected MSS at all within the window
  - among days that do, how many separate MSS flips fire before the target is
    reached (or before the window ends, if it's never reached) -- multiple
    flips mean the setup would need to be re-armed and re-entered that many
    times, not traded once
  - whether firing the MSS at all correlates with actually reaching target
"""
import json
import os

import numpy as np
import pandas as pd

import optimize_strategy as opt
from mss_engine import run_engine

PIP = opt.PIP
OUT_DIR = opt.OUT_DIR


def main():
    raw = opt.load_raw("eurusd", 2021, 2025)
    print(f"Loaded {len(raw):,} bars")

    o, h, l, c = raw["open"].values, raw["high"].values, raw["low"].values, raw["close"].values
    mss_events, regime_at_bar = run_engine(o, h, l, c)
    print(f"Engine: {len(mss_events):,} MSS events over the full 5 years")

    # index MSS events by bar for fast windowed lookup
    mss_bar = np.array([e["bar"] for e in mss_events])
    mss_dir = np.array([e["dir"] for e in mss_events])

    contexts = opt.build_contexts(raw)
    idx_of = raw.index.get_indexer

    rows = []
    for ctx in contexts:
        sweep_bar_time = None  # recover the sweep's absolute timestamp from ctx timing
        # ctx doesn't carry the absolute bar index; recompute directly here
        # using the same window definitions as build_contexts for fidelity.
        pass

    # re-derive sweep bar index directly (build_contexts doesn't expose it)
    ASIAN_START_H, LONDON_KZ_START_H, LONDON_KZ_END_H, EXT_END_H = 20, 2, 5, 12
    days = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")

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

        want_dir = "down" if side == "high" else "up"
        target = a_lo if side == "high" else a_hi
        pre_sweep_regime = int(regime_at_bar[sweep_bar - 1]) if sweep_bar > 0 else 0

        # target-reach time, within the window, via raw bars (no lookahead
        # beyond what's needed to answer "did it reach and when")
        window = raw.iloc[sweep_bar:ext_end_bar + 1]
        if side == "high":
            reach_mask = window["low"] <= target
        else:
            reach_mask = window["high"] >= target
        target_bar = sweep_bar + int(np.argmax(reach_mask.values)) if reach_mask.any() else None

        end_bar = target_bar if target_bar is not None else ext_end_bar
        sel = (mss_bar > sweep_bar) & (mss_bar <= end_bar) & (mss_dir == want_dir)
        n_mss = int(sel.sum())

        rows.append({
            "date": day.date(), "side": side, "pre_sweep_regime": pre_sweep_regime,
            "regime_matches_assumption": (pre_sweep_regime == (1 if side == "high" else 2)),
            "target_reached": target_bar is not None,
            "n_mss_in_expected_dir": n_mss,
        })

    df = pd.DataFrame(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, "mss_after_sweep.csv"), index=False)
    pd.set_option("display.width", 160)

    report = {}
    for side, want_label in [("high", "MSS DOWN (short setup)"), ("low", "MSS UP (long setup)")]:
        sub = df[df["side"] == side]
        n = len(sub)
        regime_match = int(sub["regime_matches_assumption"].sum())
        never = int((sub["n_mss_in_expected_dir"] == 0).sum())
        happened = n - never
        dist = sub["n_mss_in_expected_dir"].clip(upper=4).value_counts().sort_index()
        reach_if_never = sub.loc[sub["n_mss_in_expected_dir"] == 0, "target_reached"].mean() * 100
        reach_if_happened = sub.loc[sub["n_mss_in_expected_dir"] > 0, "target_reached"].mean() * 100
        overall_reach = sub["target_reached"].mean() * 100

        print(f"\n=== Sweep {side.upper()} first -> looking for {want_label} ===")
        print(f"n days: {n}")
        print(f"regime at sweep matches assumption ({'up' if side=='high' else 'down'}): "
              f"{regime_match}/{n} ({regime_match/n*100:.1f}%)")
        print(f"MSS never fired in expected direction before target/window-end: {never} ({never/n*100:.1f}%)")
        print(f"MSS fired at least once: {happened} ({happened/n*100:.1f}%)")
        print("Distribution of # MSS flips before target/window-end (4 = 4+):")
        print(dist.to_string())
        print(f"Target-reach rate when MSS NEVER fired: {reach_if_never:.1f}%")
        print(f"Target-reach rate when MSS fired >=1x:   {reach_if_happened:.1f}%")
        print(f"Overall target-reach rate (all {side}-sweep days): {overall_reach:.1f}%")

        report[side] = {
            "n": n, "regime_match_pct": round(regime_match / n * 100, 1),
            "never_pct": round(never / n * 100, 1), "happened_pct": round(happened / n * 100, 1),
            "flip_distribution": {str(k): int(v) for k, v in dist.items()},
            "reach_rate_never": round(float(reach_if_never), 1),
            "reach_rate_happened": round(float(reach_if_happened), 1),
            "reach_rate_overall": round(float(overall_reach), 1),
        }

    with open(os.path.join(OUT_DIR, "mss_after_sweep_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\nSaved mss_after_sweep.csv, mss_after_sweep_report.json")


if __name__ == "__main__":
    main()
