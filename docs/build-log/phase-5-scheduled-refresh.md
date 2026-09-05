---
tags: [uk-grid-observatory, build-log, phase-5]
project: "[[UK Grid Observatory]]"
date: 2026-09-04
phase: 5
status: done
---

# Phase 5 — Scheduled refresh

## Found and fixed a real bug first: `load_raw.py` wasn't idempotent

Before writing the refresh job, realized `ingestion/load_raw.py` (Phase 1)
globs *all* CSVs matching a pattern in `data/raw/` every time it runs. A
daily scheduled job re-running that loader would re-insert the entire
90-day sample as duplicates every single day — raw has no unique
constraint to catch this (it's intentionally append-only and doesn't know
what a "duplicate fact" looks like).

Fixed by adding a `raw._loaded_files` ledger table (filename ->
loaded_at) and changing `_load_csvs` to only load files not already
recorded. Caught this **by actually running it twice** and comparing row
counts, not just by reasoning about it — the first "fix" attempt still
had to be tested to be trusted:

1. Added the ledger, ran `load_raw.py` once more (first run after adding
   the ledger, so everything looked "new" and got reloaded) → row counts
   doubled (172,800 FUELHH rows instead of 86,400). Caught immediately by
   checking counts, not assumed correct.
2. Truncated raw + the ledger, reloaded clean, ran a second time
   immediately after → confirmed `(no new files matching ..., skipping)`
   and 0 rows inserted on every table. *Then* trusted it.
3. Rebuilt staging + clean from the corrected raw data and re-verified
   the Phase 1/2/3 acceptance numbers still matched exactly (86,400 /
   133,920 / 6 rows respectively) before moving on.

## `ingestion/refresh.py`

Pulls yesterday's FUELHH, demand outturn, and NESO data; snapshots
WINDFOR; loads everything into raw; reruns the staging/clean transform.
Each step is independently try/excepted and logged (`logs/refresh.log`,
gitignored) so one source being briefly down doesn't take out the whole
run.

**Transient-file cleanup, added after noticing a design smell**: FUELHH /
demand outturn / NESO generation-mix / NESO demand-forecast are all
re-fetchable from their source APIs for any past date — once loaded into
`raw` (which keeps the full payload as JSONB), the landing CSV in
`data/raw/` serves no further purpose and would otherwise accumulate one
new file per source per day, forever, in a folder whose actual purpose
(per `data/raw/README.md`) is "the committed Phase 0 portfolio sample."
`refresh.py` deletes these after a successful load. **WINDFOR snapshots
are the one exception** — kept permanently, since they're the only record
that will ever exist of what the forecast said at that moment.

## Verified end-to-end, twice, in this session

First run (after the idempotency fix), against real "yesterday" data:

```
raw.elexon_fuelhh:          86,400 -> 87,360  (+960, a real overlapping-day repull)
staging.generation_outturn:  86,400 -> 86,400  (elexon rows -- overlap correctly deduped away)
raw.elexon_windfor:              73 -> 146     (2nd real snapshot)
clean.forecast_vs_outturn:        6 -> 6       (unchanged -- no new overlap yet, expected)
```

Second run, immediately after (testing idempotency + cleanup together):
FUELHH/demand/genmix/demand-forecast all correctly logged
`0 new rows` (same "yesterday" as the first run, so nothing new to load);
WINDFOR correctly loaded a 3rd real snapshot; all 4 transient CSVs were
deleted after load, leaving `data/raw/` exactly as it was before this
phase plus the accumulating WINDFOR snapshots.

## An honest limitation surfaced by testing twice in two minutes

`raw.elexon_windfor` now has 3 snapshots (219 rows) but only **1 distinct
`publish_time`** among them. Checked why: Elexon only republishes WINDFOR
on its own internal cadence (this snapshot's `publishTime` was fixed at
`23:30:00Z`) — calling the endpoint again 90 seconds later just returns
the same forecast again, not a new one. So these 3 test snapshots don't
actually represent 3 distinct forecast states; they're 3 identical reads
of the same one. This isn't a bug in the refresh job — it's the real
behavior of the upstream API, and it's exactly why Phase 5 has to run on
a real daily (or better, sub-daily but not sub-hourly) cadence over
actual elapsed time to be useful, not something that can be
"demonstrated" by calling it repeatedly in a test session. Recorded here
rather than implied otherwise.

## What's still manual

`.github/workflows/refresh.yml` is written but untested — it needs a
`DATABASE_URL` secret pointing at a Postgres instance reachable from
GitHub's runners (this sandbox's local Postgres isn't reachable from
GitHub Actions, so this couldn't be run for real in this session). The
cron one-liner in `docs/refresh_schedule.md` is what was actually
exercised, by running `ingestion/refresh.py` directly.
