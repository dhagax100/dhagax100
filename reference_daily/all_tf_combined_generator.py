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

Run (flat folder, same convention as every other generator here). ONE
command, forever -- no --show-date/--since to bump by hand each day:

    python all_tf_combined_generator.py EURUSD_m1_BidAndAsk.csv --default-side SELL

"Today" can't be guessed from the CSV itself -- it carries months of
data past any real campaign, so guessing from its last date risks
pulling in far more than intended. Instead it's read from TODAY.txt, a
one-line marker file next to the outputs -- edit THAT single file to
today's date each day, run this exact same command. --since is pinned
once (to a second marker, dailies_since.txt) the first time it's given
-- explicitly or defaulted -- and reused automatically after that. Pass
--show-date/--since yourself only to override either one.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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
                         "trading window, as it would have looked standing in it.' Trades "
                         "before this day are still real candidates (see --since) even when "
                         "this alone is given -- --show-date is always the LAST day shown. "
                         "Omit this entirely for normal day-to-day use: it then reads "
                         "TODAY.txt (a one-line marker file next to the outputs) as "
                         "today's date -- edit that single file each day instead of this "
                         "flag, same command every run. Pass this flag yourself only to "
                         "replay one specific past day on its own.")
    p.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="Widen --show-date into a continuous range: draw every swing, MSS "
                         "and POI, and compute every 5m trade, from --since's own trading day "
                         "through --show-date's, all in the SAME one chart/ledger -- not one "
                         "day in a vacuum (2026-09-29, user's own words: 'day 13 is with day "
                         "12'). Omit this to keep the single-day behavior --show-date always "
                         "had (--since defaults to --show-date itself). Trading forward day by "
                         "day: keep --since fixed at your very first traded day and just move "
                         "--show-date/--as-of forward each run -- the SAME fixed output files "
                         "then show the whole run so far, every time, never a new file per day. "
                         "Omit this entirely for normal use: it's pinned to dailies_since.txt "
                         "(a second one-line marker file) the first time it's given -- "
                         "explicitly or defaulted to --show-date -- then reused automatically "
                         "on every later run, never needing to be typed again.")
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


def in_trading_window(t: "datetime", display_tz: ZoneInfo) -> bool:
    """Is `t` inside its OWN calendar day's real trading window --
    per-day, not a single fixed floor/ceiling (2026-09-29, --since fix:
    a multi-day range's chain search has no other way to keep rejecting
    Asia-session hours on day 2+ once the run spans more than one day's
    own window; a single window_start/window_end pair only ever bounded
    day one and the LAST day, leaving every overnight Asia session in
    between wide open to produce an "entry" that was never a real one).
    Asia is liquidity-grab only, never an entry session -- this is what
    actually enforces that, on every bar, regardless of how long a
    chain's own search has been running for."""
    date_str = t.astimezone(display_tz).date().isoformat()
    win_start, win_end = trading_window(date_str, display_tz)
    return win_start <= t < win_end


def filter_to_window(engine, win_start: "datetime", win_end: "datetime") -> None:
    """Single-window convenience wrapper around filter_to_windows() --
    see there for what actually counts as "in the window.\""""
    filter_to_windows(engine, [(win_start, win_end)])


def _dates_between(since_str: str, until_str: str) -> list[str]:
    y1, m1, d1 = (int(x) for x in since_str.split("-"))
    y2, m2, d2 = (int(x) for x in until_str.split("-"))
    cur = datetime(y1, m1, d1)
    end = datetime(y2, m2, d2)
    out = []
    while cur <= end:
        out.append(cur.date().isoformat())
        cur += timedelta(days=1)
    return out


def filter_to_windows(engine, windows: list[tuple["datetime", "datetime"]]) -> None:
    """Keep only what's actually active inside ANY of `windows` -- a list
    of DISCONTINUOUS ranges, one real trading session per day, not one
    giant span bridging every overnight/Asia gap in between (2026-09-29,
    user's own words: "I do not want to see the 1h information outside
    the trading windows in any day unless it affects the info inside
    trading window hours" -- a single-window --since range was wrongly
    treating the whole multi-day span, nights included, as "in window,"
    so a 1H POI created AND impacted entirely during an Asia session
    showed up even though it never touched a real trading session).
    This mutates the engine's own zone/event lists in place, before
    write_combined_pine ever sees them, so it needs no changes to the
    shared draw code.

    A POI counts as "in the window" if ANY of its real lifecycle events
    landed inside ANY window -- created, triggered, made eligible,
    impacted, or breached/stopped (STRAND/STRUCTURAL_BREACH, via its
    stop candle). This is exactly the exception the user asked to keep:
    a POI created in Asia but IMPACTED inside London/NY hours still
    shows, because its impact event alone already lands in a window.

    A swing/MSS counts as "in the window" if its confirmation falls
    inside any window, OR it's the single most recent swing high, most
    recent swing low, or most recent MSS confirmed BEFORE the very
    FIRST window started -- the carried-in context the first in-window
    POI's protected level and current trend are actually measured
    against. Nothing after the last window closes shows at all,
    structure or POI alike -- per the user's explicit "I do not want to
    see any info ... after the trading ends.\""""
    first_start = windows[0][0]

    def in_any(t):
        return t is not None and any(s <= t < e for s, e in windows)

    events_in = [e for e in engine.events if in_any(engine.w[e.confirm].start)]
    prior_highs = [e for e in engine.events if e.kind == 0 and engine.w[e.confirm].start < first_start]
    prior_lows = [e for e in engine.events if e.kind == 1 and engine.w[e.confirm].start < first_start]
    carry_in = ([max(prior_highs, key=lambda e: engine.w[e.confirm].start)] if prior_highs else []) + \
               ([max(prior_lows, key=lambda e: engine.w[e.confirm].start)] if prior_lows else [])
    engine.events = sorted(events_in + carry_in, key=lambda e: engine.w[e.confirm].start)

    mss_in = [x for x in engine.msses if in_any(engine.w[x.at].start)]
    prior_mss = [x for x in engine.msses if engine.w[x.at].start < first_start]
    mss_carry_in = [max(prior_mss, key=lambda x: engine.w[x.at].start)] if prior_mss else []
    engine.msses = sorted(mss_in + mss_carry_in, key=lambda x: engine.w[x.at].start)

    def happened_in_window(origin, z):
        stop_t = engine.w[z.stop].start if 0 <= z.stop < len(engine.w) else None
        return any(in_any(t) for t in (
            origin, getattr(z, "trigger_time", None), getattr(z, "eligible_time", None),
            z.impact_time, stop_t,
        ))

    engine.ob_zones = [z for z in engine.ob_zones if happened_in_window(engine.w[z.candle].start, z)]
    engine.rb_zones = [z for z in engine.rb_zones if happened_in_window(engine.w[z.candle].start, z)]
    engine.fvg_zones = [z for z in engine.fvg_zones if happened_in_window(engine.w[z.left].start, z)]


def filter_to_date_range(engine, since_str: str, until_str: str, display_tz: ZoneInfo) -> None:
    """H4/1H scoping across one or more consecutive trading days
    (2026-09-29, user's own words: "day 13 is with day 12" -- a single
    day shown in a vacuum is not how this system is actually traded:
    every new day carries forward what's still alive from the ones
    before it, and the chart should too). ONE real trading window
    (10:00-20:00 / 11:00-21:00 Riyadh, see trading_window()) PER DAY in
    the range -- not the whole calendar day, and not one span bridging
    every night in between (see filter_to_windows()). `since_str` is the
    FIRST day, `until_str` (== --show-date) is the LAST -- when they're
    the same day (--since omitted) this is exactly the single-day window
    it always was."""
    windows = [trading_window(d, display_tz) for d in _dates_between(since_str, until_str)]
    filter_to_windows(engine, windows)


def calendar_day_bounds(date_str: str, display_tz: ZoneInfo) -> tuple["datetime", "datetime"]:
    """The same full 00:00-24:00 Riyadh calendar day filter_to_calendar_range()
    uses, factored out so the "react day" checks below (which need
    today's own calendar-day bounds, not the narrow trading window) share
    the exact same definition of "today" instead of a second copy."""
    y, m, d = (int(x) for x in date_str.split("-"))
    win_start = datetime(y, m, d, 0, 0, 0, tzinfo=display_tz).astimezone(UTC)
    return win_start, win_start + timedelta(days=1)


def find_prev_day_extreme(minutes, mt: list, date_str: str, display_tz: ZoneInfo, side: str):
    """"React day" rule (user, 2026-09-29): the previous day's relevant
    extreme -- its LOW for a SELL bias (a sell setup dies as a fresh
    idea once today reclaims yesterday's low), its HIGH for a BUY bias.

    Computed directly from real M1 data over the previous CALENDAR day
    (same 00:00-24:00 Riyadh definition calendar_day_bounds() uses
    everywhere else) -- NOT by looking up a bar in the Daily engine's
    own aggregated bars (dc.aggregate_days), which are indexed by the
    NY-17:00 forex-day close (01:00 Riyadh in winter), one hour AFTER
    calendar midnight. That one-hour offset was a real bug (2026-09-29):
    probing with a midnight timestamp against those NY-anchored bar
    boundaries always matched the PRIOR bar -- i.e. the day before the
    one intended -- so every call was silently using the wrong day's
    extreme, off by one, every single time in winter. Verified: for
    14 Jan, the old code returned 12 Jan's low (1.16213); the real
    previous calendar day (13 Jan) low was 1.16339.

    Returns None for side "ALL" (no single bias to check) or if there's
    no prior day's data in the dataset."""
    if side not in ("SELL", "BUY"):
        return None
    y, m, d = (int(x) for x in date_str.split("-"))
    prev_date = (datetime(y, m, d) - timedelta(days=1)).date().isoformat()
    win_start, win_end = calendar_day_bounds(prev_date, display_tz)
    i0, i1 = bisect_left(mt, win_start), bisect_left(mt, win_end)
    if i0 >= i1:
        return None
    day_minutes = minutes[i0:i1]
    return min(x.l for x in day_minutes) if side == "SELL" else max(x.h for x in day_minutes)

