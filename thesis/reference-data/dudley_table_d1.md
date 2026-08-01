# Dudley et al. (SAND94-1884) — LS-2 Collector Validation Data

## Collector Specifications
- Aperture area: 39.2 m²
- Receiver outer diameter: 70 mm
- Receiver inner diameter: 66 mm
- Receiver length: 4.06 m (effective test length)
- Absorber coating: cermet
- Annulus condition: vacuum
- HTF: Syltherm 800

## Table D-1: Cermet / Vacuum Test Cases (9 cases used for validation)

| Case | DNI (W/m²) | Wind (m/s) | Tin (°C) | Flow (L/min) | Tout_meas (°C) | η_th_meas (%) |
|------|-----------|------------|----------|--------------|----------------|---------------|
| 1    | 933.7     | 2.6        | 102.2    | 47.7         | 124.0          | 72.51         |
| 2    | 968.2     | 3.7        | 151.0    | 47.8         | 173.3          | 70.90         |
| 3    | 982.3     | 2.5        | 197.5    | 49.1         | 219.5          | 70.17         |
| 4    | 906.6     | 3.3        | 250.7    | 54.7         | 269.4          | 70.25         |
| 5    | 937.9     | 1.0        | 297.8    | 55.5         | 316.9          | 67.98         |
| 6    | 880.6     | 2.9        | 299.0    | 55.6         | 317.2          | 68.92         |
| 7    | 920.9     | 2.6        | 379.5    | 56.8         | 398.0          | 62.34         |
| 8    | 903.2     | 4.2        | 355.9    | 56.3         | 374.0          | 63.82         |
| 9    | 920.9     | 2.6        | 379.5    | 56.8         | 398.0          | 62.34         |

Note: Cases 7 and 9 are identical in the original report.

## Key Validation Formula

Thermal efficiency (Eq. 3.34 from proposal):

```
η_th = (Q_u - P_p/η_el) / (A_a × I_b)
```

Where:
- Q_u = m_dot × c_p × (T_out - T_in) ... useful heat gained by oil
- P_p = V_dot × ΔP ... pumping power
- η_el = 0.3 ... electrical efficiency factor
- A_a = 39.2 m² ... mirror APERTURE area (NOT tube surface area)
- I_b = DNI ... beam irradiance

## CRITICAL: The denominator uses aperture area (39.2 m²), not tube surface area. This is a common mistake.

## Dudley Performance Regression (cermet/vacuum)

```
η_th = 73.3 - 0.007276 × ΔT - 0.000135 × ΔT²/I_b
```

Where ΔT = (T_avg - T_ambient), T_avg = (T_in + T_out)/2.
