# Master Specification — Multi-Timeframe ICT-Style Trading System

**Status: canonical, verbatim.** This file is the unmodified system architecture
specification supplied at project start. Do not simplify, reinterpret, or merge
its rules when implementing. Higher timeframes own their structural facts. Lower
timeframes consume those facts and provide execution timing.

Two source files under `locked/` are the authoritative *existing* implementations
referenced by this spec's own instruction not to recreate higher-timeframe facts
independently:

- `locked/Weekly_and_4h_baseline_locked.txt` — authoritative existing Weekly
  swing, MSS, and OB implementation (Pine v6).
- `locked/4h_and_5m_baseline_locked.txt` — authoritative existing H4 structure,
  H4 OB, and 5m execution implementation (Pine v6).

`docs/TRADING_SYSTEM_HANDOFF.md` is the project history / handoff record from the
prior working session (a separate Python + static-Pine historical-verification
track). It documents dozens of OB-by-OB fixes and locked decisions that must be
treated as precedent when they overlap with sections of this spec.

---

## 1. System architecture

The complete strategy contains two parallel top-down trading chains:

- System A: Weekly → 4H → 5m → 1m event resolution.
- System B: Daily → 1H → 5m → 1m event resolution.

Implement System A first. Preserve an independent interface for System B, but do
not invent its unsupplied directional rules.

The two chains will eventually operate beside each other inside one product.
The hierarchy for System A is:

- Weekly controls the market narrative and permitted trade direction.
- 4H supplies actionable POIs matching the currently permitted direction.
- 5m supplies the entry structure.
- 1m supplies exact event time, confirmation time and observed price.

Never allow 4H to recreate Weekly facts independently.
Never allow 5m to recreate 4H facts independently.
Never allow 1m to redefine whether a higher-timeframe structural event exists.
It only identifies the exact minute when an already-valid event became observable.

## 2. Required products

Build two engines with identical strategy semantics.

### Product A: Interactive TradingView indicator

The indicator must:

- Display Weekly POIs on Weekly and 4H charts.
- Display H4 POIs on H4 and 5m charts.
- Display native 5m entry structure.
- Update during live candles.
- Work causally in TradingView Replay.
- Display tables and visual objects.
- Send alerts at every important lifecycle event.
- Support display windows, focus IDs and visibility controls.
- Never reveal future information during replay.

### Product B: Expert Advisor and backtester

The EA must:

- Reproduce the indicator's event sequence exactly.
- Consume historical and live 1m candles.
- Aggregate its own Weekly, Daily, H4, H1 and 5m candles from the same 1m stream.
- Generate identical swing, MSS, POI and trade results.
- Maintain persistent IDs.
- Support alerts, logging, simulated trades and eventual automatic execution.
- Never use future candles or completed higher-timeframe values before they
  become available.

The indicator and EA must share one written specification and one set of
verification fixtures.

## 3. Definitions

### Market structure

A swing high is a structural high confirmed when later price action satisfies
the locked swing-confirmation rule. A swing low is its exact mirror.

An MSS is a strict break of the currently protected swing in the opposite
structural direction. A bullish structural break requires price to trade
strictly above the relevant high. A bearish structural break requires price to
trade strictly below the relevant low. Equality does not count as a break.

A candle can perform high-side and low-side actions during the same
higher-timeframe candle. The 1m sequence determines which happened first. If
both extremes occur inside the same 1m candle and their order cannot be known
from OHLC, use the locked deterministic candle-direction tie-breaker and report
that tie-break decision in the audit log.

### Point of interest

POI means any supported price zone capable of producing a reaction and market
structure. The planned POI families include:

- Order block
- Rejection block
- Fair value gap
- Volume imbalance
- Any later POI type added through the same interface

Every POI record must contain:

- Unique persistent ID
- Source timeframe
- POI family
- POI subtype
- Bullish or bearish side
- Pro-trend, aggressive or old classification
- Bottom boundary
- Top boundary
- Origin time
- Trigger time
- Trigger price
- Trigger confirmation time
- Eligibility time
- Eligibility price
- Eligibility confirmation time
- Impact time
- Impact price
- Impact confirmation time
- Protected structural swing
- Current lifecycle state
- Original lifecycle state
- Pre-spent state
- Rejection flag
- Structural breach time
- Weekly-close breach time
- Parent POI ID
- Child POI IDs
- Data-quality status