def find_prev_day_sweep_time(minutes, mt: list, date_str: str, display_tz: ZoneInfo, side: str, extreme):
    """First minute, anywhere in today's own full calendar day (same
    scope as Daily's own -- a sweep can happen before the trading window
    even opens), that actually takes the previous day's extreme. None if
    it never happens -- the case the user confirmed by hand for 13 Jan
    2026 ("13 did not take 12's low")."""
    if extreme is None:
        return None
    win_start, win_end = calendar_day_bounds(date_str, display_tz)
    i0 = bisect_left(mt, win_start)
    for m in minutes[i0:]:
        if m.t >= win_end:
            break
        if (m.l <= extreme) if side == "SELL" else (m.h >= extreme):
            return m.t
    return None


def is_react_day(d_zones_full, side: str, date_str: str, display_tz: ZoneInfo) -> bool:
    """The react-day rule only ever applies on a REACT day -- the day
    AFTER the Daily POI's own impact -- never on the impact day itself
    (2026-09-29, real bug caught while moving to 14 Jan: applying the
    prior-day-extreme-sweep check unconditionally, every day, silently
    would have abandoned 1H on 12 Jan too -- 11 Jan's low got swept at
    01:08 Riyadh that morning -- even though 12 Jan is the day FVG#1
    itself impacted (10:26 Riyadh), not a react day at all. A day only
    counts as "react" if NO same-side Daily POI impacted on it -- i.e.
    today's whole bias is carried in from an earlier day, not set fresh
    today."""
    if side not in ("SELL", "BUY"):
        return False
    win_start, win_end = calendar_day_bounds(date_str, display_tz)
    want_bull = side == "BUY"
    for zones in (d_zones_full.ob_zones, d_zones_full.rb_zones, d_zones_full.fvg_zones):
        for z in zones:
            if z.impact_time is not None and z.bullish == want_bull and win_start <= z.impact_time < win_end:
                return False
    return True
    return None


def structural_invalid_at(z, it: "datetime", bars: list, bar_starts: list,
                           minutes, mt: list) -> tuple:
    """Ported from five_bso_engine.py's structural_invalid_at() (SPEC.md
    SS17/SS20-24) -- the POI-violation-before-entry check the user asked
    about directly (2026-09-28) and that compute_5m_trades() previously
    had no answer for. Whichever happens first, from the zone's own
    impact time `it`:
      (a) 'h4_close' -- a fully completed 4H/1H candle closes its BODY
          at or beyond the NEAR boundary (zt for a bearish zone approached
          from above, zb for a bullish zone approached from below). A
          bare wick, or a close that hasn't reached the zone at all,
          doesn't count -- only a body close inside or through it.
      (b) 'swing_break' -- the zone's own snapshotted `protect_level`
          (the protecting swing price at creation) gets exceeded, at the
          exact 1m moment it happens. Unlike the original OB-only engine
          (which had to re-derive the protecting swing separately, since
          OB zones there had no protect_level field), every zone type
          here already carries protect_level uniformly, so it's used
          directly -- this also matches the later FVG-session correction
          that anchor-break must check protect_level, not the box edge.
    Returns (time, reason); (None, None) if never invalidated in the
    available data. A candidate whose resting swing or entry trigger
    lands at/after this time is dead: setup only, no entry."""
    bull = z.bullish
    near_boundary = z.zt if bull else z.zb

    h4_close_invalid_at = None
    start_idx = max(0, bisect_right(bar_starts, it) - 1)
    for hb in bars[start_idx:]:
        breach = (hb.c <= near_boundary) if bull else (hb.c >= near_boundary)
        if breach:
            h4_close_invalid_at = hb.end
            break

    swing_break_at = None
    idx = bisect_right(mt, it)
    for m in minutes[idx:]:
        if (m.l < z.protect_level) if bull else (m.h > z.protect_level):
            swing_break_at = m.t
            break

    if h4_close_invalid_at is not None and (swing_break_at is None or h4_close_invalid_at <= swing_break_at):
        return h4_close_invalid_at, "h4_close"
    if swing_break_at is not None:
        return swing_break_at, "swing_break"
    return None, None


def run_5m_bso(z, it, bar_starts5: list, events5_sorted: list, minutes, mt: list,
               invalidated_at, window_end, display_tz: ZoneInfo,
               watch_levels: list[tuple[str, float]] | None = None) -> dict:
    """Ported from five_bso_engine.py's run_bso() -- a single attempt.
    Genuinely different from the previous "first swing after impact is
    the entry" rule: this races an entry CANDIDATE against replacement
    and against invalidation, not a fixed level.
      1. `resting` = the first confirmed 5m swing of the SL-anchor kind
         (a LOW for a buy setup, a HIGH for a sell setup) at/after `it`.
         Nothing before this swing forms can be entered.
      2. `candidate` = the most recent entry-trigger-kind swing (opposite
         of resting's kind) confirmed at/before resting's own swing --
         the level a stop order actually rests at.
      3. Scanning 1m bars forward from resting's confirmation: any LATER
         entry-kind swing that confirms before entry fires REPLACES the
         candidate (the stop order chases the newest swing, same as the
         real engine did). Invalidation is checked on every bar BEFORE
         the break test, and the trading window close is a hard ceiling.
      4. On break, SL = the extreme (not just the last) of every
         SL-anchor-kind swing from `it` through the entry minute.
         TP = entry +/- 3R.
    Always returns a dict with a "stage" key -- "ENTERED" on a real
    trade, or one of the original engine's own no-trade stage names
    otherwise (NO_RESTING_SWING, NO_CANDIDATE, POI_BREACHED,
    NO_ENTRY_IN_WINDOW, NO_SL_POOL, ZERO_RISK) -- so every attempt,
    entered or not, can be written to the 5m trades ledger with a real
    reason instead of a bare skip.

    On ENTERED, also tracks (2026-09-29, ported from five_bso_engine.py's
    own SS34 MFE/MAE, previously dropped in the port -- a real gap, not
    an intentional cut):
      - mfe/mae: Maximum Favorable/Adverse Excursion, entry (exclusive)
        through exit (inclusive) -- or through all available data if the
        trade never resolves (OPEN). Price-based BE-rule material.
      - watch_hits: a generic, EXTENSIBLE structural-note mechanism --
        `watch_levels` is a list of (label, price) pairs to watch for
        during the same scan; the first minute each one is reached (in
        the trade's own favorable direction) is recorded as
        {label: datetime}. Structure-based BE-rule material, meant to
        grow over time as more structural events are identified -- this
        is the room for that, not a one-off special case."""
    bull = z.bullish
    need_rest_kind = 1 if bull else 0   # buy needs a resting LOW (SL anchor); sell needs a resting HIGH
    need_cand_kind = 0 if bull else 1   # entry-trigger kind is the opposite: HIGH for buy, LOW for sell

    start5 = bisect_right(bar_starts5, it) - 1
    if start5 < 0:
        return dict(stage="NO_5M_BAR_FOR_IMPACT")

    resting = None
    for ev in events5_sorted:
        if ev.kind != need_rest_kind or ev.swing < start5:
            continue
        resting = ev
        break
    if resting is None:
        return dict(stage="NO_RESTING_SWING")
    if resting.at is None:
        return dict(stage="RESTING_SWING_UNRESOLVED_M1")

    candidates_before = [ev for ev in events5_sorted if ev.kind == need_cand_kind and ev.swing <= resting.swing]
    if not candidates_before:
        return dict(stage="NO_CANDIDATE", resting_at=resting.at)
    current = candidates_before[-1]

    later_candidates = sorted(
        [ev for ev in events5_sorted if ev.kind == need_cand_kind and ev.at is not None and ev.at > resting.at],
        key=lambda e: e.at)

    idx = bisect_left(mt, resting.at)
    entry_m = None
    stopped = False
    cand_ptr = 0
    replacements = 0
    for i in range(idx, len(minutes)):
        m = minutes[i]
        if m.t >= window_end:
            break  # never triggers before the trading window closes -- setup only
        if invalidated_at is not None and m.t >= invalidated_at:
            stopped = True
            break  # POI violated (body close or protect_level break) before the trigger
        while cand_ptr < len(later_candidates) and later_candidates[cand_ptr].at <= m.t:
            current = later_candidates[cand_ptr]
            replacements += 1
            cand_ptr += 1
        if not in_trading_window(m.t, display_tz):
            continue  # Asia (or any off-hours minute) never triggers an entry, structure still updates above
        broke = (m.h > current.price) if bull else (m.l < current.price)
        if broke:
            entry_m = m
            break
    if entry_m is None:
        return dict(stage="POI_BREACHED" if stopped else "NO_ENTRY_IN_WINDOW",
                    resting_at=resting.at, candidate_price=current.price, replacements=replacements)

    entry_price = current.price
    entry_time = entry_m.t

    pool = [ev for ev in events5_sorted if ev.kind == need_rest_kind and ev.swing >= start5
            and ev.at is not None and ev.at <= entry_time]
    if not pool:
        return dict(stage="NO_SL_POOL", resting_at=resting.at, entry_time=entry_time, entry_price=entry_price)
    sl_price = min(p.price for p in pool) if bull else max(p.price for p in pool)
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return dict(stage="ZERO_RISK", resting_at=resting.at, entry_time=entry_time,
                    entry_price=entry_price, sl_price=sl_price)
    tp_price = entry_price + 3 * risk if bull else entry_price - 3 * risk

    result, exit_time = None, None
    mfe_price, mae_price = entry_price, entry_price
    watch_hits: dict[str, "datetime"] = {}
    for i in range(bisect_left(mt, entry_time) + 1, len(minutes)):
        m = minutes[i]
        if bull:
            mfe_price = max(mfe_price, m.h)
            mae_price = min(mae_price, m.l)
        else:
            mfe_price = min(mfe_price, m.l)
            mae_price = max(mae_price, m.h)
        if watch_levels:
            for label, lvl in watch_levels:
                if label not in watch_hits and ((m.h >= lvl) if bull else (m.l <= lvl)):
                    watch_hits[label] = m.t
        hit_sl = (m.l <= sl_price) if bull else (m.h >= sl_price)
        hit_tp = (m.h >= tp_price) if bull else (m.l <= tp_price)
        if hit_sl and hit_tp:
            result, exit_time = "AMBIGUOUS", m.t
            break
        if hit_sl:
            result, exit_time = "SL", m.t
            break
        if hit_tp:
            result, exit_time = "TP", m.t
            break

    return dict(stage="ENTERED", resting_at=resting.at, replacements=replacements,
                entry_time=entry_time, entry_price=entry_price, sl_price=sl_price,
                tp_price=tp_price, risk=risk, result=result or "OPEN", exit_time=exit_time,
                mfe=abs(mfe_price - entry_price), mae=abs(mae_price - entry_price), watch_hits=watch_hits)


