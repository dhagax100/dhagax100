# PTSC Receiver CFD Thesis — Claude Code Instructions

## Who I Am

Nuradin, mechanical engineering master's student. **No prior CFD background.** I learn by doing, with plain-English explanations and physical intuition. Do not assume I know terms — define them on first use. Do not guess ANSYS/SpaceClaim UI steps you cannot verify — flag uncertainty instead.

## The Project

CFD-based thesis: heat transfer enhancement in a parabolic trough solar collector (PTSC) receiver tube using a central hollow twisted square promoter (HTSP) combined with hybrid nanofluids. Advisor's published wavy-promoter study (Mohammed et al., 2022) is the direct baseline. Deadline: results by end of September 2026.

## Current State (as of late July 2026)

- **Study design locked:** 5 factors × 3 levels → Taguchi L27 = 27 CFD runs
- **Workflow plan sent to advisor**, who gave green light and expects weekly updates
- **Validation phase in progress:** reproducing smooth-tube results against Dudley et al. (SAND94-1884) LS-2 dataset
- **Mesh independence study planned:** unstructured tetrahedral mesh with inflation layers (RESOLVED Aug 2026 — supersedes earlier "3 hex mesh levels" plan; see decision_log.md), y+ ≈ 1 at highest Re, Nu and f as monitors, <1% threshold
- **Geometry work in SpaceClaim:** partially complete, annotation done independently after Claude's UI instructions proved wrong
- **Learning roadmap:** 6-phase, 11-week plan exists as a Word doc

## Communication Rules

- Lead with the answer. No preamble or question restating.
- Short sentences, plain words. Lists when content is list-shaped.
- Expand to full detail only when the topic is complex or I ask — never compress technical/thesis work where detail matters for correctness.
- Explain every CFD/physics concept from first principles using analogies.
- If you don't know exact ANSYS button clicks, say so. Do not fabricate UI paths.
- When I correct you, acknowledge and adjust — do not defend the prior response.
- Always verify links/resources before sharing. Dead or mismatched links waste my time.

## Study Design (Locked)

### Geometry (LS-2 Collector)
- Absorber tube: length 4000 mm, ID (dti) 66 mm, OD 70 mm, wall 2 mm
- Aperture area: 39.2 m² (used in thermal efficiency denominator — NOT tube surface area)
- Promoter: central hollow twisted square, stainless steel, full tube length

### Taguchi L27 Factors

| # | Factor | Level 1 | Level 2 | Level 3 |
|---|--------|---------|---------|---------|
| 1 | Pt/dti (twist pitch ratio) | 3.03 (200 mm) | 4.55 (300 mm) | 6.06 (400 mm) |
| 2 | dpo/dti (promoter size ratio) | 0.23 (15 mm) | 0.38 (25 mm) | 0.53 (35 mm) |
| 3 | tp/dpo (wall thickness ratio) | 0.04 (1 mm) | 0.08 (2 mm) | 0.12 (3 mm) |
| 4 | Hybrid nanofluid type | Fe₂O₃-GO | Al₂O₃-MWCNT | Ag-MgO |
| 5 | Nanoparticle vol. concentration | 0.5% | 1.0% | 2.0% |

All nanofluids use Syltherm 800 as base fluid. Brick-shaped nanoparticles, 50 nm diameter.

### Operating Conditions
- Re: 5,000–100,000 (turbulent)
- Tin: 400–650 K
- DNI: 1000 W/m²
- Ambient: 300 K

### Solver Settings
- ANSYS Fluent, pressure-based steady-state
- SIMPLE pressure-velocity coupling
- PRESTO pressure, second-order upwind for momentum/energy/turbulence
- Enhanced wall treatment, y+ ≈ 1
- Discrete ordinates radiation model
- Convergence: 10⁻⁶ continuity, 10⁻⁸ others

### Performance Metrics
Nusselt number, friction factor, pressure drop, thermal efficiency, exergetic efficiency, entropy generation, Bejan number, PEC (both fluid and geometry versions).

## Validation Plan
1. Smooth-tube Nu and f vs. Gnielinski and Petukhov correlations (Re 5k–100k, Tb = 500 K)
2. LS-2 experimental: Dudley et al. Table D-1, 9 cermet/vacuum cases — compare ΔT and η_th
3. Receiver-scale thermal trend vs. Mwesigye et al.
4. Enhanced-geometry trend vs. Sheikholeslami et al.

## Known Pitfalls (Learn from Past Mistakes)
- **Efficiency formula:** denominator = mirror aperture area (39.2 m²), NOT tube surface area
- **ANSYS UI steps:** Claude has previously given incorrect SpaceClaim instructions (plane creation, section views, appearances). Always caveat uncertain steps.
- **Metallic rendering:** requires KeyShot, not SpaceClaim color assignment
- **DOE completeness:** nanoparticle concentration was initially omitted as a factor — always cross-check factor lists against the 5-factor table above
- **Video/link accuracy:** previous roadmap had mismatched video titles and broken links. Verify before sharing.
- **Nanofluid at 0%:** lowest concentration is 0.5%, not 0%, because 0% makes the nanofluid-type factor meaningless

## Tools & References
- **Simulation:** ANSYS Fluent (solver), SpaceClaim (geometry), KeyShot (rendering)
- **Mesh tools:** CFD-Online y+ calculator, Volupe GCI calculator
- **Key references:** Celik et al. (2008) ASME GCI paper; Dudley et al. SAND94-1884; Mohammed et al. (2022) wavy promoter baseline
- **Tutorials:** Curiosity Fluids grid convergence walkthrough, NASA spatial convergence tutorial

## File Organization
- `docs/` — thesis proposal PDF, workflow plan, learning roadmap
- `reference-data/` — Dudley Table D-1 extracted data, Syltherm 800 property polynomials
- `taguchi/` — L27 run matrix with derived dimensions
- `notes/` — session logs, advisor feedback, decisions made
