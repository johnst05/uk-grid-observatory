-- Staging layer: typed, deduplicated, one row per real-world fact.
-- Where raw data has multiple republished versions of the same fact
-- (a settlement period gets re-published as later, more final data
-- arrives), staging keeps only the latest publish_time per key.
--
-- `source` distinguishes which upstream API a row came from (elexon vs
-- neso) so both can be compared side by side at the same grain.

CREATE SCHEMA IF NOT EXISTS staging;

-- Actual metered generation, half-hourly, by fuel type and source.
CREATE TABLE IF NOT EXISTS staging.generation_outturn (
    settlement_date     DATE        NOT NULL,
    settlement_period   SMALLINT    NOT NULL,
    fuel_type           TEXT        NOT NULL,
    source              TEXT        NOT NULL,
    generation_mw       NUMERIC     NOT NULL,
    publish_time        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (settlement_date, settlement_period, fuel_type, source)
);

-- Forecast generation (currently: Elexon WINDFOR, fuel_type = 'WIND'),
-- half-hourly grain (an hourly WINDFOR value is carried across both
-- half-hour settlement periods it covers).
CREATE TABLE IF NOT EXISTS staging.generation_forecast (
    settlement_date     DATE        NOT NULL,
    settlement_period   SMALLINT    NOT NULL,
    fuel_type           TEXT        NOT NULL,
    source              TEXT        NOT NULL,
    forecast_mw         NUMERIC     NOT NULL,
    publish_time        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (settlement_date, settlement_period, fuel_type, source)
);

-- Actual metered national demand, half-hourly (Elexon INDO).
CREATE TABLE IF NOT EXISTS staging.demand_outturn (
    settlement_date     DATE        NOT NULL,
    settlement_period   SMALLINT    NOT NULL,
    source              TEXT        NOT NULL,
    demand_mw           NUMERIC     NOT NULL,
    publish_time        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (settlement_date, settlement_period, source)
);

-- Day-ahead demand forecast (NESO), at the cardinal-point grain the
-- source publishes it in -- not every cardinal point lines up with a
-- settlement period, so this intentionally does not share a grain with
-- generation_forecast.
CREATE TABLE IF NOT EXISTS staging.demand_forecast (
    target_date         DATE        NOT NULL,
    days_ahead          SMALLINT    NOT NULL,
    cardinal_point      TEXT        NOT NULL,
    source              TEXT        NOT NULL,
    forecast_demand_mw  NUMERIC     NOT NULL,
    forecast_timestamp  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (target_date, days_ahead, cardinal_point, source)
);
