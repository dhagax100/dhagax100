# Handoff — ICT indicator debugging

Repo: `dhagax100/dhagax100`
Branch: `claude/afvg-rendering-bug-ctjnuq`
Latest commit: `134857a` (main), RB diagnostic locked at the same commit.

FVG file status: **finalized with ONLY issue 2 solved, by explicit user
decision.** Issue 1 and issue 3 were both investigated extensively in a
later session (see below) but their code changes were reverted — the
user chose to stop chasing both and ship the file as-is, issues 1 and 3
still open. Do not reapply either fix without the user asking again.
This finalized state (issue 2 + the earlier scan-range extension) has
now been **merged into `ICT_Full_OB_v24.pine`** too, at the user's
explicit request — see file 1 below for exactly what changed there.

RB file status: **DONE, locked, and merged into `ICT_Full_OB_v24.pine`.**
Two real bugs found and fixed (both also ported to main): a
dual-action-candle swing-detection bug shared with OB's original bug
(same fix, ported verbatim), and an ARB stranding formula that checked
the wrong swing kind/side because RB's bull/bear tag works differently
from AFVG's (see "RB fixes" section below for the full explanation —
important to understand before touching RB or ARB/AOB naming again).

This file exists so a fresh chat can pick up exactly where this one left
off, without the user having to re-explain any of it. Read this whole
file before touching any code.

## The four files, and where each one stands

1. **`pine/ICT_Full_OB_v24.pine`** — the MAIN combined indicator (Swings +
   MSS + OB/IFOB/AOB/AIFOB/OOB + IFVG/AFVG + IRB/ARB, all in one script).
   **OB is done.** All OB engine fixes were ported in from the diagnostic
   file (commit `e33df62`, "Main indicator: port all OB engine fixes from
   ICT_OB_Diagnostic.pine"). Do not restart OB debugging from scratch.

   **FVG is now merged too**, at the user's explicit request, matching
   the diagnostic file's finalized (issue-2-only) state:
   - `tryBullAFVG`/`tryBearAFVG` now have the `swlExt`/`swhExt` scan-range
     extension (from `b4b13d9`/`d99a0de`).
   - CLOSE-THROUGH invalidation is now restricted to `origin != 1`
     (IFVG only) — the issue 2 fix.
   - Issues 1 and 3's (reverted) experimental changes were NOT
     ported — the main file now matches the diagnostic file's actual
     shipped state exactly, not anything that was tried and undone.
   - The `liveIdx`/`pendingEligIdx` perf optimization (`b88aeb3`) was
     deliberately NOT ported — it's specific to the standalone
     diagnostic's unbounded zone growth on Daily history; the main
     file's OB code has its own, separate perf characteristics that
     were out of scope here and untouched.
   - Only the two functions/blocks above were touched, at the time of
     that merge. No OB/RB code was touched by the FVG merge itself.

   **RB is now merged too — DONE.** Main's RB section already matched
   the diagnostic's structure exactly (same functions, same call sites,
   ported earlier via `fbafa6b`) and already had the shared
   dual-action-candle swing-detection fix (it came in with the OB merge,
   since swing detection is one shared engine for OB+FVG+RB in this
   file). The only gap was the ARB stranding formula — fixed the same
   two lines here as in the diagnostic (commit `134857a`). Nothing else
   in RB needed porting.

2. **`pine/ICT_OB_Diagnostic.pine`** — standalone OB-only diagnostic.
   Superseded by the merge into main (`e33df62`). Not actively worked on
   unless a fresh OB-specific bug turns up.

