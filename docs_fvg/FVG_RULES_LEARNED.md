# FVG Rules — Learned Log

Running record of what building and control-gate-walking FVG actually
taught, mirroring `docs_rb/RB_RULES_LEARNED.md`'s own format. This is NOT
the dev handoff doc (`FVG_HANDOFF.md` -- code changes, run commands). This
file is the knowledge base: confirmed rules, carried-over OB/RB rules, and
FVG-specific rules.

---

## Zone lifecycle -- four ways an FVG zone dies (2026-09-26)

1. **IMPACT** -- any wick reaching into the gap, once eligible, ends it
   immediately. `[OB/RB]` same as always, unconditional on state.
2. **STRAND** -- a NEW confirmed swing of the protecting kind (a swing LOW
   for a bullish zone, a swing HIGH for a bearish one) confirms beyond the
   zone's own far edge. `[OB/RB]` ONE universal condition, no
   origin-branching -- the supplied `FVG_Indicator_v1.pine` had the exact
   same wrong, swapped condition for its AFVG branch that RB's own first
   pine had before its 2026-09-24 fix. Not ported; fixed from the start.
3. **CLOSE_THROUGH** -- IFVG only. The containing week's own close lands
   fully PAST the far edge (not merely inside the zone) once eligible.
   `[FVG-NEW]` Genuinely absent from OB/RB's own zone lifecycle (OB/RB's
   equivalent "body close" only reaches the NEAR edge, and lives at a
   different layer -- the control-gate's own authority-death check, not
   the zone's own state). The strict (far-edge) threshold is required
   specifically because FVG's own IMPACT rule already catches any wick
   touch unconditionally -- a close landing merely INSIDE the zone would
   always already have triggered IMPACT first, geometrically. The only
   gap IMPACT can't catch is a full bypass: price closing completely past
   the zone without ever wicking into it.
4. **STRUCTURAL_BREACH** -- a POI stops being used the instant its
   supporting swing point is exceeded, in real time, full stop. `[FVG-NEW
   at the zone-lifecycle level]` Mirrors `five_bso_engine.py`'s own
   `structural_invalid_at()` "swing_break" concept, which already existed
   for OB/RB but only at the H4/trade-invalidation layer -- applied here
   directly at the Weekly zone's own lifecycle for the first time. Each
   zone snapshots `protect_level` (a LOW for bullish, a HIGH for bearish)
   at creation, from whichever swing was the latest confirmed one of that
   kind. Not gated by eligibility.

Same-week ordering when multiple causes could apply: resolved by exact
M1/event timestamp, earliest wins -- generalized from OB/RB's own
two-candidate version to four candidates. Close-through's own "timestamp"
is inherently the week's own scheduled close (the latest possible moment
in that week), so it can only win when nothing else happened earlier.

## Control-gate derivation -- 12 gates, walked minute-by-minute (2026-09-26)

Full table (see `full_fvg_viewer.py`'s `build_manual_fvg_gates()` for the
exact tuples). Zone reference:

```
#1 BUY  1.16981-1.18346  impact 2026-02-02 16:03
#2 SELL 1.16669-1.17533  impact 2026-04-08 01:58
#3 BUY  1.16268-1.16635  impact 2026-04-29 21:44
#4 SELL 1.16614-1.16761  impact 2026-05-29 17:51
#5 SELL 1.14733-1.14994  impact 2026-07-15 20:49
#6 BUY  1.14492-1.15000  never impacted (died by STRAND) -- never becomes a parent
```

