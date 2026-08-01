# AWS AI & ML Scholars — Journey Guide

A living companion for Nuradin's acceptance into the **AWS AI & ML Scholars**
program (AWS + Udacity), **AI Programmer** track. Confirmed legitimate via
AWS's official training blog and Udacity's official scholarship page (see
Sources at the bottom) — the earlier phishing caution on the forwarded email
is resolved; the underlying program is real.

## The program, in one picture

```
Challenge Phase (already completed)      Nanodegree Phase (Aug 4 – Nov 4, 2026)
Mar 24 – Jun 24, 2026                     Top 4,500 of ~100,000 advance here
AWS AI Practitioner content,        --->  Fully-funded Udacity Nanodegree
PartyRock + Bedrock hands-on              in one of 3 tracks — you got:
                                                AI PROGRAMMER
```

You already cleared the hard filter (top ~4.5% of applicants) — the
Nanodegree phase is the payoff.

## What "AI Programmer" actually covers

This track maps closely to Udacity's existing **AI Programming with Python**
and **Deep Learning** Nanodegree content. Concretely, expect to build:

1. **Python for AI/data work** — NumPy, pandas, Matplotlib; PCEP-level
   programming fluency assumed as a base, built up from there.
2. **Neural networks in PyTorch** — implementing and training networks
   yourself, not just calling a library function.
3. **Transformers, from scratch and pre-trained** — build a small
   Transformer to understand the mechanics (attention, embeddings), then
   learn to use pre-trained ones (the same family of architecture behind
   Bedrock's models) effectively in projects.
4. **Hands-on projects** — this is project-graded, not exam-graded; expect
   a portfolio of runnable code by the end, likely a capstone.

This is a **build-it-yourself** track, not a "call an API" track. It's
closer to an ML engineer's early curriculum than a pure app-integration
course — treat the math (linear algebra, calculus basics, probability) as
in-scope, not optional.

## Key dates

| Event | Date |
|---|---|
| Nanodegree phase starts | Tuesday, August 4, 2026 |
| Virtual kickoff (orientation) | Wednesday, August 5, 2026, 8:00 AM Pacific, via Zoom |
| Nanodegree phase ends | Wednesday, November 4, 2026 (~13 weeks) |

## How to make the most of it

**Before Aug 4:**
- Skim/refresh Python basics (functions, classes, list/dict comprehensions,
  numpy array ops) if it's been a while — don't spend the first two weeks
  relearning syntax instead of learning transformers.
- Install locally: Python, a virtual env tool (venv/conda), Jupyter, PyTorch
  (CPU build is fine to start), git. Get a free Colab or Kaggle account too
  — free GPU time matters once training gets heavier than a laptop can
  handle.
- Skim "attention is all you need" concepts at a high level (many good
  3Blue1Brown-style explainer videos exist) so week-one Transformer content
  isn't the first time you've heard the terms.

**During the program:**
- **Ship every project, don't just watch videos.** Udacity Nanodegrees are
  project-graded — passive video-watching doesn't produce the portfolio or
  the actual skill. Budget more hours for building than for lectures.
- **Use office hours and mentors early**, not just when stuck for days —
  scholarship cohorts are competitive for mentor time; asking early gets
  faster answers.
- **Engage the Slack/Discord cohort.** Scholarship programs live or die on
  peer community — study groups, shared debugging, accountability partners
  for the ~13-week span.
- **Push every project to GitHub as you finish it** (public repo, clean
  README, short writeup of what you built and why) — this becomes your
  portfolio for job applications, not just a grading artifact. This repo's
  `progress-tracker.md` can log which projects are pushed where.
- **Write a one-paragraph "what I learned" note after each module** in
  `progress-tracker.md` — it's the fastest way to notice gaps before a
  project deadline exposes them.
- **Don't skip the "pre-trained models" material** even though building
  from scratch is more fun — knowing when *not* to train from scratch is
  the actually-employable skill.

**After Nov 4:**
- Use the up-to-3-months of free AWS Skill Builder access immediately,
  before it expires — target AWS Certified AI Practitioner or Machine
  Learning Engineer - Associate as a concrete next milestone.
- Turn the capstone project into a portfolio centerpiece: polished README,
  a short demo video or GIF, and a write-up of the design decisions.

## Files in this folder

- [`progress-tracker.md`](./progress-tracker.md) — phase-by-phase checklist,
  update as real module names/deadlines appear in your Udacity classroom.

Paste in any classroom content, project rubrics, or deadlines you get and
I'll fold them into the tracker and explain anything that's unclear.

## Sources

- [AWS AI & ML Scholars is open for 2026 (AWS official blog)](https://aws.amazon.com/blogs/training-and-certification/aws-ai-ml-scholars-is-open-for-2026-get-started-on-your-ai-learning-journey/)
- [AWS AI & ML Scholars (Udacity official scholarship page)](https://www.udacity.com/scholarships/aws-ai-ml-scholars)
- [AI Programming with Python Nanodegree (Udacity nd089, the closest public analog to the AI Programmer track)](https://www.udacity.com/course/ai-programming-python-nanodegree--nd089)