def run_5m_chain(z, impact_time, bar_starts5: list, events5_sorted: list, minutes, mt: list,
                  invalidated_at, window_end, display_tz: ZoneInfo,
                  watch_levels: list[tuple[str, float]] | None = None) -> list:
    """Ported from five_bso_engine.py's run_bso_chain() (SS27, "made
    universal per the user's explicit instruction"). After a plain SL,
    re-arm and search again from the SL's own exit time, as long as the
    POI's structural premise (`invalidated_at`) hasn't been crossed yet.
    Stops on the first attempt that resolves to anything other than a
    plain SL (TP/OPEN/AMBIGUOUS, or any no-entry stage). Per the
    original reporting rule: a re-entry (attempt 2+) that never actually
    became a trade is not reported at all -- it only still ends the
    search there. The first attempt is always reported, trade or not,
    since that's the POI's own result, not a re-entry."""
    attempts = []
    search_from = impact_time
    attempt_no = 1
    while True:
        res = run_5m_bso(z, search_from, bar_starts5, events5_sorted, minutes, mt, invalidated_at, window_end,
                          display_tz, watch_levels)
        entered = res.get("stage") == "ENTERED"
        if attempt_no == 1 or entered:
            res["attempt"] = attempt_no
            attempts.append(res)
        if not entered or res.get("result") != "SL":
            break
        exit_time = res.get("exit_time")
        if exit_time is None:
            break
        if invalidated_at is not None and exit_time >= invalidated_at:
            break
        search_from = exit_time
        attempt_no += 1
    return attempts


