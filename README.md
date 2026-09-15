# ICT Trading System — Weekly → 4H → 5m → 1m (System A)

This repository is scoped deliberately to a single set of inputs: the master
specification and the two locked Pine v6 source files supplied at project
start, plus the prior session's handoff record. It intentionally does **not**
inherit any other repository's code — see `docs/PROJECT_SCOPE.md`.

## Contents

- **`SPEC.md`** — the canonical, verbatim system architecture spec (38
  sections). This is the single source of truth for required behavior. Do not
  edit its rules; only correct transcription errors.
- **`locked/Weekly_and_4h_baseline_locked.txt`** — authoritative existing
  Pine v6 implementation of Weekly swing/MSS/OB structure and its W1→H4
  handoff/display. Treat as ground truth for those rules; do not reinvent them
  elsewhere in the codebase.
- **`locked/4h_and_5m_baseline_locked.txt`** — authoritative existing Pine v6
  implementation of H4 structure/OB and 5m execution. Same ground-truth status.
- **`docs/TRADING_SYSTEM_HANDOFF.md`** — full history of the prior
  investigation/verification session (separate Python + static-Pine
  historical-verification track for Weekly OBs against FXCM M1 CSV data).
  Contains locked decisions (e.g. Riyadh display time, origin-body rule,
  trigger-price semantics) that take precedence over generic spec language
  where they resolve an ambiguity the spec left open.
- **`docs/BUILD_ORDER.md`** — the spec's 19-stage build order (§36), tracked
  as a checklist against the actual state of this repo.
- **`docs/PROJECT_SCOPE.md`** — explains why this repo starts fresh instead of
  reusing `dhagax100/dhagax100`'s existing pine/mq5/ctrader files.

## Ground rules (from SPEC.md, restated for contributors)

1. Higher timeframes own their structural facts. Lower timeframes only resolve
   *when* an already-valid higher-timeframe event became observable — never
   *whether* it exists.
2. Do not simplify, reinterpret, or merge locked rules from the two `locked/`
   files. Port them faithfully; extend around them.
3. Every POI family other than Order Block is `SPECIFICATION_PENDING` and
   stays disabled until its exact construction rule is supplied (§38).
4. Lock each of the 19 build-order stages (§36) before starting the next one.
5. The indicator and the EA/backtester must share one specification (this
   repo) and one set of verification fixtures.

## Status

Repository scaffolded; native Weekly/H4/5m Pine engines carried over verbatim
from the locked sources. See `docs/BUILD_ORDER.md` for exact stage-by-stage
status and the next action.
