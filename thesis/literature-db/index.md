# Literature Database — Master Index

Tracks every paper processed, its duplicate-check result, and where its
extraction lives. Updated after every paper.

## Standing rule (2026-11-26)
Review papers are excluded from this database, period - never logged, never
summarized, never counted toward the reference expansion. Only original
research papers (experimental or numerical studies reporting new results)
are processed. Before reading a new paper in full, its abstract/intro is
checked first to confirm it is not a review/survey.

## Files in this system
- `existing_74_refs.md` — baseline: the 74 references already live in `Thesis_draft_v1.docx`. Never edited; only checked against.
- `Grand_Literature_Review.docx` — full narrative summary per paper, appended in order received. Template per entry:
  1. **Header**: Year — Title — Scope tag (PTSC+Geo only / PTSC+Nano only / PTSC+Geo+Nano, names given)
  2. **Narrative summary**: geometry/nanofluid studied (figure cited), method, software, Fluent/solver setup in detail (mesh, turbulence model, BCs, y+, discretization, convergence), parameters varied vs. held constant, findings with real numbers/%, visuals/post-processing used
  3. **Tagged fields**: turbulence model, nanofluid property model (Maxwell/Brinkman/etc.), domain type (receiver-only vs. full collector w/ envelope), validation method + deviation %, Re/Tin range, paper-stated limitations
  4. **Overlap flag**: explicit note if it shares our geometry, nanofluid, method, or metric
  5. **Duplicate check**: NEW, or "duplicate of [N]"
  6. Every figure/equation/page cited inline (Fig. N, Eq. N, p. N)
- `Literature_Database.xlsx` — one row per paper, same fields as filterable columns.
- `papers/` — optional per-paper working notes if a summary needs drafting before going into the Grand file.

## Log

| # | Year | Authors (short) | Title (short) | Duplicate check | Status |
|---|------|------------------|----------------|------------------|--------|
| P001 | 2008 | Reddy, Ravi Kumar, Satyanarayana | Energy-Efficient Receiver for PTSC | DUPLICATE of [44] | Logged |
| P002 | 2008 | Reddy, Satyanarayana | Porous Finned Receiver for PTSC | DUPLICATE of [43] | Logged |
| P003 | 2009 | Ravi Kumar, Reddy | Porous Disc Receiver for Solar PTSC | NEW | Logged |
| P004 | 2013 | de Risi, Milanese, Laforgia | Transparent PTC, Gas-Phase Nanofluids | NEW | Logged |
| P005 | 2011 | Munoz, Abanades | Internal Helically Finned Tubes (CFD) | DUPLICATE of [45] | Logged |
| P006 | 2012 | Cheng, He, Cui | Unilateral Longitudinal Vortex Generators | DUPLICATE of [46] | Logged |
| P007 | 2013 | Wang, Liu, Xu | Metal Foams in DSG Receiver Tube | NEW | Logged |
| P008 | 2013 | Ghasemi, Ranjbar, Ramiar | Porous Three Segmental Rings | NEW | Logged |
| P009 | 2014 | Ghadirijafarbeigloo, Zamzamian, Yaghoubi | Louvered Twisted-Tape Receiver Insert | DUPLICATE of [33] | Logged |
| P010 | 2014 | Mwesigye, Bello-Ochende, Meyer | Centrally Placed Perforated Plate Inserts | DUPLICATE of [34] | Logged |
| P011 | 2014 | Song, Dong, Gao, Diao, Zheng, Zhou | Nonuniform Heat Flux + Helical Screw-Tape | DUPLICATE of [36] | Logged |
| P012 | 2014 | Xiao, Zhang, Shao, Li | V-Cavity Absorber with Rectangular Fins | NEW | Logged |
| P013 | 2015 | Diwan, Soni | Wire-Coil Inserts | DUPLICATE of [51] | Logged |
| P014 | 2015 | Nayak, Sinha, Kumar, Kumar | Nanofluid + Nail Twisted Tape (STPTCS) | NEW | Logged |
| P015 | 2016 | Bellos, Tzivanidis, Antonopoulos, Gkinis | Nanofluid + Converging-Diverging Tube | DUPLICATE of [58] | Logged |
| P016 | 2015 | Rios-Iribe et al. | Non-Newtonian Fluid + Twisted Tape (NOT PTSC) | NEW | Logged |
| P017 | 2015 | Huang, Yu, Li, Tao | Dimples vs Protrusions vs Helical Fins | DUPLICATE of [48] | Logged |
| P018 | 2016 | Benabderrahmane, Aminallah, Laouedj, Benazza, Solano | Longitudinal Fins + Al2O3/Cu/SiC/C Nanofluids | DUPLICATE of [59] | Logged |
| P019 | 2016 | Benabderrahmane, Benazza, Aminallah, Laouedj | Baffles + Fullerene/CNT Nanofluid | NEW | Logged |
| P020 | 2017 | Nanan, Thianpong, Pimsarn, Chuwattanakul, Eiamsa-ard | Twisted Cross-Baffle Turbulators (NOT PTSC) | NEW | Logged |
| P021 | 2016 | Jaramillo, Borunda, Velazquez-Lucho, Robles | Low-Enthalpy PTC + Twisted Tape | DUPLICATE of [39] | Logged |
| P022 | 2016 | Mwesigye, Bello-Ochende, Meyer | Wall-Detached Twisted Tape Inserts | DUPLICATE of [35] | Logged |