def compute_5m_trades(h4_engine, h1_engine, e5, minutes, window_start, window_end, display_tz,
                       side: str = "ALL", h1_abandon_at=None) -> tuple[list[dict], list[dict]]:
    """The real entry rule (2026-09-28 this session, ported 2026-09-28
    from the previously-built and dataset-validated `five_bso_engine.py`
    -- SPEC.md SS17/SS20-27 -- after the user asked whether POI
    violation before entry was checked, and it wasn't):
      1. A 4H or 1H POI impacts, in premium (sell) or discount (buy) --
         unchanged: the 50/50 split between the zone's own protect_level
         and the most recent opposing-kind swing confirmed before impact.
      2. `structural_invalid_at()` computes, once per zone, the first
         moment its structural premise dies (a body close through the
         near edge, or its protect_level swing getting exceeded). This
         is the real POI-violation-before-entry gate.
      3. `run_5m_chain()` races an entry candidate (see run_5m_bso) that
         can be replaced by a newer swing before it triggers, checked
         against invalidation on every 1m bar, and re-arms for a further
         attempt after a plain SL as long as the POI is still alive --
         the real re-entry rule (SS27), not assumed.
      4. SL = the extreme of every qualifying SL-anchor swing in the
         window, not just the most recent one. TP = 3R, unchanged.
    Two POIs producing the identical 5m entry (same price, same trigger
    minute) collapse into ONE trade -- unchanged single-opportunity rule.

    `side`: "SELL"/"BUY" restricts to that direction only, matching
    --default-side; "ALL" computes both.

    `e5` is the caller's own 5m WeeklyCombinedEngine (built once, over
    the FULL dataset, so candidate/resting-swing lookups aren't starved
    by date-window filtering) -- also reused by the caller to write the
    5m swings/report audit files.

    Returns (trades, ledger_rows): `trades` is the deduped, drawn set
    (unchanged shape, for the pine table/boxes); `ledger_rows` is EVERY
    attempt on EVERY qualifying zone, entered or not, with its stage and
    reason -- written to 5m_trades_ledger.csv by the caller so "why
    didn't this POI trade" never again needs a one-off script.

    `h4_engine`/`h1_engine` are expected to be the FULL, unfiltered
    (pre-date-filter) zone/event snapshots (2026-09-29, "react day" fix
    -- a POI impacted on a PRIOR day, still alive and still the day's
    controlling idea today, was previously silently dropped as a
    candidate entirely, because it only ever got engines[] AFTER
    filter_to_date_range() had already trimmed out anything with no
    lifecycle event inside TODAY's narrow window). A carried-in zone's own entry
    SEARCH still only starts at `window_start` (today's own open), never
    re-litigating a trade a prior day's own run already found and
    reported -- only the zone's *eligibility* (impact, protect_level,
    invalidation) carries across days, not its already-resolved history.

    `h1_abandon_at`: the "react day" rule (user, 2026-09-29) -- once
    today sweeps the previous day's relevant extreme (the low, for a
    SELL bias; the high, for a BUY bias), 1H setups are abandoned for
    the rest of the day and only 4H stays in play. Same ceiling
    treatment as same-leg supersession: it caps how much LONGER a 1H
    zone may keep searching, it does not erase a 1H entry already found
    before the sweep."""
    mt = [m.t for m in minutes]
    hi = [m.h for m in minutes]
    lo = [m.l for m in minutes]

    bar_starts5 = [b.start for b in e5.w]
    events5_sorted = sorted(e5.events, key=lambda e: (e.confirm, e.kind))

    def riyadh(t):
        return wob.display_iso(t, display_tz) if t else ""

    candidates = []
    for eng, tf_tag in ((h4_engine, "H4"), (h1_engine, "1H")):
        eng_bar_starts = [b.start for b in eng.w]
        for zones, ptype in ((eng.ob_zones, "OB"), (eng.rb_zones, "RB"), (eng.fvg_zones, "FVG")):
            for z in zones:
                if z.impact_time is None or z.protect_level is None:
                    continue
                if side == "SELL" and z.bullish:
                    continue
                if side == "BUY" and not z.bullish:
                    continue
                # `eng` is now the FULL (unfiltered) history, not just
                # today's window -- so bound candidates to what's still
                # actually relevant to today: impacted by today's close.
                # (Real "already dead before today" filtering happens
                # just below, via structural_invalid_at -- z.stop is
                # only the zone's own IMPACT bar, same event as
                # impact_time, not a death marker; using it as one would
                # have wrongly excluded live zones.)
                if z.impact_time > window_end:
                    continue
                candidates.append((eng, eng_bar_starts, z, ptype, tf_tag))

    trades_raw = []  # one dict per zone's own ENTERED attempt, pre-merge
    ledger_rows = []  # non-entered (skip/no-trade) rows go straight in, already string-formatted
    for eng, eng_bar_starts, z, ptype, tf_tag in candidates:
        sell = not z.bullish
        poi = f"{ptype}#{z.id}"
        row_base = dict(tf=tf_tag, poi=poi, side="SELL" if sell else "BUY",
                         zone_bottom=f"{z.zb:.5f}", zone_top=f"{z.zt:.5f}",
                         protect_level=f"{z.protect_level:.5f}", impact_riyadh=riyadh(z.impact_time),
                         invalidated_riyadh="", invalidated_reason="", premium_mid="",
                         attempt="", resting_riyadh="", replacements="",
                         entry_riyadh="", entry_price="", sl_price="", tp_price="",
                         sl_hit_riyadh="", tp_hit_riyadh="", risk_price="", r_pips="",
                         mfe_pips="", mae_pips="", result="", exit_riyadh="", r_multiple="",
                         sl_tp_conflict="", structural_notes="", h1_abandoned_riyadh="")

        # Same-leg supersession (see mark_superseded_same_leg): a later
        # same-direction, unbroken-leg POI caps how much longer THIS zone
        # may still search for a NEW entry -- not a hard skip, so a real
        # entry this zone already found before the newer POI's own
        # impact still stands.
        superseded_at = getattr(z, "superseded_at", None)
        eff_window_end = min(window_end, superseded_at) if superseded_at is not None else window_end
        row_base["superseded_riyadh"] = riyadh(superseded_at)

        # "React day" rule (user, 2026-09-29): once today sweeps the
        # previous day's relevant extreme, 1H setups are abandoned for
        # the rest of the day -- same ceiling treatment as supersession,
        # so a 1H entry already found before the sweep still stands.
        if tf_tag == "1H" and h1_abandon_at is not None:
            eff_window_end = min(eff_window_end, h1_abandon_at)
            row_base["h1_abandoned_riyadh"] = riyadh(h1_abandon_at)

        # Born-violated OB/RB (2026-09-30, see mark_open_inside_trigger's
        # own docstring -- checked before anything else, same reasoning
        # as DEAD_BEFORE_WINDOW below: a zone that was never valid to
        # begin with should never reach the opposing-swing/premium
        # checks that assume a real zone.
        if getattr(z, "rejected", False):
            ledger_rows.append(dict(row_base, stage="OPEN_INSIDE_ZONE"))
            continue

        # A zone carried in from a prior day (candidates now come from
        # FULL, unfiltered history -- see this function's own docstring)
        # may simply already be structurally dead by the time today's
        # window opens. Check that FIRST, before spending any more work
        # on it: an ancient, long-invalidated zone should never reach
        # the opposing-swing/premium-discount checks below at all.
        invalidated_at, reason = structural_invalid_at(z, z.impact_time, eng.w, eng_bar_starts, minutes, mt)
        if invalidated_at is not None and invalidated_at < window_start:
            ledger_rows.append(dict(row_base, stage="DEAD_BEFORE_WINDOW",
                                     invalidated_riyadh=riyadh(invalidated_at), invalidated_reason=reason or ""))
            continue

        opp_kind = 1 if sell else 0  # opposing swing: a LOW for a sell reaction, a HIGH for a buy reaction
        opp_events = [e for e in eng.events if e.kind == opp_kind and eng.w[e.confirm].start <= z.impact_time]
        if not opp_events:
            ledger_rows.append(dict(row_base, stage="NO_OPPOSING_SWING"))
            continue
        opp = max(opp_events, key=lambda e: eng.w[e.confirm].start)
        opp_t = eng.w[opp.confirm].start
        mid = (z.protect_level + opp.price) / 2

        i0, i1 = bisect_left(mt, opp_t), bisect_left(mt, z.impact_time)
        if i1 < i0:
            ledger_rows.append(dict(row_base, stage="BAD_TIME_RANGE"))
            continue
        if sell:
            reached = max(hi[i0:i1 + 1]) >= mid
        else:
            reached = min(lo[i0:i1 + 1]) <= mid
        if not reached:
            ledger_rows.append(dict(row_base, stage="PREMIUM_NOT_REACHED", premium_mid=f"{mid:.5f}"))
            continue

        # watch_levels: structural reference prices to check for after
        # entry -- room to grow (2026-09-29, user's own words: "I will
        # tell you any more structural note I see in the road"). The
        # first one: the immediate opposing swing that formed right
        # before this POI's own impact (the same `opp` swing the
        # premium/discount check already uses) -- a candidate future BE
        # trigger the user wants tracked, universally, for every trade.
        watch_levels = [("pre_impact_swing", opp.price)]
        # Search for a NEW entry never starts before today's own window
        # open, even for a zone carried in from a prior day (react-day
        # case) -- otherwise this would just rediscover and re-report
        # the exact same entry a prior day's own run already found.
        # Everything else (opposing swing, invalidation, premium/
        # discount) still measures from the zone's real impact_time.
        search_from = max(z.impact_time, window_start)
        attempts = run_5m_chain(z, search_from, bar_starts5, events5_sorted, minutes, mt,
                                 invalidated_at, eff_window_end, display_tz, watch_levels)
        for a in attempts:
            if a.get("stage") != "ENTERED":
                ledger_rows.append(dict(row_base, stage=a.get("stage"), premium_mid=f"{mid:.5f}",
                                         invalidated_riyadh=riyadh(invalidated_at), invalidated_reason=reason or "",
                                         attempt=a.get("attempt"), resting_riyadh=riyadh(a.get("resting_at")),
                                         replacements=a.get("replacements")))
                continue
            trades_raw.append(dict(
                tf=tf_tag, poi=poi, side="SELL" if sell else "BUY", zone_bottom=z.zb, zone_top=z.zt,
                protect_level=z.protect_level, impact_time=z.impact_time, superseded_at=superseded_at,
                invalidated_at=invalidated_at, invalidated_reason=reason, premium_mid=mid,
                attempt=a.get("attempt"), resting_at=a.get("resting_at"), replacements=a.get("replacements"),
                entry_time=a["entry_time"], entry_price=a["entry_price"], sl_price=a["sl_price"],
                tp_price=a["tp_price"], risk=a["risk"], result=a["result"], exit_time=a.get("exit_time"),
                mfe=a.get("mfe"), mae=a.get("mae"), watch_hits=a.get("watch_hits") or {},
                pre_impact_swing_price=opp.price,
            ))

    # Dedup: identical entry (same price, same trigger minute) -> ONE real
    # trade, whatever POI(s) produced it. Chart and ledger are now built
    # from this SAME grouping (previously the ledger kept one row per
    # contributing POI even after the chart had already merged them into
    # a single box -- the user caught this: two rows in the CSV for a
    # trade the chart only ever drew once).
    groups: dict[tuple, list[dict]] = {}
    for t in trades_raw:
        key = (t["entry_time"], round(t["entry_price"], 5))
        groups.setdefault(key, []).append(t)

    trades = []
    for members in groups.values():
        members.sort(key=lambda m: (m["tf"], m["poi"]))
        first = members[0]
        # entry/time are identical by construction (the dedup key); SL/TP
        # are each POI's own computed value and CAN legitimately differ
        # (different protect_level -> different SL-anchor pool) even when
        # the entry itself coincides -- flagged, not silently dropped.
        sl_tp_conflict = any(abs(m["sl_price"] - first["sl_price"]) > 1e-9
                              or abs(m["tp_price"] - first["tp_price"]) > 1e-9 for m in members[1:])
        result = first["result"]
        exit_t = first.get("exit_time")
        # sl_hit_riyadh/tp_hit_riyadh: the SAME exit fact the result/
        # exit_riyadh columns already carry, just split into whichever
        # column matches -- so which one fired is readable at a glance
        # without cross-referencing the result column (the user's own
        # ask), not a second independent computation.
        sl_hit_riyadh = riyadh(exit_t) if result == "SL" else ""
        tp_hit_riyadh = riyadh(exit_t) if result == "TP" else ""

        # Structural notes -- extensible (see watch_levels in run_5m_bso;
        # more checks land here over time, never replacing this one).
        # Note #1: did price reach the immediate pre-impact opposing
        # swing after entry, and when -- a candidate future BE trigger.
        notes = []
        for m in members:
            hit_at = (m.get("watch_hits") or {}).get("pre_impact_swing")
            if hit_at is not None:
                notes.append(f"{m['poi']}: reached pre-impact swing ({m['pre_impact_swing_price']:.5f}) "
                             f"at {riyadh(hit_at)} RYD")
        structural_notes = "; ".join(notes)

        trades.append(dict(
            side=first["side"], entry_time=first["entry_time"], entry_price=first["entry_price"],
            sl=first["sl_price"], tp=first["tp_price"], r_pips=first["risk"] * 10000,
            impact_time=min(m["impact_time"] for m in members),
            poi_sources=[m["poi"] for m in members],
            mfe_pips=first.get("mfe", 0.0) * 10000, mae_pips=first.get("mae", 0.0) * 10000,
            sl_hit_riyadh=sl_hit_riyadh, tp_hit_riyadh=tp_hit_riyadh, structural_notes=structural_notes,
        ))

        ledger_rows.append(dict(
            tf="/".join(dict.fromkeys(m["tf"] for m in members)),
            poi="+".join(m["poi"] for m in members), side=first["side"],
            zone_bottom="/".join(f"{m['zone_bottom']:.5f}" for m in members),
            zone_top="/".join(f"{m['zone_top']:.5f}" for m in members),
            protect_level="/".join(f"{m['protect_level']:.5f}" for m in members),
            impact_riyadh="/".join(riyadh(m["impact_time"]) for m in members),
            superseded_riyadh="/".join(riyadh(m["superseded_at"]) for m in members),
            invalidated_riyadh="/".join(riyadh(m["invalidated_at"]) for m in members),
            invalidated_reason="/".join(m["invalidated_reason"] or "-" for m in members),
            premium_mid="/".join(f"{m['premium_mid']:.5f}" for m in members),
            attempt="/".join(str(m["attempt"]) for m in members),
            stage="ENTERED",
            resting_riyadh="/".join(riyadh(m["resting_at"]) for m in members),
            replacements="/".join(str(m["replacements"]) for m in members),
            entry_riyadh=riyadh(first["entry_time"]), entry_price=f"{first['entry_price']:.5f}",
            sl_price=f"{first['sl_price']:.5f}", tp_price=f"{first['tp_price']:.5f}",
            sl_hit_riyadh=sl_hit_riyadh, tp_hit_riyadh=tp_hit_riyadh,
            risk_price=f"{first['risk']:.5f}", r_pips=f"{first['risk'] * 10000:.1f}",
            mfe_pips=f"{first['mfe'] * 10000:.1f}" if first.get("mfe") is not None else "",
            mae_pips=f"{first['mae'] * 10000:.1f}" if first.get("mae") is not None else "",
            result=result or "", exit_riyadh=riyadh(exit_t),
            r_multiple="+3.00" if result == "TP" else ("-1.00" if result == "SL" else ""),
            sl_tp_conflict="YES" if sl_tp_conflict else "",
            structural_notes=structural_notes,
        ))

    return sorted(trades, key=lambda t: t["entry_time"]), ledger_rows


