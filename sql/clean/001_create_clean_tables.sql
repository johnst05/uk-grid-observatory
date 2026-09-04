-- Clean/mart layer: forecast-vs-outturn divergence, computed with window
-- functions. A plain view rather than a materialized table -- the data
-- volumes here are small enough that recomputing on query is cheap, and
-- a view always reflects the latest staging data with no extra refresh
-- step needed after Phase 5's scheduled runs land new WINDFOR snapshots.
--
-- Joined ON (settlement_date, settlement_period, fuel_type, source) so
-- forecast and outturn are always compared within the same provider's
-- own pipeline (currently: Elexon WINDFOR vs Elexon FUELHH, fuel_type =
-- 'WIND') rather than mixing an Elexon forecast against a NESO outturn
-- figure that was produced by a different methodology.

CREATE SCHEMA IF NOT EXISTS clean;

CREATE OR REPLACE VIEW clean.forecast_vs_outturn AS
WITH joined AS (
    SELECT
        o.settlement_date,
        o.settlement_period,
        o.fuel_type,
        o.source,
        o.generation_mw AS outturn_mw,
        f.forecast_mw,
        (o.generation_mw - f.forecast_mw) AS divergence_mw
    FROM staging.generation_outturn o
    JOIN staging.generation_forecast f
        ON o.settlement_date = f.settlement_date
       AND o.settlement_period = f.settlement_period
       AND o.fuel_type = f.fuel_type
       AND o.source = f.source
)
SELECT
    settlement_date,
    settlement_period,
    fuel_type,
    source,
    outturn_mw,
    forecast_mw,
    divergence_mw,

    -- Rolling average divergence over the trailing 7 and 30 calendar
    -- days (RANGE over settlement_date, not ROWS, so it's a true
    -- calendar window even if some settlement periods are missing).
    AVG(divergence_mw) OVER (
        PARTITION BY fuel_type
        ORDER BY settlement_date
        RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
    ) AS rolling_avg_7d_mw,
    AVG(divergence_mw) OVER (
        PARTITION BY fuel_type
        ORDER BY settlement_date
        RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW
    ) AS rolling_avg_30d_mw,

    -- Global rank of the single worst forecast misses by magnitude,
    -- 1 = worst.
    RANK() OVER (ORDER BY ABS(divergence_mw) DESC) AS worst_miss_rank,

    -- Day-over-day change in divergence: compared to the SAME
    -- settlement_period exactly one day earlier (LAG offset 48), not
    -- simply the previous row -- with half-hourly data the previous row
    -- is 30 minutes earlier, not a day earlier, so a plain LAG(...,1)
    -- would not actually be "day-over-day". 48 assumes a standard
    -- (non-clock-change) day; the two DST transition days per year will
    -- be off by one period, a known simplification.
    divergence_mw - LAG(divergence_mw, 48) OVER (
        PARTITION BY fuel_type
        ORDER BY settlement_date, settlement_period
    ) AS dod_delta_mw
FROM joined;
