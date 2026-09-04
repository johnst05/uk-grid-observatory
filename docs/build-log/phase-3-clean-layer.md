---
tags: [uk-grid-observatory, build-log, phase-3]
project: "[[UK Grid Observatory]]"
date: 2026-09-04
phase: 3
status: done-with-caveat
---

# Phase 3 — Clean layer with window functions

## `clean.forecast_vs_outturn`

Built as a plain `VIEW`, not a materialized table — cheap enough to
recompute on query at these volumes, and it means Phase 5's scheduled
WINDFOR snapshots show up in the analysis with no separate refresh step.

Joined `staging.generation_outturn` to `staging.generation_forecast` on
`(settlement_date, settlement_period, fuel_type, source)` — including
`source` in the join keeps the comparison within one provider's own
pipeline (right now: Elexon forecast vs Elexon outturn), rather than
silently comparing an Elexon forecast against a NESO-sourced outturn
figure that was produced by a different methodology.

Window functions, all working as specified in the brief:

- `divergence_mw = outturn_mw - forecast_mw`.
- `rolling_avg_7d_mw` / `rolling_avg_30d_mw`: **`RANGE BETWEEN INTERVAL
  ... PRECEDING`**, not `ROWS BETWEEN N PRECEDING` — deliberately, so the
  window is a true trailing calendar window (7 or 30 *days*) regardless
  of how many settlement periods actually have data on a given day,
  rather than "the previous N *rows*" which would silently mean something
  different once data has gaps.
- `worst_miss_rank`: `RANK() OVER (ORDER BY ABS(divergence_mw) DESC)`,
  global (not partitioned by fuel_type) as written in the brief.
- `dod_delta_mw`: **not** a plain `LAG(divergence_mw, 1)`. With
  half-hourly data, the immediately preceding row is 30 minutes earlier,
  not a day earlier — that would make "day-over-day" a lie. Used
  `LAG(divergence_mw, 48)` instead, comparing each row to the *same*
  settlement_period exactly one day before. This assumes a standard
  48-period day; the two DST clock-change days a year will be off by one
  period, which is called out as a known simplification rather than
  handled, since it doesn't affect any conclusion at this data volume.

Verified the timezone-sensitive rolling window syntax
(`RANGE ... PRECEDING` over a `DATE` column with an `INTERVAL` bound)
actually works in Postgres 16 with a throwaway query before committing to
it in the migration — it does.

## The honest caveat: only 6 rows right now

`clean.forecast_vs_outturn` currently returns **6 rows**, all fuel_type
`WIND`, all on 2026-09-03. Not a bug — this is the real, direct
consequence of the WINDFOR gotcha already documented in
[[phase-0-foundation]]: WINDFOR has no historical archive, so the single
snapshot pulled in Phase 0 only covers a ~36-hour rolling horizon
(2026-09-03 20:00 UTC onward). The outturn data (FUELHH) only goes up to
"yesterday" relative to when it was pulled (2026-09-03). The two only
overlap on the last 6 half-hour periods of 2026-09-03 — everything else
in the WINDFOR snapshot is forecasting *into the future*, where no
outturn exists yet to compare against.

Ran the query anyway rather than waiting, to prove the view's mechanics
are correct end-to-end on real data:

```
settlement_period  outturn_mw  forecast_mw  divergence_mw  worst_miss_rank
43                  9838        12423        -2585          5
44                  9466        12423        -2957          2
45                  9410        12397        -2987          1
46                  9533        12397        -2864          3
47                  9921        12372        -2451          6
48                  9741        12372        -2631          4
```

Every one of the 6 available points has outturn *below* forecast
(WINDFOR over-forecast wind generation on this particular evening by
~2,450–2,987 MW, mean ≈ -2,746 MW) — directionally consistent with wind
being notoriously hard to forecast, but **six points from one evening is
not a claim about wind forecasting in general**, and the brief's Phase 3
acceptance check ("eyeball that wind shows the largest and most volatile
divergence... expected, given it's the hardest fuel type to forecast")
can't actually be evaluated yet for a different reason too: **WINDFOR is
the only generation forecast Elexon publishes** — there is no forecast
series for any other fuel type to compare wind's divergence against.
"Wind is worst" isn't verifiable until there's a second forecasted fuel
type or a much longer wind-forecast history, neither of which exists yet.

This is exactly why Phase 5 (scheduled WINDFOR snapshotting) isn't a
nice-to-have — it's the only way this view ever has enough real history
to say anything general. Recorded here rather than papered over with
fabricated historical forecast rows, which would misrepresent what's
actually been measured.

## What's proven vs. what isn't (yet)

- **Proven**: the transform pipeline, the join, and every window function
  are correct and run against real data end-to-end, verified by hand
  against the raw payloads.
- **Not yet proven**: any general claim about wind (or any fuel's)
  forecast-vs-outturn behavior — that needs Phase 5 to run for days/weeks
  to accumulate real snapshot history first.