LEDGER_FIELDS = [
    "tf", "poi", "side", "zone_bottom", "zone_top", "protect_level",
    "impact_riyadh", "superseded_riyadh", "h1_abandoned_riyadh",
    "invalidated_riyadh", "invalidated_reason", "premium_mid",
    "attempt", "stage", "resting_riyadh", "replacements",
    "entry_riyadh", "entry_price", "sl_price", "tp_price", "sl_hit_riyadh", "tp_hit_riyadh",
    "risk_price", "r_pips", "mfe_pips", "mae_pips",
    "result", "exit_riyadh", "r_multiple", "sl_tp_conflict", "structural_notes",
]


def write_5m_trades_ledger(base: Path, ledger_rows: list[dict],
                            out_name: str = "5m_trades_ledger.csv") -> None:
    """One row per NON-entered attempt (skip reason, or a dead-end
    attempt) on every zone that reached the premium/discount gate that
    day, PLUS one row per real ENTERED trade -- already merged the same
    way the chart's own dedup merges identical entries, so a trade drawn
    once on the chart is one row here too, not one per contributing POI.
    Every field arrives from compute_5m_trades() already formatted
    (Riyadh timestamps, 5-decimal prices) -- this is a plain dump, no
    formatting logic here to drift out of sync with the chart's own.
    Written every run with --show-date, same fixed name, overwritten in
    place."""
    import csv

    with (base / out_name).open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        wr.writeheader()
        for row in ledger_rows:
            wr.writerow(row)


def mark_open_inside_trigger(engine) -> None:
    """User's rule (2026-09-30, real ICT concept, NOT in five_bso_engine.py
    or SPEC.md -- checked, absent, same status as premium/discount: new,
    directed now, not yet validated against the original port):

    "if the open of the impact candle is already in the OB, RB (not
    FVG) zones we are done, we do not trade from that OB or RB."

    User's own correction (2026-09-30, after `z.trigger` mistakenly
    caught real, unrelated cases): this is specifically about the
    IMPACT candle, not the trigger candle -- for Aggressive POIs
    (AOB/ARB) those two happen to be the same bar, which is what made
    the first version look right on the AOB/ARB example, but for other
    zone types (IRB, IFOB, ...) trigger and impact are genuinely
    different bars, and only the impact candle's open matters: if that
    candle's own open is already inside [zb, zt], its body will close
    inside the zone the moment it forms, which the zone can't survive.
    Found the impact bar by locating the bar whose own [start, end)
    span contains z.impact_time (same bisect-against-bar-starts pattern
    used everywhere else in this file for exactly that lookup).  Applies
    to OB and RB only, at every timeframe (Daily/4H/1H) -- FVG has no
    equivalent concept and is untouched. Reuses the SAME `rejected`
    field OB already had and RB now has too, so every existing
    `getattr(z, "rejected", False)` check (drawing, table, ledger)
    picks this up with no other change."""
    bar_starts = [b.start for b in engine.w]
    for zones in (engine.ob_zones, engine.rb_zones):
        for z in zones:
            if z.rejected or z.impact_time is None:
                continue
            impact_idx = bisect_right(bar_starts, z.impact_time) - 1
            if not (0 <= impact_idx < len(engine.w)):
                continue
            impact_open = engine.w[impact_idx].o
            if z.zb <= impact_open <= z.zt:
                z.rejected = True


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


def mark_superseded_same_leg(engine, minutes, mt: list) -> None:
    """User's rule (2026-09-29): when a POI impacts while another
    same-direction POI in the same unbroken leg is still active (not yet
    structurally invalidated), they are ONE opportunity, not two -- e.g.
    the 12 Jan 2026 case: a lower Daily FVG impacted, was never
    invalidated, and price ran on into a higher Daily FVG which is what
    the day's 1H setups actually came from. Cuts across zone TYPE too --
    an OB followed later by an RB in the same unbroken same-direction
    move collapses exactly like FVG-then-FVG does, since the type
    doesn't matter to "are we still in the same leg."

    Sets `z.superseded_at` (a datetime, or None) instead of a plain
    boolean: supersession takes effect from the LATER zone's own impact
    time onward, not retroactively. If the earlier zone had already
    found its own resting swing and entered BEFORE the later zone even
    impacted, that entry is real and already happened -- it must stand,
    not vanish because a newer POI showed up afterward. What supersession
    actually stops is any NEW entry attempt (or re-entry) starting after
    that moment: compute_5m_trades() uses superseded_at as an additional
    ceiling alongside the trading-window close, exactly the same way.

    "Let them be there" (the user's own words) -- this does NOT remove
    anything from engine.ob_zones/rb_zones/fvg_zones, so the pine boxes
    and table are untouched."""
    for zones in (engine.ob_zones, engine.rb_zones, engine.fvg_zones):
        for z in zones:
            z.superseded_at = None

    all_zones = list(engine.ob_zones) + list(engine.rb_zones) + list(engine.fvg_zones)
    bar_starts = [b.start for b in engine.w]

    for bull in (True, False):
        impacted = sorted(
            (z for z in all_zones if z.bullish == bull and z.impact_time is not None and z.protect_level is not None),
            key=lambda z: z.impact_time)
        active = None
        for z in impacted:
            if active is not None:
                inv_at, _ = structural_invalid_at(active, active.impact_time, engine.w, bar_starts, minutes, mt)
                if inv_at is None or inv_at > z.impact_time:
                    active.superseded_at = z.impact_time  # same unbroken leg -> superseded by z, from here on
            active = z


def build_trades_pine(trades: list[dict], display_tz: ZoneInfo) -> list[str]:
    """5m entry/SL/TP visualization: an entry label (the order itself), an
    SL label+box (red, risk) and a TP label+box (green, reward) per trade,
    plus a table -- all gated on the 5m chart specifically and behind a
    single "Show 5m trades" toggle. Uses the same array-pack-once,
    draw-in-one-loop discipline as everything else here (CE10295)."""
    lines = [
        'bool showTrades = input.bool(true, "Show 5m trades", group="Trades")',
    ]
    if not trades:
        lines.append('// no qualifying trades for this --show-date window')
        return lines

    # User's own layout (2026-09-29): price+time pairs share ONE column
    # each (Entry, SL, TP), MFE/MAE share one column, notes shortened,
    # and the POI column IS the parent-1H/4H link (relabeled so that's
    # explicit) -- 8 columns instead of 12.
    side, entry_x, entry_disp, sl_disp, tp_disp, r_pips, poi, impact_x, mfe_mae, notes = \
        [], [], [], [], [], [], [], [], [], []
    for t in trades:
        bull = t["side"] == "BUY"
        side.append(t["side"])
        entry_x.append(wc.wrb.pine_epoch(t["entry_time"]))
        impact_x.append(wc.wrb.pine_epoch(t["impact_time"]))
        entry_time_str = t["entry_time"].astimezone(display_tz).strftime("%H:%M")
        entry_disp.append(f"{t['entry_price']:.5f} @ {entry_time_str}")
        sl_hit, tp_hit = t.get("sl_hit_riyadh"), t.get("tp_hit_riyadh")
        sl_time_str = sl_hit[-8:-3] if sl_hit else None  # "...HH:MM:SS" -> "HH:MM"
        tp_time_str = tp_hit[-8:-3] if tp_hit else None
        sl_disp.append(f"{t['sl']:.5f} @ {sl_time_str}" if sl_time_str else f"{t['sl']:.5f}")
        tp_disp.append(f"{t['tp']:.5f} @ {tp_time_str}" if tp_time_str else f"{t['tp']:.5f}")
        r_pips.append(round(t["r_pips"], 1))
        poi.append("+".join(t["poi_sources"]))
        mfe_mae.append(f"{t.get('mfe_pips', 0.0):.1f} / {t.get('mae_pips', 0.0):.1f}")
        # Shortened per the user's own ask -- drop the POI prefix (the
        # POI column already says it), the date (one --show-date day
        # only) and "RYD" (whole table is Riyadh); keep the label + time.
        raw_note = t.get("structural_notes") or ""
        short = re.sub(r'^\S+#\d+:\s*', '', raw_note)              # drop "RB#67: "
        short = re.sub(r'\s*\(\d+\.\d+\)', '', short)               # drop "(1.16754)"
        short = re.sub(r'\s+at\s+\d{4}-\d\d-\d\d\s+(\d\d:\d\d):\d\d\s+RYD', r' @\1', short)
        notes.append(short or "-")

    lines += [
        *wc.wrb.pack_array("trSide", "string", side),
        *wc.wrb.pack_array("trEntryX", "int", entry_x),
        *wc.wrb.pack_array("trEntryY", "float", [round(t["entry_price"], 5) for t in trades]),
        *wc.wrb.pack_array("trSL", "float", [round(t["sl"], 5) for t in trades]),
        *wc.wrb.pack_array("trTP", "float", [round(t["tp"], 5) for t in trades]),
        *wc.wrb.pack_array("trEntryDisp", "string", entry_disp),
        *wc.wrb.pack_array("trSlDisp", "string", sl_disp),
        *wc.wrb.pack_array("trTpDisp", "string", tp_disp),
        *wc.wrb.pack_array("trRPips", "float", r_pips),
        *wc.wrb.pack_array("trPoi", "string", poi),
        *wc.wrb.pack_array("trImpactX", "int", impact_x),
        *wc.wrb.pack_array("trMfeMae", "string", mfe_mae),
        *wc.wrb.pack_array("trNotes", "string", notes),
        f'var table trTable = table.new(position.bottom_right, 8, {len(trades) + 1}, border_width=1)',
        'if barstate.islast and onFive and showTrades and array.size(trSide) > 0',
        '    boxRightOffset = 2 * 60 * 60 * 1000',
        '    headers2 = array.from("Side", "Entry", "SL", "TP", "R (pips)", "Parent 1H/4H POI", '
        '"MFE / MAE (pips)", "Notes")',
        '    for c = 0 to array.size(headers2) - 1',
        '        table.cell(trTable, c, 0, array.get(headers2, c), text_color=color.white, bgcolor=color.new(color.purple, 15))',
        '    for i = 0 to array.size(trSide) - 1',
        '        isSell = array.get(trSide, i) == "SELL"',
        '        eX = array.get(trEntryX, i)',
        '        eY = array.get(trEntryY, i)',
        '        slY = array.get(trSL, i)',
        '        tpY = array.get(trTP, i)',
        '        box.new(eX, math.max(slY, eY), eX + boxRightOffset, math.min(slY, eY), border_color=color.red, border_width=1, bgcolor=color.new(color.red, 85), xloc=xloc.bar_time)',
        '        box.new(eX, math.max(eY, tpY), eX + boxRightOffset, math.min(eY, tpY), border_color=color.green, border_width=1, bgcolor=color.new(color.green, 85), xloc=xloc.bar_time)',
        '        label.new(eX, eY, (isSell ? "SELL STOP @ " : "BUY STOP @ ") + str.tostring(eY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=isSell ? label.style_label_up : label.style_label_down, color=color.blue, textcolor=color.white, size=size.small)',
        '        label.new(eX, slY, "SL " + str.tostring(slY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_left, color=color.red, textcolor=color.white, size=size.small)',
        '        label.new(eX, tpY, "TP " + str.tostring(tpY, format.mintick), xloc=xloc.bar_time, yloc=yloc.price, style=label.style_label_left, color=color.green, textcolor=color.white, size=size.small)',
        '        table.cell(trTable, 0, i + 1, array.get(trSide, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 1, i + 1, array.get(trEntryDisp, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 2, i + 1, array.get(trSlDisp, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 3, i + 1, array.get(trTpDisp, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 4, i + 1, str.tostring(array.get(trRPips, i), "#.#"), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 5, i + 1, array.get(trPoi, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 6, i + 1, array.get(trMfeMae, i), text_color=color.black, bgcolor=na)',
        '        table.cell(trTable, 7, i + 1, array.get(trNotes, i), text_color=color.black, bgcolor=na)',
    ]
    return lines


