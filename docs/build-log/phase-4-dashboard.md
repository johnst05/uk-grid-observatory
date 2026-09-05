---
tags: [uk-grid-observatory, build-log, phase-4]
project: "[[UK Grid Observatory]]"
date: 2026-09-05
phase: 4
status: partial
---

# Phase 4 — Power BI dashboard

## Honest limitation, stated up front

**No `.pbix` file was produced.** Power BI Desktop is a Windows/macOS GUI
application; this session is a headless Linux sandbox. There is no
plausible way to run it here, so rather than claim the phase is done,
this is recorded as genuinely partial -- see `dashboard/README.md` for
what a future session (with Power BI Desktop) needs to do to finish it.

## What was actually done instead

- Exported `clean.forecast_vs_outturn` for real
  (`dashboard/forecast_vs_outturn_export.csv`) -- 6 rows, matching the
  Phase 3 caveat exactly. Didn't pad this with synthetic rows to make the
  export "look like" a real dashboard dataset; the honest 6-row file is
  more useful to whoever builds the `.pbix` than a fabricated one would
  be, since they need to know what they're actually working with.
- Additionally exported a **90-day** dataset that doesn't have the
  forecast-history limitation: `wind_outturn_elexon_vs_neso.csv`, wind
  *outturn* from both Elexon and NESO side by side. This has real volume
  today, so it's called out in `dashboard/README.md` as something worth
  building into the dashboard now rather than waiting for WINDFOR history
  to accumulate.
- Wrote exact, click-by-click build steps for all four visuals the brief
  specifies (time series w/ fuel-type filter, ranked bar chart, worst-miss
  table/heatmap, headline card), including the actual DAX measures needed
  (`AVERAGEX` for mean absolute divergence, a `SUMX`-based MWh conversion
  for the headline card since summing half-hourly MW values directly
  would not be a meaningful total).
- Recommended a **live Postgres connection** over re-importing the static
  CSV, specifically because the CSV will be stale the moment Phase 5's
  scheduled refresh adds more real forecast history -- the whole point of
  Phase 5 was to make more data show up over time, so the dashboard
  should reflect that automatically rather than needing a manual
  re-export every day.

## Design decision: don't hide the small-sample caveat inside the dashboard

Specified that the headline card (visual 4) should show *both* the total
divergence figure *and* the row count it's based on, side by side --
so the dashboard itself always discloses its own sample size rather than
presenting a confident-looking number that's currently built on 6 rows.
This mirrors the same principle followed in the build log throughout:
state what's actually been measured, not what the brief hoped would be
measured by this point.
