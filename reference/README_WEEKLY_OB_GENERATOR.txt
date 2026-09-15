WEEKLY OB GENERATOR — STRUCTURE-OWNED OB LIFECYCLE

1. Put this file in the same folder as:
   EURUSD_m1_BidAndAsk.csv

2. Open Command Prompt in that folder. Example:
   cd %USERPROFILE%\Desktop\ForexTesting

3. Run the normal first trial:
   python weekly_ob_generator.py EURUSD_m1_BidAndAsk.csv --input-tz America/New_York --box-body-minutes 15

The program creates these files in the SAME folder:

   weekly_ob_ledger.csv         Every Weekly OB and its lifecycle
   weekly_ob_swings.csv         Weekly swings and MSS events
   weekly_ob_report.txt         Data coverage, structure and OB totals
   weekly_ob_viewer.pine        The TradingView display file

4. Open weekly_ob_report.txt first. It tells you whether the CSV was read,
   how much data was found, and the number of structure/OB events.

5. Open weekly_ob_viewer.pine in Notepad, copy all of it, then paste it into
   a new TradingView Pine Editor script and click Add to chart.

IMPORTANT

- Weekly swings and MSS own every OB decision. It displays:
    blue ▲ = swing high
    black ▼ = swing low
    blue/black ✕ = up/down MSS
  plus hollow OB boxes, red impact lines and a Weekly lifecycle table.
- Color rules: IFOB BUY blue; IFOB SELL black; AOB green; AIFOB orange;
  OOB red; SPENT keeps the color it had immediately before being spent.
  Rejected OBs stay in the CSV ledger but are not drawn, matching Pine.
- The Pine viewer now also labels each drawn source candle, for example
  `#12 OOB SELL`. This is an audit aid: verify the label sits on the intended
  origin candle before judging its box edges or lifecycle.
- It does not yet trade, calculate H4, 5m entries, RBs, FVGs, VIs, control
  states, or position sizing.
- It uses Bid OHLC for structural matching and retains the Ask columns for
  the later execution module.
- This origin-candle verification version uses the original Weekly session
  convention: Sunday 17:00 America/New_York. Weekend-gap treatment is paused
  until the correct OB source candles have been verified.
- The displayed box top/bottom is now a visual test requested by you: it uses
  the open of the first OBSERVED 15-minute candle and close of the last
  OBSERVED 15-minute candle inside the selected Weekly origin. Both 15-minute
  candles are assembled from your M1 rows. No missing minute is filled and no
  record is blocked. The ledger records each bucket, its observed open/close
  timestamp and its actual M1-row count for inspection.
- This 15-minute rule changes display boundaries only. It does not alter the
  locked swing/MSS, OB selection, type, trigger, eligibility, impact or status.
- If the first chart comparison does not match the locked TradingView facts,
  DO NOT change the data. Send the report and screenshots. We will lock the
  timestamp timezone / boundary after comparing real fixtures.

OPTIONAL COMMANDS

If your CSV timestamps are New York local time rather than UTC:
   python weekly_ob_generator.py --input-tz America/New_York

To test Ask candles as a diagnostic only:
   python weekly_ob_generator.py --price-side ask

To generate fewer structure labels for TradingView:
   python weekly_ob_generator.py --pine-labels 60

To draw fewer OB boxes:
   python weekly_ob_generator.py --pine-obs 60

To use another observed display-candle size from the same M1 file:
   python weekly_ob_generator.py EURUSD_m1_BidAndAsk.csv --input-tz America/New_York --box-body-minutes 15
