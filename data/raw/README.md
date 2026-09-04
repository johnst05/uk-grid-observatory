# Sample raw data

Real data pulled from the live Elexon BMRS and NESO APIs on 2026-09-04, via
`ingestion/elexon_ingest.py --days 90` and `ingestion/neso_ingest.py --days 90`.
Committed to the repo so the project shows real data on GitHub rather than
requiring a fresh API pull just to explore it.

| File | Rows | Source | Notes |
|---|---|---|---|
| `elexon_fuelhh_2026-06-06_2026-09-03.csv` | 86,400 | Elexon FUELHH | 90 days x 48 settlement periods x 20 fuel types, half-hourly outturn generation |
| `elexon_demand_outturn_2026-06-06_2026-09-03.csv` | 4,320 | Elexon `/demand/outturn` | 90 days x 48 periods, INDO + ITSDO |
| `elexon_windfor_snapshot_20260904T234421Z.csv` | 73 | Elexon WINDFOR | a single rolling-forecast snapshot (see below -- this is why it's a snapshot, not a range) |
| `neso_generation_mix_2026-06-06_2026-09-03.csv` | 4,320 | NESO historic generation mix | 90 days x 48 half-hours, independent cross-check of outturn generation by fuel |
| `neso_demand_forecast_2026-06-06_2026-09-03.csv` | 1,030 | NESO day-ahead demand forecast | days-ahead=1, multiple cardinal points per day |

## Why the date ranges differ

- FUELHH, demand outturn, and NESO generation mix all cover the same
  trailing 90-day window (2026-06-06 to 2026-09-03) because all three have
  a real historical archive that can be queried by date range.
- WINDFOR does **not** have a historical archive. Querying it with a past
  `settlementDateFrom`/`To` does not return historical forecasts -- it just
  returns whatever the *current* rolling forecast horizon is (roughly the
  next ~36 hours, in hourly steps). So there is only ever one meaningful
  pull: "whatever WINDFOR says right now." Building up real forecast
  history requires snapshotting WINDFOR repeatedly over time -- that's what
  Phase 5's scheduled refresh does (see `docs/refresh_schedule.md`).
