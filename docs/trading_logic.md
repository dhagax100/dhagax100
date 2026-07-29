# Trading Logic Reference

This is a plain-English translation of the exact rules coded into the ICT_EA_1
system (cTrader EA, MQL5 indicator, and FXR Script port all share this same
logic). It's written for a human or a vision-based AI reading a chart by eye
on a replay platform, not for someone reading arrays/code -- anywhere the
original logic used precise index math, this describes the visual equivalent
of that same rule, not a simplification of it.

---

## 1. Swing Highs and Swing Lows

Track two running reference points as you move candle by candle:
- the **candidate peak**: the highest high since the last confirmed swing low.
- the **candidate trough**: the lowest low since the last confirmed swing high.

- A **swing HIGH** is confirmed the moment a candle's low breaks below the
  *previous* candle's low -- but only if the last confirmed swing was a LOW,
  not another high (swings must alternate: high, low, high, low, never two of
  the same kind in a row). The confirmed high's price is the candidate peak's
  own high, not necessarily the confirming candle itself.
- A **swing LOW** is confirmed the moment a candle's high breaks above the
  *previous* candle's high -- same alternation rule, mirrored.

**Same-candle ordering** (a single candle breaks both the prior high AND the
prior low -- a big "outside" candle): figure out which happened first inside
that candle using its own color. A bearish candle (closes below its open) is
assumed to have gone UP first, then DOWN -- so evaluate its high-break using
the OLD reference points, then its low-break using the freshly updated ones.
A bullish candle is assumed to have gone DOWN first, then UP -- evaluated in
the opposite order.

**Noise filter**: if the candle right before this one was itself one of these
"broke both sides" candles, and the CURRENT candle only breaks one side (not
both), ignore that single-sided break -- it's noise following a volatile
candle, not a genuine new swing point.

## 2. Market Structure Shift (MSS)

An MSS is recorded only when the trend genuinely **reverses**: price breaks
above the most recent confirmed swing high while the market was previously
in a downtrend (flips to up), or breaks below the most recent confirmed swing
low while previously in an uptrend (flips to down). The very first trend
establishment (before any prior trend existed at all) does **not** count as
an MSS -- there's nothing to reverse yet.

## 3. Order Blocks (OB)

Five states a zone can be in: **IFOB, AOB, AIFOB, OOB, SPENT.**

**IFOB (In-Favor Order Block)** -- created the instant a swing point gets
exceeded (a trend continuing or newly establishing). Look inside the
breakout leg (from the last opposite-kind swing, through the exceeded swing,
to the exceeding candle) for the single candle with the strongest close in
the OPPOSITE direction of the breakout (bullish breakout -> most
bearish-closing candle in that range; bearish breakout -> most
bullish-closing candle). That candle's **body** (open-to-close, not the
wick) is the zone.

**AOB (Anticipatory Order Block)** -- created the instant a retracement's own
swing confirms, without waiting for the prior swing to be exceeded. Same
candle-picking rule, but the range is [one candle before the previously
armed swing .. the newly confirmed retracement swing]. Plus a **straddle
guard**: if the picked candle's wick already reaches the price of the swing
that triggered this search, reject it -- that candle IS the pivot itself,
not a candle sitting inside the completed retracement.

**AIFOB** -- an IFOB created *early*: same range/pick rule as a real IFOB,
but created before the exceedance has actually happened, because the
opposite swing already confirmed while we were still waiting. If that swing
later does get exceeded, this AIFOB is promoted directly into a real IFOB
(not a duplicate). If a fresher swing supersedes it before that happens, it
just continues on as a normal AIFOB from then on.

**OOB (stranded)** -- a zone that hasn't been touched yet, but structure has
since proven it stale:
- IFOB/AIFOB: stranded by a further swing on the FAR side (price pulled away
  and made a new swing point without ever coming back to tag the zone).
- AOB: stranded by a swing on the NEAR side (a recovery attempt failed to
  make it back to the zone).

**SPENT** -- the zone gets touched: any wick reaching into its price range,
regardless of whether the reaction respects or violates it. This is final --
once touched, a zone is done. A zone that already went OOB can still later
get touched and flip to SPENT; either way, first touch ends its life.

## 4. Fair Value Gaps (FVG)

Exact same five-state lifecycle as OB (IFVG/AFVG/AIFVG/OFVG/spent mirror
IFOB/AOB/AIFOB/OOB/SPENT one-for-one), just picked differently: any 3-candle
sequence where candle 1's high sits below candle 3's low is a bullish gap;
candle 1's low above candle 3's high is a bearish gap. The empty space
between candles 1 and 3 is the zone. Unlike OB (one best candle only),
**every** qualifying gap within a leg counts, not just one.

