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
| Coarse | 2,718,404 | 1,270,568 | **0.009** ⚠️ below own target (>0.01) | 0.883 (in ANSYS's "bad" 0.80–0.95 band, but under the 0.95 ceiling) |
| Medium | 4,888,550 | 2,212,552 | **0.0129** ✓ now clears the >0.01 target | 0.848 (still in the "bad" band, but improved vs. Coarse) |
| Fine | — | — | — | — |

Both quality metrics improved from Coarse to Medium, as expected — refining a mesh tends to fix its worst-shaped cells along with improving general accuracy. Medium's element count (4,888,550) lands inside the ~4.5–5.5M expected range.

Note: actual refinement ratio between Coarse and Medium, from cell counts, is r32 = (4,888,550/2,718,404)^(1/3) ≈ 1.216 — somewhat below the ~1.30 implied by the linear element-size ratio (5.0/3.85). Expected: cell count doesn't scale as a perfect cube of the global size setting because inflation-layer cell count stays fixed regardless of global size. Watch this against r21 (Fine vs. Medium) once Fine is meshed — the GCI sheet flags it automatically if the two ratios drift more than 5% apart.

**Watch item:** confirm where the worst-orthogonal-quality cell sits (Mesh → Quality display) — if it's at a promoter corner, expect it to persist or shift across Medium/Fine rather than disappear on its own. Track both metrics at every level, not just once.

If Medium comes in below 4M or above 7M, check that Global Size is really the only setting that changed vs. Coarse.

## Fluent — nothing to change between levels

After duplicating from Coarse, open Fluent from the new system and do **not** touch: turbulence model (Realizable k-ε, Enhanced Wall Treatment), all BCs (velocity inlet, outlet, heat flux, walls), Solution Methods (SIMPLE, PRESTO!, second-order upwind everywhere), residual monitors, iteration count (1000, same as Coarse for GCI consistency). Just **Run Calculation → Calculate**.

## Results log

| Mesh level | Cell Count | Nu | f | Notes |
|---|---|---|---|---|
| Coarse | 2,718,404 | 921.49 | 0.00628 | Mass balance 0.0014%, y+ avg 0.29 / max 2.26, Re ≈ 99,600 |
| Medium | 4,888,550 | 927.35 (+0.64%) | 0.00616 (−1.96%) | Mass balance 0.0012%, y+ avg 0.29 / max 2.21, ΔP 3551.5 Pa (−1.46% vs Coarse) |
| Fine | — | — | — | pending |

Coarse → Medium change is small on both Nu and f — a good early sign for eventual GCI < 1%, but not a verdict on its own. GCI can't compute (needs all 3 levels) until Fine is in — currently shows "enter all 3 mesh levels first."

See `PTSC_GCI_Workbook.xlsx` for full raw extraction and the live GCI calculation.
