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

# Item #25 (2026-10-07, user-requested): any SL-hit trade whose SL distance
# (entry to SL price) is this many pips or less gets an "instant-stop"
# structural note -- a tracked category, not a new trading rule.
INSTANT_STOP_THRESHOLD_PIPS = 2.0

# Item #10 (2026-10-07/08): the premium/discount-region mechanism in
# run_5m_bso_premium(). RE-ENABLED 2026-10-08 (user's own explicit
# instruction) WITHOUT a proven real-world validating case on 2025 data --
# three implementations were tried and none was shown to change an
# outcome on the 19 known pre-session-impacted 2025 zones (full history
# in DAILIES_LEARNING_LOG.txt). Per the user's instruction, every trade
# this mechanism touches now carries a diagnostic `item10_note` in its
# structural_notes -- a direct, computed comparison against what the
# ordinary mechanism alone would have produced for that same zone -- so
# every real case across the full 2008-2026 backtest is visible and
# auditable, not silently trusted. Treat this as an EXPERIMENTAL, watched
# mechanism, not a settled fix, until real cases accumulate across the
# wider dataset.
ITEM10_ENABLED = True

# Item #10's real gate (2026-10-08, user's own figure, open to adjustment):
# the max acceptable SL size (pips) for a premium/discount-region entry
# candidate, measured against the real extreme since impact (`mark`). A
# candidate that would need a bigger SL than this to cover the extreme is
# skipped -- wait for a closer one instead of chasing an oversized-risk
# entry. See run_5m_bso_premium()'s own docstring for the full derivation.
PREMIUM_MAX_SL_PIPS = 15.0


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
                         "that day -- 10:00-19:00 Riyadh in summer, 11:00-20:00 in winter "
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
    """User's real trading window (2026-09-30, corrected from an earlier
    2026-09-28 guess): 10:00-19:00 Riyadh in summer, 11:00-20:00 in
    winter -- London open through New York's OWN session close, not an
    hour past it. Fixed after the user gave the exact session hours
    (Riyadh): Asia 03:00-07:00 summer/04:00-08:00 winter, London
    10:00-14:00 summer/11:00-15:00 winter, New York 15:00-19:00 summer/
    16:00-20:00 winter -- the old end times (20:00 summer/21:00 winter)
    were a full hour past New York's own close (19:00/20:00) and were
    never actually verified against these real hours. Asia excluded
    (liquidity-grab-only, never an entry window, per the earlier
    session rules). Summer/winter is detected from whether New York is
    actually in DST that day (via zoneinfo's real, year-accurate
    transition data), not a hardcoded month range -- the whole reason
    these hours shift on the Riyadh clock in the first place is NY/
    London's own DST, so that's the correct thing to check, not a guess
    at "November to March.\""""
    y, m, d = (int(x) for x in date_str.split("-"))
    ny_noon = datetime(y, m, d, 12, tzinfo=ZoneInfo("America/New_York"))
    is_summer = ny_noon.dst() != timedelta(0)
    start_h, end_h = (10, 19) if is_summer else (11, 20)
    start = datetime(y, m, d, start_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    end = datetime(y, m, d, end_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    return start, end


def after_week_open(t: "datetime", display_tz: ZoneInfo) -> bool:
    """Is `t` real trading-week data -- at or after the real forex week
    open AND at or before the real forex week close (2026-10-05/2026-10-07,
    both user-stated rules, replacing the old blanket "drop all Riyadh-
    weekend" filter): week opens Riyadh Monday 01:00 winter / 00:00
    summer, closes Riyadh Friday 00:59 winter / 23:59 summer -- NOT a
    tick-count/liquidity heuristic (that risks silently deleting real-
    but-thin data, which the user explicitly does not want) and NOT a
    Riyadh-calendar-day check on its own.

    OPEN side (2026-10-05): the old weekday()!=6 filter correctly dropped
    all of Riyadh-Sunday but missed a leftover hour in the winter case:
    Riyadh Monday 00:00-00:59 already reads as "Monday" on the calendar
    but is still before the real 01:00 open, so it slipped through
    unfiltered -- confirmed via real tick counts (2025-02-02/03: single
    digits through 22:59 UTC, jumping to 400-700+ ticks/min right at
    23:00 UTC = Riyadh Monday 02:00, with the official 01:00-02:00 Riyadh
    hour itself still thin but genuinely part of the real week, kept
    here regardless of how thin it looks).

    CLOSE side (2026-10-07, caught on 2025-01-06's PDH/PDL react-day
    chain): the week's real close is the SAME boundary the Daily engine's
    own NY-anchored "Friday" candle already closes on elsewhere in the
    code (forex_day_bounds -- Friday 01:00 Riyadh winter through Saturday
    01:00 Riyadh winter / 00:00 through 00:00 summer), not Riyadh calendar
    midnight. In winter this means real trading data genuinely continues
    into Riyadh Saturday 00:00-00:59 (the tail of Friday's own NY session)
    and must be kept, not blanket-stripped as "Saturday" -- confirmed
    directly in the raw CSV: the real week high for 2025-01-03
    (1.03096) lands at Sat 2025-01-04 00:09 Riyadh, inside this window.
    In summer the week already closes at Friday 23:59, so all of Saturday
    is correctly stripped either way -- no change there. Sunday is always
    fully between weeks in both seasons.

    Same DST detection as trading_window(), so both boundaries shift the
    same way the trading window itself does."""
    local = t.astimezone(display_tz)
    wd = local.weekday()  # Mon=0 ... Sun=6
    if wd == 6:
        return False  # all of Riyadh Sunday is always between weeks
    ny_noon = datetime(local.year, local.month, local.day, 12, tzinfo=ZoneInfo("America/New_York"))
    is_summer = ny_noon.dst() != timedelta(0)
    if wd == 5:
        if is_summer:
            return False  # week already closed Friday 23:59 summer
        return local.hour < 1  # winter: real Friday session tail, keep through 00:59
    if wd == 0:
        open_hour = 0 if is_summer else 1
        if local.hour < open_hour:
            return False
    return True


def strip_pre_week_open(minutes: list, display_tz: ZoneInfo) -> tuple[list, int]:
    """Drop every minute outside the real trading week -- before the real
    open or after the real close (see after_week_open() for the exact
    rule and why). Returns (kept_minutes, dropped_count)."""
    kept = [x for x in minutes if after_week_open(x.t, display_tz)]
    return kept, len(minutes) - len(kept)


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
    chain's own search has been running for.

    Also excludes the London/New York handover hour (2026-10-05, user:
    "a 1h break between London and New York in the winter, we do not
    trade that hour whatsoever" -- real trade caught entering at 15:42
    Riyadh on 2025-02-13, squarely inside it). Per _SESSION_HOURS:
    London ends at 14/15 (summer/winter), New York starts at 15/16 --
    so the gap is 14:00-15:00 Riyadh summer, 15:00-16:00 winter. Entries
    only -- control/impact/origin timing is untouched, same as how Asia
    exclusion only ever gated entries, never bias.

    EXPERIMENT RUN AND REVERTED (2026-10-07): the user asked, separately,
    to try removing this handover-hour block entirely ("consider it part
    of London, like fifth hour... I want to see the performance of that
    hour") -- run in ISOLATION this session (see DAILIES_LEARNING_LOG.txt
    for the standalone results) and explicitly NOT applied here: the user
    has not yet decided whether to keep it, so the committed code keeps
    the original hard block below, unchanged from the 2026-10-05 fix."""
    date_str = t.astimezone(display_tz).date().isoformat()
    win_start, win_end = trading_window(date_str, display_tz)
    if not (win_start <= t < win_end):
        return False
    is_summer = _is_summer_ny(date_str)
    london_end, ny_start = (14, 15) if is_summer else (15, 16)
    local_hour = t.astimezone(display_tz).hour
    if london_end <= local_hour < ny_start:
        return False
    return True


# Exact session hours (user, 2026-09-30, "never forget it, never" --
# Riyadh clock). Asia is liquidity-grab-only (see trading_window());
# London/New York are the two real entry sessions the sweep rule below
# actually gates.
_SESSION_HOURS = {
    True:  {"ASIA": (3, 7), "LONDON": (10, 14), "NEWYORK": (15, 19)},   # summer
    False: {"ASIA": (4, 8), "LONDON": (11, 15), "NEWYORK": (16, 20)},   # winter
}


def _is_summer_ny(date_str: str) -> bool:
    y, m, d = (int(x) for x in date_str.split("-"))
    ny_noon = datetime(y, m, d, 12, tzinfo=ZoneInfo("America/New_York"))
    return ny_noon.dst() != timedelta(0)


def _session_bounds(date_str: str, name: str, display_tz: ZoneInfo) -> tuple["datetime", "datetime"]:
    y, m, d = (int(x) for x in date_str.split("-"))
    start_h, end_h = _SESSION_HOURS[_is_summer_ny(date_str)][name]
    start = datetime(y, m, d, start_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    end = datetime(y, m, d, end_h, 0, 0, tzinfo=display_tz).astimezone(UTC)
    return start, end


def session_of(t: "datetime", display_tz: ZoneInfo) -> str | None:
    """Which of Asia/London/New York (or neither -- an off-hours minute)
    `t` falls in, on its own calendar day."""
    lt = t.astimezone(display_tz)
    date_str = lt.date().isoformat()
    hrs = _SESSION_HOURS[_is_summer_ny(date_str)]
    for name, (sh, eh) in hrs.items():
        if sh <= lt.hour < eh:
            return name
    return None


def _swept_between(mt: list, minutes, t0: "datetime", t1: "datetime", level: float | None, bull: bool) -> bool:
    """Did price cross `level` (the opposing direction's liquidity --
    a LOW for a buy setup, a HIGH for a sell setup) anywhere in
    [t0, t1)? None `level` (session never traded, e.g. no data yet)
    means "nothing to sweep," never satisfied."""
    if level is None or t0 >= t1:
        return False
    i0, i1 = bisect_left(mt, t0), bisect_left(mt, t1)
    for i in range(i0, i1):
        m = minutes[i]
        if (m.l < level) if bull else (m.h > level):
            return True
    return False


def session_sweep_satisfied(hunt_time: "datetime", bull: bool, minutes, mt: list, display_tz: ZoneInfo) -> bool:
    """User's rule (2026-09-30): trading in London or New York requires
    the PRIOR session's own liquidity to have been swept first.

    SELL example (BUY is the exact mirror -- lows instead of highs):
    to trade in London, price must have traded above the Asian session's
    own high at least once between Asian close and `hunt_time` (the
    moment we're looking for a 5m entry candidate). To trade in New
    York, price must likewise have traded above LONDON's own high
    between London close and `hunt_time` -- UNLESS Asian high was
    already swept at any point between Asian close and London's own
    close, in which case that ONE sweep satisfies both sessions and New
    York needs no separate sweep of its own.

    Only London/New York minutes are gated at all -- Asia itself is
    already excluded as an entry session entirely (in_trading_window),
    and this rule has nothing to say about a minute in neither."""
    sess = session_of(hunt_time, display_tz)
    if sess not in ("LONDON", "NEWYORK"):
        return True
    date_str = hunt_time.astimezone(display_tz).date().isoformat()
    asia_start, asia_end = _session_bounds(date_str, "ASIA", display_tz)
    london_start, london_end = _session_bounds(date_str, "LONDON", display_tz)
    asia_level = _minutes_extreme(mt, minutes, asia_start, asia_end, bull)
    if sess == "LONDON":
        return _swept_between(mt, minutes, asia_end, hunt_time, asia_level, bull)
    # NEWYORK: the Asian sweep, if it already happened by London's own
    # close, covers New York too -- no separate London sweep required.
    if _swept_between(mt, minutes, asia_end, london_end, asia_level, bull):
        return True
    london_level = _minutes_extreme(mt, minutes, london_start, london_end, bull)
    return _swept_between(mt, minutes, london_end, hunt_time, london_level, bull)


def _minutes_extreme(mt: list, minutes, t0: "datetime", t1: "datetime", bull: bool) -> float | None:
    """The session's own opposing-direction extreme (the LOW for a buy
    setup's mirror-check, the HIGH for a sell setup) -- None if the
    session has no data at all yet (nothing to sweep)."""
    i0, i1 = bisect_left(mt, t0), bisect_left(mt, t1)
    if i0 >= i1:
        return None
    seg = minutes[i0:i1]
    return (min(m.l for m in seg) if bull else max(m.h for m in seg))


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
    engine.vi_zones = [z for z in engine.vi_zones if happened_in_window(engine.w[z.left].start, z)]


def filter_to_date_range(engine, since_str: str, until_str: str, display_tz: ZoneInfo) -> None:
    """H4/1H scoping across one or more consecutive trading days
    (2026-09-29, user's own words: "day 13 is with day 12" -- a single
    day shown in a vacuum is not how this system is actually traded:
    every new day carries forward what's still alive from the ones
    before it, and the chart should too). ONE real trading window
    (10:00-19:00 / 11:00-20:00 Riyadh, see trading_window()) PER DAY in
    the range -- not the whole calendar day, and not one span bridging
    every night in between (see filter_to_windows()). `since_str` is the
    FIRST day, `until_str` (== --show-date) is the LAST -- when they're
    the same day (--since omitted) this is exactly the single-day window
    it always was."""
    windows = [trading_window(d, display_tz) for d in _dates_between(since_str, until_str)]
    filter_to_windows(engine, windows)


def filter_to_calendar_span(engine, since_str: str, until_str: str, display_tz: ZoneInfo) -> None:
    """4H-only fix (2026-09-30). filter_to_windows()/filter_to_date_range()
    keep only what lands inside the real trading windows, one
    discontinuous window per day -- correct for 1H (too many POIs to
    show them all, and the user asked for exactly this restriction on
    1H by name). Applying the SAME discontinuous filter to 4H silently
    dropped real, confirmed swings and MSS whenever their confirm time
    fell outside a window (pre-window Asia hours, or the evening/
    overnight candles) -- caught by the user two ways in one message:
    (a) 14 Jan had ZERO swings/MSS shown at all (both its real swing
    low 05:00 and swing high 21:00 landed outside window hours); (b)
    16 Jan's real MSS_UP (09:00, 1.16138) was missing entirely, and
    RB#22 -- the 4H POI that actually produced 3 real entries that day
    -- never showed as a box or table row at all, because its origin
    (15 Jan 21:00), trigger (16 Jan 03:49) and impact (16 Jan 05:34)
    all happen to fall before that day's 11:00 window open. The zone
    still produced real trades (compute_5m_trades searches the FULL
    unfiltered snapshot, not the display-filtered one) -- the display
    just never caught up, which is exactly backwards.

    User's own words: "I simply want the 4H engine to be there
    correctly from the beginning of day 12 to end of day 16" -- i.e.
    4H needs the FULL continuous calendar-day span (--since 00:00
    through --show-date 24:00 Riyadh), same idea as Daily's own
    unrestricted treatment, not the 1H-style discontinuous window
    filter. Only 4H switches to this function; 1H keeps
    filter_to_date_range()/filter_to_windows() exactly as before --
    the user's complaint and fix request were both 4H-specific."""
    win_start, _ = calendar_day_bounds(since_str, display_tz)
    _, win_end = calendar_day_bounds(until_str, display_tz)
    filter_to_windows(engine, [(win_start, win_end)])


def calendar_day_bounds(date_str: str, display_tz: ZoneInfo) -> tuple["datetime", "datetime"]:
    """The same full 00:00-24:00 Riyadh calendar day filter_to_calendar_range()
    uses, factored out so the "react day" checks below (which need
    today's own calendar-day bounds, not the narrow trading window) share
    the exact same definition of "today" instead of a second copy."""
    y, m, d = (int(x) for x in date_str.split("-"))
    win_start = datetime(y, m, d, 0, 0, 0, tzinfo=display_tz).astimezone(UTC)
    return win_start, win_start + timedelta(days=1)


def forex_day_bounds(date_str: str, display_tz: ZoneInfo) -> tuple["datetime", "datetime"]:
    """Like calendar_day_bounds() above, but anchored to the forex
    trading day (NY 17:00 close = Riyadh 01:00 winter / 00:00 summer)
    instead of Riyadh calendar midnight -- the SAME day definition the
    Daily engine's own bars already use everywhere else (dc.aggregate_
    days, forex_day_start). Used specifically by the PDH/PDL react-day
    chain below (2026-10-06, user-taught, caught on 2025-01-06): the
    old calendar-midnight bounds computed "yesterday's high" over the
    wrong hour range, giving a PDH level that real price swept through
    hours earlier than the true one -- confirmed on real 1-minute data:
    the calendar-midnight PDH (1.03072) was swept at 02:46, but the
    real Daily-bar PDH (1.03096, the same high the Daily engine's own
    zones/swings already use) wasn't swept until 04:15. The 2026-09-29
    fix (see find_prev_day_extreme below) correctly picked the right
    DAY; this fixes the boundary used to measure that day, which was
    still wrong in a different way."""
    y, m, d = (int(x) for x in date_str.split("-"))
    open_hour = 0 if _is_summer_ny(date_str) else 1
    win_start = datetime(y, m, d, open_hour, tzinfo=display_tz).astimezone(UTC)
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
    prev_date = (datetime(y, m, d) - timedelta(days=1)).date()
    # "Monday's yesterday is always Friday, period" (user, 2026-09-30) --
    # a plain calendar_day-1 lands on Saturday/Sunday for any Monday,
    # both of which are real market-closed/no-data days, not "no prior
    # day exists." Roll back to the last real trading day instead. Real
    # bug this fixes: 26 Jan (a Monday) silently returned None here --
    # not because there was genuinely no prior structure, but because
    # 25 Jan (Sunday) has zero minutes, so the abandonment check could
    # never even run that day. 19 Jan happened to get a non-None answer
    # by coincidence (some early-Monday-session minutes land on the
    # Sunday calendar date in Riyadh time), which masked the same bug --
    # inconsistent, not reliable, fixed the same way for every Monday.
    # Real bug fixed 2026-10-04 (user caught it directly: "yesterday
    # could be sunday... or 1st of january where there is no candle at
    # all"): skipping ONLY Saturday/Sunday isn't enough -- a weekday
    # holiday with zero real trading data (New Year's Day, 1 Jan, a
    # Wednesday) has the same "no prior day" problem but was never
    # rolled past, silently landing on an empty day and returning None
    # (which then read as "never abandoned" even when the real previous
    # trading day's extreme absolutely should have been checked). Now
    # rolls back past ANY day with zero minutes in the data, holiday or
    # weekend alike, not just by weekday number -- capped at 10 days so
    # a genuine start-of-data edge case still returns None instead of
    # looping forever.
    for _ in range(10):
        while prev_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            prev_date -= timedelta(days=1)
        win_start, win_end = forex_day_bounds(prev_date.isoformat(), display_tz)
        i0, i1 = bisect_left(mt, win_start), bisect_left(mt, win_end)
        if i0 < i1:
            day_minutes = minutes[i0:i1]
            return min(x.l for x in day_minutes) if side == "SELL" else max(x.h for x in day_minutes)
        prev_date -= timedelta(days=1)
    return None

def find_prev_day_sweep_time(minutes, mt: list, date_str: str, display_tz: ZoneInfo, side: str, extreme,
                              start_t: "datetime | None" = None):
    """First minute, anywhere in today's own full calendar day (same
    scope as Daily's own -- a sweep can happen before the trading window
    even opens), that actually takes the previous day's extreme. None if
    it never happens -- the case the user confirmed by hand for 13 Jan
    2026 ("13 did not take 12's low").

    `start_t` (2026-10-04, user-taught): scan from this moment instead of
    the calendar day's own 00:00 -- used when a brand new trend-POI grant
    lands partway through the day (see build_pdh_pdl_chain's reset)."""
    if extreme is None:
        return None
    win_start, win_end = forex_day_bounds(date_str, display_tz)
    if start_t is not None and start_t > win_start:
        win_start = start_t
    i0 = bisect_left(mt, win_start)
    for m in minutes[i0:]:
        if m.t >= win_end:
            break
        if (m.l <= extreme) if side == "SELL" else (m.h >= extreme):
            return m.t
    return None


def find_side_sweep_time_on_or_after(minutes, mt: list, side: str, start_date_str: str,
                                      display_tz: ZoneInfo, max_days: int = 20):
    """CONTROL (2026-10-02, user-taught): part of "respect" -- a PDL/PDH
    sweep that can land on the impact day itself, the next day, or
    several days later ("this might happen in one day, two or three or
    even more"). Generalizes find_prev_day_extreme/find_prev_day_sweep_time
    (single-day) across a run of calendar days starting at
    `start_date_str`, returning the FIRST day's sweep time found, or
    None if no sweep happens within `max_days` real calendar days."""
    y, m, d = (int(x) for x in start_date_str.split("-"))
    cur = datetime(y, m, d).date()
    for _ in range(max_days):
        date_str = cur.isoformat()
        extreme = find_prev_day_extreme(minutes, mt, date_str, display_tz, side)
        t = find_prev_day_sweep_time(minutes, mt, date_str, display_tz, side, extreme)
        if t is not None:
            return t
        cur += timedelta(days=1)
    return None


def build_pdh_pdl_chain(minutes, mt: list, side: str, display_tz: ZoneInfo,
                         window_end: "datetime", control_checkpoints: list | None = None):
    """1H ABANDONMENT, extended (2026-10-02, user-taught): a PDH (BUY) /
    PDL (SELL) wick that exceeds the relevant level WITHOUT a body
    closing through it does NOT reset the next day. It carries forward
    -- 1H is pre-abandoned from the START of every following day, no
    fresh sweep needed -- with the watched level ratcheting to each
    day's own high/low as long as that day ALSO only wicks (impulsive-
    uptrend candles exceeding one another's highs, mirrored for SELL).
    Clears on EITHER:
      (a) a real body close past the active level -- confirms the
          breakout for real, 1H re-armed starting the NEXT day, or
      (b) a structural reversal ("one day taking the low of the other,
          confirming swing high, handing control to sell or none") --
          this is exactly the CONTROL strip/flip mechanism already
          computed in compute_control_timeline, so it's consulted
          directly here rather than re-derived.

    Returns {date_str: (pre_abandoned: bool, fresh_trigger_time: datetime|None)}
    for every calendar day in the dataset up to window_end. pre_abandoned
    True means 1H is dead from that day's own 00:00 Riyadh; fresh_trigger_time
    (when pre_abandoned is False) is the exact minute a NEW sweep fires
    that same day, or None if the day stays fully armed throughout.

    TREND-GRANT RESET (2026-10-04, user-taught, caught on 2025-01-14 and
    2025-01-15): a brand new trend-direction POI impact that hands `side`
    FULL control (compute_control_timeline's "trend POI impacted ... ->
    full <side>" grant) is a clean start for the wick chain too, same as
    it already is for control itself -- any stale PDL/PDH wick carried in
    from BEFORE that grant stops mattering; 1H re-arms fresh from the
    grant's own minute, watching only price action from there onward.
    User's own words: "we have a brand new bearish POI impacted, so it
    takes full control, thus the wick chain stops here." Without this, a
    wick-based abandonment from days (even control-episodes) earlier kept
    silently blocking 1H even after a fresh trend grant had every right to
    re-arm it -- caught first on 2025-01-14 (FVG#210 regrants full SELL at
    01:11, but the OLD pre-abandoned carry-in from 01-13 kept 1H SELL dead
    all day regardless) and again on 2025-01-16/17 (FVG#209's 01-15 16:30
    SELL grant should have re-armed 1H SELL from there -- no PDL was
    actually taken since, so 1H stayed live through the 17th, but the old
    carry-in chain never gave it the chance)."""
    chain_days = {}
    active_level = None
    if not minutes:
        # No data at all in this window (e.g. a month beyond the CSV's
        # actual coverage, such as Oct-Dec 2026 when the dataset ends
        # Sep 30) -- nothing to chain, same as any other data-free month.
        return chain_days
    cur = minutes[0].t.astimezone(display_tz).date()
    end_date = window_end.astimezone(display_tz).date()
    prev_date_str = None
    grant_times = sorted(t for t, s, _o, r in (control_checkpoints or [])
                          if s == side and r.startswith("trend POI impacted"))
    while cur <= end_date:
        date_str = cur.isoformat()
        win_start, win_end = forex_day_bounds(date_str, display_tz)
        i0, i1 = bisect_left(mt, win_start), bisect_left(mt, win_end)
        day_minutes = minutes[i0:i1]
        if not day_minutes:
            chain_days[date_str] = (active_level is not None, None)
            cur += timedelta(days=1)
            continue

        if control_checkpoints is not None and active_level is not None:
            c_state, _ = control_state_at(control_checkpoints, win_start)
            if c_state not in (side, "BOTH"):
                active_level = None  # structural reversal already cleared it by today

        # A fresh trend grant landing partway through today resets the
        # chain as of its own minute -- only the day's remaining minutes
        # (from the grant forward) count for this day's sweep/ratchet.
        reset_t = max((g for g in grant_times if win_start <= g < win_end), default=None)
        if reset_t is not None:
            active_level = None
            scan_minutes = day_minutes[bisect_left([m.t for m in day_minutes], reset_t):]
        else:
            scan_minutes = day_minutes

        pre_abandoned = active_level is not None
        fresh_trigger_time = None
        if scan_minutes:
            day_high = max(m.h for m in scan_minutes)
            day_low = min(m.l for m in scan_minutes)
            day_close = scan_minutes[-1].c
        else:
            day_high = day_low = day_close = None

        if active_level is not None:
            touched = (day_high >= active_level) if side == "BUY" else (day_low <= active_level)
            if touched:
                closed_through = (day_close > active_level) if side == "BUY" else (day_close < active_level)
                if closed_through:
                    active_level = None  # clears starting TOMORROW
                else:
                    active_level = day_high if side == "BUY" else day_low  # ratchet forward
        elif prev_date_str is not None or reset_t is not None:
            prev_extreme = find_prev_day_extreme(minutes, mt, date_str, display_tz, side)
            t = find_prev_day_sweep_time(minutes, mt, date_str, display_tz, side, prev_extreme, start_t=reset_t)
            if t is not None:
                fresh_trigger_time = t
                closed_through = (day_close > prev_extreme) if side == "BUY" else (day_close < prev_extreme)
                if not closed_through:
                    active_level = day_high if side == "BUY" else day_low  # starts chaining from TOMORROW

        chain_days[date_str] = (pre_abandoned, fresh_trigger_time)
        prev_date_str = date_str
        cur += timedelta(days=1)
    return chain_days


def chain_abandon_at(chain_days: dict, date_str: str, display_tz: ZoneInfo):
    """Ceiling time for a given day from build_pdh_pdl_chain's output --
    the day's own 00:00 Riyadh if pre-abandoned, the fresh trigger
    minute if newly swept that day, or None if armed all day."""
    entry = chain_days.get(date_str)
    if entry is None:
        return None
    pre_abandoned, fresh_trigger_time = entry
    if pre_abandoned:
        win_start, _ = forex_day_bounds(date_str, display_tz)
        return win_start
    return fresh_trigger_time


def structural_hard_death_between(z, start_t: "datetime", end_t: "datetime",
                                   bars: list, bar_starts: list, minutes, mt: list):
    """CONTROL (2026-10-02): checks ONLY the two hard-death triggers
    (body_close, swing_break) in (start_t, end_t] -- used to confirm a
    zone that went swing_spent first never ALSO takes a real structural
    hit before its PDL/PDH sweep completes "respect" (spec: "what we
    care is that swing high confirmed and the POI zone is clear from
    any body no matter how many days poke into it"). swing_spent itself
    is deliberately excluded -- already known, not a disqualifier here.
    Returns (time, reason) or (None, None)."""
    bull = z.bullish
    near_boundary = z.zt if bull else z.zb

    body_close_at = None
    start_idx = max(0, bisect_right(bar_starts, start_t) - 1)
    for hb in bars[start_idx:]:
        if hb.end <= start_t:
            continue
        if hb.end > end_t:
            break
        breach = (hb.c <= near_boundary) if bull else (hb.c >= near_boundary)
        if breach:
            body_close_at = hb.end
            break

    swing_break_at = None
    # INCLUSIVE of start_t's own minute (2026-10-07, item #12, caught on
    # 2025-12-04 RB#114): a protect_level breach can land in the EXACT
    # same 1-minute bar as start_t itself (impact_time, or an already-
    # found swing_spent time) -- a wild single-minute bar can touch the
    # zone AND wick past protect_level in the same 60 seconds (no intra-
    # minute ordering is available in 1m OHLC data, so per the written
    # rule -- "wick or not, at the exact minute it happens" -- that
    # minute must count, not be silently skipped). bisect_right excluded
    # it; bisect_left includes it.
    idx = bisect_left(mt, start_t)
    for m in minutes[idx:]:
        if m.t > end_t:
            break
        if (m.l < z.protect_level) if bull else (m.h > z.protect_level):
            swing_break_at = m.t
            break

    candidates = [(t, r) for t, r in ((body_close_at, "body_close"), (swing_break_at, "swing_break")) if t is not None]
    if not candidates:
        return None, None
    return min(candidates, key=lambda tr: tr[0])


def structural_invalid_at(z, it: "datetime", bars: list, bar_starts: list,
                           minutes, mt: list, events: list | None = None) -> tuple:
    """Ported from five_bso_engine.py's structural_invalid_at() (SPEC.md
    SS17/SS20-24) -- the POI-violation-before-entry check the user asked
    about directly (2026-09-28) and that compute_5m_trades() previously
    had no answer for. Whichever happens first, from the zone's own
    impact time `it`:
      (a) 'body_close' -- a fully completed 4H/1H candle closes its BODY
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
      (c) 'swing_spent' (2026-09-30, real ICT concept, NOT in
          five_bso_engine.py/SPEC.md -- same new/unvalidated status as
          premium/discount and open-inside-zone): the zone's OWN
          timeframe confirms a same-kind swing (a swing HIGH for a SELL
          zone, a swing LOW for a BUY zone -- the SL-anchor kind) at or
          after impact, with NO anchor break needed at all. User's own
          words: "swing confirmation after impact makes the POI spent
          and not good for more trading... coming hours later after the
          impact minute is fine, what is not fine is confirming swing
          point... before we enter." Uses the swing engine's own exact
          M1 confirmation minute (Event.at), not just the bar -- verified
          against RB#22 (16 Jan): swing high 1.16138 (swing candle =
          the impact bar itself) confirmed 09:39 Riyadh, over an hour
          BEFORE the first entry attempt (11:03) -- so all three of that
          day's entries were already invalid under this rule, even
          though the anchor (protect_level) didn't break until 13:41.
      (d) 'prior_candle_taken' (2026-10-07, item #11b, user-taught): the
          zone's own-timeframe candle immediately before its impact candle
          has its relevant extreme (high for BUY, low for SELL) taken at
          any point from impact onward, BEFORE this zone ever produces an
          entry -- "the move already happened before we could react". See
          the inline comment at this check's own implementation below for
          the exact anchor-point design decision.
    Returns (time, reason); (None, None) if never invalidated in the
    available data. A candidate whose resting swing or entry trigger
    lands at/after this time is dead: setup only, no entry."""
    bull = z.bullish
    near_boundary = z.zt if bull else z.zb

    body_close_invalid_at = None
    start_idx = max(0, bisect_right(bar_starts, it) - 1)
    for hb in bars[start_idx:]:
        breach = (hb.c <= near_boundary) if bull else (hb.c >= near_boundary)
        if breach:
            body_close_invalid_at = hb.end
            break

    swing_break_at = None
    # INCLUSIVE of the impact minute itself -- see the matching note in
    # structural_hard_death_between() above (2026-10-07, item #12).
    idx = bisect_left(mt, it)
    for m in minutes[idx:]:
        if (m.l < z.protect_level) if bull else (m.h > z.protect_level):
            swing_break_at = m.t
            break

    # Compare against the IMPACT BAR's index, not its start timestamp --
    # impact almost always lands mid-bar (e.g. 05:34 inside a 05:00-09:00
    # 4H bar), so a plain `bar.start >= it` wrongly excludes a swing point
    # set by that SAME candle. A swing whose own point is the impact bar
    # itself (or later) still counts.
    impact_bar_idx = max(0, bisect_right(bar_starts, it) - 1)

    swing_spent_at = None
    if events:
        sl_anchor_kind = 0 if not bull else 1  # a HIGH (0) protects a SELL zone, a LOW (1) protects a BUY zone
        spent_candidates = [e.at for e in events
                             if e.kind == sl_anchor_kind and e.at is not None
                             and e.swing >= impact_bar_idx]
        if spent_candidates:
            swing_spent_at = min(spent_candidates)

    # Item #11b (2026-10-07, user-taught -- a REAL disqualifying rule, not
    # a note, same category as body_close/swing_break/swing_spent above).
    # "If the prior 1H/4H candle's relevant extreme (high for a would-be
    # BUY zone, low for a would-be SELL zone -- the direction that means
    # 'the move already happened before we could react') is taken at any
    # point BEFORE a trade's entry actually fires, that zone must NOT
    # produce an entry at all." Implementation choice (documented in
    # DAILIES_LEARNING_LOG.txt, since the spec left the exact anchor
    # ambiguous): "prior candle" here is the zone's OWN-timeframe candle
    # immediately preceding the candle that contains the zone's own
    # impact (a single FIXED candle, parallel to how protect_level/
    # near_boundary are each a single fixed reference snapshotted at/near
    # impact) -- NOT a rolling "most recently closed candle" definition.
    # This differs on purpose from item #11's own "prior 4H candle"
    # (ALWAYS the 4H timeframe, anchored to ENTRY time, data-collection
    # only) -- #11b is anchored to IMPACT and uses the zone's OWN
    # timeframe, because it must be evaluated continuously from impact
    # forward, before any entry time is even known yet. Checked from the
    # zone's own impact time through to the prospective entry minute, via
    # the exact same invalidated_at mechanism every other trigger here
    # already uses -- universal, every timeframe, every zone type, no
    # special-casing.
    prior_candle_taken_at = None
    prior_idx = impact_bar_idx - 1
    if prior_idx >= 0:
        prior_bar = bars[prior_idx]
        prior_level = prior_bar.h if bull else prior_bar.l
        idx_p = bisect_left(mt, it)
        for m in minutes[idx_p:]:
            if (m.h >= prior_level) if bull else (m.l <= prior_level):
                prior_candle_taken_at = m.t
                break

    candidates = [(t, r) for t, r in (
        (body_close_invalid_at, "body_close"),
        (swing_break_at, "swing_break"),
        (swing_spent_at, "swing_spent"),
        (prior_candle_taken_at, "prior_candle_taken"),
    ) if t is not None]
    if not candidates:
        return None, None
    return min(candidates, key=lambda tr: tr[0])


def compute_control_timeline(d_zones_full, minutes, mt: list, display_tz: ZoneInfo,
                              window_end: "datetime"):
    """CONTROL (2026-10-02, user-taught; CORRECTED 2026-10-04 -- see
    DAILIES_LEARNING_LOG.txt's CONTROL section for the full taught spec
    this ports). A layer ABOVE Daily bias: which side is ACTIVELY
    tradeable right now, distinct from which side the trend structurally
    favors. Driven ENTIRELY by DAILY-level POI events -- the user's own
    correction, verbatim: "control was never for 4h or 1h. it is ONLY
    for daily. everything I said about control was for daily. 4h and 1h
    are the setups that come with those controls plus other conditions."
    This used to read 4H zones (h4_engine), which was wrong from the
    start -- a real, confirmed bug, not a refinement. 4H/1H never drive
    control; they only CONSUME whatever control currently says, plus
    their own separate per-timeframe conditions (same-day Daily
    authorization, 1H's own PDL/PDH abandonment chain, premium/discount)
    -- none of which live in this function.

    States: "BUY", "SELL", "BOTH" (shared), "NONE".

    Processes the FULL zone history up through `window_end` -- NOT just
    today's narrow trading-session window (control is a multi-day/
    multi-leg timeline, not a single-day computation; using the
    session-hours window here was a real bug caught in smoke-testing --
    it silently excluded every zone impacted on a prior day, so control
    never got off NONE at all).

    Returns a sorted list of checkpoints [(time, state, one_h_owner, reason), ...]
    -- one_h_owner is "BUY"/"SELL"/None, the side currently holding the
    single 1H slot; reason is a plain-English string naming the zone/
    mechanism behind that transition."""
    d_bar_starts = [b.start for b in d_zones_full.w]

    # Step 1: classify every DAILY zone impacted up to window_end as
    # trend or opposing (same test apply_daily_bias_gate already uses).
    # events: (time, kind, side, zone_id) -- zone_id is (ptype, z.id),
    # used to correlate a trend zone's own death back to whichever zone
    # is actually the one currently holding control (see Step 2).
    events = []
    for zones, ptype in ((d_zones_full.ob_zones, "OB"), (d_zones_full.rb_zones, "RB"),
                         (d_zones_full.fvg_zones, "FVG"), (d_zones_full.vi_zones, "VI")):
        for z in zones:
            if z.impact_time is None or z.impact_time > window_end:
                continue
            # A zone already rejected -- OPEN_INSIDE_ZONE (born dead, spec
            # item (a) of respect: "cleared of OPEN_INSIDE_ZONE/body-close/
            # anchor-break") -- never counted as a real impact for CONTROL
            # purposes. Real gap caught on a final pre-flight check: this
            # zone loop never consulted z.rejected at all, so a born-dead
            # zone could still flip control.
            if getattr(z, "rejected", False):
                # STILLBORN TREND CANDIDATE (2026-10-07, user-taught,
                # caught on 2025-05-08 RB#458): a Daily swing confirmation
                # (not a zone impact) can grant a side full control without
                # ever attaching a zone to controlling_trend_group -- so
                # when the FIRST real zone that would have been that
                # side's trend support turns out to be rejected (born
                # dead), there is nothing for the ordinary trend-zone-
                # death path to see die, and the day falls through to
                # plain NONE even though a real, now-dead candidate
                # existed. Only matters when daily_controlling_bias still
                # classifies this rejected zone as the TREND side (not
                # opposing) at its own impact time -- Step 2 below further
                # gates it to fire only when controlling_trend_group is
                # still empty (no real zone already backs that side; if
                # one does, this stillborn candidate is irrelevant).
                controlling = daily_controlling_bias(d_zones_full, z.impact_time, minutes, mt)
                if controlling is not None and z.bullish == controlling:
                    side = "BUY" if z.bullish else "SELL"
                    zone_id = (ptype, z.id)
                    events.append((z.impact_time, "trend_candidate_stillborn", side, zone_id))
                continue
            controlling = daily_controlling_bias(d_zones_full, z.impact_time, minutes, mt)
            if controlling is None:
                continue
            side = "BUY" if z.bullish else "SELL"
            zone_id = (ptype, z.id)
            if z.bullish == controlling:
                events.append((z.impact_time, "impact_trend", side, zone_id))
                # CONTROL spec item 6: what happens to the SPECIFIC trend
                # zone currently holding control if it later dies.
                # body-close/open-inside-zone -> tactical reversion.
                # anchor-break -> structural (real MSS, handled for free
                # by future zones' classification already using the
                # post-flip bias -- but CONTROL itself must also flip
                # immediately, not wait for the next zone impact).
                #
                # MASKING BUG fixed 2026-10-05 (user caught on 2025-01-30,
                # RB#434): structural_invalid_at() returns only the SINGLE
                # earliest of three death types (body_close, swing_break,
                # swing_spent). The trend branch here never asked about
                # swing_spent -- it only ever reads body_close/swing_break
                # -- but whenever swing_spent happened to land EARLIEST
                # chronologically, structural_invalid_at() still returned
                # IT, silently burying a real, later body_close/swing_break
                # this branch actually needed. RB#434 genuinely body-closed
                # at 2025-01-31 01:00 (Jan 30's own daily close, exactly
                # matching the user's account), but a swing_spent at
                # 2025-01-30 16:57 masked it entirely, so CONTROL never
                # saw ANY death for RB#434 at all. Fixed by using
                # structural_hard_death_between() instead -- the SAME
                # swing_spent-blind helper already used on the opposing-
                # zone respect path for exactly this reason ("swing_spent
                # itself is deliberately excluded -- already known, not a
                # disqualifier here") -- searched from impact to
                # window_end instead of a respect window.
                invalidated_at, reason = structural_hard_death_between(
                    z, z.impact_time, window_end, d_zones_full.w, d_bar_starts, minutes, mt)
                if reason == "body_close":
                    events.append((invalidated_at, "trend_death_tactical", side, zone_id))
                elif reason == "swing_break":
                    events.append((invalidated_at, "trend_death_structural", side, zone_id))
                continue
            invalidated_at, reason = structural_invalid_at(z, z.impact_time, d_zones_full.w, d_bar_starts,
                                                             minutes, mt, d_zones_full.events)
            events.append((z.impact_time, "impact_opp", side, zone_id))
            if reason in ("body_close", "swing_break"):
                events.append((invalidated_at, "opp_death", side, zone_id))
            elif reason == "swing_spent":
                date_str = z.impact_time.astimezone(display_tz).date().isoformat()
                sweep_t = find_side_sweep_time_on_or_after(minutes, mt, side, date_str, display_tz)
                if sweep_t is None:
                    continue  # never swept in the available data -- stays pending, no resolution
                respect_t = max(invalidated_at, sweep_t)
                hard_t, _ = structural_hard_death_between(z, invalidated_at, respect_t,
                                                           d_zones_full.w, d_bar_starts, minutes, mt)
                if hard_t is not None:
                    events.append((hard_t, "opp_death", side, zone_id))
                else:
                    events.append((respect_t, "opp_respect", side, zone_id))
            # reason is None: never invalidated in available data -- stays pending, no resolution.

    # Step 1b: NONE control -- a standalone, POI-independent signal, off
    # a single Daily swing confirming (2026-10-03, user correction: a
    # swing high confirms BY breaking the connecting low -- that break
    # IS the PDL taken. Not two conditions to sweep-scan and AND
    # together; one single Daily swing-confirm event, full stop. 4H was
    # never part of this either -- NONE is Daily-only, same as PDL/PDH
    # always has been). Daily swing HIGH confirming strips BUY's control
    # (direction confirmed by the user's own worked example: trading BUY
    # off an in-favor POI in an uptrend, price makes a swing high with no
    # live opposing zone to inherit -> NONE); Daily swing LOW confirming
    # strips SELL's the same way. Only strips a side that's ACTUALLY
    # currently held (alone, or as part of BOTH) -- see Step 2's own
    # handling for what happens in each case (alone -> NONE, part of
    # BOTH -> drops to the remaining side, never NONE).
    for e in d_zones_full.events:
        if e.at is None or e.at > window_end:
            continue
        side = "BUY" if e.kind == 0 else "SELL"
        events.append((e.at, "daily_swing_strip", side, None))

    # At equal timestamps, every GRANT event (impact_trend, impact_opp,
    # opp_respect) is processed LAST, after daily_swing_strip and opp_death.
    # General rule (2026-10-04, user-taught, generalized from the original
    # impact_trend-only fix after the user caught a second instance on
    # 2025-01-08): a swing-high/low strip can only remove a side that was
    # ALREADY held BEFORE this minute's events -- never a side some OTHER
    # event in the same minute is about to grant. So every strip/death must
    # see the pre-minute state, and every grant must apply AFTER that, so
    # it always sticks.
    #   Case A (2025-01-06 04:15, the original fix): BOTH held, swing low
    #   strips SELL -> BUY, then the trend's own FVG impact (impact_trend)
    #   regrants full SELL -- the trend's always-wins regain gets the final
    #   word. User: "in one minute we first lose control of sell, then
    #   control of buy, back to sell."
    #   Case B (2025-01-08 01:00, caught next): only SELL held, nothing to
    #   strip for BUY -- the swing-high strip is a pure no-op regardless of
    #   anything else happening that minute. The SAME minute's opposing FVG
    #   impact (impact_opp) then grants shared BOTH, and nothing strips it
    #   back out, because the strip already resolved (as a no-op) before the
    #   grant applied. User: "you strip buy when you have one or both, but
    #   we only had sell... the strip should come when one is active, not
    #   when it is not there in the first place."
    #   Case C (forward-looking, user-stated, not yet seen in real data):
    #   BUY held alone, swing high strips it to NONE, but the SAME minute a
    #   fresh BUY POI impacts (trend or opposing) -- the strip still
    #   resolves first (BUY -> NONE off the pre-minute state), but the
    #   grant immediately following it restores BUY in the same minute,
    #   never actually sitting in NONE. User: "what is the point of
    #   stopping at swing high? it is to wait until price impacts another
    #   POI we can buy from -- so if it happens at the same minute, we do
    #   it." This falls out of the same ordering rule for free -- no special
    #   case needed.
    # opp_death stays in its original per-zone position (a LOSS event, not
    # a grant) -- only impact_trend/impact_opp/opp_respect are pulled to the
    # very end.
    #
    # Within that same-minute grant cluster, impact_trend must additionally
    # sort LAST of the three (2026-10-05, real bug: 2025-02-07 16:30 --
    # daily_swing_strip (swing low, strips SELL from BOTH -> BUY), then
    # impact_trend (RB #437, SELL -- an in-favor/trend POI genuinely
    # impacted that same minute) and opp_respect (FVG #222, BUY) landed on
    # the same timestamp; a plain stable sort left them in zone-processing
    # order, which happened to apply opp_respect AFTER impact_trend and so
    # silently re-overrode the trend grant back to BUY. The user caught
    # this directly: "price impacted an in favor POI... this hands over
    # the whole control to sell because we now have a POI with the trend
    # impacted upon" -- the exact same "trend's always-wins regain gets
    # the final word" principle Case A above already established for
    # strip-vs-trend-grant, just not yet applied to grant-vs-grant ties.
    # An opposing zone's "respect" is a defensive hold-your-share
    # mechanism; it cannot hand control back from a side a fresh trend
    # impact just claimed in that same instant. impact_opp sits between
    # the two: a brand-new opposing zone being impacted is a real event
    # too, so it still outranks a mere respect, but a genuine trend
    # impact outranks everything.
    _GRANT_KINDS = ("impact_trend", "impact_opp", "opp_respect")
    _GRANT_PRIORITY = {"opp_respect": 1, "impact_opp": 2, "impact_trend": 3}
    events.sort(key=lambda e: (e[0], e[1] in _GRANT_KINDS, _GRANT_PRIORITY.get(e[1], 0)))

    # Step 2: replay into a state machine.
    checkpoints = []
    state = "NONE"
    one_h_owner = None
    # SET of (ptype, id) -- every trend-direction zone (in-favor or
    # aggressive-in-favor alike, both "trade with the trend" per the
    # user) currently anchoring full control. Real bug fixed 2026-10-04,
    # user's own correction: multiple same-side trend zones impacting
    # the same day (or while already in full control) were being
    # silently dropped -- only the single zone that caused the last
    # FLIP ever got tracked, so one of them dying was wrongly treated
    # as the WHOLE trend's death even while its siblings were still
    # alive and un-breached. "We trade like we have one POI affected
    # that day" -- the group only actually dies, triggering reversion,
    # once EVERY member has died (tactical or structural), not on the
    # first one.
    controlling_trend_group = set()
    # Same group-tracking fix, mirrored for the OPPOSING side (2026-10-05,
    # user's own correction on 2025-01-24): "we have been through this
    # before, you need to be careful with price impacting multiple POI in
    # the same day" -- a second opposing zone of the SAME side impacting
    # while the first still holds the shared BOTH slot was previously
    # silently untracked (impact_opp's grant branch only fires when state
    # isn't already BOTH), so controlling_opp_zone stayed pointed at
    # whichever zone granted it FIRST; if that original zone died while a
    # LATER sibling was still alive and un-breached, nothing protected the
    # still-alive sibling from being silently invisible to opp_death's
    # own tracking. Per side: SET of (ptype, id) of every opposing zone
    # currently anchoring that side's hold -- dies only once every member
    # has died, same rule as the trend group.
    controlling_opp_group = {"BUY": set(), "SELL": set()}

    def opposite(s):
        return "SELL" if s == "BUY" else "BUY"

    def record(t, reason):
        checkpoints.append((t, state, one_h_owner, reason))

    def zone_label(zone_id):
        return f"{zone_id[0]} #{zone_id[1]}" if zone_id is not None else ""

    def grant_trend(t, side, zone_id):
        nonlocal state, one_h_owner, controlling_trend_group
        state = side
        one_h_owner = side
        controlling_trend_group = {zone_id}
        controlling_opp_group["BUY"] = controlling_opp_group["SELL"] = set()
        record(t, f"trend POI impacted ({zone_label(zone_id)}, {side}) -> full {side}")

    for t, kind, side, zone_id in events:
        if kind == "impact_trend":
            if state != side:
                grant_trend(t, side, zone_id)
            else:
                # Already fully in control of this side -- this zone
                # doesn't cause a new flip/checkpoint, but it DOES join
                # the group backing that control, same as if it had
                # caused the flip itself. No checkpoint recorded (state
                # doesn't change), it just means the group won't be
                # considered dead until THIS zone dies too.
                controlling_trend_group.add(zone_id)
        elif kind == "impact_opp":
            if state == opposite(side) or state == "NONE":
                state = "BOTH"
                one_h_owner = side
                controlling_opp_group[side] = {zone_id}
                record(t, f"opposing POI impacted ({zone_label(zone_id)}, {side}) -> shared BOTH, 1H to {side}")
            elif state == "BOTH" and one_h_owner == side:
                # Same group-join rule as impact_trend: a second same-side
                # opposing zone impacting while the first still holds the
                # shared BOTH slot doesn't cause a new flip/checkpoint, but
                # joins the group backing that slot -- the slot only gives
                # it up once EVERY member has died, not on the first one.
                controlling_opp_group[side].add(zone_id)
        elif kind == "opp_death":
            # Real bug (2026-10-03, user's own Jan-2 walkthrough caught
            # this): only a no-op when this opposing zone was never the
            # one actually holding control. If it currently IS -- either
            # as BOTH's 1H holder, or holding full control via an earlier
            # respect -- its death must hand control back, not leave it
            # untouched ("trend's dominance just reconfirmed" only ever
            # applied to the ordinary case of an opposing zone that died
            # WITHOUT ever having taken control in the first place).
            if zone_id in controlling_opp_group[side]:
                controlling_opp_group[side].discard(zone_id)
                if controlling_opp_group[side]:
                    continue  # other opposing zones from the same group are still alive -- no change
                if state == "BOTH" and one_h_owner == side:
                    state = opposite(side)
                    one_h_owner = opposite(side)
                    record(t, f"opposing zone death ({zone_label(zone_id)}, last of its group) -> was holding shared BOTH, control reverts to {opposite(side)}")
                elif state == side:
                    state = opposite(side)
                    one_h_owner = opposite(side)
                    record(t, f"opposing zone death ({zone_label(zone_id)}, last of its group) -> was holding full control via respect, control reverts to {opposite(side)}")
        elif kind == "opp_respect":
            if state != side:
                state = side
                one_h_owner = side
                controlling_trend_group = set()
                controlling_opp_group[side] = {zone_id}
                record(t, f"opposing POI respected ({zone_label(zone_id)}, {side}) -> full {side}")
        elif kind == "trend_death_tactical":
            # BOTH-state gap (2026-10-06, user-taught, caught on
            # 2025-01-30/31, RB#432): `state == side` alone missed the
            # case where `side`'s trend is still standing but only
            # SHARED (state=="BOTH", 1H currently owned by the
            # opposite side via an opposing-POI impact) -- e.g. Jan 30
            # closed BOTH (BUY trend, 1H owner SELL since 16:57), then
            # RB#432 (BUY's own last standing trend zone) body-closed
            # at Jan 31 01:00. The old condition never even looked,
            # because state was "BOTH" not "BUY", so this real trend
            # death silently produced no checkpoint at all -- CONTROL
            # only flipped to SELL later (01:49), by an unrelated
            # swing-confirmation strip, 49 minutes after the zone that
            # was actually the day's last BUY trend reference had
            # already died. `side` is still the trend backing BOTH
            # whenever one_h_owner is the OTHER side -- generalizes the
            # same proactive-flip principle to the shared-control case.
            is_trend_side = state == side or (state == "BOTH" and one_h_owner == opposite(side))
            if zone_id in controlling_trend_group and is_trend_side:
                controlling_trend_group.discard(zone_id)
                if controlling_trend_group:
                    continue  # other trend zones from the same group are still alive -- no change
                # PROACTIVE FLIP, not NONE (2026-10-05, user-taught,
                # reversing the 2026-10-04 "no banked respect -> NONE"
                # fix after the user's own correction on 2025-01-15/20-22):
                # the trend running OUT of any currently-controlling POI
                # is itself the signal that the trend is "almost being
                # changed" -- so the opposite side takes FULL control
                # immediately, the same as a real structural MSS flip,
                # not a conditional reversion that depends on whether the
                # opposite side happened to earn a "respect" first. User's
                # own words: "a POI with the trend getting breached or
                # violated simply means this trend is almost being
                # changed... we then simply stop buying or trading against
                # the trend and we keep full sell control." Verified on
                # 2025-01-20/21/22: the Daily zone that was the LAST one
                # left in its bearish leg died tactically (body close) on
                # the 20th -- proactively flips to full BUY there, holds
                # through the 21st (nothing left in that leg to re-grant
                # SELL), and the REAL structural MSS flip (the protective
                # swing high actually breaking) on the 22nd just confirms
                # what CONTROL had already anticipated two days earlier --
                # exactly the user's own account of "we anticipated it
                # with the body close... to be part of the move that makes
                # the trend change." Renders the old banked_respect
                # mechanism moot (it only ever fed this one branch) --
                # removed entirely rather than left dormant.
                state = opposite(side)
                one_h_owner = opposite(side)
                record(t, f"trend zone tactical death ({zone_label(zone_id)}, last of its group) -> "
                          f"no trend POI left standing, proactive full control to {opposite(side)}")
        elif kind == "trend_death_structural":
            # Same BOTH-state generalization as trend_death_tactical
            # above -- a real structural MSS death of the trend's last
            # standing zone must count even while that trend is only
            # shared (BOTH, 1H owned by the opposite side), not just
            # when it holds state outright.
            is_trend_side = state == side or (state == "BOTH" and one_h_owner == opposite(side))
            if zone_id in controlling_trend_group and is_trend_side:
                controlling_trend_group.discard(zone_id)
                if controlling_trend_group:
                    continue  # other trend zones from the same group are still alive -- no change
                # Real Daily MSS flip -- "the whole framework mirrors
                # from here": the opposite side takes automatic FULL
                # control immediately, not just on its next own impact.
                state = opposite(side)
                one_h_owner = opposite(side)
                record(t, f"trend zone structural death / Daily MSS flip ({zone_label(zone_id)}, last of its group) -> control to {opposite(side)}")
        elif kind == "trend_candidate_stillborn":
            # Approved fix (2026-10-07, caught on 2025-05-08 RB#458): only
            # acts when NO real zone currently backs this trend side
            # (controlling_trend_group empty) -- if one does, this
            # stillborn candidate is irrelevant, the real zone's own
            # later death (if any) is what matters, same as always.
            is_trend_side = state == side or (state == "BOTH" and one_h_owner == opposite(side))
            if is_trend_side and not controlling_trend_group:
                state = opposite(side)
                one_h_owner = opposite(side)
                record(t, f"trend candidate stillborn ({zone_label(zone_id)}, born rejected, no real trend zone ever backed {side}) -> proactive full control to {opposite(side)}")
        elif kind == "daily_swing_strip":
            swing_word = "high" if side == "BUY" else "low"
            if state == side:
                # side was alone -- nothing left standing.
                state = "NONE"
                one_h_owner = None
                controlling_trend_group = set()
                controlling_opp_group["BUY"] = controlling_opp_group["SELL"] = set()
                record(t, f"Daily swing {swing_word} confirmed -> strips {side} (was alone), control to NONE")
            elif state == "BOTH":
                # side was part of a shared BOTH -- the other side was
                # already standing on its own, so it just keeps control
                # (user correction, 2026-10-03: "if we are on both and we
                # lose sell, we go to buy" -- NOT NONE).
                state = opposite(side)
                one_h_owner = opposite(side)
                controlling_trend_group = set()
                controlling_opp_group[side] = set()
                record(t, f"Daily swing {swing_word} confirmed -> strips {side} from BOTH, control to {opposite(side)}")
            # else: side isn't currently held at all (state is opposite(side)
            # or already NONE) -- nothing to strip, no-op.

    return checkpoints


def control_state_at(checkpoints: list, t: "datetime"):
    """Returns (state, one_h_owner) as of time `t` -- the last checkpoint
    at or before `t`, or ("NONE", None) if `t` is before the first one."""
    state, one_h_owner = "NONE", None
    for ct, cs, ch, _reason in checkpoints:
        if ct > t:
            break
        state, one_h_owner = cs, ch
    return state, one_h_owner


def control_ceiling(checkpoints: list, t0: "datetime", side: str, resource: str):
    """First checkpoint AFTER t0 where `side` stops holding `resource`
    ("4h" or "1h"). None if it never does within the available
    checkpoints."""
    for ct, cs, ch, _reason in checkpoints:
        if ct <= t0:
            continue
        if resource == "4h":
            if not (cs == side or cs == "BOTH"):
                return ct
        else:
            if ch != side:
                return ct
    return None


def run_5m_bso(z, it, bar_starts5: list, events5_sorted: list, minutes, mt: list,
               invalidated_at, window_end, display_tz: ZoneInfo,
               watch_levels: list[tuple[str, float]] | None = None,
               h4_bars: list | None = None, h4_bar_starts: list | None = None,
               origin_bars: list | None = None, origin_bar_starts: list | None = None) -> dict:
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
        if not session_sweep_satisfied(m.t, bull, minutes, mt, display_tz):
            continue  # user's rule (2026-09-30): London/New York need the prior session's own liquidity swept first
        broke = (m.h > current.price) if bull else (m.l < current.price)
        if broke:
            entry_m = m
            break
    if entry_m is None:
        return dict(stage="POI_BREACHED" if stopped else "NO_ENTRY_IN_WINDOW",
                    resting_at=resting.at, candidate_price=current.price, replacements=replacements)

    entry_price = current.price
    entry_time = entry_m.t
    # item #5 (2026-10-10, tuning log): how far past the trigger level did
    # the entry minute's own extreme push -- a trade that barely overshot
    # (<=1 pip) then reversed straight to SL is a candidate optimization
    # signal. Observational only, never changes entry/SL/TP.
    entry_overshoot_pips = abs((entry_m.h if bull else entry_m.l) - entry_price) * 10000

    # SL anchor (2026-10-06, user-taught, caught on 2025-01-07 RB#115
    # attempt 1): the extreme since impact must be the real price
    # extreme (every 1m high/low), not just the extreme among CONFIRMED
    # 5m swing pivots. A genuine wick can fail to register as a
    # confirmed swing (never rolls over into a recognized pivot) and
    # was silently excluded from the old swing-pool, giving a tighter
    # SL than the real structure since impact -- e.g. RB#115 attempt 1
    # (impact 10:39, entry 11:18): the real high since impact was
    # 1.04241 (10:44 wick, never confirmed as a swing), but the old
    # pool-based SL used 1.04206 (the only swing actually confirmed by
    # entry time). User's own words: "SL should have been placed at the
    # most extreme swing high not the immediate one... by extreme we
    # mean the extreme since impact. period." Universal: every SL from
    # here on is the raw 1-minute extreme from impact through the entry
    # minute (inclusive), same direction as the SL-anchor kind.
    # Use the zone's real impact_time here, NOT `it` -- `it` is
    # max(impact_time, window_start) (clamped to when the trading
    # window opens, since entries can't be searched for before that),
    # but the SL-anchor lookback must start from the TRUE impact,
    # trading-window or not (e.g. RB#115 attempt 1: impact 10:39,
    # window didn't open until 11:00 -- the real 1.04241 wick at 10:44
    # would be silently excluded again if clamped the same way entry
    # search is).
    sl_price = _minutes_extreme(mt, minutes, z.impact_time, entry_time + timedelta(minutes=1), bull)
    if sl_price is None:
        return dict(stage="NO_SL_POOL", resting_at=resting.at, entry_time=entry_time, entry_price=entry_price)
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return dict(stage="ZERO_RISK", resting_at=resting.at, entry_time=entry_time,
                    entry_price=entry_price, sl_price=sl_price)
    tp_price = entry_price + 3 * risk if bull else entry_price - 3 * risk

    post = _post_entry_walk(bull, entry_time, entry_price, sl_price, tp_price, risk, minutes, mt,
                             watch_levels, h4_bars, h4_bar_starts,
                             zb=z.zb, zt=z.zt, origin_bars=origin_bars, origin_bar_starts=origin_bar_starts)
    post["entry_overshoot_pips"] = entry_overshoot_pips

    return dict(stage="ENTERED", resting_at=resting.at, replacements=replacements,
                entry_time=entry_time, entry_price=entry_price, sl_price=sl_price,
                tp_price=tp_price, risk=risk, **post)


def _post_entry_walk(bull: bool, entry_time, entry_price: float, sl_price: float, tp_price: float, risk: float,
                      minutes, mt: list, watch_levels: list[tuple[str, float]] | None,
                      h4_bars: list | None, h4_bar_starts: list | None,
                      zb: float | None = None, zt: float | None = None,
                      origin_bars: list | None = None, origin_bar_starts: list | None = None) -> dict:
    """Shared post-entry walk (2026-10-07 refactor, extracted verbatim
    from run_5m_bso so run_5m_bso_premium -- item #10's new mechanism --
    gets the IDENTICAL mfe/mae, watch_levels, item #11 prior-4H note, and
    item #25 instant-stop note for free, with zero risk of the two
    mechanisms' post-entry bookkeeping drifting apart. Entry (exclusive)
    through exit (inclusive), or through all available data if the trade
    never resolves.

    Item #11 (DATA COLLECTION ONLY -- never changes entry/exit/SL/TP; see
    item #11b/structural_invalid_at for the BEFORE-entry version, which
    IS a real disqualifying rule): did price take the PRIOR 4H candle's
    high (BUY)/low (SELL) between entry and exit? "Prior 4H candle" = the
    4H bar that closed immediately before THIS TRADE'S OWN entry time --
    ALWAYS the 4H timeframe, regardless of the zone's own timeframe."""
    prior_4h_level = None
    if h4_bars and h4_bar_starts:
        idx4 = bisect_right(h4_bar_starts, entry_time) - 1
        prior_idx = idx4 - 1
        if prior_idx >= 0:
            prior_bar = h4_bars[prior_idx]
            prior_4h_level = prior_bar.h if bull else prior_bar.l

    effective_watch_levels = list(watch_levels or [])
    if prior_4h_level is not None:
        effective_watch_levels.append(("prior_4h_extreme", prior_4h_level))

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
        if effective_watch_levels:
            for label, lvl in effective_watch_levels:
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

    # "Instant-stop" note (2026-10-07, item #25, user-requested -- NOT a
    # trading rule, never changes whether/how a trade is taken). Real
    # example on file: 2025-11-03 H4 SELL OB#74, entry 19:36 @ 1.15268,
    # SL 20:14 @ 1.15315 -- SL distance is the same `risk` value already
    # computed by the caller (entry to SL, in pips). User's threshold: 2
    # pips. Flag only ever set True on an actual SL exit (an open/TP
    # trade never had its "SL-hit price" reached at all).
    instant_stop_pips = risk * 10000
    instant_stop = (result == "SL") and (instant_stop_pips <= INSTANT_STOP_THRESHOLD_PIPS)

    # item #4 (2026-10-10, tuning log): did the ORIGINATING POI's own
    # timeframe candle (its zb/zt, whatever tf this zone is -- H4 or 1H)
    # body-CLOSE back inside the zone after we entered? Observational
    # only, never changes the trade -- a candidate future optimization
    # signal the user wants mined from real data, not yet a filter.
    body_close_in_poi_at = None
    if zb is not None and zt is not None and origin_bars and origin_bar_starts:
        first_bar_idx = bisect_right(origin_bar_starts, entry_time)
        end_t = exit_time or (minutes[-1].t if minutes else entry_time)
        for ob in origin_bars[first_bar_idx:]:
            if ob.start > end_t:
                break
            if zb <= ob.c <= zt:
                body_close_in_poi_at = ob.start
                break

    return dict(result=result or "OPEN", exit_time=exit_time,
                mfe=abs(mfe_price - entry_price), mae=abs(mae_price - entry_price), watch_hits=watch_hits,
                instant_stop_pips=instant_stop_pips, instant_stop=instant_stop,
                prior_4h_level=prior_4h_level, prior_4h_taken_at=watch_hits.get("prior_4h_extreme"),
                item4_body_close_in_poi_at=body_close_in_poi_at)


def run_5m_bso_premium(z, impact_time: "datetime", events5_sorted: list, minutes, mt: list,
                        invalidated_at, window_end: "datetime", display_tz: ZoneInfo,
                        h4_bars: list | None = None, h4_bar_starts: list | None = None,
                        origin_bars: list | None = None, origin_bar_starts: list | None = None) -> dict:
    """Item #10 (2026-10-07, user-designed -- a genuinely NEW 5m entry
    mechanism, FIRST IMPLEMENTATION; full design discussion, every
    ambiguous-spec judgment call, and the Dec-5 validation are in
    DAILIES_LEARNING_LOG.txt). Activates ONLY for a 1H/4H POI whose own
    impact happens BEFORE that day's real trading window opens (a
    "late/pre-session impact") -- the caller (compute_5m_trades) decides
    when to use this instead of the ordinary run_5m_bso/run_5m_chain;
    every same-session zone keeps using the ordinary mechanism completely
    unchanged. SELL case documented below; BUY mirrors with every
    max/high swapped for min/low (bull flag flips every such swap).

    THE PROBLEM the ordinary mechanism has here: its own `resting` swing
    is just "the FIRST confirmed SL-anchor-kind swing at/after impact" --
    fine for a same-session impact, but for a zone that impacted hours
    before the session even opens, by the time the window opens price
    may already be deep into the move, and the first confirmed swing the
    ordinary search finds can be a late, already-extended one with an
    oversized SL (a chasing entry) -- the exact complaint the user raised
    using Dec 5 as the worked example.

    THE MECHANISM (2026-10-08 SECOND REWRITE -- the first two attempts
    were both confirmed wrong by direct testing: the 2026-10-07 version
    armed on ANY swing confirming with no retracement check at all; the
    first 2026-10-08 "wait for a 50% retracement into the region" version
    was coded correctly but EMPIRICALLY PROVEN to change nothing on any
    of the 6 known real cases -- by the time a swing confirms in this
    engine's own swing-detection logic, price has typically already
    retraced past the midpoint, so that gate was always trivially
    satisfied and never actually blocked anything. User's own diagnosis
    and fix, which this implements directly: the real problem was never
    about HOW MUCH price retraces -- it's about the resulting SL SIZE.
    Gate directly on that instead):
      1. Track a running MARK = the most extreme price reached since
         impact (the LOWEST low for a SELL zone, the HIGHEST high for a
         BUY zone), ratcheting forward every time a new extreme 1-minute
         bar occurs.
      2. Track the most recently confirmed entry-trigger-kind swing (the
         SAME kind the ordinary mechanism uses as its breakout candidate
         -- a HIGH for a BUY zone, a LOW for a SELL zone).
      3. THE REAL GATE (user's own words, 2026-10-08): compute what the
         SL would be if we entered at that candidate's own price --
         `abs(mark - candidate.price)` in pips. Only arm it as the live
         entry trigger if that distance is <= PREMIUM_MAX_SL_PIPS (15.0,
         the user's own stated figure, open to adjustment). A candidate
         that would need a bigger SL than that to cover the real extreme
         since impact is skipped entirely -- we keep waiting for a
         CLOSER candidate to confirm instead of chasing an oversized-risk
         entry.
      4. If the mark extends to a NEW, more extreme price before any
         armed candidate's break fires, the armed candidate is
         RE-VALIDATED against the new mark -- if its own SL distance now
         exceeds the cap, it's disarmed and the search waits for a fresh,
         closer candidate, exactly mirroring the original spec's "if
         price keeps dropping, keep extending the mark" idea, just
         expressed as a live risk-size check instead of a region/
         retracement proxy.
      5. Entry fires on the ordinary break test (price breaking through
         the currently-armed candidate's price) -- unchanged mechanics,
         gated by the usual trading-window/session-sweep checks, exactly
         like the ordinary mechanism. This naturally covers the original
         spec's "refinement 2" (a round trip completing before the
         session opens) for free -- the mark/candidate machinery runs
         continuously from impact regardless of the window; the break
         test simply can't fire until the window opens.
      6. Item #11b's disqualifying check (prior-candle-extreme taken
         before entry) is the SAME `invalidated_at` already computed by
         structural_invalid_at() for this zone -- reused as-is.
      7. SL/TP/MFE/MAE/instant-stop/prior-4H note: delegated to the SAME
         `_minutes_extreme()` call and `_post_entry_walk()` helper the
         ordinary mechanism uses -- unchanged, so items #11/#25 apply
         here for free too. (Note: the FINAL SL, computed the normal way
         over the real impact-to-entry window, can still differ slightly
         from the mark used for the live 15-pip gate check, since the
         gate's `mark` is a running snapshot and the real SL extreme is
         recomputed fresh at entry time -- in practice these are the same
         value, since mark only ever ratchets toward the real extreme.)

    CAVEAT, stated plainly rather than hidden: this directly targets and
    fixes the "oversized SL from chasing a late, already-extended swing"
    complaint. It can ALSO mean some real, otherwise-valid continuation
    trades never fire at all, if price never comes back close enough to
    the extreme to produce a <=15-pip candidate -- that's accepted as
    the deliberate cost of the fix, not a bug, per the user's own request.
    This only ever applies inside this function, gated by
    `compute_5m_trades`'s own is_pre_session check -- it can NEVER affect
    an ordinary, same-session entry, which keeps using run_5m_bso/
    run_5m_chain completely unchanged, so same-session trades that
    legitimately need a bigger-than-15-pip SL are untouched.

    NOT built here (documented, not a silent gap): no re-entry chain for
    attempt 2+. After a plain SL under this mechanism, the window is
    necessarily already open (entries only fire inside it) and the
    "late/pre-session" condition that justified this whole mechanism no
    longer applies to a FRESH search starting from the SL's own exit
    time -- so compute_5m_trades wires attempt 2+ through the ordinary
    run_5m_chain instead, not this function again.

    Returns the same stage vocabulary as run_5m_bso, plus two premium-
    mechanism-only stages: NO_PREMIUM_RESTING (no candidate ever satisfied
    the SL-size cap before window_end) and POI_BREACHED_PRE_ENTRY (the
    zone died -- usually via #11b's own check -- before any candidate
    ever armed)."""
    bull = z.bullish
    need_cand_kind = 0 if bull else 1   # entry-trigger kind, same convention as run_5m_bso: HIGH for buy, LOW for sell

    idx0 = bisect_left(mt, impact_time)
    if idx0 >= len(minutes):
        return dict(stage="NO_5M_BAR_FOR_IMPACT")

    cand_events_all = sorted([e for e in events5_sorted if e.kind == need_cand_kind and e.at is not None],
                              key=lambda e: e.at)

    mark = None
    armed = None            # the currently-armed candidate (satisfies the SL-size cap against the CURRENT mark)
    resting_at = None       # first time any candidate ever armed (for reporting only)
    cand_ptr = 0
    replacements = 0
    entry_m = None
    stopped = False
    for i in range(idx0, len(minutes)):
        m = minutes[i]
        if m.t >= window_end:
            break
        if invalidated_at is not None and m.t >= invalidated_at:
            stopped = armed is not None
            break
        val = m.h if bull else m.l
        if mark is None or ((val > mark) if bull else (val < mark)):
            mark = val
        while cand_ptr < len(cand_events_all) and cand_events_all[cand_ptr].at <= m.t:
            candidate_ev = cand_events_all[cand_ptr]
            cand_ptr += 1
            sl_pips = abs(mark - candidate_ev.price) * 10000
            if sl_pips <= PREMIUM_MAX_SL_PIPS:
                if armed is not None:
                    replacements += 1
                else:
                    resting_at = m.t
                armed = candidate_ev
        if armed is not None and abs(mark - armed.price) * 10000 > PREMIUM_MAX_SL_PIPS:
            armed = None  # mark extended past the point this candidate's SL would still be acceptable
        if armed is None:
            continue
        if not in_trading_window(m.t, display_tz):
            continue
        if not session_sweep_satisfied(m.t, bull, minutes, mt, display_tz):
            continue
        broke = (m.h > armed.price) if bull else (m.l < armed.price)
        if broke:
            entry_m = m
            break
    if resting_at is None:
        return dict(stage="NO_PREMIUM_RESTING", mark=mark)
    if entry_m is None:
        return dict(stage="POI_BREACHED" if stopped else "NO_ENTRY_IN_WINDOW",
                    resting_at=resting_at, candidate_price=(armed.price if armed else None),
                    replacements=replacements, mark=mark)

    entry_price = armed.price
    entry_time = entry_m.t
    entry_overshoot_pips = abs((entry_m.h if bull else entry_m.l) - entry_price) * 10000
    sl_price = _minutes_extreme(mt, minutes, z.impact_time, entry_time + timedelta(minutes=1), bull)
    if sl_price is None:
        return dict(stage="NO_SL_POOL", resting_at=resting_at, entry_time=entry_time,
                    entry_price=entry_price, mark=mark)
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return dict(stage="ZERO_RISK", resting_at=resting_at, entry_time=entry_time,
                    entry_price=entry_price, sl_price=sl_price, mark=mark)
    tp_price = entry_price + 3 * risk if bull else entry_price - 3 * risk

    post = _post_entry_walk(bull, entry_time, entry_price, sl_price, tp_price, risk, minutes, mt,
                             None, h4_bars, h4_bar_starts,
                             zb=z.zb, zt=z.zt, origin_bars=origin_bars, origin_bar_starts=origin_bar_starts)
    post["entry_overshoot_pips"] = entry_overshoot_pips

    return dict(stage="ENTERED", mechanism="PREMIUM_REGION", mark=mark, resting_at=resting_at,
                replacements=replacements, entry_time=entry_time, entry_price=entry_price, sl_price=sl_price,
                tp_price=tp_price, risk=risk, **post)


def run_5m_chain(z, impact_time, bar_starts5: list, events5_sorted: list, minutes, mt: list,
                  invalidated_at, window_end, display_tz: ZoneInfo,
                  watch_levels: list[tuple[str, float]] | None = None,
                  h4_bars: list | None = None, h4_bar_starts: list | None = None,
                  origin_bars: list | None = None, origin_bar_starts: list | None = None) -> list:
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
                          display_tz, watch_levels, h4_bars=h4_bars, h4_bar_starts=h4_bar_starts,
                          origin_bars=origin_bars, origin_bar_starts=origin_bar_starts)
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
                       side: str = "ALL", h1_abandon_at=None, d_zones_full=None) -> tuple[list[dict], list[dict]]:
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

    # Item #11 (2026-10-07): ALWAYS the 4H timeframe's own bars, regardless
    # of which timeframe the zone itself belongs to -- see run_5m_bso's
    # own docstring note for the exact rule.
    h4_bars_for_note = list(h4_engine.w)
    h4_bar_starts_for_note = [b.start for b in h4_bars_for_note]

    # CONTROL (2026-10-02, user-taught; Daily-only, corrected 2026-10-04
    # -- see compute_control_timeline's own docstring and
    # DAILIES_LEARNING_LOG.txt's CONTROL section). None when d_zones_full
    # is missing (keeps any caller that doesn't pass it working exactly
    # as before, un-gated).
    control_checkpoints = (compute_control_timeline(d_zones_full, minutes, mt, display_tz, window_end)
                            if d_zones_full is not None else None)

    # item #15 (2026-10-10, tuning log): every zone impact across the
    # full Daily history, with its side -- used below to flag, for each
    # ENTERED trade, whether an OPPOSING-side zone impacted during the
    # trade's own lifetime while CONTROL was BOTH. Observational only
    # (no BE-exit resimulation yet -- that's a bigger follow-up piece);
    # this just surfaces exactly which trades qualify and when, so the
    # user can do the counterfactual math from the CSV themselves.
    all_zone_impacts = []
    if d_zones_full is not None:
        for zones in (d_zones_full.ob_zones, d_zones_full.rb_zones,
                      d_zones_full.fvg_zones, d_zones_full.vi_zones):
            for zz in zones:
                if zz.impact_time is not None:
                    all_zone_impacts.append((zz.impact_time, zz.bullish))
        all_zone_impacts.sort(key=lambda p: p[0])
    all_zone_impact_times = [p[0] for p in all_zone_impacts]

    # PDH/PDL wick-chain (2026-10-02, user-taught): replaces the plain
    # single-day sweep check for 1H abandonment -- a wick without a
    # body close carries the abandonment forward day after day instead
    # of resetting. Built once per side.
    pdh_chain = build_pdh_pdl_chain(minutes, mt, "BUY", display_tz, window_end, control_checkpoints)
    pdl_chain = build_pdh_pdl_chain(minutes, mt, "SELL", display_tz, window_end, control_checkpoints)

    def riyadh(t):
        return wob.display_iso(t, display_tz) if t else ""

    candidates = []
    for eng, tf_tag in ((h4_engine, "H4"), (h1_engine, "1H")):
        eng_bar_starts = [b.start for b in eng.w]
        for zones, ptype in ((eng.ob_zones, "OB"), (eng.rb_zones, "RB"), (eng.fvg_zones, "FVG"), (eng.vi_zones, "VI")):
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

    # item #6 (2026-10-10): did this zone form off a bar where
    # high_first() hit a genuine same-minute tie (a single 1-minute
    # candle crossing BOTH the prior bar's high and low -- no tick data
    # to say which side came first)? Flagged, never acted on -- see
    # WeeklyCombinedEngine.ambiguous_tie_bars and high_first()'s own
    # docstring for the full reasoning.
    def zone_origin_is_ambiguous(eng, z):
        origin_idx = z.candle if hasattr(z, "candle") else z.left
        return origin_idx in getattr(eng, "ambiguous_tie_bars", ())

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
                         sl_tp_conflict="", structural_notes="", h1_abandoned_riyadh="",
                         control_state_at_impact="", control_ceiling_riyadh="",
                         ambiguous_tie_origin=zone_origin_is_ambiguous(eng, z))

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
        #
        # Made PER-ZONE and bias-aware (2026-09-30, real gap caught on
        # 20 Jan): the old version computed ONE abandon time for the
        # whole day off args.default_side (a manually-typed flag), never
        # the code's own computed bias -- so it couldn't handle a day
        # where bias itself flips intraday (20 Jan: SELL until 11:10,
        # BUY after). User's own words: "if we are buying today and
        # price take previous daily high, 1h is abandoned for buying,
        # the mirror is true for sell." This only ever applies to a zone
        # IN FAVOR of the bias that was controlling AT ITS OWN IMPACT
        # MOMENT -- an opposing zone (authorized via a same-day Daily
        # ARB/ORB) lives or dies by its own invalidation only, this rule
        # doesn't touch it. Verified: 20 Jan's 1H BUY (FVG#51, impact
        # 13:21) is now correctly abandoned -- 19 Jan's high (1.16484)
        # was already swept at 06:19, well before the 11:10 flip, so 1H
        # BUY was never armed at all that day, even though 4H BUY and
        # the RB#1-authorized 1H SELL both still traded normally.
        # 2026-10-02, user instruction: the sweep check now applies on
        # EVERY day, including the impact day itself -- not just
        # react/continuation days. Previously is_react_day() gated this
        # off on a zone's own impact day (deliberately, per the 2026-09-29
        # fix); the user has now confirmed PDL/PDH can be swept at any
        # minute of the impact day too, and it must not be overlooked --
        # so the is_react_day() gate is removed, this runs unconditionally.
        # 2026-10-02, user correction: previously this only ran for
        # IN-FAVOR zones (z.bullish == controlling) -- an opposing zone
        # was explicitly exempt, by the original rule's own stated
        # scope ("lives or dies by its own invalidation only"). CONTROL
        # changes this: an opposing zone's 1H claim is explicitly
        # "subject to its own PDL/PDH check" too, same mechanism, just
        # using ITS OWN side -- so the in-favor restriction is gone, this
        # now runs for every 1H zone regardless of trend/opposing.
        if tf_tag == "1H" and d_zones_full is not None:
            zone_side = "BUY" if z.bullish else "SELL"
            zone_date = z.impact_time.astimezone(display_tz).date().isoformat()
            chain = pdh_chain if zone_side == "BUY" else pdl_chain
            zone_abandon_at = chain_abandon_at(chain, zone_date, display_tz)
            if zone_abandon_at is not None:
                eff_window_end = min(eff_window_end, zone_abandon_at)
                row_base["h1_abandoned_riyadh"] = riyadh(zone_abandon_at)

        # CONTROL (2026-10-02, user-taught, newly wired in -- not yet
        # verified against real data): is this zone's own side actually
        # holding the resource (4H or 1H) it needs, at its own impact
        # moment? Daily authorization (apply_daily_bias_gate, already
        # run before this function) is a SEPARATE, always-required gate
        # -- control is additional on top of it, not instead of it.
        if control_checkpoints is not None:
            zone_side = "BUY" if z.bullish else "SELL"
            resource = "4h" if tf_tag == "H4" else "1h"
            c_state, c_owner = control_state_at(control_checkpoints, z.impact_time)
            row_base["control_state_at_impact"] = f"{c_state}/{c_owner or '-'}"
            if resource == "4h":
                held = c_state in (zone_side, "BOTH")
            else:
                # SIMPLIFIED 2026-10-05 (user caught on 2025-01-27): 1H is
                # single-owner, full stop -- always test against whoever
                # CURRENTLY holds the slot (c_owner), same day or ten days
                # later alike. The old same-day/later-day split (2026-
                # 10-04) let a later-day BOTH authorize 1H for BOTH sides
                # via the state-based 4H-style fallback -- wrong: once the
                # slot is handed to the opposing side (a mere opposing
                # impact), the TREND side's own 1H is gone until something
                # actually re-grants it (its own fresh impact_trend, which
                # calls grant_trend() and resets owner back to it) -- it
                # does NOT passively reopen just because the calendar
                # rolled over while state is still BOTH. User's own words,
                # 2025-01-24's opposing SELL grant carrying into 01-27:
                # "buy is 4h only since Day 24, because we handed it over
                # to the selling POI, the opposing one." Re-derivation
                # confirmed this doesn't regress the original 2026-10-04
                # fix it replaces (Day 8/9/10's owner already stayed in
                # lockstep with state in every case that motivated it --
                # opp_death resets owner back to the trend side the same
                # moment state reverts, so plain owner-matching alone
                # already covered it). The separate PDL/PDH abandonment
                # chain above (zone_abandon_at) still restricts 1H further
                # from there, on top of this owner check, same as before.
                held = c_owner == zone_side
            if not held:
                ledger_rows.append(dict(row_base, stage="NO_CONTROL"))
                continue
            ceiling = control_ceiling(control_checkpoints, z.impact_time, zone_side, resource)
            if ceiling is not None:
                eff_window_end = min(eff_window_end, ceiling)
                row_base["control_ceiling_riyadh"] = riyadh(ceiling)

        # Born-violated OB/RB (2026-09-30, see mark_open_inside_trigger's
        # own docstring -- checked before anything else, same reasoning
        # as DEAD_BEFORE_WINDOW below: a zone that was never valid to
        # begin with should never reach the opposing-swing/premium
        # checks that assume a real zone.
        if getattr(z, "rejected", False):
            rejected_reason = getattr(z, "rejected_reason", "OPEN_INSIDE_ZONE")
            # item #16 (2026-10-10, tuning log): the user has observed the
            # "1H candle opens inside POI -> dead zone" rule looks wrong
            # specifically for OB (not necessarily RB). Rather than guess,
            # for every 1H OB/RB rejected THIS way, run the exact same
            # opposing-swing/premium/entry search the zone would have
            # gotten if it had NOT been rejected -- purely a side-channel
            # "what would have happened" row, never a real trade, never
            # affects the real result. Logged into the ledger under its
            # own stage so it's distinguishable from real attempts.
            # PERFORMANCE FIX (2026-10-10): this block was running for
            # EVERY rejected zone across the ENTIRE dataset's history on
            # every single call (candidates come from full, unfiltered
            # history -- only impact_time <= window_end is checked before
            # this point, never a lower bound), turning a cheap per-day
            # check into a full entry-search over years of ancient,
            # irrelevant zones. Real cause of the 7000+s/month slowdown
            # the user caught. Bounding to THIS call's own window, same
            # as every real candidate effectively is by the time it
            # reaches an entry search.
            if (tf_tag == "1H" and ptype in ("OB", "RB") and rejected_reason == "OPEN_INSIDE_ZONE"
                    and z.impact_time >= window_start):
                shadow_opp_kind = 1 if sell else 0
                shadow_opp_events = [e for e in eng.events if e.kind == shadow_opp_kind
                                      and eng.w[e.confirm].start <= z.impact_time]
                if shadow_opp_events:
                    shadow_opp = max(shadow_opp_events, key=lambda e: eng.w[e.confirm].start)
                    shadow_mid = (z.protect_level + shadow_opp.price) / 2
                    si0 = bisect_left(mt, eng.w[shadow_opp.confirm].start)
                    si1 = bisect_left(mt, z.impact_time)
                    shadow_reached = (si1 >= si0) and (
                        (max(hi[si0:si1 + 1]) >= shadow_mid) if sell else (min(lo[si0:si1 + 1]) <= shadow_mid))
                    if shadow_reached:
                        shadow_search_from = max(z.impact_time, window_start)
                        shadow_attempts = run_5m_chain(
                            z, shadow_search_from, bar_starts5, events5_sorted, minutes, mt,
                            None, eff_window_end, display_tz, None,
                            h4_bars=h4_bars_for_note, h4_bar_starts=h4_bar_starts_for_note,
                            origin_bars=eng.w, origin_bar_starts=eng_bar_starts)
                        shadow_first = shadow_attempts[0] if shadow_attempts else None
                        if shadow_first and shadow_first.get("stage") == "ENTERED":
                            ledger_rows.append(dict(
                                row_base, stage="ITEM16_SHADOW_WOULD_ENTER",
                                entry_riyadh=riyadh(shadow_first["entry_time"]),
                                entry_price=shadow_first["entry_price"], sl_price=shadow_first["sl_price"],
                                tp_price=shadow_first["tp_price"], result=shadow_first["result"],
                                exit_riyadh=riyadh(shadow_first.get("exit_time")),
                                r_multiple=(3.0 if shadow_first["result"] == "TP"
                                            else -1.0 if shadow_first["result"] == "SL" else ""),
                            ))
            ledger_rows.append(dict(row_base, stage=rejected_reason))
            continue

        # A zone carried in from a prior day (candidates now come from
        # FULL, unfiltered history -- see this function's own docstring)
        # may simply already be structurally dead by the time today's
        # window opens. Check that FIRST, before spending any more work
        # on it: an ancient, long-invalidated zone should never reach
        # the opposing-swing/premium-discount checks below at all.
        invalidated_at, reason = structural_invalid_at(z, z.impact_time, eng.w, eng_bar_starts, minutes, mt, eng.events)
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
        # Item #10 (2026-10-07): a POI whose own impact happens BEFORE
        # that day's real trading window opens ("late/pre-session
        # impact") gets the NEW premium/discount-region mechanism for its
        # FIRST attempt -- see run_5m_bso_premium's own docstring for the
        # full design. Every same-session zone (the overwhelming
        # majority) is completely untouched: is_pre_session is False and
        # this falls straight through to the exact same run_5m_chain call
        # as before this item was added.
        impact_date_str = z.impact_time.astimezone(display_tz).date().isoformat()
        imp_win_start, _ = trading_window(impact_date_str, display_tz)
        is_pre_session = ITEM10_ENABLED and (z.impact_time < imp_win_start)
        if is_pre_session:
            res1 = run_5m_bso_premium(z, z.impact_time, events5_sorted, minutes, mt,
                                       invalidated_at, eff_window_end, display_tz,
                                       h4_bars=h4_bars_for_note, h4_bar_starts=h4_bar_starts_for_note,
                                       origin_bars=eng.w, origin_bar_starts=eng_bar_starts)
            res1["attempt"] = 1
            attempts = [res1]
            # DIAGNOSTIC NOTE (2026-10-08, user-requested): since item #10
            # is being re-enabled without a proven real-world validating
            # case yet, compute what the ORDINARY mechanism alone would
            # have produced for this SAME zone (its own real baseline
            # search, from window_start) purely for comparison -- NEVER
            # used for the actual trade decision above, only recorded so
            # every real case this mechanism touches is visible and
            # auditable in the output, not silently trusted.
            baseline_search_from = max(z.impact_time, window_start)
            baseline_attempts = run_5m_chain(z, baseline_search_from, bar_starts5, events5_sorted, minutes, mt,
                                              invalidated_at, eff_window_end, display_tz, watch_levels,
                                              h4_bars=h4_bars_for_note, h4_bar_starts=h4_bar_starts_for_note,
                                              origin_bars=eng.w, origin_bar_starts=eng_bar_starts)
            b_first = baseline_attempts[0] if baseline_attempts else None
            b_stage = b_first.get("stage") if b_first else "NO_ATTEMPT"
            b_entered = b_first is not None and b_stage == "ENTERED"
            r_entered = res1.get("stage") == "ENTERED"
            if r_entered and b_entered:
                if (res1.get("entry_time") == b_first.get("entry_time")
                        and res1.get("entry_price") == b_first.get("entry_price")):
                    item10_note = "no change vs ordinary mechanism (identical entry)"
                else:
                    item10_note = (f"CHANGE: ordinary would enter {b_first.get('entry_time')} "
                                    f"@ {b_first.get('entry_price')} -> {b_first.get('result')}; "
                                    f"item #10 entered {res1.get('entry_time')} @ {res1.get('entry_price')} "
                                    f"-> {res1.get('result')}")
            elif r_entered and not b_entered:
                item10_note = (f"CHANGE: ordinary mechanism found no entry ({b_stage}); "
                                f"item #10 entered {res1.get('entry_time')} @ {res1.get('entry_price')} "
                                f"-> {res1.get('result')}")
            elif not r_entered and b_entered:
                item10_note = (f"CHANGE: ordinary mechanism would have entered {b_first.get('entry_time')} "
                                f"@ {b_first.get('entry_price')} -> {b_first.get('result')}; "
                                f"item #10 produced no entry here ({res1.get('stage')})")
            else:
                item10_note = f"no change vs ordinary mechanism (neither entered: item10={res1.get('stage')}, ordinary={b_stage})"
            res1["item10_note"] = item10_note
            if res1.get("stage") == "ENTERED" and res1.get("result") == "SL":
                exit_t1 = res1.get("exit_time")
                if exit_t1 is not None and not (invalidated_at is not None and exit_t1 >= invalidated_at):
                    # Re-entry (attempt 2+) falls back to the ORDINARY
                    # mechanism from the SL's own exit time: the window is
                    # necessarily open by now, so the pre-session
                    # condition that justified run_5m_bso_premium no
                    # longer applies to a fresh search (see that
                    # function's own docstring, "NOT built here"). Same
                    # reporting rule as any other re-entry chain: an
                    # attempt that never becomes a trade is not reported.
                    later = run_5m_chain(z, exit_t1, bar_starts5, events5_sorted, minutes, mt,
                                          invalidated_at, eff_window_end, display_tz, watch_levels,
                                          h4_bars=h4_bars_for_note, h4_bar_starts=h4_bar_starts_for_note,
                                          origin_bars=eng.w, origin_bar_starts=eng_bar_starts)
                    for n, la in enumerate(la for la in later if la.get("stage") == "ENTERED"):
                        la["attempt"] = 2 + n
                        attempts.append(la)
        else:
            search_from = max(z.impact_time, window_start)
            attempts = run_5m_chain(z, search_from, bar_starts5, events5_sorted, minutes, mt,
                                     invalidated_at, eff_window_end, display_tz, watch_levels,
                                     h4_bars=h4_bars_for_note, h4_bar_starts=h4_bar_starts_for_note,
                                     origin_bars=eng.w, origin_bar_starts=eng_bar_starts)
        for a in attempts:
            if a.get("stage") != "ENTERED":
                ledger_rows.append(dict(row_base, stage=a.get("stage"), premium_mid=f"{mid:.5f}",
                                         invalidated_riyadh=riyadh(invalidated_at), invalidated_reason=reason or "",
                                         attempt=a.get("attempt"), resting_riyadh=riyadh(a.get("resting_at")),
                                         replacements=a.get("replacements"),
                                         item10_note=a.get("item10_note", "")))
                continue
            trades_raw.append(dict(
                tf=tf_tag, poi=poi, side="SELL" if sell else "BUY", zone_bottom=z.zb, zone_top=z.zt,
                protect_level=z.protect_level, impact_time=z.impact_time, superseded_at=superseded_at,
                invalidated_at=invalidated_at, invalidated_reason=reason, premium_mid=mid,
                attempt=a.get("attempt"), resting_at=a.get("resting_at"), replacements=a.get("replacements"),
                entry_time=a["entry_time"], entry_price=a["entry_price"], sl_price=a["sl_price"],
                tp_price=a["tp_price"], risk=a["risk"], result=a["result"], exit_time=a.get("exit_time"),
                mfe=a.get("mfe"), mae=a.get("mae"), watch_hits=a.get("watch_hits") or {},
                instant_stop_pips=a.get("instant_stop_pips"), instant_stop=a.get("instant_stop", False),
                prior_4h_level=a.get("prior_4h_level"), prior_4h_taken_at=a.get("prior_4h_taken_at"),
                mechanism=a.get("mechanism", ""), premium_mark=a.get("mark"), item10_note=a.get("item10_note", ""),
                ambiguous_tie_origin=row_base.get("ambiguous_tie_origin", False),
                entry_overshoot_pips=a.get("entry_overshoot_pips"),
                item4_body_close_in_poi_at=a.get("item4_body_close_in_poi_at"),
                # item #9 (2026-10-10, tuning log): did the PDH/PDL 1H
                # abandonment rule actually restrict this zone's search
                # window before it entered? Pure visibility -- how often
                # does this rule bind in practice -- sequenced ahead of
                # investigating whether to loosen it, per the user's own
                # order (item #1 first, then item #9).
                item9_h1_abandoned_riyadh=row_base.get("h1_abandoned_riyadh", ""),
                # item #1 (2026-10-10, tuning log): a 1H trade taken on the
                # OPPOSING side (CONTROL state BOTH -- the trend side would
                # otherwise hold 1H alone) is flagged if it entered on a
                # LATER calendar day than the zone's own impact. The
                # user's proposed rule: 1H opposing trades should only be
                # allowed on the impact day itself. Observational only --
                # the trade is NOT rejected, just flagged for later
                # filtering/analysis.
                item1_would_reject=(
                    tf_tag == "1H"
                    and str(row_base.get("control_state_at_impact", "")).startswith("BOTH")
                    and a["entry_time"].astimezone(display_tz).date()
                        != z.impact_time.astimezone(display_tz).date()
                ),
                pre_impact_swing_price=opp.price,
                control_state_at_impact=row_base.get("control_state_at_impact", ""),
                control_ceiling=row_base.get("control_ceiling_riyadh", ""),
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
        # Note #2 (2026-10-07, item #25): "instant-stop" -- an SL-hit trade
        # whose SL distance was INSTANT_STOP_THRESHOLD_PIPS (2) or less.
        # Tracked, never changes entry/exit/SL/TP. Real example on file:
        # 2025-11-03 H4 SELL OB#74 (entry 19:36 @ 1.15268, SL 20:14 @
        # 1.15315) -- its real SL distance is 4.7 pips, ABOVE the 2-pip
        # threshold, so it correctly does NOT fire under this rule as
        # specified (flagged explicitly in DAILIES_LEARNING_LOG.txt: the
        # user's own "~1-2 pips" recollection was an approximation, not
        # the literal number -- the 2-pip threshold is applied exactly as
        # instructed, not loosened to force this example to match).
        if first.get("instant_stop"):
            notes.append(f"instant-stop: SL only {first['instant_stop_pips']:.1f} pips from entry")
        # Note #3 (2026-10-07, item #11): did price take the prior 4H
        # candle's high (BUY)/low (SELL) between entry and exit -- data
        # collection only, see run_5m_bso's own docstring for the rule.
        if first.get("prior_4h_taken_at") is not None:
            notes.append(f"took prior-4H {'high' if first['side'] == 'BUY' else 'low'} "
                         f"({first['prior_4h_level']:.5f}) at {riyadh(first['prior_4h_taken_at'])} RYD")
        # Note #4 (2026-10-07, item #10): flag any trade entered via the
        # new premium/discount-region mechanism (pre-session impact).
        # (Correction 2026-10-08: briefly misread this as a key-name bug --
        # "premium_mark" IS the right field here, trades_raw renames the
        # attempt dict's own "mark" to "premium_mark" at construction time,
        # a few lines below where this note is built from "first"/members.
        # No bug; reverted that change.)
        if first.get("mechanism") == "PREMIUM_REGION":
            mk = first.get("premium_mark")
            notes.append(f"item #10 premium/discount-region mechanism (mark {mk:.5f})" if mk is not None
                         else "item #10 premium/discount-region mechanism")
            # Diagnostic note (2026-10-08, user-requested): since item #10
            # is being re-enabled without a proven real-world validating
            # case, every trade it touches carries a direct comparison
            # against what the ordinary mechanism alone would have done --
            # see compute_5m_trades' own item10_note computation.
            if first.get("item10_note"):
                notes.append(first["item10_note"])
        # Note #5 (2026-10-10, item #6): this trade's zone formed off a
        # bar whose swing order was a genuine OHLC tie -- no tick data to
        # confirm which side was actually touched first, so the engine's
        # heuristic (body direction) was used. Flagged for visibility,
        # never changes the trade itself.
        if any(m.get("ambiguous_tie_origin") for m in members):
            notes.append("item #6: zone formed off an ambiguous same-minute candle "
                         "(no tick data to confirm swing order)")
        # Note #6 (2026-10-10, item #5): entry barely overshot the trigger
        # level (<=1 pip) before the trade ultimately went to SL --
        # candidate optimization signal, observational only.
        overshoot = first.get("entry_overshoot_pips")
        if overshoot is not None and overshoot <= 1.0 and result == "SL":
            notes.append(f"item #5: entry overshot trigger by only {overshoot:.1f} pip(s) before SL")
        # Note #7 (2026-10-10, item #4): did the originating POI's own
        # timeframe candle body-close back inside the zone after entry --
        # candidate optimization signal, observational only.
        if first.get("item4_body_close_in_poi_at") is not None:
            notes.append(f"item #4: POI body-closed back inside zone at "
                         f"{riyadh(first['item4_body_close_in_poi_at'])} RYD after entry")
        # Note #8 (2026-10-10, item #1): a 1H opposing-side trade entered
        # on a LATER day than its zone's own impact -- under the user's
        # proposed stricter rule, this trade would not have been taken.
        if first.get("item1_would_reject"):
            notes.append("item #1: would be rejected under 1H-opposing-impact-day-only rule "
                         "(entered on a later day than impact)")
        # Note #9 (2026-10-10, item #9): the PDH/PDL 1H abandonment rule
        # actually restricted this trade's search window before it
        # entered -- visibility only, how often this rule binds.
        if first.get("item9_h1_abandoned_riyadh"):
            notes.append(f"item #9: 1H abandonment rule restricted search window "
                         f"(abandoned at {first['item9_h1_abandoned_riyadh']} RYD)")
        # Note #10 (2026-10-10, item #15): did an OPPOSING-side zone
        # impact during this trade's own lifetime while CONTROL was BOTH?
        # Flagged only -- no BE-exit resimulation yet.
        if all_zone_impact_times and control_checkpoints is not None:
            seg_end = exit_t or minutes[-1].t
            lo_i = bisect_right(all_zone_impact_times, first["entry_time"])
            hi_i = bisect_right(all_zone_impact_times, seg_end)
            our_bull = first["side"] == "BUY"
            for imp_t, imp_bull in all_zone_impacts[lo_i:hi_i]:
                if imp_bull != our_bull:
                    c_state, _ = control_state_at(control_checkpoints, imp_t)
                    if c_state == "BOTH":
                        notes.append(f"item #15: opposing-side zone impacted at {riyadh(imp_t)} RYD "
                                     f"while in this trade (CONTROL BOTH)")
                        break
        structural_notes = "; ".join(notes)

        trades.append(dict(
            side=first["side"], entry_time=first["entry_time"], entry_price=first["entry_price"],
            sl=first["sl_price"], tp=first["tp_price"], r_pips=first["risk"] * 10000,
            impact_time=min(m["impact_time"] for m in members),
            poi_sources=[m["poi"] for m in members],
            mfe_pips=first.get("mfe", 0.0) * 10000, mae_pips=first.get("mae", 0.0) * 10000,
            sl_hit_riyadh=sl_hit_riyadh, tp_hit_riyadh=tp_hit_riyadh, structural_notes=structural_notes,
            instant_stop_pips=first.get("instant_stop_pips"), instant_stop=bool(first.get("instant_stop")),
            prior_4h_taken_at=first.get("prior_4h_taken_at"),
            mechanism=first.get("mechanism", ""),
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
            instant_stop_pips=f"{first['instant_stop_pips']:.1f}" if first.get("instant_stop_pips") is not None else "",
            instant_stop="YES" if first.get("instant_stop") else "",
            prior_4h_taken_riyadh=riyadh(first.get("prior_4h_taken_at")) if first.get("prior_4h_taken_at") else "",
            mechanism=first.get("mechanism", ""),
            control_state_at_impact="/".join(dict.fromkeys(m["control_state_at_impact"] for m in members)),
            control_ceiling_riyadh="/".join(dict.fromkeys(m["control_ceiling"] for m in members if m["control_ceiling"])),
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
    "instant_stop", "instant_stop_pips", "prior_4h_taken_riyadh", "mechanism",
    "control_state_at_impact", "control_ceiling_riyadh",
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
    used everywhere else in this file for exactly that lookup).

    CORRECTION (2026-10-02, user): the check compares the impact
    candle's open to the POI's own ZONE (zb/zt) -- the zone itself just
    differs by type (OB zone = origin candle's body, RB zone = origin
    candle's wick, FVG zone = the gap), but the check itself is the
    same for all three. The earlier "FVG has no equivalent concept"
    exclusion was an unexamined assumption, never actually taught --
    FVG zones have real zb/zt boundaries exactly like OB/RB, so the
    same born-dead check applies. Now runs on OB, RB, AND FVG, at every
    timeframe (Daily/4H/1H). Reuses the SAME `rejected` field, so every
    existing `getattr(z, "rejected", False)` check (drawing, table,
    ledger) picks this up with no other change."""
    bar_starts = [b.start for b in engine.w]
    for zones in (engine.ob_zones, engine.rb_zones, engine.fvg_zones, engine.vi_zones):
        for z in zones:
            if z.rejected or z.impact_time is None:
                continue
            impact_idx = bisect_right(bar_starts, z.impact_time) - 1
            if not (0 <= impact_idx < len(engine.w)):
                continue
            impact_open = engine.w[impact_idx].o
            if z.zb <= impact_open <= z.zt:
                z.rejected = True
                z.rejected_reason = "OPEN_INSIDE_ZONE"


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
    engine.vi_zones = [z for z in engine.vi_zones if wc.vi_status(z) != "OVI"]


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
    for zones in (engine.ob_zones, engine.rb_zones, engine.fvg_zones, engine.vi_zones):
        for z in zones:
            z.superseded_at = None

    all_zones = list(engine.ob_zones) + list(engine.rb_zones) + list(engine.fvg_zones) + list(engine.vi_zones)
    bar_starts = [b.start for b in engine.w]

    for bull in (True, False):
        impacted = sorted(
            (z for z in all_zones if z.bullish == bull and z.impact_time is not None and z.protect_level is not None),
            key=lambda z: z.impact_time)
        active = None
        for z in impacted:
            if active is not None:
                inv_at, _ = structural_invalid_at(active, active.impact_time, engine.w, bar_starts, minutes, mt, engine.events)
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


def zone_is_infavor(z) -> bool:
    """True if a zone is CURRENTLY classified in-favor (state 0) -- its
    present effective state, not its frozen birth tag. Real bug fixed
    2026-10-04 (user caught it directly, demanded evidence, and was
    right): this used to check `created_state` (OB/RB) / `origin` (FVG)
    -- fields set ONCE at creation and never updated -- so a zone born
    Aggressive/AIFOB/AIRB and later PROMOTED to real in-favor before it
    ever impacted was permanently misclassified as not-in-favor forever.
    Verified on real data: OB#344 and RB#429 (both 2025-01-06) were each
    born state 4 (Aggressive-In-Favor) and promoted to state 0 before
    impacting (RB#429: pre_spent_state=0, promotion_from_state=4) -- the
    old check still read their birth tag (4) and wrongly excluded both
    from a downtrend's "bearish in-favor POIs impacted" count. Fixed to
    use the same current-effective-state pattern already used by
    ob_status/rb_status/fvg_status/vi_status: pre_spent_state once the
    zone has gone SPENT (state 3), else its current state -- correct for
    OB, RB, FVG and VI alike, no per-type field-name special-casing
    needed."""
    state = z.pre_spent_state if z.state == 3 else z.state
    return state == 0


def daily_controlling_bias(d_zones_full, as_of: "datetime", minutes=None, mt: list | None = None):
    """Whichever side is genuinely in control as of `as_of`.

    User's own correction (2026-09-30), overriding two earlier same-day
    attempts at this function: "there is no a day without a bias. the
    bias was sell from 12 to 20, at the exact minute swing high was
    taken. trading setups is a different story. the in favor... POI
    control creates setup not necessarily bias." Bias is CONTINUOUS --
    it doesn't go "undefined" just because the specific POI that
    originally signaled it later goes spent/invalidated. A POI going
    spent is a SETUP-level fact (is this zone still tradeable), entirely
    separate from bias (which direction the day/trend is in). The two
    earlier versions of this function wrongly conflated them: v1 picked
    the latest in-favor POI impact with no invalidation check at all
    (right, but for the wrong reason -- it just never thought to check);
    v2 "fixed" that by requiring the picked POI to still be alive, which
    was actually a regression -- it made FVG#1 going spent on 15 Jan
    (a real, correct SETUP-level event) wrongly blank out BIAS for the
    following 4 days, when the real answer is bias just stayed SELL
    straight through, unaffected.

    The real, current model: an in-favor Daily POI impact sets bias
    (this is how it starts) and a Daily MSS is the ONLY thing that ever
    flips it -- POI invalidation afterward is irrelevant to bias. So:
    if any Daily MSS has happened at/before `as_of`, bias is that MSS's
    own direction (the LATEST one, timestamped to its real M1 minute --
    MSS doesn't carry that itself, found the same way Event.at is:
    first minute price crosses the MSS's own broken level). If no MSS
    has happened yet, bias falls back to the LATEST in-favor Daily POI
    impact at/before `as_of`, full stop -- no invalidation check, no
    "is it still alive" question, since that question doesn't apply to
    bias at all. Verified: 15-19 Jan now correctly reads SELL throughout
    (off FVG#1, despite it going spent 15 Jan) instead of the wrong
    "undefined" gap; 20 Jan still correctly flips to BUY at 11:10, the
    real MSS_UP minute."""
    # Multi-year history fix (2026-10-03, real bug a full-2021-2026 run
    # exposed -- a 6-week window never had enough zones/MSS/minutes for
    # this to matter): this used to re-walk minute-by-minute, from each
    # Daily MSS's own break forward, to find that MSS's confirming
    # minute -- EVERY TIME this function is called, i.e. once per 4H/1H
    # zone (apply_daily_bias_gate calls this for every zone with an
    # impact_time). A MSS's confirming minute is a fixed fact, totally
    # independent of `as_of` -- as_of only decides whether that fixed
    # minute counts for THIS query. So compute it once per MSS, cached
    # on d_zones_full itself (same object reused across every zone/every
    # 4H+1H call in one run), and reuse the cached, already-sorted list
    # from then on -- O(zones x MSS) instead of O(zones x MSS x minutes).
    mss_confirms = getattr(d_zones_full, "_mss_confirm_cache", None)
    if mss_confirms is None and minutes is not None and mt is not None \
            and hasattr(d_zones_full, "msses") and hasattr(d_zones_full, "w"):
        mss_confirms = []
        for x in d_zones_full.msses:
            broken_start = d_zones_full.w[x.broken].start
            idx = bisect_right(mt, broken_start)
            for m in minutes[idx:]:
                if (m.h > x.price) if x.up else (m.l < x.price):
                    mss_confirms.append((m.t, x.up))
                    break
        mss_confirms.sort(key=lambda c: c[0])
        d_zones_full._mss_confirm_cache = mss_confirms
    if mss_confirms:
        confirm_times = [c[0] for c in mss_confirms]
        pos = bisect_right(confirm_times, as_of)
        if pos > 0:
            return mss_confirms[pos - 1][1]

    candidates = []
    for zones in (d_zones_full.ob_zones, d_zones_full.rb_zones, d_zones_full.fvg_zones, d_zones_full.vi_zones):
        for dz in zones:
            if dz.impact_time is None or dz.impact_time > as_of or not zone_is_infavor(dz):
                continue
            candidates.append((dz.impact_time, dz.bullish))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1]


def daily_opposite_impacted_today(d_zones_full, opposite_bull: bool, date_str: str, display_tz: ZoneInfo) -> bool:
    """True if a Daily POI of `opposite_bull`'s side itself impacted on
    THIS SPECIFIC calendar day -- the real ARB/ORB-authorizes-1H
    mechanism (15 Jan: the ARB impacting that same day is what reopened
    1H BUY, not a coincidental 1H-level structure)."""
    win_start, win_end = calendar_day_bounds(date_str, display_tz)
    for zones in (d_zones_full.ob_zones, d_zones_full.rb_zones, d_zones_full.fvg_zones, d_zones_full.vi_zones):
        for dz in zones:
            if dz.bullish == opposite_bull and dz.impact_time is not None and win_start <= dz.impact_time < win_end:
                return True
    return False


def apply_daily_bias_gate(engine, tf_tag: str, d_zones_full, display_tz: ZoneInfo,
                           minutes=None, mt: list | None = None, control_checkpoints: list | None = None) -> None:
    """User's own correction (2026-09-30, real bug -- not a display
    preference): "we never think of Buy in a Sell day... ONLY Daily
    Timeframe related events decide the bias of that day or moment, and
    based on that we look for 4h and 1h setups." A 4H/1H zone opposite
    the day's Daily-controlled bias was previously allowed to show and
    trade off nothing more than its own coincidental same-timeframe
    structure (e.g. a 1H MSS_UP) -- caught on 14 Jan's RB#87, a BUY
    setup with zero Daily-level authorization (zero Daily POIs of
    either side impacted that day at all) that still showed and traded
    under --default-side ALL. Fixed the same way mark_open_inside_trigger
    does: sets the SAME `z.rejected` flag (reused, not a new field), so
    drawing, table, and ledger all pick this up automatically with no
    other change needed.

    Rule: a zone in favor of the day's Daily-controlled bias is always
    fine. A zone OPPOSITE it is:
      - 4H: NEVER allowed, period -- 4H only ever trades the day's own
        bias, no exceptions (already an established rule, now actually
        enforced in code instead of just conceptually true).
      - 1H: allowed ONLY if a Daily POI of that SAME opposite side
        itself impacted on the SAME calendar day as this zone's own
        impact -- the real ARB/ORB mechanism, not a same-timeframe
        coincidence. Verified: 14 Jan has zero Daily impacts of any
        kind, so RB#87 is now correctly rejected; 15 Jan's real ARB
        (Daily, impacted that same day) still correctly authorizes
        that day's 1H BUY zones."""
    for zones in (engine.ob_zones, engine.rb_zones, engine.fvg_zones, engine.vi_zones):
        for z in zones:
            if getattr(z, "rejected", False) or z.impact_time is None:
                continue
            controlling = daily_controlling_bias(d_zones_full, z.impact_time, minutes, mt)
            if controlling is None:
                # 2026-10-02, user correction: "4H/1H setups only exist
                # within whatever bias Daily has already decided" means
                # NO bias yet blocks BOTH sides -- it is not the same as
                # "already in favor." The old `controlling is None or
                # z.bullish == controlling: continue` treated a true
                # cold start (no Daily fact -- no confirmed swing, no
                # POI impact, no MSS -- has happened yet) as free-pass
                # approval for either direction. Caught on the first
                # real walk-forward dataset (2025-01-02 start): 1H
                # OB#10 traded BUY on 3 Jan 2025, four days before the
                # Daily even confirmed its first swing, let alone set a
                # bias (the first real Daily fact, FVG#2's impact, was
                # 14 Jan). A trend nobody has read yet cannot authorize
                # a trade in either direction.
                z.rejected = True
                z.rejected_reason = "NO_DAILY_BIAS_YET"
                continue
            if z.bullish == controlling:
                continue  # already in favor -- fine
            # Real bug fixed 2026-10-04 -- user's own correction, verbatim:
            # "we had the second RB impacted yesterday, it was not
            # breached, it still authorizes to buy... authorization is
            # only lost with breach or encountering in favor POI while
            # opposing with in control." The same-day-only check below
            # (daily_opposite_impacted_today) predates CONTROL and only
            # ever asked "did a Daily POI of this side impact TODAY" --
            # it had no idea an opposing zone from days ago was still
            # alive and un-breached, so it wrongly re-demanded a fresh
            # same-day impact every single day. CONTROL already tracks
            # exactly this (persists until opp_death or trend reclaiming
            # it), so authorization is now read directly from CONTROL's
            # own state instead of re-derived from "today" alone.
            if control_checkpoints is not None:
                c_state, _ = control_state_at(control_checkpoints, z.impact_time)
                side = "BUY" if z.bullish else "SELL"
                if c_state not in (side, "BOTH"):
                    z.rejected = True
                    z.rejected_reason = "NO_DAILY_AUTHORIZATION"
            else:
                date_str = z.impact_time.astimezone(display_tz).date().isoformat()
                if not daily_opposite_impacted_today(d_zones_full, z.bullish, date_str, display_tz):
                    z.rejected = True
                    z.rejected_reason = "NO_DAILY_AUTHORIZATION"


def find_parent_daily_poi(d_engine, side_bull: bool, child_impact_time: "datetime"):
    """The Daily POI that was 'active' (per mark_superseded_same_leg) at
    the moment a 4H/1H zone impacted -- the LATEST same-direction Daily
    POI whose own impact happened at/before child_impact_time and that
    hadn't yet been superseded by then. (None, None) if no such Daily
    POI exists (e.g. the child's own leg has no Daily-level driver
    impacted yet)."""
    candidates = []
    for zones, ptype in ((d_engine.ob_zones, "OB"), (d_engine.rb_zones, "RB"), (d_engine.fvg_zones, "FVG"),
                         (d_engine.vi_zones, "VI")):
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
        # Pre-week-open data in this CSV is not real trading (user's own
        # call, 2026-09-29: "there is no 11 Jan... maybe we have Sunday
        # gap data in the CSV but it is fake") -- stripped unconditionally,
        # everywhere, before any aggregation/swing/POI/entry logic ever
        # sees it. Fixed 2026-10-05: the old version only dropped Riyadh-
        # calendar Sunday, which missed a leftover thin hour (Riyadh
        # Monday 00:00-00:59 in winter) that's still before the real
        # 01:00/00:00 (winter/summer) week open -- see after_week_open()
        # for the exact rule and the real-tick-count evidence. This is a
        # fixed time boundary, never a tick-count/liquidity cutoff.
        minutes, dropped_count = strip_pre_week_open(minutes, display_tz)
        if dropped_count:
            print(f"Dropped {dropped_count} pre-week-open minutes (not real trading data)")
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
            # origin_gap_window=None -- see WeeklyCombinedEngine's own
            # comment; Daily/4H/1H are never real Weekly bars, so the
            # 5-day weekend-gap search must not apply to them.
            engine = wc.WeeklyCombinedEngine(minutes, bars_by_tag[tag], origin_gap_window=None)
            engine.run()
            mark_open_inside_trigger(engine)
            mark_superseded_same_leg(engine, minutes, mt_all)
            if tag in ("h4", "h1") and d_zones_full is not None:
                # Daily-only bias gate (2026-09-30, real bug -- see
                # apply_daily_bias_gate's own docstring): 4H/1H setups
                # only exist within whatever bias Daily has already
                # decided, never on their own separate justification.
                # gate_control_checkpoints computed once, right after
                # d_zones_full is ready (2026-10-04, see
                # apply_daily_bias_gate's own docstring for why this
                # replaces the old same-day-only authorization check).
                apply_daily_bias_gate(engine, tag, d_zones_full, display_tz, minutes, mt_all,
                                       control_checkpoints=gate_control_checkpoints)
            if tag in ("h4", "h1"):
                exclude_old_intraday_zones(engine)
                # Full (unfiltered) snapshot for compute_5m_trades' own
                # candidate search -- a POI impacted on a PRIOR day but
                # still alive today (the "react day" case) must still be
                # considered, which filter_to_date_range() below would
                # otherwise silently drop entirely (2026-09-29).
                tf_full[tag] = SimpleNamespace(ob_zones=list(engine.ob_zones), rb_zones=list(engine.rb_zones),
                                                fvg_zones=list(engine.fvg_zones), vi_zones=list(engine.vi_zones),
                                                events=engine.events, w=engine.w)
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
                                                fvg_zones=list(engine.fvg_zones), vi_zones=list(engine.vi_zones),
                                                w=engine.w, events=engine.events,
                                                msses=list(engine.msses))
                # Computed once, right here, so apply_daily_bias_gate (for
                # both h4 and h1 below) can authorize off CONTROL's own
                # persistent state instead of a same-day-only re-check --
                # see apply_daily_bias_gate's own docstring (2026-10-04 fix).
                gate_control_checkpoints = compute_control_timeline(d_zones_full, minutes, mt_all, display_tz, cutoff_utc)
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
            if args.show_date and tag == "h1":
                filter_to_date_range(engine, since_date, args.show_date, display_tz)
            elif args.show_date and tag == "h4":
                # 4H uses the FULL continuous calendar span, not 1H's
                # discontinuous trading-window filter -- see
                # filter_to_calendar_span()'s own docstring.
                filter_to_calendar_span(engine, since_date, args.show_date, display_tz)
            engines[tag] = engine
            raw_lines[tag] = build_one(base, engine, args, display_tz, tag)

        trades = []
        e5 = None
        ledger_rows = []
        if args.show_date:
            bars5 = dc.aggregate_minutes(minutes, 5)
            e5 = wc.WeeklyCombinedEngine(minutes, bars5, origin_gap_window=None)
            e5.run()
            window_start, _ = trading_window(since_date, display_tz)
            _, window_end = trading_window(args.show_date, display_tz)

            # 1H abandonment is now computed PER-ZONE, bias-aware, inside
            # compute_5m_trades itself (see its own comment there) --
            # handles a day whose bias flips intraday, which a single
            # day-wide side flag never could.
            trades, ledger_rows = compute_5m_trades(tf_full["h4"], tf_full["h1"], e5, minutes,
                                                      window_start, window_end, display_tz,
                                                      side=args.default_side, d_zones_full=d_zones_full)

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
                  f"RB={len(e.rb_zones)} FVG={len(e.fvg_zones)} VI={len(e.vi_zones)})")

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
