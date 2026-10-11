#!/usr/bin/env python3
"""Phase 3 report builder: turns one month's verify_day batch run into the
locked 4-column (Date/Bias/Setups/Entries) markdown section, matching
DAILIES_DAYBYDAY_REPORT.txt's existing style.

Usage: python3 build_report.py YEAR MONTH [lead_months]
Prints the markdown section to stdout.
"""
import sys, calendar, time, os
# Portable path: this file lives in the repo root itself, so reference_daily
# is a direct child -- works regardless of where the repo was cloned
# (Windows, Mac, Linux).
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_REPO_ROOT, "reference_daily"))
import verify_day as vd
import all_tf_combined_generator as atc
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

RYD = ZoneInfo("Asia/Riyadh")
MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def hhmm(t):
    return t.astimezone(RYD).strftime("%H:%M")


def state_label(state, owner):
    if state == "BOTH":
        return f"BOTH (1H {owner})"
    return state


def short_reason(reason, side_hint=None):
    if reason.startswith("opposing POI impacted"):
        return "opposing zone hit"
    if reason.startswith("opposing POI respected"):
        return "opposing zone respected"
    if reason.startswith("opposing zone death"):
        return "opposing zone died"
    if reason.startswith("trend POI impacted"):
        return "trend zone hit"
    if reason.startswith("trend zone tactical death") and "no trend POI left standing" in reason:
        return "no trend zone left, proactive flip"
    if reason.startswith("trend zone structural death"):
        return reason  # kept verbatim, matches existing locked precedent
    if reason.startswith("trend candidate stillborn"):
        return "trend candidate stillborn, proactive flip"
    if reason.startswith("Daily swing high"):
        return "daily swing high confirmed"
    if reason.startswith("Daily swing low"):
        return "daily swing low confirmed"
    return reason


PHRASE_ORDER = [
    "a zone died before a valid entry window opened",
    "a zone was live but never triggered before invalidation",
    "price opened already inside a zone, not tradable",
    "a zone broke structure before filling",
    "price never reached a zone's entry level",
]
PHRASE_RANK = {p: i for i, p in enumerate(PHRASE_ORDER)}

STAGE_PHRASE = {
    "DEAD_BEFORE_WINDOW": "a zone died before a valid entry window opened",
    "OPEN_INSIDE_ZONE": "price opened already inside a zone, not tradable",
    "NO_ENTRY_IN_WINDOW": "price never reached a zone's entry level",
    "NO_RESTING_SWING": "a zone was live but never triggered before invalidation",
    "NO_CANDIDATE": "a zone was live but never triggered before invalidation",
    "NO_OPPOSING_SWING": "a zone was live but never triggered before invalidation",
    "NO_SL_POOL": "a zone was live but never triggered before invalidation",
    "ZERO_RISK": "a zone was live but never triggered before invalidation",
    "BAD_TIME_RANGE": "a zone was live but never triggered before invalidation",
    "PREMIUM_NOT_REACHED": "price never reached a zone's entry level",
    # Item #10 (2026-10-07): the premium/discount-region mechanism's own
    # no-trade stages, same bucket treatment as their ordinary-mechanism
    # equivalents (NO_RESTING_SWING / POI_BREACHED respectively) -- see
    # run_5m_bso_premium's own docstring.
    "NO_PREMIUM_RESTING": "a zone was live but never triggered before invalidation",
}


def poi_breached_phrase(reason):
    if reason == "swing_break":
        return "a zone broke structure before filling"
    return "a zone was live but never triggered before invalidation"


def build_month(year, month, lead_months=2, out_path=None, pad_days=10):
    last_day = calendar.monthrange(year, month)[1]
    cutoff_date = date(year, month, last_day) + timedelta(days=pad_days)
    cutoff = cutoff_date.isoformat()
    t0 = time.time()
    ctx = vd.build_engines(vd.DEFAULT_CSV, cutoff, lead_months)
    print(f"[{time.time()-t0:.1f}s] engines built for {cutoff}", file=sys.stderr)
    return build_month_from_ctx(ctx, year, month, out_path=out_path)


