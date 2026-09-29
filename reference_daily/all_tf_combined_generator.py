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
from bisect import bisect_left, bisect_right
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


def filter_to_window(engine, win_start: "datetime", win_end: "datetime") -> None:
    """Keep only what's actually active inside [win_start, win_end). This
    mutates the engine's own zone/event lists in place, before
    write_combined_pine ever sees them, so it needs no changes to the
    shared draw code.

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


def filter_to_date(engine, date_str: str, display_tz: ZoneInfo) -> None:
    """H4/1H scoping: the narrow real trading window (10:00-20:00 /
    11:00-21:00 Riyadh, see trading_window()) -- NOT the whole calendar
    day. Different from --as-of, which keeps everything ACCUMULATED up
    to that day (so a swing from three months earlier still shows)."""
    win_start, win_end = trading_window(date_str, display_tz)
    filter_to_window(engine, win_start, win_end)


def filter_to_calendar_day(engine, date_str: str, display_tz: ZoneInfo) -> None:
    """Daily scoping is deliberately WIDER than filter_to_date()'s narrow
    trading window (2026-09-29, real bug the user caught: the Daily POI
    that sets a whole day's bias can impact at ANY hour, including
    before the trading window even opens -- the 12 Jan 2026 walk-through
    earlier this project used exactly such a Daily FVG, impacted well
    before the 11:00 Riyadh open, to set that day's SELL bias. Scoping
    Daily to the narrow window like H4/1H silently dropped it: Daily
    showed 0 POIs no matter what the Daily settings toggles were set to,
    since there was nothing left in engine.ob_zones/rb_zones/fvg_zones
    for them to filter. Scope is the full calendar day (00:00-24:00
    Riyadh) instead -- still per-day, just not per-session."""
    y, m, d = (int(x) for x in date_str.split("-"))
    win_start = datetime(y, m, d, 0, 0, 0, tzinfo=display_tz).astimezone(UTC)
    win_end = win_start + timedelta(days=1)
    filter_to_window(engine, win_start, win_end)


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
               invalidated_at, window_end) -> dict:
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
    reason instead of a bare skip."""
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
    for i in range(bisect_left(mt, entry_time) + 1, len(minutes)):
        m = minutes[i]
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
                tp_price=tp_price, risk=risk, result=result or "OPEN", exit_time=exit_time)


def run_5m_chain(z, impact_time, bar_starts5: list, events5_sorted: list, minutes, mt: list,
                  invalidated_at, window_end) -> list:
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
        res = run_5m_bso(z, search_from, bar_starts5, events5_sorted, minutes, mt, invalidated_at, window_end)
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


def compute_5m_trades(h4_engine, h1_engine, e5, minutes, window_end, display_tz,
                       side: str = "ALL") -> tuple[list[dict], list[dict]]:
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
    didn't this POI trade" never again needs a one-off script."""
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
                         entry_riyadh="", entry_price="", sl_price="", tp_price="", risk_price="",
                         r_pips="", result="", exit_riyadh="", r_multiple="", sl_tp_conflict="")

        # Same-leg supersession (see mark_superseded_same_leg): a later
        # same-direction, unbroken-leg POI caps how much longer THIS zone
        # may still search for a NEW entry -- not a hard skip, so a real
        # entry this zone already found before the newer POI's own
        # impact still stands.
        superseded_at = getattr(z, "superseded_at", None)
        eff_window_end = min(window_end, superseded_at) if superseded_at is not None else window_end
        row_base["superseded_riyadh"] = riyadh(superseded_at)

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

        invalidated_at, reason = structural_invalid_at(z, z.impact_time, eng.w, eng_bar_starts, minutes, mt)
        attempts = run_5m_chain(z, z.impact_time, bar_starts5, events5_sorted, minutes, mt,
                                 invalidated_at, eff_window_end)
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
        trades.append(dict(
            side=first["side"], entry_time=first["entry_time"], entry_price=first["entry_price"],
            sl=first["sl_price"], tp=first["tp_price"], r_pips=first["risk"] * 10000,
            impact_time=min(m["impact_time"] for m in members),
            poi_sources=[m["poi"] for m in members],
        ))
        result = first["result"]
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
            risk_price=f"{first['risk']:.5f}", r_pips=f"{first['risk'] * 10000:.1f}",
            result=result or "", exit_riyadh=riyadh(first.get("exit_time")),
            r_multiple="+3.00" if result == "TP" else ("-1.00" if result == "SL" else ""),
            sl_tp_conflict="YES" if sl_tp_conflict else "",
        ))

    return sorted(trades, key=lambda t: t["entry_time"]), ledger_rows