def find_parent_daily_poi(d_engine, side_bull: bool, child_impact_time: "datetime"):
    """The Daily POI that was 'active' (per mark_superseded_same_leg) at
    the moment a 4H/1H zone impacted -- the LATEST same-direction Daily
    POI whose own impact happened at/before child_impact_time and that
    hadn't yet been superseded by then. (None, None) if no such Daily
    POI exists (e.g. the child's own leg has no Daily-level driver
    impacted yet)."""
    candidates = []
    for zones, ptype in ((d_engine.ob_zones, "OB"), (d_engine.rb_zones, "RB"), (d_engine.fvg_zones, "FVG")):
        for dz in zones:
            if dz.bullish != side_bull or dz.impact_time is None or dz.impact_time > child_impact_time:
                continue
            sup = getattr(dz, "superseded_at", None)
            if sup is not None and sup <= child_impact_time:
                continue
            candidates.append((dz.impact_time, dz, ptype))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: c[0])
    _, dz, ptype = candidates[-1]
    return dz, ptype


def build_parent_column(engine, d_engine) -> list[str]:
    """User's correction (2026-09-29): no separate table -- ONE more
    column in the ALREADY existing shared ledger table. Row order here
    MUST match weekly_combined_generator.py's own ledger-table row
    construction exactly (its `_table_rows`/`all_rows`: OB+RB+FVG zones,
    excluding rejected, sorted by origin week/day descending), since
    this array is read row-for-row alongside tPoi/tId/etc -- not
    recomputed independently. `d_engine=None` means this call IS
    building the Daily engine's own column (Daily has no Daily-level
    parent of its own, every row is "-")."""
    all_rows = []
    for zones, left_of in ((engine.ob_zones, lambda z: z.candle),
                            (engine.rb_zones, lambda z: z.candle),
                            (engine.fvg_zones, lambda z: z.left)):
        for z in zones:
            if getattr(z, "rejected", False):
                continue
            all_rows.append((engine.w[left_of(z)].start, z))
    all_rows.sort(key=lambda pair: pair[0], reverse=True)

    if d_engine is None:
        return ["-" for _ in all_rows]
    out = []
    for _, z in all_rows:
        if z.impact_time is None:
            out.append("-")
            continue
        dz, dptype = find_parent_daily_poi(d_engine, z.bullish, z.impact_time)
        out.append(f"{dptype}#{dz.id}" if dz else "-")
    return out


def inject_parent_column(body_lines: list[str], tag: str) -> list[str]:
    """Adds the 'Daily Parent' column (index 11) to the shared ledger
    table this body already writes into -- widens this body's own
    table.clear() range and its own headers = array.from(...) line, and
    adds one more table.cell(...) call (reading {tag}_tParent) right
    after the existing Status column (index 10) in the per-row
    population loop. No new table."""
    header_re = re.compile(r'^(\s*)headers = array\.from\((.*)\)$')
    out = []
    for ln in body_lines:
        ln = ln.replace('table.clear(ledger, 0, 0, 10, 20)', 'table.clear(ledger, 0, 0, 11, 20)')
        m = header_re.match(ln)
        if m:
            ln = f'{m.group(1)}headers = array.from({m.group(2)}, "Daily Parent")'
        out.append(ln)
        if ln.strip().startswith(f'table.cell(ledger, 10, rowN, array.get({tag}_tStatus, i)'):
            indent = ln[:len(ln) - len(ln.lstrip())]
            out.append(f'{indent}table.cell(ledger, 11, rowN, array.get({tag}_tParent, i), '
                        'text_color=color.black, bgcolor=na)')
    return out


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


_IMPACT_COLOR_BY_TAG = {"d": "color.red", "h4": "color.green", "h1": "color.green"}


def inject_input_params(body_lines: list[str], tag: str) -> list[str]:
    """f_drawPoiBox is a shared function (defined ONCE in the header,
    reused by weekly/daily's own standalone viewers too -- left
    untouched there) that used to read sideFilter/inspectOnePoi/
    focusPoi/poiFromLast as free global variables. Now that each
    timeframe has its OWN copy of those 4 (see build_own_inputs), the
    shared function can't close over a single global any more -- they
    have to be passed in as real parameters at each call site instead.
    Also appends the impact-line color (2026-09-29: the user wants
    Daily's own impact lines red, 4H/1H's green -- a fixed per-timeframe
    literal, not a user setting, so it's baked in here rather than in
    build_own_inputs). Only touches lines that literally start with
    'f_drawPoiBox(' (the 3 calls per timeframe body); the function
    DEFINITION itself is patched once, separately, in main()."""
    extra = (f"{tag}_sideFilter, {tag}_inspectOnePoi, {tag}_focusPoi, {tag}_poiFromLast, "
             f"{tag}_countFromStart, {_IMPACT_COLOR_BY_TAG[tag]}")
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


def extract_poibox_block(body_lines: list[str], on_name: str) -> list[str]:
    """Pulls out just the POI-box drawing section (the bare `if {on_name}`
    block that calls f_drawPoiBox 3 times) from an already-built
    per-timeframe body -- NOT the swing/MSS label block before it (that
    one's own gate line has ` and array.size(...)` appended, so it never
    matches the bare form here), and NOT the ledger-table block after it
    (that one clears and repopulates the single shared `ledger` table,
    and must stay owned by exactly one timeframe's own chart at a time,
    never duplicated onto a projection). There are exactly two bare
    `if {on_name}` lines in the generated template -- box-draw, then
    table -- so the first-to-second span is exactly the box-draw block."""
    bare = f"if {on_name}"
    idxs = [i for i, ln in enumerate(body_lines) if ln.strip() == bare]
    if len(idxs) < 2:
        raise ValueError(f"expected 2 bare '{bare}' lines (box-draw, table) in body, found {len(idxs)}")
    return body_lines[idxs[0]:idxs[1]]


