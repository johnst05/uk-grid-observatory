# Power BI dashboard

## Why there's no `.pbix` file here

Power BI Desktop is a Windows/macOS GUI application. This phase was built
in a headless Linux sandbox with no Docker daemon and no display server --
there is no way to run Power BI Desktop here, so the `.pbix` itself could
not be produced in this session. What *could* be done, and was:

- Verify `clean.forecast_vs_outturn` produces correct data (Phase 3).
- Export it, plus a supporting dataset, as CSVs a real Power BI Desktop
  session can open immediately.
- Write exact, click-by-click steps for the four visuals the brief asks
  for, so building the actual `.pbix` is mechanical once you have Power
  BI Desktop open.

## Files in this folder

- `forecast_vs_outturn_export.csv` -- a direct export of
  `clean.forecast_vs_outturn` as it stood on 2026-09-04. **Only 6 rows.**
  This is not a bug in the export; see the honest caveat in
  `docs/build-log/phase-3-clean-layer.md` -- WINDFOR has no historical
  archive, so real forecast-vs-outturn overlap only accumulates via
  Phase 5's scheduled refresh running over actual elapsed days. Re-export
  this (same query, see below) after the refresh has run for a while.
- `wind_outturn_elexon_vs_neso.csv` -- 90 days of half-hourly wind
  *outturn* (not forecast) from both sources side by side. This has real
  volume today and is worth building the Elexon-vs-NESO comparison
  chart against now, rather than waiting on forecast history.

## Recommended: connect live, don't just import the CSV

The CSVs above are snapshots. Once Phase 5 has been running for a while,
`clean.forecast_vs_outturn` will have real history that a static CSV
export won't reflect. In Power BI Desktop:

1. **Get Data -> PostgreSQL database.**
2. Server: `localhost` (or wherever Postgres actually runs), port `5432`,
   database `grid_observatory`.
3. Under **Advanced options**, you can paste a SQL statement directly,
   e.g. `SELECT * FROM clean.forecast_vs_outturn;` -- or just navigate to
   the `clean` schema and select `forecast_vs_outturn` from the table
   list.
4. Credentials: database, username `grid`, password from your `.env`.
5. **Import** mode is fine at this data volume; switch to **DirectQuery**
   later if the table grows large enough that re-importing on every
   refresh gets slow.

If a live connection genuinely isn't convenient (e.g. building the
dashboard on a machine that can't reach the database), re-run the export
this file used and open the CSV instead:

```bash
psql "$DATABASE_URL" -c "\copy (SELECT * FROM clean.forecast_vs_outturn ORDER BY settlement_date, settlement_period) TO STDOUT WITH CSV HEADER" > dashboard/forecast_vs_outturn_export.csv
```

## Build steps for the four visuals

### 1. Time-series of divergence, filterable by fuel type

- Visual: **Line chart**.
- X-axis: a date field built from `settlement_date` +
  `settlement_period` (Power Query: add a custom column
  `Timestamp = settlement_date + #duration(0, 0, (settlement_period - 1) * 30, 0)`
  for a proper half-hourly timestamp instead of a per-day step chart).
- Y-axis: `divergence_mw`.
- Add `rolling_avg_7d_mw` as a second line on the same chart (different
  color, e.g. a muted grey) so the raw half-hourly noise and the smoothed
  trend are both visible at once.
- **Filter/slicer**: `fuel_type` (a slicer visual above the chart). Right
  now this only has one real value (`WIND`) since WINDFOR is the only
  forecast Elexon publishes -- the slicer is still worth building now, so
  it's ready if a second forecasted fuel type is ever added.

### 2. Bar chart ranking fuel types by average absolute divergence

- Visual: **Bar chart** (horizontal, easier to read fuel-type labels).
- Axis: `fuel_type`.
- Value: a new **measure**, in DAX:
  `Avg Abs Divergence = AVERAGEX(forecast_vs_outturn, ABS(forecast_vs_outturn[divergence_mw]))`.
- Sort descending by that measure.
- Honest caveat to carry into the dashboard itself (as a text box, not
  just this README): with only `WIND` in the data so far, this chart is
  a bar of one until a second forecasted fuel type exists.

### 3. Table/heatmap of the worst individual forecast-miss days

- Visual: **Table** (or a matrix with conditional-formatting heatmap on
  the divergence column).
- Columns: `settlement_date`, `settlement_period`, `fuel_type`,
  `outturn_mw`, `forecast_mw`, `divergence_mw`, `worst_miss_rank`.
- Filter: `worst_miss_rank <= 20` (top 20 worst misses).
- Conditional formatting: background color scale on `divergence_mw`,
  diverging (e.g. blue for over-forecast/negative, orange for
  under-forecast/positive) so the direction of the miss is visible at a
  glance, not just its size.

### 4. Headline card: total divergence over the loaded window

- Visual: **Card**.
- Measure: `Total Abs Divergence MWh = SUMX(forecast_vs_outturn, ABS(forecast_vs_outturn[divergence_mw]) * 0.5)`
  (× 0.5 converts a half-hourly MW figure to MWh for that period, so the
  summed total is in energy units, not an average-of-power figure that
  doesn't mean much summed).
- A second small card next to it: `COUNTROWS(forecast_vs_outturn)` so the
  headline number always shows how many settlement periods it's actually
  based on -- important given the current 6-row caveat; the dashboard
  should never present a total without also showing its sample size.

## What's genuinely ready to build today

The Elexon-vs-NESO wind outturn comparison
(`wind_outturn_elexon_vs_neso.csv`, 90 real days) can become a real chart
right now -- two line series (`source = elexon` vs `source = neso`) over
the same `settlement_date`/`settlement_period` axis, showing where the two
independent measurements of the same real-world quantity agree or
disagree. That's a genuinely interesting result on its own, doesn't
depend on WINDFOR history, and is worth including in the dashboard
alongside the four required visuals above.
