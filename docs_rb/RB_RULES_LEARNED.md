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

## Real bug caught by the user from a chart replay (2026-09-20)

Gate 2's end / gate 3's start was first encoded at the week-of-02-16's
own close (2026-02-23 01:00 Riyadh), using a structural
close-below-prior-week's-low fact as the trigger. **This was wrong.**
User clarified the actual rule: **MSS does not require a close — a
1-pip wick exceedance of the protecting swing point is enough, real-time,
on whatever timeframe it happens** (mid-week, mid-day, mid-hour). The
swing protecting gate 2's BUY leg is AIRB #3's own anchor low (1.17652);
the first real M1 wick below it is **2026-02-19 16:01 Riyadh** (low
1.17645), 4 days before the week's own close. Under the wrong boundary,
a real H4 RB (#91) got authorized BUY on 2026-02-20 18:12 Riyadh — a
live trading mistake, caught by the user replaying the chart, since the
real-time MSS-down had already confirmed the day before. Fixed: gate
2/3's boundary moved to 2026-02-19 16:01 Riyadh; H4 RB #91 now correctly
shows `authorized=False`.

`[RB-NEW]` **MSS confirmation rule, corrected**: real-time wick
exceedance of a protecting swing point (even 1 pip), not a close, not
delayed to any candle's own close on any timeframe. This generalizes
the earlier "gates react in real time" finding (from the 1.16162 vs
14:06 stop-event check) into an explicit, reusable rule: any future gate
boundary describable as "trend flips" or "MSS" must be checked for the
first wick (not close) breach of the relevant protecting swing, not a
candle-close event on any timeframe.

## Real fixes — Pine CE10295 (permanent) and CLI runtime O(n^2) bug (2026-09-24)

**CE10295 "main body is too long"**, recurring even though array-packing (the
original fix, documented earlier in `docs/TRADING_SYSTEM_HANDOFF.md`'s OB
history) was already in place everywhere. Array-packing caps the number of
Pine STATEMENTS, but each `array.from(...)` literal's own element count
still scales the compiled AST node count with the data -- as the manual
gates window widened (38 H4 RBs, 52 drawn, hundreds of swing/MSS events),
that kept growing past Pine's ceiling again, same failure, same symptom.
Root cause of the SIZE, not just the statement count: every time-valued
array element was `wob.pine_time(t)` / `fv.pine_time(t)` --
`timestamp("GMT+0", Y, M, D, h, mi)` -- a 6-node function call (1 call + 5
int args) for every single element. **Fixed for real**: added `pine_epoch(t)`
in `weekly_rb_generator.py` (bare UTC epoch-millisecond integer literal --
exactly equivalent, since Pine's own `time`/`time_close` built-ins already
ARE epoch-ms ints) and swapped it in everywhere a bulk array literal or
per-item time comparison previously used `pine_time`, in both
`weekly_rb_generator.py`'s own Weekly layer and `full_rb_viewer.py`'s H4
layer (`rb.pine_epoch`). One node instead of six per time value, same
array, ~5x fewer AST nodes for every time-heavy array (`structX`,
`h4RbStructX`, `rbLeft`/`h4RbLeft`, impact watchers) -- scales the same way
regardless of how much wider the gates window gets later, not just a fix
for today's data size. Verified: `structX`'s array now holds bare integers
(e.g. `1766959200000`) instead of nested `timestamp(...)` calls; 38
authorized H4 RBs / 38 shown unchanged (rendering-only change, zero effect
on computed facts).

**CLI runtime, real O(n^2) bug**: `claimed()` rescanned the ENTIRE (ever-
growing) `self.zones` list on every single candidate zone check
(`any(z.candle == candle and z.bullish == bull for z in self.zones)`).
Profiled directly: 232.9M function calls, 139s wall time, with 202M of
those calls being that one genexpr's iterations across ~20.7k `claimed()`
calls -- the triangular-number signature (~n^2/2) of a linear rescan inside
a growing loop. The 5-minute engine (tens of thousands of bars, run purely
to extract swing/MSS events for BSO) was the dominant contributor, since
it creates by far the most candidate zones. **Fixed**: replaced the full-
list rescan with an O(1) `set` lookup (`self._claimed_pairs`), populated
alongside `self.zones.append(...)` in `add_rb_from_swing`. Verified:
function-call count dropped from 232.9M to 30.9M (the 202M genexpr calls
gone entirely), 38/38 authorized unchanged (pure speed fix, zero output
change). Remaining runtime (~50s on this machine, still profiled at ~83s
of `finish_events_and_lifecycle`'s own per-bar/per-active-zone loop body)
is genuinely proportional to (bars x concurrently-active zones) -- real,
necessary work on the 5m timeframe's huge bar count, not a bug found so
far. Flagged, not touched further -- a real algorithmic redesign there
(e.g. only re-checking zones whose range could plausibly be touched by a
given bar) would need its own careful review before risking a change to
the actual computed results.

## Real bug fixed — ARB/ORB stranding used the wrong ("near-side") condition (2026-09-24)

H4 RB #163 (SELL, W6, zb=1.16187/zt=1.16268) never stranded in the engine
despite a run of swing highs (1.15636, 1.15488, 1.15713 -- all well below
its own bottom) forming during its life; it stayed ARB and only died by
direct impact on 2026-04-08 01:05 Riyadh. User: "this is wrong... compare
[this] to the stranding rule of the AOB... I knew ORB had inherited
mistake of this from the first pine code I shared with you but it needs
to be fixed now."

Checked `weekly_ob_generator.py`'s strand check directly (line ~542): OB
uses **one single condition for every OB type** -- IFOB, AOB, AIFOB alike,
no branching at all: `(bullish and LOW swing confirmed above zt) or
(bearish and HIGH swing confirmed below zb)`. RB's `weekly_rb_generator.py`
had split this into an `origin_type`-keyed `is_irb` branch: the `is_irb`
branch (origin_type 0, IRB/AIRB) already matched OB's real rule exactly;
the `else` branch (origin_type 1, ARB) used an invented, swapped condition
(`bullish+HIGH below zb` / `bearish+LOW above zt`) that OB never has for
AOB or any other type.

`[RB-NEW]` **Fixed**: removed the `origin_type` branch entirely from the
stranding check in `WeeklyRBEngine.finish_events_and_lifecycle` (or
equivalent step-3 lifecycle block) -- all RB zone types (IRB, ARB, AIRB)
now strand under the exact same single condition OB uses for all its
types. `origin_type` is still used elsewhere (ARB's immediate-eligibility
timing at zone creation) -- that usage is unrelated and untouched.

Re-ran: zone #163 now correctly shows `ORB`, `authorized=False` (a
stranded zone is no longer a fresh POI). Full-window effect: 449 H4 RBs
computed, 27 authorized (was 29), 31 5m BSO attempts (was 33) -- several
other ARB zones in the W6 sell campaign were also wrongly staying ARB and
now correctly strand to ORB (e.g. #166's stranding time shifted earlier,
2026-04-03 05:21 -> its own downstream eligible/impact times moved with
it).

## Known issue flagged, NOT fixed yet — weekly-open-candle wick RBs (2026-09-24)

H4 RB #168 (Parent W #6, SELL, bottom=1.15195, top=1.15226, trigger
2026-04-06 01:05 Riyadh, eligible/impact 2026-04-06 05:17 Riyadh) is wrong.
User: "you gave a random color swing high and swing low inside the wick, so
that the wick was considered as RB which is wrong and the sole reason is it
is weekly open candle." The zone was built from the wick of the Monday
00:00 (weekly-open) candle — same family of issue as the OB weekly-gap
problem investigated earlier this segment, but here it produced a false
swing-pivot pick on the open candle itself rather than a gap-range error.

