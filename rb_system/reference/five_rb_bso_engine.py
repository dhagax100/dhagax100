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

What is NOT reusable is `five_bso_engine.py`'s `main()`: it hard-gates
target H4 OBs through `weekly_control_engine.py`'s BUY_ONLY/SELL_ONLY/BOTH
permission ledger and OB's own state family (`pre_spent_state in (0,1,4)`).
Per `h4_rb_engine.py`'s own resolved finding, RB has no control-ledger
analog (`RB_Indicator_v1.pine` never mentions control/permission), so this
script's `main()` instead targets every H4 RB zone that was genuinely
impacted (`status()` reads `state==3`) AND was never stranded before that
impact (`pre_spent_state in (0, 1)` -- IRB or ARB, RB's two "still a live
POI" states; state 2/ORB is RB's stranded-and-dead state, the direct analog
of OB's OOB, correctly excluded the same way `pre_spent_ok` excludes OOB
for OB).

Run order: h4_rb_engine.py -> this script. Requires the same CSV/args.
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
import h4_rb_engine as h4rb                # noqa: E402
from five_bso_engine import (               # noqa: E402  (reused verbatim, POI-agnostic)
    run_bso_chain, structural_invalid_at, ledger_row, aggregate_5m, LEDGER_FIELDS,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="5m BSO engine for RB zones (reuses OB's POI-agnostic core)")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4))
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

    h4_bars = h4rb.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wrb.WeeklyRBEngine(minutes, h4_bars)
    h4_engine.run()
    h4_bar_starts = [b.start for b in h4_bars]

    # RB-specific target gate (see module docstring): impacted, and never
    # stranded (ORB) before that impact. No control-permission layer -- RB
    # has none (h4_rb_engine.py's own finding).
    targets = []
    for z in h4_engine.rbs:
        impacted = z.state == 3
        if not impacted or z.impact_time is None:
            continue
        if z.pre_spent_state not in (0, 1):
            continue  # was already ORB (stranded) before this impact -- dead POI, same as OB's OOB exclusion
        targets.append((z, z.impact_time, ""))  # no parent_weekly_id concept for RB (no control layer)

    print(f"{len(targets)} impacted, never-stranded H4 RB zones to run BSO on")

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
