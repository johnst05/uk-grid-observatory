---
tags: [uk-grid-observatory, build-log, phase-1]
project: "[[UK Grid Observatory]]"
date: 2026-09-04
phase: 1
status: done
---

# Phase 1 — Postgres running, raw layer loaded

## Environment note

No Docker daemon in this sandbox (confirmed in [[phase-0-foundation]]), so
Postgres was started via the system's own cluster instead of
`docker compose up`:

```bash
pg_ctlcluster 16 main start
# then, one-time setup (docker-compose.yml creates these automatically
# when run for real; sandbox needed them created by hand):
psql -c "CREATE ROLE grid WITH LOGIN PASSWORD 'grid_dev_password';"
psql -c "CREATE DATABASE grid_observatory OWNER grid;"
```

Functionally identical outcome to `docker compose up -d` — same DB name,
user, password, port (5432) — so `.env.example` didn't need to change.

## Migrations applied

```bash
psql "$DATABASE_URL" -f sql/raw/001_create_raw_tables.sql
psql "$DATABASE_URL" -f sql/staging/001_create_staging_tables.sql
```

Both applied cleanly, no errors, on the first attempt — schemas were
already validated by construction in Phase 0.

## `ingestion/load_raw.py`

Wrote a loader that globs `data/raw/*.csv` by filename pattern (one glob
per source table, since ingestion filenames carry a date range or
timestamp that varies run to run), loads each matching file with pandas,
and bulk-inserts via `psycopg2.extras.execute_values`. Each row's
`source_payload` is the *entire* original CSV row serialized to JSON
(NaN mapped to `None` first, so it lands as SQL `NULL` rather than the
literal string `"NaN"`), independent of whatever typed columns are also
pulled out.

Design choice: raw is append-only. The loader never truncates or
upserts — running it again after a fresh ingestion pull just adds the new
file's rows. Deduplication is staging's job (Phase 2), not raw's.

## Run + acceptance check

```
python3 ingestion/load_raw.py
```

All five tables loaded on the first run, no retries needed:

| Table | Rows loaded |
|---|---|
| `raw.elexon_fuelhh` | 86,400 |
| `raw.elexon_demand_outturn` | 4,320 |
| `raw.elexon_windfor` | 73 |
| `raw.neso_generation_mix` | 4,320 |
| `raw.neso_demand_forecast` | 1,030 |

Matches the CSV row counts from Phase 0 exactly (86,400/4,320/etc.) — no
rows dropped or duplicated on load.

Spot-check per the brief's acceptance criterion — picked one row and
confirmed `source_payload` matches the source CSV row exactly:

```sql
SELECT settlement_date, settlement_period, fuel_type, generation_mw, source_payload
FROM raw.elexon_fuelhh LIMIT 1;
```

```
 settlement_date | settlement_period | fuel_type | generation_mw | source_payload
 2026-06-12      | 48                | BIOMASS   | 902           | {"dataset": "FUELHH", "fuelType": "BIOMASS", "startTime": "2026-06-12T22:30:00Z", "generation": 902, "publishTime": "2026-06-12T23:00:00Z", "settlementDate": "2026-06-12", "settlementPeriod": 48}
```

Typed columns and JSONB payload agree. `SELECT count(*) FROM
raw.elexon_fuelhh` returns 86,400 (brief's acceptance target was "~87,360"
— close, the small difference is just this run's actual 20-fuel-type ×
90-day × 48-period math rather than the brief's placeholder estimate).

## Nothing unexpected here

Unlike Phase 0 (which turned up two real API gotchas), Phase 1 went
exactly to plan — schemas and loader worked on the first try because the
CSV shapes were already known precisely from writing the ingestion
scripts in Phase 0.
