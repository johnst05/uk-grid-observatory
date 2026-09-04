---
tags: [uk-grid-observatory, build-log, phase-2]
project: "[[UK Grid Observatory]]"
date: 2026-09-04
phase: 2
status: done
---

# Phase 2 — Raw → staging transform

## Approach: full rebuild, not incremental

`ingestion/transform_staging.py` truncates each staging table and rebuilds
it from raw every run. This is safe because raw is append-only (Phase 1)
— nothing staging-only would be lost — and at current volumes
(hundreds of thousands of rows) a full rebuild is fast. Flagged as a
scale limitation rather than solved: a real incremental/merge strategy
would matter once raw grows into the tens of millions of rows, not now.

## Grain problems that needed real decisions

1. **NESO generation mix is wide, half-hourly by naive `datetime`** — one
   column per fuel (`gas_mw`, `wind_mw`, ...) rather than one row per
   fuel. Unpivoted with `unnest()` against two parallel arrays (fuel names
   and their values) to get it into the same long
   `(settlement_date, settlement_period, fuel_type)` shape as
   `staging.generation_outturn`. `datetime` has no timezone info but is
   already UK local clock time (half-hour steps starting at `00:00`), so
   `settlement_period` is computed directly from its hour/minute — no
   timezone conversion needed for this one.

2. **WINDFOR is hourly UTC (`start_time`), everything else is half-hourly
   UK-local settlement periods.** This needed an actual timezone
   conversion (`AT TIME ZONE 'Europe/London'`), not just arithmetic,
   because the UK is on BST (UTC+1) for part of the year. Verified this
   was handled correctly with a spot check:

   ```
   raw:      start_time = 2026-09-03 20:00:00+00, generation_mw = 12423
   staging:  settlement_date = 2026-09-03, settlement_period = 43  (2026-09-03 21:00 local)
             settlement_date = 2026-09-03, settlement_period = 44  (2026-09-03 21:30 local)
   ```

   20:00 UTC in September (BST, UTC+1) is 21:00 local → period 43 is
   correct (period *n* covers local time `(n-1)*30` minutes after
   midnight, so 21:00 → period `21*2+1 = 43`). Each hourly WINDFOR value
   is written to both half-hour periods it spans, via
   `CROSS JOIN generate_series(0, 1)`.

3. **NESO's fuel taxonomy doesn't match Elexon's.** NESO's generation mix
   reports `GAS`, `COAL`, `WIND`, `WIND_EMB`, `HYDRO`, `IMPORTS`,
   `BIOMASS`, `OTHER`, `SOLAR`, `STORAGE`, `NUCLEAR`. Elexon's FUELHH
   reports BM-unit-level fuel types: `CCGT`, `OCGT`, `WIND`, `NUCLEAR`,
   `BIOMASS`, `COAL`, `NPSHYD`, `PS`, `OIL`, `OTHER`, plus a long tail of
   interconnector codes (`INTFR`, `INTIRL`, `INTNED`, ...) that NESO rolls
   up into a single `IMPORTS` figure. **Decision: don't force a mapping
   that doesn't really exist.** Both sources' fuel_type values are loaded
   as-is, distinguished by `source`. `WIND`, `NUCLEAR`, `COAL`, and
   `BIOMASS` happen to be named identically in both and are directly
   comparable cross-source; `GAS` (NESO) vs `CCGT`+`OCGT` (Elexon) and
   `IMPORTS` (NESO) vs the interconnector codes (Elexon) are not
   comparable without an explicit rollup, which wasn't built here since
   it wasn't needed for the wind-forecast-divergence question this
   project is actually about.

4. **`staging.demand_forecast` intentionally stays off the settlement-period
   grain** — NESO's day-ahead forecast is published at named cardinal
   points (overnight minimum, evening peak, ...), which don't line up with
   half-hours. Kept at `(target_date, days_ahead, cardinal_point, source)`,
   as planned in [[phase-0-foundation]].

## Dedup verification

Per the brief's Phase 2 acceptance check ("row counts make sense... no
duplicate primary keys"):

| Staging table | Rows | Note |
|---|---|---|
| `generation_outturn` | 133,920 | 86,400 (Elexon FUELHH, 1:1 with raw — no revisions in this pull) + 47,520 (NESO: 4,320 half-hours × 11 fuel types) |
| `generation_forecast` | 146 | 73 WINDFOR rows × 2 half-hour periods each |
| `demand_outturn` | 4,320 | 1:1 with raw — no revisions in this pull |
| `demand_forecast` | 986 | raw had 1,030 rows but only **986 distinct** `(target_date, days_ahead, cardinal_point)` keys — 44 rows were later revisions of an earlier forecast, correctly collapsed to the latest `forecast_timestamp` by `DISTINCT ON` |

No duplicate-key errors on insert (staging's composite primary keys would
have rejected the insert outright if `DISTINCT ON` had missed anything —
it didn't).

Note on `generation_outturn`/`demand_outturn` showing zero revisions
collapsed: expected, since this raw data came from a single ingestion
pull rather than the same settlement periods being re-pulled and
republished over time. Once Phase 5's scheduled refresh has run for a
while, later pulls will actually exercise the "supersedes an earlier row"
path for these two.
