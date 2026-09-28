#!/usr/bin/env python3
"""ONE Pine file: Daily + 4H + 1H structure, all in the same script.

User asked for "one pine doing all" after getting three separate files
(daily_combined_viewer.pine, h4_combined_viewer.pine, h1_combined_viewer.pine)
-- one script that shows the RIGHT timeframe's own swings/MSS/POIs
depending on which chart you're actually looking at (Daily, 4H or 1H),
instead of three files to juggle.

How it works: runs the SAME WeeklyCombinedEngine three times (once each on
daily/4H/1H bars, via daily_combined_generator's aggregate_days/
aggregate_hours), gets three normal pine outputs from
weekly_combined_generator.write_combined_pine() exactly as before (so the
draw logic itself is byte-identical to the already-verified single-timeframe
files -- nothing about swing/MSS/POI rules is reimplemented here), then
merges them into one file:
  - ONE shared header (inputs, the ledger table, the f_trackImpactX/
    f_drawPoiBox function defs) -- written once.
  - THREE per-timeframe bodies (data arrays + draw calls), each with its own
    array names prefixed (d_/h4_/h1_) so they can't collide, each gated on
    its OWN timeframe check (onD / onH4 / onH1) instead of the single
    onWeekly the standalone files used -- so only the block matching the
    chart you're currently on ever draws.

Writes into the same folder this script sits in (override with --out-dir) --
same fixed names every run, overwritten in place:
  all_tf_combined_viewer.pine   the one script (Daily/4H/1H, self-detecting)
  d_tf_swings.csv / d_tf_report.txt     Daily structure, for audit
  h4_tf_swings.csv / h4_tf_report.txt   4H structure, for audit
  h1_tf_swings.csv / h1_tf_report.txt   1H structure, for audit

Run (flat folder, same convention as every other generator here):

    python all_tf_combined_generator.py EURUSD_m1_BidAndAsk.csv --as-of 2026-01-12 --default-side SELL
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_here = Path(__file__).resolve().parent
for _p in (_here, _here.parent / "reference_combined", _here.parent / "reference",
           _here.parent / "reference_rb", _here.parent / "reference_fvg"):
    sys.path.insert(0, str(_p))
import weekly_ob_generator as wob          # noqa: E402
import weekly_combined_generator as wc     # noqa: E402
import daily_combined_generator as dc      # noqa: E402

UTC = timezone.utc

# (tag, timeframe.period string, title word)
TIMEFRAMES = [
    ("d", "1D", "Daily"),
    ("h4", "240", "4H"),
    ("h1", "60", "1H"),
]

SPLIT_MARKER = "var array<int> structX = array.new<int>()"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv_file", nargs="?", default="EURUSD_m1_BidAndAsk.csv")
    p.add_argument("--input-tz", default="UTC")
    p.add_argument("--price-side", choices=("bid", "ask"), default="bid")
    p.add_argument("--day-close-zone", default="America/New_York")
    p.add_argument("--day-close-hour", type=int, default=17, choices=range(24))
    p.add_argument("--display-tz", default="Asia/Riyadh")
    p.add_argument("--pine-labels", type=int, default=160, choices=range(1, 161))
    p.add_argument("--pine-obs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-rbs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-fvgs", type=int, default=200, choices=range(1, 451))
    p.add_argument("--pine-table", type=int, default=20, choices=range(1, 21))
    p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help="Truncate the input data to end of this day (in --display-tz wall "
                         "time), same truncation applied to all three timeframes.")
    p.add_argument("--default-side", choices=("ALL", "BUY", "SELL"), default="ALL")
    p.add_argument("--out-dir", default=None,
                    help="Where to write the outputs. Default: the same folder this script "
                         "sits in (not the CSV's folder) -- keeps a data folder that mixes "
                         "raw CSVs and scripts from also collecting generated files.")
    p.add_argument("--show-date", default=None, metavar="YYYY-MM-DD",
                    help="Only draw swings/MSS/POIs active inside the real trading window "
                         "that day -- 10:00-20:00 Riyadh in summer, 11:00-21:00 in winter "
                         "(London open through New York close; DST-detected automatically, "
                         "not hardcoded months) -- plus the single most recent swing high, "
                         "swing low and MSS confirmed before the window opened (the carried-in "
                         "context in-window POIs are measured against). Nothing after the "
                         "window closes shows, structure or POI alike. Different from --as-of: "
                         "--as-of controls what data the engine sees (so structure isn't "
                         "computed from the future); --show-date controls what gets drawn from "
                         "the already-computed structure. Use both together for 'only this "
                         "trading window, as it would have looked standing in it.'")
    return p.parse_args()


def trading_window(date_str: str, display_tz: ZoneInfo) -> tuple[datetime, datetime]:
    """User's real trading window (2026-09-28): 10:00-20:00 Riyadh in
    summer, 11:00-21:00 in winter -- London open through New York close,
    Asia excluded (Asia is liquidity-grab-only, never an entry window,
    per the earlier session rules). Summer/winter is detected from
    whether New York is actually in DST that day (via zoneinfo's real,
    year-accurate transition data), not a hardcoded month range -- the
    whole reason these hours shift on the Riyadh clock in the first
    place is NY/London's own DST, so that's the correct thing to check,
    not a guess at "November to March.\""""
    y, m, d = (int(x) for x in date_str.split("-"))
    ny_noon = datetime(y, m, d, 12, tzinfo=ZoneInfo("America/New_York"))
    is_summer = ny_noon.dst() != timedelta(0)
    start_h, end_h = (10, 20) if is_summer else (11, 21)
    start = datetime(y, m, d, start_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    end = datetime(y, m, d, end_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    return start, end


def filter_to_date(engine, date_str: str, display_tz: ZoneInfo) -> None:
    """Keep only what's actually active inside the user's real trading
    window that day (10:00-20:00 / 11:00-21:00 Riyadh, see
    trading_window()) -- NOT the whole calendar day. Different from
    --as-of, which keeps everything ACCUMULATED up to that day (so a
    swing from three months earlier still shows). This mutates the
    engine's own zone/event lists in place, before write_combined_pine
    ever sees them, so it needs no changes to the shared draw code.

    A POI counts as "in the window" if ANY of its real lifecycle events
    landed inside it -- created, triggered, made eligible, impacted, or
    breached/stopped (STRAND/STRUCTURAL_BREACH, via its stop candle).

    A swing/MSS counts as "in the window" if its confirmation falls
    inside it, OR it's the single most recent swing high, most recent
    swing low, or most recent MSS confirmed BEFORE the window started --
    the carried-in context every in-window POI's protected level and
    current trend are actually measured against. Nothing after the
    window closes shows at all, structure or POI alike -- per the user's
    explicit "I do not want to see any info ... after the trading ends.\""""
    win_start, win_end = trading_window(date_str, display_tz)

    events_in = [e for e in engine.events if win_start <= engine.w[e.confirm].start < win_end]
    prior_highs = [e for e in engine.events if e.kind == 0 and engine.w[e.confirm].start < win_start]
    prior_lows = [e for e in engine.events if e.kind == 1 and engine.w[e.confirm].start < win_start]
    carry_in = ([max(prior_highs, key=lambda e: engine.w[e.confirm].start)] if prior_highs else []) + \
               ([max(prior_lows, key=lambda e: engine.w[e.confirm].start)] if prior_lows else [])
    engine.events = sorted(events_in + carry_in, key=lambda e: engine.w[e.confirm].start)

    mss_in = [x for x in engine.msses if win_start <= engine.w[x.at].start < win_end]
    prior_mss = [x for x in engine.msses if engine.w[x.at].start < win_start]
    mss_carry_in = [max(prior_mss, key=lambda x: engine.w[x.at].start)] if prior_mss else []
    engine.msses = sorted(mss_in + mss_carry_in, key=lambda x: engine.w[x.at].start)

    def in_window(t):
        return t is not None and win_start <= t < win_end

    def happened_in_window(origin, z):
        stop_t = engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else None
        return any(in_window(t) for t in (
            origin, getattr(z, "trigger_time", None), getattr(z, "eligible_time", None),
            z.impact_time, stop_t,
        ))

    engine.ob_zones = [z for z in engine.ob_zones if happened_in_window(engine.w[z.candle].start, z)]
    engine.rb_zones = [z for z in engine.rb_zones if happened_in_window(engine.w[z.candle].start, z)]
    engine.fvg_zones = [z for z in engine.fvg_zones if happened_in_window(engine.w[z.left].start, z)]


def compute_5m_trades(h4_engine, h1_engine, minutes, window_end, display_tz) -> list[dict]:
    """The real entry rule, as given (2026-09-28, this session):
      1. A 4H or 1H POI impacts, in premium (sell) or discount (buy) --
         premium/discount = the 50/50 split between the zone's own
         protect_level (the protecting swing) and the most recent
         opposing-kind swing confirmed before impact (the swing price
         came from, on its way up/down to react on the POI).
      2. Entry = the first confirmed 5m swing low (sell) / high (buy)
         after that impact -- a stop order at that level.
      3. SL = the last confirmed 5m swing high (sell) / low (buy)
         between the impact and the entry trigger.
      4. TP = 3R.
    Two POIs producing the identical 5m entry (same price, same trigger
    minute) collapse into ONE trade -- same single-opportunity rule
    already used elsewhere in this project (one real move, not one
    trade per POI that happened to touch it)."""
    mt = [m.t for m in minutes]
    hi = [m.h for m in minutes]
    lo = [m.l for m in minutes]

    bars5 = dc.aggregate_minutes(minutes, 5)
    e5 = wc.WeeklyCombinedEngine(minutes, bars5)
    e5.run()

    candidates = []
    for eng in (h4_engine, h1_engine):
        for zones, left_of in ((eng.ob_zones, lambda z: eng.w[z.candle].start),
                                (eng.rb_zones, lambda z: eng.w[z.candle].start),
                                (eng.fvg_zones, lambda z: eng.w[z.left].start)):
            for z in zones:
                if z.impact_time is None or z.protect_level is None:
                    continue
                candidates.append((eng, z))

    trades = []
    for eng, z in candidates:
        sell = not z.bullish
        opp_kind = 1 if sell else 0  # opposing swing: a LOW for a sell reaction, a HIGH for a buy reaction
        opp_events = [e for e in eng.events if e.kind == opp_kind and eng.w[e.confirm].start <= z.impact_time]
        if not opp_events:
            continue
        opp = max(opp_events, key=lambda e: eng.w[e.confirm].start)
        opp_t = eng.w[opp.confirm].start
        mid = (z.protect_level + opp.price) / 2

        i0, i1 = bisect_left(mt, opp_t), bisect_left(mt, z.impact_time)
        if i1 < i0:
            continue
        if sell:
            reached = max(hi[i0:i1 + 1]) >= mid
        else:
            reached = min(lo[i0:i1 + 1]) <= mid
        if not reached:
            continue

        entry_kind = 1 if sell else 0  # entry swing: a LOW for a sell stop, a HIGH for a buy stop
        after = [e for e in e5.events if e.kind == entry_kind and e5.w[e.confirm].start > z.impact_time]
        if not after:
            continue
        entry_swing = min(after, key=lambda e: e5.w[e.confirm].start)
        entry_price = entry_swing.price
        confirm_t = e5.w[entry_swing.confirm].start

        j0, j1 = bisect_left(mt, confirm_t), bisect_left(mt, window_end)
        entry_t = None
        for k in range(j0, j1):
            if (lo[k] < entry_price) if sell else (hi[k] > entry_price):
                entry_t = mt[k]
                break
        if entry_t is None:
            continue  # setup, never triggered before the window closed

        sl_kind = 0 if sell else 1  # SL swing: the last HIGH before a sell entry, last LOW before a buy entry
        sl_events = [e for e in e5.events if e.kind == sl_kind and z.impact_time < e5.w[e.confirm].start <= entry_t]
        if not sl_events:
            continue
        sl_swing = max(sl_events, key=lambda e: e5.w[e.confirm].start)
        sl_price = sl_swing.price
        r = (sl_price - entry_price) if sell else (entry_price - sl_price)
        tp_price = entry_price - 3 * r if sell else entry_price + 3 * r

        ptype = "OB" if z in eng.ob_zones else ("RB" if z in eng.rb_zones else "FVG")
        trades.append(dict(
            side="SELL" if sell else "BUY", entry_time=entry_t, entry_price=entry_price,
            sl=sl_price, tp=tp_price, r_pips=abs(r) * 10000,
            impact_time=z.impact_time, poi_label=f"{ptype}#{z.id}",
        ))

    # Dedup: identical entry (same price, same trigger minute) -> one trade
    merged: dict[tuple, dict] = {}
    for t in trades:
        key = (t["entry_time"], round(t["entry_price"], 5))
        if key not in merged:
            merged[key] = dict(t, poi_sources=[t["poi_label"]])
        else:
            merged[key]["poi_sources"].append(t["poi_label"])
            merged[key]["impact_time"] = min(merged[key]["impact_time"], t["impact_time"])
    return sorted(merged.values(), key=lambda t: t["entry_time"])


def exclude_old_intraday_zones(engine) -> None:
    """User's absolute rule (2026-09-28): "old POIs are never shown or
    used in hourly and minute timeframes. period." OOB/ORB/OFVG (the
    "old" state -- stranded, untouched opposing POI from before the
    current trend) is a real, tradeable category at Daily/Weekly per
    SPEC.md SS12-15, but not here: this drops it entirely for H4/H1,
    independent of --show-date, unconditional."""
    engine.ob_zones = [z for z in engine.ob_zones if wc.ob_status(z) != "OOB"]
    engine.rb_zones = [z for z in engine.rb_zones if wc.rb_status(z) != "ORB"]
    engine.fvg_zones = [z for z in engine.fvg_zones if wc.fvg_status(z) != "OFVG"]


def build_trades_pine(trades: list[dict], display_tz: ZoneInfo) -> list[str]:
    """5m entry/SL/TP visualization: an entry label (the order itself), an
    SL label+box (red, risk) and a TP label+box (green, reward) per trade,
    plus a table -- all gated on the 5m chart specifically and behind a
    single "Show 5m trades" toggle. Uses the same array-pack-once,
    draw-in-one-loop discipline as everything else here (CE10295)."""
    lines = [
        'bool showTrades = input.bool(true, "Show 5m trades", group="Trades")',
        'bool on5 = timeframe.period == "5"',
    ]
    if not trades:
        lines.append('// no qualifying trades for this --show-date window')
        return lines

    side, entry_x, entry_y, sl, tp, r_pips, poi, impact_x, entry_disp = [], [], [], [], [], [], [], [], []
    for t in trades:
        side.append(t["side"])
        entry_x.append(wc.wrb.pine_epoch(t["entry_time"]))
        entry_y.append(round(t["entry_price"], 5))
        sl.append(round(t["sl"], 5))
        tp.append(round(t["tp"], 5))
        r_pips.append(round(t["r_pips"], 1))
        poi.append("+".join(t["poi_sources"]))
        impact_x.append(wc.wrb.pine_epoch(t["impact_time"]))
        entry_disp.append(t["entry_time"].astimezone(display_tz).strftime("%Y-%m-%d %H:%M"))

    lines += [
        *wc.wrb.pack_array("trSide", "string", side),
        *wc.wrb.pack_array("trEntryX", "int", entry_x),
        *wc.wrb.pack_array("trEntryY", "float", entry_y),
        *wc.wrb.pack_array("trSL", "float", sl),
        *wc.wrb.pack_array("trTP", "float", tp),
        *wc.wrb.pack_array("trRPips", "float", r_pips),
        *wc.wrb.pack_array("trPoi", "string", poi),
        *wc.wrb.pack_array("trImpactX", "int", impact_x),
        *wc.wrb.pack_array("trEntryDisp", "string", entry_disp),
        f'var table trTable = table.new(position.bottom_right, 7, {len(trades) + 1}, border_width=1)',
        'if barstate.islast and on5 and showTrades and array.size(trSide) > 0',
        '    boxRightOffset = 2 * 60 * 60 * 1000',
        '    headers2 = array.from("Side", "Entry (RYD)", "Entry", "SL", "TP", "R (pips)", "POI")',
        '    for c = 0 to array.size(headers2) - 1',
        '        table.cell(trTable, c, 0, array.get(headers2, c), text_color=color.white, bgcolor=color.new(color.purple, 15))',
        '    for i = 0 to array.size(trSide) - 1',
        '        isSell = array.get(trSide, i) == "SELL"',
        '        eX = array.get(trEntryX, i)',
        '        eY = array.get(trEntryY, i)',
        '        slY = array.get(trSL, i)',
        '        tpY = array.get(trTP, i)',
        '        box.new(eX, math.max(slY, eY), eX + boxRightOffset, math.min(slY, eY), border_color=color.red, border_width=1, bgcolor=color.new(color.red, 85))',
        '        box.new(eX, math.max(eY, tpY), eX + boxRightOffset, math.min(eY, tpY), border_color=color.green, border_width=1, bgcolor=color.new(color.green, 85))',
        '        label.new(eX, eY, (isSell ? "SELL STOP @ " : "BUY STOP @ ") + str.tostring(eY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=isSell ? label.style_label_up : label.style_label_down, color=color.blue, textcolor=color.white, size=size.small)',
        '        label.new(eX, slY, "SL " + str.tostring(slY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_left, color=color.red, textcolor=color.white, size=size.small)',
        '        label.new(eX, tpY, "TP " + str.tostring(tpY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_left, color=color.green, textcolor=color.white, size=size.small)',
        '        table.cell(trTable, 0, i + 1, array.get(trSide, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 1, i + 1, array.get(trEntryDisp, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 2, i + 1, str.tostring(eY, format.mintick), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 3, i + 1, str.tostring(slY, format.mintick), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 4, i + 1, str.tostring(tpY, format.mintick), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 5, i + 1, str.tostring(array.get(trRPips, i), "#.#"), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 6, i + 1, array.get(trPoi, i), text_color=color.black, bgcolor=na)',
    ]
    return lines


def build_one(base: Path, engine, args, display_tz, tag: str) -> list[str]:
    """Run write_combined_pine into a scratch temp file and return its lines."""
    tmp_name = f"_scratch_{tag}.pine"
    wc.write_combined_pine(base, engine, args.pine_labels, args.pine_obs, args.pine_rbs,
                            args.pine_fvgs, args.pine_table, display_tz, out_name=tmp_name)
    tmp_path = base / tmp_name
    lines = tmp_path.read_text(encoding="utf-8").split("\n")
    tmp_path.unlink()
    return lines


def extract_maxval(header_lines: list[str]) -> int:
    for ln in header_lines:
        m = re.search(r'maxval=(\d+)', ln)
        if m and "poiFromLast" in ln:
            return int(m.group(1))
    return 1


_SHARED_INPUT_NAMES = ["focusPoi", "inspectOnePoi", "countFromStart", "sideFilter", "poiFromLast"]


def rename_arrays(body_lines: list[str], prefix: str) -> list[str]:
    names = sorted(set(re.findall(r'var array<\w+> (\w+)', "\n".join(body_lines))),
                    key=len, reverse=True)
    names += _SHARED_INPUT_NAMES  # each timeframe gets its OWN copy of these 5 inputs, not one shared set
    text = "\n".join(body_lines)
    for name in sorted(set(names), key=len, reverse=True):
        text = re.sub(rf'\b{re.escape(name)}\b', f"{prefix}_{name}", text)
    return text.split("\n")


def build_own_inputs(base_input_lines: list[str], tag: str, title: str, maxval: int, default_side: str) -> list[str]:
    """Each timeframe's own copy of the 5 Combined-settings inputs (Focus
    POI / Inspect one POI only / Count from start / Side / POI from
    last) -- separately grouped and separately remembered, instead of
    one shared set that changing on the 1H chart silently also changes
    for Daily/4H. Same identifier-rename technique as rename_arrays,
    plus its own maxval (that timeframe's own zone count, not the
    merged max) and its own settings-group label."""
    out = []
    for ln in base_input_lines:
        for name in sorted(_SHARED_INPUT_NAMES, key=len, reverse=True):
            ln = re.sub(rf'\b{re.escape(name)}\b', f"{tag}_{name}", ln)
        ln = ln.replace('group="Combined settings"', f'group="{title} settings"')
        ln = re.sub(r'(maxval=)\d+', rf'\g<1>{maxval}', ln)
        if default_side != "ALL":
            ln = ln.replace('input.string("ALL", "Side"', f'input.string("{default_side}", "Side"')
        out.append(ln)
    return out


def inject_input_params(body_lines: list[str], tag: str) -> list[str]:
    """f_drawPoiBox is a shared function (defined ONCE in the header,
    reused by weekly/daily's own standalone viewers too -- left
    untouched there) that used to read sideFilter/inspectOnePoi/
    focusPoi/poiFromLast as free global variables. Now that each
    timeframe has its OWN copy of those 4 (see build_own_inputs), the
    shared function can't close over a single global any more -- they
    have to be passed in as real parameters at each call site instead.
    Only touches lines that literally start with 'f_drawPoiBox(' (the 3
    calls per timeframe body); the function DEFINITION itself is
    patched once, separately, in main()."""
    extra = f"{tag}_sideFilter, {tag}_inspectOnePoi, {tag}_focusPoi, {tag}_poiFromLast, {tag}_countFromStart"
    out = []
    for ln in body_lines:
        if ln.strip().startswith("f_drawPoiBox("):
            assert ln.rstrip().endswith(")")
            ln = ln.rstrip()[:-1] + f", {extra})"
        out.append(ln)
    return out


def regate(body_lines: list[str], on_name: str) -> list[str]:
    out = []
    for ln in body_lines:
        ln = ln.replace('if onWeekly or onH4 or onFive', f'if {on_name}')
        ln = ln.replace('if onWeekly and array.size', f'if {on_name} and array.size')
        ln = re.sub(r'^(\s*)if onWeekly$', rf'\1if {on_name}', ln)
        out.append(ln)
    return out


_PACK_DECL_RE = re.compile(r'^(\s*)var array<(\w+)> (\w+) = array\.new<\2>\(\)$')
_PACK_LOOP_RE = re.compile(r'^\s*for p in str\.split\("(.*)", "\|"\)$')
_PACK_PUSH_RE = re.compile(r'^\s*array\.push\((\w+), p == "\xa7NA\xa7" \? \w+\(na\) : .*\)$')


def collapse_pack_blocks(body_lines: list[str]) -> list[str]:
    """Merging 3 timeframes into one file triples every pack_array() block
    -- CE10295 ("main body too long") is about duplicated STRUCTURE, not
    data volume (same lesson as the earlier weekly_combined_generator.py
    fix, see docs_combined/COMBINED_RULES_LEARNED.md): each packed array
    still carries its own inline `if barstate.isfirst / for p in
    str.split(...) / array.push(...)` loop, and x3 timeframes x ~30 arrays
    each is enough top-level loops to blow the compiled main body even
    though the DATA itself packs into one string literal per array. Same
    remedy as f_trackImpactX/f_drawPoiBox: replace each block's own
    inline loop with a call to ONE shared per-kind function, defined once
    in the header."""
    out = []
    i = 0
    while i < len(body_lines):
        m_decl = _PACK_DECL_RE.match(body_lines[i])
        if (m_decl and i + 3 < len(body_lines)
                and body_lines[i + 1].strip() == "if barstate.isfirst"
                and _PACK_LOOP_RE.match(body_lines[i + 2])
                and _PACK_PUSH_RE.match(body_lines[i + 3])):
            indent, kind, name = m_decl.group(1), m_decl.group(2), m_decl.group(3)
            packed = _PACK_LOOP_RE.match(body_lines[i + 2]).group(1)
            fn = {"int": "f_pushInt", "float": "f_pushFloat",
                  "bool": "f_pushBool", "string": "f_pushString"}[kind]
            out.append(body_lines[i])
            out.append(f'{indent}if barstate.isfirst')
            out.append(f'{indent}    {fn}({name}, "{packed}")')
            i += 4
        else:
            out.append(body_lines[i])
            i += 1
    return out


def main() -> int:
    args = parse_args()
    path = Path(args.csv_file).expanduser().resolve()
    base = Path(args.out_dir).expanduser().resolve() if args.out_dir else Path(__file__).resolve().parent
    if not path.exists():
        print("CSV not found:", path, file=sys.stderr)
        return 2
    try:
        input_tz = ZoneInfo(args.input_tz)
        close_tz = ZoneInfo(args.day_close_zone)
        display_tz = ZoneInfo(args.display_tz)

        minutes, warnings = wob.load_minutes(path, input_tz, args.price_side)
        if args.as_of:
            y, m, d = (int(x) for x in args.as_of.split("-"))
            cutoff_local = datetime(y, m, d, 23, 59, 59, tzinfo=display_tz) + timedelta(seconds=1)
            cutoff_utc = cutoff_local.astimezone(UTC)
            minutes = [x for x in minutes if x.t < cutoff_utc]
            if not minutes:
                print(f"No data at or before {args.as_of}", file=sys.stderr)
                return 2

        bars_by_tag = {
            "d": dc.aggregate_days(minutes, close_tz, args.day_close_hour),
            "h4": dc.aggregate_hours(minutes, 4),
            "h1": dc.aggregate_hours(minutes, 1),
        }

        engines = {}
        raw_lines = {}
        for tag, tf_period, title in TIMEFRAMES:
            engine = wc.WeeklyCombinedEngine(minutes, bars_by_tag[tag])
            engine.run()
            if tag in ("h4", "h1"):
                exclude_old_intraday_zones(engine)
            if args.show_date:
                filter_to_date(engine, args.show_date, display_tz)
            engines[tag] = engine
            raw_lines[tag] = build_one(base, engine, args, display_tz, tag)

        trades = []
        if args.show_date:
            _, window_end = trading_window(args.show_date, display_tz)
            trades = compute_5m_trades(engines["h4"], engines["h1"], minutes, window_end, display_tz)

        # Header: identical across all three except title/onWeekly/maxval --
        # take it from "d", split at the first body-only line.
        d_lines = raw_lines["d"]
        split_idx = next(i for i, ln in enumerate(d_lines) if ln.strip() == SPLIT_MARKER)
        header = d_lines[:split_idx]

        header = [ln.replace(
            'indicator("FXCM Weekly OB+RB+FVG Combined - Python Reference"',
            'indicator("Dhagax Dailies -- Daily+4H+1H OB+RB+FVG Combined"',
        ) for ln in header]

        # Pull the 5 Combined-settings inputs OUT of the shared header --
        # each timeframe gets its own copy (see build_own_inputs), not one
        # set shared across Daily/4H/1H (user caught this: toggling Side on
        # the 1H chart was silently also changing what Daily/4H would show).
        input_line_prefixes = ('string focusPoi', 'bool inspectOnePoi', 'bool countFromStart',
                                'string sideFilter', 'int poiFromLast')
        shared_input_lines = [ln for ln in header if ln.strip().startswith(input_line_prefixes)]
        header = [ln for ln in header if not ln.strip().startswith(input_line_prefixes)]

        # Replace the 4 single-purpose timeframe bools with the 3 real ones
        # this file actually uses (onD/onH4/onH1) -- drop onFive/on1m, they
        # were leftover from a different, unused 5m/1m concept.
        new_header = []
        for ln in header:
            if ln.strip().startswith('bool onWeekly = timeframe.period =='):
                new_header.append('bool onD = timeframe.period == "1D"')
                new_header.append('bool onH4 = timeframe.period == "240"')
                new_header.append('bool onH1 = timeframe.period == "60"')
            elif ln.strip().startswith('bool onH4 = timeframe.period ==') or \
                 ln.strip().startswith('bool onFive = timeframe.period ==') or \
                 ln.strip().startswith('bool on1m = timeframe.period =='):
                continue
            else:
                new_header.append(ln)
        header = new_header

        bodies = []
        for tag, tf_period, title in TIMEFRAMES:
            own_maxval = extract_maxval(raw_lines[tag][:split_idx])
            own_inputs = build_own_inputs(shared_input_lines, tag, title, own_maxval, args.default_side)
            body = own_inputs + raw_lines[tag][split_idx:]
            body = rename_arrays(body, tag)
            body = inject_input_params(body, tag)
            on_name = {"d": "onD", "h4": "onH4", "h1": "onH1"}[tag]
            body = regate(body, on_name)
            body = collapse_pack_blocks(body)
            bodies.append(body)

        # Patch the shared f_drawPoiBox definition to take the 4 inputs as
        # real parameters instead of closing over a single global set (see
        # inject_input_params -- every call site already passes them now).
        header = [
            ln.replace(
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, dashed, filled) =>',
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, dashed, filled, sideFilterP, inspectOnePoiP, focusPoiP, poiFromLastP, countFromStartP) =>',
            ).replace(
                'effRank = countFromStart ? total - array.get(rank, i) + 1 : array.get(rank, i)',
                'effRank = countFromStartP ? total - array.get(rank, i) + 1 : array.get(rank, i)',
            ).replace(
                'effGRank = countFromStart ? gTotal - array.get(grank, i) + 1 : array.get(grank, i)',
                'effGRank = countFromStartP ? gTotal - array.get(grank, i) + 1 : array.get(grank, i)',
            ).replace(
                'sideOk = sideFilter == "ALL" or (sideFilter == "BUY" and array.get(bull, i)) or (sideFilter == "SELL" and not array.get(bull, i))',
                'sideOk = sideFilterP == "ALL" or (sideFilterP == "BUY" and array.get(bull, i)) or (sideFilterP == "SELL" and not array.get(bull, i))',
            ).replace(
                'if sideOk and (not inspectOnePoi or (focusPoi == "ALL" ? effGRank == poiFromLast : effRank == poiFromLast))',
                'if sideOk and (not inspectOnePoiP or (focusPoiP == "ALL" ? effGRank == poiFromLastP : effRank == poiFromLastP))',
            )
            for ln in header
        ]

        # Shared unpack functions (CE10295 fix -- see collapse_pack_blocks):
        # one definition each, called by every collapsed pack_array() block
        # across all three timeframes instead of each carrying its own loop.
        push_fns = [
            'f_pushInt(arr, s) =>',
            '    for p in str.split(s, "|")',
            '        array.push(arr, p == "\xa7NA\xa7" ? int(na) : int(str.tonumber(p)))',
            'f_pushFloat(arr, s) =>',
            '    for p in str.split(s, "|")',
            '        array.push(arr, p == "\xa7NA\xa7" ? float(na) : str.tonumber(p))',
            'f_pushBool(arr, s) =>',
            '    for p in str.split(s, "|")',
            '        array.push(arr, p == "\xa7NA\xa7" ? bool(na) : p == "true")',
            'f_pushString(arr, s) =>',
            '    for p in str.split(s, "|")',
            '        array.push(arr, p == "\xa7NA\xa7" ? string(na) : p)',
        ]
        header = header + push_fns

        out_name = "all_tf_combined_viewer.pine"
        final_lines = header
        for body in bodies:
            final_lines += body
        final_lines += collapse_pack_blocks(build_trades_pine(trades, display_tz))
        (base / out_name).write_text("\n".join(final_lines), encoding="utf-8")

        print("Created:")
        print(f"  {out_name}   <-- one script, draws the right timeframe's own "
              "structure depending on which chart (Daily/4H/1H) you have open")
        bar_word = {"d": "days", "h4": "4h_bars", "h1": "1h_bars"}
        for tag, tf_period, title in TIMEFRAMES:
            e = engines[tag]
            swings_name = f"{tag}_tf_swings.csv"
            report_name = f"{tag}_tf_report.txt"
            dc.write_swings_csv(base, e, display_tz, swings_name)
            dc.write_report(base, minutes, bars_by_tag[tag], e, display_tz, report_name,
                             label=title, bar_word=bar_word[tag])
            print(f"  {swings_name} / {report_name}   ({title}: OB={len(e.ob_zones)} "
                  f"RB={len(e.rb_zones)} FVG={len(e.fvg_zones)})")
        if warnings:
            print(f"({len(warnings)} data warnings -- see load_minutes output)")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
