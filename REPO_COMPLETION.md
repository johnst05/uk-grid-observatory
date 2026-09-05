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
| 4 | Power BI dashboard (`.pbix`) | **Partial by necessity** -- `.pbix` itself cannot be built inside this headless Linux sandbox (needs Power BI Desktop on Windows/macOS). Data exported (`dashboard/*.csv`) and exact click-by-click build steps for all 4 required visuals written in `dashboard/README.md`. |
| 5 | Scheduled refresh (cron/Action) -- important specifically because WINDFOR has no historical archive and must be snapshotted repeatedly to accumulate real forecast history | **Done** -- `ingestion/refresh.py` ran twice for real in this session; found and fixed a real idempotency bug in the Phase 1 loader along the way |
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

1. **Actually schedule `ingestion/refresh.py` to run daily** (cron entry
   or the included `.github/workflows/refresh.yml`, once it has a
   Postgres it can reach). It's built, idempotent, and was verified
   working end-to-end in this session -- what it needs now is real
   elapsed calendar time running on a schedule, which no single session
   can produce. Every day this isn't scheduled is a day of WINDFOR
   forecast history gone for good.
2. **Build the actual `.pbix`** on a machine with Power BI Desktop
   installed, following `dashboard/README.md`'s click-by-click steps --
   this repo has done everything possible short of that (data exported,
   live-connection instructions, exact DAX measures written out).
3. **Phase 6** -- once there's enough real forecast history to say
   something true, add the results/insights section to the README (e.g.
   "wind forecasts diverge from outturn by an average of X MW, Y% of the
   time by more than Z").

Detailed narration of what was tried, what failed, and every gotcha found
along the way is in [`docs/build-log/`](docs/build-log/), organized one
file per phase.