def project_poibox_block(block_lines: list[str], source_gate: str, source_tag: str,
                          target_gate: str, settings_tag: str) -> list[str]:
    """Re-shows a timeframe's own already-drawn POI boxes on a DIFFERENT
    chart -- e.g. 4H's own OB/RB/FVG boxes also on the 5m chart, or 1H's
    own also on the 5m chart -- so the higher-timeframe POI a trade is
    actually being taken from is visible without switching charts.
    Reuses the SAME already-declared data arrays as-is (Pine allows
    reading an array from a second draw call; no redeclaration needed),
    but swaps the gate to the target chart and the 5 filter inputs to an
    INDEPENDENT settings group -- so toggling Side/Inspect-one/etc. for
    this projected view never silently also changes the source
    timeframe's own chart, same reasoning that gave Daily/4H/1H each
    their own settings in the first place."""
    text = "\n".join(block_lines)
    text = re.sub(rf'^(\s*)if {re.escape(source_gate)}$', rf'\1if {target_gate}', text, flags=re.MULTILINE)
    for name in sorted(_SHARED_INPUT_NAMES, key=len, reverse=True):
        text = re.sub(rf'\b{source_tag}_{name}\b', f'{settings_tag}_{name}', text)
    return ["if barstate.islast"] + text.split("\n")


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
        # Sunday data in this CSV is not real trading (user's own call,
        # 2026-09-29: "there is no 11 Jan... maybe we have Sunday gap
        # data in the CSV but it is fake") -- stripped unconditionally,
        # everywhere, before any aggregation/swing/POI/entry logic ever
        # sees it. Judged by the display timezone's own calendar day
        # (Riyadh), same clock the rest of this tool already uses.
        sunday_count = sum(1 for x in minutes if x.t.astimezone(display_tz).weekday() == 6)
        if sunday_count:
            minutes = [x for x in minutes if x.t.astimezone(display_tz).weekday() != 6]
            print(f"Dropped {sunday_count} Sunday minutes (not real trading data)")
        # Auto-detect --show-date/--as-of/--since so the SAME command
        # runs every day forever, no hand-edit needed (user, 2026-09-29:
        # "let the python code handle any change"). "Today" can NOT be
        # guessed from the CSV's own last date -- tried that first, and
        # it picked up September data this CSV carries far past the
        # real campaign (started 2026-01-12), feeding the engine 9
        # months it was never meant to see and overflowing Pine's own
        # string-literal limit (real crash, caught by the user: "String
        # is too long"). So "today" is instead read from a tiny marker
        # file you maintain by hand -- one line, one date, nothing else
        # to type -- TODAY.txt next to the outputs. Same command every
        # day; only that one file's single line ever changes.
        today_marker = base / "TODAY.txt"
        show_date_from_marker = False
        if not args.show_date:
            show_date_from_marker = True
            if today_marker.exists():
                args.show_date = today_marker.read_text().strip()
            else:
                today_marker.write_text("2026-01-14")
                print(f"No --show-date given and no {today_marker.name} found -- created "
                      f"it with 2026-01-14 (your last known trading day) as a starting "
                      f"point. Edit that ONE file to today's date each day and re-run "
                      f"this exact same command -- or pass --show-date yourself.",
                      file=sys.stderr)
                return 2
        if not args.as_of:
            args.as_of = args.show_date

        if args.as_of:
            y, m, d = (int(x) for x in args.as_of.split("-"))
            cutoff_local = datetime(y, m, d, 23, 59, 59, tzinfo=display_tz) + timedelta(seconds=1)
            cutoff_utc = cutoff_local.astimezone(UTC)
            minutes = [x for x in minutes if x.t < cutoff_utc]
            if not minutes:
                print(f"No data at or before {args.as_of}", file=sys.stderr)
                return 2

        # --since can NOT default to "the earliest date in the CSV"
        # either, for the same reason (this CSV carries history from
        # before the campaign started) -- pinned instead the first time
        # this ever runs with no --since given, to a small marker file
        # (dailies_since.txt), then read back from it on every later
        # run: exactly "keep --since fixed at your very first traded
        # day," automatic instead of hand-typed. Delete that file (or
        # pass --since yourself) to reset the campaign start.
        since_marker = base / "dailies_since.txt"
        if not args.since and since_marker.exists():
            args.since = since_marker.read_text().strip()
        if not args.since:
            args.since = args.show_date
        if not since_marker.exists() or since_marker.read_text().strip() != args.since:
            since_marker.write_text(args.since)
        today_src = today_marker.name if show_date_from_marker else "--show-date"
        print(f"--since {args.since} --show-date {args.show_date} "
              f"(today from {today_src}, since pinned in {since_marker.name})")

        # display_tz passed through so aggregate_days/aggregate_hours can
        # fold the leftover hour after a stripped Sunday into the
        # following real day's candle instead of building a fake stub
        # candle from it (2026-09-29, user: "you are using Sunday data
        # right. check the 3rd candle" -- verified: it was).
        bars_by_tag = {
            "d": dc.aggregate_days(minutes, close_tz, args.day_close_hour, display_tz),
            "h4": dc.aggregate_hours(minutes, 4, close_tz, args.day_close_hour, display_tz),
            "h1": dc.aggregate_hours(minutes, 1, close_tz, args.day_close_hour, display_tz),
        }

        mt_all = [m.t for m in minutes]

        # --since widens --show-date into a continuous multi-day range
        # (2026-09-29, user's own words: "day 13 is with day 12" -- one
        # day in a vacuum is not how this is actually traded). Defaults
        # to --show-date itself, i.e. the exact single-day behavior this
        # always had, when --since is omitted.
        since_date = args.since or args.show_date

        engines = {}
        raw_lines = {}
        d_zones_full = None  # snapshot of Daily's zone lists BEFORE date-filtering truncates them (see below)
        tf_full = {}  # h4/h1 full (pre-date-filter) engine snapshots -- see compute_5m_trades' own docstring
        for tag, tf_period, title in TIMEFRAMES:
            engine = wc.WeeklyCombinedEngine(minutes, bars_by_tag[tag])
            engine.run()
            mark_open_inside_trigger(engine)
            mark_superseded_same_leg(engine, minutes, mt_all)
            if tag in ("h4", "h1"):
                exclude_old_intraday_zones(engine)
                # Full (unfiltered) snapshot for compute_5m_trades' own
                # candidate search -- a POI impacted on a PRIOR day but
                # still alive today (the "react day" case) must still be
                # considered, which filter_to_date_range() below would
                # otherwise silently drop entirely (2026-09-29).
                tf_full[tag] = SimpleNamespace(ob_zones=list(engine.ob_zones), rb_zones=list(engine.rb_zones),
                                                fvg_zones=list(engine.fvg_zones), events=engine.events, w=engine.w)
            if tag == "d":
                # A Daily POI from a PRIOR day can still be the active
                # parent today (2026-09-29 -- "react day" case: FVG#1
                # impacted 12 Jan, still alive and in control on 13 Jan,
                # yet 13 Jan's own Daily engine has zero same-day events
                # of its own). filter_to_calendar_range() below only keeps
                # zones with a lifecycle event ON args.show_date, so it
                # would otherwise silently drop FVG#1 from the parent
                # search entirely. Snapshot the full (pre-filter) zone
                # lists here -- the Zone objects themselves aren't
                # mutated by filtering, only which ones the engine's own
                # list still references -- and hand the snapshot to
                # find_parent_daily_poi() instead of the filtered engine.
                d_zones_full = SimpleNamespace(ob_zones=list(engine.ob_zones), rb_zones=list(engine.rb_zones),
                                                fvg_zones=list(engine.fvg_zones))
            # Daily is never --since-FLOOR-scoped here (2026-09-29, user:
            # "I want all... all the POIs, swings, MSS and everything...
            # by using the focus toggle" -- --since scoping makes sense
            # for 1H/4H, which are real per-day trading-session windows,
            # not for Daily). It IS still capped at the --as-of/--show-
            # date CEILING like everything else, though -- an attempt to
            # remove that too (full_minutes, an unbounded second Daily
            # engine) made the combined script cross a real Pine compile
            # limit ("main body too long," CE10295 -- confirmed with the
            # user's own TradingView error, confirmed again even after
            # a first fix attempt) once Daily carries a whole multi-
            # month dataset's worth of POIs alongside 4H/1H/5m in the
            # SAME file. Reverted -- see daily_full_dataset_viewer.pine
            # (a genuinely separate script, generated on request) for a
            # full-history, no-"today"-cap Daily view instead; this
            # combined script's own Daily body stays capped at --show-
            # date, same as 1H/4H always were.
            if args.show_date and tag != "d":
                filter_to_date_range(engine, since_date, args.show_date, display_tz)
            engines[tag] = engine
            raw_lines[tag] = build_one(base, engine, args, display_tz, tag)

        trades = []
        e5 = None
        ledger_rows = []
        if args.show_date:
            bars5 = dc.aggregate_minutes(minutes, 5)
            e5 = wc.WeeklyCombinedEngine(minutes, bars5)
            e5.run()
            window_start, _ = trading_window(since_date, display_tz)
            _, window_end = trading_window(args.show_date, display_tz)

            # "React day" rule (user, 2026-09-29): once today sweeps the
            # previous day's relevant extreme (the low for a SELL bias,
            # the high for a BUY bias), 1H setups are abandoned for the
            # rest of the day and only 4H stays in play. Only applies on
            # an actual react day -- never the impact day itself (see
            # is_react_day's own docstring for the real bug this fixed).
            h1_abandon_at = None
            if is_react_day(d_zones_full, args.default_side, args.show_date, display_tz):
                prev_extreme = find_prev_day_extreme(minutes, mt_all, args.show_date, display_tz, args.default_side)
                h1_abandon_at = find_prev_day_sweep_time(minutes, mt_all, args.show_date, display_tz,
                                                           args.default_side, prev_extreme)

            trades, ledger_rows = compute_5m_trades(tf_full["h4"], tf_full["h1"], e5, minutes,
                                                      window_start, window_end, display_tz,
                                                      side=args.default_side, h1_abandon_at=h1_abandon_at)

        # Header: identical across all three except title/onWeekly/maxval --
        # take it from "d", split at the first body-only line.
        d_lines = raw_lines["d"]
        split_idx = next(i for i, ln in enumerate(d_lines) if ln.strip() == SPLIT_MARKER)
        header = d_lines[:split_idx]

        header = [ln.replace(
            'indicator("FXCM Weekly OB+RB+FVG Combined - Python Reference"',
            'indicator("Dhagax Dailies -- Daily+4H+1H OB+RB+FVG Combined"',
        ).replace(
            # One more shared-ledger-table column: "Daily Parent" (see
            # build_parent_column/inject_parent_column) -- NOT a new
            # table, the same one every body already writes into.
            'table.new(position.top_right, 11,', 'table.new(position.top_right, 12,',
        ) for ln in header]

        # Pull the 5 Combined-settings inputs OUT of the shared header --
        # each timeframe gets its own copy (see build_own_inputs), not one
        # set shared across Daily/4H/1H (user caught this: toggling Side on
        # the 1H chart was silently also changing what Daily/4H would show).
        input_line_prefixes = ('string focusPoi', 'bool inspectOnePoi', 'bool countFromStart',
                                'string sideFilter', 'int poiFromLast')
        shared_input_lines = [ln for ln in header if ln.strip().startswith(input_line_prefixes)]
        header = [ln for ln in header if not ln.strip().startswith(input_line_prefixes)]

        # Replace the single-purpose timeframe bools with the 4 real ones
        # this file actually uses (onD/onH4/onH1/onFive) -- drop on1m,
        # leftover from a different, unused 1m concept. onFive is real now:
        # 4H/1H POIs project onto the 5m chart (see project_poibox_block),
        # and the 5m trades table (build_trades_pine) also gates on it.
        new_header = []
        for ln in header:
            if ln.strip().startswith('bool onWeekly = timeframe.period =='):
                new_header.append('bool onD = timeframe.period == "1D"')
                new_header.append('bool onH4 = timeframe.period == "240"')
                new_header.append('bool onH1 = timeframe.period == "60"')
                new_header.append('bool onFive = timeframe.period == "5"')
            elif ln.strip().startswith('bool onH4 = timeframe.period ==') or \
                 ln.strip().startswith('bool onFive = timeframe.period ==') or \
                 ln.strip().startswith('bool on1m = timeframe.period =='):
                continue
            else:
                new_header.append(ln)
        header = new_header

        # Cross-timeframe context (2026-09-28, corrected 2026-09-29): "the
        # daily FVG we are trading from" should be visible on 4H/1H, and
        # "the 1H OB/RB we are trading from" on 5m -- but ONLY the POI
        # boxes and impact lines, never the swing points/MSS labels of
        # the source timeframe (user's own correction: "we transfer the
        # POIs and impact lines only to any other timeframe we decide...
        # even the 1h and 4h swing points and MSSs can never be
        # transferred to 5m"). The first attempt widened Daily's ENTIRE
        # gate (swing/MSS block included, via regate()) to also fire on
        # 4H/1H -- wrong, it put Daily's own swing dots and MSS labels on
        # the 4H/1H charts too. Every body now stays fully NATIVE-gated
        # (onD/onH4/onH1 only); cross-timeframe POI display is built
        # SEPARATELY below via extract_poibox_block/project_poibox_block
        # -- the same mechanism 4H/1H-onto-5m already used correctly.
        gate_by_tag = {"d": "onD", "h4": "onH4", "h1": "onH1"}

        bodies = []
        own_maxvals = {}
        for tag, tf_period, title in TIMEFRAMES:
            own_maxval = extract_maxval(raw_lines[tag][:split_idx])
            own_maxvals[tag] = own_maxval
            own_inputs = build_own_inputs(shared_input_lines, tag, title, own_maxval, args.default_side)
            # Daily-parent-POI column (2026-09-29, user's own words: "we
            # want the daily parent POI ID to appear in the already
            # established 1h table, nowhere else, no new table") -- one
            # more packed array, generic-named like every other one here
            # so rename_arrays tag-prefixes it the same way; row order
            # matches build_parent_column()'s own docstring exactly.
            # Declared BEFORE the rest of the body, not appended after it
            # -- the table-population loop that reads {tag}_tParent lives
            # INSIDE raw_lines[tag], earlier in file order than wherever
            # an appended-at-the-end pack block would land, which is
            # exactly the CE10272 "undeclared identifier" the user hit:
            # Pine executes top-to-bottom, so a `var array` declared
            # after its own first read doesn't exist yet at that point.
            parent_col = build_parent_column(engines[tag], None if tag == "d" else d_zones_full)
            body = own_inputs + wc.wrb.pack_array("tParent", "string", parent_col) + raw_lines[tag][split_idx:]
            body = rename_arrays(body, tag)
            body = inject_input_params(body, tag)
            body = regate(body, gate_by_tag[tag])
            body = collapse_pack_blocks(body)
            body = inject_parent_column(body, tag)
            bodies.append(body)

        # 5m's own settings group ("just like other timeframes have") --
        # controls the projected 4H+1H POI boxes shown on the 5m chart,
        # independent of 4H's/1H's own settings. maxval covers whichever
        # source has more zones, since one group filters both projections.
        m5_maxval = max(own_maxvals["h4"], own_maxvals["h1"])
        m5_inputs = build_own_inputs(shared_input_lines, "m5", "5m", m5_maxval, args.default_side)

        # Project 4H's and 1H's own POI boxes onto the 5m chart, reusing
        # their already-built (renamed, gated) bodies' data arrays as-is.
        h4_body, h1_body = bodies[1], bodies[2]
        h4_on5 = project_poibox_block(extract_poibox_block(h4_body, "onH4"), "onH4", "h4", "onFive", "m5")
        h1_on5 = project_poibox_block(extract_poibox_block(h1_body, "onH1"), "onH1", "h1", "onFive", "m5")

        # Project Daily's own POI boxes onto 4H and 1H -- same mechanism,
        # but reusing Daily's OWN settings group (settings_tag="d" ==
        # source_tag, so project_poibox_block's input re-tagging is a
        # no-op): unlike the 4H/1H-onto-5m projection, this one was
        # already explicitly decided to need no separate settings group
        # (same POI data, Daily's own Side/Focus/etc. already govern it
        # regardless of which chart is open) -- just the swing/MSS labels
        # that must never come along, which the native-only gate_by_tag
        # above now guarantees.
        d_body = bodies[0]
        d_on4 = project_poibox_block(extract_poibox_block(d_body, "onD"), "onD", "d", "onH4", "d")
        d_on1 = project_poibox_block(extract_poibox_block(d_body, "onD"), "onD", "d", "onH1", "d")

        # Patch the shared f_drawPoiBox definition to take the 4 inputs as
        # real parameters instead of closing over a single global set (see
        # inject_input_params -- every call site already passes them now).
        header = [
            ln.replace(
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, sideGTotalBuy, sideGTotalSell, dashed, filled) =>',
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, sideGTotalBuy, sideGTotalSell, dashed, filled, sideFilterP, inspectOnePoiP, focusPoiP, poiFromLastP, countFromStartP, impactColorP) =>',
            ).replace(
                'line.new(boxRight, array.get(bottom, i), boxRight, array.get(top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)',
                'line.new(boxRight, array.get(bottom, i), boxRight, array.get(top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(impactColorP, 30), width=1)',
            ).replace(
                'effRank = countFromStart ? total - array.get(rank, i) + 1 : array.get(rank, i)',
                'effRank = countFromStartP ? total - array.get(rank, i) + 1 : array.get(rank, i)',
            ).replace(
                'sideGTotal = sideFilter == "BUY" ? sideGTotalBuy : sideFilter == "SELL" ? sideGTotalSell : gTotal',
                'sideGTotal = sideFilterP == "BUY" ? sideGTotalBuy : sideFilterP == "SELL" ? sideGTotalSell : gTotal',
            ).replace(
                'effGRank = countFromStart ? sideGTotal - (sideFilter == "ALL" ? realGRank : realSideGRank) + 1 : (sideFilter == "ALL" ? realGRank : realSideGRank)',
                'effGRank = countFromStartP ? sideGTotal - (sideFilterP == "ALL" ? realGRank : realSideGRank) + 1 : (sideFilterP == "ALL" ? realGRank : realSideGRank)',
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
        final_lines = header + m5_inputs
        for body in bodies:
            final_lines += body
        final_lines += h4_on5 + h1_on5 + d_on4 + d_on1
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

        if args.show_date and e5 is not None:
            ledger_name = "5m_trades_ledger.csv"
            write_5m_trades_ledger(base, ledger_rows, ledger_name)
            print(f"  {ledger_name}   ({len(ledger_rows)} rows: every 5m attempt on every "
                  f"qualifying POI that day, entered or not, with its stage/reason)")

            # 5m swings/report audit files, same convention as d/h4/h1 above --
            # scoped to the same trading-window+carry-in filter AFTER trades
            # are computed (compute_5m_trades needs e5's FULL event history
            # for correct resting/candidate lookups; the audit files don't).
            filter_to_date_range(e5, since_date, args.show_date, display_tz)
            swings5_name, report5_name = "5m_tf_swings.csv", "5m_tf_report.txt"
            dc.write_swings_csv(base, e5, display_tz, swings5_name)
            dc.write_report(base, minutes, bars5, e5, display_tz, report5_name,
                             label="5m", bar_word="5m_bars")
            print(f"  {swings5_name} / {report5_name}   (5m swings/MSS used by the trade engine that day)")

        if warnings:
            print(f"({len(warnings)} data warnings -- see load_minutes output)")
        return 0
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
