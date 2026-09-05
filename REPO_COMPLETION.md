# Repo Completion Assessment

**Last updated:** 2026-09-05

## What this repo is

UK Grid Observatory: a pipeline that measures how far NESO/Elexon
generation forecasts (especially wind) diverge from metered outturn, via
Postgres (raw -> staging -> clean with window functions) and a Power BI
dashboard. Full project brief lives in the session history that scoped
this repo; the phase breakdown below is that brief's build routine.

## History

- 2026-09-04, first automated pass: repo was completely empty (no
  commits, no branches). Scoped from a full project brief in the same
  session and built from scratch, phase by phase, through 2026-09-05.

## Phase status

| Phase | What | Status |
|---|---|---|
| 0 | Foundation: README, deps, docker-compose, .env.example, sql/raw + sql/staging, ingestion scripts, real sample data in `data/raw/` | **Done** |
| 1 | Postgres running, raw layer loaded from `data/raw/` CSVs | **Done** |
| 2 | Raw -> staging transform (dedupe, type, pivot) | **Done** |
| 3 | Clean/mart layer: `clean.forecast_vs_outturn` with window functions (divergence, rolling avg, rank, day-over-day delta) | **Done, but only 6 rows of real overlap exist so far** -- see `docs/build-log/phase-3-clean-layer.md` |
| 4 | Power BI dashboard (`.pbix`) | **Partial by necessity** -- `.pbix` cannot be built inside this headless Linux sandbox (needs Power BI Desktop on Windows/macOS). Data exported and exact click-by-click build steps written in `dashboard/README.md`. |
| 5 | Scheduled refresh -- important specifically because WINDFOR has no historical archive and must be snapshotted repeatedly to accumulate real forecast history | **Done** -- `ingestion/refresh.py` ran twice for real in this session; found and fixed a real idempotency bug in the Phase 1 loader along the way. Not yet actually scheduled anywhere (see below). |
| 6 | Portfolio polish: README results section, architecture diagram, `.gitignore` review | **Done** -- see `docs/build-log/phase-6-polish.md` |

Every phase in the brief has been executed against real data end-to-end.
The two things genuinely outstanding are not "unfinished work" so much as
"work that needs a different environment or real elapsed time," detailed
below.

## Gap summary

The full raw -> staging -> clean pipeline runs end-to-end against real
data: raw is loaded and spot-checked, staging is deduped and
grain-reconciled across two providers with genuinely different data
shapes, and `clean.forecast_vs_outturn` computes every window function
the brief specified and returns correct numbers. The README's Results
section reports two real findings with their actual sample sizes stated
(a robust 4,320-point Elexon-vs-NESO comparison, and a preliminary 6-point
forecast-divergence figure) rather than one blended, overconfident
headline. What's left is: (a) actually scheduling the refresh job
somewhere it will run daily -- it's built and proven, just not deployed to
a scheduler -- and (b) building the literal `.pbix` file, which requires
Power BI Desktop on a machine this sandbox can't provide.

## Prioritized list for future sessions

1. **Schedule `ingestion/refresh.py` to actually run daily** (cron entry,
   Task Scheduler, or `.github/workflows/refresh.yml` once it has a
   Postgres it can reach). This is the single highest-leverage remaining
   step: every day it isn't running is a day of WINDFOR forecast history
   that can never be recovered afterward.
2. **Build the actual `.pbix`** on a machine with Power BI Desktop
   installed, following `dashboard/README.md`'s click-by-click steps.
3. **Revisit the README's Results section periodically** as the scheduled
   refresh accumulates real WINDFOR history -- re-run the forecast-vs-
   outturn query, update the sample size and the numbers, and only then
   consider the kind of general claim the original brief envisioned
   ("wind forecasts diverge from outturn by an average of X MW, Y% of the
   time by more than Z").

Detailed narration of what was tried, what failed, and every gotcha found
along the way is in [`docs/build-log/`](docs/build-log/), organized one
file per phase.