Do not substitute generic textbook formulas for POI types whose exact
construction rule has not yet been supplied.

The locked files currently provide the authoritative implementation for the OB
family. Build other POI families as separate modules. Keep them disabled until
their exact rules are supplied. Their absence must not alter the OB engine.

## 4. Order-block definition

An OB is the selected source candle identified by the locked swing, MSS and
backward-search procedure. Its price zone uses the candle body:

- Bottom = minimum of open and close.
- Top = maximum of open and close.

The wick does not define the displayed OB boundaries.

Every OB receives a permanent ID based on chronological creation order.
Filtering, replay, deletion of drawings and focus mode must never renumber
historical OBs.

### OB types and states

Use these state values:

- IFOB = 0
- AOB = 1
- OOB = 2
- SPENT = 3
- AIFOB = 4

Definitions:

- IFOB: an in-favor order block created or promoted by the relevant structural
  break.
- AOB: an aggressive order block formed during continuation or pullback
  structure before full trend confirmation.
- AIFOB: a pending anticipated in-favor order block. It can later be promoted
  while preserving its original identity.
- OOB: an out-of-balance or stranded POI that no longer qualifies for
  downstream trade execution.
- SPENT: an OB that has received its valid impact.

An OB must preserve both its original type and current state. AIFOB origin
must remain recorded as AIFOB even if it later becomes IFOB. A waiting AOB can
become IFOB only through the matching MSS and only if it remains alive,
unspent, unrejected and not already eligible. Do not create two same-direction
OB records from the same origin candle. OOB is never eligible for downstream
trading on Weekly, H4 or 5m.

## 5. OB visual conventions

Use hollow boxes without background fill. Default state colours:

- Bullish IFOB: blue.
- Bearish IFOB: black or a visible near-black colour on light charts.
- AOB: green.
- AIFOB: orange.
- OOB: red.
- SPENT: retain the colour of the state immediately before impact.
- Old untouched opposing POI: red and explicitly labelled OLD.
- Rejected POI: hidden from normal visuals but retained in the audit ledger.

Impact lines are red vertical lines with partial transparency. A POI box begins
at its true origin candle. A POI box stops at the chart candle containing its
exact impact minute. It must never stop at the following candle.

## 6. POI lifecycle events

### Creation

Creation means the structure engine has identified the POI and assigned its
permanent ID and boundaries. Creation does not automatically mean the POI is
eligible for downstream trading.

### Trigger

The trigger is the structural event that activates the POI lifecycle. Store
separately:

- Broken structural level
- Exact 1m event time
- 1m candle confirmation time
- Observed 1m high or low

The table must show the exact observed event price, not merely the structural
threshold.

### Eligibility

IFOB, AOB and AIFOB wait for the required valid swing event unless the locked
subtype rule states otherwise. Eligibility must:

- Occur after the trigger when required.
- Use the correct same-direction swing.
- Respect the POI's body boundary.
- Reject the POI if the required eligibility structure violates its boundary.
- Store the exact 1m eligibility time.
- Store the correct 1m high or low as eligibility price.
- Appear immediately when the confirming minute closes.

Never substitute the Weekly or H4 candle opening time for eligibility time.

### Impact

Impact means the first strict 1m penetration of an eligible POI:

- Bullish POI impact: first 1m low strictly below the POI top.
- Bearish POI impact: first 1m high strictly above the POI bottom.

Equality alone does not count as structural penetration.

The impact price displayed in the compact lifecycle table is the relevant
original POI boundary:

- Bullish POI: POI top.
- Bearish POI: POI bottom.

The observed 1m extreme must remain separately available in the audit record.

When impact occurs:

- Record exact 1m event time.
- Record confirmation time one minute later.
- Set the POI to SPENT.
- Preserve its pre-spent state.
- Stop its box on the display candle containing the exact minute.
- Draw one impact line on that containing candle.
- Send the impact alert immediately after confirmation.

## 7. Exact-time mapping

Event time and display time are different fields. Event time is the exact 1m
timestamp. Display time is the opening timestamp of the chart candle containing
that minute.

