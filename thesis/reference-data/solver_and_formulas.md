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

**Checked 2026-08-18: Fluent's own built-in `syltherm800_oil` database entry does NOT have this pre-loaded.** Its "polynomial" profile option opens a blank template (coefficient 1 = 0, rest empty) — confirmed via screenshot, not an assumption. No shortcut available; the real Dow datasheet is still required. Until then, **using constant properties (ρ=747.2, Cp=1962, k=0.0961, μ=0.00084 — Fluent's own database defaults, matching Table 6 of the real Mohammed et al. 2022 paper) for both the base fluid and all hybrid nanofluid materials.** This is a documented limitation to resolve before final results/defense, not a blocker for starting the 27 runs.

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
Ck = thermal-conductivity shape coefficient.

**CORRECTED 2026-08-18: For brick-shaped nanoparticles, Ck = 3.37** — read directly from Table 7 of the real, published Mohammed et al. (2022) paper. The proposal draft stated Ck = 6.0, which does not match any row of the paper's own Table 7 (Platelets 2.61, Blades 2.74, Cylindrical 3.95, Bricks 3.37) — likely a transcription error in the proposal. The real paper is the authoritative source; use 3.37.

### Hybrid nanofluid viscosity (Eq 3.30 — NOT the Brinkman model):
```
μ_hnf = μ_bf · [(1 + a·φp1 + b·φp1²) + (1 + a·φp2 + b·φp2²)]
```
a, b = morphology-dependent coefficients.

**CORRECTED 2026-08-18: For brick-shaped nanoparticles, a = 1.9, b = 471.4** — read directly from Table 8 of the real paper. The proposal draft stated a = 14.9, b = 123.3, which is actually the **Blades** row (a=14.6, b=123.3), not Bricks — the proposal appears to have copied the wrong row and mislabeled it. Table 8 in full:

| Shape | a | b |
|---|---|---|
| Platelets | 37.1 | 612.6 |
| Blades | 14.6 | 123.3 |
| Cylindrical | 13.5 | 904.4 |
| **Bricks (this study)** | **1.9** | **471.4** |

### φp1/φp2 split assumption
Eqs 3.26/3.27/3.30 use separate volume fractions per particle type (φp1, φp2) but the real paper's text never states how the total φ splits between the two particles in a hybrid pair. Not confirmed anywhere — using the standard literature convention of an even split (φp1 = φp2 = φ_total/2) until the advisor confirms otherwise. Flag this assumption in the thesis methodology chapter.

### Reference nanoparticle/base-fluid properties (CORRECTED 2026-08-18 — read directly from Table 6 of the real Mohammed et al. 2022 paper, replaces the proposal's Table 14 transcription):
| Material | ρ (kg/m³) | k (W/m·K) | μ (Pa·s) | Cp (J/kg·K) |
|---|---|---|---|---|
| Syltherm 800 | 747.2 | 0.0961 | 0.00084 | 1962 |
| Fe₂O₃ | 5180 | 6.9 | — | 670 |
| Graphene oxide (GO) | 1800 | 5000 | — | 717 |
| Silicon carbide (SiC) | 3160 | 117.56 | — | 723 |
| Titanium dioxide (TiO₂) | 4250 | 8.9538 | — | 686.2 |

(Al₂O₃, MWCNT, Ag, MgO property data — not in Mohammed et al. 2022 at all, since that paper doesn't use those nanoparticles. Still needs its own literature search, as already logged in `decision_log.md`.)

### How these get entered into Fluent (per the real paper's own method)
Eqs 3.26/3.27 explicitly say ρ_hnf and (Cp)_hnf are evaluated **"at the reference temperature (Tin)"** — i.e., computed once by hand per run (given that run's fixed Tin and φ), then entered into Fluent's Material panel as **constant numbers**, not a temperature-varying UDF. k_hnf and μ_hnf (Eqs 3.29/3.30) are likewise algebraic in φ and shape constants only — also constants per run. Only the **base fluid** Syltherm 800 itself uses the temperature-dependent polynomial (Eq 3.25) — that's the one property set that should vary with T inside Fluent; the nanofluid mixture properties built from it are fixed values for a given run's Tin and φ.

## Heat flux boundary condition (Eq — Table 3 of the real Mohammed et al. 2022 paper, Section 2.3)

The real paper's exact flux profile, from Monte Carlo Ray Tracing (MCRT), DNI = 1000 W/m²:
```
q(θ) = a₀ + a₁cos(ωθ) + b₁sin(ωθ) + a₂cos(2ωθ) + b₂sin(2ωθ)
```
| θ range | ω | a₀ | a₁ | b₁ | a₂ | b₂ |
|---|---|---|---|---|---|---|
| 0°–41.6° | 0 | 680 | 0 | 0 | 0 | 0 |
| 41.6°–88.6° | 5.88×10⁻² | 3.512×10⁴ | 2.547×10⁴ | −2.425×10⁴ | −1.464×10³ | −6.71×10³ |
| 88.6°–180° | 3.12×10⁻² | 5.616×10⁴ | −1.129×10⁴ | 1.051×10⁴ | −4.039×10³ | −1.582×10³ |

The paper applies this with the near-flat, low first segment (0–41.6°) on the shaded/back half of the tube ("uniform") and the two swinging segments toward 180° on the sun-facing half ("nonuniform"). **The paper's own text is internally inconsistent about whether this lands on the tube's "inner" or "outer" wall** ("the absorber tube outer surface received... solar radiation," two sentences later "the absorber's inner upper half surface is exposed to...") — the first statement is the physically correct one (solar flux must land where the sun is absorbed, the cermet-coated outer wall); the second "inner" is almost certainly a wording slip that survived review. Doesn't matter for us either way — see below.

**Translation to our domain (no glass/vacuum, per the already-locked decision):** apply this exact q(θ) profile directly as a **wall heat flux BC on the absorber tube's OUTER wall** — that's the surface facing the sun in our model, since we don't have a glass envelope or DO-radiation annular gap to route the heat through first. The solid tube wall (2 mm, stainless steel) then conducts it inward by itself, same physics as the paper, just without the intervening glass layer we already decided to exclude.

**One thing I could not verify:** which direction θ=0 points (top of tube vs. bottom, i.e., which half is "shaded" vs. "sun-facing" in the model's coordinate system). The paper's Fig. 1(b) cross-section doesn't label θ, and no text I found states the reference direction. Physically, θ=0 (flat, low 680 W/m²) should be the shaded back of the tube and θ→180° (the swinging, higher terms) should be the sun-facing front — that's the standard convention in PTC circumferential-flux literature (Forristall/Eck-type models) — but I'm inferring this, not reading it stated. Worth a quick confirmation from your advisor before you commit to it in Fluent, since getting it backwards would put the hot spot on the wrong side of the tube.

## Open Items / Unresolved
- ~~Mesh type conflict~~ **RESOLVED (Aug 2026):** unstructured tetrahedral mesh with inflation layers, per proposal Section 3.6 — used consistently for the smooth-tube baseline and every enhanced geometry so Ns/PEC comparisons aren't contaminated by a meshing-method difference. Supersedes CLAUDE.md's earlier "3 hex mesh levels" plan.
- Proposal's own grid-independence (Table 13) and validation figures (Figs 6–9) contain specific numbers that do not reconcile with the smooth-tube GCI numbers already in `mesh-validation/Mesh_and_Validation_Workbook.xlsx`. Not yet resolved whether the proposal's numbers are completed results or template values adapted from Mohammed et al. (2022).
