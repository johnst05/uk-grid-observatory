# Repo Completion Assessment

**Last updated:** 2026-09-04

## What this repo is

UK Grid Observatory: a pipeline that measures how far NESO/Elexon
generation forecasts (especially wind) diverge from metered outturn, via
Postgres (raw -> staging -> clean with window functions) and a Power BI
dashboard. Full project brief lives in the session history that scoped
this repo; the phase breakdown below is that brief's build routine.

## History

- 2026-09-04, first automated pass: repo was completely empty (no commits,
  no branches) -- see git history for that finding. It has since been
  scoped and Phase 0 was started from scratch in the same session.

## Phase status

| Phase | What | Status |
|---|---|---|
| 0 | Foundation: README, deps, docker-compose, .env.example, sql/raw + sql/staging, ingestion scripts, real sample data in `data/raw/` | **Done** |
| 1 | Postgres running, raw layer loaded from `data/raw/` CSVs | **Done** |
| 2 | Raw -> staging transform (dedupe, type, pivot) | **Done** |
| 3 | Clean/mart layer: `clean.forecast_vs_outturn` with window functions (divergence, rolling avg, rank, day-over-day delta) | **Done, but only 6 rows of real overlap exist so far** -- see caveat below and `docs/build-log/phase-3-clean-layer.md` |
| 4 | Power BI dashboard (`.pbix`) | Not started -- **cannot be built inside a headless Linux sandbox**; needs Power BI Desktop on Windows/macOS. This session can export the clean-layer data and write exact build steps, but not produce the `.pbix` itself. |
| 5 | Scheduled refresh (cron/Action) -- important specifically because WINDFOR has no historical archive and must be snapshotted repeatedly to accumulate real forecast history | Not started |
| 6 | Portfolio polish: README results section, architecture diagram, `.gitignore` review | Partially done (architecture diagram + gotchas already in README; results section needs Phase 3 data first) |

## Gap summary

The full raw -> staging -> clean pipeline now runs end-to-end against
real data: raw is loaded and spot-checked, staging is deduped and
grain-reconciled across two providers with genuinely different data
shapes, and `clean.forecast_vs_outturn` computes every window function
the brief specified and returns correct numbers. The one real gap left in
the pipeline itself: the view only has **6 rows of actual forecast/outturn
overlap** right now, because WINDFOR (Elexon's only generation forecast
dataset) has no historical archive -- only ever "whatever the current
rolling forecast says." Nothing general can be claimed about wind
forecast accuracy from 6 points on one evening; that needs Phase 5 to run
repeatedly over real time to build up history. Beyond the pipeline: no
dashboard yet, and no scheduled refresh yet.

## Prioritized list for future sessions

1. **Phase 5 matters most now, and is time-sensitive**: `docs/refresh_schedule.md`
   + a scheduled script that pulls new FUELHH, snapshots WINDFOR, and
   reruns staging/clean. Every day this doesn't run is a day of WINDFOR
   forecast history that's gone for good (there's no way to retrieve it
   after the fact) -- do this before Phase 4, not after, even though the
   brief lists it last.
2. **Phase 4** -- export clean-layer data for Power BI and document the
   exact dashboard-build steps; the `.pbix` itself needs to be built on a
   machine with Power BI Desktop installed. Worth waiting for Phase 5 to
   accumulate at least a few days of real forecast history first, or the
   dashboard will just be visualizing the same 6-row caveat.
3. **Phase 6** -- once there's enough real forecast history to say
   something true, add the results/insights section to the README (e.g.
   "wind forecasts diverge from outturn by an average of X MW, Y% of the
   time by more than Z").

Detailed narration of what was tried, what failed, and every gotcha found
along the way is in [`docs/build-log/`](docs/build-log/), organized one
file per phase.
