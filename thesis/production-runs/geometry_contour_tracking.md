# Geometry-Stage Contour Tracking (Temperature, Velocity, TKE)

## Purpose

This is the equivalent of the mirror thesis's Figure 4-6 (cross-sectional temperature,
velocity, and turbulent kinetic energy contours), adapted to our own geometry and
study design. These contours exist to show the physical mechanism behind the PEC
rankings already established in sections 4.2.1-4.2.3 (why one configuration mixes
or heats better than another), not to repeat the PEC numbers themselves.

## Fixed conditions (same for all 15 images)

- Re = 5,000
- Twist pitch Pt = 200 mm (fixed across every configuration shown here)
- Cross-sectional plane at x = 1.5 m along the 2.0 m tube (downstream region,
  swirl pattern fully developed, not still forming as it would be near the inlet)
- Plane-only data: Auto Range ON, Global Range OFF, only the single x=1.5m plane
  surface selected in Fluent's Contours dialog Surfaces list (not all 24 surfaces)
  so Min/Max reflect this cross-section only, not the whole domain

## The 5 configurations

Matches the actual stage design, not a full factorial: Stage 2 (promoter size) swept
dpo/dti at a fixed baseline wall thickness; Stage 3 (wall thickness) then swept
tp/dpo only on the Stage 2 winner (dpo/dti = 0.25). The 0.20 and 0.15 promoter-size
losers were never re-run at tp/dpo = 0.10 or 0.15, so this figure set has fewer
panels than the mirror's full BR x angle matrix (Figure 4-6, 15 configs + smooth
tube). That is an honest reflection of a sequential single-factor-at-a-time
screening design, not a missing result, and will be stated plainly in the
discussion text.

| # | dpo/dti | tp/dpo | Stage |
|---|---------|--------|-------|
| 1 | 0.15 | 0.05 | Promoter size sweep |
| 2 | 0.20 | 0.05 | Promoter size sweep |
| 3 | 0.25 | 0.05 | Promoter size sweep (winner) |
| 4 | 0.25 | 0.10 | Wall thickness sweep (winner) |
| 5 | 0.25 | 0.15 | Wall thickness sweep |

## Why solid regions are handled differently per field

- **Temperature**: includes the full cross-section (tube solid wall + annulus
  fluid + promoter solid wall + core fluid). This is a conjugate heat transfer
  problem, so the solid's temperature is physically meaningful (shows the
  wall-to-fluid gradient, and whether the promoter wall itself runs hot).
- **Velocity and TKE**: fluid zones only (annulus + core). Neither quantity is
  solved inside a solid region in Fluent, so the solid promoter/tube wall is
  excluded from these two contours, not just visually blanked.

## Why one shared color-scale range per field (not per image)

Matches the mirror's own Figure 4-6 convention (one legend shared across its whole
BR x angle grid, per field) and standard CFD comparison practice (fixed, shared
contour range across side-by-side comparisons; see conversation sources: ANSYS
CFD-Post Contour: Geometry Tab documentation, and CFD-Online practitioner
threads on manual contour range selection). A shared range per field means the 5
panels for that field are a fair, apples-to-apples visual comparison; different
independently auto-scaled ranges per image would make two physically different
fields look artificially similar or different based on legend choice alone.

## Real plane-only Min/Max per configuration (from Fluent, Auto Range + single
## plane selected) -- to be filled in from Nuradin's actual readings

### Temperature (K)

| # | Config | Min (K) | Max (K) |
|---|--------|---------|---------|
| 1 | dpo/dti=0.15, tp/dpo=0.05 | 513.94 | 903.77 |
| 2 | dpo/dti=0.20, tp/dpo=0.05 | 514.46 | 890.16 |
| 3 | dpo/dti=0.25, tp/dpo=0.05 | 515.83 | 880.18 |
| 4 | dpo/dti=0.25, tp/dpo=0.10 | 516.03 | 884.79 |
| 5 | dpo/dti=0.25, tp/dpo=0.15 | 516.22 | 880.82 |

**Shared temperature range to use in all 5 images: Min = 513.94 K, Max = 903.77 K**
(lowest of the 5 real minimums is config 1; highest of the 5 real maximums is
also config 1 — both come from the dpo/dti=0.15, tp/dpo=0.05 case, the smallest
promoter, which makes physical sense: the smallest promoter blocks the annulus
least, so it departs least from the smooth-tube baseline and should show the
widest spread between hot wall and cool bulk fluid).

### Velocity (m/s)

| # | Config | Min (m/s) | Max (m/s) |
|---|--------|-----------|-----------|
| 1 | dpo/dti=0.15, tp/dpo=0.05 | 0.00 | 0.11 |
| 2 | dpo/dti=0.20, tp/dpo=0.05 | 0.00 | 0.11 |
| 3 | dpo/dti=0.25, tp/dpo=0.05 | 0.00 | 0.11 |
| 4 | dpo/dti=0.25, tp/dpo=0.10 | 0.00 | 0.12 |
| 5 | dpo/dti=0.25, tp/dpo=0.15 | 0.00 | 0.12 |

**Shared velocity range to use in all 5 images: Min = 0.00 m/s, Max = 0.12 m/s**
(minimum is the no-slip wall value, identical in every case as expected; the
maximum comes from configs 4 and 5, the two thickest-wall cases at the winning
promoter size — a thinner hollow core forces the core-flow fraction through a
smaller area, raising its peak velocity, consistent with the TKE pattern above).

### Turbulent Kinetic Energy, TKE (m^2/s^2)

| # | Config | Min (m^2/s^2) | Max (m^2/s^2) |
|---|--------|---------------|---------------|
| 1 | dpo/dti=0.15, tp/dpo=0.05 | 1.49e-09 | 1.54e-04 |
| 2 | dpo/dti=0.20, tp/dpo=0.05 | 1.69e-09 | 1.50e-04 |
| 3 | dpo/dti=0.25, tp/dpo=0.05 | 1.60e-09 | 1.51e-04 |
| 4 | dpo/dti=0.25, tp/dpo=0.10 | 1.13e-09 | 1.55e-04 |
| 5 | dpo/dti=0.25, tp/dpo=0.15 | 1.10e-09 | 1.76e-04 |

**Shared TKE range to use in all 5 images: Min = 1.10e-09 m^2/s^2, Max = 1.76e-04
m^2/s^2** (both from config 5, dpo/dti=0.25 tp/dpo=0.15 — the thickest promoter
wall at the winning promoter size shows the most intense turbulence peak, which
fits the physical pattern already discussed in section 4.2.3: a thicker wall
shrinks the hollow core, forcing more flow through the annulus and sharpening
the corner-induced vortices there).

## Status

Waiting on Nuradin's real plane-only Min/Max readings for all 15 images (5
configs x 3 fields) before the shared ranges can be computed and the final
exported images produced for insertion into the thesis.