For H4: H4 open ≤ event time < H4 close.

Example: event time 09:55; containing H4 candle 08:00–12:00; draw the event on
the 08:00 candle; never draw it on the 12:00 candle.

For 5m: 5m open ≤ event time < 5m close.

Example: event time 02:28; containing 5m candle 02:25–02:30; draw it on the
02:25 candle; never draw it on the 02:30 candle.

Never overwrite the exact event timestamp with the display candle timestamp.

## 8. Why the 1m base stream is mandatory

The higher-timeframe candle shows only open, high, low and close. It does not
reveal the sequence of events inside the candle. The strategy requires 1m data
to determine:

- Whether the high or low occurred first.
- Exact trigger time.
- Exact eligibility time.
- Exact impact time.
- Exact entry time.
- Whether invalidation occurred before entry.
- Whether SL or TP occurred first.
- When break-even became active.
- Whether an event existed before a replay cutoff.
- Which H4 or 5m candle contains the event.
- Correct live alerts.

The EA and external backtester must therefore use 1m as the base dataset and
aggregate every higher timeframe from it. The TradingView indicator may request
confirmed 1m child candles, but TradingView limits historical intrabar access.
Therefore:

- Use TradingView 1m data for recent history and live operation.
- Use several years of matching FXCM EURUSD 1m data for external backtesting.
- Prefer data from the same FXCM feed.
- Verify the external feed against known TradingView candles and known OB
  events.
- Store a data-source identifier with every backtest.
- Never claim exact agreement if feeds differ.
- Never manufacture an exact timestamp when the necessary minute data is
  absent.

Use these data-quality labels:

- EXACT 1M: the required minute exists and resolved the event.
- 1M DATA UNAVAILABLE: the structural event exists but the required minute is
  outside available coverage.
- LEDGER ERROR: minute coverage exists, but the resolver failed to produce an
  expected result.
- AMBIGUOUS: 1m OHLC cannot determine the order of two competing events
  occurring inside the same minute.

## 9. Weekly narrative and direction controller

Maintain two separate states:

Trend state:

- BULLISH
- BEARISH
- UNDEFINED

Trend describes the prevailing Weekly market structure.

Trade-control state:

- BUY_ONLY
- SELL_ONLY
- BOTH
- NONE

Trade control determines which H4 opportunities may generate 5m setups. Do not
assume the trend state and trade-control state must always match.

## 10. Bullish pro-trend sequence

When Weekly structure is bullish:

1. Identify every valid bullish in-favor Weekly POI located in the discount or
   lower area of the bullish leg.
2. Price normally approaches that buying area through a bearish pullback.
3. The first valid impact of a bullish Weekly POI activates the bullish
   campaign.
4. The impact must contribute to a valid H4 swing low before the required H4
   POI chain becomes actionable.
5. BUY_ONLY becomes the initial control state.
6. Hunt every valid bullish H4 aggressive POI and bullish H4 in-favor POI.
7. Every valid H4 POI impact starts an independent 5m buy setup.
8. The number of H4 opportunities can be zero, one or many.
9. Failure to obtain a trade from one H4 impact does not terminate the Weekly
   campaign.
10. Continue hunting later H4 POIs during the same week.

At the next Weekly open, evaluate the completed Weekly candle. If at least one
supporting bullish Weekly POI survives, continue BUY_ONLY during the new week.
Repeat this every week until a control-changing event occurs.

The bearish pro-trend sequence is the exact mirror.

## 11. Weekly breach rules

A Weekly buying campaign has two independent invalidation mechanisms.

### Immediate structural breach

For a bullish campaign:

- Price trades strictly below the protected Weekly swing low.
- Any strict exceedance counts, including 0.5 pip.
- Do not wait for the Weekly candle to close.
- Immediately terminate every buying thesis that depends on that protected
  low.

For a bearish campaign, use the protected Weekly swing high as the mirror
condition.

### Weekly-close POI breach

Evaluate this only after the Weekly candle closes. An intraweek wick can pass
through the POI without producing a POI-close breach, provided the protected
structural swing remains intact. Apply the exact rule belonging to each POI
family:

- OB: use the specified Weekly body-close rule.
- RB: use the specified Weekly body-close rule.
- Volume imbalance: use the specified Weekly body-close rule.
- FVG: breach requires the Weekly candle to close through the complete gap.

