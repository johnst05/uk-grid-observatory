---
tags: [uk-grid-observatory, code-documentation, reference]
project: "[[UK Grid Observatory]]"
date: 2026-09-05
type: full-code-reference
---

# UK Grid Observatory — Full Code Documentation

This is a complete, file-by-file, line-by-line walkthrough of every piece
of code in the repository, as it stands after Phases 0–6. It's a
companion to [[REPO_COMPLETION]] (status/roadmap) and
`docs/build-log/` (the dated narrative of *why* each decision was made,
including the gotchas discovered along the way). This document is the
*what* and *how*; the build log is the *why* and *when*. Read both for
the full picture.

## Repository map

```
.env.example                          Template for local secrets/config
.gitignore                            What git deliberately ignores
docker-compose.yml                    Postgres 16 service definition
requirements.txt                      Python dependencies
README.md                             Project overview, setup, results
REPO_COMPLETION.md                    Phase status + roadmap

.github/workflows/refresh.yml         Optional GitHub Action for the daily refresh

sql/raw/001_create_raw_tables.sql         Raw-layer schema (5 tables)
sql/staging/001_create_staging_tables.sql Staging-layer schema (4 tables)
sql/clean/001_create_clean_tables.sql     Clean-layer view (window functions)

ingestion/common.py                   Shared HTTP + file-path helpers
ingestion/elexon_ingest.py            Pulls Elexon BMRS data -> CSV
ingestion/neso_ingest.py              Pulls NESO CKAN data -> CSV
ingestion/load_raw.py                 Loads CSVs -> raw.* Postgres tables
ingestion/transform_staging.py        raw.* -> staging.* transform
ingestion/refresh.py                  Orchestrates the daily scheduled run

data/raw/README.md                    What's in the committed sample data
dashboard/README.md                   Power BI build guide
docs/refresh_schedule.md              How/why the scheduled refresh works
docs/build-log/*.md                   Dated narrative, one file per phase
```

Data flows in one direction through three Postgres schemas:

```
Elexon BMRS API ─┐                ┌─> staging ─┐
                  ├─> raw (JSONB) ─┤            ├─> clean (window functions) ─> Power BI
NESO CKAN API ────┘                └─> staging ─┘
```

---

## `.env.example`

```env
# Postgres connection (matches docker-compose.yml)
PGHOST=localhost
PGPORT=5432
PGDATABASE=grid_observatory
PGUSER=grid
PGPASSWORD=grid_dev_password

# Convenience DSN built from the above (used by SQLAlchemy scripts)
DATABASE_URL=postgresql://grid:grid_dev_password@localhost:5432/grid_observatory

# Public API bases
NESO_API_BASE=https://api.neso.energy/api/3/action
ELEXON_API_BASE=https://data.elexon.co.uk/bmrs/api/v1
```