LEDGER_FIELDS = [
    "tf", "poi", "side", "zone_bottom", "zone_top", "protect_level",
    "impact_riyadh", "superseded_riyadh", "invalidated_riyadh", "invalidated_reason", "premium_mid",
    "attempt", "stage", "resting_riyadh", "replacements",
    "entry_riyadh", "entry_price", "sl_price", "tp_price", "risk_price", "r_pips",
    "result", "exit_riyadh", "r_multiple", "sl_tp_conflict",
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
        'if barstate.islast and onFive and showTrades and array.size(trSide) > 0',
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
        '        box.new(eX, math.max(slY, eY), eX + boxRightOffset, math.min(slY, eY), border_color=color.red, border_width=1, bgcolor=color.new(color.red, 85), xloc=xloc.bar_time)',
        '        box.new(eX, math.max(eY, tpY), eX + boxRightOffset, math.min(eY, tpY), border_color=color.green, border_width=1, bgcolor=color.new(color.green, 85), xloc=xloc.bar_time)',
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

        mt_all = [m.t for m in minutes]

        engines = {}
        raw_lines = {}
        for tag, tf_period, title in TIMEFRAMES:
            engine = wc.WeeklyCombinedEngine(minutes, bars_by_tag[tag])
            engine.run()
            mark_superseded_same_leg(engine, minutes, mt_all)
            if tag in ("h4", "h1"):
                exclude_old_intraday_zones(engine)
            if args.show_date:
                if tag == "d":
                    filter_to_calendar_day(engine, args.show_date, display_tz)
                else:
                    filter_to_date(engine, args.show_date, display_tz)
            engines[tag] = engine
            raw_lines[tag] = build_one(base, engine, args, display_tz, tag)

        trades = []
        e5 = None
        ledger_rows = []
        if args.show_date:
            bars5 = dc.aggregate_minutes(minutes, 5)
            e5 = wc.WeeklyCombinedEngine(minutes, bars5)
            e5.run()
            _, window_end = trading_window(args.show_date, display_tz)
            trades, ledger_rows = compute_5m_trades(engines["h4"], engines["h1"], e5, minutes, window_end,
                                                      display_tz, side=args.default_side)

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

        # Cross-timeframe context (2026-09-28): "the daily FVG we are
        # trading from" should be visible on 4H/1H, and "the 1H OB/RB we
        # are trading from" on 5m -- not just on their own native chart.
        # Daily's own gate is simply widened to also fire on 4H/1H,
        # reusing Daily's OWN settings group (no new group needed: it's
        # the same POI data either way, and Daily's own Side/Focus/etc.
        # already govern it regardless of which chart is open). 4H/1H
        # projected onto 5m is different -- that needs its OWN
        # independent settings group (see project_poibox_block), so
        # toggling Side/Inspect-one/etc. for the 5m view never silently
        # also changes the 4H or 1H chart's own display.
        gate_by_tag = {"d": "(onD or onH4 or onH1)", "h4": "onH4", "h1": "onH1"}

        bodies = []
        own_maxvals = {}
        for tag, tf_period, title in TIMEFRAMES:
            own_maxval = extract_maxval(raw_lines[tag][:split_idx])
            own_maxvals[tag] = own_maxval
            own_inputs = build_own_inputs(shared_input_lines, tag, title, own_maxval, args.default_side)
            body = own_inputs + raw_lines[tag][split_idx:]
            body = rename_arrays(body, tag)
            body = inject_input_params(body, tag)
            body = regate(body, gate_by_tag[tag])
            body = collapse_pack_blocks(body)
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

        # Patch the shared f_drawPoiBox definition to take the 4 inputs as
        # real parameters instead of closing over a single global set (see
        # inject_input_params -- every call site already passes them now).
        header = [
            ln.replace(
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, dashed, filled) =>',
                'f_drawPoiBox(left, top, bottom, fallbackRight, hasImp, impX, colCode, rank, grank, bull, total, gTotal, dashed, filled, sideFilterP, inspectOnePoiP, focusPoiP, poiFromLastP, countFromStartP, impactColorP) =>',
            ).replace(
                'line.new(boxRight, array.get(bottom, i), boxRight, array.get(top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(color.red, 30), width=1)',
                'line.new(boxRight, array.get(bottom, i), boxRight, array.get(top, i), xloc=xloc.bar_time, extend=extend.both, color=color.new(impactColorP, 30), width=1)',
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
        final_lines = header + m5_inputs
        for body in bodies:
            final_lines += body
        final_lines += h4_on5 + h1_on5
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
            filter_to_date(e5, args.show_date, display_tz)
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
