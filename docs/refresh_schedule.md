# Refresh schedule

## Why this exists

Elexon WINDFOR has no historical archive (see the README's "Gotchas"
section and `docs/build-log/phase-0-foundation.md`): querying it with a
past date range just returns whatever the *current* rolling forecast
horizon is. The only way `clean.forecast_vs_outturn` ever accumulates
enough real forecast history to say anything general about wind forecast
accuracy is to snapshot WINDFOR **repeatedly, over real elapsed time**.
There's no way to backfill a missed day later — a day not snapshotted is
a day of forecast history gone for good. This is why Phase 5 is more
urgent than its position at the end of the brief's phase list suggests.

## What runs, and in what order

`ingestion/refresh.py`, once a day:

1. Fetch yesterday's FUELHH (outturn generation).
2. Fetch yesterday's demand outturn (INDO/ITSDO).
3. **Snapshot the current WINDFOR forecast** — the irreplaceable step.
4. Fetch yesterday's NESO generation mix (independent cross-check).
5. Fetch yesterday's NESO day-ahead demand forecast.
6. Load anything new into `raw.*` (idempotent — see below).
7. Rerun the raw -> staging -> clean transform.

Each step is wrapped so one source failing (an API being briefly down)
doesn't skip the others — a NESO outage on a given day shouldn't also
cost that day's Elexon pull, and vice versa. Logged to `logs/refresh.log`
(gitignored — this is operational log output, not something to commit).

## Idempotency

`ingestion/load_raw.py` keeps a `raw._loaded_files` ledger (filename ->
when it was loaded). Re-running the refresh twice in one day, or after a
partial failure, only loads files it hasn't seen before — it does not
re-insert the same day's data twice. This was verified directly: running
`load_raw.py` a second time with no new files logged
`(no new files matching ..., skipping)` for every table and inserted 0
rows.

Note this ledger is at the *file* level, not the *fact* level: pulling
the same day's FUELHH twice under two different filenames (which
`refresh.py` can legitimately do, since a settlement period gets
re-published with a later `publish_time` as more final data becomes
available) will load both files into `raw` — that's intentional, raw is
an audit trail of every real pull. The **staging** transform is what
actually deduplicates to one row per fact, always keeping the latest
`publish_time`. This was also verified directly: after a real refresh run
that re-pulled an overlapping day, `raw.elexon_fuelhh` grew from 86,400 to
87,360 rows (the honest audit trail), while `staging.generation_outturn`
stayed at exactly 86,400 elexon rows — the overlap was correctly collapsed
back down by `DISTINCT ON ... ORDER BY publish_time DESC`.

## Running it

### Cron (simplest, if this runs on a machine that's on)

```cron
# Daily at 06:00 -- well after WINDFOR/FUELHH have published for "yesterday"
0 6 * * * cd /path/to/uk-grid-observatory && /path/to/venv/bin/python ingestion/refresh.py
```

### GitHub Actions (`.github/workflows/refresh.yml`, included)

Runs on a daily cron trigger. **Requires a `DATABASE_URL` repository
secret pointing at a Postgres instance reachable from GitHub's runners** —
a GitHub Actions runner is a fresh, throwaway VM with no access to a
Postgres running on your own machine, so this only works with an
externally hosted database (a small managed Postgres instance, e.g. on
Supabase/Neon/RDS free tier). If you're running this project entirely
locally with `docker compose`, use cron instead — the workflow file is
there for whichever fits your actual setup, per the project brief.

### Windows Task Scheduler

Equivalent to the cron entry above: trigger daily at a fixed time, action
= `python.exe ingestion\refresh.py`, start-in = the repo root.

## Verified end-to-end

Ran `ingestion/refresh.py` for real in this session:

```
OK: fetch FUELHH (yesterday)              -> 960 new rows
OK: fetch demand outturn (yesterday)      -> 48 new rows
OK: snapshot WINDFOR                      -> 73 new rows (2nd real snapshot)
OK: fetch NESO generation mix (yesterday) -> 48 new rows
OK: fetch NESO demand forecast (yesterday)-> 10 new rows
OK: rerun staging + clean transform
```

`raw.elexon_windfor` now holds **2 real snapshots** taken ~13 minutes
apart in this session — proof the accumulation mechanism works, though
obviously not yet enough elapsed time to show a meaningful forecast
history. That takes this actually running daily, for real, going forward.
