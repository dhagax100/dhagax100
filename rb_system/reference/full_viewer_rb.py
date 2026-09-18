#!/usr/bin/env python3
"""Combined Weekly + 4H Pine viewer for RB (Rejection Block) zones.

Parallel to `ob_reference/full_viewer.py`, but for RB, not OB, and
deliberately smaller in scope: RB has no weekly-control gating layer and no
BSO-lines layer requirement from the task, so this script draws exactly
what `RB_Indicator_v1.pine`'s own header (lines 1-33) specifies for RB
zones -- nothing more:
  - Weekly RB zones + swing/MSS labels + a ledger table, on the Weekly
    chart (reuses `weekly_rb_generator.WeeklyRBEngine` unchanged).
  - H4 RB zones + a ledger table, on the H4 chart (reuses `h4_rb_engine`'s
    own `aggregate_h4` + `WeeklyRBEngine` reuse, same as h4_rb_engine.py).
  - H4 RB boxes ALSO render on the 5m chart (no table there), same
    cross-timeframe convention `full_viewer.py` uses for its H4 OB layer.

Drawing conventions, taken verbatim from `RB_Indicator_v1.pine`'s header
(the ONLY source for RB drawing rules per this project's own discipline):
  "Drawing: dashed border, hollow (no fill). IRB = blue(bull)/black(bear)
  by its own raw-wick label. ARB = green, fixed. ORB = red, fixed, hidden
  on 5m/1h/4h like OOB/OFVG (same 'never traded there' reasoning)."
So: every RB box is drawn with `border_style=line.style_dashed`,
`bgcolor=na` (hollow). Colour: IRB uses blue if bullish else black (by RAW
WICK label, i.e. `z.bullish`, unaffected by which hunt fired it -- see
`weekly_rb_generator.py`'s own `bullish` field, already the raw-wick
label). ARB is always green. A zone currently ORB (stranded, `state==2`,
or `pre_spent_state==2` once SPENT) is drawn red, and is skipped entirely
on the H4 and 5m charts (`onH4`/`onFive`) -- it is only ever drawn on the
Weekly chart. `RB_Indicator_v1.pine`'s comment flags this convention as
possibly needing revisiting for RB ("flag if RB shouldn't follow that
convention") -- not changed here without a fresh instruction; carried over
as-is per that comment's own instruction to flag rather than silently
alter it. No 1h layer exists in this Python reference at all (no native 1h
engine has been built for either OB or RB), so the "hidden on ... 1h"
part of that convention has nothing to apply to yet.

Run: no external ledger dependency (RB has no control-ledger prerequisite,
per h4_rb_engine.py's own resolved finding) -- this script only needs the
input CSV.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta, timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_rb_generator as wrb  # noqa: E402  (verified RB engine, unmodified)
import h4_rb_engine as h4rb        # noqa: E402  (reuses its aggregate_h4)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H Pine viewer for RB zones")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="Etc/GMT+2")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4))
    p.add_argument("--label-cap", type=int, default=120, choices=range(1, 161))
    p.add_argument("--rb-cap", type=int, default=120, choices=range(1, 451))
    p.add_argument("--h4-rb-cap", type=int, default=200, choices=range(1, 451))
    p.add_argument("--table-cap", type=int, default=20, choices=range(1, 21))
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def pine_time(t) -> str:
    u = t.astimezone(UTC)
    return f"timestamp(\"GMT+0\", {u.year}, {u.month}, {u.day}, {u.hour}, {u.minute})"


def pine_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def arr(kind: str, values: List[str]) -> str:
    return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"


def rb_colour(z) -> str:
    """Per RB_Indicator_v1.pine's header: IRB blue(bull)/black(bear) by raw
    wick; ARB green fixed; ORB red fixed. `z.origin` is the permanent
    creation-type marker (0=IRB-style, 1=ARB-style) -- NOT affected by later
    lifecycle transitions, so an IRB that later strands to ORB still needs
    the ORB-red override read from current status, not origin, hence the
    explicit `is_orb` check first."""
    is_orb = (z.state == 2) or (z.state == 3 and z.pre_spent_state == 2)
    if is_orb:
        return "color.red"
    if z.origin == 1:  # ARB
        return "color.green"
    return "color.blue" if z.bullish else "color.black"  # IRB


def is_orb(z) -> bool:
    return (z.state == 2) or (z.state == 3 and z.pre_spent_state == 2)


def build_rb_block(prefix: str, engine, bars, shown, table_zones, display_tz: ZoneInfo,
                    draw_flag_expr: str, hide_orb: bool, right_edge, with_table: bool,
                    table_flag_expr: str = None) -> List[str]:
    if table_flag_expr is None:
        table_flag_expr = draw_flag_expr
    """One RB layer's worth of packed arrays + a single runtime draw loop,
    reused for both the Weekly layer and the H4 layer (`prefix` keeps their
    Pine variable names from colliding when both blocks appear in the same
    generated file, same reason full_viewer.py prefixes its H4 arrays
    `h4...`)."""
    impact_vars = {}
    impact_watchers: List[str] = []
    for z in shown:
        if hide_orb and is_orb(z):
            continue
        if z.impact_time is not None:
            name = f"{prefix}impact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = pine_time(z.impact_time)
            impact_watchers += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]

    lefts, tops, bottoms, right_exprs, cols, statuses = [], [], [], [], [], []
    for z in shown:
        if hide_orb and is_orb(z):
            continue
        origin = bars[z.candle]
        lefts.append(pine_time(origin.start))
        tops.append(f"{z.zt:.5f}")
        bottoms.append(f"{z.zb:.5f}")
        fallback_right = z.impact_time or (bars[z.stop].start if 0 <= z.stop < len(bars) else right_edge)
        if z.id in impact_vars:
            right_exprs.append(f"(na({impact_vars[z.id]}) ? {pine_time(fallback_right)} : {impact_vars[z.id]})")
        else:
            right_exprs.append(pine_time(fallback_right))
        cols.append(rb_colour(z))
        statuses.append(f"\"#{z.id} {wrb.status(z)} {'BUY' if z.bullish else 'SELL'}\"")

    lines = [
        f"var array<int> {prefix}Left = {arr('int', lefts)}",
        f"var array<float> {prefix}Top = {arr('float', tops)}",
        f"var array<float> {prefix}Bottom = {arr('float', bottoms)}",
        f"var array<color> {prefix}Col = {arr('color', cols)}",
        f"var array<string> {prefix}Label = {arr('string', statuses)}",
        *impact_watchers,
        "if barstate.islast",
        f"    if {draw_flag_expr}",
        f"        array<int> {prefix}Right = {arr('int', right_exprs)}",
        f"        for i = 0 to array.size({prefix}Left) - 1",
        f"            rCol = array.get({prefix}Col, i)",
        f"            box.new(array.get({prefix}Left, i), array.get({prefix}Top, i), array.get({prefix}Right, i), array.get({prefix}Bottom, i), border_color=rCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        f"            label.new(array.get({prefix}Left, i), array.get({prefix}Top, i), array.get({prefix}Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(rCol,85), textcolor=rCol, size=size.tiny)",
    ]

    if with_table:
        t_id, t_type, t_side, t_bottom, t_top, t_origin, t_trigger, t_eligible, t_impact, t_bg = ([] for _ in range(10))
        for z in table_zones:
            origin = bars[z.candle]
            trig_txt = wrb.display_iso(z.trigger_time, display_tz)
            elig_txt = wrb.display_iso(z.eligible_time, display_tz)
            imp_txt = wrb.display_iso(z.impact_time, display_tz)
            t_id.append(f"\"#{z.id}\""); t_type.append(f"\"{wrb.status(z)}\"")
            t_side.append(f"\"{'BUY' if z.bullish else 'SELL'}\"")
            t_bottom.append(f"\"{z.zb:.5f}\""); t_top.append(f"\"{z.zt:.5f}\"")
            t_origin.append(f"\"{pine_text(wrb.display_iso(origin.start, display_tz))}\"")
            t_trigger.append(f"\"{pine_text(trig_txt)}\""); t_eligible.append(f"\"{pine_text(elig_txt)}\"")
            t_impact.append(f"\"{pine_text(imp_txt)}\"")
            t_bg.append(f"color.new({rb_colour(z)}, 80)")
        n = len(table_zones)
        lines += [
            f"var table {prefix}Ledger = table.new(position.top_right, 9, {n + 1}, border_width=1)",
            f"var array<string> {prefix}TId = {arr('string', t_id)}",
            f"var array<string> {prefix}TType = {arr('string', t_type)}",
            f"var array<string> {prefix}TSide = {arr('string', t_side)}",
            f"var array<string> {prefix}TBottom = {arr('string', t_bottom)}",
            f"var array<string> {prefix}TTop = {arr('string', t_top)}",
            f"var array<string> {prefix}TOrigin = {arr('string', t_origin)}",
            f"var array<string> {prefix}TTrigger = {arr('string', t_trigger)}",
            f"var array<string> {prefix}TEligible = {arr('string', t_eligible)}",
            f"var array<string> {prefix}TImpact = {arr('string', t_impact)}",
            f"var array<color> {prefix}TBg = {arr('color', t_bg)}",
        ]
        header = ["RB", "Type", "Side", "Bottom", "Top", "Origin (RYD)", "Trigger (RYD)", "Eligible (RYD)", "Impact (RYD)"]
        lines.append("if barstate.islast")
        lines.append(f"    if {table_flag_expr}")
        for col, h in enumerate(header):
            lines.append(f"        table.cell({prefix}Ledger, {col}, 0, \"{h}\", text_color=color.white, bgcolor=color.new(color.green,15))")
        lines += [
            f"        for i = 0 to array.size({prefix}TId) - 1",
            f"            row = i + 1",
            f"            table.cell({prefix}Ledger, 0, row, array.get({prefix}TId, i), text_color=color.black, bgcolor=array.get({prefix}TBg, i))",
            f"            table.cell({prefix}Ledger, 1, row, array.get({prefix}TType, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 2, row, array.get({prefix}TSide, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 3, row, array.get({prefix}TBottom, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 4, row, array.get({prefix}TTop, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 5, row, array.get({prefix}TOrigin, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 6, row, array.get({prefix}TTrigger, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 7, row, array.get({prefix}TEligible, i), text_color=color.black, bgcolor=na)",
            f"            table.cell({prefix}Ledger, 8, row, array.get({prefix}TImpact, i), text_color=color.black, bgcolor=na)",
        ]
    return lines


def build_struct_block(prefix: str, engine, bars, label_cap: int, draw_flag_expr: str) -> List[str]:
    sh = [e for e in engine.events if e.kind == 0][-label_cap:]
    sl = [e for e in engine.events if e.kind == 1][-label_cap:]
    ms = engine.msses[-label_cap:]
    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(pine_time(bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▲\""); struct_col.append("color.blue"); struct_low.append("false")
    for e in sl:
        struct_x.append(pine_time(bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▼\""); struct_col.append("color.black"); struct_low.append("true")
    for m in ms:
        struct_x.append(pine_time(bars[m.broken].start)); struct_y.append(f"{m.price:.5f}")
        struct_txt.append("\"✕\""); struct_col.append("color.blue" if m.up else "color.black")
        struct_low.append("false" if m.up else "true")
    return [
        f"var array<int> {prefix}StructX = {arr('int', struct_x)}",
        f"var array<float> {prefix}StructY = {arr('float', struct_y)}",
        f"var array<string> {prefix}StructTxt = {arr('string', struct_txt)}",
        f"var array<color> {prefix}StructCol = {arr('color', struct_col)}",
        f"var array<bool> {prefix}StructLow = {arr('bool', struct_low)}",
        "if barstate.islast",
        f"    if {draw_flag_expr}",
        f"        for i = 0 to array.size({prefix}StructX) - 1",
        f"            sYY = array.get({prefix}StructLow, i) ? array.get({prefix}StructY, i) - lowGap : array.get({prefix}StructY, i)",
        f"            label.new(array.get({prefix}StructX, i), sYY, array.get({prefix}StructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=array.get({prefix}StructCol, i), size=size.small)",
    ]


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wrb.load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)

    weeks = wrb.aggregate_weeks(minutes, ZoneInfo("America/New_York"), 17)
    weekly_engine = wrb.WeeklyRBEngine(minutes, weeks)
    weekly_engine.run()

    h4_bars = h4rb.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wrb.WeeklyRBEngine(minutes, h4_bars)
    h4_engine.run()

    right_edge = minutes[-1].t + timedelta(days=365)
    weekly_shown = weekly_engine.rbs[-args.rb_cap:]
    weekly_table = weekly_engine.rbs[-args.table_cap:][::-1]
    h4_shown = h4_engine.rbs[-args.h4_rb_cap:]
    h4_table = h4_engine.rbs[-args.table_cap:][::-1]

    lines = [
        "//@version=6",
        "indicator(\"FXCM RB - Python Reference (Weekly + H4)\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. RB zones/lifecycle follow",
        "// RB_Indicator_v1.pine's addRBFromSwing/tryBullARB/tryBearARB/STEP2/STEP3",
        "// verbatim (weekly_rb_generator.py / h4_rb_engine.py). Drawing convention",
        "// (from that pine file's own header): dashed hollow boxes; IRB",
        "// blue(bull)/black(bear) by raw wick; ARB green; ORB red, hidden on H4/5m",
        "// (only ever drawn on the Weekly chart here) -- flagged in that same header",
        "// comment as a convention to double-check for RB, not silently changed here.",
        "// Weekly chart: Weekly RB zones + swing/MSS labels + table. H4 chart: H4 RB",
        "// zones + table. 5m chart: H4 RB boxes only (no table). Every other",
        "// timeframe draws nothing.",
        "float lowGap = ta.atr(14) * 0.08",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
        "bool onFive = timeframe.period == \"5\"",
    ]

    lines += build_struct_block("w", weekly_engine, weeks, args.label_cap, "onWeekly")
    lines += build_rb_block("w", weekly_engine, weeks, weekly_shown, weekly_table, display_tz,
                             draw_flag_expr="onWeekly", hide_orb=False, right_edge=right_edge, with_table=True)
    lines += build_rb_block("h4", h4_engine, h4_bars, h4_shown, h4_table, display_tz,
                             draw_flag_expr="onH4 or onFive", hide_orb=True, right_edge=right_edge,
                             with_table=True, table_flag_expr="onH4")

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "full_viewer_rb.pine").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Created: full_viewer_rb.pine")
    print(f"Weekly RB zones: {len(weekly_engine.rbs)} ({len(weekly_shown)} shown)")
    print(f"H4 RB zones: {len(h4_engine.rbs)} ({len(h4_shown)} shown, ORB hidden on H4/5m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