Do not apply the old simplified rule that any wick beyond the zone
automatically breaches it.

When several distinct Weekly POIs exist:

- Breaching one POI does not invalidate another POI that remains safe.
- Continue the campaign while at least one supporting POI remains valid.

When same-direction POIs overlap at substantially the same reaction location:

- Treat them as one composite Weekly reaction area for direction control.
- Preserve every component internally.
- Give the composite area its own ID.
- Record which component produced each trigger, impact or breach.
- The composite remains valid while its control rule says at least one
  qualifying component remains safe.

A deeper OB or RB situated below a breached FVG remains a separate POI unless
their ranges satisfy the composite-overlap rule.

## 12. Opposing POI encounter and dual-direction mode

Assume Weekly trend remains bullish and BUY_ONLY currently controls. Bullish
price movement can encounter:

- A newly created bearish aggressive Weekly POI.
- An older untouched bearish Weekly POI.

The moment price validly encounters such an opposing POI:

1. Change trade control from BUY_ONLY to BOTH.
2. Continue hunting bullish H4 aggressive and in-favor POIs.
3. Begin hunting bearish H4 aggressive and in-favor POIs.
4. Whichever valid H4 POI impacts first starts its corresponding 5m process.
5. Permit simultaneous buy and sell trades.
6. Do not close an existing trade merely because an opposite setup appears.
7. Treat each H4 impact and 5m trade chain independently.

The aggressive or old POI exists because it may:

- Produce a temporary counter-trend reaction.
- Produce a larger reversal.
- Eventually change the Weekly trend.

The system must not predict which outcome will occur.

## 13. Opposing POI gains control

An opposing bearish Weekly POI gains control when:

1. Price has encountered it.
2. The POI survives its applicable breach rules.
3. Its reaction produces a confirmed Weekly swing high.
4. No active bullish Weekly POI currently forces buy control.

When all four conditions hold:

- Change control from BOTH to SELL_ONLY.
- Keep the Weekly trend state BULLISH until the protected Weekly swing low is
  actually broken.
- Hunt only bearish H4 aggressive and in-favor POIs.
- Continue selling until another control-transfer event occurs.

An old untouched bearish POI follows the same rule as a newly created bearish
aggressive POI. The bullish mirror applies in a bearish Weekly trend.

## 14. Opposing POI loses control

While a bullish trend remains structurally valid, an opposing bearish POI can
fail through:

- Its POI-specific Weekly-close breach.
- A strict break above its protected Weekly swing high.

After failure:

1. Check whether another safe bearish aggressive or old Weekly POI remains
   active.
2. If one remains, preserve BOTH or SELL_ONLY according to its current control
   status.
3. If none remains, return to BUY_ONLY.
4. Do not invalidate a safe neighbouring POI merely because another POI
   failed.

## 15. Full Weekly trend reversal

If a controlling bearish movement strictly breaks the protected Weekly swing
low:

- Change Weekly trend from BULLISH to BEARISH.
- Bearish in-favor POIs become the pro-trend POIs.
- Bullish aggressive and old POIs become the opposing POIs.
- Use the exact mirrored control-state process.
- SELL_ONLY becomes the base pro-trend state when a valid bearish in-favor POI
  supports it.

The bullish reversal from a bearish trend is the exact mirror.

## 16. No-control state

A direction can lose control without the opposite direction gaining control.

Example:

1. A bearish Weekly POI controls and SELL_ONLY is active.
2. Price moves downward.
3. Price does not encounter any bullish Weekly POI.
4. Price nevertheless stops and forms a confirmed Weekly swing low.
5. The bearish POI has lost directional control.
6. No bullish POI caused the reaction.
7. Buying therefore has no valid POI support.

Required result:

- Change trade control to NONE.
- Stop opening new sell setups.
- Do not open buy setups.
- Allow already-open trades to continue under their management rules.
- Wait until price encounters a valid Weekly POI of either direction.
- Process that encounter through the normal control rules.

A swing by itself cannot grant directional control. A valid POI reaction must
support it.

## 17. Weekly-to-H4 handoff

Weekly must publish an immutable record containing:

