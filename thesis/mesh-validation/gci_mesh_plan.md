# GCI Mesh Plan — 3-Level Mesh Independence Study

Locked mesh-generation plan for the smooth-tube-with-promoter GCI study (dpo = 25 mm, tp = 2 mm — see `decision_log.md`). Source: Nuradin's mesh input reference, 2026-08-17.

## What changes vs. what stays fixed

| Item | Coarse | Medium | Fine |
|---|---|---|---|
| Global Element Size | 5.0 mm | 3.85 mm | 2.96 mm |
| Patch Conforming Tet method | same | same | same |
| Inflation — First Layer | same | same | same |
| Inflation — Growth Rate | same | same | same |
| Inflation — Max Layers | same | same | same |
| All Named Selections | same | same | same |

**Rule: only the global element size number changes. Nothing else.**

Refinement ratio check: 5.0/3.85 = 1.299, 3.85/2.96 = 1.301 — effectively constant (~1.3× linear scaling per level), which is exactly the assumption the GCI Calculation sheet in `PTSC_GCI_Workbook.xlsx` requires (r21 ≈ r32) for its non-iterative apparent-order formula to hold.

## Workbench workflow (Medium and Fine)

1. Right-click the entire Coarse system in Workbench → **Duplicate** (independent copy: geometry + mesh + Fluent all preserved).
2. Open the duplicated Mesh cell.
3. Details of "Mesh" → Sizing → Element Size → change to 3.85 mm (then 2.96 mm for Fine).
4. Click **Generate**.
5. Record quality metrics → close Mesh.
6. Open Fluent from the same duplicated system — BCs, models, solver already carried over. Click **Run Calculation → Calculate**.
7. Repeat for Fine.

## Meshing panel — exact input values

**Global Mesh Settings (Details of "Mesh")**

| Parameter | Value |
|---|---|
| Physics Preference | CFD |
| Solver Preference | Fluent |
| Element Size | 3.85 mm (Medium) / 2.96 mm (Fine) |
| Use Adaptive Sizing | No |
| Capture Curvature | Yes |
| Curvature Normal Angle | 18° |
| Capture Proximity | No |
| Smoothing | High |
| Transition | Slow |

**Method — all 5 bodies at once (Insert → Method)**

| Parameter | Value |
|---|---|
| Method | Tetrahedrons |
| Algorithm | Patch Conforming |
| Element Midside Nodes | Use Global Setting |

**Inflation Object 1 — Annulus Fluid**

| Parameter | Value |
|---|---|
| Scope → Geometry | annulus_fluid body |
| Boundary → Geometry | all wall faces bounding the annulus (tube inner wall, promoter outer wall) |
| Inflation Option | First Layer Thickness |
| First Layer Height | 0.006959 mm |
| Maximum Layers | 15 |
| Growth Rate | 1.2 |
| Inflation Algorithm | Post |

**Inflation Object 2 — Core Fluid**

| Parameter | Value |
|---|---|
| Scope → Geometry | core_fluid body |
| Boundary → Geometry | all wall faces bounding the core (promoter inner wall) |
| Inflation Option | First Layer Thickness |
| First Layer Height | 0.006959 mm |
| Maximum Layers | 15 |
| Growth Rate | 1.2 |
| Inflation Algorithm | Post |

## Quality metrics recorded after each mesh (Mesh → Statistics / Mesh Metric)

| Metric | Where | Target |
|---|---|---|
| Number of Elements | Statistics → Elements | record as-is |
| Number of Nodes | Statistics → Nodes | record as-is |
| Min Orthogonal Quality | Mesh Metrics → Orthogonal Quality → Min | > 0.01 (flag if lower) |
| Max Skewness | Mesh Metrics → Skewness → Max | < 0.95 |
| Average Skewness | Mesh Metrics → Skewness → Average | < 0.33 ideally |

## Expected element count progression

| Level | Size | Expected elements | Actual |
|---|---|---|---|
| Coarse | 5.0 mm | ~2.7 M | **2,718,404** (logged) |
| Medium | 3.85 mm | ~4.5–5.5 M | pending |
| Fine | 2.96 mm | ~7.5–9.5 M | pending |

## Mesh quality log

