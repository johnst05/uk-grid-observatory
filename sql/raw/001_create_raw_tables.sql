-- Raw layer: land exactly what each API returned, plus enough typed
-- columns to filter/join on. source_payload always keeps the full
-- original record so any raw row can be audited back to the API response.

CREATE SCHEMA IF NOT EXISTS raw;

-- Elexon BMRS FUELHH: half-hourly outturn generation by fuel type.
CREATE TABLE IF NOT EXISTS raw.elexon_fuelhh (
    id              BIGSERIAL PRIMARY KEY,
    settlement_date DATE        NOT NULL,
    settlement_period SMALLINT  NOT NULL,
    fuel_type       TEXT        NOT NULL,
    generation_mw   NUMERIC     NOT NULL,
    publish_time    TIMESTAMPTZ NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    source_payload  JSONB       NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_elexon_fuelhh_settlement
    ON raw.elexon_fuelhh (settlement_date, settlement_period, fuel_type);

-- Elexon BMRS WINDFOR: rolling wind/solar generation forecast snapshot.
-- No settlement_date/period -- WINDFOR is a rolling forecast horizon keyed
-- by start_time, snapshotted at whatever publish_time it was pulled.
CREATE TABLE IF NOT EXISTS raw.elexon_windfor (
    id              BIGSERIAL PRIMARY KEY,
    publish_time    TIMESTAMPTZ NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    generation_mw   NUMERIC     NOT NULL,
    source_payload  JSONB       NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_elexon_windfor_start_time
    ON raw.elexon_windfor (start_time, publish_time);

-- Elexon /demand/outturn: half-hourly initial (transmission system)
-- national demand outturn (datasets INDO + ITSDO).
CREATE TABLE IF NOT EXISTS raw.elexon_demand_outturn (
    id              BIGSERIAL PRIMARY KEY,
    settlement_date DATE        NOT NULL,
    settlement_period SMALLINT  NOT NULL,
    demand_mw       NUMERIC     NOT NULL,
    itsdo_mw        NUMERIC,
    publish_time    TIMESTAMPTZ NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    source_payload  JSONB       NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_elexon_demand_outturn_settlement
    ON raw.elexon_demand_outturn (settlement_date, settlement_period);

-- NESO "Historic Day Ahead Demand Forecasts" datastore resource.
CREATE TABLE IF NOT EXISTS raw.neso_demand_forecast (
    id                  BIGSERIAL PRIMARY KEY,
    days_ahead          SMALLINT,
    target_date         DATE        NOT NULL,
    forecast_demand_mw  NUMERIC,
    cardinal_point      TEXT,
    cp_type             TEXT,
    forecast_timestamp  TIMESTAMPTZ,
    source_payload      JSONB       NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_neso_demand_forecast_target_date
    ON raw.neso_demand_forecast (target_date);

-- NESO "Historic GB Generation Mix" datastore resource -- an independent
-- (non-Elexon) cross-check source for actual generation by fuel type.
CREATE TABLE IF NOT EXISTS raw.neso_generation_mix (
    id              BIGSERIAL PRIMARY KEY,
    datetime        TIMESTAMPTZ NOT NULL,
    gas_mw          NUMERIC,
    coal_mw         NUMERIC,
    nuclear_mw      NUMERIC,
    wind_mw         NUMERIC,
    wind_embedded_mw NUMERIC,
    hydro_mw        NUMERIC,
    imports_mw      NUMERIC,
    biomass_mw      NUMERIC,
    other_mw        NUMERIC,
    solar_mw        NUMERIC,
    storage_mw      NUMERIC,
    generation_mw   NUMERIC,
    carbon_intensity NUMERIC,
    source_payload  JSONB       NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_neso_generation_mix_datetime
    ON raw.neso_generation_mix (datetime);
