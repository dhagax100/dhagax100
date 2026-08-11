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
| Jul 2026 | Mesh plan: 3 hex levels, y+≈1 at highest Re, <1% threshold | Nuradin + Claude | Standard GCI approach. Nu and f as convergence monitors. **NOTE: conflicts with `docs/Proposal_Last.pdf` Section 3.6, which specifies tetrahedral mesh — see Open Items below, unresolved as of 2026-08-11.** |
| Aug 2026 | Keep the 27-run L27 Taguchi design (3 geometric factors × 3 nanofluids × 3 concentration levels) as the actual study plan, overriding the smaller single-pitch/single-nanofluid study described in `docs/Proposal_Last.pdf` | Nuradin | `Proposal_Last.pdf`'s methodology chapter describes a narrower study (fixed dpo/tp, 5 twist-pitch levels, only Fe₂O₃-GO, φ swept 0-2% continuously, no Taguchi/L27 mentioned anywhere). When asked which reflects the real plan, Nuradin confirmed the bigger 27-run repo design is correct. The proposal's *equations* (governing equations, exergy, entropy/Bejan/Ns, PEC, hybrid mixing rules, turbulence model, solver settings) remain adopted as verified reference material — only the DOE scope (factor levels, number of nanofluids) is superseded. |
| Aug 2026 | Turbulence model: Realizable k-ε + Enhanced Wall Treatment | Confirmed via `docs/Proposal_Last.pdf` Section 3.3.4 | Resolves the previously open item — proposal explicitly states realizable k-ε was used in "the reference methodology" (Mohammed et al. 2022) and adopted here. Must stay identical across GCI, correlation validation, Dudley validation, and all 27 runs. |

## Open / Pending Advisor Feedback

| Item | Status | Notes |
|------|--------|-------|
| Representative Re and Tin for production runs | Awaiting confirmation | Workflow plan asks advisor to confirm specific values |
| Exact nanofluid property correlations for Al₂O₃-MWCNT and Ag-MgO | Needs literature search | Fe₂O₃-GO properties now verified from `docs/Proposal_Last.pdf` Table 14 (density, k, cp; viscosity uses shape-coefficient model, not tabulated directly). Al₂O₃-MWCNT and Ag-MgO still need sourcing — proposal only covers Fe₂O₃-GO. |
| Glass envelope and vacuum annulus modeling | Decided: excluded | Receiver-tube-scale model only. Heat loss handled via boundary conditions. Confirmed consistent with proposal Section 3.2 ("parabolic reflector, glass envelope, annular vacuum region... are not included in the computational domain"). |
| **Mesh type: hex vs. tetrahedral** | **Conflict — unresolved** | CLAUDE.md previously specified "3 hex mesh levels." `docs/Proposal_Last.pdf` Section 3.6 explicitly specifies "unstructured tetrahedral mesh... with inflation layers." These disagree. Must be resolved before Module 4 (mesh) production work — see thesis-assistant session, 2026-08-11. |
| Proposal's own grid-independence/validation numbers vs. this repo's smooth-tube GCI numbers | Unreconciled | `Proposal_Last.pdf` Table 13 (grid independence, enhanced geometry, Tb=300K) and Figs 6-9 (validation) contain specific results that don't match `mesh-validation/Mesh_and_Validation_Workbook.xlsx`'s smooth-tube GCI numbers (different Tb, different Nu values ~780-800 vs ~650-661 at Re=100k). Unclear if proposal numbers are completed results or template values inherited from Mohammed et al. (2022)'s reported structure. Flagged 2026-08-11, not yet resolved. |

## Corrections Made

| Date | What was wrong | Corrected to |
|------|---------------|-------------|
| Jul 2026 | DOE initially had 4 factors (missing concentration) | Added φ as 5th factor |
| Jul 2026 | Learning roadmap had mismatched video resources | Corrected with verified appendix |
| Jul 2026 | Claude gave wrong SpaceClaim UI steps | Nuradin figured out correct workflow independently |
| Jul 2026 | Metallic appearance assumed doable in SpaceClaim | Actually requires KeyShot rendering |