3. **`pine/ICT_Full_FVG_Indicator.pine`** — standalone FVG-only
   diagnostic (no OB/RB code at all, by design, to stay well under
   TradingView's 20s script-execution limit on Daily history). This was
   the entire focus of the session that produced this handoff. Baseline
   locked at commit `2e88f5d` for issue 2 (issues 1/3 still open, see
   below) — plus one more universal fix layered on top after that:
   the same dual-action-candle swing-detection bug found in OB/RB
   (fix 1 in the RB section below) was ALSO still present here, since
   it had only ever been fixed in `ICT_OB_Diagnostic.pine`/main, never
   ported to the FVG file. Fixed the same way, ported verbatim. This is
   not a reopening of issues 1/3 — it's the same shared-engine bug as
   OB/RB, unrelated to the FVG-specific naming/detection questions.

4. **`pine/ICT_RB_Diagnostic.pine`** — standalone RB-only diagnostic.
   **DONE. Locked baseline, merged into main.** Started from a
   user-provided baseline (commit `ae8801a`) that replaced everything
   accumulated in prior sessions — **only IRB and ARB**, no AIRB (type
   field, hunts, pending pointers, promotion logic all removed), no
   debug-label tooling. Wick-based zones off a fixed swing pivot, no
   scanning, no picking. Don't reconcile against the old AIRB-era
   commits (`fafc402` and everything back through the AIRB rebuild
   history) — those are superseded, not a reference to merge back in.

   Two real bugs found and fixed against that baseline (see "RB fixes"
   below for full detail) — both also ported into
   `ICT_Full_OB_v24.pine`. Do not restart RB debugging from scratch;
   this is a finished, locked file, same status as OB.

## FVG status — three numbered issues this session

The user numbers issues as we go and revisits them by number. Keep that
convention alive in the new chat.

### Issue 1 — AFVG missed detection (INVESTIGATED IN DEPTH, code reverted, still OPEN)

A real AFVG gap (confirmed by hand-tracing real EURUSD Daily OHLC,
Thu 31 Jul – Tue 05 Aug 2025) was structurally impossible for the old
scan to ever find: the scan's upper bound stopped exactly at the swing
pivot candle, one candle short of where the real closing candle of the
gap actually sat.

Originally "fixed" in two commits (`b4b13d9`, `d99a0de` — extended the
scan's upper bound by one candle, then guarded against out-of-bounds on
dual-action candles). **These commits are still in history but a later
session found the real bug goes deeper**, and additional attempted
fixes on top were ultimately reverted — see below.

**The concrete example, fully hand-traced (real numbers, verified by
close[i]=open[i+1] chaining):**

| Date | O | H | L | C |
|---|---|---|---|---|
| Thu 31 Jul | 1.14032 | 1.14607 | — | 1.14123 |
| Fri 01 Aug | 1.14123 | 1.15969 | 1.13914 | 1.15853 |
| Mon 04 Aug | 1.15894 | 1.15965 | 1.15494 | 1.15679 |
| Tue 05 Aug | 1.15679 | 1.15879 | 1.15277 | 1.15751 |

Downtrend regime. The gap: `c1=Jul31 (H=1.14607)`, `c3=Aug4 (L=1.15494)`
— a genuine rising-shape gap (`h1 < l3`). **Aug 1 is a dual-action
candle that fully engulfs BOTH neighbors** — its range `[1.13914,
1.15969]` contains all of Jul 31's range and all of Aug 4's range. This
makes Aug 1 serve as BOTH the reference swing low (via breaking Jul
31's low) AND, once later confirmed, the swing high pivot (its own high
is the true peak, higher than both neighbors) — `aobSWLi == newSwhI ==
Aug1` in the code's terms. Aug 5 (breaking Aug 4's low) is what finally
confirms Aug 1 as the swing high, triggering `tryBearAFVG`.

**Debug label result (confirmed via live chart, `InpFocusFvgDate`
= 2025-07-31, current code): `state=3 orig=0, leftIdx=14023,
trigK=14025, eligK=14026, stopK=14026`.** This is an ordinary,
unrelated continuation IFVG from the down-leg — not the target gap.
No AFVG box ever appears in this window.

**Two internal fixes were tried and both proved NOT to be the actual
blocker** (confirmed by re-checking the debug label after each — output
was byte-identical to before any fix):
1. Guard price equality (`h1 <= guardPrice` instead of `<`) — reasoning
   was that when the pivot candle IS c1, its own high always equals
   guardPrice exactly, never strictly less. Applied, committed, tested
   — no change to the debug label. Reverted along with everything else
   per the user's decision to stop here.
2. Range extension to `k-1` instead of a fixed pivot+1 — analysis
   showed this wasn't even needed for this specific example once
   `aobSWLi == newSwhI == Aug1` was accounted for (the old range formula
   already reaches Aug 4). Never actually applied to the file.

**Leading unconfirmed hypothesis, not yet tested:** on Aug 1's own bar,
the swing-detection code may ALSO fire a "Second break: SWH" against
some OLDER, previously-armed swing high (from further back in the
downtrend) — if Aug 1's high breaks that older reference too, regime
flips to UP right there on Aug 1's own bar, not later at Aug 5. If so,
by the time Aug 1 finally gets structurally confirmed as swing high (at
Aug 5), `tryBearAFVG`'s gate (`pReg==2`) already fails, because the code
thinks we're in an uptrend by then — explaining why the hunt never
fires at all, independent of the guard/range questions above. **Next
step, if this gets picked back up**: check whether an MSS mark (✕)
appears exactly on Aug 1's candle. Never confirmed — the user chose to
stop investigating issue 1 at this point.

