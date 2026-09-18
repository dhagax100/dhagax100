#!/usr/bin/env python3
"""5m BSO (Break-of-Swing Opportunity) engine for RB (Rejection Block) zones.

FINDING (task question, resolved by reading the code, not assumed): most of
`ob_reference/five_bso_engine.py` is already POI-type-agnostic. `run_bso()`,
`structural_invalid_at()`, `run_bso_chain()`, `ledger_row()` and
`aggregate_5m()` only ever touch a zone through `z.id`, `z.bullish`, `z.zb`,
`z.zt` (fields present, with the same meaning, on both `wob.Zone` and
`wrb.RbZone`) and a swing `Event` through `kind`/`swing`/`at`/`price`/
`confirm` (structurally identical dataclass in both `weekly_ob_generator.py`
and `weekly_rb_generator.py`). None of that code reads any OB-specific
field (`state`, `pre_spent_state`, `rejected`, `origin_state`) -- it
operates purely on "the current opportunity zone's box and side" plus "the
native swing structure at whatever bar grid it's given," exactly as the
task's own question anticipated. Those five functions are imported and
reused UNCHANGED from `ob_reference/five_bso_engine.py` below -- not
copied, not re-derived.

What is NOT reusable is `five_bso_engine.py`'s `main()` -- it is
OB-specific glue, not because control-gating itself doesn't apply to RB
(see below), but because it reads OB's own zone fields directly. This
script's own `main()` is written fresh but now applies the SAME control
gate OB's `main()` does.

SUPERSEDED (2026-09-18, later this same day, per explicit user decision):
`h4_rb_engine.py`'s original finding that RB's pine spec has no control
concept of its own is still true and is not being overridden. What changed
is the user's choice: rather than run RB's 5m BSO stage on every impacted,
never-stranded H4 RB zone unconditionally (this script's earlier
behavior), it now also requires that the SAME Weekly control permission
that gates OB's 5m BSO (`weekly_control_engine.py`, unmodified, run on OB
zones) permits that zone's direction at its impact time -- i.e. it reads
the `authorized` column `h4_rb_engine.py` now writes into `h4_rb_ledger.csv`
(computed there via the same `load_control_by_week`/`permits`/`control_at`
interface `h4_ob_engine.py` uses), and targets only rows where
`authorized == True`. See `RB_TRADING_SYSTEM_HANDOFF.md` SS8 for the
decision and verification evidence.

Run order: weekly_control_engine.py -> h4_rb_engine.py -> this script.
Requires the same CSV/args (plus h4_rb_engine.py's --control-ledger/
--week-close-zone/--week-close-hour if they differ from the defaults).
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ob_reference"))
import weekly_rb_generator as wrb          # noqa: E402  (verified RB engine)
import weekly_ob_generator as wob          # noqa: E402  (only for aggregate_weeks -- same week grid weekly_control_engine.py used)
import h4_rb_engine as h4rb                # noqa: E402  (also provides load_control_by_week/permits, identical to h4_ob_engine.py's)
from five_bso_engine import (               # noqa: E402  (reused verbatim, POI-agnostic)
    run_bso_chain, structural_invalid_at, ledger_row, aggregate_5m, LEDGER_FIELDS,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="5m BSO engine for RB zones (reuses OB's POI-agnostic core), "
                                             "gated by the same Weekly control permission that gates OB's 5m BSO")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4))
    p.add_argument("--week-close-zone", default="America/New_York", help="must match the run that produced --control-ledger")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24), help="must match the run that produced --control-ledger")
    p.add_argument("--control-ledger", default=None, help="path to weekly_control_ledger.csv; default: alongside input CSV")
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wrb.load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    mt = [m.t for m in minutes]

    base = csv_path.resolve().parent
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger.csv"
    if not control_path.exists():
        print("weekly_control_ledger.csv not found. Run weekly_control_engine.py first (same CSV, same "
              "--week-close-zone/--week-close-hour), or pass --control-ledger.", file=sys.stderr)
        return 2
    control_by_week = h4rb.load_control_by_week(control_path)
    close_tz = ZoneInfo(args.week_close_zone)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    week_starts = [w.start for w in weeks]

    def control_at(t) -> str:
        if t is None:
            return ""
        idx = bisect_left(week_starts, t)
        if idx >= len(week_starts) or week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(week_starts) - 1))
        return control_by_week.get(idx, "NONE")

    h4_bars = h4rb.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wrb.WeeklyRBEngine(minutes, h4_bars)
    h4_engine.run()
    h4_bar_starts = [b.start for b in h4_bars]

    # RB target gate: impacted, never stranded (ORB) before that impact,
    # AND the same Weekly control permission that gates OB's 5m BSO permits
    # this zone's direction at its impact time (see module docstring / SS8
    # of the handoff for the decision -- this mirrors h4_ob_engine.py's own
    # `authorized` computation exactly, just applied to RB zones).
    targets = []
    n_impacted_never_stranded = 0
    for z in h4_engine.rbs:
        impacted = z.state == 3
        if not impacted or z.impact_time is None:
            continue
        if z.pre_spent_state not in (0, 1):
            continue  # was already ORB (stranded) before this impact -- dead POI, same as OB's OOB exclusion
        n_impacted_never_stranded += 1
        ctrl = control_at(z.impact_time)
        if not h4rb.permits(ctrl, z.bullish):
            continue  # Weekly control did not permit this direction at impact time -- gated out
        targets.append((z, z.impact_time, ""))  # no parent_weekly_id concept for RB (no control-zone ancestry)

    print(f"{n_impacted_never_stranded} impacted, never-stranded H4 RB zones; "
          f"{len(targets)} also control-authorized -> BSO run on those")

    five_bars = aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = wrb.WeeklyRBEngine(minutes, five_bars)
    five_engine.run()

    rows = []
    for z, it, parent_id in targets:
        invalidated_at, invalidation_reason = structural_invalid_at(z, it, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = run_bso_chain(z, it, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            rows.append(ledger_row(z, it, parent_id, invalidation_reason, res, display_tz))

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "five_rb_bso_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["rb_id" if fld == "h4_ob_id" else fld for fld in LEDGER_FIELDS])
        wr.writeheader()
        for r in rows:
            r = dict(r)
            r["rb_id"] = r.pop("h4_ob_id")
            wr.writerow(r)

    stages = {}
    for r in rows:
        stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    print("Created: five_rb_bso_ledger.csv")
    print("Stage breakdown:", stages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