- Weekly POI ID
- Family and subtype
- Direction
- Classification
- Boundaries
- Origin
- Trigger
- Eligibility
- Impact
- Protected swing
- Lifecycle state
- Breach state
- Control state
- Exact 1m timestamps
- Data-quality status

H4 consumes this record. H4 must not independently decide:

- Which Weekly POI exists.
- Which Weekly ID it has.
- Whether it impacted.
- When it impacted.
- Whether it controls direction.

On the H4 chart:

- Draw the Weekly POI from the H4 candle containing its Weekly origin.
- Stop the box at the H4 candle containing its exact impact or terminal event.
- Draw the impact line on the H4 candle containing the impact minute.
- Retain the exact minute in tables, alerts and logs.

## 18. H4 opportunity engine

For every direction permitted by the Weekly control state, hunt valid H4 POIs
of these classifications:

- In-favor H4 POI.
- Aggressive H4 POI.

For a bullish Weekly campaign:

1. Weekly POI impact contributes to an H4 swing low.
2. Track the latest relevant H4 swing high.
3. If H4 breaks that swing high, the H4 direction changes upward and an
   in-favor H4 POI can become valid.
4. If price reacts from a POI in the preceding bearish leg before completing
   that break, an aggressive bullish H4 POI can become valid.
5. Continue identifying every later valid bullish H4 aggressive or in-favor
   POI while BUY is permitted.
6. A valid H4 POI impact activates one 5m setup chain.

For bearish direction, mirror every condition. In BOTH mode, run bullish and
bearish H4 opportunity engines simultaneously.

Each H4 POI must have its own permanent ID and must link to:

- Parent Weekly POI or composite area.
- Weekly campaign ID.
- Direction-control state at creation.
- Direction-control state at impact.

## 19. H4 lifecycle timing

The H4 structure engine processes authoritative H4 candles. Confirmed 1m
children determine exact timing. Store for every H4 POI:

- Creation time
- Trigger event minute
- Trigger confirmation time
- Eligibility event minute
- Eligibility confirmation time
- First impact minute
- Impact confirmation time
- Structural level
- Observed 1m extreme
- Original impact boundary
- Containing H4 candle
- Containing 5m candle

An already-eligible H4 POI must be monitored proactively during the current H4
candle. Do not wait for the H4 candle to close before reporting an exact 1m
impact.

## 20. Five-minute BSO execution process

BSO is the complete 5m Break-of-Swing Opportunity process that begins after an
H4 POI impact. The H4 POI direction determines the 5m setup direction.

### Bullish BSO

1. Map the exact H4 impact minute to its containing 5m candle.
2. Begin the 5m structural search from that containing candle.
3. Find the first confirmed 5m swing low whose origin is inside the impacted
   H4 POI.
4. Its origin must occur in the impact-containing 5m candle or later.
5. Its confirmation must occur before H4 invalidation.
6. Select the immediately preceding structurally known 5m swing high as
   Candidate 1.
7. Candidate 1 may originate before the H4 impact.
8. Candidate 1 does not need to lie inside the H4 POI.
9. Arm Candidate 1 only when the qualifying resting swing low becomes
   confirmed.
10. Entry occurs at the first 1m high strictly above the candidate swing high.

### Bearish BSO

Mirror the bullish process:

1. Find the first confirmed 5m swing high inside the H4 POI.
2. Select the immediately preceding 5m swing low.
3. Entry occurs at the first 1m low strictly below that candidate level.

## 21. Candidate replacement

After the resting swing confirms:

- Continue monitoring new same-side candidate swings.
- For a buy, later confirmed swing highs can replace the active swing-high
  candidate.
- For a sell, later confirmed swing lows can replace the active swing-low
  candidate.
- There is no fixed maximum number of replacements.
- A replacement occurs only if the existing candidate has not already
  triggered entry.
- Replaced candidate lines must not remain as misleading historical entry
  lines.
- The current unresolved candidate extends to the current confirmed 5m edge.
- The winning candidate line stops at the exact 1m entry minute.

## 22. Pre-entry invalidation race

From candidate activation, continuously race:

- Exact 1m entry break.
- Exact 1m H4 far-boundary breach.
- Completed-H4 close invalidation.
- Confirmation of the next replacement candidate.

The earliest valid event wins.

