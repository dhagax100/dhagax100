# Solver Settings & Performance Formulas

**Source of truth for this file: `docs/Proposal_Last.pdf`, Chapter 3 (Methodology), Section 3.3 (Governing Equations) and Section 3.3.6 (Performance parameters), verified 2026-08-11.** All equation numbers below reference that document.

## ANSYS Fluent Solver Configuration

| Setting | Value |
|---------|-------|
| Solver | Pressure-based, steady-state |
| Discretization | Finite volume method |
| Pressure-velocity coupling | SIMPLE |
| Pressure discretization | PRESTO |
| Momentum | Second-order upwind |
| Energy | Second-order upwind |
| Turbulence | Second-order upwind |
| Radiation model | Discrete ordinates (DO) |
| Turbulence model | **Realizable k-ε (CONFIRMED — Proposal Section 3.3.4, matches Mohammed et al. 2022 reference methodology)** |
| Wall treatment | Enhanced wall treatment |
| Continuity residual | 10⁻⁶ |
| All other residuals | 10⁻⁸ |

## Governing Equations (Proposal Eq. 3.3–3.10)

### Continuity (steady, incompressible):
```
∂(ρuᵢ)/∂xᵢ = 0
```

### Momentum (Reynolds-averaged):
```
∂/∂xⱼ(ρuᵢuⱼ) = -∂P/∂xᵢ + ∂/∂xⱼ[μ(∂uᵢ/∂xⱼ + ∂uⱼ/∂xᵢ) - ρu'ᵢu'ⱼ]
```
Reynolds stress closed via Boussinesq approximation:
```
-ρu'ᵢu'ⱼ = μₜ(∂uᵢ/∂xⱼ + ∂uⱼ/∂xᵢ) - (2/3)(ρk + μₜ∂uₖ/∂xₖ)δᵢⱼ
```

### Energy:
```
∂/∂xⱼ(ρuⱼCpT) = ∂/∂xⱼ[kf·∂T/∂xⱼ + (μₜ/σₕ,ₜ)·∂(CpT)/∂xⱼ] + Φ
```
Φ = viscous dissipation term.

### Turbulence — Realizable k-ε transport equations:
```
∂/∂xⱼ(ρkuⱼ) = ∂/∂xⱼ[(μ + μₜ/σₖ)∂k/∂xⱼ] + Gₖ - ρε

∂/∂xⱼ(ρεuⱼ) = ∂/∂xⱼ[(μ + μₜ/σε)∂ε/∂xⱼ] + ρC₁Sε - ρC₂ε²/(k + √(νε))

μₜ = ρCμ(k²/ε)
```

### Radiation — Discrete Ordinates (DO):
```
dI(r,s)/ds + (a+σₛ)I(r,s) = an²(σT⁴/π) + (σₛ/4π)∫[4π] I(r,s')Φ(s,s')dΩ'
```

Additional convergence check: outlet temperature, average absorber temperature, pressure drop, Nu, and η_th must all reach stable values (not just residuals).

## Boundary Conditions

| Boundary | Type |
|----------|------|
| Inlet | Velocity inlet (from Re) |
| Outlet | Pressure outlet |
| Absorber wall (lower) | Non-uniform heat flux from optical model |
| Absorber wall (upper) | Uniform heat flux |
| All walls | No-slip |
| DNI | 1000 W/m² |
| Ambient | 300 K |
| Tin range | 400–650 K |
| Re range | 5,000–100,000 |

## Validation Correlations

### Gnielinski (Nusselt number):
```
Nu = (f/8)(Re - 1000)Pr / [1 + 12.7(f/8)^(1/2)(Pr^(2/3) - 1)]
```

### Petukhov (friction factor):
```
f = (0.79 ln(Re) - 1.64)^(-2)
```

Expected agreement: Nu ≤ ~9% max deviation, f ≤ ~5% max deviation.

## Performance Parameter Definitions (Proposal Eq. 3.11–3.19)

```
Re = ρ·u_m·d_ri / μ
h  = q'' / (T_ri - T_b)
Nu = h·d_ri / k_f
f  = 2τ_w / (ρ·u_m²)
ΔP = f·(L/d_ri)·(ρ·u_m²/2)
```
- u_m = mean velocity, d_ri = absorber tube inner diameter, T_ri = average inner wall temperature, T_b = bulk fluid temp, τ_w = wall shear stress.

## Performance Metrics

### Useful heat gain and thermal efficiency (Eq 3.16–3.17):
```
Q̇_u = ṁ·Cp·(Tout - Tin)
η_th = (Q̇_u - P_p/η_el) / (A_a × I_b)
```
- P_p = V̇ × ΔP (pumping power)
- η_el = 0.3 (mechanical-to-electrical conversion factor — 1 W pumping ≈ 3.33 W thermal-equivalent penalty)
- A_a = 39.2 m² (APERTURE area, not tube surface area)

### PEC (fluid/nanofluid enhancement, Eq 3.18):
```
PEC₁ = (Nu_hnf/Nu_f) / (f_hnf/f_f)^(1/3)
```