A template for the real `.env` file, which is git-ignored (never
committed — it's where real credentials would go in a non-toy
deployment, even though this project's default password is just a local
dev placeholder). Every value here matches `docker-compose.yml`'s service
definition exactly, so copying this file as-is to `.env` and running
`docker compose up` "just works" with no edits needed. `DATABASE_URL` is
a single-string convenience form of the five `PG*` variables, kept in
sync by hand (there's no code that derives one from the other) — used
wherever a tool expects one connection string (e.g. `psql "$DATABASE_URL"`)
rather than five separate env vars.

## `.gitignore`

```gitignore
.env
__pycache__/
*.pyc
.venv/
venv/
*.log
logs/

# Sample raw data IS intentionally tracked so the repo shows real data on
# GitHub -- do not add data/raw/ here.
```

- `.env` — the real secrets file, never committed.
- `__pycache__/`, `*.pyc` — Python bytecode caches, regenerated locally,
  never meaningful to commit.
- `.venv/`, `venv/` — local virtualenv directories, if someone creates one.
- `*.log`, `logs/` — `ingestion/refresh.py`'s operational log output
  (`logs/refresh.log`) — runtime noise, not source.
- The trailing comment is a deliberate guardrail: it exists so that a
  future edit doesn't accidentally add `data/raw/` to this file, since
  the whole point of that folder (per the project brief) is to show real,
  committed sample data on GitHub rather than requiring a fresh API pull
  just to explore the repo.

## `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16
    container_name: grid_observatory_db
    environment:
      POSTGRES_DB: grid_observatory
      POSTGRES_USER: grid
      POSTGRES_PASSWORD: grid_dev_password
    ports:
      - "5432:5432"
    volumes:
      - grid_observatory_pgdata:/var/lib/postgresql/data

volumes:
  grid_observatory_pgdata:
```

One service, `db`, running the official `postgres:16` image.
`POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` are Postgres's own
first-boot environment variables — the official image's entrypoint script
reads these and creates that database/role automatically the first time
the container starts with an empty data directory. Port `5432` is
published straight through to the host at the same port number, matching
`.env.example`'s `PGPORT`. The named volume `grid_observatory_pgdata` is
mounted at Postgres's data directory so the database survives a
`docker compose down`/`up` cycle (only `docker compose down -v` would
actually delete the data).

> Note from the build log: the sandbox this project was built in had no
> running Docker daemon, so Postgres was actually started via the host's
> own `pg_ctlcluster` instead, with the role/database created by hand to
> match this file's values exactly. `docker compose up -d` is the
> intended way to run this for real; the manual steps were a
> sandbox-specific substitute, not a different design.

## `requirements.txt`

```
requests>=2.31
pandas>=2.2
psycopg2-binary>=2.9
SQLAlchemy>=2.0
python-dotenv>=1.0
tenacity>=8.2
```

- `requests` — HTTP calls to the Elexon and NESO APIs.
- `pandas` — CSV read/write and DataFrame manipulation in every
  ingestion/loading script.
- `psycopg2-binary` — the Postgres driver used directly (not through an
  ORM) for all database access.
- `SQLAlchemy` — listed per the original project brief for
  connection-string-style database access; not currently imported by any
  script (all DB access goes through raw `psycopg2` connections and
  cursors instead, which turned out to be all that was needed for
  straight `INSERT`/`SELECT` work with no ORM-mapped models).
- `python-dotenv` — loads `.env` into `os.environ` at the top of
  `common.py` and `load_raw.py`.
- `tenacity` — the retry decorator wrapping every outbound HTTP call in
  `common.http_get_json`.

---

# SQL layer

## `sql/raw/001_create_raw_tables.sql`

Creates the `raw` schema and five tables. Every raw table follows the
same pattern: a `BIGSERIAL` surrogate key, a handful of typed columns
pulled out of the API response for filtering/joining, a `source_payload
JSONB NOT NULL` column holding the *entire* original record (so any row
can always be audited back to exactly what the API returned), and an
`ingested_at TIMESTAMPTZ DEFAULT now()` stamp.

**`raw.elexon_fuelhh`** — half-hourly outturn generation by fuel type
from Elexon's FUELHH dataset.
- `settlement_date DATE`, `settlement_period SMALLINT` — which half-hour
  this row is for (UK settlement calendar: 48 periods/day nominally).
- `fuel_type TEXT` — Elexon's BM-unit-level fuel code (e.g. `CCGT`,
  `WIND`, `NUCLEAR`, or an interconnector code like `INTFR`).
- `generation_mw NUMERIC` — metered generation in MW for that fuel type
  and period.
- `publish_time` / `start_time TIMESTAMPTZ` — when Elexon published this
  figure, and the half-hour period's own start time.
- Indexed on `(settlement_date, settlement_period, fuel_type)` since
  every downstream query filters or groups by this combination.

**`raw.elexon_windfor`** — Elexon's rolling wind generation forecast.
- No `settlement_date`/`settlement_period` columns, unlike the other
  tables — WINDFOR's own data model is a rolling hourly horizon keyed by
  `start_time`, not a settlement period; converting to settlement periods
  happens later, in the staging transform.
- `publish_time` — critically important here: since the same forecast
  value can be re-fetched by repeated snapshots (see `refresh.py`),
  `publish_time` is what staging's `DISTINCT ON` dedup uses to tell "two
  snapshots of the identical forecast" from "a genuinely revised
  forecast."
- Indexed on `(start_time, publish_time)`.

**`raw.elexon_demand_outturn`** — half-hourly demand outturn from the
`/demand/outturn` endpoint (not `/datasets/INDO` — see the Gotchas
section of the README for why).
- `demand_mw` — Elexon's `initialDemandOutturn` (INDO) figure.
- `itsdo_mw NUMERIC` (nullable) — Elexon's
  `initialTransmissionSystemDemandOutturn` (ITSDO) figure, captured
  because the same API call returns it for free alongside INDO.

**`raw.neso_demand_forecast`** — NESO's "Historic Day Ahead Demand
Forecasts" CKAN resource.
- `days_ahead SMALLINT` — how many days ahead this forecast was made
  (this project always queries `days_ahead = 1`).
- `target_date DATE` — the date being forecast.
- `forecast_demand_mw`, `cardinal_point`, `cp_type` — the forecast value
  and which named point in the day it's for (e.g. overnight minimum,
  evening peak — NESO's own vocabulary, not settlement periods).
- `forecast_timestamp` — when this particular forecast was made; used
  the same way `publish_time` is used for the Elexon tables, to dedupe
  revisions down to the latest one in staging.

**`raw.neso_generation_mix`** — NESO's "Historic GB Generation Mix" CKAN
resource, an independent (non-Elexon) measurement of actual generation.
- `datetime TIMESTAMPTZ` — half-hourly timestamp (stored as UTC by
  Postgres's column type, though the source values are naive/local — see
  the staging transform section for how this is actually interpreted).
- One nullable `NUMERIC` column per fuel: `gas_mw`, `coal_mw`,
  `nuclear_mw`, `wind_mw`, `wind_embedded_mw`, `hydro_mw`, `imports_mw`,
  `biomass_mw`, `other_mw`, `solar_mw`, `storage_mw` — this table is
  intentionally *wide* (one column per fuel), unlike the *long* shape
  (one row per fuel type) that `elexon_fuelhh` and staging use; the
  unpivot from wide to long happens in the staging transform.
- `generation_mw`, `carbon_intensity` — NESO's own totals, kept for
  completeness even though this project's analysis doesn't currently use
  them.

## `sql/staging/001_create_staging_tables.sql`

Creates the `staging` schema and four tables — typed, deduplicated, one
row per real-world fact, always including a `source` column so the same
kind of fact from Elexon and NESO can coexist and be compared without
colliding on primary key.

**`staging.generation_outturn`** — `PRIMARY KEY (settlement_date,
settlement_period, fuel_type, source)`. Populated from both
`raw.elexon_fuelhh` (`source='elexon'`) and `raw.neso_generation_mix`
(`source='neso'`, after being unpivoted from wide to long).

**`staging.generation_forecast`** — same key shape as
`generation_outturn`, so the two can be joined directly. Currently only
ever populated with `source='elexon'`, `fuel_type='WIND'` (from WINDFOR)
— there is no other generation forecast source in this project.

**`staging.demand_outturn`** — `PRIMARY KEY (settlement_date,
settlement_period, source)` — no `fuel_type`, since demand isn't
fuel-specific. Populated from `raw.elexon_demand_outturn`.

**`staging.demand_forecast`** — `PRIMARY KEY (target_date, days_ahead,
cardinal_point, source)`. Deliberately **not** on the settlement-period
grain the other three tables share — NESO's day-ahead forecast is
published at named cardinal points in the day (overnight minimum,
evening peak, etc.), which don't line up one-to-one with half-hour
settlement periods, so forcing this table onto that grain would either
lose information or require inventing a mapping that doesn't really
exist.

## `sql/clean/001_create_clean_tables.sql`

Creates the `clean` schema and one object: the view
`clean.forecast_vs_outturn`. It's a view rather than a materialized
table — cheap enough to recompute on every query at this data volume, and
it means new WINDFOR snapshots (from `refresh.py`) show up in the
analysis immediately with no separate "refresh the mart" step.

**The `joined` CTE**: an inner `JOIN` between `staging.generation_outturn`
(aliased `o`) and `staging.generation_forecast` (aliased `f`) on all four
key columns — `settlement_date`, `settlement_period`, `fuel_type`, *and*
`source`. Including `source` in the join condition is a deliberate
methodological choice: it guarantees a forecast is only ever compared
against an outturn figure from the *same* provider's own pipeline
(currently, Elexon vs Elexon), never silently mixed with a NESO-sourced
outturn number that was produced by a different measurement methodology.
`divergence_mw` is computed here as `outturn_mw - forecast_mw` — positive
means outturn exceeded the forecast (under-forecast), negative means
outturn fell short (over-forecast).

**The outer `SELECT`** passes through the joined columns and adds four
window-function columns:

- `rolling_avg_7d_mw` / `rolling_avg_30d_mw` — `AVG(divergence_mw) OVER
  (PARTITION BY fuel_type ORDER BY settlement_date RANGE BETWEEN INTERVAL
  '6 days'/'29 days' PRECEDING AND CURRENT ROW)`. Using `RANGE` over a
  `DATE`-typed `ORDER BY` column (rather than `ROWS`) makes this a true
  trailing *calendar* window — "the last 7 days," not "the last 7 rows" —
  which stays correct even if some settlement periods are missing on a
  given day. Partitioned by `fuel_type` so each fuel's rolling average is
  computed independently.
- `worst_miss_rank` — `RANK() OVER (ORDER BY ABS(divergence_mw) DESC)`,
  with **no** `PARTITION BY` — this is a single global ranking across all
  rows (all fuel types, if more than one ever has both forecast and
  outturn data), matching the brief's literal specification.
- `dod_delta_mw` — `divergence_mw - LAG(divergence_mw, 48) OVER
  (PARTITION BY fuel_type ORDER BY settlement_date, settlement_period)`.
  The `48` offset (not `1`) is the key design choice here: with
  half-hourly data, the immediately preceding row (`LAG(..., 1)`) is 30
  minutes earlier, not a day earlier — offsetting by 48 rows instead
  compares each period to the *same* settlement_period exactly one
  standard (48-period) day before. The two DST clock-change days per year
  will be off by one period under this scheme; noted as a known,
  accepted simplification rather than something this view handles.

---

# Python ingestion layer

All scripts in `ingestion/` are run as standalone scripts from within the
`ingestion/` directory (e.g. `python3 elexon_ingest.py`, or
`python3 ingestion/elexon_ingest.py` from the repo root — both work,
since `common.py` computes `REPO_ROOT` relative to its own file location,
not the working directory). They all import from `common.py` for shared
plumbing, and several import from each other (`transform_staging.py`
imports `load_raw.get_connection`; `refresh.py` imports functions from
`elexon_ingest`, `neso_ingest`, and `load_raw`).

## `ingestion/common.py`

The shared foundation every other ingestion script builds on.

- `load_dotenv()` — called at import time, so any script that imports
  `common` (directly or transitively) automatically has `.env` loaded
  into `os.environ` before it does anything else.
- `REPO_ROOT = Path(__file__).resolve().parent.parent` — resolves to the
  repository root regardless of the current working directory, since
  it's computed from `common.py`'s own file path (`ingestion/common.py`
  → parent is `ingestion/` → parent's parent is the repo root).
- `DATA_RAW_DIR = REPO_ROOT / "data" / "raw"` — the single source of
  truth for where CSVs get written and read from; every ingestion and
  loading script uses this constant rather than hardcoding a path.
- `ELEXON_API_BASE`, `NESO_API_BASE` — read from the environment (with
  sensible hardcoded fallbacks matching `.env.example`), so the actual
  API endpoint is configurable without editing code.
- `_RETRYABLE = retry_if_exception_type((requests.exceptions.RequestException,))`
  — a tenacity predicate matching any `requests` exception (connection
  errors, timeouts, HTTP error status raised via `raise_for_status()`),
  used by the retry decorator below.
- `http_get_json(url, params=None)` — the single choke point every API
  call in this project goes through. Decorated with
  `@retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30), retry=_RETRYABLE)`:
  up to 5 attempts, exponential backoff starting at 1 second and capping
  at 30 seconds between attempts, and `reraise=True` means that if all 5
  attempts fail, the *original* exception propagates (rather than
  tenacity's own wrapper exception), so calling code's error handling
  sees the real `requests` exception. Inside: a plain `requests.get`
  with a 30-second timeout, `raise_for_status()` to turn any 4xx/5xx into
  an exception (which triggers the retry), and returns the parsed JSON
  body.
- `daterange_chunks(start, end, max_days=7)` — a generator yielding
  `(chunk_start, chunk_end)` date pairs that together cover `[start,
  end]` inclusive, with no chunk spanning more than `max_days` days. This
  exists because different Elexon endpoints enforce different maximum
  date-range sizes per request (7 days for FUELHH, 28 for
  `/demand/outturn` — see `elexon_ingest.py`), so both call this same
  helper with a different `max_days`. Mechanically: `step =
  timedelta(days=max_days - 1)` (so a 7-day max means a 6-day step,
  giving exactly 7 inclusive days per chunk); the loop advances `cursor`
  to `chunk_end + 1 day` after each yield until it passes `end`.
- `save_csv(df, filename)` — ensures `data/raw/` exists
  (`mkdir(parents=True, exist_ok=True)`), writes the DataFrame there with
  `index=False` (no pandas row-number column in the CSV), and returns the
  full `Path` written to (callers use this return value — e.g.
  `refresh.py` collects these paths to delete them later once loaded).
- `utcnow_stamp()` — returns the current UTC time as a
  `YYYYMMDDTHHMMSSZ` string, used to give each WINDFOR snapshot a unique,
  sortable filename (`elexon_windfor_snapshot_<stamp>.csv`).

## `ingestion/elexon_ingest.py`

Pulls three Elexon datasets and writes each to a CSV in `data/raw/`.
This script only *fetches and saves* — it does not touch the database
(that's `load_raw.py`'s job).

- `fetch_fuelhh(start, end)` — loops `daterange_chunks(start, end,
  max_days=7)` (FUELHH's 7-day cap), calling `GET
  {ELEXON_API_BASE}/datasets/FUELHH?settlementDateFrom=...&settlementDateTo=...`
  for each chunk, turning each response's `"data"` array into a
  DataFrame, and concatenating all chunks into one DataFrame at the end.
  Returns an empty DataFrame if there were no chunks at all (i.e.
  `start > end`).
- `fetch_demand_outturn(start, end)` — identical structure to
  `fetch_fuelhh`, but hits `{ELEXON_API_BASE}/demand/outturn` and chunks
  at `max_days=28` (that endpoint's actual cap, discovered by testing —
  see the Gotchas section). This endpoint returns both INDO and ITSDO
  fields per row.
- `fetch_windfor_snapshot()` — a single, unparameterized `GET
  {ELEXON_API_BASE}/datasets/WINDFOR` call. No date range is passed at
  all, because passing one wouldn't change the result — WINDFOR always
  returns its current rolling forecast horizon regardless of what date
  range you ask for. This function's docstring states that directly:
  "there's only ever a 'latest snapshot' to fetch here."
- `main()` — the CLI entry point (`argparse`, one flag: `--days`,
  default 90). Computes `end = yesterday` and `start = end - (days - 1)`,
  so `--days 90` (the default) pulls a 90-day window ending yesterday
  (never including "today," since today's data is still incomplete).
  Calls all three fetch functions in sequence, printing a row count and
  save path after each, and saves each with a filename that encodes the
  date range (or timestamp, for WINDFOR) it covers.

## `ingestion/neso_ingest.py`

Pulls two NESO CKAN datastore resources.

- `GENERATION_MIX_RESOURCE_ID`, `DEMAND_FORECAST_RESOURCE_ID` — the two
  CKAN resource UUIDs this project reads from, found by searching NESO's
  package catalog (`package_search`) during Phase 0 and hardcoded here
  since resource IDs are stable identifiers, not something that needs to
  be re-discovered on every run.
- `RATE_LIMIT_SLEEP_SECONDS = 31` — NESO's API is observed to allow
  roughly 2 requests/minute; 31 seconds between calls keeps this script
  comfortably under that.
- `_sql_query(sql)` — the low-level helper every fetch function calls:
  `GET {NESO_API_BASE}/datastore_search_sql?sql=<sql>`, then builds a
  DataFrame from `payload["result"]["records"]`. This is CKAN's
  "run a SQL SELECT against this resource" action — the resource UUID is
  used as if it were a table name, in double quotes.
- `fetch_generation_mix(start, end_exclusive)` — builds
  `SELECT * FROM "<resource_id>" WHERE "DATETIME" >= '<start>' AND
  "DATETIME" < '<end_exclusive>' ORDER BY "DATETIME"` and runs it via
  `_sql_query`. Column names are double-quoted, which is not optional —
  the docstring and README both document that unquoted column names get
  lower-cased by Postgres (CKAN's datastore is backed by Postgres) and
  the query then fails with `column "datetime" does not exist`, since the
  actual column is `DATETIME` (mixed/upper case).
- `fetch_demand_forecast(start, end, days_ahead=1)` — same pattern,
  filtering `"DAYSAHEAD" = <days_ahead>` and `"TARGETDATE"` between
  `start` and `end` inclusive.
- `main()` — CLI entry (`--days`, default 90). Computes the same
  yesterday-ending window as `elexon_ingest.py`. Fetches generation mix
  first, saves it, **sleeps `RATE_LIMIT_SLEEP_SECONDS`**, then fetches
  the demand forecast and saves it — the sleep exists specifically to
  keep these two sequential calls within NESO's rate limit.

## `ingestion/load_raw.py`

Loads the CSVs sitting in `data/raw/` into the `raw.*` Postgres tables.
This is the file that was revised mid-project (see the build log for
Phase 5) to add idempotency — the version documented here is the current,
fixed one.

- `_clean(value)` — maps a float `NaN` to `None`; used so a missing value
  in a CSV lands as SQL `NULL` inside the JSONB payload rather than the
  literal string `"NaN"` (which `json.dumps` would otherwise produce from
  a raw pandas `NaN`).
- `_row_to_payload(row)` — `json.dumps` of the entire row dict, with
  every value passed through `_clean` first. This is what becomes each
  raw table's `source_payload` column — the complete, original record.
- `ensure_loaded_files_table(conn)` — `CREATE TABLE IF NOT EXISTS
  raw._loaded_files (filename TEXT PRIMARY KEY, loaded_at TIMESTAMPTZ
  NOT NULL DEFAULT now())`, committed immediately. This is the
  idempotency ledger: a record of which source CSV filenames have
  already been loaded, so re-running the loader (as the daily scheduled
  refresh does) doesn't re-insert the same file's rows as duplicates —
  raw itself has no unique constraint that could catch that on its own,
  since it's intentionally an append-only audit log with no concept of
  "this fact already exists."
- `_already_loaded(conn, filenames)` — `SELECT filename FROM
  raw._loaded_files WHERE filename = ANY(%s)`, returning the subset of
  the given filenames that are already recorded, as a Python `set`.
- `_mark_loaded(conn, filenames)` — bulk-inserts the given filenames into
  the ledger via `psycopg2.extras.execute_values`, with `ON CONFLICT DO
  NOTHING` (harmless if a filename somehow got marked already).
- `_load_csvs(conn, pattern)` — the core idempotency logic: globs
  `DATA_RAW_DIR` for `pattern`, calls `_already_loaded` to find which of
  those files are already in the ledger, filters them out, and only
  reads (`pd.read_csv`) the genuinely new ones. Returns a tuple of
  `(DataFrame of new rows, list of new filenames)` — an empty DataFrame
  and empty list if there was nothing new. This is the function every
  `load_*` function calls first.
- `get_connection()` — builds a `psycopg2.connect(...)` call from the
  `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` environment
  variables (with fallback defaults matching `.env.example`), used by
  every script that touches the database.
- `load_fuelhh`, `load_demand_outturn`, `load_windfor`,
  `load_neso_generation_mix`, `load_neso_demand_forecast` — one function
  per raw table, each following the identical pattern:
  1. Call `_load_csvs(conn, "<pattern>")` to get new rows + filenames.
  2. If the DataFrame is empty, return `0` immediately.
  3. Build a list of tuples, one per row, matching that table's column
     order exactly, always ending with `_row_to_payload(r)` for
     `source_payload`.
  4. Bulk-insert with `psycopg2.extras.execute_values` (a single
     multi-row `INSERT` statement rather than one round-trip per row —
     the reason this can load 86,400 rows in well under a second).
  5. Call `_mark_loaded(conn, filenames)` so the ledger reflects this
     load.
  6. `conn.commit()` and return the row count.

  The column-mapping details worth noting per function: `load_fuelhh`
  reads `settlementDate`/`settlementPeriod`/`fuelType`/`generation`
  (Elexon's camelCase field names) directly from the CSV. `load_windfor`
  has no settlement fields at all — just `publishTime`, `startTime`,
  `generation`. `load_neso_generation_mix` and
  `load_neso_demand_forecast` read NESO's upper-case field names
  (`DATETIME`, `GAS`, `TARGETDATE`, etc.) via `.get(...)` (rather than
  `[...]`) for the optional/nullable columns, so a missing column in an
  older CSV wouldn't crash the load.
- `LOADERS` — a dict mapping table-name strings to their loader
  functions, used by both `main()`'s `--only` flag and by
  `refresh.py` (`load_raw.LOADERS.items()`) to iterate all five loaders
  generically.
- `main()` — CLI entry (`--only`, repeatable, restricts to specific
  tables; default is all of them). Opens one connection, calls
  `ensure_loaded_files_table` once, then calls each target loader in
  turn, printing the row count inserted.

## `ingestion/transform_staging.py`

The raw → staging transform. Structurally different from the other
scripts: instead of building SQL dynamically in Python, it defines five
multi-line SQL string constants and executes them via a single shared
connection — the actual transform logic lives in SQL, not Python.

- `FUELHH_TO_STAGING_SQL` — `INSERT INTO staging.generation_outturn ...
  SELECT DISTINCT ON (settlement_date, settlement_period, fuel_type,
  source) ... FROM raw.elexon_fuelhh ORDER BY ..., publish_time DESC`.
  `DISTINCT ON` in Postgres keeps the first row per the `DISTINCT ON`
  columns *as encountered in the query's sort order* — because the
  `ORDER BY` ends with `publish_time DESC`, the row kept for each
  `(date, period, fuel_type, source)` combination is always the one with
  the latest `publish_time`, which is exactly the dedup rule this project
  uses everywhere.
- `NESO_GENMIX_TO_STAGING_SQL` — the most structurally complex of the
  five. An inner subquery unpivots `raw.neso_generation_mix` from wide to
  long using `unnest()` on two parallel arrays — one of fuel-type name
  literals (`ARRAY['GAS','COAL','NUCLEAR','WIND','WIND_EMB','HYDRO',
  'IMPORTS','BIOMASS','OTHER','SOLAR','STORAGE']`) and one of the
  corresponding column values (`ARRAY[gas_mw, coal_mw, nuclear_mw, ...]`)
  — `unnest()` on two arrays of equal length in the same `SELECT`
  produces one output row per array position, pairing element *i* of one
  array with element *i* of the other, which is exactly "turn 11 columns
  into 11 rows, each labeled with which column it came from." In that
  same subquery, `settlement_period` is computed directly from
  `datetime`'s hour and minute
  (`(EXTRACT(HOUR...)*2 + EXTRACT(MINUTE...)/30)::int + 1`) — no
  timezone conversion is applied here, because NESO's `datetime` values
  are already naive UK-local clock time (verified during Phase 2 by spot
  checking real values). The outer `SELECT DISTINCT ON` then dedupes and
  inserts exactly as `FUELHH_TO_STAGING_SQL` does, with `source='neso'`
  and a `WHERE generation_mw IS NOT NULL` filter (so a genuinely missing
  reading for one fuel on one half-hour doesn't insert a fake zero-like
  row).
- `WINDFOR_TO_STAGING_SQL` — the second most complex. WINDFOR's
  `start_time` is hourly and UTC; everything it needs to join against is
  half-hourly and UK-local. The subquery: `CROSS JOIN LATERAL (SELECT
  (w.start_time AT TIME ZONE 'Europe/London') AS dt)` converts each row's
  UTC `start_time` into UK local time (correctly handling the BST/GMT
  offset via Postgres's own timezone database, verified during Phase 2
  against a real 20:00 UTC value converting to 21:00 local during BST).
  `CROSS JOIN generate_series(0, 1) AS half(i)` then duplicates every row
  into two, with `i = 0` and `i = 1`; adding `half.i * interval '30
  minutes'` to the local timestamp before computing `settlement_date`/
  `settlement_period` means each hourly forecast value is written out as
  both of the half-hour settlement periods it actually covers, carrying
  the same `forecast_mw` value to both. `fuel_type` is hardcoded to
  `'WIND'` and `source` to `'elexon'`, since that's the only thing
  WINDFOR ever represents.