If entry occurs first:

- Open the trade.

If H4 boundary breach occurs first:

- Cancel the BSO.
- Remove the unresolved candidate line.
- Record H4_OB_BREACHED.

If completed-H4 close invalidation occurs first:

- Stop all new entry hunting for that H4 POI.
- Record H4_CLOSE_INVALID.
- Do not terminate an already-open trade through this rule.

## 23. Stop loss

Use a structural stop without an added buffer.

For a buy:

- Search every relevant confirmed 5m swing low from the 5m candle containing
  the H4 impact through the exact entry minute.
- Use the lowest qualifying swing low.

For a sell:

- Search every relevant confirmed 5m swing high over the same period.
- Use the highest qualifying swing high.

Every swing used for the stop must have become confirmed no later than entry.
Risk equals the absolute distance between entry and structural stop.

## 24. Take profit

Use a fixed 3R target:

- Buy TP = entry + 3 × risk.
- Sell TP = entry − 3 × risk.

Store:

- Entry
- Original SL
- Risk in price
- Risk in pips
- TP
- Result
- Exact exit time

## 25. Break-even

Break-even uses H4 structure.

For a buy:

- After entry, find the first confirmed H4 swing low whose swing price lies
  inside the parent H4 POI.
- Activate break-even at that swing's exact 1m confirmation time.

For a sell:

- Use the first confirmed H4 swing high inside the parent H4 POI.

When break-even activates:

- Move the effective stop exactly to entry.
- Preserve the original structural stop in the audit record.
- Do not apply an additional buffer.
- Continue monitoring TP and break-even using 1m data.

## 26. Exit ordering

SL and TP count on touch, including equality.

Before break-even:

- First SL touch ends the trade as SL.
- First TP touch ends the trade as TP.

After break-even:

- First entry-price touch ends the trade as BE.
- First TP touch ends the trade as TP.

If two competing exits occur during the same 1m candle:

- Do not invent their order.
- Record AMBIGUOUS.
- Preserve both event prices and the shared minute.

## 27. Re-entry after SL

An SL can create another trade attempt from the same H4 setup.

After SL:

1. Start waiting from the exact SL minute.
2. Find the first new qualifying resting 5m swing.
3. Its origin may be the 5m candle containing the SL event.
4. Its confirmation must occur strictly after the SL.
5. Select the immediately preceding opposite swing as the new entry candidate.
6. Repeat the original entry sequence.
7. Continue using the structural stop pool beginning at the original H4
   impact-containing 5m candle.
8. Increment the trade-attempt number only when an actual entry occurs.
9. Allow repeated post-SL attempts until the H4 setup terminates.

A BE exit does not automatically arm another entry. A TP ends that trade
attempt normally.

## 28. Live indicator requirements

The indicator must update from confirmed information without requiring:

- Hiding and showing the indicator.
- Changing timeframe.
- Reopening settings.
- Waiting for the higher-timeframe candle to close when the event is already
  confirmed on 1m.

Use persistent state and incremental processing. Do not rebuild enormous
historical arrays on every minute. Do not allow arrays to exceed Pine limits.
Keep terminal historical POIs in cold storage for tables and replay, while
removing them from active per-bar iteration. Delete and redraw visual objects
deterministically on the last chart bar. Respect TradingView limits for labels,
boxes, lines, arrays and requested intrabars.

## 29. Replay requirements

Replay must behave like the market was live at the selected historical point.
At replay cutoff T:

- Use only confirmed 1m candles whose close time is at or before T.
- Build a partial Weekly, Daily, H4, H1 or 5m candle from available confirmed
  minutes.
- Hide every POI and event whose creation time is after T.
- Hide future trigger, eligibility, impact, breach, entry and exit
  information.
- Reveal each field only when its confirmation time is reached.
- Preserve permanent IDs.
- Recalculate control state causally.
- Produce the same result in all-POI, hidden-POI and focused-POI modes.

Replay filtering must affect computation and displayed facts, not merely hide
drawings after future information has already entered the state.

## 30. Display controls

Provide these controls:

