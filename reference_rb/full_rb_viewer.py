#!/usr/bin/env python3
"""Combined Weekly + 4H + 5m RB Pine viewer -- RB counterpart of full_viewer.py.

Reuses, UNCHANGED, everything from the OB side that is genuinely generic
(confirmed by reading each function's own body, not assumed):
  - h4_ob_engine.aggregate_h4() / .permits()        -- pure minute/control math,
                                                        no Zone-type coupling.
  - five_bso_engine.aggregate_5m() / .structural_invalid_at() /
    .run_bso_chain() / .ledger_row() / .LEDGER_FIELDS -- every one of these
    only ever touches z.bullish, z.zb, z.zt, z.id, z.state, z.pre_spent_state
    on the zone object passed in. RBZone has all six with the identical
    names/meanings, so these run against RB zones with zero modification.
  - full_viewer.build_bso_extra_lines() / .manual_control_and_parent_at() /
    .pine_time() / .pine_text() -- same reasoning: only z.id/z.bullish and
    the `res` dict from run_bso_chain, nothing OB-specific.

The Weekly RB layer itself is weekly_rb_generator.write_rb_pine(), also
unchanged, using its own extra_lines= hook (same mechanism
weekly_ob_generator.write_ob_pine() offers) to append the H4 + 5m layers
below into the SAME generated .pine file.

New/RB-specific in this file: build_manual_rb_gates() (the hand-verified
control timeline for RB, mirrors build_manual_gates()) and
build_h4_rb_extra_lines() (RB's own H4 layer -- adapted from
full_viewer.build_h4_extra_lines() only because RBZone stores its own
trigger/eligible/impact times directly as fields, with no OB-style
fallback-derivation helpers needed).
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
import weekly_rb_generator as rb       # noqa: E402
import h4_ob_engine as h4              # noqa: E402  (reuses aggregate_h4/permits -- generic)
import five_bso_engine as bso          # noqa: E402  (reuses aggregate_5m/run_bso_chain -- generic)
import full_viewer as fv               # noqa: E402  (reuses build_bso_extra_lines/pine_time/pine_text -- generic)

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Combined Weekly+4H+5m RB Pine viewer")
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--week-close-zone", default="America/New_York")
    p.add_argument("--week-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=120, choices=range(1, 161))
    p.add_argument("--pine-rbs", type=int, default=150, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--h4-anchor-hour", type=int, default=17, choices=range(24), help="NY-LOCAL hour the 4H grid starts from, DST-aware -- see h4_ob_engine.h4_grid_start().")
    p.add_argument("--h4-pine-rbs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--h4-pine-labels", type=int, default=80, choices=range(1, 161))
    p.add_argument("--window-start", default=None,
                    help="Only draw H4 RBs/trades/labels impacted on or after this date/time "
                         "(e.g. 2026-08-01 or '2026-08-01 09:00'), in --display-tz. Narrows the "
                         "known-gates window -- doesn't change what's computed, only what's drawn "
                         "in the .pine file. The CSVs (h4_rb_ledger.csv, five_bso_rb_ledger.csv, "
                         "weekly_rb_ledger.csv) always contain the FULL history regardless. Added "
                         "2026-09-24 because the whole-dataset render (122 H4 RBs, 152 5m trades) "
                         "is simply too much data for one Pine script to hold, no matter how it's "
                         "encoded -- see docs_rb/RB_RULES_LEARNED.md.")
    p.add_argument("--window-end", default=None,
                    help="Only draw H4 RBs/trades/labels impacted before this date/time, in "
                         "--display-tz. See --window-start.")
    return p.parse_args()


RB_LEDGER_FIELDS = [f.replace("h4_ob_", "h4_rb_") for f in bso.LEDGER_FIELDS]


def rb_relabel(res: Dict) -> Dict:
    """Relabel OB-specific wording in a five_bso_engine result dict for RB
    display, WITHOUT touching the shared engine itself (still used by the
    actual OB project, unmodified). Only ever renames labels; never
    changes any value that drives logic (result/stage classification,
    prices, times) -- purely cosmetic, per the user's explicit request
    ("we should use RB everywhere for consistency... I have seen 4H OB
    breached in the table which is weird while we are working on RB")."""
    out = dict(res)
    for k in ("stage", "result"):
        if out.get(k) == "H4_OB_BREACHED":
            out[k] = "H4_RB_BREACHED"
    return out


def rb_ledger_row(z, it: Optional[datetime], parent_id: str, invalidation_reason: Optional[str],
                   res: Dict, display_tz: ZoneInfo) -> Dict:
    row = bso.ledger_row(z, it, parent_id, invalidation_reason, rb_relabel(res), display_tz)
    return {k.replace("h4_ob_", "h4_rb_"): v for k, v in row.items()}


def build_manual_rb_gates() -> List[Tuple[datetime, datetime, str, str, str]]:
    """Hand-verified RB control timeline, gates 1 through the final BUY_ONLY
    (2026-02-09 -> 2026-09-11, end of the loaded M1 data). Same tuple shape
    as OB's build_manual_gates(): (start, end, control, sell_parent_id,
    buy_parent_id). Every boundary was checked directly against
    weekly_rb_ledger.csv / weekly_rb_swings.csv / the raw M1 data before
    being encoded -- see docs_rb/RB_RULES_LEARNED.md for the full
    gate-by-gate verification record and worked examples.

    PARENT-IN-CHARGE RULE (final form, corrected 2026-09-24 -- see
    RB_RULES_LEARNED.md's "Parent-in-charge rule, corrected" entry for the
    full derivation): a side's parent updates ONLY the instant price
    actually REACTS off (impacts/touches) a zone on that side -- never
    merely because a new zone was created/triggered, and never merely
    because a structural/swing/MSS continuation event fires (a swing
    confirming, an MSS exceedance, an RB's own anchor breaking). A
    continuation event can start/stop/flip CONTROL, but it never changes
    WHO the parent is -- the last-REACTED zone on that side stays in
    charge, even once SPENT, even after a Weekly-close body-breach kills
    it, until a newer zone on that same side is actually touched by price.
    This is why the same sell_parent/buy_parent id often persists across
    many consecutive gates below, including through control flips to the
    opposite side and back.

    Gate boundaries (WHEN control changes) were established gate-by-gate
    through direct verification exactly as for gates 1-7 (documented
    in-line through 2026-09-24's history in RB_RULES_LEARNED.md): each
    boundary is either an RB reaction (an opposing zone's impact, which
    opens BOTH), an RB's own anchor breaking or a Weekly-close body-breach
    (which closes one side of BOTH), or a real-time MSS/swing-confirm
    continuation event (which starts/stops a single-direction campaign,
    reacting to whichever side that event protects). Two recurring
    resolution rules for BOTH: (1) if the just-impacted zone gets a clean
    "respect" reaction (a later swing confirms at/near the exact impact
    price with no break of its own anchor in between), control flips FULLY
    to that side at the swing-confirm minute, not just staying BOTH until
    the anchor eventually breaks; (2) if a stopping continuation event
    (e.g. a swing confirming) coincides in the SAME M1 minute as a fresh
    zone impact on the side that event would otherwise stop, the impact
    overrides the stop -- control continues/opens BOTH instead.

    Full parent history so far (each id's FIRST reaction time, i.e. the
    moment it actually starts being parent):
      SELL: #2 (2026-02-09 15:07) -> #6 (2026-04-08 01:32) -> #8
        (2026-05-06 13:45) -> #15 (2026-07-29 21:53) -> #13 (2026-08-07
        15:34) -> #12 (2026-08-19 16:29, current).
      BUY: none until #3 (2026-02-17 18:28) -> #1 (2026-03-03 17:24) ->
        #9 (2026-05-14 18:00) -> #11 (2026-06-05 16:00) -> #7 (2026-06-08
        12:31) -> #5 (2026-06-19 07:57) -> #14 (2026-07-23 15:43, current).
    Note this corrects two things already shipped before the rule's final
    form was nailed down: gate 2 (2026-02-16 -> 02-17 18:28) has NO buy
    parent -- zone #3 is only created then, not reacted to until 02-17
    18:28 -- and gate 7 (2026-04-08 01:36 -> 04-29 21:37)'s buy parent is
    #1 (RB1, last reacted 2026-03-03), not #7 -- zone #7 was created that
    same minute but not actually touched by price until 2026-06-08."""
    rtz = ZoneInfo("Asia/Riyadh")

    def rt(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
        return datetime(y, mo, d, h, mi, tzinfo=rtz)

    return [
        (rt(2026, 2, 9, 15, 7), rt(2026, 2, 16, 1, 0), "SELL_ONLY", "2", ""),
        (rt(2026, 2, 16, 1, 0), rt(2026, 2, 17, 18, 28), "BUY_ONLY", "2", ""),
        (rt(2026, 2, 17, 18, 28), rt(2026, 2, 19, 16, 1), "BUY_ONLY", "2", "3"),
        (rt(2026, 2, 19, 16, 1), rt(2026, 3, 3, 17, 24), "SELL_ONLY", "2", "3"),
        (rt(2026, 3, 3, 17, 24), rt(2026, 3, 3, 17, 26), "BOTH", "2", "1"),
        (rt(2026, 3, 3, 17, 26), rt(2026, 3, 23, 14, 6), "SELL_ONLY", "2", "1"),
        (rt(2026, 3, 23, 14, 6), rt(2026, 3, 30, 12, 17), "NONE", "2", "1"),
        (rt(2026, 3, 30, 12, 17), rt(2026, 4, 8, 1, 32), "SELL_ONLY", "2", "1"),
        (rt(2026, 4, 8, 1, 32), rt(2026, 4, 8, 1, 36), "SELL_ONLY", "6", "1"),
        (rt(2026, 4, 8, 1, 36), rt(2026, 4, 29, 21, 37), "BUY_ONLY", "6", "1"),
        (rt(2026, 4, 29, 21, 37), rt(2026, 5, 6, 13, 45), "NONE", "6", "1"),
        (rt(2026, 5, 6, 13, 45), rt(2026, 5, 11, 1, 0), "BOTH", "8", "1"),
        (rt(2026, 5, 11, 1, 0), rt(2026, 5, 14, 18, 0), "BUY_ONLY", "8", "1"),
        (rt(2026, 5, 14, 18, 0), rt(2026, 5, 15, 3, 38), "BUY_ONLY", "8", "9"),
        (rt(2026, 5, 15, 3, 38), rt(2026, 5, 29, 17, 51), "SELL_ONLY", "8", "9"),
        (rt(2026, 5, 29, 17, 51), rt(2026, 6, 5, 16, 0), "NONE", "8", "9"),
        (rt(2026, 6, 5, 16, 0), rt(2026, 6, 5, 16, 51), "BOTH", "8", "11"),
        (rt(2026, 6, 5, 16, 51), rt(2026, 6, 8, 12, 31), "SELL_ONLY", "8", "11"),
        (rt(2026, 6, 8, 12, 31), rt(2026, 6, 15, 0, 29), "BOTH", "8", "7"),
        (rt(2026, 6, 15, 0, 29), rt(2026, 6, 17, 22, 24), "BUY_ONLY", "8", "7"),
        (rt(2026, 6, 17, 22, 24), rt(2026, 6, 19, 7, 57), "SELL_ONLY", "8", "7"),
        (rt(2026, 6, 19, 7, 57), rt(2026, 6, 23, 11, 17), "BOTH", "8", "5"),
        (rt(2026, 6, 23, 11, 17), rt(2026, 7, 14, 15, 30), "SELL_ONLY", "8", "5"),
        (rt(2026, 7, 14, 15, 30), rt(2026, 7, 23, 15, 43), "NONE", "8", "5"),
        (rt(2026, 7, 23, 15, 43), rt(2026, 7, 27, 1, 0), "BOTH", "8", "14"),
        (rt(2026, 7, 27, 1, 0), rt(2026, 7, 29, 21, 53), "SELL_ONLY", "8", "14"),
        (rt(2026, 7, 29, 21, 53), rt(2026, 7, 30, 13, 43), "SELL_ONLY", "15", "14"),
        (rt(2026, 7, 30, 13, 43), rt(2026, 8, 7, 15, 34), "BUY_ONLY", "15", "14"),
        (rt(2026, 8, 7, 15, 34), rt(2026, 8, 19, 15, 36), "BOTH", "13", "14"),
        (rt(2026, 8, 19, 15, 36), rt(2026, 8, 19, 16, 29), "BUY_ONLY", "13", "14"),
        (rt(2026, 8, 19, 16, 29), rt(2026, 8, 20, 9, 45), "BOTH", "12", "14"),
        (rt(2026, 8, 20, 9, 45), rt(2026, 8, 31, 0, 4), "BUY_ONLY", "12", "14"),
        (rt(2026, 8, 31, 0, 4), rt(2026, 9, 9, 9, 15), "NONE", "12", "14"),
        (rt(2026, 9, 9, 9, 15), rt(2026, 9, 11, 22, 5), "BUY_ONLY", "12", "14"),
    ]


def build_h4_rb_extra_lines(h4_engine: rb.WeeklyRBEngine, h4_bars: List["wob.Week"], drawn: List[tuple],
                              rb_cap: int, display_tz: ZoneInfo,
                              window_start: Optional[datetime] = None, window_end: Optional[datetime] = None,
                              label_cap: int = 80) -> List[str]:
    """RB's own H4 layer. Adapted from full_viewer.build_h4_extra_lines():
    same array-packing discipline, same impact_x_<id> cross-timeframe
    watcher technique, same "boxes/lines also render on 5m, table/labels
    stay H4-only" split. Differs only because RBZone already stores its
    own trigger_time/eligible_time/impact_time as plain fields -- no
    OB-style trigger_display_detail/eligibility_detail/impact_time
    fallback-derivation helpers needed."""
    shown = drawn[-rb_cap:]
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
        struct_x.append(rb.pine_epoch(h4_bars[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▲"); struct_col.append("B"); struct_low.append(False)
    for e in sl:
        struct_x.append(rb.pine_epoch(h4_bars[e.swing].start)); struct_y.append(e.price)
        struct_txt.append("▼"); struct_col.append("K"); struct_low.append(True)
    for m in ms:
        struct_x.append(rb.pine_epoch(h4_bars[m.broken].start))
        struct_y.append(m.price)
        struct_txt.append("✕"); struct_col.append("B" if m.up else "K")
        struct_low.append(not m.up)

    lefts, tops, bottoms, fallback_rights, impact_stamps, bulls, labels, parents, sides, bots5, tops5, trigs, eligs, impacts = ([] for _ in range(14))
    for z, parent_id in shown:
        origin = h4_bars[z.candle]
        lefts.append(rb.pine_epoch(origin.start))
        tops.append(z.zt)
        bottoms.append(z.zb)
        fallback_rights.append(rb.pine_epoch(h4_bars[z.stop].start))  # guaranteed valid: authorized => impacted => z.stop set
        impact_stamps.append(rb.pine_epoch(z.impact_time))  # guaranteed: authorized => impacted => impact_time set
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
        "bool inspectOneH4RB = input.bool(true, \"Inspect one 4H RB only\", group=\"H4 RB inspection\")",
        f"int h4RbFromLast = input.int(1, \"H4 RB from last\", minval=1, maxval={max(1, n)}, group=\"H4 RB inspection\", tooltip=\"1 = most recent 4H RB, 2 = the one before it, and so on.\")",
        f"var table h4RbLedger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        *fv.pack_array("h4RbLeft", "int", lefts),
        *fv.pack_array("h4RbTop", "float", tops),
        *fv.pack_array("h4RbBottom", "float", bottoms),
        *fv.pack_array("h4RbBull", "bool", bulls),
        *fv.pack_array("h4RbLabel", "string", labels),
        *fv.pack_array("h4RbId", "string", ids),
        *fv.pack_array("h4RbParent", "string", parents),
        *fv.pack_array("h4RbSide", "string", sides),
        *fv.pack_array("h4RbBot5", "string", bots5),
        *fv.pack_array("h4RbTop5", "string", tops5),
        *fv.pack_array("h4RbTrig", "string", trigs),
        *fv.pack_array("h4RbElig", "string", eligs),
        *fv.pack_array("h4RbImpact", "string", impacts),
        *fv.pack_array("h4RbFallbackRight", "int", fallback_rights),
        *fv.pack_array("h4RbImpactStamp", "int", impact_stamps),
        *fv.pack_array("h4RbStructX", "int", struct_x),
        *fv.pack_array("h4RbStructY", "float", struct_y),
        *fv.pack_array("h4RbStructTxt", "string", struct_txt),
        *fv.pack_array("h4RbStructCol", "string", struct_col),
        *fv.pack_array("h4RbStructLow", "bool", struct_low),
        # ONE shared per-bar watcher loop replaces what used to be a
        # separate named `var int h4rbimpact_x_<id>` + its own 3-line `if`
        # per zone (up to 3n top-level statements). Same effect (each
        # slot latches to the real bar `time` the instant it reaches that
        # zone's own impact minute, never a lookahead), but O(1) compile
        # cost regardless of n -- the other half of the 2026-09-24 fix,
        # see pack_array's own docstring for the array.from(...) half.
        f"var array<int> h4RbImpactX = array.new<int>({n}, na)",
        "for hi = 0 to array.size(h4RbImpactStamp) - 1",
        "    hiStamp = array.get(h4RbImpactStamp, hi)",
        "    if na(array.get(h4RbImpactX, hi)) and time <= hiStamp and hiStamp < time_close",
        "        array.set(h4RbImpactX, hi, time)",
        "if barstate.islast",
        "    if onH4 or on1m or onFive",
        "        for i = 0 to array.size(h4RbLeft) - 1",
        "            hrRank = array.size(h4RbLeft) - i",
        "            if not inspectOneH4RB or hrRank == h4RbFromLast",
        "                hrRight = na(array.get(h4RbImpactX, i)) ? array.get(h4RbFallbackRight, i) : array.get(h4RbImpactX, i)",
        "                hrCol = array.get(h4RbBull, i) ? color.blue : color.black",
        "                box.new(array.get(h4RbLeft, i), array.get(h4RbTop, i), hrRight, array.get(h4RbBottom, i), border_color=hrCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "                label.new(array.get(h4RbLeft, i), array.get(h4RbTop, i), array.get(h4RbLabel, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hrCol,85), textcolor=hrCol, size=size.tiny)",
        "                line.new(hrRight, array.get(h4RbBottom, i), hrRight, array.get(h4RbTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)",
        "    if onH4",
        "        for i = 0 to array.size(h4RbStructX) - 1",
        "            hrStructCol = array.get(h4RbStructCol, i) == \"B\" ? color.blue : color.black",
        "            hrStructYY = array.get(h4RbStructLow, i) ? array.get(h4RbStructY, i) - lowGap : array.get(h4RbStructY, i)",
        "            label.new(array.get(h4RbStructX, i), hrStructYY, array.get(h4RbStructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=hrStructCol, size=size.small)",
        "        table.cell(h4RbLedger, 0, 0, \"4H RB\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 1, 0, \"Parent W\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 3, 0, \"Bottom\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 4, 0, \"Top\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 5, 0, \"Trigger (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 6, 0, \"Eligible (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        table.cell(h4RbLedger, 7, 0, \"Impact (RYD)\", text_color=color.white, bgcolor=color.new(color.blue,15))",
        "        for i = 0 to array.size(h4RbLeft) - 1",
        "            hrRank = array.size(h4RbLeft) - i",
        "            if not inspectOneH4RB or hrRank == h4RbFromLast",
        "                hrRow = inspectOneH4RB ? 1 : i + 1",
        "                table.cell(h4RbLedger, 0, hrRow, array.get(h4RbId, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 1, hrRow, array.get(h4RbParent, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 2, hrRow, array.get(h4RbSide, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 3, hrRow, array.get(h4RbBot5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 4, hrRow, array.get(h4RbTop5, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 5, hrRow, array.get(h4RbTrig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 6, hrRow, array.get(h4RbElig, i), text_color=color.black, bgcolor=na)",
        "                table.cell(h4RbLedger, 7, hrRow, array.get(h4RbImpact, i), text_color=color.black, bgcolor=na)",
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

    weekly_engine = rb.WeeklyRBEngine(minutes, weeks)
    weekly_engine.run()

    h4_bars = h4.aggregate_h4(minutes, args.h4_anchor_hour)
    h4_engine = rb.WeeklyRBEngine(minutes, h4_bars)
    h4_engine.run()

    gates = build_manual_rb_gates()

    rows = []
    drawn = []
    for z in h4_engine.zones:
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1, 4) if impacted else None  # not the ORBs
        ctrl_parent = fv.manual_control_and_parent_at(gates, z.impact_time, z.bullish) if (impacted and z.impact_time is not None) else None
        ctrl, parent_id = ctrl_parent if ctrl_parent is not None else ("", "")
        authorized = bool(impacted and pre_spent_ok and h4.permits(ctrl, z.bullish))
        origin_bar = h4_bars[z.candle]
        rows.append(dict(
            id=z.id, side="BUY" if z.bullish else "SELL", type=rb.status(z),
            bottom=f"{z.zb:.5f}", top=f"{z.zt:.5f}",
            origin_utc=wob.iso(origin_bar.start), origin_riyadh=wob.display_iso(origin_bar.start, display_tz),
            trigger_riyadh=wob.display_iso(z.trigger_time, display_tz),
            eligible_riyadh=wob.display_iso(z.eligible_time, display_tz),
            impact_riyadh=wob.display_iso(z.impact_time, display_tz),
            control_at_impact=ctrl, parent_weekly_id=parent_id, authorized=authorized,
        ))
        if authorized:
            drawn.append((z, parent_id))

    with (base / "h4_rb_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "side", "type", "bottom", "top", "origin_utc", "origin_riyadh",
                   "trigger_riyadh", "eligible_riyadh", "impact_riyadh",
                   "control_at_impact", "parent_weekly_id", "authorized"]
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    # Span of the currently hand-verified/narrated gates only -- NOT
    # gates[-1][1], which is the open-ended trailing NONE's end (almost
    # the whole dataset). Authorization itself is already correct
    # regardless (permits() only matches a zone impacted inside an actual
    # SELL_ONLY/BUY_ONLY/BOTH gate), but this window also scopes which H4
    # swing/MSS labels get shown, which must stay to the real, verified
    # span -- the last gate before the final trailing NONE marks that end.
    window_start = gates[0][0]
    window_end = gates[-1][0] if gates[-1][2] == "NONE" else gates[-1][1]

    # --window-start/--window-end (2026-09-24): narrow the drawn slice on
    # top of the known-gates span above -- never widen it. The whole-
    # dataset render (122 H4 RBs, 152 5m trades) is too much data for one
    # Pine script regardless of encoding; this lets the user pick a
    # smaller slice to actually view while the CSVs above still hold the
    # complete, unwindowed history. See docs_rb/RB_RULES_LEARNED.md.
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
    h4_extra_lines = build_h4_rb_extra_lines(h4_engine, h4_bars, focused_drawn, args.h4_pine_rbs, display_tz,
                                              window_start, window_end, args.h4_pine_labels)

    mt = [m.t for m in minutes]
    h4_bar_starts = [b.start for b in h4_bars]
    five_bars = bso.aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = rb.WeeklyRBEngine(minutes, five_bars)
    five_engine.run()

    bso_results = []
    for z, parent_id in focused_drawn:
        invalidated_at, invalidation_reason = bso.structural_invalid_at(z, z.impact_time, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = bso.run_bso_chain(z, z.impact_time, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            bso_results.append((z, z.impact_time, parent_id, invalidation_reason, rb_relabel(res)))
    # build_bso_extra_lines is reused verbatim from the OB project (it's
    # otherwise fully generic -- see the module docstring), but its own
    # 5m table header hardcodes "Weekly OB"/"4H OB" literally. Patched
    # post-hoc rather than duplicating the whole function for two labels;
    # the shared OB function itself stays untouched.
    bso_extra_lines = [
        line.replace('"Weekly OB"', '"Weekly RB"').replace('"4H OB"', '"4H RB"')
        for line in fv.build_bso_extra_lines(bso_results, display_tz)
    ]

    with (base / "five_bso_rb_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=RB_LEDGER_FIELDS)
        wr.writeheader()
        for z, it, parent_id, invalidation_reason, res in bso_results:
            wr.writerow(rb_ledger_row(z, it, parent_id, invalidation_reason, res, display_tz))

    extra_lines = h4_extra_lines + bso_extra_lines

    rb.write_rb_pine(base, weekly_engine, args.pine_labels, args.pine_rbs, args.pine_table,
                      display_tz, extra_lines=extra_lines, out_name="full_rb_viewer.pine")
    rb.write_ledger(base, weekly_engine, display_tz)
    rb.write_report(base, minutes, weeks, warnings, weekly_engine, args, display_tz)

    print("Created:")
    print("  full_rb_viewer.pine   (Weekly RB layer + 4H RB layer/table + 5m BSO entry lines)")
    print("  h4_rb_ledger.csv, five_bso_rb_ledger.csv")
    print("  weekly_rb_ledger.csv, weekly_rb_swings.csv, weekly_rb_report.txt")
    print(f"Known gates window: {window_start} -> {window_end} ({len(gates) - 1} gates, gate 1 SELL_ONLY RB zone #2)")
    print(f"{len(h4_bars)} 4H bars, {len(h4_engine.zones)} H4 RBs computed, {len(drawn)} authorized, {len(focused_drawn)} shown (known gates window).")
    bso_stages: Dict[str, int] = {}
    for _z, _it, _parent_id, _reason, res in bso_results:
        bso_stages[res.get("stage")] = bso_stages.get(res.get("stage"), 0) + 1
    print(f"5m BSO on {len(bso_results)} drawn RBs: {bso_stages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