- `DEMAND_OUTTURN_TO_STAGING_SQL` — the simplest of the five: a direct
  `DISTINCT ON` dedup of `raw.elexon_demand_outturn` into
  `staging.demand_outturn`, no grain conversion needed since both tables
  already share the settlement-period grain.
- `DEMAND_FORECAST_TO_STAGING_SQL` — dedupes `raw.neso_demand_forecast`
  into `staging.demand_forecast`, keyed on `(target_date, days_ahead,
  cardinal_point, source)` with the latest `forecast_timestamp` winning
  ties, and a `WHERE cardinal_point IS NOT NULL` guard (defensive; in
  practice no row has ever had a null cardinal_point, but the staging
  table's primary key includes this column, so a null would otherwise
  violate the not-null constraint on insert).
- `STEPS` — a list of `(label, truncate_sql_or_None, insert_sql)` tuples
  driving `main()`. Every staging table is `TRUNCATE`d before being
  repopulated *except* that the second entry
  (`NESO_GENMIX_TO_STAGING_SQL`) has `truncate_sql=None` — because it
  inserts into the *same* table (`staging.generation_outturn`) that the
  first step (`FUELHH_TO_STAGING_SQL`) already populated, and truncating
  again here would wipe out the Elexon rows just inserted. This is the
  one place in the file where step order matters: FUELHH must run before
  the NESO generation-mix step for this reason.
