#!/usr/bin/env python3
"""4H structure/OB engine -- Stage 7-9 of the build order (SPEC.md SS7,SS18-19).

Reuses the LOCKED structure/OB engine unmodified: wob.WeeklyOBEngine and
wob.Week are generic (their fields are just start/end/o/h/l/c/first/last),
so this script builds native 4-hour bars into that same Week shape and runs
the identical class on them. Trigger/eligibility/impact use the exact same
machinery as Weekly -- "the same weekly engine in terms of trigger,
eligibility and impact," per spec.

Gating: an impacted 4H OB is only drawn in the Pine output if BOTH:
  1. It was a genuine eligible OB before impact (pre-impact state was
     IFOB/AOB/AIFOB, never OOB) -- "not the OOBs."
  2. Its direction matches the Weekly control permission (from
     weekly_control_engine.py's ledger) that was active at its impact time
     -- SPEC.md SS18: "For every direction permitted by the Weekly control
     state, hunt valid H4 POIs."
Every other computed 4H OB (pending/never-eligible/never-impacted/OOB/off
-permission) is still written to the CSV ledger for audit, just never drawn.

This is a FIRST PASS. The 4H candle grid anchor (default 00:00 UTC) is the
first thing to verify against the real FXCM chart -- see weekly_control's
own timezone saga for why this cannot be assumed correct without a check.

Requires weekly_control_ledger.csv already generated (see
weekly_control_engine.py) next to the input CSV, or pass --control-ledger.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_ob_generator as wob  # noqa: E402  (locked engine, unmodified)

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="4H structure/OB engine, gated by Weekly control permission")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York", help="must match the run that produced --control-ledger")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24), help="must match the run that produced --control-ledger")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4), help="UTC hour the 4H grid starts from (1 => 01/05/09/13/17/21 UTC = 04/08/12/16/20/00 Riyadh). Chart-verified 2026-09-16 against a real FXCM 4H candle open at 16:00 Riyadh (=13:00 UTC).")
    p.add_argument("--control-ledger", default=None, help="path to weekly_control_ledger.csv; default: alongside input CSV")
    p.add_argument("--pine-obs", type=int, default=200, choices=range(1, 451))
    return p.parse_args()


def aggregate_h4(minutes: List["wob.Minute"], anchor_hour: int) -> List["wob.Week"]:
    """Native 4-hour bars aligned to anchor_hour UTC. Reuses wob.Week's shape
    (start,end,o,h,l,c,first,last) unmodified -- it is generic, not Weekly
    -specific. Gaps (weekend, missing export minutes) simply produce no bar
    for that slot, same policy as aggregate_weeks."""
    bars: List["wob.Week"] = []
    i, n = 0, len(minutes)
    while i < n:
        t = minutes[i].t
        epoch_hours = int((t - EPOCH).total_seconds() // 3600)
        grid_hours = ((epoch_hours - anchor_hour) // 4) * 4 + anchor_hour
        start = EPOCH + timedelta(hours=grid_hours)
        end = start + timedelta(hours=4)
        j = i + 1
        high, low = minutes[i].h, minutes[i].l
        while j < n and minutes[j].t < end:
            high = max(high, minutes[j].h)
            low = min(low, minutes[j].l)
            j += 1
        bars.append(wob.Week(start, end, minutes[i].o, high, low, minutes[j - 1].c, i, j))
        i = j
    return bars


def load_control_by_week(path: Path) -> Dict[int, str]:
    out: Dict[int, str] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[int(row["week_index"])] = row["control"]
    return out


def permits(control: str, bullish: bool) -> bool:
    if bullish:
        return control in ("BUY_ONLY", "BOTH")
    return control in ("SELL_ONLY", "BOTH")


def status(z: "wob.Zone") -> str:
    if z.rejected:
        return "REJECTED"
    return wob.STATE[z.pre_spent_state if z.state == 3 else z.state]


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger.csv"
    if not control_path.exists():
        print("weekly_control_ledger.csv not found. Run weekly_control_engine.py first (same CSV, same "
              "--week-close-zone/--week-close-hour), or pass --control-ledger.", file=sys.stderr)
        return 2

    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    week_starts = [w.start for w in weeks]
    control_by_week = load_control_by_week(control_path)

    h4_bars = aggregate_h4(minutes, args.h4_anchor_hour)
    engine = wob.WeeklyOBEngine(minutes, h4_bars)
    engine.run()

    def control_at(t: Optional[datetime]) -> str:
        if t is None:
            return ""
        idx = bisect_left(week_starts, t)
        if idx >= len(week_starts) or week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(week_starts) - 1))
        return control_by_week.get(idx, "NONE")

    rows = []
    drawn = []
    for z in engine.zones:
        et, ep = wob.eligibility_detail(engine, z)
        tt, tp, _ = wob.trigger_display_detail(engine, z)
        it = wob.impact_time(engine, z, et)
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1, 4) if impacted else None
        ctrl = control_at(it) if impacted else ""
        authorized = bool(impacted and pre_spent_ok and permits(ctrl, z.bullish))
        rows.append(dict(
            id=z.id, side="BUY" if z.bullish else "SELL", type=status(z),
            bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
            origin_utc=wob.iso(h4_bars[z.candle].start), origin_riyadh=wob.display_iso(h4_bars[z.candle].start, display_tz),
            trigger_riyadh=wob.display_iso(tt, display_tz), trigger_price="" if tp is None else f"{tp:.5f}",
            eligible_riyadh=wob.display_iso(et, display_tz), eligible_price="" if ep is None else f"{ep:.5f}",
            impact_riyadh=wob.display_iso(it, display_tz),
            control_at_impact=ctrl, authorized=authorized,
        ))
        if authorized:
            drawn.append((z, tt, tp, et, ep, it))

    with (base / "h4_ob_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                             ["id", "side", "type", "bottom", "top", "origin_utc", "origin_riyadh",
                              "trigger_riyadh", "trigger_price", "eligible_riyadh", "eligible_price",
                              "impact_riyadh", "control_at_impact", "authorized"])
        wr.writeheader()
        wr.writerows(rows)

    write_pine(base, engine, h4_bars, drawn, args.pine_obs, display_tz)

    with (base / "h4_ob_report.txt").open("w", encoding="utf-8") as f:
        f.write("4H STRUCTURE/OB ENGINE -- FIRST PASS, UNVERIFIED\n\n")
        f.write(f"4H bars: {len(h4_bars)}  (grid anchor: {args.h4_anchor_hour:02d}:00 UTC -- VERIFY against the real FXCM chart first)\n")
        f.write(f"4H OBs computed: {len(engine.zones)}\n")
        f.write(f"Impacted (state=SPENT): {sum(1 for z in engine.zones if z.state == 3)}\n")
        f.write(f"Drawn (impacted + pre-eligible, not OOB + control-authorized at impact): {len(drawn)}\n")
        f.write("\nEvery row in h4_ob_ledger.csv is kept for audit even when not drawn; "
                "'authorized' is False for: never impacted, was OOB before impact, or impacted "
                "while the Weekly control state did not permit that direction.\n")

    print("Created:")
    print("  h4_ob_ledger.csv")
    print("  h4_ob_viewer.pine")
    print("  h4_ob_report.txt")
    print(f"{len(h4_bars)} 4H bars, {len(engine.zones)} OBs computed, {len(drawn)} drawn (impacted + authorized).")
    return 0


def pine_time(t: datetime) -> str:
    u = t.astimezone(UTC)
    return f"timestamp(\"GMT+0\", {u.year}, {u.month}, {u.day}, {u.hour}, {u.minute})"


def pine_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_pine(base: Path, engine, h4_bars, drawn, ob_cap: int, display_tz: ZoneInfo) -> None:
    shown = drawn[-ob_cap:]
    lines = [
        "//@version=6",
        "indicator(\"FXCM 4H OB - Python Reference (control-authorized, impacted only)\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// Draws ONLY 4H OBs that: (1) were genuinely eligible before impact (never OOB),",
        "// (2) actually got impacted, and (3) whose direction matched the Weekly control",
        "// permission active at that impact time. Everything else is in h4_ob_ledger.csv only.",
        "// Attach to EURUSD, FXCM, any timeframe <= 4H.",
        "var table ledger = table.new(position.top_right, 7, " + str(len(shown) + 1) + ", border_width=1)",
    ]
    impact_vars: Dict[int, str] = {}
    for z, tt, tp, et, ep, it in shown:
        if it is not None:
            name = f"impact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = pine_time(it)
            lines += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]
    lines.append("if barstate.islast")
    right_edge = engine.m[-1].t + timedelta(days=30)
    for z, tt, tp, et, ep, it in shown:
        origin = h4_bars[z.candle]
        col = "color.blue" if z.bullish else "color.black"
        fallback_right = it or right_edge
        right = f"(na({impact_vars[z.id]}) ? {pine_time(fallback_right)} : {impact_vars[z.id]})" if it is not None else pine_time(fallback_right)
        lines.append(f"    box.new({pine_time(origin.start)}, {z.zt:.5f}, {right}, {z.zb:.5f}, border_color={col}, border_width=1, bgcolor=na, xloc=xloc.bar_time)")
        label_text = f"#{z.id} {'BUY' if z.bullish else 'SELL'}"
        lines.append(f"    label.new({pine_time(origin.start)}, {z.zt:.5f}, \"{label_text}\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new({col},85), textcolor={col}, size=size.tiny)")
        if it is not None:
            lines.append(f"    line.new({right}, {z.zb:.5f}, {right}, {z.zt:.5f}, xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)")
    lines += [
        "    table.clear(ledger, 0, 0, 6, " + str(len(shown)) + ")",
        "    table.cell(ledger, 0, 0, \"4H OB\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 1, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 2, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 3, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 4, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 5, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.green,15))",
        "    table.cell(ledger, 6, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.green,15))",
    ]
    for row, (z, tt, tp, et, ep, it) in enumerate(shown, 1):
        trig = wob.display_iso(tt, display_tz) + (f" @ {tp:.5f}" if tp is not None else "")
        elig = wob.display_iso(et, display_tz) + (f" @ {ep:.5f}" if ep is not None else "")
        vals = [f"#{z.id}", "BUY" if z.bullish else "SELL", f"{z.zb:.5f}", f"{z.zt:.5f}", trig, elig, wob.display_iso(it, display_tz)]
        for col, v in enumerate(vals):
            lines.append(f"    table.cell(ledger, {col}, {row}, \"{pine_text(v)}\", text_color=color.black, bgcolor=na)")
    lines.append("")
    (base / "h4_ob_viewer.pine").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