**Decision: do not fix now.** User: "We do not need to fix it now we will
take care of all the issues of midnight candles and their gaps later. we
just need to record their info for later." This entry is that record.

`[RB-KNOWN-ISSUE]` Midnight/weekly-open candles can produce false
swing-high/swing-low picks purely from their own wick, generating a
spurious H4 (and potentially Weekly) RB zone. Root cause not yet
diagnosed — deferred, grouped with the broader "midnight candles and
their gaps" cleanup to be done later, together with the open OB gap
question. Do not treat any RB zone whose trigger/origin candle sits at a
weekly (or possibly daily) open as trustworthy until this is fixed.

## Real bug caught by the user questioning a swing-confirm timestamp (2026-09-24)

Asked whether a swing high was confirmed at 2026-03-30 12:17 Riyadh; I first
said no, reading `weekly_rb_swings.csv`'s `confirm_riyadh` column, which
showed 2026-03-30 00:00 (week-open) for that swing. User correctly pushed
back: that column was never the real confirmation minute -- it's just the
containing week's scheduled boundary. Checked `write_ledger()` in
`weekly_rb_generator.py`: it wrote `engine.w[e.confirm].start` (a SWING's
confirm week label) and `engine.w[x.at].start` (an MSS's break week label)
instead of the engine's own stored exact-minute facts. Re-ran the engine
directly and confirmed the real minute for that swing high (1.16394) is
2026-03-30 12:17 -- exactly the RB #5/#6 trigger minute already logged
above, and independently reproduces the MSS_DOWN gate-2/3 boundary
(2026-02-19 16:01) already hand-verified for the real bug entry below.

`[RB-NEW]` **Fixed**: `weekly_rb_swings.csv`'s `confirm_utc`/`confirm_riyadh`
now use the SWING `Event.at` (already an exact 1m timestamp, just never
exported) directly, and the MSS row now computes its exact break minute via
`engine.break_time(x.at, x.up, x.price)` (same helper the RB trigger-timing
code already uses) instead of printing the week's own open time. `origin_*`
columns are untouched -- those correctly label which week's candle the
pivot itself sits on, a week-level fact, not a confirmation-timing one.

Note: `reference/weekly_ob_generator.py`'s own `weekly_ob_swings.csv`
export (OB project, lines ~810-813) has the identical defect, unfixed --
flagged, not touched, since that engine is marked locked/complete.

## The real answer: too much data for one Pine script, added --window-start/--window-end (2026-09-24)

CE10295 persisted even after ALL three layers were converted to
`pack_array` (zero `array.from(` anywhere, verified). User asked directly:
what is this error, how did OB solve it, why hadn't this been fixed after
several tries. Honest answer, given plainly: CE10295 is Pine's ceiling on
the TOTAL SIZE/complexity of a script, not specifically statement count or
element count -- `pack_array` reduced AST node count, but the actual DATA
(122 H4 RBs + 152 5m trades, all their prices/times/labels) didn't get any
smaller, so the ceiling was still being hit. OB never solved this at RB's
scale -- OB's own rendered window always stayed small (one zone's
~6-13-week span), so it never had to.

