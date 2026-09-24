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

A third, 5m-only layer (`onFive`, see build_bso_extra_lines) runs
five_bso_engine.run_bso() on exactly the OBs drawn above and shows the entry
machine: a blue line at the entry/candidate price from when that candidate
became active to the moment price broke it, then a red line (SL hit first)
or green line (TP hit first) at that level from entry to the exit minute.
Writes five_bso_ledger.csv alongside h4_ob_ledger.csv.

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
import five_bso_engine as bso      # noqa: E402  (reuses its aggregate_5m/run_bso)

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
    p.add_argument("--h4-anchor-hour", type=int, default=17, choices=range(24), help="NY-LOCAL hour the 4H grid starts from, DST-aware -- see h4_ob_engine.h4_grid_start(). Default 17 matches the Weekly close hour (grid: 17/21/01/05/09/13 NY-local).")
    p.add_argument("--h4-pine-obs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--h4-pine-labels", type=int, default=80, choices=range(1, 161), help="max recent H4 swing-high/swing-low/MSS labels shown (each)")
    p.add_argument("--control-ledger", default=None)
    p.add_argument("--focus-weekly-id", type=int, default=0,
                    help="Only draw/table 4H OBs whose parent Weekly zone matches this ID "
                         "(0 = show every authorized OB across the whole dataset).")
    p.add_argument("--manual-gates", action="store_true",
                    help="Use the hand-verified control timeline (see build_manual_gates()) instead of "
                         "weekly_control_ledger.csv for authorization, for the window it covers. "
                         "weekly_control_engine.py does not yet implement SS16's NONE state or the "
                         "Weekly-close-body-inside-zone kill rule, so its control column is wrong for "
                         "this stretch; this flag uses the sequence the user verified gate-by-gate "
                         "against raw price instead (TRADING_SYSTEM_HANDOFF.md, 2026-09-16). Outside "
                         "the covered window, falls back to the normal weekly_control_ledger.csv lookup.")
    return p.parse_args()