- `main()` — opens a connection, iterates `STEPS` running the optional
  truncate then the insert for each, prints
  `f"{label}: inserted {cur.rowcount} rows"` after each insert (using the
  cursor's own row count, which for an `INSERT` reflects exactly how many
  rows were written), commits once at the end (all five steps run inside
  one transaction — if any statement fails, nothing from this run is
  applied).

## `ingestion/refresh.py`

The Phase 5 orchestrator — the script meant to run once a day via cron,
Task Scheduler, or the GitHub Action. Ties together everything above
into one command.

- `LOG_DIR = REPO_ROOT / "logs"`, created if missing. `logging.basicConfig`
  is set up with two handlers: a `FileHandler` writing to
  `logs/refresh.log` (git-ignored — operational output, not source) and
  a `StreamHandler` to stdout (so the same output is visible when run
  interactively or captured by cron/a CI runner's own log capture).
- `step(name, fn, *args, **kwargs)` — the error-isolation wrapper every
  individual action in this script goes through. Calls `fn(*args,
  **kwargs)` inside a `try`; on success, logs `"OK: {name}"` and returns
  the result; on *any* exception, logs the full traceback via
  `log.exception` and returns `None` rather than propagating — meaning
  one failing step (e.g. a NESO outage) never prevents the other,
  independent steps in the same run from executing.
- `ingest_latest_day()` — computes `yesterday = date.today() -
  timedelta(days=1)`, then, via `step(...)`, in order:
  1. Fetch yesterday's FUELHH (`fetch_fuelhh(yesterday, yesterday)`,
     a one-day range) and save it, if non-empty, appending the saved
     `Path` to a `transient_paths` list.
  2. Fetch yesterday's demand outturn, same pattern.
  3. **Snapshot WINDFOR** (`fetch_windfor_snapshot()`, no date
     parameters) and save it — but **do not** add this path to
     `transient_paths`; it's the one file type this function keeps
     permanently rather than marking for deletion later.
  4. Fetch yesterday's NESO generation mix
     (`fetch_generation_mix(yesterday, yesterday + 1 day)`, since that
     function's `end_exclusive` parameter needs the day *after*
     yesterday to include all of yesterday), save it, mark it transient.
  5. Sleep `RATE_LIMIT_SLEEP_SECONDS` (imported from `neso_ingest`) to
     respect NESO's rate limit before the next NESO call.
  6. Fetch yesterday's NESO demand forecast, save it, mark it transient.
  Returns `transient_paths` — everything except the WINDFOR snapshot.
