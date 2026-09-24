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
    """Hand-verified RB control timeline, gates 1-5 (through 2026-03-23).
    Same tuple shape as OB's build_manual_gates(): (start, end, control,
    sell_parent_id, buy_parent_id). Every boundary below was checked
    directly against weekly_rb_ledger.csv / weekly_rb_swings.csv / the raw
    M1 data before being encoded -- see docs_rb/RB_RULES_LEARNED.md for the
    full gate-by-gate verification record.

    Gate 1 -- SELL_ONLY (RB zone #2, ARB):
      RB zone #2 (Weekly ARB, bearish -- top=1.20825, bottom=1.18609) has
      trigger, eligible and impact all at the SAME minute, 2026-02-09
      15:07 Riyadh. Trend context (2025 carryover, user-supplied, not
      derivable from this 2026-only dataset): Weekly trend was UP, so this
      is a COUNTERTREND SELL_ONLY start (trend and control are independent
      per SPEC.md SS9). Dies at the containing week's own close: week
      2026-02-09 -> 02-16 Riyadh closes at 1.18722, which is >= zb
      (1.18609) -- Weekly-close-body-inside/through POI-breach (SPEC.md
      SS14).

    Gate 2 -- BUY_ONLY (RB zone #3, AIRB), 2026-02-16 -> 02-19 16:01 Riyadh:
      RB2 (the only countertrend zone) is dead, so control reverts to the
      underlying UP trend at the next week's open. Zone #3 (AIRB, BUY,
      zb=1.17652/zt=1.18095) is first TOUCHED mid-week (2026-02-17 18:28
      Riyadh, "no respect") without ending BUY_ONLY -- a touch alone
      doesn't flip control.

      Ends the moment MSS actually confirms: MSS does NOT require a close
      -- a 1-pip wick exceedance of the protecting swing point is enough,
      real-time, whatever the timeframe (SPEC clarification, user-given).
      The swing protecting this BUY leg is AIRB #3's own anchor low,
      1.17652 (confirmed swing, weekly_rb_swings.csv). First M1 wick
      below it: 2026-02-19 16:01 Riyadh (low 1.17645, close 1.17648 --
      same minute also closes through, so no ambiguity here between the
      wick and close reads). This is BEFORE the week's own close
      (02-23 01:00 Riyadh) -- an earlier draft of this gate incorrectly
      used the week's close as the boundary; a real H4 RB (#91) got
      authorized BUY on 2026-02-20 18:12 Riyadh under that wrong boundary
      even though the real-time MSS-down had already confirmed the day
      before. Corrected here.

    Gate 3 -- SELL_ONLY, no anchor zone, 2026-02-19 16:01 -> 03-03 17:24
    Riyadh:
      Starts at the same 2026-02-19 16:01 Riyadh MSS-down confirmation
      above. (The week-of-2026-02-16's own close, 1.17921, is also below
      the PRIOR week's low, 1.18086 -- a real structural fact, but it is
      a CONSEQUENCE of the same real-time move, not the trigger: the
      trigger already fired days earlier via the wick-exceedance rule.)
      Read as: AIRB #3 failed to hold, trend flipped bearish, BUY_ONLY
      ends. RB2 (the old SELL parent) already died in gate 1, but the
      "parent" isn't blank -- parent-in-charge is the LAST RB zone on the
      current bias side, whether or not it has been impacted yet (user
      rule, 2026-09-23: "get the RB in charge from the last RB that has
      the same direction as our bias"). The last SELL zone that exists by
      2026-02-19 16:01 is zone #4 (Weekly ORB, bearish, top=1.19283,
      bottom=1.18722, confirmed/promoted at this exact same MSS-down
      minute) -- so zone #4, not RB2, is gate 3's sell parent.

    Gate 4 -- BOTH, 2026-03-03 17:24 -> 17:26 Riyadh (2 minutes):
      RB1 (W ORB #1, BUY, zb=1.15692/zt=1.15797) is impacted at 2026-03-03
      17:24 Riyadh, opening BOTH directions per RB1's buy side alongside
      the ongoing sell thesis (sell side still in charge of zone #4, per
      the same last-RB-on-that-side rule).

    Gate 5 -- SELL_ONLY, resumes 2026-03-03 17:26 Riyadh:
      Just 2 minutes after RB1's impact, price breaks below RB1's own
      floor (1.15692 -- RB1's own swing-low anchor, confirmed week of
      2026-01-19) at 2026-03-03 17:26 Riyadh (low 1.15667) -- RB1's
      protecting swing low is violated, snapping control back to
      SELL_ONLY. Zone #4 is still the last (and only) SELL zone in
      existence through the end of this gate -- no newer SELL zone is
      born until zone #6 (origin week 2026-03-23, well after this gate
      ends) -- so zone #4 stays the sell parent here too.

      Stops at 2026-03-23 14:06 Riyadh: the first real-time minute price
      exceeds the PRIOR week's high (week-of-2026-03-16, high=1.16159) --
      high=1.1619 at that minute. User-confirmed as the actual rule (NOT
      the later, formally-confirmed engine SWING HIGH at 1.16394/week of
      2026-03-30, which lags this real-time break by a week).

    NONE, 2026-03-23 14:06 -> 03-30 12:17 Riyadh:
      No live SELL RB anchor yet (zone #6 doesn't exist until the swing high
      that creates it confirms). Confirmed against the fixed
      weekly_rb_swings.csv real-minute export (2026-09-24 fix): the
      week-of-2026-03-23 swing high (1.16394) confirms at the exact M1
      minute 2026-03-30 12:17 Riyadh -- not the week-open label previously
      (wrongly) shown for it.

    Gate 6a -- SELL_ONLY, 2026-03-30 12:17 -> 04-08 01:32 Riyadh:
      Resumes selling the moment that swing high confirms real-time. Zone
      #6 (Weekly AIRB, SELL, zb=1.15348/zt=1.16394) is created at this same
      minute and is the new last (most recent) SELL zone in existence, so
      it's the sell parent -- same "last RB on the current bias side" rule
      already applied to zone #4 in gates 3-5.

    Gate 6b -- SELL_ONLY, 2026-04-08 01:32 -> 01:36 Riyadh (4 minutes):
      Zone #6 (still AIRB, not yet promoted) is impacted at 01:32 (first M1
      high, 1.16298, crossing its own zb 1.15348) -- confirmed against raw
      M1 data. Control stays SELL_ONLY (an AIRB touch alone doesn't flip
      control, same as zone #3 in gate 2), split into its own gate purely
      to mark the impact boundary in the record.

    Gate 7 -- BUY_ONLY, 2026-04-08 01:36 -> 04-29 21:37 Riyadh (correction,
    2026-09-24): 4 minutes after zone #6's impact, price wicks above its
    own top -- the same swing high (1.16394) that created it -- at 01:36.
    User corrected the original call here: this is NOT a stop to NONE, it's
    a trend SHIFT to up. No opposing (BUY) RB gets impacted to justify BOTH
    -- the only live, never-impacted BUY zone is far away (zone #7 itself is
    born this same minute, not yet eligible; the nearest pre-existing live
    SELL zone, #4, tops out at zb=1.18722, and price's real max in this
    whole window is only 1.18488, confirmed against raw M1 data -- so #4 is
    never touched). So BUY_ONLY opens with no opposing-impact anchor. Per
    the "last RB on the current bias side" rule, zone #7 (Weekly IRB, BUY,
    zb=1.14427/zt=1.15005, triggered this exact minute 2026-04-08 01:36) is
    the newest BUY zone in existence, so it's the buy parent -- despite
    itself not being eligible/impacted yet (same pattern as zone #4 in
    gates 3-5).

      Stops at 2026-04-29 21:37 Riyadh: the engine's formally-confirmed
      SWING HIGH at 1.18488 (peak itself printed 2026-04-17 13:12 UTC /
      16:12 Riyadh, confirmed two-sided on 2026-04-29 18:37 UTC / 21:37
      Riyadh once price pulled back enough) -- verified against the fixed
      weekly_rb_swings.csv real-minute export. Unlike an MSS/structural
      break (real-time, single wick), a swing-high stop is inherently the
      engine's own two-sided confirmation event -- there is no earlier
      real-time equivalent to prefer here. Goes to NONE at that minute.
      Next gate not yet given -- out of scope for this delivery."""
    rtz = ZoneInfo("Asia/Riyadh")

    def rt(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
        return datetime(y, mo, d, h, mi, tzinfo=rtz)

    return [
        (rt(2026, 2, 9, 15, 7), rt(2026, 2, 16, 1, 0), "SELL_ONLY", "2", ""),
        (rt(2026, 2, 16, 1, 0), rt(2026, 2, 19, 16, 1), "BUY_ONLY", "", "3"),
        (rt(2026, 2, 19, 16, 1), rt(2026, 3, 3, 17, 24), "SELL_ONLY", "4", ""),
        (rt(2026, 3, 3, 17, 24), rt(2026, 3, 3, 17, 26), "BOTH", "4", "1"),
        (rt(2026, 3, 3, 17, 26), rt(2026, 3, 23, 14, 6), "SELL_ONLY", "4", ""),
        (rt(2026, 3, 23, 14, 6), rt(2026, 3, 30, 12, 17), "NONE", "", ""),
        (rt(2026, 3, 30, 12, 17), rt(2026, 4, 8, 1, 32), "SELL_ONLY", "6", ""),
        (rt(2026, 4, 8, 1, 32), rt(2026, 4, 8, 1, 36), "SELL_ONLY", "6", ""),
        (rt(2026, 4, 8, 1, 36), rt(2026, 4, 29, 21, 37), "BUY_ONLY", "", "7"),
        (rt(2026, 4, 29, 21, 37), rt(2026, 9, 11, 22, 5), "NONE", "", ""),
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

    def arr(kind: str, values: List[str]) -> str:
        return f"array.from({', '.join(values)})" if values else f"array.new<{kind}>()"

    def in_window(t: datetime) -> bool:
        if window_start is None:
            return True
        return window_start <= t < window_end

    sh = [e for e in h4_engine.events if e.kind == 0 and in_window(h4_bars[e.swing].start)][-label_cap:]
    sl = [e for e in h4_engine.events if e.kind == 1 and in_window(h4_bars[e.swing].start)][-label_cap:]
    ms = [m for m in h4_engine.msses if in_window(h4_bars[m.broken].start)][-label_cap:]
    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(rb.pine_epoch(h4_bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▲\""); struct_col.append("color.blue"); struct_low.append("false")
    for e in sl:
        struct_x.append(rb.pine_epoch(h4_bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▼\""); struct_col.append("color.black"); struct_low.append("true")
    for m in ms:
        struct_x.append(rb.pine_epoch(h4_bars[m.broken].start))
        struct_y.append(f"{m.price:.5f}")
        struct_txt.append("\"✕\""); struct_col.append("color.blue" if m.up else "color.black")
        struct_low.append("false" if m.up else "true")

    impact_vars: Dict[int, str] = {}
    impact_watchers: List[str] = []
    for z, parent_id in shown:
        if z.impact_time is not None:  # guaranteed: authorized => impacted => impact_time set
            name = f"h4rbimpact_x_{z.id}"
            impact_vars[z.id] = name
            stamp = rb.pine_epoch(z.impact_time)
            impact_watchers += [f"var int {name} = na", f"if time <= {stamp} and {stamp} < time_close", f"    {name} := time"]

    lefts, tops, bottoms, right_exprs, bulls, labels, parents, sides, bots5, tops5, trigs, eligs, impacts = ([] for _ in range(13))
    for z, parent_id in shown:
        origin = h4_bars[z.candle]
        fallback_right = h4_bars[z.stop].start  # guaranteed valid: authorized => impacted => z.stop set
        lefts.append(rb.pine_epoch(origin.start))
        tops.append(f"{z.zt:.5f}")
        bottoms.append(f"{z.zb:.5f}")
        if z.id in impact_vars:
            right_exprs.append(f"(na({impact_vars[z.id]}) ? {rb.pine_epoch(fallback_right)} : {impact_vars[z.id]})")
        else:
            right_exprs.append(rb.pine_epoch(fallback_right))
        bulls.append("true" if z.bullish else "false")
        label_text = f"#{z.id} {'BUY' if z.bullish else 'SELL'} (W{parent_id})"
        labels.append(f"\"{fv.pine_text(label_text)}\"")
        parents.append(f"\"{fv.pine_text('#' + parent_id if parent_id else '-')}\"")
        sides.append(f"\"{'BUY' if z.bullish else 'SELL'}\"")
        bots5.append(f"\"{z.zb:.5f}\"")
        tops5.append(f"\"{z.zt:.5f}\"")
        trig_txt = wob.display_iso(z.trigger_time, display_tz)
        elig_txt = wob.display_iso(z.eligible_time, display_tz)
        trigs.append(f"\"{fv.pine_text(trig_txt)}\"")
        eligs.append(f"\"{fv.pine_text(elig_txt)}\"")
        impacts.append(f"\"{fv.pine_text(wob.display_iso(z.impact_time, display_tz))}\"")

    ids = [f"\"{'#' + str(z.id)}\"" for z, *_ in shown]

    lines: List[str] = [
        "bool inspectOneH4RB = input.bool(true, \"Inspect one 4H RB only\", group=\"H4 RB inspection\")",
        f"int h4RbFromLast = input.int(1, \"H4 RB from last\", minval=1, maxval={max(1, n)}, group=\"H4 RB inspection\", tooltip=\"1 = most recent 4H RB, 2 = the one before it, and so on.\")",
        f"var table h4RbLedger = table.new(position.bottom_right, 8, {n + 1}, border_width=1)",
        f"var array<int> h4RbLeft = {arr('int', lefts)}",
        f"var array<float> h4RbTop = {arr('float', tops)}",
        f"var array<float> h4RbBottom = {arr('float', bottoms)}",
        f"var array<bool> h4RbBull = {arr('bool', bulls)}",
        f"var array<string> h4RbLabel = {arr('string', labels)}",
        f"var array<string> h4RbId = {arr('string', ids)}",
        f"var array<string> h4RbParent = {arr('string', parents)}",
        f"var array<string> h4RbSide = {arr('string', sides)}",
        f"var array<string> h4RbBot5 = {arr('string', bots5)}",
        f"var array<string> h4RbTop5 = {arr('string', tops5)}",
        f"var array<string> h4RbTrig = {arr('string', trigs)}",
        f"var array<string> h4RbElig = {arr('string', eligs)}",
        f"var array<string> h4RbImpact = {arr('string', impacts)}",
        f"var array<int> h4RbStructX = {arr('int', struct_x)}",
        f"var array<float> h4RbStructY = {arr('float', struct_y)}",
        f"var array<string> h4RbStructTxt = {arr('string', struct_txt)}",
        f"var array<color> h4RbStructCol = {arr('color', struct_col)}",
        f"var array<bool> h4RbStructLow = {arr('bool', struct_low)}",
        *impact_watchers,
        "if barstate.islast",
        "    if onH4 or on1m or onFive",
        f"        array<int> h4RbRight = {arr('int', right_exprs)}",
        "        for i = 0 to array.size(h4RbLeft) - 1",
        "            hrRank = array.size(h4RbLeft) - i",
        "            if not inspectOneH4RB or hrRank == h4RbFromLast",
        "                hrCol = array.get(h4RbBull, i) ? color.blue : color.black",
        "                box.new(array.get(h4RbLeft, i), array.get(h4RbTop, i), array.get(h4RbRight, i), array.get(h4RbBottom, i), border_color=hrCol, border_width=1, border_style=line.style_dashed, bgcolor=na, xloc=xloc.bar_time)",
        "                label.new(array.get(h4RbLeft, i), array.get(h4RbTop, i), array.get(h4RbLabel, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hrCol,85), textcolor=hrCol, size=size.tiny)",
        "                line.new(array.get(h4RbRight, i), array.get(h4RbBottom, i), array.get(h4RbRight, i), array.get(h4RbTop, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red,30), width=1)",
        "    if onH4",
        "        for i = 0 to array.size(h4RbStructX) - 1",
        "            hrStructYY = array.get(h4RbStructLow, i) ? array.get(h4RbStructY, i) - lowGap : array.get(h4RbStructY, i)",
        "            label.new(array.get(h4RbStructX, i), hrStructYY, array.get(h4RbStructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=array.get(h4RbStructCol, i), size=size.small)",
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