def build_month_from_ctx(ctx, year, month, out_path=None):
    """Same exact report-building logic as build_month() above, but takes
    an already-built ctx (e.g. from fast_full_year.py's shared-Daily-engine
    driver) instead of calling vd.build_engines() itself -- lets a full
    12-month run share the expensive full-history/Daily-engine/control-
    checkpoint build once instead of redoing it per month."""
    last_day = calendar.monthrange(year, month)[1]

    origin_lookup = {}
    for tag, eng in (("H4", ctx.h4_engine), ("1H", ctx.h1_engine)):
        for kind, zones in (("OB", eng.ob_zones), ("RB", eng.rb_zones),
                            ("FVG", eng.fvg_zones), ("VI", eng.vi_zones)):
            for z in zones:
                idx = z.candle if hasattr(z, "candle") else z.left
                origin_lookup[(tag, f"{kind}#{z.id}")] = eng.w[idx].start

    lines = [f"## {MONTH_NAMES[month]} {year}", "", "| Date | Bias | Setups | Entries |", "|---|---|---|---|"]
    total_trades = total_tp = total_sl = 0
    net_r = 0.0
    all_entered_rows = []  # verification/streak-calc side channel, not part of the locked report

    d = date(year, month, 1)
    end = date(year, month, last_day)
    while d <= end:
        ds = d.isoformat()
        window_start, window_end = atc.trading_window(ds, RYD)
        trades, ledger_rows = atc.compute_5m_trades(
            ctx.tf_full_h4, ctx.tf_full_h1, ctx.e5, ctx.short_minutes,
            window_start, window_end, RYD, side="ALL", d_zones_full=ctx.d_zones_full)

        day_start = datetime(d.year, d.month, d.day, tzinfo=RYD).astimezone(ZoneInfo("UTC"))
        day_end = day_start + timedelta(days=1)
        today_cps = [(t, s, o, r) for (t, s, o, r) in ctx.gate_control_checkpoints if day_start <= t < day_end]

        state_before, owner_before = atc.control_state_at(ctx.gate_control_checkpoints, day_start - timedelta(seconds=1))

        if d.weekday() >= 5:  # Sat/Sun -- no row, state still carries via checkpoints above
            d += timedelta(days=1)
            continue

        # ---- Bias column ----
        if not today_cps:
            bias_cell = f"{state_label(state_before, owner_before)} all day (carried)"
        else:
            labels = [state_label(state_before, owner_before)] + [state_label(s, o) for (_, s, o, _) in today_cps]
            times = [hhmm(t) for (t, _, _, _) in today_cps]
            n = len(times)
            segs = [f"{labels[i]} until {times[i]}" for i in range(n)]
            segs.append(f"{labels[n]} from {times[n-1]}")
            chain = " -> ".join(segs)
            brackets = "; ".join(f"{times[i]} {short_reason(r)}" for i, (_, _, _, r) in enumerate(today_cps))
            bias_cell = f"{chain}  [{brackets}]"

        # ---- Entries + Setups columns ----
        today_rows = [r for r in ledger_rows if r["impact_riyadh"].startswith(ds) or
                      (r.get("entry_riyadh", "") or "").startswith(ds)]
        # restrict further to rows actually impacting (today's own candidate set per report_day convention)
        today_rows = [r for r in ledger_rows if r["impact_riyadh"].startswith(ds)]

        entered = [r for r in today_rows if r["stage"] == "ENTERED"]
        shown_non_entered = [r for r in today_rows if r["stage"] not in ("ENTERED", "NO_CONTROL")
                              and not r["poi"].startswith("_dropped")]

        # group entered by poi for attempt-number suffix
        from collections import defaultdict
        by_poi = defaultdict(list)
        for r in entered:
            by_poi[r["poi"]].append(r)

        # DEDUP rule: two POIs producing the identical entry (same price,
        # same trigger minute) collapse into ONE trade -- group entered
        # rows by (entry_riyadh, entry_price, side) across different POIs.
        dedup_groups = defaultdict(list)
        for r in entered:
            key = (r.get("entry_riyadh"), r.get("entry_price"), r["side"])
            dedup_groups[key].append(r)

        entry_strs = []
        seen_keys = set()
        for r in entered:
            key = (r.get("entry_riyadh"), r.get("entry_price"), r["side"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            group = dedup_groups[key]
            side = r["side"]
            # The engine itself already merges a dedup'd cross-POI entry
            # (poi="RB#636+RB#162", tf="1H/H4", attempt="1/1" etc, per the
            # real 2025-12-31 precedent) -- detect that directly rather
            # than re-grouping ourselves.
            is_merged = "+" in r["poi"] or "/" in str(r.get("tf", ""))
            if is_merged or (len(group) > 1 and len(set(g["poi"] for g in group)) > 1):
                tfs = r["tf"] if is_merged else "/".join(dict.fromkeys(g["tf"] for g in group))
                attempt_nos = str(r.get("attempt")) if is_merged else "/".join(str(g.get("attempt") or 1) for g in group)
                ptype = r["poi"].split("#")[0]
                origin_label = None  # ambiguous across merged POIs, per locked precedent (Dec 31)
                tf_label = tfs
                suffix = f" (attempt {attempt_nos})"
            else:
                tf = r["tf"]
                ptype = r["poi"].split("#")[0]
                attempt_no = r.get("attempt")
                suffix = f" (attempt {attempt_no})" if len(by_poi[r["poi"]]) > 1 and attempt_no else ""
                origin = origin_lookup.get((tf, r["poi"]))
                if origin is not None:
                    origin = origin.astimezone(RYD)
                if origin is not None:
                    if origin.date() == d:
                        origin_label = f"origin {hhmm_naive(origin)} same day"
                    else:
                        origin_label = f"origin {MONTH_NAMES[origin.month]} {origin.day} {hhmm_naive(origin)}"
                else:
                    origin_label = "origin ?"
                tf_label = tf
            entry_t = r["entry_riyadh"].split(" ")[1][:5] if r.get("entry_riyadh") else "?"
            entry_price = r.get("entry_price", "")
            result = r.get("result", "")
            if result == "OPEN":
                tail = "-> OPEN ()"
            else:
                exit_t = (r.get("exit_riyadh") or "").split(" ")
                exit_hhmm = exit_t[1][:5] if len(exit_t) > 1 else "?"
                exit_price = r.get("sl_price") if result == "SL" else r.get("tp_price")
                rmult = r.get("r_multiple", "")
                try:
                    rnum = float(rmult)
                    rstr = f"{rnum:+.0f}R"
                except Exception:
                    rstr = f"{rmult}R"
                tail = f"-> {result} {exit_hhmm} @ {exit_price} ({rstr})"
            if origin_label is None:
                entry_strs.append(f"**{tf_label} {side}** {ptype}{suffix}, entry {entry_t} @ {entry_price} {tail}")
            else:
                entry_strs.append(f"**{tf_label} {side}** {ptype}{suffix}, {origin_label}, entry {entry_t} @ {entry_price} {tail}")

        entries_cell = "; ".join(entry_strs) if entry_strs else "NONE"

        # setups column
        phrases = []
        if entered:
            n = len(seen_keys)
            phrases.append(f"{n} zone{'s' if n != 1 else ''} on the allowed side matured and traded (see Entries).")
        bucket = set()
        for r in shown_non_entered:
            stage = r["stage"]
            if stage in ("POI_BREACHED", "POI_BREACHED_PRE_ENTRY"):
                bucket.add(poi_breached_phrase(r.get("invalidated_reason", "")))
            elif stage in STAGE_PHRASE:
                bucket.add(STAGE_PHRASE[stage])
        if bucket:
            ordered = sorted(bucket, key=lambda p: PHRASE_RANK.get(p, 99))
            phrases.append("Other allowed-side zones did not: " + "; ".join(ordered) + ".")
        if not entered and not shown_non_entered:
            any_candidate = any(r["stage"] != "NO_CONTROL" for r in today_rows) or bool(today_rows)
            phrases.append("No zone ever reached the allowed side." if today_rows else "No zones formed at all.")
        setups_cell = " ".join(phrases) if phrases else "No zone ever reached the allowed side."

        day_label = f"{MONTH_NAMES[month]} {d.day}"
        lines.append(f"| {day_label} | {bias_cell} | {setups_cell} | {entries_cell} |")

        for r in entered:
            total_trades += 1
            if r.get("result") == "TP":
                total_tp += 1
                net_r += 3.0
            elif r.get("result") == "SL":
                total_sl += 1
                net_r -= 1.0
            all_entered_rows.append(dict(r, date=ds))

        d += timedelta(days=1)

    lines.append("")
    lines.append(f"**{MONTH_NAMES[month]} result: {total_trades} trades -- {total_tp} TP, {total_sl} SL, net {net_r:+.0f}R.**")
    lines.append("")
    text = "\n".join(lines)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
    print(text)
    return total_trades, total_tp, total_sl, net_r, all_entered_rows


def hhmm_naive(dt):
    return dt.strftime("%H:%M")


if __name__ == "__main__":
    year = int(sys.argv[1])
    month = int(sys.argv[2])
    lead_months = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    pad_days = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    out_path = sys.argv[5] if len(sys.argv) > 5 else None
    build_month(year, month, lead_months, out_path=out_path, pad_days=pad_days)