def build_manual_gates() -> List[Tuple[datetime, datetime, str, str, str]]:
    """Control timeline from zone #3's impact through the end of the
    dataset. Originally hand-verified (TRADING_SYSTEM_HANDOFF.md's
    2026-09-16 "user-verified gate-by-gate control sequence" entry) as 14
    gates; now 16, after this session's port into weekly_control_engine.py
    surfaced two more real, previously-missed transitions (gates 2/3 below)
    that the hand walkthrough never caught, confirmed real by the user and
    folded in here. Each row is (start, end, control, sell_parent_id,
    buy_parent_id):

      1. 2026-04-14 17:55 -> 2026-05-06 13:45  SELL_ONLY (zone 3)
      2. 2026-05-06 13:45 -> 2026-05-14 18:00  NONE       (swing low confirms -- found by the
                                                            automated port, not originally
                                                            hand-verified; confirmed real)
      3. 2026-05-14 18:00 -> 2026-05-29 17:51  SELL_ONLY (swing high confirms, sell resumes --
                                                            same origin as gate 2)
      4. 2026-05-29 17:51 -> 2026-06-05 16:51  NONE       (swing low confirms)
      5. 2026-06-05 16:51 -> 2026-06-05 18:37  SELL_ONLY (that low breaks, sell resumes)
      6. 2026-06-05 18:37 -> 2026-06-08 00:00  BOTH       (zone 5 impacted, zone 8 still alive)
      7. 2026-06-08 00:00 -> 2026-06-15 00:29  SELL_ONLY (week closes body inside zone 5 -- buy
                                                            dead immediately, no swing wait needed)
      8. 2026-06-15 00:29 -> 2026-06-17 22:24  NONE       (fresh, unrelated swing low confirms)
      9. 2026-06-17 22:24 -> 2026-07-14 15:30  SELL_ONLY (that low breaks, sell resumes)
     10. 2026-07-14 15:30 -> 2026-07-23 15:43  NONE       (swing low confirms)
     11. 2026-07-23 15:43 -> 2026-07-29 21:53  SELL_ONLY (swing HIGH confirms -- see rule
                                                            revision below, not the old
                                                            "swing low taken out" rule)
     12. 2026-07-29 21:53 -> 2026-07-30 16:48  NONE       (new swing low confirms, no buy
                                                            in control)
     13. 2026-07-30 16:48 -> 2026-08-03 00:00  SELL_ONLY (zone 9, first reaction from a
                                                            plain NONE; one entry only)
     14. 2026-08-03 00:00 -> 2026-08-19 15:49  NONE       (zone 9's own containing week
                                                            closes body INSIDE its box --
                                                            dies; nothing tradable until
                                                            zone 8 reacts)
     15. 2026-08-19 15:49 -> 2026-08-24 00:00  SELL_ONLY (zone 8 reacts; one entry only)
     16. 2026-08-24 00:00 -> 2026-09-11 22:05  NONE       (zone 8's own containing week
                                                            closes with a full body breach
                                                            through its own top -- dies;
                                                            no tradable zone left anywhere;
                                                            stays NONE through the last 1m
                                                            bar in the CSV, 2026-09-11 22:05)

    All 16 gates above are now independently reproduced by
    weekly_control_engine.py itself (SWING_PAUSE/SWING_RESUME/ZONE_DEATH
    events in weekly_control_events.csv), including the body-close-dead
    rule (gates 7, 14, 16 above) and the swing-high-resume rule (gates 3,
    9, 11) -- this table is kept as the same hand-checkable reference it
    always was, not because the engine can't derive it anymore.

    Rule revision (earlier session, user-directed): the earlier assumption
    that SELL resumes from NONE when "the swing low that caused NONE gets
    taken out" is WRONG and is abandoned going forward. The real rule: SELL
    resumes the moment a Weekly swing HIGH confirms (gates 3, 5, 9, 11
    above). Verified against gates 4->5 and 8->9 above (both already
    chart-confirmed by the user before this revision) -- gate 8->9 lands on
    the identical minute either way, no conflict; gate 4->5 differs by 51
    minutes under the new rule (16:00 vs. 16:51) but the user confirmed this
    makes no material difference (same 4H structures, same 5m entries either
    way), so that timestamp is kept exactly as originally verified, NOT
    retroactively recomputed.

    New mechanism (earlier session): exiting a *plain* NONE with no live
    campaign (gates 12->13, 14->15) is governed by whichever zone reacts
    first, either side -- not the swing-high rule, which only applies when
    resuming a campaign that already has a live supporting swing high (gate
    10->11). Gates 13 and 15 each represent exactly ONE entry (from zones 9
    and 8 respectively) before their own zone dies to the body-close rule.

    Gates 2/3 (this session): while porting all of the above into
    weekly_control_engine.py itself, a real bug surfaced a genuine gap in
    the hand-verified chain -- a zone's own is_spent_state stays true
    forever once ever impacted, even after that zone's own control episode
    already concluded via ZONE_DEATH. Zone #1's long-dead BUY campaign
    (spent + died back in week 10, months before zone #3's SELL_ONLY even
    starts) was wrongly counted as "an opposing zone in control" and
    silently blocked every SWING_PAUSE check for the rest of the dataset.
    Fixing that (control being single-direction already means no concurrent
    opposition exists, by construction of the BOTH-promotion check) exposed
    a real, previously-missed swing low/high pause-resume pair at
    2026-05-06 13:45 / 2026-05-14 18:00 that the original hand walkthrough
    never caught. User confirmed these are real and must be included, not
    dismissed as non-material like the 4->5 timing difference above.

    During BOTH (gate 6), sell_parent=3 (the same ongoing SELL thesis) and
    buy_parent=5 (zone 5 itself, the only live BUY POI in that window).
    During every other SELL_ONLY gate, the parent is zone 3 throughout
    UNTIL gate 13, where zone 9 (not zone 3) is the actual zone supplying
    the entry, and gate 15, where it's zone 8 -- both distinct, later
    Weekly zones in the same SELL lineage, not zone 3's own original box."""
    rtz = ZoneInfo("Asia/Riyadh")

    def rt(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
        return datetime(y, mo, d, h, mi, tzinfo=rtz)

    return [
        (rt(2026, 4, 14, 17, 55), rt(2026, 5, 6, 13, 45), "SELL_ONLY", "3", ""),
        (rt(2026, 5, 6, 13, 45), rt(2026, 5, 14, 18, 0), "NONE", "", ""),
        (rt(2026, 5, 14, 18, 0), rt(2026, 5, 29, 17, 51), "SELL_ONLY", "3", ""),
        (rt(2026, 5, 29, 17, 51), rt(2026, 6, 5, 16, 51), "NONE", "", ""),
        (rt(2026, 6, 5, 16, 51), rt(2026, 6, 5, 18, 37), "SELL_ONLY", "3", ""),
        (rt(2026, 6, 5, 18, 37), rt(2026, 6, 8, 0, 0), "BOTH", "3", "5"),
        (rt(2026, 6, 8, 0, 0), rt(2026, 6, 15, 0, 29), "SELL_ONLY", "3", ""),
        (rt(2026, 6, 15, 0, 29), rt(2026, 6, 17, 22, 24), "NONE", "", ""),
        (rt(2026, 6, 17, 22, 24), rt(2026, 7, 14, 15, 30), "SELL_ONLY", "3", ""),
        (rt(2026, 7, 14, 15, 30), rt(2026, 7, 23, 15, 43), "NONE", "", ""),
        (rt(2026, 7, 23, 15, 43), rt(2026, 7, 29, 21, 53), "SELL_ONLY", "3", ""),
        (rt(2026, 7, 29, 21, 53), rt(2026, 7, 30, 16, 48), "NONE", "", ""),
        (rt(2026, 7, 30, 16, 48), rt(2026, 8, 3, 0, 0), "SELL_ONLY", "9", ""),
        (rt(2026, 8, 3, 0, 0), rt(2026, 8, 19, 15, 49), "NONE", "", ""),
        (rt(2026, 8, 19, 15, 49), rt(2026, 8, 24, 0, 0), "SELL_ONLY", "8", ""),
        (rt(2026, 8, 24, 0, 0), rt(2026, 9, 11, 22, 5), "NONE", "", ""),
    ]


def manual_control_and_parent_at(gates: List[Tuple[datetime, datetime, str, str, str]],
                                  t: datetime, bullish: bool) -> Optional[Tuple[str, str]]:
    """Looks up (control, parent_id) for time `t` and a candidate direction
    (`bullish`) in the manual gate table. Returns None if `t` falls outside
    every gate (caller should fall back to the normal weekly-ledger lookup)."""
    for start, end, control, sell_parent, buy_parent in gates:
        if start <= t < end:
            if control == "NONE":
                return control, ""
            if control == "BOTH":
                return control, (buy_parent if bullish else sell_parent)
            return control, (buy_parent if bullish else sell_parent)
    return None


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


def pine_epoch(t: datetime) -> str:
    """Bare UTC epoch-millisecond integer literal -- exactly equivalent to
    pine_time(t) as a Pine time VALUE (Pine's own `time`/`time_close` are
    already epoch-ms ints), but one AST node instead of six (one
    timestamp() call + 5 int args). Use this, not pine_time(), for any
    array.from(...) literal or comparison built from many rows -- e.g.
    build_bso_extra_lines' per-attempt time arrays -- so the compiled
    script's node count doesn't scale 6x with row count. Real bug, fixed
    2026-09-24 (RB side, ported here since this shared function hit the
    same CE10205 "statement too long" once RB's 5m BSO table grew past
    ~150 rows -- see reference_rb/docs_rb/RB_RULES_LEARNED.md). Ported
    into this locked-adjacent shared file deliberately: it only changes
    how a time VALUE is spelled in generated Pine text, never which
    events/prices/logic get computed, so it's safe for OB's own use of
    this same function too."""
    return str(int(t.astimezone(UTC).timestamp() * 1000))


def pine_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


_PACK_NA = "\u00a7NA\u00a7"  # printable sentinel (section-sign guards), never collides with real data
_PACK_SEP = "|"  # printable delimiter -- none of our values (dates, prices, labels, ids) ever contain "|"


def pack_array(var_name: str, kind: str, values: list) -> List[str]:
    """The REAL, scale-invariant CE10295 fix (2026-09-24) -- see
    RB_RULES_LEARNED.md's "CE10295, actually fixed this time" entry.

    Array-packing (one array.from(...) statement per FIELD instead of one
    label.new/box.new per ROW) was the original, correct fix for the
    original failure mode -- but array.from(...) STILL costs Pine roughly
    one AST node per ELEMENT, so a field's own compiled cost still scales
    with row count. Switching every time value from timestamp(...) (6
    nodes) to a bare epoch-ms int (1 node) bought real headroom but didn't
    change that scaling -- it only moved the ceiling further out. Once RB's
    known-gates window grew to cover the whole dataset (122 H4 RBs, 152 5m
    BSO rows), the sheer ELEMENT COUNT (not per-element complexity) pushed
    the whole script over CE10295 again, even with epoch ints.

    This is the actual fix: pack the whole column into ONE Pine string
    literal (a string literal costs Pine ONE node no matter how long the
    string is) and decode it at runtime with str.split() inside a single
    `if barstate.isfirst` for-loop. A for-loop's COMPILE-TIME cost is its
    own body's statement count (fixed, ~2 lines), not how many times it
    iterates -- so this is O(1) compile cost regardless of row count,
    scaling to any future dataset size without hitting this ceiling again.

    `values`: raw Python values (int/float/str/bool), None means na.
    `kind`: "int" | "float" | "string" | "bool". Returns the `var array`
    declaration plus the populating if-block, as a self-contained sequence
    of top-level Pine lines (safe to splice anywhere in the top-level
    statement list -- never insert anything between these lines)."""
    if not values:
        return [f"var array<{kind}> {var_name} = array.new<{kind}>()"]

    def fmt(v):
        if v is None:
            return _PACK_NA
        if kind == "bool":
            return "true" if v else "false"
        return str(v)

    packed = _PACK_SEP.join(fmt(v) for v in values)
    esc = packed.replace("\\", "\\\\").replace('"', '\\"')
    conv = {
        "string": "p",
        "int": "int(str.tonumber(p))",
        "float": "str.tonumber(p)",
        "bool": 'p == "true"',
    }[kind]
    return [
        f"var array<{kind}> {var_name} = array.new<{kind}>()",
        "if barstate.isfirst",
        f"    for p in str.split(\"{esc}\", \"{_PACK_SEP}\")",
        f"        array.push({var_name}, p == \"{_PACK_NA}\" ? {kind}(na) : {conv})",
    ]


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
    # Packed into arrays + one small draw loop, same technique as the OB
    # boxes/lines below -- NOT one label.new per event. An earlier version
    # unrolled these one statement per swing/MSS (fine at zone #3's original
    # ~6-week scope, at most a couple dozen events), but a wider window (the
    # --manual-gates render, ~13 weeks) pushed the count well past 80 per
    # kind and blew CE10295 ("main body is too long") -- the exact failure
    # mode this file's own box/line code was already written to avoid.
    # Colors briefly changed to maroon (from the Weekly layer's locked
    # blue high / black low+down-MSS convention) as an unproven hypothesis
    # fix on 2026-09-17, before the real bug below was found. That change
    # had zero effect (proving it wasn't a contrast problem) and is
    # reverted here -- this layer now matches the Weekly layer's convention.
    #
    # REAL BUG, found 2026-09-17 (user-caught -- changing color had zero
    # effect, which is what proved this wasn't a contrast problem): every
    # var array declared here is `var`, so Pine evaluates its array.from(...)
    # exactly ONCE, on the chart's very first historical bar. `lowGap` is
    # `ta.atr(14) * 0.08` -- still `na` at bar 0, since ATR(14) needs 14 bars
    # of history that don't exist yet. Every entry that baked "price -
    # lowGap" directly into the array literal (every swing low and
    # down-MSS) therefore got PERMANENTLY set to `na` the instant that line
    # first ran, and never recalculated on later bars even once lowGap
    # became valid -- label.new() given `na` for its price silently draws
    # nothing. Swing highs and up-MSS never used lowGap, so they're plain
    # literals, unaffected. Same reason h4Right (which depends on
    # impact_x_<id>) is deliberately NOT a `var` array and is instead
    # recomputed fresh inside "if barstate.islast" -- this needed the same
    # treatment. Fixed by storing only the RAW price (a safe literal) in the
    # `var` array, plus a bool flag for which entries need the offset, and
    # applying "- lowGap" at DRAW TIME instead, when lowGap's current value
    # is actually valid.
    struct_x, struct_y, struct_txt, struct_col, struct_low = [], [], [], [], []
    for e in sh:
        struct_x.append(pine_time(h4_bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▲\""); struct_col.append("color.blue"); struct_low.append("false")
    for e in sl:
        struct_x.append(pine_time(h4_bars[e.swing].start)); struct_y.append(f"{e.price:.5f}")
        struct_txt.append("\"▼\""); struct_col.append("color.black"); struct_low.append("true")
    for m in ms:
        # REVERTED 2026-09-17. An earlier change this same session switched
        # this from `m.broken` to `m.at`, believing the X should sit on the
        # breaking candle -- that was wrong. Checked against the ORIGINAL
        # locked code (write_ob_pine in the very first commit, c2bcde7):
        # it uses `engine.w[m.broken].start`, i.e. the swing candle itself
        # (the arrow being exceeded), not the candle that exceeds it. Per
        # the user: the X marks the swing point that got exceeded, not the
        # price/candle that did the exceeding. Restored to `m.broken` to
        # match the original, unmodified engine convention.
        struct_x.append(pine_time(h4_bars[m.broken].start))
        struct_y.append(f"{m.price:.5f}")
        struct_txt.append("\"✕\""); struct_col.append("color.blue" if m.up else "color.black")
        struct_low.append("false" if m.up else "true")

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
        f"var array<int> h4StructX = {arr('int', struct_x)}",
        f"var array<float> h4StructY = {arr('float', struct_y)}",
        f"var array<string> h4StructTxt = {arr('string', struct_txt)}",
        f"var array<color> h4StructCol = {arr('color', struct_col)}",
        f"var array<bool> h4StructLow = {arr('bool', struct_low)}",
        *impact_watchers,
        "if barstate.islast",
        "    if onH4 or onFive",
        f"        array<int> h4Right = {arr('int', right_exprs)}",
        "        for i = 0 to array.size(h4Left) - 1",
        "            hRank = array.size(h4Left) - i",
        "            if not inspectOneH4OB or hRank == h4ObFromLast",
        "                hCol = array.get(h4Bull, i) ? color.blue : color.black",
        "                box.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Right, i), array.get(h4Bottom, i), border_color=hCol, border_width=1, bgcolor=na, xloc=xloc.bar_time)",
        "                label.new(array.get(h4Left, i), array.get(h4Top, i), array.get(h4Label, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_down, color=color.new(hCol,85), textcolor=hCol, size=size.tiny)",
        "                line.new(array.get(h4Right, i), array.get(h4Bottom, i), array.get(h4Right, i), array.get(h4Top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.blue,55), width=1)",
        "    if onH4",
        "        for i = 0 to array.size(h4StructX) - 1",
        "            structYY = array.get(h4StructLow, i) ? array.get(h4StructY, i) - lowGap : array.get(h4StructY, i)",
        "            label.new(array.get(h4StructX, i), structYY, array.get(h4StructTxt, i), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_none, textcolor=array.get(h4StructCol, i), size=size.small)",
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


def build_bso_extra_lines(bso_results: List[tuple], display_tz: ZoneInfo) -> List[str]:
    """5m entry-machine visualization -- 5m chart only (`onFive`), nothing on
    H4/Weekly: this is 5m execution detail, not higher-timeframe structure.

    One row per BSO attempt (`bso_results` is now flattened across each H4
    OB's full re-entry chain, SPEC.md SS27 -- an OB that hit SL and re-armed
    contributes more than one row, labelled "(re-entry N)" in the 4H OB
    column), with its own `Inspect one 5m BSO only` / `5m BSO from last`
    toggle -- same pattern as the H4 OB inspector -- so a single attempt's
    table row and lines can be isolated the same way a single H4 OB already
    can.

    For an attempt that reached ENTERED:
      - a BLUE horizontal line at the entry/candidate price, from the
        winning candidate swing's OWN bar (`candidate_since` -- where that
        exact price level first printed as a 5m swing, whichever candidate
        ultimately won after any replacements) to the moment price broke it
        (the entry minute). Anchoring to the swing's own bar rather than to
        when it merely became "the active one being watched" (an earlier
        version) matters when a resting swing forms only a few minutes
        before entry -- that earlier definition could collapse to a line so
        short it was effectively invisible on the chart.
      - a RED horizontal line at the SL price, from entry to the exact
        minute price reached it, if SL was hit first.
      - a GREEN horizontal line at the TP price, from entry to the exact
        minute price reached it, if TP was hit first.
      - ADDITIONALLY (2026-09-16, user: "it would be amazing if you can
        draw the order mark with the green on the profit side and red on
        the loss side starting from the entry and stopping on whichever
        comes first, win or loss" -- kept alongside the SL/TP lines above,
        not instead of them, per the user's explicit correction) TWO
        filled boxes, always both, both anchored at (entry time, entry
        price), spanning entry to `excursion_end_time` (the exit minute
        when resolved, or the last minute of available data for an OPEN
        trade -- see five_bso_engine.run_bso):
          - a GREEN box from entry_price to tp_price -- the fixed 3R
            reward frame this attempt was risking for.
          - a RED box from entry_price to sl_price -- the fixed 1R risk
            frame.
        Twice corrected 2026-09-16. First (user: "the box should always
        have the two sides ... we want to see the red part ...
        intersecting with the green until the SL") from an earlier
        single-colour version that only showed the winning side
        (entry-to-exit only, colour picked by outcome) and skipped
        OPEN/AMBIGUOUS trades. That version was then changed to use the
        trade's actual MFE/MAE prices as the box edges -- which promptly
        drew boxes that did NOT line up with the SL/TP price lines already
        on the chart (MFE/MAE are usually short of the full SL/TP
        distance) and, on a losing trade, drew a stunted green box that
        stopped wherever price happened to turn back, not at the reward
        target. Second correction (user: "the boxs does not happen to be
        exactly on the entry, tp or sl lines" + "if the price hit SL
        first, the green part should cover the 3rr range for
        consistency"): the box now always uses the SAME sl_price/tp_price
        values as the SL/TP table column and line, so its edges are
        pixel-identical to those references on every attempt, win or
        lose -- what actually happened (MFE/MAE) stays in the table
        column below, not the box.
    An attempt that never reached an entry (H4_OB_BREACHED, NO_RESTING_SWING,
    etc) gets a table row (stage shown in the Result column) but no lines.
    OPEN/AMBIGUOUS results get the blue line but no SL/TP line or box,
    since the outcome isn't resolved (OPEN) or isn't orderable from 1m OHLC
    alone (AMBIGUOUS).

    MFE/MAE (SPEC.md SS34, 2026-09-16) get one combined table column,
    "N.N/N.N" pips (MFE/MAE), matching the SL column's own pips-then-price
    convention.

    The table reports the full lineage per SPEC.md SS17's parent-POI chain:
    Weekly OB (grandparent) -> 4H OB (parent) -> 5m entry (child)."""
    n = len(bso_results)

    ids, weeklys, sides, restings, entries, sls, tps, results, exits, excursions = ([] for _ in range(10))
    blefts, brights, bys = [], [], []
    clefts, crights, cys, ccols = [], [], [], []
    gleft, gright, gtop, gbottom = [], [], [], []
    rleft, rright, rtop, rbottom = [], [], [], []
    for z, _it, parent_id, _invalidation_reason, res in bso_results:
        attempt_no = res.get("attempt")
        ids.append(f"#{z.id}" if attempt_no in (None, 1) else f"#{z.id} (re-entry {attempt_no})")
        weeklys.append('#' + parent_id if parent_id else '-')
        sides.append('BUY' if z.bullish else 'SELL')
        restings.append(wob.display_iso(res.get('resting_at'), display_tz))
        entry_t, entry_p = res.get("entry_time"), res.get("entry_price")
        entry_txt = f"{wob.display_iso(entry_t, display_tz)} @ {entry_p:.5f}" if entry_t is not None and entry_p is not None else "-"
        entries.append(entry_txt)
        sl_v, tp_v, risk_v = res.get("sl_price"), res.get("tp_price"), res.get("risk")
        # SL column shows risk in pips (1 pip = 0.0001 for EURUSD) ahead of
        # the price itself, separated by "/", e.g. "6.5/1.16527".
        sl_txt = f"{risk_v / 0.0001:.1f}/{sl_v:.5f}" if sl_v is not None and risk_v is not None else ("-" if sl_v is None else f"{sl_v:.5f}")
        sls.append(sl_txt)
        tps.append(f"{tp_v:.5f}" if tp_v is not None else "-")
        result_txt = res.get("result") or res.get("stage") or "?"
        results.append(result_txt)
        exit_t, exit_p = res.get("exit_time"), res.get("exit_price")
        exit_txt = f"{wob.display_iso(exit_t, display_tz)} @ {exit_p:.5f}" if exit_t is not None and exit_p is not None else "-"
        exits.append(exit_txt)
        mfe_v, mae_v = res.get("mfe"), res.get("mae")
        excursion_txt = f"{mfe_v / 0.0001:.1f}/{mae_v / 0.0001:.1f}" if mfe_v is not None and mae_v is not None else "-"
        excursions.append(excursion_txt)

        cs, ep = res.get("candidate_since"), res.get("entry_price")
        have_b = cs is not None and entry_t is not None
        blefts.append(pine_epoch(cs) if have_b else None)
        brights.append(pine_epoch(entry_t) if have_b else None)
        bys.append(ep if have_b else None)

        result = res.get("result")
        if result in ("SL", "TP") and entry_t is not None and exit_t is not None and exit_p is not None:
            clefts.append(pine_epoch(entry_t)); crights.append(pine_epoch(exit_t)); cys.append(exit_p)
            ccols.append("R" if result == "SL" else "G")
        else:
            clefts.append(None); crights.append(None); cys.append(None); ccols.append(None)

        end_t = res.get("excursion_end_time")
        if entry_t is not None and end_t is not None and tp_v is not None and sl_v is not None:
            gleft.append(pine_epoch(entry_t)); gright.append(pine_epoch(end_t))
            gtop.append(max(entry_p, tp_v)); gbottom.append(min(entry_p, tp_v))
            rleft.append(pine_epoch(entry_t)); rright.append(pine_epoch(end_t))
            rtop.append(max(entry_p, sl_v)); rbottom.append(min(entry_p, sl_v))
        else:
            gleft.append(None); gright.append(None); gtop.append(None); gbottom.append(None)
            rleft.append(None); rright.append(None); rtop.append(None); rbottom.append(None)

    return [
        "bool inspectOne5mBSO = input.bool(false, \"Inspect one 5m BSO only\", group=\"5m BSO inspection\")",
        f"int bso5FromLast = input.int(1, \"5m BSO from last\", minval=1, maxval={max(1, n)}, group=\"5m BSO inspection\", tooltip=\"1 = most recent 5m BSO attempt, 2 = the one before it, and so on.\")",
        f"var table bso5Ledger = table.new(position.middle_right, 10, {n + 1}, border_width=1)",
        *pack_array("bso5Id", "string", ids),
        *pack_array("bso5Weekly", "string", weeklys),
        *pack_array("bso5Side", "string", sides),
        *pack_array("bso5Resting", "string", restings),
        *pack_array("bso5Entry", "string", entries),
        *pack_array("bso5Sl", "string", sls),
        *pack_array("bso5Tp", "string", tps),
        *pack_array("bso5Result", "string", results),
        *pack_array("bso5Exit", "string", exits),
        *pack_array("bso5Excursion", "string", excursions),
        *pack_array("bso5BLeft", "int", blefts),
        *pack_array("bso5BRight", "int", brights),
        *pack_array("bso5BY", "float", bys),
        *pack_array("bso5CLeft", "int", clefts),
        *pack_array("bso5CRight", "int", crights),
        *pack_array("bso5CY", "float", cys),
        *pack_array("bso5CCol", "string", ccols),
        *pack_array("bso5GLeft", "int", gleft),
        *pack_array("bso5GRight", "int", gright),
        *pack_array("bso5GTop", "float", gtop),
        *pack_array("bso5GBottom", "float", gbottom),
        *pack_array("bso5RLeft", "int", rleft),
        *pack_array("bso5RRight", "int", rright),
        *pack_array("bso5RTop", "float", rtop),
        *pack_array("bso5RBottom", "float", rbottom),
        "if barstate.islast",
        "    if onFive",
        "        table.cell(bso5Ledger, 0, 0, \"Weekly OB\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 1, 0, \"4H OB\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 2, 0, \"Side\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 3, 0, \"Resting (RYD)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 4, 0, \"Entry (RYD / px)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 5, 0, \"SL\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 6, 0, \"TP\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 7, 0, \"Result\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 8, 0, \"Exit (RYD / px)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        table.cell(bso5Ledger, 9, 0, \"MFE/MAE (pips)\", text_color=color.white, bgcolor=color.new(color.purple,15))",
        "        for i = 0 to array.size(bso5Id) - 1",
        "            bRank = array.size(bso5Id) - i",
        "            if not inspectOne5mBSO or bRank == bso5FromLast",
        "                bRow = inspectOne5mBSO ? 1 : i + 1",
        "                table.cell(bso5Ledger, 0, bRow, array.get(bso5Weekly, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 1, bRow, array.get(bso5Id, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 2, bRow, array.get(bso5Side, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 3, bRow, array.get(bso5Resting, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 4, bRow, array.get(bso5Entry, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 5, bRow, array.get(bso5Sl, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 6, bRow, array.get(bso5Tp, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 7, bRow, array.get(bso5Result, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 8, bRow, array.get(bso5Exit, i), text_color=color.black, bgcolor=na)",
        "                table.cell(bso5Ledger, 9, bRow, array.get(bso5Excursion, i), text_color=color.black, bgcolor=na)",
        "                if not na(array.get(bso5BLeft, i))",
        "                    line.new(array.get(bso5BLeft, i), array.get(bso5BY, i), array.get(bso5BRight, i), array.get(bso5BY, i), xloc=xloc.bar_time, extend=extend.none, color=color.blue, width=2)",
        "                if not na(array.get(bso5CLeft, i))",
        "                    line.new(array.get(bso5CLeft, i), array.get(bso5CY, i), array.get(bso5CRight, i), array.get(bso5CY, i), xloc=xloc.bar_time, extend=extend.none, color=array.get(bso5CCol, i) == \"R\" ? color.red : color.green, width=2)",
        "                if not na(array.get(bso5GLeft, i))",
        "                    box.new(array.get(bso5GLeft, i), array.get(bso5GTop, i), array.get(bso5GRight, i), array.get(bso5GBottom, i), border_color=color.green, bgcolor=color.new(color.green, 80), xloc=xloc.bar_time)",
        "                if not na(array.get(bso5RLeft, i))",
        "                    box.new(array.get(bso5RLeft, i), array.get(bso5RTop, i), array.get(bso5RRight, i), array.get(bso5RBottom, i), border_color=color.red, bgcolor=color.new(color.red, 80), xloc=xloc.bar_time)",
    ]


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

    manual_gates = build_manual_gates() if args.manual_gates else None

    rows = []
    drawn = []
    for z in h4_engine.zones:
        et, ep = wob.eligibility_detail(h4_engine, z)
        tt, tp, _ = wob.trigger_display_detail(h4_engine, z)
        it = wob.impact_time(h4_engine, z, et)
        impacted = z.state == 3
        pre_spent_ok = z.pre_spent_state in (0, 1, 4) if impacted else None
        ctrl_parent = manual_control_and_parent_at(manual_gates, it, z.bullish) if (manual_gates and impacted and it is not None) else None
        if ctrl_parent is not None:
            ctrl, parent_id = ctrl_parent
        else:
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
    if args.manual_gates:
        window_start = manual_gates[0][0]
        window_end = manual_gates[-1][1]
        focused_drawn = [d for d in drawn if window_start <= d[5] < window_end]
    elif args.focus_weekly_id:
        focused_drawn = [d for d in drawn if d[6] == str(args.focus_weekly_id)]
        matching_weeks = [idx for idx, pid in parent_by_week.items() if pid == str(args.focus_weekly_id)]
        if matching_weeks:
            window_start = weeks[min(matching_weeks)].start
            window_end = weeks[max(matching_weeks)].end
    h4_extra_lines = build_h4_extra_lines(h4_engine, h4_bars, focused_drawn, args.h4_pine_obs, display_tz,
                                          window_start, window_end, args.h4_pine_labels)

    # 5m BSO layer: run the entry engine on exactly the OBs drawn above (same
    # window, same authorization gate -- "the OBs of this window only").
    mt = [m.t for m in minutes]
    h4_bar_starts = [b.start for b in h4_bars]
    five_bars = bso.aggregate_5m(minutes)
    five_bar_starts = [b.start for b in five_bars]
    five_engine = wob.WeeklyOBEngine(minutes, five_bars, origin_gap_window=None)
    five_engine.run()
    # Re-entry chain per SPEC.md SS27 (made universal, 2026-09-16): after an
    # SL, re-arm and search again as long as the OB's own structural premise
    # (near-boundary close, or the supporting 4H swing breaking -- see
    # bso.structural_invalid_at) hasn't been invalidated. Each H4 OB can now
    # yield more than one attempt.
    bso_results = []
    for z, tt, tp, et, ep, it, parent_id in focused_drawn:
        invalidated_at, invalidation_reason = bso.structural_invalid_at(z, it, h4_bars, h4_bar_starts, h4_engine.events, minutes, mt)
        attempts = bso.run_bso_chain(z, it, five_bar_starts, five_engine.events, minutes, mt, invalidated_at)
        for res in attempts:
            bso_results.append((z, it, parent_id, invalidation_reason, res))
    bso_extra_lines = build_bso_extra_lines(bso_results, display_tz)

    with (base / "five_bso_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=bso.LEDGER_FIELDS)
        wr.writeheader()
        for z, it, parent_id, invalidation_reason, res in bso_results:
            wr.writerow(bso.ledger_row(z, it, parent_id, invalidation_reason, res, display_tz))

    extra_lines = h4_extra_lines + bso_extra_lines

    wob.write_ob_pine(base, weekly_engine, args.pine_labels, args.pine_obs, args.pine_table,
                       args.box_body_minutes, display_tz, args.origin_first_price,
                       args.origin_body_offset_minutes, extra_lines=extra_lines, out_name="full_viewer.pine")
    wob.write_ledger(base, weekly_engine, args.box_body_minutes, display_tz, args.origin_first_price, args.origin_body_offset_minutes)
    wob.write_report(base, minutes, weeks, warnings, weekly_engine, args)

    print("Created:")
    print("  full_viewer.pine   (Weekly layer + 4H layer/table + 5m BSO entry lines)")
    print("  h4_ob_ledger.csv, five_bso_ledger.csv")
    print("  weekly_ob_ledger.csv, weekly_ob_swings.csv, weekly_ob_report.txt")
    focus_note = f", {len(focused_drawn)} shown (--manual-gates)" if args.manual_gates else (
        f", {len(focused_drawn)} shown (--focus-weekly-id {args.focus_weekly_id})" if args.focus_weekly_id else "")
    print(f"{len(h4_bars)} 4H bars, {len(h4_engine.zones)} H4 OBs computed, {len(drawn)} drawn (impacted + authorized){focus_note}.")
    bso_stages = {}
    for _z, _it, _parent_id, _invalidation_reason, res in bso_results:
        bso_stages[res.get("stage")] = bso_stages.get(res.get("stage"), 0) + 1
    print(f"5m BSO on {len(bso_results)} drawn OBs: {bso_stages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