- Months to display.
- Exact display-from date.
- Toggle selecting date or month window.
- Enable replay mode.
- Replay cutoff date, with zero meaning follow the chart replay position.
- Focus Weekly POI ID.
- Focus H4 POI ID.
- Focus 5m setup ID.
- Show or hide Weekly lifecycle table.
- Show or hide H4 lifecycle table.
- Show or hide 5m trade table.
- Show or hide impact lines.
- Maximum number of structural labels.
- Separate visibility toggles for each POI family.
- Separate visibility toggles for pro-trend, aggressive and old POIs.

For the Weekly POI visual control:

- Zero hides all Weekly OB boxes and their table rows.
- Enabled shows every selected POI inside the display window.
- Focus ID shows only that exact permanent POI ID.
- Focus mode overrides the ordinary display-window selection for the
  requested ID.
- Display filtering must not change lifecycle calculations.

## 31. Tables

### Weekly table

Columns: Weekly POI ID, Family, Type, Side, Classification, Bottom, Top,
Origin, Trigger time, Trigger price, Eligibility time, Eligibility price,
Impact time, Impact price, Protected swing, Breach state, Control state,
Status, Data-quality ledger.

### H4 table

Columns: H4 POI ID, Parent Weekly POI, Side, Type, Boundaries, Trigger,
Eligibility, Impact, Current lifecycle, Weekly control state, Data-quality
ledger.

### 5m table

Columns: Setup ID, Parent H4 POI, Parent Weekly POI, Side, H4 impact, BSO
stage, Trade-attempt number, Entry time and price, Original SL, Effective
stop, Risk in pips, TP, BE activation, Result, Exit time, MFE in pips and R,
MAE in pips and R.

## 32. Alerts

Every alert must include: Symbol, Feed, Event type, Direction, Source
timeframe, Exact event time, Confirmation time, Event price, Structural level,
POI boundaries, Weekly POI ID, H4 POI ID when applicable, 5m setup ID when
applicable, Trade-attempt number when applicable, Trend state, Trade-control
state, Data-quality status.

### Required alerts

Weekly alerts:

- Weekly swing high confirmed
- Weekly swing low confirmed
- Weekly MSS confirmed
- Weekly POI created
- Weekly POI triggered
- Weekly POI became eligible
- Weekly POI impacted
- Weekly POI rejected
- Weekly structural breach
- Weekly-close POI breach
- Composite POI updated
- Opposing POI encountered
- Control changed to BUY_ONLY
- Control changed to SELL_ONLY
- Control changed to BOTH
- Control changed to NONE
- Weekly trend changed

H4 alerts:

- H4 swing confirmed
- H4 MSS confirmed
- H4 POI created
- H4 POI triggered
- H4 POI became eligible
- H4 POI impacted
- H4 POI rejected
- H4 POI breached
- H4 close invalidation

5m alerts:

- BSO started
- Resting swing confirmed
- Entry candidate armed
- Entry candidate replaced
- Entry triggered
- SL calculated
- TP calculated
- Break-even activated
- SL hit
- TP hit
- BE hit
- Exit ambiguous
- Re-entry hunt started
- Setup terminated

Alerts must fire once per unique event ID. Reloading the indicator must not
duplicate historical alerts.

## 33. Backtesting requirements

The external backtester must:

- Read chronological FXCM EURUSD 1m OHLC.
- Validate timestamp order and missing minutes.
- Aggregate higher timeframes consistently with the chart session and
  timezone.
- Reproduce the Weekly, H4 and 5m engines.
- Process every event sequentially.
- Never use a candle's final high, low or close before that candle completes.
- Preserve intrabar event ordering.
- Record ambiguous same-minute outcomes.
- Export every lifecycle record.
- Produce campaign-level, setup-level and trade-level results.
- Compare known cases against TradingView.

Initial verification fixtures must include: Weekly OB #872, Weekly OB #877,
Weekly OB #878.

Known reference:

- Weekly OB #872 impact: 2026-06-05 11:37 at boundary price 1.15351.
- Weekly OB #878 eligibility: 2026-07-14 08:30 with observed price 1.14622.
- Weekly OB #878 impact: 2026-07-30 09:48 at boundary price 1.15075.

> Note: `docs/TRADING_SYSTEM_HANDOFF.md` §8 explicitly cautions against using
> these arbitrary legacy IDs as a required benchmark unless the exact source
> data/session is reproduced. Treat them as a starting fixture set to attempt,
> not an unconditional pass/fail gate, until their time basis is independently
> confirmed against the actual backtest data source.

