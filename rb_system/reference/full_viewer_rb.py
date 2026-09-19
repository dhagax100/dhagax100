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
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ob_reference"))
import weekly_rb_generator as wrb  # noqa: E402  (verified RB engine, unmodified)
import h4_rb_engine as h4rb        # noqa: E402  (reuses its aggregate_h4/load_control_by_week/permits)
import weekly_ob_generator as wob  # noqa: E402  (only for aggregate_weeks -- same week grid weekly_control_engine_rb.py used)
from five_bso_engine import (       # noqa: E402  (reused verbatim, POI-agnostic -- same as five_rb_bso_engine.py)
    run_bso_chain, structural_invalid_at, aggregate_5m,
)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H Pine viewer for RB zones")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4))
    p.add_argument("--label-cap", type=int, default=120, choices=range(1, 161))
    p.add_argument("--rb-cap", type=int, default=120, choices=range(1, 451))
    p.add_argument("--h4-rb-cap", type=int, default=200, choices=range(1, 451))
    p.add_argument("--table-cap", type=int, default=20, choices=range(1, 21))
    p.add_argument("--bso-cap", type=int, default=200, choices=range(1, 451))
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--control-ledger", default=None, help="path to weekly_control_ledger_rb.csv; default: alongside input CSV")
    p.add_argument("--gates-csv", default=None, help="path to rb_control_gates.csv (build_control_gates.py output); default: alongside this script's ../data. Powers the focusGateNum Pine input.")
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def load_gates(path: Path) -> List[Tuple[datetime, Optional[datetime]]]:
    """Reads `rb_control_gates.csv` (build_control_gates.py's output) into a
    list of (start_utc, end_utc) pairs, ordered by gate_index, for the
    focusGateNum Pine input (Task 5): a runtime toggle restricting the H4 RB
    and 5m BSO layers to one gate's time window, mirroring OB's
    `full_viewer.py` --focus-weekly-id/--manual-gates convention but as a
    Pine input (evaluated at chart runtime) rather than a Python CLI flag
    (evaluated at generation time) -- deliberately different mechanism
    because the task asked for a per-gate toggle a viewer can flip without
    regenerating the file, matching this file's own existing inspectOne*
    toggles' own runtime-input pattern, not full_viewer.py's generation-time
    one. Missing file -> empty list (focusGateNum then has nothing to look
    up; callers treat that as "gate filtering unavailable", same fallback
    style as this file's other optional-file reads)."""
    gates: List[Tuple[datetime, Optional[datetime]]] = []
    if not path.exists():
        return gates
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows):
        start = datetime.strptime(row["gate_start_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        end = None
        if i + 1 < len(rows):
            end = datetime.strptime(rows[i + 1]["gate_start_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        gates.append((start, end))
    return gates


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
                    table_flag_expr: str = None, inspect_flag_expr: str = None,
                    from_last_expr: str = None, draw_impact_line: bool = False,
                    gate_filter: bool = False) -> List[str]:
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

    lefts, tops, bottoms, right_exprs, cols, statuses, impact_stamps = [], [], [], [], [], [], []
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
        # For the focusGateNum filter (Task 5): each zone's own impact time,
        # baked as a literal Pine timestamp -- "na" for a zone never
        # impacted (excluded from every gate when the filter is active,
        # since it never became `authorized` at any gate in the first
        # place -- gates are built from h4_rb_ledger.csv's own
        # `impact_time_utc`, see build_control_gates.py).
        impact_stamps.append(pine_time(z.impact_time) if z.impact_time is not None else "na")

    lines = [
        f"var array<int> {prefix}Left = {arr('int', lefts)}",
        f"var array<float> {prefix}Top = {arr('float', tops)}",
        f"var array<float> {prefix}Bottom = {arr('float', bottoms)}",
        f"var array<color> {prefix}Col = {arr('color', cols)}",
        f"var array<string> {prefix}Label = {arr('string', statuses)}",
        f"var array<int> {prefix}ImpactT = {arr('int', impact_stamps)}",
        *impact_watchers,
        "if barstate.islast",
        f"    if {draw_flag_expr}",
        f"        array<int> {prefix}Right = {arr('int', right_exprs)}",
        f"        for i = 0 to array.size({prefix}Left) - 1",
        f"            rCol = array.get({prefix}Col, i)",
    ]
    # rank 1 = most recently created zone (shown is ordered oldest..newest by
    # id, same convention full_viewer.py's OB inspection already uses:
    # hRank = array.size(h4Left) - i).
    gate_ok_expr = (
        f"(focusGateNum == 0 or (not na(array.get({prefix}ImpactT, i)) and "
        f"array.get({prefix}ImpactT, i) >= array.get(gateStart, focusGateNum) and "
        f"array.get({prefix}ImpactT, i) < array.get(gateEnd, focusGateNum)))"
    ) if gate_filter else None
    if inspect_flag_expr is not None:
        lines.append(f"            {prefix}Rank = array.size({prefix}Left) - i")
        cond = f"not {inspect_flag_expr} or {prefix}Rank == {from_last_expr}"
        if gate_ok_expr is not None:
            cond = f"({cond}) and {gate_ok_expr}"
        lines.append(f"            if {cond}")
        indent = "                "
    elif gate_ok_expr is not None:
        lines.append(f"            if {gate_ok_expr}")
        indent = "                "
    else:
        indent = "            "
    lines.append(f"{indent}box.new(array.get({prefix}Left, i), array.get({prefix}Top, i), array.get({prefix}Right, i), array.get({prefix}Bottom, i), border_color=rCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)")
    lines.append(f"{indent}label.new(array.get({prefix}Left, i), array.get({prefix}Top, i), array.get({prefix}Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(rCol,85), textcolor=rCol, size=size.tiny)")
    if draw_impact_line:
        lines.append(f"{indent}line.new(array.get({prefix}Right, i), array.get({prefix}Bottom, i), array.get({prefix}Right, i), array.get({prefix}Top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,40), width=1)")

    if with_table:
        t_id, t_type, t_side, t_bottom, t_top, t_origin, t_trigger, t_eligible, t_impact, t_bg, t_impact_stamp = ([] for _ in range(11))
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
            t_impact_stamp.append(pine_time(z.impact_time) if z.impact_time is not None else "na")
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
            f"var array<int> {prefix}TImpactT = {arr('int', t_impact_stamp)}",
        ]
        header = ["RB", "Type", "Side", "Bottom", "Top", "Origin (RYD)", "Trigger (RYD)", "Eligible (RYD)", "Impact (RYD)"]
        lines.append("if barstate.islast")
        lines.append(f"    if {table_flag_expr}")
        for col, h in enumerate(header):
            lines.append(f"        table.cell({prefix}Ledger, {col}, 0, \"{h}\", text_color=color.white, bgcolor=color.new(color.green,15))")
        lines.append(f"        for i = 0 to array.size({prefix}TId) - 1")
        lines.append("            row = i + 1")
        t_gate_ok_expr = (
            f"(focusGateNum == 0 or (not na(array.get({prefix}TImpactT, i)) and "
            f"array.get({prefix}TImpactT, i) >= array.get(gateStart, focusGateNum) and "
            f"array.get({prefix}TImpactT, i) < array.get(gateEnd, focusGateNum)))"
        ) if gate_filter else None
        if inspect_flag_expr is not None:
            # table_zones is newest-first, so row 1 (i=0) is rank 1 -- same
            # rank convention as the box/label loop above.
            tcond = f"not {inspect_flag_expr} or row == {from_last_expr}"
            if t_gate_ok_expr is not None:
                tcond = f"({tcond}) and {t_gate_ok_expr}"
            lines.append(f"            if {tcond}")
            tindent = "                "
        elif t_gate_ok_expr is not None:
            lines.append(f"            if {t_gate_ok_expr}")
            tindent = "                "
        else:
            tindent = "            "
        lines += [
            f"{tindent}table.cell({prefix}Ledger, 0, row, array.get({prefix}TId, i), text_color=color.black, bgcolor=array.get({prefix}TBg, i))",
            f"{tindent}table.cell({prefix}Ledger, 1, row, array.get({prefix}TType, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 2, row, array.get({prefix}TSide, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 3, row, array.get({prefix}TBottom, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 4, row, array.get({prefix}TTop, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 5, row, array.get({prefix}TOrigin, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 6, row, array.get({prefix}TTrigger, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 7, row, array.get({prefix}TEligible, i), text_color=color.black, bgcolor=na)",
            f"{tindent}table.cell({prefix}Ledger, 8, row, array.get({prefix}TImpact, i), text_color=color.black, bgcolor=na)",
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


def arr_generic(kind: str, values: List[str]) -> str:
    return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"


def build_bso_extra_lines_rb(bso_results: list, display_tz: ZoneInfo, gate_filter: bool = False) -> List[str]:
    """RB analog of `full_viewer.py`'s `build_bso_extra_lines` (~lines
    440-580 there): entry/SL/TP lines, the fixed-R green/red boxes, and a
    ledger table, on the 5m chart only (`onFive`). Reuses the SAME
    `five_bso_engine.run_bso_chain`-produced `res` dict shape (RB's
    `five_rb_bso_engine.py` imports that function unchanged, so its result
    dicts have identical keys) -- only the column set is trimmed for RB:
    there is no Weekly-OB-parent lineage concept for RB (five_rb_bso_engine.
    py's own targets never carry a parent_weekly_id -- see its module
    docstring), so that column is dropped rather than shown as a permanent
    "-" placeholder; everything else (entry/SL/TP lines, R:R boxes, table
    columns, toggle) mirrors the OB version's naming and structure exactly,
    using `bso5...`/`inspectOne5mBSO`/`bso5FromLast`/group="5m BSO
    inspection" for the same reason `h4_rb_engine.py` mirrors
    `inspectOneH4OB`/`h4ObFromLast`'s naming for its own H4 toggle."""
    n = len(bso_results)

    def pt(t: Optional[object]) -> str:
        return pine_time(t) if t is not None else "na"

    def pf(v: Optional[float]) -> str:
        return f"{v:.5f}" if v is not None else "na"

    ids, sides, restings, entries, sls, tps, results, exits, excursions, entry_stamps = ([] for _ in range(10))
    blefts, brights, bys = [], [], []
    clefts, crights, cys, ccols = [], [], [], []
    gleft, gright, gtop, gbottom = [], [], [], []
    rleft, rright, rtop, rbottom = [], [], [], []
    for z, _it, _parent_id, _invalidation_reason, res in bso_results:
        attempt_no = res.get("attempt")
        ids.append(f"\"#{z.id}\"" if attempt_no in (None, 1) else f"\"#{z.id} (re-entry {attempt_no})\"")
        sides.append(f"\"{'BUY' if z.bullish else 'SELL'}\"")
        restings.append(f"\"{pine_text(wrb.display_iso(res.get('resting_at'), display_tz))}\"")
        entry_t, entry_p = res.get("entry_time"), res.get("entry_price")
        entry_txt = f"{wrb.display_iso(entry_t, display_tz)} @ {entry_p:.5f}" if entry_t is not None and entry_p is not None else "-"
        entries.append(f"\"{pine_text(entry_txt)}\"")
        sl_v, tp_v, risk_v = res.get("sl_price"), res.get("tp_price"), res.get("risk")
        sl_txt = f"{risk_v / 0.0001:.1f}/{sl_v:.5f}" if sl_v is not None and risk_v is not None else ("-" if sl_v is None else f"{sl_v:.5f}")
        sls.append(f"\"{sl_txt}\"")
        tps.append(f"\"{tp_v:.5f}\"" if tp_v is not None else "\"-\"")
        result_txt = res.get("result") or res.get("stage") or "?"
        results.append(f"\"{pine_text(result_txt)}\"")
        exit_t, exit_p = res.get("exit_time"), res.get("exit_price")
        exit_txt = f"{wrb.display_iso(exit_t, display_tz)} @ {exit_p:.5f}" if exit_t is not None and exit_p is not None else "-"
        exits.append(f"\"{pine_text(exit_txt)}\"")
        mfe_v, mae_v = res.get("mfe"), res.get("mae")
        excursion_txt = f"{mfe_v / 0.0001:.1f}/{mae_v / 0.0001:.1f}" if mfe_v is not None and mae_v is not None else "-"
        excursions.append(f"\"{excursion_txt}\"")
        # For the focusGateNum filter (Task 5): this attempt's own entry
        # time (not the resting/candidate time) -- "na" for an attempt that
        # never entered (e.g. H4_OB_BREACHED before an entry), excluded from
        # every gate when the filter is active, same convention as the H4
        # layer's ImpactT array above.
        entry_stamps.append(pt(entry_t) if entry_t is not None else "na")

        cs, ep = res.get("candidate_since"), res.get("entry_price")
        blefts.append(pt(cs) if cs is not None and entry_t is not None else "na")
        brights.append(pt(entry_t) if cs is not None and entry_t is not None else "na")
        bys.append(pf(ep) if cs is not None and entry_t is not None else "na")

        result = res.get("result")
        if result in ("SL", "TP") and entry_t is not None and exit_t is not None and exit_p is not None:
            clefts.append(pt(entry_t)); crights.append(pt(exit_t)); cys.append(pf(exit_p))
            ccols.append("color.red" if result == "SL" else "color.green")
        else:
            clefts.append("na"); crights.append("na"); cys.append("na"); ccols.append("na")

        end_t = res.get("excursion_end_time")
        if entry_t is not None and end_t is not None and tp_v is not None and sl_v is not None:
            gleft.append(pt(entry_t)); gright.append(pt(end_t))
            gtop.append(pf(max(entry_p, tp_v))); gbottom.append(pf(min(entry_p, tp_v)))
            rleft.append(pt(entry_t)); rright.append(pt(end_t))
            rtop.append(pf(max(entry_p, sl_v))); rbottom.append(pf(min(entry_p, sl_v)))
        else:
            gleft.append("na"); gright.append("na"); gtop.append("na"); gbottom.append("na")
            rleft.append("na"); rright.append("na"); rtop.append("na"); rbottom.append("na")

    bso_gate_ok_expr = (
        "(focusGateNum == 0 or (not na(array.get(bso5EntryT, i)) and "
        "array.get(bso5EntryT, i) >= array.get(gateStart, focusGateNum) and "
        "array.get(bso5EntryT, i) < array.get(gateEnd, focusGateNum)))"
    ) if gate_filter else None
    bso_cond = "not inspectOne5mBSO or bRank == bso5FromLast"
    if bso_gate_ok_expr is not None:
        bso_cond = f"({bso_cond}) and {bso_gate_ok_expr}"

    return [
        "bool inspectOne5mBSO = input.bool(false, \"Inspect one 5m BSO only\", group=\"5m BSO inspection\")",
        f"int bso5FromLast = input.int(1, \"5m BSO from last\", minval=1, maxval={max(1, n)}, group=\"5m BSO inspection\", tooltip=\"1 = most recent 5m BSO attempt, 2 = the one before it, and so on.\")",
        f"var table bso5Ledger = table.new(position.top_right, 9, {n + 1}, border_width=1)",
        f"var array<string> bso5Id = {arr_generic('string', ids)}",
        f"var array<string> bso5Side = {arr_generic('string', sides)}",
        f"var array<string> bso5Resting = {arr_generic('string', restings)}",
        f"var array<string> bso5Entry = {arr_generic('string', entries)}",
        f"var array<string> bso5Sl = {arr_generic('string', sls)}",
        f"var array<string> bso5Tp = {arr_generic('string', tps)}",
        f"var array<string> bso5Result = {arr_generic('string', results)}",
        f"var array<string> bso5Exit = {arr_generic('string', exits)}",
        f"var array<string> bso5Excursion = {arr_generic('string', excursions)}",
        f"var array<int> bso5EntryT = {arr_generic('int', entry_stamps)}",
        "if barstate.islast",
        "    if onFive",
        f"        array<int> bso5BLeft = {arr_generic('int', blefts)}",
        f"        array<int> bso5BRight = {arr_generic('int', brights)}",
        f"        array<float> bso5BY = {arr_generic('float', bys)}",
        f"        array<int> bso5CLeft = {arr_generic('int', clefts)}",
        f"        array<int> bso5CRight = {arr_generic('int', crights)}",
        f"        array<float> bso5CY = {arr_generic('float', cys)}",
        f"        array<color> bso5CCol = {arr_generic('color', ccols)}",
        f"        array<int> bso5GLeft = {arr_generic('int', gleft)}",
        f"        array<int> bso5GRight = {arr_generic('int', gright)}",
        f"        array<float> bso5GTop = {arr_generic('float', gtop)}",
        f"        array<float> bso5GBottom = {arr_generic('float', gbottom)}",
        f"        array<int> bso5RLeft = {arr_generic('int', rleft)}",
        f"        array<int> bso5RRight = {arr_generic('int', rright)}",
        f"        array<float> bso5RTop = {arr_generic('float', rtop)}",
        f"        array<float> bso5RBottom = {arr_generic('float', rbottom)}",
        "        table.cell(bso5Ledger, 0, 0, \"RB\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 1, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 2, 0, \"Resting (RYD)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 3, 0, \"Entry (RYD / px)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 4, 0, \"SL\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 5, 0, \"TP\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 6, 0, \"Result\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 7, 0, \"Exit (RYD / px)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 8, 0, \"MFE/MAE (pips)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        for i = 0 to array.size(bso5Id) - 1",
        "            bRank = array.size(bso5Id) - i",
    ] + [f"            if {bso_cond}"] + [
        "                bRow = inspectOne5mBSO ? 1 : i + 1",
        "                table.cell(bso5Ledger, 0, bRow, array.get(bso5Id, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 1, bRow, array.get(bso5Side, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 2, bRow, array.get(bso5Resting, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 3, bRow, array.get(bso5Entry, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 4, bRow, array.get(bso5Sl, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 5, bRow, array.get(bso5Tp, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 6, bRow, array.get(bso5Result, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 7, bRow, array.get(bso5Exit, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 8, bRow, array.get(bso5Excursion, i), text_color=color.black, bgcolor=na)",
        "                if not na(array.get(bso5BLeft, i))",
        "                    line.new(array.get(bso5BLeft, i), array.get(bso5BY, i), array.get(bso5BRight, i), array.get(bso5BY, i), xloc=xloc.bar_time, extend=extend.none, color=color.blue, width=2)",
        "                if not na(array.get(bso5CLeft, i))",
        "                    line.new(array.get(bso5CLeft, i), array.get(bso5CY, i), array.get(bso5CRight, i), array.get(bso5CY, i), xloc=xloc.bar_time, extend=extend.none, color=array.get(bso5CCol, i), width=2)",
        "                if not na(array.get(bso5GLeft, i))",
        "                    box.new(array.get(bso5GLeft, i), array.get(bso5GTop, i), array.get(bso5GRight, i), array.get(bso5GBottom, i), border_color=color.green, bgcolor=color.new(color.green, 80), xloc=xloc.bar_time)",
        "                if not na(array.get(bso5RLeft, i))",
        "                    box.new(array.get(bso5RLeft, i), array.get(bso5RTop, i), array.get(bso5RRight, i), array.get(bso5RBottom, i), border_color=color.red, bgcolor=color.new(color.red, 80), xloc=xloc.bar_time)",
    ]


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_file)
    input_tz = ZoneInfo(args.input_tz)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wrb.load_minutes(csv_path, input_tz, args.price_side)
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    mt = [m.t for m in minutes]

    weeks = wrb.aggregate_weeks(minutes, ZoneInfo("America/New_York"), 17)
    weekly_engine = wrb.WeeklyRBEngine(minutes, weeks)
    weekly_engine.run()

    h4_bars = h4rb.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = wrb.WeeklyRBEngine(minutes, h4_bars)
    h4_engine.run()

    # Control gate for the H4 authorized flag shown in the H4 table -- same
    # RB-native ledger h4_rb_engine.py/five_rb_bso_engine.py now use (see
    # RB_TRADING_SYSTEM_HANDOFF.md; this used to read OB's control ledger,
    # corrected here to match). Optional: if the ledger isn't present yet,
    # every zone is simply treated as unauthorized rather than failing --
    # this viewer's job is to draw zones, not to fail without the gate.
    base = csv_path.resolve().parent
    control_path = Path(args.control_ledger) if args.control_ledger else base / "weekly_control_ledger_rb.csv"
    control_by_week = h4rb.load_control_by_week(control_path) if control_path.exists() else {}
    close_tz = ZoneInfo(args.week_close_zone)
    ctrl_weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)
    ctrl_week_starts = [w.start for w in ctrl_weeks]
    from bisect import bisect_left as _bl

    def control_at(t):
        if t is None or not control_by_week:
            return ""
        idx = _bl(ctrl_week_starts, t)
        if idx >= len(ctrl_week_starts) or ctrl_week_starts[idx] != t:
            idx -= 1
        idx = max(0, min(idx, len(ctrl_week_starts) - 1))
        return control_by_week.get(idx, "NONE")

    # 5m BSO targets: impacted, never-stranded-before-impact, control-
    # authorized -- identical gate to five_rb_bso_engine.py's own main(),
    # duplicated here (not imported) only because that module's main() is a
    # script entrypoint, not an importable function; the underlying
    # run_bso_chain/structural_invalid_at calls below are the SAME reused
    # functions, so results match that engine's own ledger exactly.
    targets = []
    for z in h4_engine.rbs:
        impacted = z.state == 3
        if not impacted or z.impact_time is None:
            continue
        if z.pre_spent_state not in (0, 1):
            continue
        ctrl = control_at(z.impact_time)
        if control_by_week and not h4rb.permits(ctrl, z.bullish):
            continue
        targets.append((z, z.impact_time, ""))

    five_bars = aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = wrb.WeeklyRBEngine(minutes, five_bars)
    five_engine.run()
    h4_bar_starts = [b.start for b in h4_bars]

    bso_results = []
    for z, it, parent_id in targets[-args.bso_cap:]:
        invalidated_at, invalidation_reason = structural_invalid_at(z, it, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = run_bso_chain(z, it, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            bso_results.append((z, it, parent_id, invalidation_reason, res))

    right_edge = minutes[-1].t + timedelta(days=365)

    # Gate boundaries for the focusGateNum Pine input (Task 5).
    gates_path = Path(args.gates_csv) if args.gates_csv else base / "rb_control_gates.csv"
    gates = load_gates(gates_path)
    gate_starts_pine = [pine_time(s) for s, _e in gates]
    gate_ends_pine = [pine_time(e) if e is not None else pine_time(right_edge) for _s, e in gates]
    gate_filter_on = len(gates) > 0

    weekly_shown = weekly_engine.rbs[-args.rb_cap:]
    weekly_table = weekly_engine.rbs[-args.table_cap:][::-1]
    h4_shown = h4_engine.rbs[-args.h4_rb_cap:]
    h4_table = h4_engine.rbs[-args.table_cap:][::-1]

    lines = [
        "//@version=6",
        "indicator(\"FXCM RB - Python Reference (Weekly + H4 + 5m BSO)\", overlay=true, max_labels_count=500, max_boxes_count=500, max_lines_count=500)",
        "// GENERATED FROM 1-MINUTE FXCM BID DATA. RB zones/lifecycle follow",
        "// RB_Indicator_v1.pine's addRBFromSwing/tryBullARB/tryBearARB/STEP2/STEP3",
        "// verbatim (weekly_rb_generator.py / h4_rb_engine.py). Drawing convention",
        "// (from that pine file's own header): dashed hollow boxes; IRB",
        "// blue(bull)/black(bear) by raw wick; ARB green; ORB red, hidden on H4/5m",
        "// (only ever drawn on the Weekly chart here) -- flagged in that same header",
        "// comment as a convention to double-check for RB, not silently changed here.",
        "// Weekly chart: Weekly RB zones + swing/MSS labels + table (+ 'Inspect one",
        "// RB only' toggle). H4 chart: H4 RB zones + table (+ 'Inspect one 4H RB",
        "// only' toggle). 5m chart: H4 RB boxes (no table) + the 5m BSO",
        "// entry/SL/TP lines, R:R boxes, and ledger table (+ 'Inspect one 5m BSO",
        "// only' toggle). Every other timeframe draws nothing. All table times are",
        "// Riyadh, labeled (RYD).",
        "float lowGap = ta.atr(14) * 0.08",
        "bool onWeekly = timeframe.period == \"1W\"",
        "bool onH4 = timeframe.period == \"240\"",
        "bool onFive = timeframe.period == \"5\"",
        "bool inspectOneRB = input.bool(false, \"Inspect one RB only\", group=\"Weekly RB inspection\")",
        f"int rbFromLast = input.int(1, \"RB from last\", minval=1, maxval={max(1, len(weekly_shown))}, group=\"Weekly RB inspection\")",
        "bool inspectOneH4RB = input.bool(false, \"Inspect one 4H RB only\", group=\"H4 RB inspection\")",
        f"int h4RbFromLast = input.int(1, \"4H RB from last\", minval=1, maxval={max(1, len(h4_shown))}, group=\"H4 RB inspection\")",
        # focusGateNum (Task 5): a runtime Pine input restricting the H4 RB
        # layer and the 5m BSO layer to one control gate's time window
        # (gate numbering matches rb_control_gates.csv's gate_index + 1, so
        # "1" is the first gate, matching how the "Inspect one X only"
        # toggles above already use 1-based "from last" ranks, not 0-based
        # indices). 0 = off (show everything, the existing behavior).
        # Independent of and combinable with inspectOneH4RB/inspectOne5mBSO
        # above (both filters AND together when both are active). Does NOT
        # touch the Weekly RB layer -- the task asked for H4/5m only.
        f"int focusGateNum = input.int(0, \"Focus one gate only (H4/5m), 0=off\", minval=0, maxval={max(1, len(gates))}, group=\"Control gate focus\", tooltip=\"Gate numbers match rb_control_gates.csv's own gate_index column exactly (0 doubles as off and the trivial dataset-start gate, which never has any authorized zones or entries anyway).\")",
        f"var array<int> gateStart = {arr('int', gate_starts_pine)}",
        f"var array<int> gateEnd = {arr('int', gate_ends_pine)}",
    ]

    lines += build_struct_block("w", weekly_engine, weeks, args.label_cap, "onWeekly")
    lines += build_rb_block("w", weekly_engine, weeks, weekly_shown, weekly_table, display_tz,
                             draw_flag_expr="onWeekly", hide_orb=False, right_edge=right_edge, with_table=True,
                             inspect_flag_expr="inspectOneRB", from_last_expr="rbFromLast", draw_impact_line=True)
    lines += build_rb_block("h4", h4_engine, h4_bars, h4_shown, h4_table, display_tz,
                             draw_flag_expr="onH4 or onFive", hide_orb=True, right_edge=right_edge,
                             with_table=True, table_flag_expr="onH4",
                             inspect_flag_expr="inspectOneH4RB", from_last_expr="h4RbFromLast", draw_impact_line=True,
                             gate_filter=gate_filter_on)
    lines += build_bso_extra_lines_rb(bso_results, display_tz, gate_filter=gate_filter_on)

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "full_viewer_rb.pine").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Created: full_viewer_rb.pine")
    print(f"Weekly RB zones: {len(weekly_engine.rbs)} ({len(weekly_shown)} shown)")
    print(f"H4 RB zones: {len(h4_engine.rbs)} ({len(h4_shown)} shown, ORB hidden on H4/5m)")
    print(f"5m BSO targets: {len(targets)}, attempts drawn: {len(bso_results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