| # | Control | Zone | Start (Riyadh) | End (Riyadh) | Why it ends |
|---|---|---|---|---|---|
| 0 | NONE | -- | 2026-01-02 09:31 | 2026-02-02 16:03 | Zone #1 impacted |
| 1 | BUY_ONLY | #1 | 2026-02-02 16:03 | 2026-02-17 18:28 | swing pause, no opposing zone |
| 2 | NONE | (#1 paused) | 2026-02-17 18:28 | 2026-04-08 01:58 | MSS down cancels resume (02-19 16:01); Zone #2 impacted ends NONE |
| 3 | SELL_ONLY | #2 | 2026-04-08 01:58 | 2026-04-29 21:44 | Zone #3 impacted (opposing) -> BOTH |
| 4 | BOTH | #2 vs #3 | 2026-04-29 21:44 | 2026-05-06 13:45 | Zone #3 respected -> full flip |
| 5 | BUY_ONLY | #3 | 2026-05-06 13:45 | 2026-05-14 18:00 | swing pause, no opposing zone |
| 6 | NONE | (#3 paused) | 2026-05-14 18:00 | 2026-05-29 17:51 | MSS down cancels resume (05-15 03:38); Zone #4 impacted ends NONE |
| 7 | SELL_ONLY | #4 | 2026-05-29 17:51 | 2026-06-15 00:29 | swing pause, no opposing zone |
| 8 | NONE | (#4 paused) | 2026-06-15 00:29 | 2026-06-17 22:24 | matching swing resumes (no MSS break) |
| 9 | SELL_ONLY | #4 | 2026-06-17 22:24 | 2026-07-14 15:30 | swing pause, no opposing zone |
| 10 | NONE | (#4 paused) | 2026-07-14 15:30 | 2026-07-15 20:49 | Zone #5 impacted, same side -> new campaign |
| 11 | SELL_ONLY | #5 | 2026-07-15 20:49 | 2026-07-29 21:53 | swing pause, no opposing zone |
| 12 | NONE | (#5 paused) | 2026-07-29 21:53 | end of data (09-11 22:05) | MSS up cancels resume (07-30 13:43); nothing else happens |

**Two real corrections found by walking this out loud with the user, not
assumed from RB's own code:**

1. **Anchor break must use the controlling zone's own supporting swing
   point (`protect_level`), not its own box edge.** First pass copied
   RB's control-engine convention verbatim (check the zone's own zb/zt) --
   wrong for FVG. Caught directly: a wick touching Zone #2's own top at
   2026-04-13 21:48 was NOT a real violation (its supporting swing was
   never actually taken out), and gate 3 (SELL_ONLY, Zone #2) actually ran
   over two weeks longer than the first pass gave it, once fixed to check
   `protect_level` instead. **This is NOT a bug in RB's own engine** -- RB
   zones are built directly from a swing-pivot candle's wick, so their box
   edge IS their supporting swing's price by construction. FVG's box comes
   from a 3-candle gap, unrelated to any swing extreme, so the two
   concepts are genuinely different prices for FVG specifically. RB never
   had to make this distinction; FVG's different construction forced it.
2. **A swing-pause resume must be CANCELLED, not honored, if an MSS
   against the paused side confirms before the matching resume-swing** --
   the underlying trend itself broke, not just the pause; there's nothing
   left to resume to. Found at gate 2 (BUY paused 02-17 18:28, MSS DOWN
   confirms 02-19 16:01, but the naive first pass still resumed BUY_ONLY
   at the next matching swing on 03-23). **Flagged as a possible
   undetected gap in RB's own shipped control engine** -- RB's own resume
   logic has the identical structure and has not been checked against this
   same scenario. Not yet acted on; a real follow-up item.
3. Considered and explicitly REJECTED: a "mitigation" exception where an
   opposing impact that brings price back to a trend-aligned POI would
   stop the opposing control outright instead of going to BOTH. User's own
   call: follow RB's rule as-is -- every opposing impact goes to BOTH,
   unconditionally, no trend-alignment exception.
4. Confirmed directly (not assumed): no weekly close crossed Zone #2's own
   top (1.17533) anywhere in gate 3's real span (2026-04-08 to 04-29),
   ruling out close-through as an alternative explanation for anything in
   that window.

**FVG's own close-through stands in wherever OB/RB use plain body-close**,
per explicit user direction -- but the actual THRESHOLD differs (far-edge
for FVG vs near-edge for OB/RB), confirmed directly against
`five_bso_engine.py`'s own pre-existing comment naming FVG as the
deliberate exception. Do not assume a rule ported by name-similarity uses
the same condition -- verify the exact edge each time.

## H4 + 5m layers (2026-09-26)

`full_fvg_viewer.py` built mirroring `full_rb_viewer.py` exactly. Two real
RB mistakes deliberately avoided from the start (not discovered the hard
way this time):
- H4 swing/MSS label window scoped to the real gates span
  (`gates[-1][0]` when the last gate is NONE), not the trailing
  open-ended NONE's end.
- The manual gates table above already carries both corrections from the
  walk, not a first-guess table needing a later fix.

Result: 221 H4 FVGs computed, 30 authorized, 50 5m entries (46 ENTERED,
4 H4_FVG_BREACHED).

## Trade analysis findings (2026-09-26)

All computed directly against the real ledgers, not estimated:

- **Full dataset**: 46 entries, 11W/35L, win rate 23.9%, net -2.00R.
  Side split 42 SELL / 4 BUY.
- **Kill zones** (London 02:00-05:00 NY, New York 07:00-10:00 NY):
  consistently the WORSE half of the session for entry timing, across all
  three POI systems (OB/RB/FVG) -- New York kill zone entries are net
  negative in every single system.
- **"2nd entry of a 3+-attempt H4 POI"**: a real, striking pattern --
  0% win rate, -12R combined across OB+RB+FVG (12 trades, 0 wins). A POI
  needing 3+ attempts already looks structurally weak; its 2nd re-entry
  specifically loses every time in this dataset.
- **Breakeven-at-1R** (naive, first pass): looked promising from
  aggregate MFE/MAE averages alone, but SIMULATED properly against real
  entry/exit paths, it's net NEGATIVE (-8R) -- 41.5% of real winners get
  clipped to breakeven on their way to +3R, costing more than the losers
  it saves. Rejected. Lesson: aggregate MFE/MAE stats alone can mislead;
  simulate the actual price path before trusting a stop-management rule.
- **Breakeven-at-2R**, applied to the kill-zone + no-3rd-trade subset (54
  trades): net improvement, -2.0R -> -1.0R (5 trades converted to
  breakeven: 1 clipped winner, 4 saved losers).
- **Cross-POI control-gate reconciliation** (first pass, not yet a real
  unified engine): over the 150-day span all three systems' gates
  overlap, all three agree on control only 24% of the time. Direct
  BUY-vs-SELL conflicts happen 15% of the time -- and in every single
  such conflict, OB reads SELL while RB reads BUY, never the reverse.
  FVG never causes a direct conflict on its own; when it disagrees it's
  almost always sitting in NONE. A real unified control model needs an
  explicit OB-vs-RB tie-breaking rule, plus a `protect_level`-equivalent
  for OB zones (OB's own box is a scanned "best candle," not tied to any
  swing extreme, so its own anchor-break would need the same fix FVG's
  did) -- not yet built, explicitly deferred ("not officially now").

## Open questions / not yet tested by real data

- 0 AFVG zones formed on this dataset at Weekly granularity -- plausible
  (a genuine 3-candle gap is rare on wide Weekly bars) but not chart-
  confirmed.
- 0 real STRUCTURAL_BREACH and 0 real CLOSE_THROUGH events occurred in
  this dataset -- both verified synthetically, neither exercised by real
  data yet.
- Whether RB's own shipped control engine (`weekly_rb_control_engine.py`)
  carries either of the two corrections found here (protect_level anchor-
  break is likely NOT an issue for RB, confirmed above why; the
  MSS-cancelled-resume gap has NOT been checked against RB and remains a
  real, open follow-up item).