Invalidation for FVG is simpler than OB's structural stranding: a candle's
body closing all the way through the far edge of the gap ends it, checked
independently of (and before) the structural OFVG check.

---

## 5. The Trading Cascade

**Step 1 -- Daily trigger.** Watch daily-chart **IFOB zones only** (not
AOB/AIFOB/OOB at this level). The moment price wicks into a live daily IFOB
-- any part of the wick touching the zone's price range -- that's the
trigger. No respect/violate check here; the raw touch is the whole signal.
Note only its direction (this was a bullish or bearish zone).

Important: a zone that already went OOB before ever being touched is dead --
it does not count as a trigger even if price later wicks through where it
used to be.

**Step 2 -- Wait for the pivot (1H chart).** If the daily zone was bearish
(we're heading toward a sell), wait for the next confirmed 1H swing **HIGH**
after the touch. If bullish, wait for the next confirmed 1H swing **LOW**.
Nothing before the touch counts -- only swings confirming after it.

**Step 3 -- Wait for the direction to actually flip (1H chart).** After the
pivot, watch for whichever of these happens first:

- **Scenario A**: a genuine 1H MSS in our target direction. The moment that
  happens, a fresh continuation IFOB forms from it (per the IFOB rule above)
  -- that new IFOB is the zone to trade.
- **Scenario B**: a same-direction retracement swing confirms *without* the
  armed swing being broken first (price pulls back, makes a new swing point,
  but never actually breaks the level that would flip the trend). If this
  happens first, pick the single most-extreme candle, of the SAME color as
  our target direction, within [one candle before the pivot .. this
  retracement swing] -- same "most extreme close" rule as everywhere else.
  That candle is the zone. (This is deliberately *not* the standard
  continuation-AOB rule, which would pick the opposite color and trade the
  opposite direction -- this is betting the retracement is actually the
  start of a reversal.)

Whichever of A or B occurs on the earlier candle wins; the other path is
simply never used for this attempt.

**Step 4 -- Wait for the reaction (1H chart).** Watch the zone from step 3.
The moment a 1H candle's wick touches it, check that *same* candle's close:
- Stayed on the correct side of the zone (didn't punch through) ->
  **respected**, move to step 5.
- Broke through -> **violated** -> this whole attempt is over (step 6).

**Step 5 -- Fire the entry.** Take the very next 1H candle after the
reaction candle.
- Check first: has price already broken past the stop level (the reaction
  candle's own wick extreme) at any point while waiting? If yes, abandon
  (step 6) -- don't enter a trade that's already lost before it starts.
- Otherwise, the first candle (starting with the very next one) whose open
  time falls inside the trading window fires the entry, at that candle's
  open price. Window (for this version): the first 2 hours of the London
  session or the first 2 hours of the New York session. If the reaction
  candle is already inside the window, or the very next candle is, enter
  immediately -- don't wait an extra hour past what's needed.

Stop-loss: the reaction candle's wick extreme (the low, for a buy; the high,
for a sell). Take-profit: 3x that risk distance. Move the stop to breakeven
once price reaches 2x that risk distance. Risk 1% of account equity per
trade. Only one trade open at a time, account-wide.

**Step 6 -- Expiry.** Whether this specific daily IFOB led to a trade, got
violated, got stranded, or timed out waiting -- it is now done. It never
triggers anything again, and nothing resets back to step 2 or 3 to retry
with it. The only way anything happens again is a genuinely new daily IFOB
touch, back at step 1. (A version that allows re-trading the same zone more
than once is a deliberately separate, later stage -- not part of this rule
set.)

---

## Quick-reference summary

1. Price wicks into a live daily IFOB -> note its direction.
2. Wait for the opposite-kind 1H swing (the "pivot").
3. After the pivot, wait for whichever comes first: a real 1H trend
   reversal (trade the IFOB it creates), or a same-direction retracement
   that holds without breaking the armed swing (trade the picked candle
   from that leg).
4. Wait for a wick into that zone whose same candle closes back in our
   favor (not through it).
5. Enter at the open of the first 1H candle after that reaction which falls
   in the London or New York first-2-hours window -- immediately if already
   there, otherwise the next one that is. SL at the reaction wick, 3R
   target, breakeven at 2R, 1% risk, one trade at a time.
6. That daily IFOB is now expired regardless of outcome -- wait for the next
   fresh one.