- `load_and_transform()` — opens one connection via
  `load_raw.get_connection()`, calls `load_raw.ensure_loaded_files_table`,
  then iterates `load_raw.LOADERS.items()` calling each loader (wrapped
  in `step(...)`, so one table's load failing doesn't block the others)
  and logging the row count each returns. After the `with`/`finally`
  block closes the connection, it runs
  `ingestion/transform_staging.py` as a **separate subprocess**
  (`subprocess.run([sys.executable, ...], check=True, cwd=.../ingestion)`)
  rather than importing and calling its `main()` directly — this keeps
  the transform's own connection lifecycle (open, do work, close)
  completely independent of the loader's, and means the transform script
  can still be run and tested standalone with identical behavior.
- `cleanup_transient_files(paths)` — iterates the transient paths
  collected by `ingest_latest_day()` and deletes each
  (`path.unlink(missing_ok=True)`, so a file already gone for any reason
  doesn't raise), logging each removal. The rationale, straight from the
  docstring: everything in this list is re-fetchable from its source API
  for any past date, so once it's loaded into `raw` (which keeps the full
  payload as JSONB regardless), the landing CSV has no further purpose —
  keeping it would just make `data/raw/` grow by one file per source
  every single day, forever, cluttering a folder whose actual purpose is
  the one committed 90-day portfolio sample plus the (deliberately kept)
  WINDFOR snapshot history.
