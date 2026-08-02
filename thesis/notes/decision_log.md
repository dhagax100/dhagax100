# Decision Log

Track key decisions, who made them, and why. Update as the project progresses.

## Locked Decisions

| Date | Decision | Decided by | Rationale |
|------|----------|------------|-----------|
| Jul 2026 | 3 geometric factors (not 4) — dropped polygon sides (n) | Nuradin + Claude | Keeps design at 5 factors × 3 levels = L27. Adding n would need L81 or compromise balance. |
| Jul 2026 | Three hybrid nanofluids: Fe₂O₃-GO, Al₂O₃-MWCNT, Ag-MgO | Nuradin + Claude | Covers three enhancement mechanisms. Fe₂O₃-GO maintains baseline continuity. |
| Jul 2026 | Concentration levels: 0.5%, 1.0%, 2.0% (not starting at 0%) | Nuradin (caught omission) | 0% makes nanofluid type meaningless for that run. |
| Jul 2026 | Taguchi L27 orthogonal array (27 runs) | Advisor guidance | Advisor said "4 parameters, three nanofluids → ~27 runs." Matches L27 exactly. |
| Jul 2026 | Validation against Dudley Table D-1 (9 cermet/vacuum cases) | Standard practice | Same validation approach as Mohammed et al. (2022) baseline. |
| Jul 2026 | Mesh plan: 3 hex levels, y+≈1 at highest Re, <1% threshold | Nuradin + Claude | Standard GCI approach. Nu and f as convergence monitors. |

## Open / Pending Advisor Feedback

| Item | Status | Notes |
|------|--------|-------|
| Representative Re and Tin for production runs | Awaiting confirmation | Workflow plan asks advisor to confirm specific values |
| Exact nanofluid property correlations for Al₂O₃-MWCNT and Ag-MgO | Needs literature search | Fe₂O₃-GO properties available from Mohammed et al. (2022) |
| Glass envelope and vacuum annulus modeling | Decided: excluded | Receiver-tube-scale model only. Heat loss handled via boundary conditions. |
| Turbulence model: Realizable k-ε + Enhanced Wall Treatment | Working choice, awaiting advisor confirmation | Fluent's Fluid Flow template defaulted to SST k-omega. Switched to k-ε because solver_and_formulas.md/CLAUDE.md specify "Enhanced Wall Treatment," a k-ε-family near-wall option in Fluent that k-omega SST doesn't have. Inferred from wording, not an explicit model statement — confirm against Mohammed et al. (2022)'s actual turbulence model before production runs. Must stay identical across GCI, correlation validation, Dudley validation, and all 27 runs. |

## Corrections Made

| Date | What was wrong | Corrected to |
|------|---------------|-------------|
| Jul 2026 | DOE initially had 4 factors (missing concentration) | Added φ as 5th factor |
| Jul 2026 | Learning roadmap had mismatched video resources | Corrected with verified appendix |
| Jul 2026 | Claude gave wrong SpaceClaim UI steps | Nuradin figured out correct workflow independently |
| Jul 2026 | Metallic appearance assumed doable in SpaceClaim | Actually requires KeyShot rendering |
