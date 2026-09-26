#!/usr/bin/env python3
"""Combined Weekly + 4H + 5m OB+RB+FVG Pine viewer.

Builds on top of weekly_combined_generator.py (the single shared swing/
regime/MSS pass) and weekly_combined_control_engine.py (the unified
BUY_ONLY/SELL_ONLY/BOTH/NONE state machine across all three POI types),
same way full_fvg_viewer.py builds the H4+5m layers on top of the Weekly
FVG engine. Reuses, UNCHANGED, everything generic from the OB/RB/FVG side:
  - h4_ob_engine.aggregate_h4() / .permits()          -- pure minute/control
                                                          math.
  - five_bso_engine.aggregate_5m() / .structural_invalid_at() /
    .run_bso_chain() / .ledger_row() / .LEDGER_FIELDS  -- generic over any
                                                          zone with
                                                          bullish/zb/zt/id/
                                                          state/pre_spent_state.
  - full_viewer.manual_control_and_parent_at() / .build_bso_extra_lines() /
    .pack_array()                                       -- same reasoning.

New here: one combined H4 layer with a "Focus POI" toggle (ALL/OB/RB/FVG)
+ "Inspect one 4H POI only" + "4H POI from last" -- same scheme as
weekly_combined_generator.write_combined_pine's own Weekly-layer toggle,
including a GLOBAL rank across all three types under ALL (see that file's
own comment for why). The 5m layer reuses full_viewer.build_bso_extra_lines()
verbatim -- it already has its own per-attempt "Inspect one 5m BSO only" /
"5m BSO from last" toggle, generic across whatever zones are fed into it;
each row's own "Weekly" column is POI-type-prefixed (e.g. "FVG1" instead of
a bare "1") so rows from different POI types never look identical.

By default, restricts to gate 1 -- the first non-NONE control window after
the unified control walk's leading NONE (per explicit user direction:
"show me the 4h opportunities in gate 1 buying window"). --window-start/
--window-end override this the same way full_fvg_viewer.py's do.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import argparse

_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference", _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob            # noqa: E402
import weekly_rb_generator as wrb            # noqa: E402
import weekly_fvg_generator as wfvg          # noqa: E402
import weekly_combined_generator as wc       # noqa: E402
import weekly_combined_control_engine as cc  # noqa: E402
import h4_ob_engine as h4                    # noqa: E402  (generic)
import five_bso_engine as bso                # noqa: E402  (generic)
import full_viewer as fv                     # noqa: E402  (generic)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H+5m OB+RB+FVG Pine viewer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=120, choices=range(1, 451))
    p.add_argument("--pine-rbs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-fvgs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--h4-anchor-hour", type=int, default=17, choices=range(24))
    p.add_argument("--h4-pine-cap", type=int, default=200, choices=range(1, 451))
    p.add_argument("--h4-pine-labels", type=int, default=80, choices=range(1, 161))
    p.add_argument("--window-start", default=None,
                    help="Only draw H4 opportunities/trades impacted on or after this date/time "
                         "(e.g. 2026-02-02 or '2026-02-02 16:03'), in --display-tz. Defaults to "
                         "gate 1's own start (the first non-NONE control window).")
    p.add_argument("--window-end", default=None,
                    help="Only draw H4 opportunities/trades impacted before this date/time, in "
                         "--display-tz. Defaults to gate 1's own end.")
    return p.parse_args()


def events_to_gates(events: List["cc.ControlEvent"], data_start: datetime, data_end: datetime) -> List[Tuple[datetime, datetime, str, str, str]]:
    """Converts the unified control walk's flat ControlEvent list into the
    same (start, end, control, sell_parent, buy_parent) tuple shape every
    manual gates table in this project already uses -- so
    full_viewer.manual_control_and_parent_at() runs against it unchanged."""
    gates: List[Tuple[datetime, datetime, str, str, str]] = []
    if not events or events[0].at_utc is None or events[0].at_utc > data_start:
        first_at = events[0].at_utc if events else data_end
        gates.append((data_start, first_at, "NONE", "", ""))
    for i, e in enumerate(events):
        end = events[i + 1].at_utc if i + 1 < len(events) else data_end
        gates.append((e.at_utc, end, e.control, e.sell_parent, e.buy_parent))
    return gates


def gate1_window(gates: List[Tuple[datetime, datetime, str, str, str]]) -> Tuple[datetime, datetime]:
    """The first non-NONE gate after the leading NONE."""
    for start, end, control, _sp, _bp in gates:
        if control != "NONE":
            return start, end
    raise SystemExit("No non-NONE gate found -- nothing to show for gate 1.")


def parse_window_arg(s: str, display_tz: ZoneInfo) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=display_tz)
        except ValueError:
            continue
    raise SystemExit(f"--window-start/--window-end: could not parse {s!r} (use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')")


def build_h4_combined_extra_lines(rows: List[Tuple[object, str, str]], h4_bars_by_type: Dict[str, List["wob.Week"]],
                                   h4_engines: Dict[str, object], h4_cap: int, display_tz: ZoneInfo,
                                   window_start: datetime, window_end: datetime, label_cap: int) -> List[str]:
    """rows: list of (zone, parent_id, poi_type). One combined H4 layer:
    boxes+labels+table, gated by a "Focus POI" toggle (ALL/OB/RB/FVG) +
    "Inspect one 4H POI only" + "4H POI from last" -- same scheme as
    weekly_combined_generator.write_combined_pine's own Weekly toggle,
    including a global rank across types under ALL."""
    pack_array = wrb.pack_array
    pine_epoch = wrb.pine_epoch

    shown = rows[-h4_cap:]
    n = len(shown)

    # Per-type rank (1 = most recent OF THAT TYPE, by impact time) and
    # global rank (1 = most recent OF ANY TYPE) -- mirrors the Weekly
    # layer's obRank/obGRank convention exactly.
    by_type: Dict[str, List[int]] = {"OB": [], "RB": [], "FVG": []}
    for i, (_z, _pid, ptype) in enumerate(shown):
        by_type[ptype].append(i)
    per_type_rank = [0] * n
    for ptype, idxs in by_type.items():
        idxs_sorted = sorted(idxs, key=lambda i: shown[i][0].impact_time, reverse=True)
        for rank, i in enumerate(idxs_sorted, start=1):
            per_type_rank[i] = rank
    global_order = sorted(range(n), key=lambda i: shown[i][0].impact_time, reverse=True)
    global_rank = [0] * n
    for rank, i in enumerate(global_order, start=1):
        global_rank[i] = rank
    max_rank = max(1, n)

    def in_window(t: datetime) -> bool:
        return window_start <= t < window_end

    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for ptype, bars in h4_bars_by_type.items():
        eng = h4_engines[ptype]
        sh = [e for e in eng.events if e.kind == 0 and in_window(bars[e.swing].start)][-label_cap:]
        sl = [e for e in eng.events if e.kind == 1 and in_window(bars[e.swing].start)][-label_cap:]
        ms = [m for m in eng.msses if in_window(bars[m.broken].start)][-label_cap:]
        for e in sh:
            struct_x.append(pine_epoch(bars[e.swing].start)); struct_y.append(e.price)
            struct_txt.append("▲"); struct_col.append("B"); struct_low.append(False)
        for e in sl:
            struct_x.append(pine_epoch(bars[e.swing].start)); struct_y.append(e.price)
            struct_txt.append("▼"); struct_col.append("K"); struct_low.append(True)
        for m in ms:
            struct_x.append(pine_epoch(bars[m.broken].start))
            struct_y.append(m.price)
            struct_txt.append("✕"); struct_col.append("B" if m.up else "K")
            struct_low.append(not m.up)

    lefts, tops, bottoms, fallback_rights, impact_stamps, bulls, labels, ids, parents, sides, bots5, tops5, trigs, eligs, impacts, ptypes = ([] for _ in range(16))
    for i, (z, parent_id, ptype) in enumerate(shown):
        bars = h4_bars_by_type[ptype]
        origin_idx = z.left if ptype == "FVG" else z.candle
        origin = bars[origin_idx]
        lefts.append(pine_epoch(origin.start))
        tops.append(z.zt); bottoms.append(z.zb)
        fallback_rights.append(pine_epoch(bars[z.stop].start))
        impact_stamps.append(pine_epoch(z.impact_time))
        bulls.append(z.bullish)
        ids.append(f"{ptype}#{z.id}")
        parents.append(f"{ptype}{parent_id}" if parent_id else '-')
        labels.append(f"{ptype}#{z.id} {'BUY' if z.bullish else 'SELL'} (W{ptype}{parent_id})")
        sides.append('BUY' if z.bullish else 'SELL')
        bots5.append(f"{z.zb:.5f}"); tops5.append(f"{z.zt:.5f}")
        trigs.append(wob.display_iso(z.trigger_time, display_tz))
        eligs.append(wob.display_iso(z.eligible_time, display_tz))
        impacts.append(wob.display_iso(z.impact_time, display_tz))
        ptypes.append(ptype)

    lines: List[str] = [
        "string focusH4Poi = input.string(\"ALL\", \"Focus 4H POI\", options=[\"ALL\", \"OB\", \"RB\", \"FVG\"], group=\"4H opportunities (gate 1)\")",
        "bool inspectOneH4Poi = input.bool(false, \"Inspect one 4H POI only\", group=\"4H opportunities (gate 1)\")",
        f"int h4PoiFromLast = input.int(1, \"4H POI from last\", minval=1, maxval={max_rank}, group=\"4H opportunities (gate 1)\", tooltip=\"1 = the latest 4H POI (of the focused type if one is picked, or of ANY type if Focus 4H POI is ALL), 2 = the one before it, and so on.\")",
        f"var table h4Ledger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        *pack_array("h4Left", "int", lefts), *pack_array("h4Top", "float", tops), *pack_array("h4Bottom", "float", bottoms),
        *pack_array("h4Bull", "bool", bulls), *pack_array("h4Label", "string", labels), *pack_array("h4Id", "string", ids),
        *pack_array("h4Parent", "string", parents), *pack_array("h4Side", "string", sides),
        *pack_array("h4Bot5", "string", bots5), *pack_array("h4Top5", "string", tops5),
        *pack_array("h4Trig", "string", trigs), *pack_array("h4Elig", "string", eligs), *pack_array("h4Impact", "string", impacts),
        *pack_array("h4FallbackRight", "int", fallback_rights), *pack_array("h4ImpactStamp", "int", impact_stamps),
        *pack_array("h4PoiType", "string", ptypes),
        *pack_array("h4Rank", "int", per_type_rank), *pack_array("h4GRank", "int", global_rank),
        *pack_array("h4StructX", "int", struct_x), *pack_array("h4StructY", "float", struct_y),
        *pack_array("h4StructTxt", "string", struct_txt), *pack_array("h4StructCol", "string", struct_col),
        *pack_array("h4StructLow", "bool", struct_low),
        f"var array<int> h4ImpactX = array.new<int>({n}, na)",
        "for hi = 0 to array.size(h4ImpactStamp) - 1",
        "    hiStamp = array.get(h4ImpactStamp, hi)",
        "    if na(array.get(h4ImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "        array.set(h4ImpactX, hi, time)",
        "if barstate.islast",
        "    if onH4 or on1m or onFive",
        "        for i = 0 to array.size(h4Left) - 1",
        "            if focusH4Poi == \"ALL\" or array.get(h4PoiType, i) == focusH4Poi",
        "                if not inspectOneH4Poi or (focusH4Poi == \"ALL\" ? array.get(h4GRank, i) == h4PoiFromLast : array.get(h4Rank, i) == h4PoiFromLast)",
        "                    hrRight = na(array.get(h4ImpactX, i)) ? array.get(h4FallbackRight, i) : array.get(h4ImpactX, i)",
        "                    hrCol = array.get(h4Bull, i) ? color.blue : color.black",
        "                    box.new(array.get(h4Left, i), array.get(h4Top, i), hrRight, array.get(h4Bottom, i), border_color=hrCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "                    label.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hrCol,85), textcolor=hrCol, size=size.tiny)",
        "                    line.new(hrRight, array.get(h4Bottom, i), hrRight, array.get(h4Top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)",
        "    if onH4",
        "        for i = 0 to array.size(h4StructX) - 1",
        "            hrStructCol = array.get(h4StructCol, i) == \"B\" ? color.blue : color.black",
        "            hrStructYY = array.get(h4StructLow, i) ? array.get(h4StructY, i) - lowGap : array.get(h4StructY, i)",
        "            label.new(array.get(h4StructX, i), hrStructYY, array.get(h4StructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=hrStructCol, size=size.small)",
        "        table.cell(h4Ledger, 0, 0, \"4H POI\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 1, 0, \"Parent W\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 5, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 6, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4Ledger, 7, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        rowN = 0",
        "        for i = 0 to array.size(h4Left) - 1",
        f"            if rowN < {n} and (focusH4Poi == \"ALL\" or array.get(h4PoiType, i) == focusH4Poi) and (not inspectOneH4Poi or (focusH4Poi == \"ALL\" ? array.get(h4GRank, i) == h4PoiFromLast : array.get(h4Rank, i) == h4PoiFromLast))",
        "                rowN += 1",
        "                table.cell(h4Ledger, 0, rowN, array.get(h4Id, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 1, rowN, array.get(h4Parent, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 2, rowN, array.get(h4Side, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 3, rowN, array.get(h4Bot5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 4, rowN, array.get(h4Top5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 5, rowN, array.get(h4Trig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 6, rowN, array.get(h4Elig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 7, rowN, array.get(h4Impact, i), text_color=color.black, bgcolor=na)",
    ]
    return lines


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = path.parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2

    input_tz = ZoneInfo(args.input_tz)
    close_tz = ZoneInfo(args.week_close_zone)
    display_tz = ZoneInfo(args.display_tz)

    minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
    weeks = wob.aggregate_weeks(minutes, close_tz, args.week_close_hour)

    weekly_engine = wc.WeeklyCombinedEngine(minutes, weeks)
    weekly_engine.run()

    control_events = cc.run_control_walk(weekly_engine, weeks, minutes)
    gates = events_to_gates(control_events, minutes[0].t, minutes[-1].t)
    g1_start, g1_end = gate1_window(gates)

    window_start, window_end = g1_start, g1_end
    if args.window_start:
        window_start = max(window_start, parse_window_arg(args.window_start, display_tz))
    if args.window_end:
        window_end = min(window_end, parse_window_arg(args.window_end, display_tz))
    if window_start >= window_end:
        raise SystemExit(f"--window-start/--window-end leaves an empty window: {window_start} -> {window_end}")

    h4_bars = h4.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_ob = wob.WeeklyOBEngine(minutes, h4_bars); h4_ob.run()
    h4_rb = wrb.WeeklyRBEngine(minutes, h4_bars); h4_rb.run()
    h4_fvg = wfvg.WeeklyFVGEngine(minutes, h4_bars); h4_fvg.run()
    h4_bars_by_type = {"OB": h4_bars, "RB": h4_bars, "FVG": h4_bars}
    h4_engines = {"OB": h4_ob, "RB": h4_rb, "FVG": h4_fvg}

    def authorize(zones, pre_spent_ok_states):
        drawn = []
        for z in zones:
            if getattr(z, "rejected", False):
                continue
            impacted = z.state == 3
            pre_spent_ok = z.pre_spent_state in pre_spent_ok_states if impacted else None
            ctrl_parent = fv.manual_control_and_parent_at(gates, z.impact_time, z.bullish) if (impacted and z.impact_time is not None) else None
            ctrl, parent_id = ctrl_parent if ctrl_parent is not None else ("", "")
            authorized = bool(impacted and pre_spent_ok and h4.permits(ctrl, z.bullish))
            if authorized:
                drawn.append((z, parent_id))
        return drawn

    drawn_ob = [(z, pid, "OB") for z, pid in authorize(h4_ob.zones, (0, 1, 4))]
    drawn_rb = [(z, pid, "RB") for z, pid in authorize(h4_rb.zones, (0, 1, 4))]
    drawn_fvg = [(z, pid, "FVG") for z, pid in authorize(h4_fvg.zones, (0, 1))]
    all_drawn = drawn_ob + drawn_rb + drawn_fvg

    focused = [d for d in all_drawn if window_start <= d[0].impact_time < window_end]
    focused.sort(key=lambda d: d[0].impact_time)

    h4_extra_lines = build_h4_combined_extra_lines(focused, h4_bars_by_type, h4_engines, args.h4_pine_cap,
                                                    display_tz, window_start, window_end, args.h4_pine_labels)

    mt = [m.t for m in minutes]
    h4_bar_starts = [b.start for b in h4_bars]
    five_bars = bso.aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_ob = wob.WeeklyOBEngine(minutes, five_bars); five_ob.run()
    five_rb = wrb.WeeklyRBEngine(minutes, five_bars); five_rb.run()
    five_fvg = wfvg.WeeklyFVGEngine(minutes, five_bars); five_fvg.run()
    five_events_by_type = {"OB": five_ob.events, "RB": five_rb.events, "FVG": five_fvg.events}

    # Real bug, user-caught (2026-09-26): two DIFFERENT H4 POI zones (often
    # nested continuation FVGs/OBs/RBs created by a strong trending leg) can
    # get impacted by the SAME real candle. Since the 5m entry search only
    # depends on impact_time, both zones then resolve to the IDENTICAL
    # underlying trade (same resting swing, entry time/price, SL/TP) --
    # counted twice in the ledger otherwise. Dedupe by the trade's own
    # signature (side, resting swing, entry time/price, exit time/result):
    # the first POI to reach a given signature keeps the row; a later POI
    # reaching the SAME signature is merged into that row's parent label
    # instead of appended as a second row.
    bso_results = []
    seen: Dict[tuple, int] = {}
    for z, parent_id, ptype in focused:
        five_events = five_events_by_type[ptype]
        invalidated_at, invalidation_reason = bso.structural_invalid_at(z, z.impact_time, h4_bars, h4_bar_starts, h4_engines[ptype].events, minutes, mt)
        attempts = bso.run_bso_chain(z, z.impact_time, five_bar_starts, five_events, minutes, mt, invalidated_at)
        for res in attempts:
            label = f"{ptype}{parent_id}" if parent_id else ""
            key = (z.bullish, res.get("resting_at"), res.get("entry_time"), res.get("entry_price"),
                   res.get("exit_time"), res.get("result"))
            if key in seen:
                idx = seen[key]
                dz, dit, dlabel, dreason, dres = bso_results[idx]
                if label and label not in dlabel.split("+"):
                    bso_results[idx] = (dz, dit, f"{dlabel}+{label}" if dlabel else label, dreason, dres)
                continue
            seen[key] = len(bso_results)
            bso_results.append((z, z.impact_time, label, invalidation_reason, res))

    bso_extra_lines = [
        line.replace('"Weekly OB"', '"Weekly POI"').replace('"4H OB"', '"4H POI"')
        for line in fv.build_bso_extra_lines(bso_results, display_tz)
    ]

    extra_lines = h4_extra_lines + bso_extra_lines

    wc.write_combined_pine(base, weekly_engine, args.pine_labels, args.pine_obs, args.pine_rbs, args.pine_fvgs,
                            args.pine_table, display_tz, out_name="full_combined_viewer.pine", extra_lines=extra_lines)

    print("Created:")
    print("  full_combined_viewer.pine   (Weekly combined layer + 4H combined layer/table + 5m BSO entry lines)")
    print(f"Gate 1 window: {window_start} -> {window_end}")
    print(f"{len(h4_bars)} 4H bars. Authorized: OB={len(drawn_ob)} RB={len(drawn_rb)} FVG={len(drawn_fvg)}. Shown in gate 1 window: {len(focused)}.")
    bso_stages: Dict[str, int] = {}
    for _z, _it, _parent_id, _reason, res in bso_results:
        bso_stages[res.get("stage")] = bso_stages.get(res.get("stage"), 0) + 1
    print(f"5m BSO on {len(bso_results)} drawn POIs: {bso_stages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