- `main()` — logs a start banner, calls `ingest_latest_day()` (capturing
  the transient paths), then `load_and_transform()`, then
  `cleanup_transient_files(transient_paths)`, then a completion banner.
  Note the strict ordering: cleanup only happens *after* the load step
  has run — deleting a transient file before confirming it was loaded
  would risk losing data if the load step failed.

## `.github/workflows/refresh.yml`

An optional, alternative way to run `ingestion/refresh.py` on a schedule,
for a setup where the project's Postgres is hosted somewhere reachable
from the public internet (GitHub Actions runners are fresh, throwaway
VMs — they cannot reach a database running on your own machine or behind
a local Docker Compose setup).

- Triggers: `schedule: cron: "0 6 * * *"` (06:00 UTC daily) plus
  `workflow_dispatch: {}` (a manual "Run workflow" button in GitHub's UI,
  useful for testing without waiting for the schedule).
- Steps: checkout the repo, set up Python 3.11, `pip install -r
  requirements.txt`, then run `python refresh.py` with its working
  directory set to `ingestion/` (so its relative imports resolve the same
  way they do when run locally) and its Postgres connection details
  supplied via GitHub Actions **secrets** (`DATABASE_URL`, `PGHOST`,
  `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`) rather than a committed
  `.env` file.