Do not proceed to broad backtesting until the external engine reproduces the
known IDs, boundaries, timestamps and prices.

## 34. Measurement-only analytics

Calculate MFE and MAE after entry. Exclude the entry minute because 1m OHLC
cannot determine whether its high or low occurred before or after the entry
trigger. Calculate: MFE in price, MFE in pips, MFE in R, exact minute of MFE,
MAE in price, MAE in pips, MAE in R, exact minute of MAE. These analytics must
never change trade decisions.

## 35. Engineering rules

Use one authoritative engine per timeframe. Use immutable parent-to-child
handoff records. Keep calculation, presentation and alerts separate. Maintain
these modules:

- Data ingestion
- Candle aggregation
- Structure engine
- POI engine
- POI lifecycle engine
- Weekly direction controller
- Parent-child handoff
- 5m BSO engine
- Trade-management engine
- Replay engine
- Alert engine
- Visual renderer
- Tables
- Audit logger
- Verification tests

Use deterministic IDs and chronological processing. Do not scan all historical
records on every incoming minute. Use indexed active sets for mutable POIs and
trades. Preserve completed records separately. Never fix visual behaviour by
changing structural semantics. Never fix table behaviour by recomputing
lifecycle truth inside the table. Tables, drawings, alerts and trades must
read the same authoritative records.

## 36. Required implementation order

Build and lock the system in these stages:

1. Confirm the native Weekly structure and OB engine.
2. Add exact 1m Weekly trigger, eligibility and impact timing.
3. Verify Weekly tables, visuals, focus and replay.
4. Implement the Weekly direction-control state machine.
5. Define immutable Weekly-to-H4 handoff records.
6. Display Weekly POIs correctly on H4.
7. Confirm the native H4 structure and POI engine.
8. Connect Weekly control permissions to H4 opportunity hunting.
9. Confirm exact 1m H4 event timing.
10. Define immutable H4-to-5m handoff records.
11. Implement the complete 5m BSO process.
12. Implement SL, 3R TP and H4 break-even.
13. Implement post-SL re-entry.
14. Implement alerts.
15. Implement causal replay.
16. Build the external 1m backtester.
17. Compare indicator and backtester event by event.
18. Add the Daily → H1 → 5m system only after its complete narrative is
    supplied.
19. Add execution and position-sizing rules last.

Lock every successful stage before changing the next one.

## 37. Acceptance criteria

The build is acceptable only when:

- Weekly facts remain identical on Weekly and H4.
- H4 facts remain identical on H4 and 5m.
- Event timestamps remain exact 1m timestamps.
- Boxes and impact lines appear on containing candles.
- Live eligibility and impact appear immediately after their minute confirms.
- Replay never exposes future information.
- Focus mode does not change calculations.
- All-POI replay behaves identically to focused replay.
- Indicator reload does not repair missing state because state never
  disappears.
- Arrays remain within platform limits.
- Alerts fire once and contain complete identifiers.
- Tables, visuals, alerts and EA decisions agree.
- External backtest fixtures reproduce the verified TradingView cases.
- Missing minute data is reported honestly.
- The bearish implementation exactly mirrors the bullish implementation.
- No unsupplied POI formula is invented.

## 38. Current specification boundary

The OB-family structure and lifecycle rules, Weekly direction-control
narrative, H4 opportunity cascade and 5m BSO/trade-management process are
defined above. The following still require their exact proprietary
construction formulas before activation:

- Rejection blocks
- Fair value gaps beyond the stated breach behaviour
- Volume imbalances
- Any other POI family
- Exact overlap threshold for creating one composite POI
- Position sizing
- Account-risk percentage
- Spread, commission and slippage model
- Maximum simultaneous exposure
- Daily loss limits
- News and session filters
- The complete Daily → H1 → 5m direction narrative

Do not ask what an OB, AIFOB, 1m event clock, control state or BSO means. They
are defined in this specification. For any remaining undefined proprietary
rule, keep its module disabled and clearly mark it as SPECIFICATION_PENDING.
Continue implementing every fully defined component without modifying or
guessing the missing rule.
