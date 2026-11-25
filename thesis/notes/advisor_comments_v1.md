# Advisor Comments on Thesis Draft v1 (received 2026-11-25)

Full progress report was shared with advisor; these are his comments, to be
worked through one by one. Saved here so nothing gets lost or has to be
repeated.

## Formatting / document mechanics

1. **Page numbers** — need to be added (currently missing from the document).
2. **Chapter start pages** — every chapter must start on a new page.
3. **Table 3-4** — currently broken/needs fixing (thermophysical properties
   table — need to open and check what's actually wrong with it: likely a
   layout/rendering issue, possibly similar to the landscape-table column
   problem fixed earlier, or a content gap).
4. **T_ro notation** — remove the underscore in "T_ro", make the "ro" part a
   subscript instead (proper equation/variable formatting, not underscore
   text).
5. **Figure text sizing** — increase font size and bold on figure text
   generally; specifically: panel labels (a)/(b)/(c)/(d) should be bigger
   than the figure number, and the chart title should be the biggest text
   of all on each figure.
6. **Temperature contour legend** — reduce the font size on the Temperature
   contour legend specifically, so the word "Temperature" (or any other long
   word in a legend) does not wrap/split across two lines.
7. **Legend placement bug** — some figures have their legend placed on top of
   the plotted line/data in the chart instead of in the clean top-right
   corner per our established figure style. Need to find and fix these.
8. **University thesis template** — the official university-provided thesis
   template must be followed (need to get this template from Nuradin and
   reformat the whole document to match: margins, fonts, heading styles,
   title page, TOC format, etc. — this may supersede/override some of the
   earlier font-and-heading formatting work already done).

## Wording / terminology

9. **"Improved" instead of "optimized"** — replace the word "optimized"
   (and likely "optimum") throughout with "improved" (e.g. "improved
   geometry" instead of "optimized geometry"). Need to sweep the whole
   document for this term.

## Content additions / scope changes (significant)

10. **Thermal and exergetic efficiency must be added** — the advisor
    explicitly said this CAN be done and that we must do it. This reverses
    the earlier standing project decision (that thermal/exergetic efficiency
    were not supportable given the receiver-only CFD domain, and were
    actively removed from Chapter 4 and the objectives). This now needs to
    be revisited: figure out how to actually compute/support thermal and
    exergetic efficiency for our results and add it back into Chapter 4
    (and correspondingly back into the Scope/Objectives/Thesis Outline
    wording that was deliberately changed to remove it).
11. **Reference count ~116** — the reference list should be close to, at, or
    more than 116 papers, matching the number of papers in the
    "116_Summaries.pdf" / literature summary file. Currently the reference
    list is much shorter. Need to substantially expand the Literature
    Review (Chapter 2) and reference list to pull in more of those 116
    papers.
12. **Temperature, Velocity, and TKE contours for nanofluid results too** —
    the cross-sectional contour treatment done for the geometry section
    (Figures 4-7, 4-8) needs an equivalent for the nanofluid results
    (hybrid screening and/or concentration sweep) — same three fields,
    same contour-comparison approach.
13. **Chapter 4 Summary** — a summary section for Chapter 4 must be written
    (wrapping up all of Section 4's findings).
14. **Correlation equation** — a correlation equation must be developed
    (likely a fitted Nu/f/PEC correlation as a function of Re and the
    geometric/nanofluid parameters, a common PTSC-thesis deliverable;
    need to confirm exact scope with Nuradin before building it).

## Justification

15. **Justification is a must, a lot of text is missing it** — general,
    cross-cutting note: many passages throughout the thesis (not limited to
    Chapter 4) need stronger justification/reasoning, not just statements of
    fact. Needs a careful pass section by section.

## Working notes / sequencing

- Items 1, 2, 4, 5, 6, 7 are mechanical/formatting fixes, independent of each
  other, can be done quickly.
- Item 8 (university template) is a prerequisite that could reshape how
  items 1, 2, 5, 6, 7 are implemented — need the actual template file from
  Nuradin before finalizing formatting, to avoid redoing work.
- Item 9 (optimized -> improved) is a quick global find-and-replace sweep.
- Item 3 (Table 3-4) needs investigation first to know what "solved" means
  here.
- Items 10, 11, 12, 13, 14 are substantial content work, each needing its own
  focused session:
  - Item 10 (thermal/exergetic efficiency) is the biggest reversal and needs
    to be scoped carefully (what data do we actually have/can compute).
  - Item 11 (116 references) is a large literature-review expansion.
  - Item 12 (nanofluid contours) follows the same workflow already
    established for geometry contours (Fluent export -> crop -> table).
  - Item 13 (Chapter 4 summary) should probably come after items 10-12 are
    in place, so it can summarize the final content.
  - Item 14 (correlation equation) needs scope confirmation.
- Item 15 (justification) is best done as a careful full-document read-through
  near the end, once content is otherwise settled, so it's not redone twice.

Status: not yet started on any of these. Working through one at a time per
Nuradin's instruction, starting with whichever he prioritizes first.
