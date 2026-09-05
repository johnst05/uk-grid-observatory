---
tags: [uk-grid-observatory, build-log, phase-6]
project: "[[UK Grid Observatory]]"
date: 2026-09-05
phase: 6
status: done
---

# Phase 6 — Portfolio polish

## Results section: kept the two findings separate on purpose

Computed two real numbers from the actual database rather than writing
placeholder text:

- Elexon vs NESO wind outturn: **n = 4,320**, correlation 0.985, mean
  absolute difference 380.5 MW — a real, statistically meaningful result
  from 90 days of genuine overlap.
- WINDFOR forecast vs outturn: **n = 6**, mean divergence -2,746 MW
  (22.1% of forecast) — real and correctly computed, but from six points
  on one evening.

Deliberately wrote these as two separate findings with their own sample
sizes stated up front, rather than folding them into one "headline"
number. Blending a robust 4,320-point result with a 6-point one into a
single confident-sounding sentence would misrepresent how much is
actually known — the brief's own acceptance language ("wind forecasts
diverge from outturn by an average of X MW, Y% of the time by more than
Z") is exactly the kind of generalization that needs real accumulated
history to make honestly, which doesn't exist yet.

## Architecture diagram: switched to Mermaid

Replaced the plain-text ASCII diagram from Phase 0 with a Mermaid
flowchart (GitHub renders these natively in READMEs). Added the scheduled
refresh as a dashed-line node feeding back into both APIs, since it's a
recurring process rather than a one-time step in the pipeline — worth
making visually distinct from the once-through raw→staging→clean flow.

## `.gitignore` review

Checked against the brief's requirement ("make sure sample CSVs in
data/raw/ are still intentionally committed"): confirmed `data/raw/` was
never added to `.gitignore` at any point across all six phases, `.env` /
`__pycache__` / `logs/` are correctly ignored, and `git status` shows a
clean tree with nothing unintentionally tracked or untracked.

## What this phase deliberately did NOT do

Did not backfill the Results section with invented numbers to make the
project look more "finished" than the underlying data supports. The
honest small-sample caveat from Phase 3 is carried through to the
README's Results section verbatim rather than smoothed over — a reader
of this repo should come away knowing exactly how much of the analysis is
solid (the cross-source comparison) versus how much is a proof-of-concept
pending more scheduled runs (the forecast divergence).