- A final step uploads `logs/refresh.log` as a workflow artifact
  (`if: always()`, so this happens even if the refresh step itself
  failed) — the same log file `refresh.py` writes locally, made visible
  in GitHub's UI for a run that happened on a runner rather than a local
  machine.

---

## How it all fits together, end to end

1. **`elexon_ingest.py` / `neso_ingest.py`** (once, for the initial
   sample; or automatically via `refresh.py` daily) hit the live APIs and
   write CSVs into `data/raw/`.
2. **`load_raw.py`** reads whichever of those CSVs it hasn't already
   recorded in `raw._loaded_files`, and bulk-inserts them into the five
   `raw.*` tables, each row carrying its full original payload as JSONB.
3. **`transform_staging.py`** truncates and rebuilds the four
   `staging.*` tables from whatever is currently in `raw.*` — deduping
   to one row per real-world fact (latest `publish_time`/
   `forecast_timestamp` wins), reconciling grain differences (NESO's wide
   generation-mix table unpivoted to long; WINDFOR's hourly UTC data
   expanded to half-hourly UK-local periods), and tagging every row with
   which provider (`source`) it came from.
4. **`clean.forecast_vs_outturn`** (a SQL view, not a script) joins
   `staging.generation_outturn` and `staging.generation_forecast` live,
   computing divergence and the four window-function columns on every
   query — so it's always current with whatever staging holds, no
   refresh step of its own required.
5. **`refresh.py`**, run daily, is steps 1–3 wired together for exactly
   "yesterday," plus a WINDFOR snapshot (step 1's forecast equivalent,
   since WINDFOR has no history to backfill), with idempotent loading and
   automatic cleanup of the now-redundant transient CSVs.
6. **Power BI** (not automated — a human step, documented in
   `dashboard/README.md`) connects live to `clean.forecast_vs_outturn`
   (or a CSV export of it) to visualize the result.

Every gotcha, false start, and verification step that led to this final
shape — the `/datasets/INDO` trap, the WINDFOR rolling-forecast
limitation, the NESO SQL quoting requirement, the idempotency bug found
and fixed mid-project, the BST timezone conversion verified against a
real value — is narrated in full, with the actual commands and output run
at the time, across the six files in `docs/build-log/`.
