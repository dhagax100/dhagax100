#!/usr/bin/env python3
"""Combined Weekly + 4H Pine viewer -- ONE script, ONE .pine file.

Reuses the Weekly layer completely unchanged via
weekly_ob_generator.write_ob_pine() (Weekly chart: swings/MSS/OB boxes/
table; 4H chart: Weekly OB boxes + impact lines only; every other
timeframe: nothing -- see that module for the SPEC.md SS17 gating).

Adds a SEPARATE H4 layer (own `if onH4:` block, own table -- Weekly and 4H
never share a table, per the user's explicit requirement) using the same
structure/OB engine (wob.WeeklyOBEngine on native 4H bars) and the same
impacted+authorized gating as h4_ob_engine.py: an H4 OB is drawn only if it
was genuinely eligible before impact (never OOB) AND its direction matched
the Weekly control permission active at its impact time.

Each drawn H4 OB also carries `parent_weekly_id`, read from
weekly_control_ledger.csv's `controlling_zone_id` column (SPEC.md SS17
"Parent Weekly POI").

Run order:
  1. weekly_control_engine.py   (writes weekly_control_ledger.csv)
  2. full_viewer.py             (this script)

Requires weekly_control_ledger.csv already generated next to the input CSV,
or pass --control-ledger.
"""
from __future__ import annotations

import argparse
import csv
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_ob_generator as wob  # noqa: E402  (locked engine, unmodified)
import h4_ob_engine as h4          # noqa: E402  (reuses its aggregate_h4/permits)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H Pine viewer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--box-body-minutes", type=int, default=60, choices=(1, 5, 15, 30, 60))
    p.add_argument("--origin-first-price", choices=("open", "close"), default="close")
    p.add_argument("--origin-body-offset-minutes", type=int, default=0, choices=range(-240, 241))
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=120, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--h4-anchor-hour", type=int, default=0, choices=range(4), help="UTC hour the 4H grid starts from. VERIFY against the real chart.")
    p.add_argument("--h4-pine-obs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--control-ledger", default=None)
    return p.parse_args()


def load_control_and_parent_by_week(path: Path) -> Tuple[Dict[int, str], Dict[int, str]]:
    control_by_week: Dict[int, str] = {}
    parent_by_week: Dict[int, str] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            idx = int(row["week_index"])
            control_by_week[idx] = row["control"]
            parent_by_week[idx] = row.get("controlling_zone_id", "")
    return control_by_week, parent_by_week


def pine_time(t: datetime) -> str:
    u = t.astimezone(UTC)
    return f"timestamp(\"GMT+0\", {u.year}, {u.month}, {u.day}, {u.hour}, {u.minute})"


