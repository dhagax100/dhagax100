#!/usr/bin/env python3
"""Builds rb_system/data/rb_control_gates.csv -- one row per control-state
segment ("gate") on RB's own control ledger.

A gate is a maximal time span during which `control` (NONE/BUY_ONLY/
SELL_ONLY/BOTH) stays constant, per `weekly_control_ledger_rb.csv`/
`weekly_control_events_rb.csv` (produced by weekly_control_engine_rb.py).
For each gate: the exact event (zone id/side, event kind) that caused the
transition INTO it, the resulting control state, how many H4 RB zones
(`h4_rb_ledger.csv`) became `authorized=True` with `impact_time` inside the
gate's span, how many 5m entries (`five_rb_bso_ledger.csv`, stage=ENTERED)
have `entry_utc` inside the span, and the SL/TP breakdown of those entries.
Also records what the NEXT gate transitions to and why.

All chart-facing times are Riyadh (Asia/Riyadh), labeled as such.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
RIYADH = ZoneInfo("Asia/Riyadh")
DATA = Path(__file__).resolve().parent.parent / "data"


def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def to_riyadh(dt: datetime) -> str:
    return dt.astimezone(RIYADH).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    events = []
    with (DATA / "weekly_control_events_rb.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events.append(row)

    # Keep only events where control ACTUALLY changes (TREND_FLIP with an
    # unchanged control_after is not a gate boundary). Track running control.
    gates = []  # each: {start_utc, reason_event, reason_detail, reason_zone, control}
    current_control = "NONE"
    start_utc = None  # first week's start (week 0) -- ledger's very first row
    with (DATA / "weekly_control_ledger_rb.csv").open(newline="", encoding="utf-8") as f:
        first_row = next(csv.DictReader(f))
        start_utc = parse_dt(first_row["week_start_utc"])
    gates.append({
        "start_utc": start_utc, "reason_event": "START", "reason_detail": "Dataset start (week 0)",
        "reason_zone": "", "control": "NONE",
    })
    for e in events:
        new_control = e["control_after"]
        if new_control != current_control:
            gates.append({
                "start_utc": parse_dt(e["week_start_utc"]),
                "reason_event": e["event"],
                "reason_detail": e["detail"],
                "reason_zone": e["zone_id"],
                "control": new_control,
            })
            current_control = new_control

    # Gate end = next gate's start (or None/open-ended for the last gate).
    for i, g in enumerate(gates):
        g["end_utc"] = gates[i + 1]["start_utc"] if i + 1 < len(gates) else None

    # H4 RB authorized zones, by impact_time.
    h4_rows = []
    with (DATA / "h4_rb_ledger.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["authorized"] != "True":
                continue
            if not row["impact_time_utc"]:
                continue
            h4_rows.append((parse_dt(row["impact_time_utc"]), row["id"], row["side"]))

    # 5m entries, by entry_utc, with result.
    five_rows = []
    with (DATA / "five_rb_bso_ledger.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["stage"] != "ENTERED":
                continue
            if not row["entry_utc"]:
                continue
            five_rows.append((parse_dt(row["entry_utc"]), row["rb_id"], row["result"]))

    def in_gate(t, g):
        return t >= g["start_utc"] and (g["end_utc"] is None or t < g["end_utc"])

    out_rows = []
    for i, g in enumerate(gates):
        authorized_ids = [rid for (t, rid, side) in h4_rows if in_gate(t, g)]
        entries = [(rid, res) for (t, rid, res) in five_rows if in_gate(t, g)]
        n_sl = sum(1 for _, res in entries if res == "SL")
        n_tp = sum(1 for _, res in entries if res == "TP")
        n_other = sum(1 for _, res in entries if res not in ("SL", "TP"))
        nxt = gates[i + 1] if i + 1 < len(gates) else None
        out_rows.append({
            "gate_index": i,
            "gate_start_riyadh": to_riyadh(g["start_utc"]),
            "gate_start_utc": g["start_utc"].strftime("%Y-%m-%d %H:%M:%S"),
            "in_reason_event": g["reason_event"],
            "in_reason_zone_id": g["reason_zone"],
            "in_reason_detail": g["reason_detail"],
            "control": g["control"],
            "h4_rb_authorized_count": len(authorized_ids),
            "h4_rb_authorized_ids": ";".join(authorized_ids),
            "five_entries_count": len(entries),
            "five_entries_sl": n_sl,
            "five_entries_tp": n_tp,
            "five_entries_other": n_other,
            "gate_end_riyadh": to_riyadh(g["end_utc"]) if g["end_utc"] else "OPEN (dataset end)",
            "next_control": nxt["control"] if nxt else "",
            "next_reason_event": nxt["reason_event"] if nxt else "",
            "next_reason_zone_id": nxt["reason_zone"] if nxt else "",
            "next_reason_detail": nxt["reason_detail"] if nxt else "",
        })

    out_path = DATA / "rb_control_gates.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        wr.writeheader()
        for r in out_rows:
            wr.writerow(r)

    print(f"Wrote {len(out_rows)} gates to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
