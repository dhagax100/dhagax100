# Project scope decision

This repository was created fresh rather than continuing inside
`dhagax100/dhagax100`, per explicit instruction: **"create new repo and
consider only the files and info given in the beginning of this chat."**

That means the sole authoritative inputs for this project are:

1. The master specification (38 sections) supplied as the task description —
   preserved verbatim in `SPEC.md`.
2. `Weekly and 4h baseline locked(4).txt` — preserved verbatim in
   `locked/Weekly_and_4h_baseline_locked.txt`.
3. `4h and 5m baseline locked(3).txt` — preserved verbatim in
   `locked/4h_and_5m_baseline_locked.txt`.
4. `TRADING_SYSTEM_HANDOFF.md` — preserved verbatim in
   `docs/TRADING_SYSTEM_HANDOFF.md`.

## What was explicitly excluded

`dhagax100/dhagax100` (the repo this session started in) already contains a
mature, independently-evolved set of files: `pine/ICT_Full_OB_v24.pine`,
`mq5/ICT_EA_1.mq5`, `mq5/ICT_Full_OB_v24.mq5`, `mq5/ICT_Swings_MSS_FVG.mq5`,
`ctrader/ICT_EA_1.cs`, `fxreplay/ict_swings_mss_fvg.fxr.js`, and
`docs/trading_logic.md`. None of that was carried into this repository. Its
relationship to the two locked baseline files above (same lineage? a later
fork? a different port?) was not established, and the instruction was to
consider only the chat-start files — so it was left untouched rather than
guessed at.

If work in `dhagax100/dhagax100` and this repository need to be reconciled
later, that reconciliation should be a deliberate, evidence-based comparison
(matching the handoff's own "ledger-only verification" discipline), not an
assumption that either one supersedes the other.

## What the two "locked" files actually are

Both `locked/*.txt` files are themselves complete Pine v6 scripts (not prose
documentation), each beginning with a header comment identifying its lineage
as a port of a supplied C# source:

- `Weekly_and_4h_baseline_locked.txt`: `indicator("SI EA Visualizer - W1 to H4
  - H4 Table Working", ...)` — full Weekly swing/MSS/OB engine plus its
  Weekly→H4 handoff, H4 display, and an H4 table.
- `4h_and_5m_baseline_locked.txt`: an H4-focused build ("H4-only audit build")
  that also carries the 5m execution logic per the handoff's description of
  this file as "authoritative existing H4 structure, H4 OB and 5m execution
  implementation."

Per SPEC.md §1 and the handoff's own working style, these are **not to be
rewritten from a blank page**. New work should extend/wire these two engines
together and add the layers SPEC.md still requires on top of them (Weekly
direction-control state machine, immutable handoff records, alerts, replay
guarantees, EA/backtester, etc.), not re-derive their swing/MSS/OB rules from
scratch.