def pine_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_h4_extra_lines(h4_engine, h4_bars, drawn: List[tuple], ob_cap: int, display_tz: ZoneInfo) -> List[str]:
    """Self-contained H4 layer: data packed into Pine arrays (one bulk
    `array.from(...)` statement per field, not one statement per OB), then a
    single small runtime `for` loop draws everything. `onH4` is reused from
    the Weekly layer's own declaration earlier in the same script.

    Earlier versions unrolled one box.new/label.new/table.cell per OB. At 70+
    drawn OBs that first blew a single if-block's statement limit (CE10205),
    and after batching into smaller blocks, blew the WHOLE SCRIPT's total
    statement limit (CE10295 "main body is too long"). Packing into arrays
    and looping once keeps the script's own size roughly constant regardless
    of how many OBs get drawn -- the fix TradingView's own error message
    points at ("try wrapping code in functions").

    Every drawn OB is guaranteed impacted (authorized requires it), so the
    box's right edge is simply the H4 bar containing that exact impact
    minute (h4_bars[z.stop].start) -- no per-bar "which timeframe am I on"
    resolution is needed here, unlike the Weekly layer, because this layer
    only ever renders on the 4H chart itself (onH4 gate)."""
    shown = drawn[-ob_cap:]
    n = len(shown)

    def arr(kind: str, values: List[str]) -> str:
        return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"

    lefts, tops, bottoms, rights, bulls, labels, parents, sides, bots5, tops5, trigs, eligs, impacts = ([] for _ in range(13))
    for z, tt, tp, et, ep, it, parent_id in shown:
        origin = h4_bars[z.candle]
        right_time = h4_bars[z.stop].start  # guaranteed valid: authorized => impacted => z.stop set
        lefts.append(pine_time(origin.start))
        tops.append(f"{z.zt:.5f}")
        bottoms.append(f"{z.zb:.5f}")
        rights.append(pine_time(right_time))
        bulls.append("true" if z.bullish else "false")
        label_text = f"#{z.id} {'BUY' if z.bullish else 'SELL'} (W{parent_id})"
        labels.append(f"\"{pine_text(label_text)}\"")
        parents.append(f"\"{pine_text('#' + parent_id if parent_id else '-')}\"")
        sides.append(f"\"{'BUY' if z.bullish else 'SELL'}\"")
        bots5.append(f"\"{z.zb:.5f}\"")
        tops5.append(f"\"{z.zt:.5f}\"")
        trig_txt = wob.display_iso(tt, display_tz) + (f" @ {tp:.5f}" if tp is not None else "")
        elig_txt = wob.display_iso(et, display_tz) + (f" @ {ep:.5f}" if ep is not None else "")
        trigs.append(f"\"{pine_text(trig_txt)}\"")
        eligs.append(f"\"{pine_text(elig_txt)}\"")
        impacts.append(f"\"{pine_text(wob.display_iso(it, display_tz))}\"")

    ids = [f"\"{'#' + str(z.id)}\"" for z, *_ in shown]

    lines: List[str] = [
        f"var table h4Ledger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        f"var array<int> h4Left = {arr('int', lefts)}",
        f"var array<float> h4Top = {arr('float', tops)}",
        f"var array<float> h4Bottom = {arr('float', bottoms)}",
        f"var array<int> h4Right = {arr('int', rights)}",
        f"var array<bool> h4Bull = {arr('bool', bulls)}",
        f"var array<string> h4Label = {arr('string', labels)}",
        f"var array<string> h4Id = {arr('string', ids)}",
        f"var array<string> h4Parent = {arr('string', parents)}",
        f"var array<string> h4Side = {arr('string', sides)}",
        f"var array<string> h4Bot5 = {arr('string', bots5)}",
        f"var array<string> h4Top5 = {arr('string', tops5)}",
        f"var array<string> h4Trig = {arr('string', trigs)}",
        f"var array<string> h4Elig = {arr('string', eligs)}",
        f"var array<string> h4Impact = {arr('string', impacts)}",
        "var bool h4Drawn = false",
        "if barstate.islast and not h4Drawn",
        "    if onH4",
        f"        table.cell(h4Ledger, 0, 0, \"4H OB\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 1, 0, \"Parent W\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 5, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 6, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        f"        table.cell(h4Ledger, 7, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        for i = 0 to array.size(h4Left) - 1",
        "            hCol = array.get(h4Bull, i) ? color.blue : color.black",
        "            box.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Right, i), array.get(h4Bottom, i), border_color=hCol, border_width=1, bgcolor=na, xloc=xloc.bar_time)",
        "            label.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hCol,85), textcolor=hCol, size=size.tiny)",
        "            line.new(array.get(h4Right, i), array.get(h4Bottom, i), array.get(h4Right, i), array.get(h4Top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)",
        "            table.cell(h4Ledger, 0, i + 1, array.get(h4Id, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 1, i + 1, array.get(h4Parent, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 2, i + 1, array.get(h4Side, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 3, i + 1, array.get(h4Bot5, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 4, i + 1, array.get(h4Top5, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 5, i + 1, array.get(h4Trig, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 6, i + 1, array.get(h4Elig, i), text_color=color.black, bgcolor=na)",
        "            table.cell(h4Ledger, 7, i + 1, array.get(h4Impact, i), text_color=color.black, bgcolor=na)",
        "        h4Drawn := true",
    ]
    return lines


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger.csv"
    if not control_path.exists():
        print("weekly_control_ledger.csv not found. Run weekly_control_engine.py first "
              "(same CSV, same --week-close-zone/--week-close-hour), or pass --control-ledger.", file=sys.stderr)
        return 2

    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    week_starts = [w.start for w in weeks]
    control_by_week, parent_by_week = load_control_and_parent_by_week(control_path)

    weekly_engine = wob.WeeklyOBEngine(minutes, weeks)
    weekly_engine.run()

    h4_bars = h4.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wob.WeeklyOBEngine(minutes, h4_bars)
    h4_engine.run()

    def control_and_parent_at(t: Optional[datetime]) -> Tuple[str, str]:
        if t is None:
            return "", ""
        idx = bisect_left(week_starts, t)
        if idx >= len(week_starts) or week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(week_starts) - 1))
        return control_by_week.get(idx, "NONE"), parent_by_week.get(idx, "")

    rows = []
    drawn = []
    for z in h4_engine.zones:
        et, ep = wob.eligibility_detail(h4_engine, z)
        tt, tp, _ = wob.trigger_display_detail(h4_engine, z)
        it = wob.impact_time(h4_engine, z, et)
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1, 4) if impacted else None
        ctrl, parent_id = control_and_parent_at(it) if impacted else ("", "")
        authorized = bool(impacted and pre_spent_ok and h4.permits(ctrl, z.bullish))
        rows.append(dict(
            id=z.id, side="BUY" if z.bullish else "SELL", type=h4.status(z),
            bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
            origin_utc=wob.iso(h4_bars[z.candle].start), origin_riyadh=wob.display_iso(h4_bars[z.candle].start, display_tz),
            trigger_riyadh=wob.display_iso(tt, display_tz), trigger_price="" if tp is None else f"{tp:.5f}",
            eligible_riyadh=wob.display_iso(et, display_tz), eligible_price="" if ep is None else f"{ep:.5f}",
            impact_riyadh=wob.display_iso(it, display_tz),
            control_at_impact=ctrl, parent_weekly_id=parent_id, authorized=authorized,
        ))
        if authorized:
            drawn.append((z, tt, tp, et, ep, it, parent_id))

    with (base / "h4_ob_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "side", "type", "bottom", "top", "origin_utc", "origin_riyadh",
                   "trigger_riyadh", "trigger_price", "eligible_riyadh", "eligible_price",
                   "impact_riyadh", "control_at_impact", "parent_weekly_id", "authorized"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    extra_lines = build_h4_extra_lines(h4_engine, h4_bars, drawn, args.h4_pine_obs, display_tz)

    wob.write_ob_pine(base, weekly_engine, args.pine_labels, args.pine_obs, args.pine_table,
                       args.box_body_minutes, display_tz, args.origin_first_price,
                       args.origin_body_offset_minutes, extra_lines=extra_lines, out_name="full_viewer.pine")
    wob.write_ledger(base, weekly_engine, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes)
    wob.write_report(base, minutes, weeks, warnings, weekly_engine, args)

    print("Created:")
    print("  full_viewer.pine   (Weekly layer unchanged + separate 4H layer/table)")
    print("  h4_ob_ledger.csv")
    print("  weekly_ob_ledger.csv, weekly_ob_swings.csv, weekly_ob_report.txt")
    print(f"{len(h4_bars)} 4H bars, {len(h4_engine.zones)} H4 OBs computed, {len(drawn)} drawn (impacted + authorized).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
