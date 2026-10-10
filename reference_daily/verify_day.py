#!/usr/bin/env python3
"""Fast single-day verification tool (2026-10-05).

Formalizes the "fast hybrid" pattern used throughout the January
walkthrough: builds the Daily engine from the FULL multi-year history
(old POIs genuinely go back years and must stay visible), but builds
4H/1H/5m engines from only a short lead-in window before the target
date -- cuts a ~18-20 minute full run down to ~45-60 seconds, with no
loss of fidelity (same functions, same code paths, just differently
scoped inputs).

Usage:
    python3 verify_day.py 2025-01-08
    python3 verify_day.py 2025-01-08 --lead-months 3
    python3 verify_day.py 2025-01-08 --csv data/EURUSD_m1_BidAndAsk_2021-01-03_to_2026-09-30.csv

Prints, for the target date:
  - 4H/1H candidates with origin, impact, control state, stage, entry/result
  - full attempt detail (SL/TP/MFE/MAE) for any ENTERED candidate
  - the Daily control timeline (checkpoints with reasons) for the target day
  - the 1H abandonment ceiling (PDH/PDL wick chain) for both sides that day

This is the ONLY sanctioned way to check a single day's output -- do not
re-run the full multi-year generator for a one-day question; it produces
byte-identical results through the same compute_control_timeline/
compute_5m_trades code paths, just ~20x slower.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent / "reference_combined", _HERE.parent / "reference",
           _HERE.parent / "reference_rb", _HERE.parent / "reference_fvg",
           _HERE.parent / "reference_vi"):
    sys.path.insert(0, str(_p))

import weekly_ob_generator as wob           # noqa: E402
import weekly_combined_generator as wc      # noqa: E402
import daily_combined_generator as dc       # noqa: E402
import all_tf_combined_generator as atc     # noqa: E402

DISPLAY_TZ = ZoneInfo("Asia/Riyadh")
INPUT_TZ = ZoneInfo("UTC")
CLOSE_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DEFAULT_CSV = _HERE.parent / "data" / "EURUSD_m1_BidAndAsk_2001-11-28_to_2026-09-30.csv"


def disp(t):
    return wob.display_iso(t, DISPLAY_TZ) if t else None


def build_engines(csv_path: Path, date_str: str, lead_months: int):
    t0 = time.time()
    y, m, d = (int(x) for x in date_str.split("-"))
    cutoff = datetime(y, m, d, 23, 59, 59, tzinfo=DISPLAY_TZ).astimezone(UTC)

    full_minutes, _ = wob.load_minutes(csv_path, INPUT_TZ, "bid")
    full_minutes, _ = atc.strip_pre_week_open(full_minutes, DISPLAY_TZ)
    full_minutes = [x for x in full_minutes if x.t < cutoff]
    full_mt = [x.t for x in full_minutes]
    print(f"[{time.time()-t0:.1f}s] loaded full history: {len(full_minutes)} minutes", file=sys.stderr)

    # Daily engine: FULL history -- old POIs genuinely go back years.
    bars_d = dc.aggregate_days(full_minutes, CLOSE_TZ, 17, DISPLAY_TZ)
    d_engine = wc.WeeklyCombinedEngine(full_minutes, bars_d, origin_gap_window=None)
    d_engine.run()
    atc.mark_open_inside_trigger(d_engine)
    atc.mark_superseded_same_leg(d_engine, full_minutes, full_mt)
    d_zones_full = SimpleNamespace(
        ob_zones=list(d_engine.ob_zones), rb_zones=list(d_engine.rb_zones),
        fvg_zones=list(d_engine.fvg_zones), vi_zones=list(d_engine.vi_zones),
        w=d_engine.w, events=d_engine.events, msses=list(d_engine.msses))
    print(f"[{time.time()-t0:.1f}s] Daily engine built (full history)", file=sys.stderr)

    # Prewarm the MSS confirm cache on full history before switching to
    # the short window -- the cache keys off d_zones_full only, not
    # whatever minutes/mt happen to be passed afterward.
    atc.daily_controlling_bias(d_zones_full, cutoff, full_minutes, full_mt)
    gate_control_checkpoints = atc.compute_control_timeline(
        d_zones_full, full_minutes, full_mt, DISPLAY_TZ, cutoff)
    print(f"[{time.time()-t0:.1f}s] control checkpoints computed", file=sys.stderr)

    # 4H/1H/5m engines: short lead-in window, not the full history --
    # needs enough lead-in for PDL/PDH-rollback and swing/regime
    # continuity to have something to anchor to.
    short_start = (datetime(y, m, 1, tzinfo=DISPLAY_TZ) - timedelta(days=30 * lead_months)).astimezone(UTC)
    short_minutes = [x for x in full_minutes if x.t >= short_start]
    short_mt = [x.t for x in short_minutes]
    print(f"[{time.time()-t0:.1f}s] short window: {len(short_minutes)} minutes", file=sys.stderr)

    bars_h4 = dc.aggregate_hours(short_minutes, 4, CLOSE_TZ, 17, DISPLAY_TZ)
    h4_engine = wc.WeeklyCombinedEngine(short_minutes, bars_h4, origin_gap_window=None)
    h4_engine.run()
    atc.mark_open_inside_trigger(h4_engine)
    atc.mark_superseded_same_leg(h4_engine, short_minutes, short_mt)
    atc.apply_daily_bias_gate(h4_engine, "h4", d_zones_full, DISPLAY_TZ, short_minutes, short_mt,
                               control_checkpoints=gate_control_checkpoints)
    atc.exclude_old_intraday_zones(h4_engine)
    tf_full_h4 = SimpleNamespace(
        ob_zones=list(h4_engine.ob_zones), rb_zones=list(h4_engine.rb_zones),
        fvg_zones=list(h4_engine.fvg_zones), vi_zones=list(h4_engine.vi_zones),
        events=h4_engine.events, w=h4_engine.w,
        ambiguous_tie_bars=set(h4_engine.ambiguous_tie_bars))
    print(f"[{time.time()-t0:.1f}s] 4H engine built", file=sys.stderr)

    bars_h1 = dc.aggregate_hours(short_minutes, 1, CLOSE_TZ, 17, DISPLAY_TZ)
    h1_engine = wc.WeeklyCombinedEngine(short_minutes, bars_h1, origin_gap_window=None)
    h1_engine.run()
    atc.mark_open_inside_trigger(h1_engine)
    atc.mark_superseded_same_leg(h1_engine, short_minutes, short_mt)
    atc.apply_daily_bias_gate(h1_engine, "h1", d_zones_full, DISPLAY_TZ, short_minutes, short_mt,
                               control_checkpoints=gate_control_checkpoints)
    atc.exclude_old_intraday_zones(h1_engine)
    tf_full_h1 = SimpleNamespace(
        ob_zones=list(h1_engine.ob_zones), rb_zones=list(h1_engine.rb_zones),
        fvg_zones=list(h1_engine.fvg_zones), vi_zones=list(h1_engine.vi_zones),
        events=h1_engine.events, w=h1_engine.w,
        ambiguous_tie_bars=set(h1_engine.ambiguous_tie_bars))
    print(f"[{time.time()-t0:.1f}s] 1H engine built", file=sys.stderr)

    bars5 = dc.aggregate_minutes(short_minutes, 5)
    e5 = wc.WeeklyCombinedEngine(short_minutes, bars5, origin_gap_window=None)
    e5.run()
    print(f"[{time.time()-t0:.1f}s] 5m engine built", file=sys.stderr)

    return SimpleNamespace(
        t0=t0, cutoff=cutoff, full_minutes=full_minutes, full_mt=full_mt,
        d_engine=d_engine, d_zones_full=d_zones_full,
        gate_control_checkpoints=gate_control_checkpoints,
        short_minutes=short_minutes, short_mt=short_mt,
        h4_engine=h4_engine, h1_engine=h1_engine, e5=e5,
        tf_full_h4=tf_full_h4, tf_full_h1=tf_full_h1)


def report_day(ctx, date_str: str):
    window_start, window_end = atc.trading_window(date_str, DISPLAY_TZ)
    trades, ledger_rows = atc.compute_5m_trades(
        ctx.tf_full_h4, ctx.tf_full_h1, ctx.e5, ctx.short_minutes,
        window_start, window_end, DISPLAY_TZ, side="ALL", d_zones_full=ctx.d_zones_full)
    print(f"[{time.time()-ctx.t0:.1f}s] trades computed: {len(ledger_rows)} ledger rows", file=sys.stderr)

    origin_lookup = {}
    for tag, eng in (("H4", ctx.h4_engine), ("1H", ctx.h1_engine)):
        for kind, zones in (("OB", eng.ob_zones), ("RB", eng.rb_zones),
                            ("FVG", eng.fvg_zones), ("VI", eng.vi_zones)):
            for z in zones:
                idx = z.candle if hasattr(z, "candle") else z.left
                origin_lookup[(tag, f"{kind}#{z.id}")] = eng.w[idx].start

    print(f"\n4H/1H candidates for {date_str}, with origin:")
    entered_rows = []
    for row in ledger_rows:
        if not row["impact_riyadh"].startswith(date_str):
            continue
        origin = origin_lookup.get((row["tf"], row["poi"]))
        print(f"  {row['tf']:3s} {row['poi']:8s} {row['side']:4s}  origin={disp(origin)}  "
              f"impact={row['impact_riyadh']}  stage={row['stage']}  "
              f"control={row.get('control_state_at_impact','')}  "
              f"invalidated={row.get('invalidated_riyadh','')} ({row.get('invalidated_reason','')})  "
              f"entry={row.get('entry_riyadh','')}  result={row.get('result','')}")
        if row["stage"] == "ENTERED":
            entered_rows.append(row)

    for row in entered_rows:
        print(f"\nFull detail {row['poi']} (attempt {row.get('attempt')}):")
        for k, v in row.items():
            print(f"  {k}={v}")

    print(f"\nControl checkpoints on {date_str}:")
    day_start = datetime(*(int(x) for x in date_str.split("-")), tzinfo=DISPLAY_TZ).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    for t, s, owner, reason in ctx.gate_control_checkpoints:
        if day_start <= t < day_end:
            print(f"  {disp(t)}  ->  {s}  (1H owner: {owner})")
            print(f"      reason: {reason}")

    pdh_chain = atc.build_pdh_pdl_chain(ctx.full_minutes, ctx.full_mt, "BUY", DISPLAY_TZ,
                                         ctx.cutoff, control_checkpoints=ctx.gate_control_checkpoints)
    pdl_chain = atc.build_pdh_pdl_chain(ctx.full_minutes, ctx.full_mt, "SELL", DISPLAY_TZ,
                                         ctx.cutoff, control_checkpoints=ctx.gate_control_checkpoints)
    print(f"\n1H abandonment ceiling on {date_str}:")
    for label, chain in (("BUY/PDH", pdh_chain), ("SELL/PDL", pdl_chain)):
        ab = atc.chain_abandon_at(chain, date_str, DISPLAY_TZ)
        print(f"  {label}: abandon_at={disp(ab) if ab else None}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", help="target date, YYYY-MM-DD (Riyadh calendar day)")
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="path to the merged M1 CSV")
    ap.add_argument("--lead-months", type=int, default=2,
                     help="months of lead-in before the target month for 4H/1H/5m engines (default 2)")
    args = ap.parse_args()

    ctx = build_engines(Path(args.csv), args.date, args.lead_months)
    report_day(ctx, args.date)


if __name__ == "__main__":
    main()
