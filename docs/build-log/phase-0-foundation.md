---
tags: [uk-grid-observatory, build-log, phase-0]
project: "[[UK Grid Observatory]]"
date: 2026-09-04
phase: 0
status: done
---

# Phase 0 — Foundation

## Context

Session started against a **completely empty** GitHub repo (no commits, no
branches at all — confirmed via `git ls-remote` and the GitHub API, which
returned `409 Git Repository is empty`). An earlier automated
[[Repo Completion Protocol]] run had already logged that finding in
`REPO_COMPLETION.md`. The user then supplied the full project brief and
asked to build it from scratch, in parallel with keeping detailed notes —
this file (and its siblings in `docs/build-log/`) is that documentation,
written in Obsidian-friendly Markdown since no live Obsidian connector was
available in this sandbox to write into a vault directly.

## Environment reality-check

Before writing any code, checked what the sandbox actually supports:

- **Outbound network**: works, via a policy-enforced proxy. Confirmed real
  HTTPS access to both `data.elexon.co.uk` and `api.neso.energy`.
- **Docker**: the `docker` CLI is present but the daemon isn't running
  (`no such file or directory` on `/var/run/docker.sock`) — no `docker
  compose up` possible here.
- **Postgres**: a local Postgres 16 cluster *is* installed
  (`pg_lsclusters` shows `16 main … down`), so the database itself can
  still be stood up without Docker in this environment — `docker-compose.yml`
  is written anyway since it's the intended way to run this outside the
  sandbox.
- **Power BI Desktop**: not installable here (Windows/macOS-only GUI app on
  a headless Linux box) — flagged now so Phase 4 doesn't get planned as if
  it could be finished in-session.

## What was built

- `README.md`, `requirements.txt`, `.env.example`, `docker-compose.yml`
  (Postgres 16, matches `.env.example`), `.gitignore`.
- `sql/raw/001_create_raw_tables.sql` — five raw tables, each with a
  `source_payload JSONB` audit column:
  `elexon_fuelhh`, `elexon_windfor`, `elexon_demand_outturn`,
  `neso_demand_forecast`, `neso_generation_mix`.
- `sql/staging/001_create_staging_tables.sql` — four staging tables:
  `generation_outturn`, `generation_forecast`, `demand_outturn`,
  `demand_forecast`. Each has a `source` column (`elexon`/`neso`) in its
  primary key so the same fact from two providers can coexist and be
  compared.
- `ingestion/common.py` — shared retrying HTTP GET (via `tenacity`) and a
  `daterange_chunks()` helper, since **two different endpoints turned out
  to have two different max-range limits** (see gotchas).
- `ingestion/elexon_ingest.py`, `ingestion/neso_ingest.py` — pull real data
  and write CSVs to `data/raw/`. Actually run against the live APIs (not
  mocked) — see [[#Real data pulled]] below.

## Design decisions worth remembering

- **`staging.generation_forecast` grain**: WINDFOR publishes *hourly*
  values (`startTime` steps of 1h), but outturn (`FUELHH`) is half-hourly
  (48 settlement periods/day). Decided the raw→staging transform (Phase 2)
  will carry each hourly WINDFOR value across both half-hour settlement
  periods it spans, so `generation_forecast` and `generation_outturn`
  share a grain and can be joined directly in Phase 3.
- **`staging.demand_forecast` grain deliberately does NOT match
  settlement periods.** NESO's day-ahead demand forecast is published at
  "cardinal points" (named points in the day like overnight minimum,
  evening peak) — not at every half-hour. Forcing it onto
  `(settlement_date, settlement_period)` would lose the cardinal-point
  structure for no real benefit, since the brief's window-function
  analysis (Phase 3) is scoped to *generation* divergence, not demand.
  Kept `demand_forecast` at its natural `(target_date, days_ahead,
  cardinal_point, source)` grain instead.
- **Raw `elexon_demand_outturn` table gained an `itsdo_mw` column** beyond
  what was originally sketched, because the real endpoint returns both
  INDO and ITSDO in the same payload for free — no reason to throw it
  away.

## Real data pulled

Ran both ingestion scripts against the live APIs for a 90-day trailing
window (2026-06-06 to 2026-09-03) plus one live WINDFOR snapshot. Numbers,
for the record:

| Dataset | Rows |
|---|---|
| Elexon FUELHH | 86,400 (90 days × 48 periods × 20 fuel types) |
| Elexon demand outturn (INDO+ITSDO) | 4,320 (90 × 48) |
| Elexon WINDFOR snapshot | 73 |
| NESO generation mix | 4,320 |
| NESO day-ahead demand forecast | 1,030 |

All committed under `data/raw/` (see that folder's own README for the
per-file breakdown and the WINDFOR date-range caveat).

## Gotchas found (the expensive way)

1. **Elexon FUELHH**: >7-day range → `400`, `"date range … must not exceed
   7 days"`. Matches what the brief already warned about.
2. **Elexon `/datasets/INDO` is a trap.** It looks exactly like FUELHH's
   generic dataset endpoint and accepts the same `settlementDateFrom`/`To`
   params *without erroring* — but it silently ignores them and always
   returns just the single latest settlement period. Spent a check finding
   this (first ingestion run returned 13 rows for a 90-day request when
   4,320 were expected). The actual endpoint for demand *history* is
   `/demand/outturn`, which returns both INDO and ITSDO and has its own,
   **different** range cap: **28 days**, not 7. This was not in the
   original brief and is new information for future sessions.
3. **Elexon WINDFOR has no historical archive**, confirmed directly:
   requesting a past date range just returns the current rolling horizon
   regardless. Exactly as the brief described — Phase 5's scheduled
   snapshot job is the only way to accumulate real forecast history.
4. **NESO `datastore_search_sql` column quoting**: confirmed —
   unquoted column names fail; double-quoted (`"DATETIME"`) works.
5. **NESO `_sql` action ignores `format=csv`** — always JSON. Not directly
   tested (didn't try `format=csv`) but not needed since `datastore_search_sql`
   already returns clean JSON records.
6. **NESO has no default row cap on `datastore_search_sql`** — a query
   returning 4,363 rows came back in one request with no `LIMIT` needed,
   unlike `datastore_search` (which defaults to 100). Only rate limiting
   (~2 req/min) requires pacing, not pagination, for the volumes this
   project needs.

## Open questions for later phases

- Phase 4 (Power BI) cannot be completed inside this sandbox — no Windows/
  macOS GUI environment. Plan is to get the clean-layer export and exact
  click-by-click build steps ready, and flag clearly that the `.pbix`
  itself needs a session with Power BI Desktop.
- Docker daemon isn't running here, so Phase 1 will start Postgres via the
  system's `pg_ctlcluster` rather than `docker compose up` — functionally
  equivalent, but worth noting since it deviates from the brief's
  suggested command.
