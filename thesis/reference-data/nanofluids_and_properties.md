# Hybrid Nanofluids and Property Models

## Base Fluid: Syltherm 800

Temperature-dependent properties using polynomial form:
```
ψ = a + bT + cT² + dT³ + eT⁴
```
Where ψ = density, viscosity, thermal conductivity, or specific heat. Coefficients from Dow Chemical datasheet (Ref [68] in proposal).

Operating range: 400–650 K.

## Three Hybrid Nanofluids (all with Syltherm 800)

### 1. Fe₂O₃-GO/Syltherm 800
- **Why:** Validated by Mohammed et al. (2022) — the advisor's own study — in the same PTSC configuration with wavy promoters. Produced 150.4% Nu improvement at 2 vol%. Direct continuity with the baseline methodology.
- **Type:** Metal oxide + carbon sheet

### 2. Al₂O₃-MWCNT/Syltherm 800
- **Why:** Well-characterised ceramic oxide + multi-walled carbon nanotubes. A dedicated PTSC study found 70.54% average thermal efficiency with this combination. MWCNTs provide dramatic heat capacity enhancement; Al₂O₃ ensures good suspension stability.
- **Type:** Ceramic oxide + carbon nanotube

### 3. Ag-MgO/Syltherm 800
- **Why:** Noble metal + metal oxide. Ag has the highest thermal conductivity of any metal (~429 W/m·K). MgO provides thermal stability at high operating temperatures (400–650 K). Multiple PTSC studies identify Ag-MgO as one of the most efficient hybrid combinations.
- **Type:** Noble metal + metal oxide

## Common Nanoparticle Parameters
- Shape: brick
- Diameter: 50 nm
- Volume concentration levels: 0.5%, 1.0%, 2.0%

## Nanofluid Modeling Assumptions
- Single-phase homogeneous model (no slip between particles and fluid)
- Uniform nanoparticle dispersion
- Stable suspension throughout simulation
- Nanofluid properties calculated from established mixing rules (see proposal Section 3.7)

## Why 0.5% minimum (not 0%)
At φ = 0% the fluid is just Syltherm 800. The nanofluid-type factor becomes meaningless for that run. Starting at 0.5% ensures every run tests a real nanofluid effect.