**The real fix**: show less at once. Added `--window-start`/`--window-end`
to `full_rb_viewer.py` -- narrows which H4 RBs/trades/labels get DRAWN in
the `.pine` file, on top of (never widening) the known-gates span. The
CSVs (`h4_rb_ledger.csv`, `five_bso_rb_ledger.csv`, `weekly_rb_ledger.csv`)
always contain the COMPLETE, unwindowed history regardless -- only the
Pine chart itself is scoped down. Verified directly: full window = 99,716
characters in the generated `.pine`; `--window-start 2026-08-01` alone
cuts it to 52,660 characters (122 H4 RBs -> 32 shown, 152 trades -> 38
drawn) -- character count scales with the actual row count, confirming
this (not any encoding trick) is the real lever for staying under
whatever Pine's true ceiling is. Use e.g.:
`python full_rb_viewer.py ..\EURUSD_m1_BidAndAsk.csv --window-start 2026-08-01`

## CE10295 for a third time -- the Weekly layer was never converted (2026-09-24)

User: "this is your last chance to fix this." Fair -- the CE10295 fix had
only been applied to the H4 RB and 5m BSO layers (`full_rb_viewer.py`,
`full_viewer.py`); `weekly_rb_generator.py`'s own `write_rb_pine()` --
the Weekly layer, drawn first in the same combined script -- was still
using the old `array.from(...)` for every one of its ~36 fields
(structX/Y/Txt/Col/Low, rbLeft/Top/Bottom/Right/Col/Rank/Audit/HasLine,
the per-zone named `impact_x_<id>` watchers, and BOTH the table_cap-
limited `t_*` fields AND the fully uncapped `i_*` "inspect any zone"
audit fields covering every zone ever created). Small in isolation (~18
zones), but combined with the two already-fixed layers this was enough
to push the WHOLE script over CE10295 again -- exactly the earlier lesson
("array-packing alone doesn't scale, only the string+split technique
does") not yet applied everywhere it needed to be.

**Fixed**: `pack_array()` duplicated into `weekly_rb_generator.py` itself
(same technique as `full_viewer.py`'s copy -- this file doesn't import
`full_viewer`, so a second small copy, matching the existing
`pine_epoch` duplication pattern already in place). Every field in
`write_rb_pine()` converted, including colors: `array<color>` isn't
`str.tonumber`-able, so colors now pack as one-letter codes
("R"/"G"/"O"/"B"/"K") and get mapped back to the real `color.*` value
with a ternary at draw time (`colour_ternary()` helper). The per-zone
`impact_x_<id>` named-watcher pattern (up to 3 lines x every shown zone)
also got the same consolidation the H4 layer already had: one shared
`array<int> rbImpactX` + one per-bar loop, instead of one named var +
one watcher block per zone.

Verified: **zero remaining `array.from(` calls anywhere in the generated
file** (checked directly, not just believed) -- 0 in the Weekly layer, 0
in the H4 layer, 0 in the 5m BSO layer. File is 480 lines (up slightly
from 394 since every field is now its own small if-block instead of one
compact array.from line, but every one of those blocks costs Pine the
same handful of AST nodes regardless of how many rows/zones/swings it
holds). 122 H4 RBs, 152 5m BSO rows, same computed facts as before --
this was rendering-only, top to bottom. This should not recur regardless
of how much further the gates list grows, since NOTHING in the generated
script scales with row count anymore.

## CE10123 in pack_array's na cast (2026-09-24)

After the CE10295 rewrite, real compile error on the actual chart:
**CE10123, "Cannot call operator ?: with argument expr1='na'. An argument
of simple na type was used but a series bool type was expected."** --
Pine's ternary requires both branches to share not just a type but a type
QUALIFIER (simple/series); a bare `na` defaults to "simple", which
conflicts with a runtime-computed "series bool" (`p == "true"`) on the
other branch. Hit on both bool fields (`h4RbBull`, `h4RbStructLow`); int/
float/string happened not to trip the same qualifier check in this case,
but the fix needs to be uniform, not per-kind-as-needed.

**Fixed**: `pack_array`'s na branch now casts explicitly to the target
type (`int(na)`, `float(na)`, `bool(na)`, `string(na)`) instead of bare
`na`, for every kind. This is Pine's own documented idiom for producing a
correctly-qualified na. Verified in the regenerated file: every packed
array's na branch now reads e.g. `p == "§NA§" ? bool(na) : p == "true"`.

## CE10295, actually fixed this time (2026-09-24)

User, after the epoch-int fix still didn't hold: "well, you aren't
learning from the OB journey. are you?" -- fair. Array-packing (one
`array.from(...)` per FIELD, not one statement per ROW) was the right fix
for the ORIGINAL failure mode, and epoch-int literals were a real
improvement, but neither one changes the fact that `array.from(...)`
still costs Pine roughly ONE AST NODE PER ELEMENT. That cost scales
directly with row count no matter how cheap each element's own expression
is -- so every partial fix just moved the ceiling further out, guaranteeing
a repeat the next time the known-gates window grew (which it always will,
since RB's whole point is covering more of the dataset over time, unlike
OB's narrower single-zone windows that never grew this large).

**The actual, scale-invariant fix**: `full_viewer.py`'s new `pack_array()`
packs an entire column into ONE Pine string literal (costs Pine ONE node
regardless of string length) and decodes it at runtime with
`str.split()` inside a single `if barstate.isfirst` for-loop (a loop's
compile-time cost is its own fixed body size, not how many times it
iterates -- so this is O(1) compile cost per field, forever, regardless of
row count). Applied to every large field in both `build_h4_rb_extra_lines`
(full_rb_viewer.py: h4RbLeft/Top/Bottom/Bull/Label/Id/Parent/Side/
Bot5/Top5/Trig/Elig/Impact/StructX/Y/Txt/Col/Low) and `build_bso_extra_lines`
(full_viewer.py, shared with OB: all 26 bso5* fields). Colors got the same
treatment as a byproduct: packed as a one-letter code string ("B"/"K"/"R"/"G")
and mapped to the real `color.*` value with a ternary at draw time, since
color isn't a `str.tonumber`-able primitive.

Also eliminated the OTHER O(n) source in the H4 RB layer: up to 122
separate named `var int h4rbimpact_x_<id>` watcher variables (one per
zone, 3 lines each = up to 366 top-level statements) got replaced with
ONE shared `array<int> h4RbImpactX`, updated by a single per-bar loop --
same "latch to the real bar `time` the first bar it's reached, never a
lookahead" behavior, O(1) statement cost regardless of zone count.

Verified: `full_rb_viewer.pine` dropped from 617 lines / ~7422
array-literal elements to 394 lines / 714 elements (the 714 remaining are
all in the small, naturally-bounded Weekly layer -- ~18 zones/swings --
never touched by this fix since it was never the problem). Same 122 H4
RBs, 152 5m BSO rows, identical computed facts -- rendering-only change.
This is expected to hold regardless of how many more gates get added
later, since the big layers' compile cost no longer scales with row count
at all.

Delimiter/NA-sentinel note: the first version used the ASCII unit-separator
control character (0x1F) as the delimiter, which is INVISIBLE in a
terminal/editor and risks being silently stripped by a browser textarea
on copy-paste into Pine Editor -- switched to a plain printable delimiter
(`|`) and NA sentinel (`§NA§`) before delivery, since none of RB's own
data (dates, prices, ids, labels) ever contains either.

## CE10205 in the shared BSO layer, same fix ported (2026-09-24)

With gates 8-34 added, the 5m BSO table grew to 152 rows and hit a NEW
Pine error: **CE10205, "the {statementName} statement is too long"** --
one specific statement (a single `array.from(...)` line), not the whole
script (that's CE10295, already fixed). Root cause: `full_viewer.py`'s
`build_bso_extra_lines()` -- the shared 5m entry-visualization function
RB reuses verbatim from OB -- still built its time arrays with the old
`pine_time(t)` (`timestamp("GMT+0", Y, M, D, h, mi)`, 6 AST nodes per
element) through its own `pt()` helper, never touched by the earlier
CE10295 fix (that fix only covered RB's OWN files). At 152 rows this one
array literal got too large for a single statement.

**Fixed**: added `pine_epoch(t)` to `full_viewer.py` itself (same bare
epoch-ms-int technique) and pointed `pt()` at it instead of `pine_time()`.
This is a SHARED file (OB's own `build_bso_extra_lines` call site too),
but the change only affects how a time VALUE is spelled in generated Pine
text -- zero effect on any computed event, price, or logic -- so it's safe
and also benefits OB the same way if OB's own BSO table ever grows this
large. Verified: `bso5BLeft` etc. now hold bare integers
(e.g. `1770693300000`), not nested `timestamp(...)` calls.

## Two 1-hour timestamp discrepancies fixed; engine now matches all 34 gates exactly (2026-09-26)

Verified the two flagged 1-hour differences (zone #8's and zone #14's own
Weekly-close death times) directly against the canonical week aggregation
(`wob.aggregate_weeks(minutes, "America/New_York", 17)` -- the exact call
`full_rb_viewer.py` itself uses): both weeks genuinely END at **:00
Riyadh**, not :01 -- 2026-05-11 00:00 and 2026-07-27 00:00. The automated
engine was right; the hand-typed table had a stale 1-hour error on both
(most likely from an earlier, less careful ad hoc verification script
that didn't use the canonical NY-local-17:00 week-close convention).

Fixed both boundaries in `build_manual_rb_gates()`. Regenerated: same 120
H4 RBs authorized, same 150 5m BSO rows -- nothing was actually impacted
inside that 1-hour gap, so this was a pure precision fix with zero effect
on any computed result. **`weekly_rb_control_engine.py`'s automated
derivation now matches all 34 hand-verified gates exactly, to the
minute** -- the validation this session set out to do is complete.

## Gate 2 finding accepted; two NONE windows added (2026-09-26)

Follow-up to the automated engine's gate-2 finding above. User's decision,
given the two options put to them (assert the pre-existing uptrend anyway,
or stay honest about having no reacted zone): **"take gate 2 here to none
and mention we considered that we did not have a direction before."**

`build_manual_rb_gates()` now has two NONE windows where BUY_ONLY was
previously asserted on assumption alone, with no zone having reacted yet
to justify it:
- **2026-01-02 09:31 (start of the loaded M1 data) -> 02-09 15:07** (zone
  #2's own impact): no zone reacts anywhere before this. The pre-2026
  uptrend context (used only as background for why gate 1 is
  "countertrend") is NOT asserted as a live BUY_ONLY campaign here --
  nothing in the data itself proves one existed.
- **2026-02-16 01:00 (zone #2 dies) -> 02-17 18:28** (zone #3's first
  reaction): previously "the only countertrend zone died, so control
  reverts to the underlying uptrend" -- same gap, same fix.

This is the same discipline held everywhere else in this project: never
assert control without an actual reaction behind it. Verified: H4 RBs #80
and #82 (both BUY, impacted inside the old 02-16->02-17 window) now
correctly show `control_at_impact=NONE, authorized=False` -- previously
wrongly authorized. Full-dataset counts: 449 H4 RBs computed, 120
authorized (was 122), 150 5m BSO rows (was 152, 90 ENTERED unchanged).

## Automated control engine built and validated against the 34-gate table (2026-09-24)

New file: `reference_rb/weekly_rb_control_engine.py` -- RB's counterpart of
OB's `weekly_control_engine.py`, independently deriving control state from
raw zone/swing/MSS facts instead of the hand-maintained
`build_manual_rb_gates()` table. Implements every RB-specific rule this
session established: parent-in-charge = last REACTED zone (not created),
every opposing impact -> BOTH (no OB-style direct-switch exception), BOTH
resolves via respect / anchor-break / Weekly-close body-death of the
challenger (whichever comes first), a sole controlling zone's own anchor
breaking flips control directly (no NONE in between), a genuinely unrelated
swing pauses to NONE and resumes via the opposite-kind swing, and same-
minute collisions between an impact and a would-be pause/resume are
resolved by the impact.

**Validated directly against the 34-gate table, not just run once and
trusted.** Three real bugs found and fixed while validating (each one only
surfaced by an actual mismatch against the known-correct gates, not by
inspection):
1. **Same-minute collision checks never fired.** They reused a
   "next impact STRICTLY AFTER this time" lookup to test for a same-minute
   impact -- which by construction can never match anything AT that exact
   minute. Added a real `impact_at_exact()` helper. (Caught by gate 6a->6b:
   zone #6's own impact at 04-08 01:32 coincides with an unrelated swing
   low confirming the same minute; the engine wrongly read it as a bare
   pause instead of "stays SELL_ONLY, parent updates.")
2. **Tie-break bug**, same root family: when an impact and a resume
   candidate land at the EXACT same timestamp, the impact candidate was
   always listed first and always won ties, so the collision check (which
   only ran when `kind_ == "resume"`) never got a chance to fire. Fixed by
   checking the collision against the winning timestamp directly, not
   against which literal candidate the sort happened to pick. (Caught by
   gate 8->9: 05-06 13:45's zone #8 impact and BUY resume swing tie
   exactly.)
3. **BOTH only checked two of the three real resolution paths** (respect,
   anchor-break) -- missing that the challenger zone can also just die
   outright via the ordinary Weekly-close body-breach rule, same as any
   other zone. Missing this made the engine skip right past the real
   05-11 00:00 resolution (zone #8 dying at its own week close) to a much
   later, unrelated coincidental swing. Added `body_close_dead_after()`
   (itself needed its own fix -- filtered candidate weeks by `w.start`
   instead of `w.end`, wrongly discarding the very week whose CLOSE was
   being tested whenever the cutoff fell mid-week, which it normally does).

**Result after all three fixes: 32 of 34 hand-verified transitions match
almost exactly** (same event, same zone, same minute in all but two
body-close timestamps that are off by exactly 1 hour -- see below).

**One genuine, freshly-surfaced discrepancy, flagged for a decision, not
silently resolved either way**: gate 2 (02-16 -> 02-19 16:01, previously
recorded as BUY_ONLY the whole stretch). The engine says control is
**NONE** from 02-16 01:00 (zone #2's own death) until 02-17 18:28 (zone
#3's first impact), THEN BUY_ONLY -- not BUY_ONLY the whole time. This is
consistent with every other gate's now-corrected rule (control only starts
via an actual REACTION, matching the earlier "parent-in-charge, corrected"
fix, which already established that gate 2 has no PARENT until 02-17
18:28 -- the engine is now saying the CONTROL STATE itself should follow
the same logic, not just the parent id). Not yet accepted into the
benchmark table -- this is exactly the kind of finding OB's own port
surfaced (2 new gates, both accepted after user confirmation) and should
get the same treatment: user confirms or rejects it before
`build_manual_rb_gates()` changes.

**Minor, non-structural discrepancies to reconcile**: two Weekly-close
body-death timestamps (zone #8's death, zone #14's death) land at :00
Riyadh in the engine's output vs :01 in the hand-typed table -- a 1-hour
difference, most likely from an earlier, less careful ad hoc verification
script using slightly different week-close parameters than the canonical
`--week-close-zone America/New_York --week-close-hour 17` defaults (which
the new engine uses exactly, matching `full_rb_viewer.py`'s own defaults).
Worth reconciling before trusting the exact hour on those two boundaries,
though it doesn't change which gate or which zone -- only a 1-hour
precision question on 2 of 34 transitions.

**Not yet done**: `full_rb_viewer.py`/`build_manual_rb_gates()` has NOT
been switched over to use this engine's output -- it still uses the
hand-maintained table. This is intentionally the same "verify before
wiring in" discipline OB's own port followed. Outputs
(`weekly_rb_control_events.csv`, `weekly_rb_control_report.txt`) are
written next to the CSV for inspection; nothing downstream reads them yet.

## RB declared the benchmark over OB where the two disagree (2026-09-24)

Compared OB's 16-gate control history (`full_viewer.py`'s `build_manual_gates()`)
against RB's 34-gate history directly, timestamp by timestamp, over their
shared window (2026-04-14 onward, both derived from the SAME underlying
swing/MSS engine).

**Where they agree** (pure swing/MSS-driven boundaries, no zone impact
involved): exact match on NONE 07-14 15:30 -> 07-23 15:43; exact match on
SELL_ONLY end times 05-29 17:51, 06-15 00:29, 07-14 15:30, 07-29 21:53;
exact match on SELL_ONLY resuming 06-05 16:51. Confirms both projects
correctly share the identical underlying swing/MSS facts.

**Where they diverge** (any zone-impact-driven transition): OB's zones
(range-scanned) and RB's zones (single swing-pivot wick) are different
physical objects even off the same swing skeleton, so they react to price
at different times, sometimes flipping which side is "in control"
entirely:
- 2026-04-14 -> 04-29: OB says SELL_ONLY, RB says BUY_ONLY.
- 2026-06-15 -> 06-17: OB says NONE, RB says BUY_ONLY.
- 2026-07-30 -> 08-19: OB mostly SELL_ONLY/NONE, RB mostly BUY_ONLY/BOTH.
- **Terminal state, 2026-08-24 -> end of data (09-11)**: OB ends flat
  (NONE, no live zone). RB ends BUY_ONLY, parent #14. The two projects
  disagree about the entire final ~3 weeks of the dataset.

**User's explicit ruling, verbatim**: "we need to record this and consider
RB more accurate if we will have to pick one because I had the enough
time and clear mind to guide you and I am sure every gate is correct. so,
consider it benchmark." **RB is the benchmark going forward wherever the
two disagree** -- all 34 RB gates are user-confirmed correct, walked and
verified live, gate by gate, in this session. This does NOT mean OB's own
16 gates are wrong (never re-verified against this finding) -- it means
if a future decision has to pick one project's read of a given stretch,
RB's is the one to trust. Flagged for whoever next touches OB's own gate
history: the divergent windows above are worth a second look there, but
that re-verification is OB's own task, not done as part of this entry.

## Full gate history written into code, corrected rule applied everywhere (2026-09-24)

`build_manual_rb_gates()` now covers the ENTIRE loaded dataset: 2026-02-09
15:07 through 2026-09-11 22:05 Riyadh (end of the M1 data), 33 gate rows.
Every boundary from gate 8 onward was walked and verified live in this
session (respect reactions, anchor breaks, Weekly-close body-breaches,
simultaneous-event collisions -- all per the rules above and below).

Applying the corrected parent-in-charge rule RIGOROUSLY (via a small script
that merges the established control-state timeline against every zone's
actual impact time, sorted) surfaced two corrections to gates already
shipped before the rule reached its final form:
- **Gate 2** (2026-02-16 -> 02-19 16:01): splits into two rows. No buy
  parent at all from 02-16 to 02-17 18:28 (zone #3 doesn't react until
  then -- it's the FIRST buy reaction in the whole dataset, so there is
  nothing to show before it). buy_parent="3" only from 02-17 18:28.
- **Gate 7** (2026-04-08 01:36 -> 04-29 21:37): buy_parent corrected from
  "7" to "1" (RB1, last reacted 2026-03-03 17:24) -- zone #7 was CREATED
  at 04-08 01:36 but not actually touched by price until 2026-06-08 12:31,
  long after gate 7 already ended.

Full sell/buy parent reaction history (each id's first reaction time):
  SELL: #2 (02-09 15:07) -> #6 (04-08 01:32) -> #8 (05-06 13:45) -> #15
    (07-29 21:53) -> #13 (08-07 15:34) -> #12 (08-19 16:29, current).
  BUY: none -> #3 (02-17 18:28) -> #1 (03-03 17:24) -> #9 (05-14 18:00)
    -> #11 (06-05 16:00) -> #7 (06-08 12:31) -> #5 (06-19 07:57) -> #14
    (07-23 15:43, current).

Regenerated: 122 H4 RBs authorized (up from 38), 152 5m BSO attempts (90
ENTERED, 61 H4_RB_BREACHED, 1 NO_ENTRY_IN_DATA). The full docstring inside
`build_manual_rb_gates()` was rewritten to state the rule once, generally,
rather than repeat per-gate reasoning inline for all 33 gates (that
reasoning lives in this doc's own gate-by-gate entries instead).

## Parent-in-charge rule, corrected: REACTED, not just created (2026-09-24)

The earlier "last RB on the current bias side" rule (below, 2026-09-23) was
WRONG in one critical way: it picked the last zone CREATED on that side,
even if price never actually touched it yet. User correction, verbatim:
"you need to distinguish between events caused and RB reaction caused
control gates. if price reacted off sell RB, the parent RB is in control
but if just continuation of trend (like swing high confirmation or swing
low exceedance of course kept us selling), the last reacted RB is in
control even if it was spent and even if it had candle body close."

`[RB-NEW]` **Parent-in-charge rule, final form**: the parent updates ONLY
when price actually REACTS off (impacts/touches) a zone on that side --
never merely because a new zone was created/triggered, and never merely
because a structural/swing/MSS continuation event fires. A continuation
event (structural break, RB-anchor break, swing-high/low confirm/exceed)
NEVER changes the parent by itself -- it keeps whatever zone was last
actually impacted on that side in charge, even if that zone is already
SPENT and even if it already died via the Weekly-close body-breach rule.

Re-derived the full sell-parent history under this corrected rule
(re-walked every sell-side gate from scratch): only 4 real sell parents
exist so far, each starting at that zone's own impact minute, not its
creation/trigger minute:
- **#2** from 2026-02-09 15:07 (zone #2's own impact -- gate 1 opens).
- **#6** from 2026-04-08 01:32 (zone #6's first touch) -- #2 stayed
  parent through gates 3, 4-sell-side, 5, 6a even though zone #4 was
  created in that window and zone #6 was created at 6a's own start
  (03-30 12:17) -- NEITHER was ever reacted to before this point, so
  neither was ever parent.
- **#8** from 2026-05-06 13:45 (zone #8's own impact, opening gate 9's
  sell side) -- stayed parent through every later sell-side gate
  (11, the 06-05/06-08/06-19 BOTH sell-sides, the 06-17/06-23 SELL_ONLY
  resumptions, the 07-23 BOTH sell-side, the 07-27 reversion) even
  though zones #10, #12, #13 were all created in that stretch --
  none of them had been touched by price yet.
- **#15** from 2026-07-29 21:53 (zone #15's own impact -- a real
  reaction, coinciding by pure timing coincidence with the confirmation
  of an unrelated swing low, not a causal link).

Zone #13 was NEVER actually a sell parent at any point, despite two of my
own answers claiming it was -- caught and corrected by the user before
being written into code. **Bookkeeping instruction from the user,
verbatim**: "if it was not known before, you should consider recording and
bookkeeping it. I do not want to explain myself in the future" -- this
entry exists specifically so this distinction never has to be re-explained.
Any future "who is the parent" question must be re-derived by walking
every gate's own IMPACT events, not by re-reading `build_manual_rb_gates()`
(the code still records the WRONG pre-correction parents for this window
as of this entry -- not yet re-written to match; check this doc, not the
code, until it is).

## Real bug caught by the user from the H4 table (2026-09-23)

H4 RB #143 (SELL, gate 5, 2026-03-23) showed `Parent W: -` (blank). User
clarified: the parent shown for a control gate with no anchor-impact zone
should never be blank -- it's **the last RB zone on the current bias side**,
whether or not that zone has itself been impacted yet. "If RB2 was the last
selling RB, then in this 4h sell that RB2 is in charge." Checked
`weekly_rb_ledger.csv`: by 2026-02-19 16:01 Riyadh (gate 3's start), zone #4
(Weekly ORB, SELL, zb=1.18722/zt=1.19283) had just been confirmed at that
exact same MSS-down minute -- the newest SELL zone in existence, superseding
RB2 (dead since gate 1). No newer SELL zone is born until zone #6 (origin
week 2026-03-23, after gate 5 ends), so zone #4 stays the sell parent
through gates 3, 4 (sell side), and 5.

`[RB-NEW]` **Parent-in-charge rule**: a control gate's displayed parent is
the most recently created RB zone sharing that gate's bias direction, not
necessarily the zone whose impact/MSS event opened the gate. An "anchor
zone" gate (one triggered by a specific zone's impact, e.g. gate 1/RB2 or
gate 4's BUY/RB1) still uses that triggering zone directly; a "no anchor"
gate (triggered by a structural/MSS event with no zone impact, e.g. gates
3/5) must look up the last same-direction zone instead of leaving the
parent blank.

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

## Gates 2-5 — 2026-02-16 01:00 Riyadh → 2026-03-23 14:06 Riyadh

**Claim (user-supplied), verified sub-claim by sub-claim against the real
ledger/swing/M1 data before any code was written:**

- **Gate 2, BUY_ONLY** (2026-02-16 → 02-23 Riyadh, parent zone #3 AIRB):
  RB2 dead → control reverts to the underlying UP trend at week open.
  Zone #3 (AIRB, BUY, zb=1.17652/zt=1.18095) impacted mid-week
  (2026-02-17 18:28 Riyadh) without ending BUY_ONLY — confirmed an AIRB
  touch alone does not flip control.
- **Gate 3, SELL_ONLY, no anchor zone** (2026-02-23 → 03-03 17:24 Riyadh):
  A **new** rule, distinct from gate 1's Weekly-close-body-breach rule —
  **structural break-of-structure**: the week-of-2026-02-16's own close
  (1.17921) is below the *prior* week's low (1.18086, week-of-02-09).
  Confirmed directly. Read as AIRB #3 failing + trend flip; no live SELL
  RB exists to anchor the campaign (RB2 already dead), so SELL_ONLY here
  has no parent zone.
- **Gate 4, BOTH** (2026-03-03 17:24 → 17:26 Riyadh, only 2 minutes):
  RB1 (W ORB #1, BUY, zb=1.15692/zt=1.15797) impacted 2026-03-03 17:24
  Riyadh, opening BOTH.
- **Gate 5, SELL_ONLY, no anchor zone** (resumes 2026-03-03 17:26 Riyadh):
  2 minutes after RB1's impact, price breaks below RB1's own anchor low
  (1.15692, confirmed swing week-of-2026-01-19) — low 1.15667 at
  2026-03-03 17:26 Riyadh. Confirmed near-immediate.
- **Stop, 2026-03-23 14:06 Riyadh**: user initially cited price 1.16162,
  but direct data check showed price had already exceeded the prior
  week's high (1.16159, week-of-03-16) earlier that same day, at 14:06
  Riyadh (high 1.1619) — **user confirmed 14:06/1.1619 is correct**, not
  the later 1.16162 print, and not the engine's own formally-confirmed
  SWING HIGH (which lags to 1.16394, week-of-03-30).

**`[RB-NEW]` Real, important rule difference confirmed here**: the
control-gate "stop" trigger uses the **first real-time tick that exceeds
the prior week's high/low** — NOT the engine's formal, delayed
two-sided-confirmed SWING event. This is the "event vs. candle reaction"
distinction the user set up from the start; gates react in real time,
the Weekly RB zone engine's own SWING/MSS detection is deliberately
slower/confirmed. Any future gate-boundary claim citing a "swing"
must be checked against BOTH definitions before encoding, since they
can disagree by up to a week and a meaningfully different price.

**Result**: `build_manual_rb_gates()` in `full_rb_viewer.py` now encodes
gates 1-5, then NONE from 2026-03-23 14:06 Riyadh onward (next gate not
yet given). 25 H4 RBs authorized across the known window (up from gate
1's 5): 5 BUY (gate 2, parent #3), 20 SELL (5 parent #2 from gate 1, 15
parentless from gates 3/5). Cross-checked every authorized row's side
against its own control_at_impact column — zero mismatches. 29 total 5m
entries (14 ENTERED, 15 H4_RB_BREACHED).

## Open questions / not yet tested by real gate data

- Does RB ever need its own countertrend/trend-alignment nuance beyond
  the OB SS9 rule, or does it inherit it exactly?
- Does AIRB promotion-in-place ever interact with a control gate boundary
  (e.g. promoted mid-gate vs. promoted after a gate closes)?
- Whether RB's simpler "wick impact + stranding only" lifecycle ever
  produces a gate-relevant case OB's close-through rule would have
  caught (or vice versa) — no case has surfaced yet.

## 2026-09-26 — dataset closed out (34/34 gates, chart-verified)

All 34 gates walked to the end of the 2026 CSV, chart-verified, and
cross-checked by an independent automated engine (`weekly_rb_control_engine.py`)
that matches this table exactly, to the minute. Final trade result:
90 entries (22 TP, 68 SL), net -2.00R. Full writeup, terminal state, and
handoff checklist: see `RB_HANDOFF.md`'s 2026-09-26 entry. No open
questions above were resolved by this sweep — they remain as listed.