**Also worth revisiting if this comes back**: `InpDebugValues` +
`InpFocusFvgDate` (still in the file, defaults to 2025-07-31) is the
tool for this — it shows the SINGLE zone whose `leftIdx` is nearest the
given date. Set the date precisely to the candle you care about (not a
nearby one) — the debug scan will silently show an unrelated zone
otherwise, which caused real confusion earlier in this investigation.

### Issue 2 — AFVG box stopped extending before impact (SOLVED)

Hand-traced against real EURUSD Daily OHLC (Nov 2025) with a leg that
had two AFVG gaps: a wide lower one (5-7 Nov, zone 1.14979-1.15295) and
a narrow upper one (12-14 Nov, zone 1.15977-1.16060). Both stopped
drawing on the exact same day (Wed 12 Nov), which looked like a
coupling bug (one zone's impact taking out another). It wasn't — traced
line by line, each zone's SPENT decision only ever reads its own
`zb`/`zt`/`stopK`, no shared state between zones.

**Actual root cause:** the CLOSE-THROUGH INVALIDATION rule (a candle's
close moving past the zone's far edge = dead) was applied to BOTH IFVG
and AFVG zones identically. That's correct for IFVG (a continuation
zone starts on the "correct" side of price, so a close back through it
later is a genuine reversal signal) but wrong for AFVG (an anticipatory
zone starts ALREADY on the far side of price by design, waiting for a
later return visit — so the same check is trivially true the instant
it becomes eligible, killing it on day one regardless of whether price
ever comes back).

In the traced example: both AFVG zones became eligible on the exact
same day (Nov 12, when the swing high that triggered both finally
confirmed). By then price had already rallied past the lower zone —
so it died via CLOSE-THROUGH the instant it went live, same day the
upper zone died from a genuine wick impact. Two independent rules,
same day, not a shared bug.

**Fix (commit `2e88f5d`):** CLOSE-THROUGH now only applies to
`origin == 0` (IFVG-style) zones. AFVG zones (`origin == 1`) can now
only end via IMPACT (real wick touch) or STRANDING (a real new
opposing swing forming beyond the zone — already correctly implemented
and untouched by this fix).

Also fixed in this session, unrelated to issue 2 but discovered along
the way while chasing a **real** 20-second timeout (not the earlier
debug-label one, a structural one):

- `b88aeb3` — STEP 2 (eligibility arming) and STEP 3 (spent/close-
  through/stranding lifecycle) both rescanned the ENTIRE `fvgs` array
  on every relevant bar. On Daily history going back decades, `fvgs`
  grows into the thousands (continuous per-bar gap scan), so this was
  effectively bars × total-zones-ever-created — the actual cause of the
  timeout, unrelated to the debug labels. Fixed with two small index
  lists (`liveIdx`, `pendingEligIdx`) that only track zones still
  actually live/pending, swap-removed once resolved. No creation/
  eligibility/lifecycle rule changed, only which zones get walked each
  bar.

### Issue 3 — "bullish AFVG in a downward leg" (DECISION MADE, code reverted — OPEN in the file)

Not a code bug. A naming/classification disagreement, raised while
verifying a real AFVG gap found inside a down-pullback leg within a
larger uptrend (Jan-Feb 2026 EURUSD data, gap at 1.18747-1.19060). The
code labels it "bullish" even though every candle that carved it was
moving down.

**The actual mechanism (confirmed against the code, not guessed):**
the `bull`/`bullish` field is assigned by which HUNT found the zone —
`tryBullAFVG` fires when the previous regime was UP (a down-pullback
within an uptrend) and tags its zone bullish; `tryBearAFVG` mirrors it
for downtrends. This names the zone by the trade/trend it's expected
to serve (a "buy zone" for when the uptrend resumes), not by the raw
shape of the candles that created it. Confirmed via `ICT_Full_OB_v24.pine`
that AOB uses the identical `pReg == 1` → bullish convention — so this
isn't an AFVG quirk, it already exists, unquestioned, in AOB.

**Where it was left:** the user pushed back hard — "candles will form
at the right in the uptrend leg, covering whatever's on the left...
since when do we mark bullish zone in downward leg." The explanation
given (this matches real ICT terminology — a bullish order block is
often literally a down-candle, named for what it sets up next, not its
own color) was **not accepted or rejected** — the chat ended there.

**Status: decision made, but NOT implemented in the file — reverted at
the user's explicit request to finalize the FVG file with only issue 2
solved.** The user confirmed that bearish-instead-of-bullish is the
CORRECT/INTENDED outcome for the Jan-Feb 2026 example (1.18747-1.19060)
if the fix were applied — that was agreement on what the right answer
should look like, not confirmation the live chart shows it (nobody
checked before the code was reverted).

**Decision, for whenever this gets picked back up:** shape-based.
AFVG's `bullish` tag should match IFVG's own convention exactly —
rising-shape gap (`high[c1] < low[c3]`) = bullish, falling-shape gap
(`low[c1] > high[c3]`) = bearish — regardless of which hunt
(bullish-context/uptrend-pullback vs bearish-context/downtrend-pullback)
found it. Since a bullish-context hunt only ever finds falling-shape
gaps and a bearish-context hunt only ever finds rising-shape gaps, this
would be a full inversion of the old labels for AFVG, not a per-zone
conditional.

**What the (reverted) implementation looked like, for reference if this
gets redone:**
- `tryCreateAFVGs`: flip the boolean passed to the two `addFVG(...)`
  calls (bullish-context hunt → `false`/bearish tag; bearish-context
  hunt → `true`/bullish tag). The `bullish` parameter itself still means
  hunt context, not the final label.
- STRANDING (`else` branch, AFVG/origin==1 zones): the `bullf`/
  `not bullf` conditions need swapping to compensate — that branch
  decides which geometric side (new swing high below zb, or new swing
  low above zt) counts as stranded, and that geometric truth doesn't
  change even though the label does. Skipping this swap would make
  AFVG stranding silently check the wrong side.
- Nothing else reads AFVG's `bullish` field in a way that matters: the
  eligibility-arming code and CLOSE-THROUGH check only ever run for
  IFVG zones (gated by `state==0`/`origin!=1`), and live AFVG boxes are
  colored green regardless of `bullish`.

**Not touched (and shouldn't be until the user asks):**
`ICT_Full_OB_v24.pine` — per the user's standing rule, the main
indicator does not get touched while a diagnostic file is being worked.
Its FVG section stays the older, pre-session copy, and its AOB/IFOB
naming stays exactly as it was. The open follow-up on AOB/IFOB naming:

AOB doesn't have AFVG's exact shape/intent conflict — it picks an
actual candle whose color already matches its label, by construction
of the scan (only up-close candles qualify for a "bullish" pick).
IFOB's opposite-color pick (it deliberately picks the strongest
down-candle for a "bullish" IFOB) matches real ICT terminology on
purpose. So AOB/IFOB naming isn't a guaranteed same-fix as AFVG's —
it needs its own decision from the user later, not assumed.

## RB status — DONE, two bugs found and fixed (both merged into main)

### Fix 1 — missing swing high/low after a dual-action candle

RB shares the exact same swing-detection code as OB (and originally had
OB's pre-fix bug: a blanket "block ANY swing confirmation on the candle
right after a dual-action/outside candle" rule, with no check for
whether the new confirmation was a genuine duplicate or a different,
legitimate point). This had already been found and fixed in OB
(`4401edd`) and ported to main (`e33df62`) — but RB's user-provided
baseline (`ae8801a`) carried the OLD pre-fix code forward, since that
fix had never landed in the RB file itself.

Fix: same as OB's — track the exact `(kind, swingIdx)` pair(s) the
dual-action candle confirmed, only block an exact duplicate, let any
different point through. Ported verbatim (diagnostic: `ffe98da`, main:
part of `134857a`'s branch history — main's swing detection already had
this since it's one shared engine, so only the diagnostic needed it).

### Fix 2 — ARB stranding checked the wrong swing kind/side

This one's a real, non-obvious bug worth understanding fully before
touching ARB/AOB naming again:

**The trap:** ARB's STRANDING code was a literal copy of AFVG's
formula. That's wrong because RB's `bullish` tag means something
different from AFVG's:
- **AFVG** tags a zone bullish by which **hunt** found it
  (`tryBullAFVG` fires in an uptrend-pullback context → bullish).
- **RB** tags a zone bullish by **raw wick type** (swing-low wick =
  always bullish, swing-high wick = always bearish), per RB's own
  header spec — completely decoupled from which hunt fired it.

Because of that, the hunt matching AFVG's bullish trigger condition
(`tryBullARB`, `pReg==1`) anchors on a swing-**high** wick → tagged
**bearish** in RB. The hunt matching AFVG's bearish trigger condition
(`tryBearARB`, `pReg==2`) anchors a swing-**low** wick → tagged
**bullish** in RB. RB's labels are the mirror image of AFVG's,
hunt-context for hunt-context — so copying AFVG's kind/side pairing
verbatim checked the wrong swing on the wrong side, for both
directions.

**Fix:** bullish ARB (low-wick, price sits above it, anticipating a
later fall back down to it) now strands on a new swing **low** that
tops out **above** its own top. Bearish ARB (high-wick, price below
it) strands on a new swing **high** that bottoms out **below** its own
bottom. This makes ARB's formula come out numerically identical to
IRB's — not a redundancy to "clean up," just a coincidence of RB's
uniform raw-wick tagging (unlike FVG, where IFVG and AFVG genuinely
differ). Fixed identically in both files, same commit message: the
diagnostic in `134857a`, and ported into main in the commit right
after it in this branch's log.

**Only the ARB stranding branch changed** in both files — creation,
IMPACT, eligibility, and IRB's stranding (whose raw-wick tag already
matches its own breakout direction, no flip needed) are untouched.

**Relevant to issue 3 (FVG naming) if that ever comes back:** this RB
bug is proof that blindly mirroring a formula across files with
different tagging conventions is a real, demonstrated failure mode —
worth keeping in mind if AFVG's naming ever gets changed to shape-based
(per issue 3's decision), since anything that reads AFVG's `bullish`
field elsewhere would need the same kind of careful re-derivation, not
an assumed copy.

## How this user wants to work (do not skip this)

- **Explain first, short, plain English.** No jargon dumps before a
  diagnosis is understood. Keep replies SHORT — this user has
  explicitly said "why the fuck are you talking too much." Answer the
  question asked, then stop.
- **Never claim "fixed" without a real, checkable diff.** This user has
  been burned by (in their words) hallucinated/repeated-code claims
  before, twice, and does not extend trust automatically. If accused of
  it, prove it — `git diff`, exact line numbers matched against their
  own screenshot, or `curl` MD5 + cache-header checks against the raw
  GitHub URL if caching is the suspicion.
- **Diagnose against REAL OHLC data, hand-traced.** The user reads
  candles off TradingView via click-lock (not hover — hover values
  proved unreliable earlier). Verify a sequence of screenshotted
  candles really are consecutive by checking `close[i] == open[i+1]`
  chains before trusting the numbers.
- **State blast radius before implementing a fix.** The user
  consistently asks "will this affect the rest of the code, in any
  way?" before saying "go ahead" — answer that plainly, unprompted,
  alongside every proposed fix, not just when asked.
- **When the user wants to hand-edit in the Pine Editor themselves**,
  give exact line numbers cross-checked against their screenshot/error
  trace — don't just re-paste the whole file.
- **Numbered issues persist across the conversation** — the user refers
  back to "issue 2," "gap 1," etc. Keep a running list, don't lose the
  numbering.
- **Never touch the main indicator (`ICT_Full_OB_v24.pine`) while
  working a diagnostic file.** Fixes, and even flagging comments, stay
  in the diagnostic being worked (e.g. `ICT_Full_FVG_Indicator.pine`)
  or in this HANDOFF doc. Nothing gets ported or noted in the main file
  until the user explicitly asks for that merge.

## Quick orientation for whichever file comes next

- All four `.pine` files share the same core engine shape: OHLC arrays
  pushed once per bar (`O_`/`H_`/`L_`/`C_`/`BI`/`BT`), a swing-detection
  pass (`peakIdx_`/`troughIdx_`/`addSH`/`addSL`/`addEv`), then a
  regime/MSS/zone-lifecycle pass keyed on `k = i` (the current bar's
  index into those arrays — valid range is always `0..k` at any point
  during that bar's own processing, a critical invariant for any
  index-arithmetic fix).
- `docs/trading_logic.md` has a plain-English reference for swings,
  MSS, OB, and FVG concepts (section 4 is FVG) — read it before
  re-deriving definitions from scratch.
- Full trace of everything that happened this session, including all
  verbatim back-and-forth, is in this branch's commit history
  (`b4b13d9` through `2e88f5d`) — commit messages are written in full
  sentences explaining root cause, not just "fix bug."
