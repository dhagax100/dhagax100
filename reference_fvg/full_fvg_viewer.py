#!/usr/bin/env python3
"""Combined Weekly + 4H + 5m FVG Pine viewer -- FVG counterpart of
full_rb_viewer.py / full_viewer.py.

Reuses, UNCHANGED, everything from the OB/RB side that is genuinely
generic (confirmed by reading each function's own body, not assumed):
  - h4_ob_engine.aggregate_h4() / .permits()        -- pure minute/control
                                                        math, no Zone-type
                                                        coupling.
  - five_bso_engine.aggregate_5m() / .structural_invalid_at() /
    .run_bso_chain() / .ledger_row() / .LEDGER_FIELDS -- every one of these
    only ever touches z.bullish, z.zb, z.zt, z.id, z.state, z.pre_spent_state
    on the zone object passed in. FVGZone has all six with the identical
    names/meanings, so these run against FVG zones with zero modification.
  - full_viewer.build_bso_extra_lines() / .manual_control_and_parent_at() /
    .pine_time() / .pine_text() -- same reasoning.

The Weekly FVG layer itself is weekly_fvg_generator.write_fvg_pine(), also
unchanged, using its own extra_lines= hook to append the H4 + 5m layers
below into the SAME generated .pine file.

New/FVG-specific in this file: build_manual_fvg_gates() (the hand-derived
control timeline from the 2026-09-26 minute-by-minute walk -- see
docs_fvg/FVG_RULES_LEARNED.md) and build_h4_fvg_extra_lines() (FVG's own
H4 layer -- adapted from build_h4_rb_extra_lines() only because FVGZone
stores its own trigger_time/eligible_time/impact_time directly as fields,
same as RBZone, no OB-style fallback-derivation helpers needed).

Avoided the two real RB mistakes on the way in:
  - RB's first H4 delivery scoped its swing/MSS label window to
    gates[-1][1] (the trailing open-ended NONE's end, effectively the
    whole rest of the dataset) instead of the real gates span. Fixed here
    from the start: window_end = gates[-1][0] when the last gate is NONE,
    matching build_manual_rb_gates()'s own corrected convention.
  - RB's control-gate table went through two real corrections
    (parent-in-charge = last REACTED not last created; a swing-pause
    resume must be cancelled by an opposing MSS, not blindly honored) that
    were only found by walking gate-by-gate with the user, checking real
    M1/weekly data at each step. The table below is that same walked,
    corrected result for FVG -- not a first guess.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))
import weekly_ob_generator as wob      # noqa: E402  (locked engine, unmodified)
import weekly_fvg_generator as fvg     # noqa: E402
import h4_ob_engine as h4              # noqa: E402  (reuses aggregate_h4/permits -- generic)
import five_bso_engine as bso          # noqa: E402  (reuses aggregate_5m/run_bso_chain -- generic)
import full_viewer as fv               # noqa: E402  (reuses build_bso_extra_lines/pine_time/pine_text -- generic)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H+5m FVG Pine viewer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-fvgs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--h4-anchor-hour", type=int, default=17, choices=range(24), help="NY-LOCAL hour the 4H grid starts from, DST-aware -- see h4_ob_engine.h4_grid_start().")
    p.add_argument("--h4-pine-fvgs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--h4-pine-labels", type=int, default=80, choices=range(1, 161))
    p.add_argument("--window-start", default=None,
                    help="Only draw H4 FVGs/trades/labels impacted on or after this date/time "
                         "(e.g. 2026-08-01 or '2026-08-01 09:00'), in --display-tz. Narrows the "
                         "known-gates window -- doesn't change what's computed, only what's drawn "
                         "in the .pine file. The CSVs (h4_fvg_ledger.csv, five_bso_fvg_ledger.csv, "
                         "weekly_fvg_ledger.csv) always contain the FULL history regardless.")
    p.add_argument("--window-end", default=None,
                    help="Only draw H4 FVGs/trades/labels impacted before this date/time, in "
                         "--display-tz. See --window-start.")
    return p.parse_args()


FVG_LEDGER_FIELDS = [f.replace("h4_ob_", "h4_fvg_") for f in bso.LEDGER_FIELDS]


def fvg_relabel(res: Dict) -> Dict:
    """Relabel OB-specific wording in a five_bso_engine result dict for FVG
    display, WITHOUT touching the shared engine itself. Only ever renames
    labels; never changes any value that drives logic (result/stage
    classification, prices, times) -- purely cosmetic, same convention
    already used for RB (rb_relabel)."""
    out = dict(res)
    for k in ("stage", "result"):
        if out.get(k) == "H4_OB_BREACHED":
            out[k] = "H4_FVG_BREACHED"
    return out


def fvg_ledger_row(z, it: Optional[datetime], parent_id: str, invalidation_reason: Optional[str],
                    res: Dict, display_tz: ZoneInfo) -> Dict:
    row = bso.ledger_row(z, it, parent_id, invalidation_reason, fvg_relabel(res), display_tz)
    return {k.replace("h4_ob_", "h4_fvg_"): v for k, v in row.items()}


def build_manual_fvg_gates() -> List[Tuple[datetime, datetime, str, str, str]]:
    """Hand-derived FVG control timeline, gate 0 (leading NONE) through
    gate 12 (trailing NONE, end of the loaded M1 data). Same tuple shape as
    OB/RB's own manual-gates tables: (start, end, control, sell_parent_id,
    buy_parent_id).

    Derived 2026-09-26 via a genuine minute-by-minute walk (see
    docs_fvg/FVG_RULES_LEARNED.md for the full derivation and the two real
    corrections found along the way):

      1. PARENT-IN-CHARGE: same rule as RB -- a side's parent updates ONLY
         the instant price actually REACTS off (impacts) a zone on that
         side, never on mere creation. The last-REACTED zone stays parent
         even through a control flip to the other side and back.
      2. Every opposing impact goes to BOTH, unconditionally -- no
         exception for a "mitigation back to the trend-aligned side"
         scenario (considered and explicitly rejected; RB's own rule
         applies as-is).
      3. BOTH resolves via RESPECT (a swing of the challenger's own
         protecting kind confirms before its own supporting level breaks
         -> full flip) or ANCHOR-BREAK/BODY-DEATH (challenger's own level
         breaks or closes through first, no respect -> reverts to whoever
         controlled before BOTH started).
      4. REAL FIX #1 (found gate 3, first pass): "anchor break" for a
         single-direction campaign's sole controller is NOT a wick merely
         touching the zone's own box (zb/zt) -- that's just price
         revisiting it. The real structural invalidation is the SAME
         concept already built into the zone's own lifecycle
         (STRUCTURAL_BREACH): the zone's supporting SWING POINT actually
         getting taken out. Gate 3 (SELL_ONLY, zone #2) survived over two
         weeks longer than a first (wrong) pass gave it, once this was
         fixed to check the zone's own protect_level instead of its box.
      5. REAL FIX #2 (found gates 2/6/12): a swing-pause resume must be
         CANCELLED, not honored, if an MSS against the paused side
         confirms before the matching resume-swing -- the underlying
         trend itself broke, not just the pause; there's nothing left to
         resume to. Control stays NONE from the MSS's own confirm minute
         onward, only leaving NONE via a fresh impact on either side.
      6. FVG's own close-through (far-edge: close fully past the zone, not
         merely reaching the near edge) stands in wherever OB/RB use plain
         body-close, per explicit user direction -- confirmed directly:
         no weekly close crossed 1.17533 during all of gate 3's real span,
         ruling out close-through as an alternative explanation there.

    Zone reference (side, box, impact time):
      #1 BUY  1.16981-1.18346  impact 2026-02-02 16:03
      #2 SELL 1.16669-1.17533  impact 2026-04-08 01:58
      #3 BUY  1.16268-1.16635  impact 2026-04-29 21:44
      #4 SELL 1.16614-1.16761  impact 2026-05-29 17:51
      #5 SELL 1.14733-1.14994  impact 2026-07-15 20:49
      #6 BUY  1.14492-1.15000  never impacted (died by STRAND) -- never
        becomes a parent.

    NOT yet chart-verified against the real TradingView chart (same
    "verify before trusting" caveat OB/RB's own first control-gate tables
    carried) -- this is the first full pass, built directly from the raw
    M1/weekly data and the corrected rule set above."""
    rtz = ZoneInfo("Asia/Riyadh")

    def rt(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
        return datetime(y, mo, d, h, mi, tzinfo=rtz)

    return [
        (rt(2026, 1, 2, 9, 31), rt(2026, 2, 2, 16, 3), "NONE", "", ""),
        (rt(2026, 2, 2, 16, 3), rt(2026, 2, 17, 18, 28), "BUY_ONLY", "", "1"),
        (rt(2026, 2, 17, 18, 28), rt(2026, 4, 8, 1, 58), "NONE", "", "1"),
        (rt(2026, 4, 8, 1, 58), rt(2026, 4, 29, 21, 44), "SELL_ONLY", "2", "1"),
        (rt(2026, 4, 29, 21, 44), rt(2026, 5, 6, 13, 45), "BOTH", "2", "3"),
        (rt(2026, 5, 6, 13, 45), rt(2026, 5, 14, 18, 0), "BUY_ONLY", "2", "3"),
        (rt(2026, 5, 14, 18, 0), rt(2026, 5, 29, 17, 51), "NONE", "2", "3"),
        (rt(2026, 5, 29, 17, 51), rt(2026, 6, 15, 0, 29), "SELL_ONLY", "4", "3"),
        (rt(2026, 6, 15, 0, 29), rt(2026, 6, 17, 22, 24), "NONE", "4", "3"),
        (rt(2026, 6, 17, 22, 24), rt(2026, 7, 14, 15, 30), "SELL_ONLY", "4", "3"),
        (rt(2026, 7, 14, 15, 30), rt(2026, 7, 15, 20, 49), "NONE", "4", "3"),
        (rt(2026, 7, 15, 20, 49), rt(2026, 7, 29, 21, 53), "SELL_ONLY", "5", "3"),
        (rt(2026, 7, 29, 21, 53), rt(2026, 9, 11, 22, 5), "NONE", "5", "3"),
    ]


def build_h4_fvg_extra_lines(h4_engine: fvg.WeeklyFVGEngine, h4_bars: List["wob.Week"], drawn: List[tuple],
                              fvg_cap: int, display_tz: ZoneInfo,
                              window_start: Optional[datetime] = None, window_end: Optional[datetime] = None,
                              label_cap: int = 80) -> List[str]:
    """FVG's own H4 layer. Adapted from build_h4_rb_extra_lines(): same
    array-packing discipline, same impact_x_<id> cross-timeframe watcher
    technique, same "boxes/lines also render on 5m, table/labels stay
    H4-only" split. FVGZone stores its own trigger_time/eligible_time/
    impact_time as plain fields, same as RBZone -- no fallback-derivation
    helpers needed."""
    shown = drawn[-fvg_cap:]
    n = len(shown)

    def in_window(t: datetime) -> bool:
        if window_start is None:
            return True
        return window_start <= t < window_end

    sh = [e for e in h4_engine.events if e.kind == 0 and in_window(h4_bars[e.swing].start)][-label_cap:]
    sl = [e for e in h4_engine.events if e.kind == 1 and in_window(h4_bars[e.swing].start)][-label_cap:]
    ms = [m for m in h4_engine.msses if in_window(h4_bars[m.broken].start)][-label_cap:]
    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(fvg.pine_epoch(h4_bars[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▲"); struct_col.append("B"); struct_low.append(False)
    for e in sl:
        struct_x.append(fvg.pine_epoch(h4_bars[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▼"); struct_col.append("K"); struct_low.append(True)
    for m in ms:
        struct_x.append(fvg.pine_epoch(h4_bars[m.broken].start))
        struct_y.append(m.price)
        struct_txt.append("✕"); struct_col.append("B" if m.up else "K")
        struct_low.append(not m.up)

    lefts, tops, bottoms, fallback_rights, impact_stamps, bulls, labels, parents, sides, bots5, tops5, trigs, eligs, impacts = ([] for _ in range(14))
    for z, parent_id in shown:
        origin = h4_bars[z.left]
        lefts.append(fvg.pine_epoch(origin.start))
        tops.append(z.zt)
        bottoms.append(z.zb)
        fallback_rights.append(fvg.pine_epoch(h4_bars[z.stop].start))  # guaranteed valid: authorized => impacted => z.stop set
        impact_stamps.append(fvg.pine_epoch(z.impact_time))  # guaranteed: authorized => impacted => impact_time set
        bulls.append(z.bullish)
        parents.append('#' + parent_id if parent_id else '-')
        labels.append(f"#{z.id} {'BUY' if z.bullish else 'SELL'} (W{parent_id})")
        sides.append('BUY' if z.bullish else 'SELL')
        bots5.append(f"{z.zb:.5f}")
        tops5.append(f"{z.zt:.5f}")
        trigs.append(wob.display_iso(z.trigger_time, display_tz))
        eligs.append(wob.display_iso(z.eligible_time, display_tz))
        impacts.append(wob.display_iso(z.impact_time, display_tz))

    ids = [f"#{z.id}" for z, *_ in shown]

    lines: List[str] = [
        "bool inspectOneH4FVG = input.bool(true, \"Inspect one 4H FVG only\", group=\"H4 FVG inspection\")",
        f"int h4FvgFromLast = input.int(1, \"4H FVG from last\", minval=1, maxval={max(1, n)}, group=\"H4 FVG inspection\", tooltip=\"1 = most recent 4H FVG, 2 = the one before it, and so on.\")",
        f"var table h4FvgLedger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        *fv.pack_array("h4FvgLeft", "int", lefts),
        *fv.pack_array("h4FvgTop", "float", tops),
        *fv.pack_array("h4FvgBottom", "float", bottoms),
        *fv.pack_array("h4FvgBull", "bool", bulls),
        *fv.pack_array("h4FvgLabel", "string", labels),
        *fv.pack_array("h4FvgId", "string", ids),
        *fv.pack_array("h4FvgParent", "string", parents),
        *fv.pack_array("h4FvgSide", "string", sides),
        *fv.pack_array("h4FvgBot5", "string", bots5),
        *fv.pack_array("h4FvgTop5", "string", tops5),
        *fv.pack_array("h4FvgTrig", "string", trigs),
        *fv.pack_array("h4FvgElig", "string", eligs),
        *fv.pack_array("h4FvgImpact", "string", impacts),
        *fv.pack_array("h4FvgFallbackRight", "int", fallback_rights),
        *fv.pack_array("h4FvgImpactStamp", "int", impact_stamps),
        *fv.pack_array("h4FvgStructX", "int", struct_x),
        *fv.pack_array("h4FvgStructY", "float", struct_y),
        *fv.pack_array("h4FvgStructTxt", "string", struct_txt),
        *fv.pack_array("h4FvgStructCol", "string", struct_col),
        *fv.pack_array("h4FvgStructLow", "bool", struct_low),
        # ONE shared per-bar watcher loop -- same O(1)-compile-cost fix
        # already used for the Weekly layer and for RB's own H4 layer.
        f"var array<int> h4FvgImpactX = array.new<int>({n}, na)",
        "for hi = 0 to array.size(h4FvgImpactStamp) - 1",
        "    hiStamp = array.get(h4FvgImpactStamp, hi)",
        "    if na(array.get(h4FvgImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "        array.set(h4FvgImpactX, hi, time)",
        "if barstate.islast",
        "    if onH4 or on1m or onFive",
        "        for i = 0 to array.size(h4FvgLeft) - 1",
        "            hrRank = array.size(h4FvgLeft) - i",
        "            if not inspectOneH4FVG or hrRank == h4FvgFromLast",
        "                hrRight = na(array.get(h4FvgImpactX, i)) ? array.get(h4FvgFallbackRight, i) : array.get(h4FvgImpactX, i)",
        "                hrCol = array.get(h4FvgBull, i) ? color.blue : color.black",
        "                box.new(array.get(h4FvgLeft, i), array.get(h4FvgTop, i), hrRight, array.get(h4FvgBottom, i), border_color=hrCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "                label.new(array.get(h4FvgLeft, i), array.get(h4FvgTop, i), array.get(h4FvgLabel, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hrCol,85), textcolor=hrCol, size=size.tiny)",
        "                line.new(hrRight, array.get(h4FvgBottom, i), hrRight, array.get(h4FvgTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)",
        "    if onH4",
        "        for i = 0 to array.size(h4FvgStructX) - 1",
        "            hrStructCol = array.get(h4FvgStructCol, i) == \"B\" ? color.blue : color.black",
        "            hrStructYY = array.get(h4FvgStructLow, i) ? array.get(h4FvgStructY, i) - lowGap : array.get(h4FvgStructY, i)",
        "            label.new(array.get(h4FvgStructX, i), hrStructYY, array.get(h4FvgStructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=hrStructCol, size=size.small)",
        "        table.cell(h4FvgLedger, 0, 0, \"4H FVG\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 1, 0, \"Parent W\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 5, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 6, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4FvgLedger, 7, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        for i = 0 to array.size(h4FvgLeft) - 1",
        "            hrRank = array.size(h4FvgLeft) - i",
        "            if not inspectOneH4FVG or hrRank == h4FvgFromLast",
        "                hrRow = inspectOneH4FVG ? 1 : i + 1",
        "                table.cell(h4FvgLedger, 0, hrRow, array.get(h4FvgId, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 1, hrRow, array.get(h4FvgParent, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 2, hrRow, array.get(h4FvgSide, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 3, hrRow, array.get(h4FvgBot5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 4, hrRow, array.get(h4FvgTop5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 5, hrRow, array.get(h4FvgTrig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 6, hrRow, array.get(h4FvgElig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4FvgLedger, 7, hrRow, array.get(h4FvgImpact, i), text_color=color.black, bgcolor=na)",
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

    weekly_engine = fvg.WeeklyFVGEngine(minutes, weeks)
    weekly_engine.run()

    h4_bars = h4.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = fvg.WeeklyFVGEngine(minutes, h4_bars)
    h4_engine.run()

    gates = build_manual_fvg_gates()

    rows = []
    drawn = []
    for z in h4_engine.zones:
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1) if impacted else None  # not the OFVGs
        ctrl_parent = fv.manual_control_and_parent_at(gates, z.impact_time, z.bullish) if (impacted and z.impact_time is not None) else None
        ctrl, parent_id = ctrl_parent if ctrl_parent is not None else ("", "")
        authorized = bool(impacted and pre_spent_ok and h4.permits(ctrl, z.bullish))
        origin_bar = h4_bars[z.left]
        rows.append(dict(
            id=z.id, side="BUY" if z.bullish else "SELL", type=fvg.status(z),
            bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
            origin_utc=wob.iso(origin_bar.start), origin_riyadh=wob.display_iso(origin_bar.start, display_tz),
            trigger_riyadh=wob.display_iso(z.trigger_time, display_tz),
            eligible_riyadh=wob.display_iso(z.eligible_time, display_tz),
            impact_riyadh=wob.display_iso(z.impact_time, display_tz),
            control_at_impact=ctrl, parent_weekly_id=parent_id, authorized=authorized,
        ))
        if authorized:
            drawn.append((z, parent_id))

    with (base / "h4_fvg_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "side", "type", "bottom", "top", "origin_utc", "origin_riyadh",
                   "trigger_riyadh", "eligible_riyadh", "impact_riyadh",
                   "control_at_impact", "parent_weekly_id", "authorized"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    # Span of the currently hand-derived gates only -- NOT gates[-1][1],
    # which is the trailing open-ended NONE's end (almost the whole
    # dataset). Same fix RB's own first H4 delivery needed after shipping
    # the bug once; applied here from the start.
    window_start = gates[0][0]
    window_end = gates[-1][0] if gates[-1][2] == "NONE" else gates[-1][1]

    def parse_window_arg(s: str) -> datetime:
        s = s.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=display_tz)
            except ValueError:
                continue
        raise SystemExit(f"--window-start/--window-end: could not parse {s!r} "
                          f"(use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')")

    if args.window_start:
        window_start = max(window_start, parse_window_arg(args.window_start))
    if args.window_end:
        window_end = min(window_end, parse_window_arg(args.window_end))
    if window_start >= window_end:
        raise SystemExit(f"--window-start/--window-end leaves an empty window: "
                          f"{window_start} -> {window_end}")

    focused_drawn = [d for d in drawn if window_start <= d[0].impact_time < window_end]
    h4_extra_lines = build_h4_fvg_extra_lines(h4_engine, h4_bars, focused_drawn, args.h4_pine_fvgs, display_tz,
                                               window_start, window_end, args.h4_pine_labels)

    mt = [m.t for m in minutes]
    h4_bar_starts = [b.start for b in h4_bars]
    five_bars = bso.aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = fvg.WeeklyFVGEngine(minutes, five_bars)
    five_engine.run()

    bso_results = []
    for z, parent_id in focused_drawn:
        invalidated_at, invalidation_reason = bso.structural_invalid_at(z, z.impact_time, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = bso.run_bso_chain(z, z.impact_time, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            bso_results.append((z, z.impact_time, parent_id, invalidation_reason, fvg_relabel(res)))
    # build_bso_extra_lines is reused verbatim (otherwise fully generic --
    # see the module docstring), but its own 5m table header hardcodes
    # "Weekly OB"/"4H OB". Patched post-hoc rather than duplicating the
    # whole function; the shared function itself stays untouched.
    bso_extra_lines = [
        line.replace('"Weekly OB"', '"Weekly FVG"').replace('"4H OB"', '"4H FVG"')
        for line in fv.build_bso_extra_lines(bso_results, display_tz)
    ]

    with (base / "five_bso_fvg_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FVG_LEDGER_FIELDS)
        wr.writeheader()
        for z, it, parent_id, invalidation_reason, res in bso_results:
            wr.writerow(fvg_ledger_row(z, it, parent_id, invalidation_reason, res, display_tz))

    extra_lines = h4_extra_lines + bso_extra_lines

    fvg.write_fvg_pine(base, weekly_engine, args.pine_labels, args.pine_fvgs, args.pine_table,
                        display_tz, extra_lines=extra_lines, out_name="full_fvg_viewer.pine")
    fvg.write_ledger(base, weekly_engine, display_tz)
    fvg.write_report(base, minutes, weeks, warnings, weekly_engine, args, display_tz)

    print("Created:")
    print("  full_fvg_viewer.pine   (Weekly FVG layer + 4H FVG layer/table + 5m BSO entry lines)")
    print("  h4_fvg_ledger.csv, five_bso_fvg_ledger.csv")
    print("  weekly_fvg_ledger.csv, weekly_fvg_swings.csv, weekly_fvg_report.txt")
    print(f"Known gates window: {window_start} -> {window_end} ({len(gates) - 1} gates, gate 1 BUY_ONLY FVG zone #1)")
    print(f"{len(h4_bars)} 4H bars, {len(h4_engine.zones)} H4 FVGs computed, {len(drawn)} authorized, {len(focused_drawn)} shown (known gates window).")
    bso_stages: Dict[str, int] = {}
    for _z, _it, _parent_id, _reason, res in bso_results:
        bso_stages[res.get("stage")] = bso_stages.get(res.get("stage"), 0) + 1
    print(f"5m BSO on {len(bso_results)} drawn FVGs: {bso_stages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
