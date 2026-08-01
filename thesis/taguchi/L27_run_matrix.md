# Taguchi L27 Orthogonal Array — 27 CFD Simulation Runs

## Fixed Parameters (same for all runs)
- dti = 66 mm (absorber inner diameter)
- dto = 70 mm (absorber outer diameter)
- Tube wall thickness = 2 mm
- Tube length = 4000 mm
- Promoter length = 4000 mm
- Promoter material = stainless steel
- Nanoparticle shape: brick, diameter 50 nm
- Base fluid: Syltherm 800

## Factor Definitions

| Factor | Symbol | Level 1 | Level 2 | Level 3 |
|--------|--------|---------|---------|---------|
| A: Twist pitch ratio | Pt/dti | 3.03 | 4.55 | 6.06 |
| B: Promoter size ratio | dpo/dti | 0.23 | 0.38 | 0.53 |
| C: Wall thickness ratio | tp/dpo | 0.04 | 0.08 | 0.12 |
| D: Nanofluid type | — | Fe₂O₃-GO | Al₂O₃-MWCNT | Ag-MgO |
| E: Volume concentration | φ (%) | 0.5 | 1.0 | 2.0 |

## Derived Dimensions

From the ratios and dti = 66 mm:

| Level | Pt (mm) | dpo (mm) | tp @ tp/dpo=0.04 | tp @ tp/dpo=0.08 | tp @ tp/dpo=0.12 |
|-------|---------|----------|-------------------|-------------------|-------------------|
| 1     | 200     | 15       | 0.6 mm            | 1.2 mm            | 1.8 mm            |
| 2     | 300     | 25       | 1.0 mm            | 2.0 mm            | 3.0 mm            |
| 3     | 400     | 35       | 1.4 mm            | 2.8 mm            | 4.2 mm            |

Internal hollow side: dpi = dpo - 2×tp

Worst case check: dpo=15, tp/dpo=0.12 → tp=1.8 mm → dpi=11.4 mm (viable hollow opening).

## L27 Run Matrix

| Run | A (Pt/dti) | B (dpo/dti) | C (tp/dpo) | D (Nanofluid) | E (φ %) | Pt (mm) | dpo (mm) | tp (mm) | dpi (mm) |
|-----|-----------|-------------|-----------|---------------|---------|---------|----------|---------|----------|
| 1   | 3.03      | 0.23        | 0.04      | Fe₂O₃-GO     | 0.5     | 200     | 15       | 0.6     | 13.8     |
| 2   | 3.03      | 0.23        | 0.08      | Al₂O₃-MWCNT  | 1.0     | 200     | 15       | 1.2     | 12.6     |
| 3   | 3.03      | 0.23        | 0.12      | Ag-MgO        | 2.0     | 200     | 15       | 1.8     | 11.4     |
| 4   | 3.03      | 0.38        | 0.04      | Al₂O₃-MWCNT  | 2.0     | 200     | 25       | 1.0     | 23.0     |
| 5   | 3.03      | 0.38        | 0.08      | Ag-MgO        | 0.5     | 200     | 25       | 2.0     | 21.0     |
| 6   | 3.03      | 0.38        | 0.12      | Fe₂O₃-GO     | 1.0     | 200     | 25       | 3.0     | 19.0     |
| 7   | 3.03      | 0.53        | 0.04      | Ag-MgO        | 1.0     | 200     | 35       | 1.4     | 32.2     |
| 8   | 3.03      | 0.53        | 0.08      | Fe₂O₃-GO     | 2.0     | 200     | 35       | 2.8     | 29.4     |
| 9   | 3.03      | 0.53        | 0.12      | Al₂O₃-MWCNT  | 0.5     | 200     | 35       | 4.2     | 26.6     |
| 10  | 4.55      | 0.23        | 0.04      | Al₂O₃-MWCNT  | 1.0     | 300     | 15       | 0.6     | 13.8     |
| 11  | 4.55      | 0.23        | 0.08      | Ag-MgO        | 2.0     | 300     | 15       | 1.2     | 12.6     |
| 12  | 4.55      | 0.23        | 0.12      | Fe₂O₃-GO     | 0.5     | 300     | 15       | 1.8     | 11.4     |
| 13  | 4.55      | 0.38        | 0.04      | Ag-MgO        | 0.5     | 300     | 25       | 1.0     | 23.0     |
| 14  | 4.55      | 0.38        | 0.08      | Fe₂O₃-GO     | 1.0     | 300     | 25       | 2.0     | 21.0     |
| 15  | 4.55      | 0.38        | 0.12      | Al₂O₃-MWCNT  | 2.0     | 300     | 25       | 3.0     | 19.0     |
| 16  | 4.55      | 0.53        | 0.04      | Fe₂O₃-GO     | 2.0     | 300     | 35       | 1.4     | 32.2     |
| 17  | 4.55      | 0.53        | 0.08      | Al₂O₃-MWCNT  | 0.5     | 300     | 35       | 2.8     | 29.4     |
| 18  | 4.55      | 0.53        | 0.12      | Ag-MgO        | 1.0     | 300     | 35       | 4.2     | 26.6     |
| 19  | 6.06      | 0.23        | 0.04      | Ag-MgO        | 2.0     | 400     | 15       | 0.6     | 13.8     |
| 20  | 6.06      | 0.23        | 0.08      | Fe₂O₃-GO     | 0.5     | 400     | 15       | 1.2     | 12.6     |
| 21  | 6.06      | 0.23        | 0.12      | Al₂O₃-MWCNT  | 1.0     | 400     | 15       | 1.8     | 11.4     |
| 22  | 6.06      | 0.38        | 0.04      | Fe₂O₃-GO     | 1.0     | 400     | 25       | 1.0     | 23.0     |
| 23  | 6.06      | 0.38        | 0.08      | Al₂O₃-MWCNT  | 2.0     | 400     | 25       | 2.0     | 21.0     |
| 24  | 6.06      | 0.38        | 0.12      | Ag-MgO        | 0.5     | 400     | 25       | 3.0     | 19.0     |
| 25  | 6.06      | 0.53        | 0.04      | Al₂O₃-MWCNT  | 0.5     | 400     | 35       | 1.4     | 32.2     |
| 26  | 6.06      | 0.53        | 0.08      | Ag-MgO        | 1.0     | 400     | 35       | 2.8     | 29.4     |
| 27  | 6.06      | 0.53        | 0.12      | Fe₂O₃-GO     | 2.0     | 400     | 35       | 4.2     | 26.6     |

## Notes
- Each factor level appears exactly 9 times across 27 runs (statistical balance)
- Every pair of factor levels is tested equally often
- Full factorial would require 3⁵ = 243 runs; Taguchi reduces this to 27
- Output analysis: signal-to-noise ratios + ANOVA to rank factor importance
