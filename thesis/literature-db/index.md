# Literature Database — Master Index

Tracks every paper processed, its duplicate-check result, and where its
extraction lives. Updated after every paper.

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
