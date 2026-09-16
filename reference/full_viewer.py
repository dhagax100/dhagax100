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

The H4 OB boxes + impact lines (not the swing/MSS labels or the table) also
render on the 5m chart (`onFive`), reusing the exact same box/line data --
no separate engine run, no separate array packing. Same boxes, same times,
just an extra chart to draw on, matching how the Weekly layer already
renders unchanged on the H4 chart.

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
    p.add_argument("--h4-anchor-hour", type=int, default=1, choices=range(4), help="UTC hour the 4H grid starts from (1 => 01/05/09/13/17/21 UTC = 04/08/12/16/20/00 Riyadh). Chart-verified 2026-09-16 against a real FXCM 4H candle open at 16:00 Riyadh (=13:00 UTC).")
    p.add_argument("--h4-pine-obs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--h4-pine-labels", type=int, default=80, choices=range(1, 161), help="max recent H4 swing-high/swing-low/MSS labels shown (each)")
    p.add_argument("--control-ledger", default=None)
    p.add_argument("--focus-weekly-id", type=int, default=0,
                    help="Only draw/table 4H OBs whose parent Weekly zone matches this ID "
                         "(0 = show every authorized OB across the whole dataset).")
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


def build_h4_extra_lines(h4_engine, h4_bars, drawn: List[tuple], ob_cap: int, display_tz: ZoneInfo,
                          window_start: Optional[datetime] = None, window_end: Optional[datetime] = None,
                          label_cap: int = 80) -> List[str]:
    """Self-contained H4 layer: data packed into Pine arrays (one bulk
    `array.from(...)` statement per field, not one statement per OB), then a
    single small runtime `for` loop draws everything. `onH4`/`onFive` are
    reused from the Weekly layer's own declaration earlier in the same
    script.

    Earlier versions unrolled one box.new/label.new/table.cell per OB. At 70+
    drawn OBs that first blew a single if-block's statement limit (CE10205),
    and after batching into smaller blocks, blew the WHOLE SCRIPT's total
    statement limit (CE10295 "main body is too long"). Packing into arrays
    and looping once keeps the script's own size roughly constant regardless
    of how many OBs get drawn -- the fix TradingView's own error message
    points at ("try wrapping code in functions").

    Box right edge / impact line: resolved into the opening time of whichever
    chart bar contains the exact 1m impact minute, using the same watcher
    technique as the Weekly layer (`var int impact_x_<id> = na`, updated every
    bar via `time <= stamp < time_close`). On the H4 chart this happens to
    equal the H4 bar's own start, which is why an earlier version could get
    away with the cruder `h4_bars[z.stop].start` shortcut -- but on the 5m
    chart the exact impact is usually several 5m bars after the H4 bar opens,
    so that shortcut drew the box/line at the wrong place there. Swing/MSS
    labels and the table stay H4-only; only the OB boxes and impact lines
    also render on 5m, per the user's explicit request."""
    shown = drawn[-ob_cap:]
    n = len(shown)

    def arr(kind: str, values: List[str]) -> str:
        return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"

    def in_window(t: datetime) -> bool:
        if window_start is None:
            return True
        return window_start <= t < window_end

    # H4 swing highs/lows and MSS, scoped to the same window as the focused
    # Weekly zone (SPEC.md SS18's "H4 structure" -- this is genuinely computed
    # H4 structure, not re-derived Weekly structure). Reuses `lowGap`, already
    # declared once by the Weekly layer earlier in the same script.
    sh = [e for e in h4_engine.events if e.kind == 0 and in_window(h4_bars[e.swing].start)][-label_cap:]
    sl = [e for e in h4_engine.events if e.kind == 1 and in_window(h4_bars[e.swing].start)][-label_cap:]
    ms = [m for m in h4_engine.msses if in_window(h4_bars[m.broken].start)][-label_cap:]
    struct_lines: List[str] = []
    for e in sh:
        struct_lines.append(f"        label.new({pine_time(h4_bars[e.swing].start)}, {e.price:.5f}, \"▲\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=color.blue, size=size.small)")
    for e in sl:
        struct_lines.append(f"        label.new({pine_time(h4_bars[e.swing].start)}, {e.price:.5f} - lowGap, \"▼\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=color.black, size=size.small)")
    for m in ms:
        y = f"{m.price:.5f}" if m.up else f"{m.price:.5f} - lowGap"
        colour = "color.blue" if m.up else "color.black"
        struct_lines.append(f"        label.new({pine_time(h4_bars[m.broken].start)}, {y}, \"✕\", xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor={colour}, size=size.small)")

    # Same cross-timeframe impact-resolution technique as the Weekly layer
    # (write_ob_pine's impact_vars): a `var int` tracker per drawn OB, updated
    # on every chart bar until the bar containing the exact 1m impact is
    # reached, after which it stays fixed. Declared once here so it works
    # whether this layer is on the H4 or the 5m chart.
    impact_vars: Dict[int, str] = {}
    impact_watchers: List[str] = []
    for z, tt, tp, et, ep, it, parent_id in shown:
        if it is not None:  # guaranteed: authorized => impacted => it is set
            name = f"h4impact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = pine_time(it)
            impact_watchers += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]

    lefts, tops, bottoms, right_exprs, bulls, labels, parents, sides, bots5, tops5, trigs, eligs, impacts = ([] for _ in range(13))
    for z, tt, tp, et, ep, it, parent_id in shown:
        origin = h4_bars[z.candle]
        fallback_right = h4_bars[z.stop].start  # guaranteed valid: authorized => impacted => z.stop set
        lefts.append(pine_time(origin.start))
        tops.append(f"{z.zt:.5f}")
        bottoms.append(f"{z.zb:.5f}")
        if z.id in impact_vars:
            right_exprs.append(f"(na({impact_vars[z.id]}) ? {pine_time(fallback_right)} : {impact_vars[z.id]})")
        else:
            right_exprs.append(pine_time(fallback_right))
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
        "bool inspectOneH4OB = input.bool(true, \"Inspect one 4H OB only\", group=\"H4 OB inspection\")",
        f"int h4ObFromLast = input.int(1, \"H4 OB from last\", minval=1, maxval={max(1, n)}, group=\"H4 OB inspection\", tooltip=\"1 = most recent 4H OB, 2 = the one before it, and so on.\")",
        f"var table h4Ledger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        f"var array<int> h4Left = {arr('int', lefts)}",
        f"var array<float> h4Top = {arr('float', tops)}",
        f"var array<float> h4Bottom = {arr('float', bottoms)}",
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
        *impact_watchers,
        "if barstate.islast",
        "    if onH4 or onFive",
        f"        array<int> h4Right = {arr('int', right_exprs)}",
        *struct_lines,
        "        for i = 0 to array.size(h4Left) - 1",
        "            hRank = array.size(h4Left) - i",
        "            if not inspectOneH4OB or hRank == h4ObFromLast",
        "                hCol = array.get(h4Bull, i) ? color.blue : color.black",
        "                box.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Right, i), array.get(h4Bottom, i), border_color=hCol, border_width=1, bgcolor=na, xloc=xloc.bar_time)",
        "                label.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hCol,85), textcolor=hCol, size=size.tiny)",
        "                line.new(array.get(h4Right, i), array.get(h4Bottom, i), array.get(h4Right, i), array.get(h4Top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.blue,55), width=1)",
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
        "            hRank = array.size(h4Left) - i",
        "            if not inspectOneH4OB or hRank == h4ObFromLast",
        "                hRow = inspectOneH4OB ? 1 : i + 1",
        "                table.cell(h4Ledger, 0, hRow, array.get(h4Id, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 1, hRow, array.get(h4Parent, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 2, hRow, array.get(h4Side, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 3, hRow, array.get(h4Bot5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 4, hRow, array.get(h4Top5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 5, hRow, array.get(h4Trig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 6, hRow, array.get(h4Elig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4Ledger, 7, hRow, array.get(h4Impact, i), text_color=color.black, bgcolor=na)",
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
    # origin_gap_window=None: see h4_ob_engine.py's identical comment --
    # the Weekly-only Friday-close gap repair must not apply to H4 bars.
    h4_engine = wob.WeeklyOBEngine(minutes, h4_bars, origin_gap_window=None)
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
        origin_bar = h4_bars[z.candle]
        origin_dir = "UP" if origin_bar.c > origin_bar.o else "DOWN" if origin_bar.c < origin_bar.o else "FLAT"
        # Real M1 row count inside the origin bar vs the expected 240 (4h x
        # 60m). A count well under 240 means the bar is truncated -- e.g. the
        # first bar after a weekend close, where the "open" is genuinely the
        # first available post-gap price, not invented, but only a fraction
        # of the bar is real continuous trading. Same disclosure policy as
        # the Weekly origin-gap work: never invent data, always show the
        # real coverage so a thin bar is visible without re-investigating by
        # hand each time.
        origin_m1_count = origin_bar.last - origin_bar.first
        rows.append(dict(
            id=z.id, side="BUY" if z.bullish else "SELL", type=h4.status(z),
            bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
            origin_utc=wob.iso(origin_bar.start), origin_riyadh=wob.display_iso(origin_bar.start, display_tz),
            # Raw origin-candle OHLC + direction, for auditing "why was this
            # candle picked as the OB" without re-running Python by hand --
            # the origin body (bottom/top above) is min/max(open,close) of
            # exactly this candle, per SPEC.md SS4.
            origin_open=f"{origin_bar.o:.5f}", origin_high=f"{origin_bar.h:.5f}",
            origin_low=f"{origin_bar.l:.5f}", origin_close=f"{origin_bar.c:.5f}", origin_direction=origin_dir,
            origin_m1_count=origin_m1_count, origin_m1_expected=240,
            trigger_riyadh=wob.display_iso(tt, display_tz), trigger_price="" if tp is None else f"{tp:.5f}",
            eligible_riyadh=wob.display_iso(et, display_tz), eligible_price="" if ep is None else f"{ep:.5f}",
            impact_riyadh=wob.display_iso(it, display_tz),
            control_at_impact=ctrl, parent_weekly_id=parent_id, authorized=authorized,
        ))
        if authorized:
            drawn.append((z, tt, tp, et, ep, it, parent_id))

    with (base / "h4_ob_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "side", "type", "bottom", "top", "origin_utc", "origin_riyadh",
                   "origin_open", "origin_high", "origin_low", "origin_close", "origin_direction",
                   "origin_m1_count", "origin_m1_expected",
                   "trigger_riyadh", "trigger_price", "eligible_riyadh", "eligible_price",
                   "impact_riyadh", "control_at_impact", "parent_weekly_id", "authorized"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    focused_drawn = drawn
    window_start = window_end = None
    if args.focus_weekly_id:
        focused_drawn = [d for d in drawn if d[6] == str(args.focus_weekly_id)]
        matching_weeks = [idx for idx, pid in parent_by_week.items() if pid == str(args.focus_weekly_id)]
        if matching_weeks:
            window_start = weeks[min(matching_weeks)].start
            window_end = weeks[max(matching_weeks)].end
    extra_lines = build_h4_extra_lines(h4_engine, h4_bars, focused_drawn, args.h4_pine_obs, display_tz,
                                       window_start, window_end, args.h4_pine_labels)

    wob.write_ob_pine(base, weekly_engine, args.pine_labels, args.pine_obs, args.pine_table,
                       args.box_body_minutes, display_tz, args.origin_first_price,
                       args.origin_body_offset_minutes, extra_lines=extra_lines, out_name="full_viewer.pine")
    wob.write_ledger(base, weekly_engine, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes)
    wob.write_report(base, minutes, weeks, warnings, weekly_engine, args)

    print("Created:")
    print("  full_viewer.pine   (Weekly layer unchanged + separate 4H layer/table)")
    print("  h4_ob_ledger.csv")
    print("  weekly_ob_ledger.csv, weekly_ob_swings.csv, weekly_ob_report.txt")
    focus_note = f", {len(focused_drawn)} shown (--focus-weekly-id {args.focus_weekly_id})" if args.focus_weekly_id else ""
    print(f"{len(h4_bars)} 4H bars, {len(h4_engine.zones)} H4 OBs computed, {len(drawn)} drawn (impacted + authorized){focus_note}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
