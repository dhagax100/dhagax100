# Promoter Size (dpo) Sweep (18 Runs) — Diagnosis Audit

Fixed: Pt=200mm, tp=0.05. Varying: dpo (0.15/0.20/0.25) x Re (5k-30k).

Output snapshot check (from nanos_v2.xlsx, runs 19-36) found ONE clear problem;
the other 17 look physically plausible but still need the residual-flatness
check in Fluent (same as twist pitch).

Status key:
- OK — residuals flat, converged, nothing to do
- NOT_FLAT — ran, converged-looking output, but residuals still drifting -> needs more iterations
- DIVERGED/BAD — needs UDF application / fix
- NOT_RUN — needs running with UDF applied

| # | Label | Status | Notes |
|---|---|---|---|
| 19 | dpo=0.15 @ 5K | TBD | |
| 20 | dpo=0.15 @ 10K | TBD | |
| 21 | dpo=0.15 @ 15K | TBD | |
| 22 | dpo=0.15 @ 20K | TBD | |
| 23 | dpo=0.15 @ 25K | TBD | |
| 24 | dpo=0.15 @ 30K | TBD | |
| 25 | dpo=0.20 @ 5K | TBD | |
| 26 | dpo=0.20 @ 10K | TBD | |
| 27 | dpo=0.20 @ 15K | TBD | |
| 28 | dpo=0.20 @ 20K | TBD | |
| 29 | dpo=0.20 @ 25K | TBD | |
| 30 | dpo=0.20 @ 30K | TBD | |
| 31 | dpo=0.25 @ 5K | TBD | |
| 32 | dpo=0.25 @ 10K | TBD | |
| 33 | dpo=0.25 @ 15K | **BAD** | Wall heat flux collapsed to 3.79 W/m² (expected ~37765); t_wall≈t_out≈500K — degenerate/invalid result, same signature as Ag-MgO 2%@15K |
| 34 | dpo=0.25 @ 20K | TBD | |
| 35 | dpo=0.25 @ 25K | TBD | |
| 36 | dpo=0.25 @ 30K | TBD | |
