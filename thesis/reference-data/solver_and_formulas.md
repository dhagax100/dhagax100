# Solver Settings & Performance Formulas

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
| Wall treatment | Enhanced wall treatment |
| Continuity residual | 10⁻⁶ |
| All other residuals | 10⁻⁸ |

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

## Performance Metrics

### Thermal efficiency:
```
η_th = (Q_u - P_p/η_el) / (A_a × I_b)
```
- Q_u = ṁ × cp × (Tout - Tin)
- P_p = V̇ × ΔP (pumping power)
- η_el = 0.3
- A_a = 39.2 m² (APERTURE area)

### PEC (fluid enhancement):
```
PEC₁ = (Nu_hnf/Nu_f) / (f_hnf/f_f)^(1/3)
```

### PEC (geometry enhancement):
```
PEC₂ = (Nu_w/Nu_o) / (f_w/f_o)^(1/3)
```

### Total entropy generation:
```
S_gen_total = S_gen_F + S_gen_H
```
(friction + heat transfer contributions)

### Bejan number:
```
Be = S_gen_H / S_gen_total
```
(Be → 1 means heat transfer dominates irreversibility; Be → 0 means friction dominates)

### Exergetic efficiency:
See proposal Eq. 3.22–3.24 for full formulation.
