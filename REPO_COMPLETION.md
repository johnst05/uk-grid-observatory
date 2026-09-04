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
| 1 | Postgres running, raw layer loaded from `data/raw/` CSVs | Not started |
| 2 | Raw -> staging transform (dedupe, type, pivot) | Not started |
| 3 | Clean/mart layer: `clean.forecast_vs_outturn` with window functions (divergence, rolling avg, rank, day-over-day delta) | Not started |
| 4 | Power BI dashboard (`.pbix`) | Not started -- **cannot be built inside a headless Linux sandbox**; needs Power BI Desktop on Windows/macOS. This session can export the clean-layer data and write exact build steps, but not produce the `.pbix` itself. |
| 5 | Scheduled refresh (cron/Action) -- important specifically because WINDFOR has no historical archive and must be snapshotted repeatedly to accumulate real forecast history | Not started |
| 6 | Portfolio polish: README results section, architecture diagram, `.gitignore` review | Partially done (architecture diagram + gotchas already in README; results section needs Phase 3 data first) |

## Gap summary

The repo now has a real, working ingestion layer against two live public
APIs (Elexon BMRS, NESO CKAN) with genuine sample data committed, and SQL
schemas for the raw and staging layers. What's still missing to match the
full brief: nothing has been loaded into Postgres yet, there's no
transform/clean layer, no window-function analysis, no dashboard, and no
scheduled refresh. In short: ingestion exists and is proven against real
APIs; everything from "load it into a database" onward is still ahead.

## Prioritized list for future sessions

1. **Phase 1** -- start Postgres (docker compose, or a local cluster if
   Docker's not available), apply the two existing SQL migrations, write
   `ingestion/load_raw.py` to load the `data/raw/` CSVs into `raw.*`
   tables with `source_payload` JSONB, verify row counts.
2. **Phase 2** -- raw -> staging transforms per source, deduped to latest
   `publish_time` per key.
3. **Phase 3** -- `sql/clean/001_create_clean_tables.sql` with the window
   functions described in the brief (divergence, 7/30-day rolling avg,
   `RANK()` on worst misses, `LAG()` day-over-day delta).
4. **Phase 4** -- export clean-layer data for Power BI and document the
   exact dashboard-build steps; the `.pbix` itself needs to be built on a
   machine with Power BI Desktop installed.
5. **Phase 5** -- `docs/refresh_schedule.md` + a scheduled script that
   pulls new FUELHH, snapshots WINDFOR, and reruns the transforms.
6. **Phase 6** -- once Phase 3 produces real numbers, add the results/
   insights section to the README (e.g. "wind forecasts diverge from
   outturn by an average of X MW, Y% of the time by more than Z").

Detailed narration of what was tried, what failed, and every gotcha found
along the way is in [`docs/build-log/`](docs/build-log/), organized one
file per phase.