| Level | Elements | Nodes | Min Orthogonal Quality | Max Skewness |
|---|---|---|---|---|
| Mesh 1 (Coarsest) | 2,718,404 | 1,270,568 | **0.009** ⚠️ below own target (>0.01) | 0.883 (in ANSYS's "bad" 0.80–0.95 band, but under the 0.95 ceiling) |
| Mesh 2 | 4,888,550 | 2,212,552 | **0.0129** ✓ clears the >0.01 target | 0.848 (still in the "bad" band, but improved vs. Mesh 1) |
| Mesh 3 | 8,658,088 | 3,761,583 | **0.01498** ✓ continues improving | 0.850 (essentially flat vs. Mesh 2 — skewness has plateaued) |
| Mesh 4 (Finest, 2.28mm) | 15,675,184 | 6,571,364 | **0.01312** — small step back from Mesh 3, still clears >0.01 | 0.8499 (flat, matches plateau) |

Both quality metrics improved from Coarse to Medium, as expected — refining a mesh tends to fix its worst-shaped cells along with improving general accuracy. Medium's element count (4,888,550) and Fine's (8,658,088) both land inside their expected ranges.

**Refinement ratio check — passes.** r32 (Medium/Coarse) ≈ 1.216, r21 (Fine/Medium) ≈ 1.210 — within 0.5% of each other, well inside the 5% tolerance the GCI sheet checks for. The constant-refinement-ratio assumption behind the GCI formula holds across all three levels.

**Watch item:** confirm where the worst-orthogonal-quality cell sits (Mesh → Quality display) — if it's at a promoter corner, expect it to persist or shift across Medium/Fine rather than disappear on its own. Track both metrics at every level, not just once.

If Medium comes in below 4M or above 7M, check that Global Size is really the only setting that changed vs. Coarse.

## Fluent — nothing to change between levels

After duplicating from Coarse, open Fluent from the new system and do **not** touch: turbulence model (Realizable k-ε, Enhanced Wall Treatment), all BCs (velocity inlet, outlet, heat flux, walls), Solution Methods (SIMPLE, PRESTO!, second-order upwind everywhere), residual monitors, iteration count (1000, same as Coarse for GCI consistency). Just **Run Calculation → Calculate**.

## Results log

| Mesh level | Cell Count | Nu | f | Notes |
|---|---|---|---|---|
| Coarse | 2,718,404 | 921.49 | 0.00628 | Mass balance 0.0014%, y+ avg 0.29 / max 2.26, Re ≈ 99,600 |
| Medium | 4,888,550 | 927.35 (+0.64%) | 0.00616 (−1.96%) | Mass balance 0.0012%, y+ avg 0.29 / max 2.21, ΔP 3551.5 Pa (−1.46% vs Coarse) |
| Fine | 8,658,088 | 909.12 | 0.00595 | Mass balance 0.0003%, y+ avg 0.29 / max 2.12, ΔP 3443.4 Pa |

## FINAL VERDICT (2026-08-18): Mesh independence achieved — Mesh 3 adopted

| Monitor | Mesh 3 value | Mesh 4 value | % diff | Threshold | Verdict |
|---|---|---|---|---|---|
| Nu | 909.12 | 898.40 | 1.19% | 2% | PASS |
| ΔP (Pa) | 3443.41 | 3480.93 | 1.08% | 2% | PASS |

Mesh 4 results (15,675,184 elements): mass balance error 0.00034%, y+ avg 0.286, y+ max 1.64, T_in=300K, T_out=300.109K, T_wall=300.819K, p_in=3480.93 Pa, p_out=0 Pa, τ_w=6.424 Pa, ṁ_in=4.11646 kg/s, q″=1000 W/m², Q̇=879.53 W.

**Both Nu and ΔP clear the 2% bar between Mesh 3 and Mesh 4 → mesh independence declared.** Per Mohammed et al. (2022)'s own practice (adopt the first level that clears the bar, not the finest tested), **Mesh 3 (2.96 mm element size, 8,658,088 elements) is the adopted mesh for all 27 production runs** — not Mesh 4. Mesh 4 served only to confirm Mesh 3 was already sufficient; using it for all 27 runs would roughly double compute cost for no accuracy benefit.

**Known deviation, documented 2026-08-18:** the mesh-independence study (Mesh 1-4) used **aluminum** for the tube wall solid material; production runs (starting with Run 1) correctly use **steel**. This does not invalidate the mesh-independence conclusion — all 4 mesh levels used the same material consistently, so the relative Mesh3-vs-Mesh4 comparison (the actual mesh-sensitivity question) is unaffected. The dominant resolution challenge in this geometry is the fluid-side turbulent boundary layer (what the inflation layers/y+ targets are built around), not conduction through a thin 2mm solid wall, so this is a low-risk deviation. The absolute Nu/ΔP/T_wall values reported in this GCI study reflect aluminum-tube physics and are not meant to be taken as final production results — only as the mesh-sensitivity check they were designed for.

**This closes the mesh-independence phase.** The 27-run Taguchi production study (deferred since the start of this engagement pending this result) is now unblocked, subject to the other two open items already tracked in `decision_log.md` (Re/Tin fixed at 10,000/500K — done; Al₂O₃-MWCNT and Ag-MgO property correlations — still open, blocks 18 of 27 runs, not the 9 Fe₂O₃-GO runs).

## Methodology decision, 2026-08-17: switched from Celik GCI to Mohammed et al. (2022)'s method

After checking the advisor's real published paper (Section 2.6, Table 4 — not just the thesis proposal draft), decided to match his actual accepted practice rather than the stricter Celik et al. (2008) Richardson-extrapolation approach originally built:

- **Monitors: Nu and ΔP** (not f — swapped to match the paper's own table)
- **Method: simple consecutive-mesh percent difference** between the two finest levels, no Richardson extrapolation, no apparent order, no monotonicity requirement
- **Threshold: 2%** (verified from the real paper's Table 4, not the proposal draft's stated 1%, which doesn't reconcile with its own numbers)
- **4 mesh levels**, matching the paper's own practice — proceeding to build Mesh 4

`PTSC_GCI_Workbook.xlsx` renamed its check sheet to **"Mesh Independence Check"**; old Celik/GCI sheet retired.

### Current standing (Mesh 1–3, before Mesh 4)

| Comparison | Nu % diff | ΔP % diff |
|---|---|---|
| Mesh 1 → Mesh 2 | 0.63% | 1.49% |
| Mesh 2 → Mesh 3 | 2.01% | 3.14% |

Neither of these is the decision point — only **Mesh 3 vs. Mesh 4** (the two finest, once Mesh 4 exists) determines the verdict, matching the paper's own practice of comparing only the latest pair.

## Baseline (Smooth Tube) Mesh Independence Study — started 2026-08-18

Same methodology as the enhanced geometry: same 4 element sizes (5.0/3.85/2.96/2.28mm), same tet mesh type (kept for consistency with the enhanced geometry — see decision_log.md), same inflation settings, Nu + ΔP monitors, simple consecutive-mesh % method, 2% threshold. Geometry: plain circular tube, no promoter, 2m length (matching the production length decision), dti=66mm/dto=70mm/wall=2mm.

**Corrected 2026-08-19: BCs must match the enhanced-geometry mesh test's convention, not the production Baseline run's.** The enhanced-geometry mesh study was run at the *most demanding* condition in the operating range — Re≈100,000 (highest Re, thinnest boundary layer, toughest y+ target), Tin=300K, uniform q″=1000 W/m² — not the production condition (Re=10,000, Tin=500K, real MCRT flux profile). For the two mesh studies to be comparable, the baseline mesh test must use the same convention:

| Quantity | Value | Basis |
|---|---|---|
| Re (mesh test) | 100,000 | Highest Re in range — matches enhanced-geometry mesh test |
| u_m | **1.70 m/s** | Re·μ/(ρ·d_ri) = 100,000×0.00084/(747.2×0.066), same Syltherm 800 constants as enhanced test |
| Tin (mesh test) | 300K | Matches enhanced-geometry mesh test |
| Heat flux (mesh test) | uniform 1000 W/m² | Matches enhanced-geometry mesh test (not the real UDF) |
| d_ri | 0.066 m | Smooth tube ID |

**This supersedes the earlier plan of this mesh test "doubling as" the production Baseline run.** It cannot — the BCs are different on purpose. The actual production Baseline run (Re=10,000, Tin=500K, real MCRT UDF, steel tube) will be a separate Fluent run, done after this mesh study concludes, using whichever mesh level gets adopted here.

Mesh generation itself (element count, skewness, orthogonal quality) does not depend on BCs, so Mesh 1's already-built geometry/mesh data below remains valid — only the not-yet-run Fluent step needs the corrected u_m=1.70 m/s / Tin=300K / q″=1000 W/m² inputs above.

**Note:** two earlier Mesh 1 attempts are superseded by the final run below — (1) 724,846 elements, built before the fluid body's topology issue was fixed (Fill produced a degenerate surface body; rebuilt via direct extrude + Form New Part) and before inflation was properly resolvable; (2) 1,009,884 elements, an intermediate regeneration pass. Also note: the first Fluent run on this mesh used the wrong conditions (Re=10,000/Tin=500K production conditions, and briefly a broken `inner_wall` thermal BC set to Heat Flux=0 instead of Coupled, which blocked all heat transfer into the fluid) — both corrected before the data below was recorded. See `Baseline_Smooth_Mesh_Independence_Workbook.xlsx` for the full record, including that now-separately-saved production-condition run.

| Level | Elements | Nodes | Max Skewness | Min Orthogonal Quality |
|---|---|---|---|---|
| Mesh 1 (Coarsest, 5.0mm) | 1,023,406 | 385,377 | 0.84354 | 0.15646 |

**Mesh 1 Fluent results (Re≈99,800, Tin=300K, uniform q″=1000 W/m²):** mass balance error 0.0000012%, y+ avg 0.268, y+ max 2.128, T_in=300K, T_out=300.05324K, T_wall=300.86659K, p_in=670.905 Pa, τ_w=5.9079 Pa, ṁ_in=4.32875 kg/s, Q̇=452.17 W. Computed: Nu=817.63, f=0.005515 — both lower than the enhanced-geometry Coarse level (Nu=921.49, f=0.00628), consistent with the promoter's expected enhancement effect. Full formulas and cross-checks in the workbook.

| Level | Elements | Nodes | Max Skewness | Min Orthogonal Quality |
|---|---|---|---|---|
| Mesh 2 (3.85mm) | 1,762,070 | 650,727 | 0.84496 | 0.15504 |

**Mesh 2 Fluent results (same conditions):** mass balance error 0.0000046%, y+ avg 0.270, y+ max 2.177, T_in=300K, T_out=300.05315K, T_wall=300.86581K, p_in=640.891 Pa, τ_w=6.0111 Pa, ṁ_in=4.33594 kg/s, Q̇=452.23 W. Computed: Nu=818.35, f=0.005593.

**Mesh 1 → Mesh 2 comparison (informational — not yet the decision point, that's the two finest levels once Mesh 3/4 exist):** Nu %diff = 0.088% (essentially flat). ΔP %diff = 4.68% (above the 2% threshold — expected, coarser levels normally haven't converged yet).

## Archived: old Celik/GCI verdict (superseded by the above, kept for record — do not act on this)

**Nu is not monotonic:** 921.49 → 927.35 → 909.12 (up, then down). The GCI sheet's built-in check catches this ("OSCILLATORY -- standard GCI NOT valid") and overrides any raw percentage with an explicit INVALID verdict, rather than reporting a spurious PASS.

**f is monotonic in direction (0.00628 → 0.00616 → 0.00595, consistently decreasing) but fails a second check:** the Medium→Fine change (0.000208) is *larger* than the Coarse→Medium change (0.000122) — the error is growing, not shrinking, as the mesh refines. This produces a negative "apparent order," which is not physically meaningful, so the sheet also overrides this to INVALID.

**Why this is likely happening — not a failed study, a real methodological gap:** the total spread across all 3 levels is small (~2% on Nu, ~5.5% on f), likely close to the size of ordinary iteration-to-iteration noise from the swirling flow (see Lesson 10 in the Report Definitions course — residual convergence ≠ physical-monitor convergence; a report read at a single fixed iteration count can land on a different point of a mild oscillation for each mesh level). All three runs used exactly 1000 iterations with no averaging, which is exactly the setup that would let this kind of noise contaminate the comparison.

**Next step before re-running any mesh:** re-extract Nu and f using **Report Definitions → Average Over** (Lesson 10) — average the last ~50–100 iterations instead of reading the single final value — for all three existing mesh levels, and re-populate the workbook. If the convergence pattern becomes monotonic with a sensible positive apparent order after that, this is very likely resolved without needing a 4th mesh level.

See `PTSC_GCI_Workbook.xlsx` for full raw extraction and the live GCI calculation.
