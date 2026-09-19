RB (REJECTION BLOCK) ENGINES — WEEKLY, H4, 5M, COMBINED VIEWER

This is the RB analog of `README_WEEKLY_OB_GENERATOR.txt` from the original
OB export. Swing/MSS detection is unchanged from OB (byte-identical, see
docs/RB_TRADING_SYSTEM_HANDOFF.md SS3b); only the RB zone construction/
lifecycle rules (from RB_Indicator_v1.pine's addRBFromSwing/tryBullARB/
tryBearARB/STEP2/STEP3) are new.

FILES IN THIS FOLDER

  weekly_rb_generator.py   Weekly RB engine (swing/MSS + Weekly RB zones)
  h4_rb_engine.py          4H RB engine, reuses WeeklyRBEngine on a native
                           4H bar grid; also NOW gates every H4 RB zone
                           through the same Weekly control permission that
                           gates OB's H4 (see "CONTROL GATING" below)
  five_rb_bso_engine.py    5m BSO (Break-of-Swing Opportunity) entries on
                           control-authorized H4 RB zones; reuses OB's
                           run_bso/structural_invalid_at/run_bso_chain/
                           ledger_row/aggregate_5m functions UNCHANGED
                           (imports them from ob_reference/five_bso_engine.py
                           at runtime — that file must be present alongside
                           this one, or its four functions copied in)
  full_viewer_rb.py        Combined Weekly + H4 Pine (TradingView) viewer;
                           draws every computed RB zone (NOT filtered by
                           the control gate — see CAVEATS)

RUN ORDER AND EXACT COMMANDS

1. Put EURUSD_m1_BidAndAsk.csv in this folder (or pass its path).
2. weekly_control_engine.py (from the OB reference set) must be run FIRST
   against the same CSV, to produce weekly_control_ledger.csv in the same
   folder as the CSV — h4_rb_engine.py and five_rb_bso_engine.py both
   require this file and will exit with an error naming it if missing.
   This file is included in ../data/ (already generated) if you're not
   regenerating it yourself.

   python3 weekly_control_engine.py EURUSD_m1_BidAndAsk.csv --input-tz Etc/GMT+2

3. Weekly RB:
   python3 weekly_rb_generator.py EURUSD_m1_BidAndAsk.csv --input-tz UTC
   -> weekly_rb_swings.csv, weekly_rb_ledger.csv, weekly_rb_report.txt

4. H4 RB (requires weekly_control_ledger.csv next to the CSV, or pass
   --control-ledger):
   python3 h4_rb_engine.py EURUSD_m1_BidAndAsk.csv --input-tz UTC
   -> h4_rb_swings.csv, h4_rb_ledger.csv, h4_rb_report.txt

5. 5m BSO for RB (requires the same control ledger; run after step 4,
   though it recomputes the H4 RB pass itself rather than reading
   h4_rb_ledger.csv):
   python3 five_rb_bso_engine.py EURUSD_m1_BidAndAsk.csv --input-tz UTC
   -> five_rb_bso_ledger.csv

6. Combined Pine viewer (no control-ledger dependency — draws everything,
   see CAVEATS):
   python3 full_viewer_rb.py EURUSD_m1_BidAndAsk.csv --input-tz UTC
   -> full_viewer_rb.pine
   Open in Notepad, copy all, paste into TradingView Pine Editor, Add to
   chart. Attach to EURUSD. Weekly chart shows Weekly RB zones + swing/MSS
   labels + a ledger table; H4 chart shows H4 RB zones + table; 5m chart
   shows the same H4 RB boxes (no table), matching full_viewer.py's own
   OB convention.

   All RB commands above (steps 3-6) default to --input-tz UTC as of the
   2026-09-19 session: the raw CSV Date/Time columns are now treated as
   already being UTC wall-clock, per the user's explicit decision (see
   docs/RB_TRADING_SYSTEM_HANDOFF.md, "raw = UTC directly" entry). This is
   a deliberate change from the RB port's earlier Etc/GMT+2 default and is
   NOT the same flag the OB pipeline (step 2, weekly_control_engine.py)
   uses — that script is unchanged and still defaults to Etc/GMT+2.

CONTROL GATING (added 2026-09-18, see docs/RB_TRADING_SYSTEM_HANDOFF.md SS8)

RB's own pine spec (RB_Indicator_v1.pine) has no control/permission concept
of its own. Rather than run ungated, h4_rb_engine.py and
five_rb_bso_engine.py both now obey the SAME Weekly control permission that
already gates OB's H4/5m opportunities (weekly_control_engine.py, run
unmodified on OB zones) — an RB opportunity is only "authorized"/actioned
when its direction (BUY/SELL) matches the Weekly control state
(BUY_ONLY/SELL_ONLY/BOTH) active at its impact time. h4_rb_ledger.csv now
has control_at_impact/authorized columns; five_rb_bso_engine.py only runs
BSO on authorized zones. Every H4 RB zone is still written to
h4_rb_ledger.csv for audit even when not authorized.

KNOWN CAVEATS (current state, be aware before trusting output blindly)

- full_viewer_rb.py's Pine output has NOT been chart-tested in TradingView
  (pasted/compiled/rendered) — it reuses OB's already-proven array-packing
  technique but that specific file has not itself been confirmed to compile.
- full_viewer_rb.py draws every computed RB zone; it does NOT filter by the
  new control-authorized gate the way full_viewer.py filters OB zones by
  `authorized`. This was an intentional scope boundary for the control-
  wiring task (only h4_rb_engine.py/five_rb_bso_engine.py were in scope),
  not an oversight — flagged here so it isn't assumed to already match.
- Weekly RB itself is NOT gated by control (only H4/5m are) — Weekly is
  where OB's own control state is computed FROM, so gating Weekly RB by
  Weekly control would be circular; this mirrors OB's own structure (OB's
  Weekly layer isn't gated by its own control output either).
- RB's ledger schema is deliberately smaller than OB's (no
  origin_first_price/H1-audit-body columns, no trigger_fact_source
  provenance split) — none of that OB-specific display-audit apparatus has
  an RB analog yet.
- No RB-specific SL/TP/BSO variant was built — five_rb_bso_engine.py reuses
  OB's BSO mechanics verbatim (verified POI-agnostic by reading the code,
  not assumed).

See docs/RB_TRADING_SYSTEM_HANDOFF.md for the full build history,
hand-verification evidence (specific record IDs/timestamps traced against
raw M1 data), and every decision made along the way.
