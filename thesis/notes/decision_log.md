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
| Aug 2026 | Mesh type: unstructured tetrahedral with inflation layers, same method for smooth-tube baseline and enhanced geometry | Confirmed via `docs/Proposal_Last.pdf` Section 3.6 | Resolves the hex/tet conflict below — see moved row under Corrections. |

## Milestones

| Date | Milestone |
|------|-----------|
| Aug 2026 | **Mesh independence achieved.** Mesh 3 (2.96mm, 8,658,088 elements) adopted for all 27 production runs — Nu and ΔP both clear the 2% bar vs. Mesh 4 (1.19% and 1.08% respectively). See `mesh-validation/gci_mesh_plan.md` for full data. Unblocks the 27-run Taguchi study. |

## Open / Pending Advisor Feedback

| Item | Status | Notes |
|------|--------|-------|
| Representative Re and Tin for production runs | Awaiting confirmation | Workflow plan asks advisor to confirm specific values |
| Exact nanofluid property correlations for Al₂O₃-MWCNT and Ag-MgO | Needs literature search | Fe₂O₃-GO properties now verified from `docs/Proposal_Last.pdf` Table 14 (density, k, cp; viscosity uses shape-coefficient model, not tabulated directly). Al₂O₃-MWCNT and Ag-MgO still need sourcing — proposal only covers Fe₂O₃-GO. |
| Glass envelope and vacuum annulus modeling | Decided: excluded | Receiver-tube-scale model only. Heat loss handled via boundary conditions. Confirmed consistent with proposal Section 3.2 ("parabolic reflector, glass envelope, annular vacuum region... are not included in the computational domain"). |
| ~~Mesh type: hex vs. tetrahedral~~ | **Resolved (Aug 2026)** | Unstructured tetrahedral mesh with inflation layers, used consistently for both the smooth-tube baseline and every enhanced (promoter) geometry — per `docs/Proposal_Last.pdf` Section 3.6. Hex was ruled out for the enhanced geometry (twisted square promoter is not practically hex-meshable across 27 variants); same mesh type is required on both baseline and enhanced sides so Ns/PEC comparisons aren't contaminated by a meshing-method difference. Supersedes CLAUDE.md's original "3 hex mesh levels" plan. |
| Proposal's own grid-independence/validation numbers vs. this repo's smooth-tube GCI numbers | Unreconciled | `Proposal_Last.pdf` Table 13 (grid independence, enhanced geometry, Tb=300K) and Figs 6-9 (validation) contain specific results that don't match `mesh-validation/Mesh_and_Validation_Workbook.xlsx`'s smooth-tube GCI numbers (different Tb, different Nu values ~780-800 vs ~650-661 at Re=100k). Unclear if proposal numbers are completed results or template values inherited from Mohammed et al. (2022)'s reported structure. Flagged 2026-08-11, not yet resolved. **UPDATE 2026-08-17: proposal's Table 13 also fails its own internal arithmetic (Nu% differences don't reconcile against the listed Nu values) — likely partially copied/adapted text, not a fully self-consistent source. See real paper's methodology below instead.** |
| **Real Mohammed et al. (2022) paper's actual grid-independence methodology (Section 2.6, Table 4) vs. this repo's GCI approach and vs. the proposal draft's Table 13** | **Resolved (Aug 2026)** | Verified 2026-08-17 directly from the published paper (uploaded PDF, not the proposal draft). Real paper: (1) monitors are Thermal Efficiency (η) and Entropy Generation Rate (Sgen); (2) simple consecutive-mesh-level % difference, no Richardson extrapolation / apparent order / Celik GCI formula; (3) threshold ~2%, not 1%; (4) tested at Re=10⁴, T_in=500K (mid-range, not highest Re); (5) adopted the 3rd of 4 mesh levels the moment it cleared 2% vs. the 2nd level, not the finest tested. **Decision (Nuradin, 2026-08-17): adopt the real paper's simple consecutive-% method and 2% threshold, but keep Nu and ΔP as monitors (not η/Sgen) — a hybrid choice, not a literal match to either source.** `PTSC_GCI_Workbook.xlsx` rebuilt accordingly: "GCI Calculation" sheet (Celik method) replaced with "Mesh Independence Check" sheet (simple % method); Mesh Run Data expanded to 4 mesh-level columns to match the paper's 4-level practice. See `mesh-validation/gci_mesh_plan.md` for full detail and the old Celik-method result (archived, not acted on). |

| **dpo=35mm (Level B3, largest promoter) causes a recurring mesh-quality failure** | **Confirmed 2026-08-21** | Run 8 (tp=2.8mm, Pt=200mm, φ=2%) and Run 16 (tp=1.4mm, Pt=300mm, φ=2%) both diverged with a floating point exception, both traced to Min Orthogonal Quality just below the 0.01 threshold (0.0096914 and 0.0092812 respectively) in the tightest-annulus region. Different tp, different Pt, different mesh method assignments (verified via Mesh Quality Worksheet, not guessed) — the one thing in common across both failures is dpo=35mm itself (annulus gap only ~15.5mm). This rules out meshing-method choice as the cause (Run 1 and Run 6 also excluded bodies from Patch Conforming without failing) and points to genuine geometric tightness. **All dpo=35mm runs (7, 8, 9, 16, 17, 18, 25, 26, 27 — Level B3 of the L27 design) are at risk and need a finer local mesh (smaller element size and/or local face sizing at the promoter corners) before their results can be trusted.** Both failed runs marked INVALID and red-highlighted in `PTSC_27Run_Master_Workbook.xlsx`.

## Corrections Made

| Date | What was wrong | Corrected to |
|------|---------------|-------------|
| Aug 2026 | Proposal's brick-shape nanofluid coefficients (Ck=6.0, a=14.9, b=123.3) don't match any row of the real Mohammed et al. (2022) paper's own Table 7/8 — b=123.3 is an exact match to the paper's **Blades** row, suggesting a copy/mislabel error in the proposal | Ck=3.37, a=1.9, b=471.4 (Bricks, read directly from the real paper's Tables 7-8) — `solver_and_formulas.md` updated |
| Jul 2026 | DOE initially had 4 factors (missing concentration) | Added φ as 5th factor |
| Jul 2026 | Learning roadmap had mismatched video resources | Corrected with verified appendix |
| Jul 2026 | Claude gave wrong SpaceClaim UI steps | Nuradin figured out correct workflow independently |
| Jul 2026 | Metallic appearance assumed doable in SpaceClaim | Actually requires KeyShot rendering |