### PEC (geometry/passive enhancement, Eq 3.19):
```
PEC₂ = (Nu_w/Nu_o) / (f_w/f_o)^(1/3)
```
Subscripts: hnf = hybrid nanofluid, f = base fluid, w = receiver with promoter, o = smooth receiver.

### Total entropy generation (Eq 3.20):
```
S_gen_total = S_gen_F + S_gen_H
```
(friction + heat transfer contributions — proposal does not give the field/lumped computation formula explicitly; likely computed via CFD field integration in Fluent. Confirm exact method before Module 7/8 implementation.)

### Bejan number (Eq 3.21):
```
Be = S_gen_H / S_gen_total
```
(Be → 1 means heat transfer dominates irreversibility; Be → 0 means friction dominates)

### Entropy generation ratio (Eq 3.22) — NEW, not previously tracked in this file:
```
Ns = (S_gen_total)_w / (S_gen_total)_o
```
Ratio of the enhanced receiver's total entropy generation to the smooth receiver's, at matching conditions. Ns < 1 means the promoter reduces total irreversibility despite adding friction losses; Ns > 1 means it increases total irreversibility overall.

### Exergetic efficiency (Eq 3.23) — VERIFIED, corrects earlier assumed form:
```
η_ex = ṁ·Cp·[(Tout - Tin) - T_amb·ln(Tout/Tin)]  /  { A_a·I_b·[1 + (1/3)(T_amb/T_s)⁴ - (4/3)(T_amb/T_s)] }
```
- T_amb = 300 K, T_s = apparent sun temperature.
- **Correction: the numerator does NOT subtract pumping power P_p.** (An earlier lesson taught a literature form that included a `- P_p` term — that term is not present in the thesis's actual adopted equation. Exergetic efficiency here is evaluated purely from the fluid's thermal exergy gain against the sun's exergy input.)

### Direct normal irradiance (Eq 3.24):
```
DNI = 1000 W/m²
```

## Hybrid Nanofluid Property Models (Proposal Eq. 3.25–3.30) — VERIFIED, replaces earlier Maxwell/Brinkman teaching

### Base fluid (Syltherm 800), temperature-dependent (Eq 3.25):
```
ψ = a + bT + cT² + dT³ + eT⁴
```
ψ = density, viscosity, thermal conductivity, or specific heat. Coefficients from Dow datasheet [ref 68] — not yet in this repo, still needed.

### Hybrid nanofluid density (Eq 3.26):
```
ρ_hnf = (1 - φp)·ρ_bf + φp1·ρp1 + φp2·ρp2
```
φp = φp1 + φp2 (total particle volume fraction); φp1, φp2 = volume fractions of the two nanoparticle types.

### Hybrid nanofluid specific heat (Eq 3.27):
```
(Cp)_hnf = [(1-φp)·ρ_bf·Cp,bf + φp1·ρp1·Cp1 + φp2·ρp2·Cp2] / ρ_hnf
```

### Hybrid nanofluid thermal conductivity (Eq 3.29 — NOT the Maxwell model):
```
k_hnf = k_bf · (1 + Ck·φ)
```
Ck = thermal-conductivity shape coefficient. **For brick-shaped nanoparticles (this study's shape): Ck = 6.0** (Timofeeva et al., cited in proposal).

### Hybrid nanofluid viscosity (Eq 3.30 — NOT the Brinkman model):
```
μ_hnf = μ_bf · [(1 + a·φp1 + b·φp1²) + (1 + a·φp2 + b·φp2²)]
```
a, b = morphology-dependent coefficients. **For brick-shaped nanoparticles: a = 14.9, b = 123.3** (Timofeeva et al.).

### Reference nanoparticle/base-fluid properties (Proposal Table 14):
| Material | ρ (kg/m³) | k (W/m·K) | μ (Pa·s) | Cp (J/kg·K) |
|---|---|---|---|---|
| Syltherm 800 | 747.2 | 0.0961 | 0.00084 | 1962 |
| Fe₂O₃ | 5180 | 6.9 | — | 670 |
| Graphene oxide (GO) | 1800 | 5000 | — | 717 |

(Al₂O₃, MWCNT, Ag, MgO property data not yet in the proposal — still needed for the other two hybrid pairs before their UDFs can be written.)

## Open Items / Unresolved
- ~~Mesh type conflict~~ **RESOLVED (Aug 2026):** unstructured tetrahedral mesh with inflation layers, per proposal Section 3.6 — used consistently for the smooth-tube baseline and every enhanced geometry so Ns/PEC comparisons aren't contaminated by a meshing-method difference. Supersedes CLAUDE.md's earlier "3 hex mesh levels" plan.
- Proposal's own grid-independence (Table 13) and validation figures (Figs 6–9) contain specific numbers that do not reconcile with the smooth-tube GCI numbers already in `mesh-validation/Mesh_and_Validation_Workbook.xlsx`. Not yet resolved whether the proposal's numbers are completed results or template values adapted from Mohammed et al. (2022).
