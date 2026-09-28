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
                    help="Only draw swings/MSS/POIs actually active ON this one day, not "
                         "everything accumulated up to it. Different from --as-of: --as-of "
                         "controls what data the engine sees (so structure isn't computed "
                         "from the future); --show-date controls what gets drawn from the "
                         "already-computed structure. Use both together for 'only this day, "
                         "as it would have looked standing on that day.'")
    return p.parse_args()


def filter_to_date(engine, date_str: str, display_tz: ZoneInfo) -> None:
    """Keep only what's actually active ON that one day -- different from
    --as-of, which keeps everything ACCUMULATED up to that day (so a
    swing from three months earlier still shows). This mutates the
    engine's own zone/event lists in place, before write_combined_pine
    ever sees them, so it needs no changes to the shared draw code.

    A swing/MSS counts as "on" the day if its confirmation falls inside
    it. A POI counts as active if its box would visually overlap the
    day: origin on or before day-end, AND (still open/never stopped, OR
    its death -- impact time if impacted, else its stop candle's start
    -- falls on or after day-start)."""
    y, m, d = (int(x) for x in date_str.split("-"))
    day_start = datetime(y, m, d, 0, 0, 0, tzinfo=display_tz).astimezone(UTC)
    day_end = day_start + timedelta(days=1)

    engine.events = [e for e in engine.events if day_start <= engine.w[e.confirm].start < day_end]
    engine.msses = [x for x in engine.msses if day_start <= engine.w[x.at].start < day_end]

    def overlaps(origin, death):
        if origin >= day_end:
            return False
        if death is not None and death < day_start:
            return False
        return True

    def death_of(z):
        if z.impact_time is not None:
            return z.impact_time
        if 0 <= z.stop < len(engine.w):
            return engine.w[z.stop].start
        return None  # still open -- always overlaps any day up to "now"

    engine.ob_zones = [z for z in engine.ob_zones if overlaps(engine.w[z.candle].start, death_of(z))]
    engine.rb_zones = [z for z in engine.rb_zones if overlaps(engine.w[z.candle].start, death_of(z))]
    engine.fvg_zones = [z for z in engine.fvg_zones if overlaps(engine.w[z.left].start, death_of(z))]


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


def rename_arrays(body_lines: list[str], prefix: str) -> list[str]:
    names = sorted(set(re.findall(r'var array<\w+> (\w+)', "\n".join(body_lines))),
                    key=len, reverse=True)
    text = "\n".join(body_lines)
    for name in names:
        text = re.sub(rf'\b{re.escape(name)}\b', f"{prefix}_{name}", text)
    return text.split("\n")


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
            if args.show_date:
                filter_to_date(engine, args.show_date, display_tz)
            engines[tag] = engine
            raw_lines[tag] = build_one(base, engine, args, display_tz, tag)

        # Header: identical across all three except title/onWeekly/maxval --
        # take it from "d", split at the first body-only line.
        d_lines = raw_lines["d"]
        split_idx = next(i for i, ln in enumerate(d_lines) if ln.strip() == SPLIT_MARKER)
        header = d_lines[:split_idx]

        header = [ln.replace(
            'indicator("FXCM Weekly OB+RB+FVG Combined - Python Reference"',
            'indicator("Dhagax Dailies -- Daily+4H+1H OB+RB+FVG Combined"',
        ) for ln in header]

        max_maxval = max(extract_maxval(raw_lines[tag][:split_idx]) for tag, _, _ in TIMEFRAMES)
        header = [re.sub(r'(int poiFromLast = input\.int\(1, "POI from last", minval=1, maxval=)\d+',
                          rf'\g<1>{max_maxval}', ln) for ln in header]

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

        if args.default_side != "ALL":
            header = [ln.replace(
                'string sideFilter = input.string("ALL", "Side"',
                f'string sideFilter = input.string("{args.default_side}", "Side"',
            ) for ln in header]

        bodies = []
        for tag, tf_period, title in TIMEFRAMES:
            body = raw_lines[tag][split_idx:]
            body = rename_arrays(body, tag)
            on_name = {"d": "onD", "h4": "onH4", "h1": "onH1"}[tag]
            body = regate(body, on_name)
            body = collapse_pack_blocks(body)
            bodies.append(body)

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
