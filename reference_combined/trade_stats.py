#!/usr/bin/env python3
"""Strategy statistics over five_bso_combined_ledger.csv.

Breaks the 254 ENTERED trades down several ways, all independently
(per user direction, 2026-09-27: "separately"):

  1. FREE TRADE -- the baseline: every entry taken, no filtering at all.
  2. KILL ZONE -- which session the entry falls in (standard ICT hours,
     Asia/Riyadh display time): London 10:00-13:00, New York 15:30-18:30,
     Asian 03:00-06:00, everything else is "Other".
  3. FIRST TWO HOURS -- entries in the first 2 hours of a kill zone
     (London 10:00-12:00, NY 15:30-17:30, Asian 03:00-05:00) vs the rest
     of that same kill zone.
  4. ATTEMPT CUTOFF -- the ledger's own "attempt" column (the Nth re-entry
     after an earlier attempt got stopped out/invalidated for the same
     POI): attempts 1-2 kept vs attempt 3+ discarded.

Only stage == "ENTERED" rows have a real trade outcome (TP/SL); breached/
no-entry rows are excluded from every stat below -- they never became a
trade.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List


KILL_ZONES = {
    "London":  (10, 0, 13, 0),
    "NewYork": (15, 30, 18, 30),
    "Asian":   (3, 0, 6, 0),
}
FIRST_TWO_HOURS = {
    "London":  (10, 0, 12, 0),
    "NewYork": (15, 30, 17, 30),
    "Asian":   (3, 0, 5, 0),
}


def hm(s: str) -> int:
    """'HH:MM' -> minutes since midnight."""
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_range(mins: int, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    start, end = start_h * 60 + start_m, end_h * 60 + end_m
    return start <= mins < end


def kill_zone_of(entry_hour_riyadh: str) -> str:
    mins = hm(entry_hour_riyadh)
    for name, (sh, sm, eh, em) in KILL_ZONES.items():
        if in_range(mins, sh, sm, eh, em):
            return name
    return "Other"


def in_first_two_hours(entry_hour_riyadh: str, zone: str) -> bool:
    if zone not in FIRST_TWO_HOURS:
        return False
    mins = hm(entry_hour_riyadh)
    sh, sm, eh, em = FIRST_TWO_HOURS[zone]
    return in_range(mins, sh, sm, eh, em)


def r_of(row: dict) -> float:
    v = row.get("r_multiple_result", "")
    return float(v) if v not in (None, "") else 0.0


def stats_line(label: str, rows: List[dict]) -> str:
    n = len(rows)
    if n == 0:
        return f"{label:<28} n=0"
    wins = sum(1 for r in rows if r["result"] == "TP")
    losses = sum(1 for r in rows if r["result"] == "SL")
    total_r = sum(r_of(r) for r in rows)
    winrate = 100.0 * wins / n
    avg_r = total_r / n
    return (f"{label:<28} n={n:<4} TP={wins:<4} SL={losses:<4} "
            f"win%={winrate:5.1f}  total_R={total_r:+7.2f}  avg_R={avg_r:+.3f}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("ledger_csv", nargs="?", default="five_bso_combined_ledger.csv")
    args = p.parse_args()
    path = Path(args.ledger_csv).expanduser().resolve()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    entered = [r for r in rows if r["stage"] == "ENTERED"]

    for r in entered:
        r["_zone"] = kill_zone_of(r["entry_hour_riyadh"])
        r["_first2h"] = in_first_two_hours(r["entry_hour_riyadh"], r["_zone"])

    print(f"Total ledger rows: {len(rows)}  |  ENTERED (real trades): {len(entered)}\n")

    print("=== 1. FREE TRADE (baseline -- every entry, no filtering) ===")
    print(stats_line("All entries", entered))

    print("\n=== 2. KILL ZONE (standard ICT hours, Riyadh time) ===")
    for zone in ("London", "NewYork", "Asian", "Other"):
        print(stats_line(zone, [r for r in entered if r["_zone"] == zone]))

    print("\n=== 3. FIRST TWO HOURS OF KILL ZONE vs REST OF THAT KILL ZONE ===")
    for zone in ("London", "NewYork", "Asian"):
        zone_rows = [r for r in entered if r["_zone"] == zone]
        first2 = [r for r in zone_rows if r["_first2h"]]
        rest = [r for r in zone_rows if not r["_first2h"]]
        print(stats_line(f"{zone} first 2h", first2))
        print(stats_line(f"{zone} rest", rest))

    print("\n=== 4. ATTEMPT CUTOFF (ledger's own 'attempt' column) ===")
    att12 = [r for r in entered if r["attempt"] in ("1", "2")]
    att34 = [r for r in entered if r["attempt"] not in ("1", "2")]
    print(stats_line("Attempt 1-2 kept", att12))
    print(stats_line("Attempt 3+ discarded", att34))
    from collections import Counter
    print("  attempt-number breakdown:", dict(sorted(Counter(r["attempt"] for r in entered).items(), key=lambda kv: int(kv[0]))))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
