# Twist Pitch Sweep (18 Runs) — Diagnosis Audit

Fixed: dpo=0.23, tp=0.07. Varying: Pt (200/300/400mm) x Re (5k-30k).

Output snapshot check (from twist_pitch_v2.xlsx) confirms: all 18 have complete,
physically plausible final values (no divergence, nothing missing). So the only
open question per run is whether residuals have actually FLATTENED (not just
"look okay at the last iteration").

Status key:
- OK — residuals flat, converged, nothing to do
- NOT_FLAT — ran, converged-looking output, but residuals still drifting -> needs more iterations
- DIVERGED — needs UDF application / fix
- NOT_RUN — needs running with UDF applied

| # | Label | Status | Notes |
|---|---|---|---|
| 1 | 200Pt @ 5K | OK | Confirmed flat, converged by ~it.300 |
| 2 | 200Pt @ 10K | OK | Confirmed flat, converged by ~it.300 |
| 3 | 200Pt @ 15K | OK | Confirmed by Nuradin |
| 4 | 200Pt @ 20K | OK | Confirmed by Nuradin |
| 5 | 200Pt @ 25K | OK | Confirmed by Nuradin |
| 6 | 200Pt @ 30K | OK | Confirmed by Nuradin |
| 7 | 300Pt @ 5K | OK | Confirmed by Nuradin |
| 8 | 300Pt @ 10K | OK | Confirmed by Nuradin |
| 9 | 300Pt @ 15K | OK | Confirmed by Nuradin |
| 10 | 300Pt @ 20K | OK | Confirmed by Nuradin |
| 11 | 300Pt @ 25K | OK | Confirmed by Nuradin |
| 12 | 300Pt @ 30K | OK | Confirmed by Nuradin |
| 13 | 400Pt @ 5K | OK | Confirmed by Nuradin |
| 14 | 400Pt @ 10K | OK | Confirmed by Nuradin |
| 15 | 400Pt @ 15K | OK | Confirmed by Nuradin |
| 16 | 400Pt @ 20K | OK | Confirmed by Nuradin |
| 17 | 400Pt @ 25K | OK | Confirmed by Nuradin |
| 18 | 400Pt @ 30K | OK | Confirmed by Nuradin |

**TWIST PITCH SWEEP: ALL 18 RUNS CONFIRMED GOOD. Audit complete.**
