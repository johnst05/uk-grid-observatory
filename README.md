# UK Grid Observatory

When National Grid ESO (NESO) and Elexon publish forecasts for UK
electricity generation -- especially wind -- how much does that forecast
actually diverge from what gets metered and settled after the fact?
Reported ≠ real, and the gap between them is where operational risk
(balancing costs, price spikes, grid stress) actually lives.

This project is a small but complete data pipeline that answers that
question with real data: it ingests outturn and forecast generation from
two independent public UK energy data sources, lands them in Postgres
through a raw -> staging -> clean warehouse, computes forecast-vs-outturn
divergence with SQL window functions, and visualizes the result.

## Status

Under active build. See [`REPO_COMPLETION.md`](REPO_COMPLETION.md) for the
phase-by-phase plan and current progress, and
[`docs/build-log/`](docs/build-log/) for a detailed, dated log of decisions
made and gotchas discovered along the way.

## Architecture

```
Elexon BMRS API ───┐                 ┌──> staging ──> clean (window fns) ──> Power BI
                    ├──> raw (JSONB) ─┤
NESO CKAN API ──────┘                 └──> staging ──┘
```

- **raw** -- exactly what each API returned, one row per record, full
  payload kept as JSONB for audit. Immutable once written.
- **staging** -- typed, deduplicated to one row per (date, period, fuel
  type, source), so Elexon and NESO can be compared side by side.
- **clean** -- `forecast_vs_outturn`: divergence, rolling averages, and
  ranked worst misses, computed via SQL window functions.

## Data sources

| Source | What | Endpoint |
|---|---|---|
| Elexon BMRS | FUELHH (half-hourly outturn generation by fuel) | `/datasets/FUELHH` |
| Elexon BMRS | WINDFOR (rolling wind generation forecast) | `/datasets/WINDFOR` |
| Elexon BMRS | INDO/ITSDO (half-hourly demand outturn) | `/demand/outturn` |
| NESO | Historic GB Generation Mix (independent outturn cross-check) | CKAN datastore, resource `f93d1835-...` |
| NESO | Historic Day Ahead Demand Forecast | CKAN datastore, resource `9847e7bb-...` |

Sample data already pulled from these live APIs is committed under
[`data/raw/`](data/raw/) -- see that folder's README for row counts and an
important caveat about WINDFOR (it has no historical archive; see
"Gotchas" below).

## Setup

```bash
cp .env.example .env          # edit if you change ports/credentials
docker compose up -d          # starts Postgres 16 on localhost:5432
pip install -r requirements.txt

psql "$DATABASE_URL" -f sql/raw/001_create_raw_tables.sql
psql "$DATABASE_URL" -f sql/staging/001_create_staging_tables.sql
```

Then pull fresh data (optional -- `data/raw/` already has a 90-day sample):

```bash
python3 ingestion/elexon_ingest.py --days 90
python3 ingestion/neso_ingest.py --days 90
python3 ingestion/load_raw.py
python3 ingestion/transform_staging.py
```

Then keep it current with a daily scheduled refresh (see
[`docs/refresh_schedule.md`](docs/refresh_schedule.md) for cron / GitHub
Actions / Task Scheduler options):

```bash
python3 ingestion/refresh.py
```

This matters more than it sounds: WINDFOR has no historical archive (see
Gotchas below), so real forecast-vs-outturn history only exists for
whatever days this has actually been run on.

## Gotchas discovered while building this

- **Elexon FUELHH** rejects any single request spanning more than 7 days.
- **Elexon `/demand/outturn`** rejects more than 28 days in one request --
  a different limit than FUELHH, on a different endpoint. The generic
  `/datasets/INDO` endpoint looks like it should behave like FUELHH but
  silently ignores date-range params and always returns just the latest
  settlement period; `/demand/outturn` is the endpoint that actually
  respects a date range for demand history.
- **Elexon WINDFOR is a rolling forecast only.** Querying it with a past
  `settlementDateFrom`/`To` does not return historical forecasts -- it
  returns whatever the *current* forecast horizon is. There is no
  historical WINDFOR archive. The only way to build up real forecast
  history is to snapshot WINDFOR repeatedly over time via a scheduled job.
- **NESO SQL column quoting:** column names in a `datastore_search_sql`
  query must be double-quoted (`"DATETIME"`, not `DATETIME`), or Postgres
  lower-cases them and the query fails with
  `column "datetime" does not exist`.
- **NESO `&format=csv`** is ignored on the `datastore_search_sql` action --
  it always returns JSON. Only the plain `datastore_search` action
  respects `format=csv`.
- **NESO rate limit:** roughly 2 requests/minute; the ingestion script
  sleeps between calls accordingly.

Full detail on how each of these was found is in
[`docs/build-log/`](docs/build-log/).

## Repository layout

```
ingestion/          Python scripts that pull from the APIs and write CSVs to data/raw/
sql/raw/            Raw-layer schema migrations
sql/staging/        Staging-layer schema migrations
sql/clean/          Clean/mart-layer schema + window-function views (Phase 3)
data/raw/           Sample data already pulled from the live APIs
dashboard/          Power BI file / exports (Phase 4)
docs/               Refresh-schedule docs and the build log
```
