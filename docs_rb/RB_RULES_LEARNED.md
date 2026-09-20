# RB Control-Gate Rules — Learned Log

Running record of what the control-gate walkthrough has actually taught,
gate by gate, through 2026. This is NOT the dev handoff doc
(`RB_HANDOFF.md` — code changes, bugs, run commands). This file is the
knowledge base: confirmed rules, carried-over OB rules, and RB-specific
rules, so later gates can be checked against everything learned so far
instead of re-deriving it each time.

Format per gate: **claim → verification method → confirmed rule(s)**.
Rules inherited from OB unchanged are marked `[OB]`. Rules that are new,
or that apply differently in RB, are marked `[RB-NEW]` or `[RB-DIFF]`.

---

## Carried over from OB (assumed true until RB data contradicts it)

- `[OB]` **Weekly-close body-breach kills a POI.** If the containing
  week's own close is inside or through the zone (`close >= zb` for a
  bearish zone measured against its bottom, mirrored for bullish), the
  zone dies at that week's close. SPEC.md SS14. — Confirmed still true
  for RB via gate 1 (zone #2 dies at 2026-02-16 close, 1.18722 >= zb
  1.18609).
- `[OB]` **Trend and control are independent.** A COUNTERTREND gate
  (trend up, gate SELL_ONLY or vice versa) is not itself invalid —
  SPEC.md SS9. — Confirmed still true for RB via gate 1 (trend up per
  2025 carryover, gate is SELL_ONLY on a bearish ARB).
- `[OB]` Control gates are checked two ways: (1) **event-level** — swing
  point creation, POI reaction, MSS; (2) **candle-close behavior** —
  especially close behavior around candles that sit inside a POI. Both
  checks are required per gate, not just one.

## RB-specific rules confirmed so far

- `[RB-NEW]` RB zone = the **wick** of a single known swing-pivot candle
  (never scanned/picked from a range, unlike OB's zone selection).
- `[RB-NEW]` IRB mirrors IFOB (delayed eligibility, arms on next
  same-direction swing); ARB mirrors AOB (immediate eligibility,
  `eligible_time = trigger_time` at creation); AIRB mirrors AIFOB
  (speculative at mid-arm, promotable in place to IRB on a real break).
- `[RB-NEW]` Bull/bear label follows the **raw wick type** (swing-high
  wick always bearish, swing-low wick always bullish), independent of
  which hunt direction created the zone.
- `[RB-DIFF]` Lifecycle stranding rule is simpler than OB: **wick impact
  + stranding only, no close-through rule** for RB zone death by touch —
  separate from the Weekly-close body-breach rule above, which still
  applies the same way it does in OB.

---

## Gate 1 — 2026-02-09 15:07 Riyadh → 2026-02-16 01:00 Riyadh (SELL_ONLY)

**Claim (user-supplied):** RB zone #2 (Weekly, ARB, bearish,
top=1.20825, bottom=1.18609) is the first RB ever impacted. Trigger,
eligible, and impact are the same minute (2026-02-09 15:07 Riyadh).
Trend was UP (2025 carryover, not derivable from 2026-only data) →
countertrend SELL_ONLY start. Zone dies at its own containing week's
close (2026-02-16 01:00 Riyadh close = 1.18722, inside the zone).

**Verification:** all three sub-claims checked directly against
`weekly_rb_ledger.csv` and the week's own OHLC before any code was
written — all confirmed true.

**Result:** gate 1 = SELL_ONLY, 2026-02-09 15:07 → 2026-02-16 01:00
Riyadh, then NONE. Within this window: 5 H4 RBs authorized (post-DST-fix;
was 6 pre-fix), all SELL, all parent zone #2. 8 total 5m entry attempts
(post-fix; was 10 pre-fix): 5 ENTERED, 3 H4_RB_BREACHED.

**Not yet chart-verified** against the real TradingView chart with the
corrected (post-DST-fix) numbers — pending.

---

## Open questions / not yet tested by real gate data

- Does RB ever need its own countertrend/trend-alignment nuance beyond
  the OB SS9 rule, or does it inherit it exactly?
- Does AIRB promotion-in-place ever interact with a control gate boundary
  (e.g. promoted mid-gate vs. promoted after a gate closes)?
- Whether RB's simpler "wick impact + stranding only" lifecycle ever
  produces a gate-relevant case OB's close-through rule would have
  caught (or vice versa) — no case has surfaced yet.
