"""Raw -> staging transform.

Staging is fully derived from raw every time this runs: each staging
table is truncated and rebuilt from the current contents of raw. This is
safe and correct because raw is append-only and immutable (Phase 1) --
there is no staging-only state that would be lost by rebuilding it, and
at this data volume a full rebuild is cheap. (At much larger scale you'd
want an incremental/merge strategy instead; noted here rather than
built, since it isn't needed yet.)

Dedup rule throughout: when raw has multiple republished versions of the
same real-world fact (a settlement period gets a later, more final
publish), keep only the row with the latest publish_time (or
forecast_timestamp, for the NESO demand forecast) per key -- via
`DISTINCT ON`.

Grain notes:
  - generation_outturn / generation_forecast share a half-hourly
    settlement-period grain so they can be joined directly in Phase 3.
    WINDFOR is hourly, so each hourly forecast is expanded into the two
    half-hour settlement periods it spans (see WINDFOR_TO_STAGING_SQL).
  - NESO's generation-mix fuel labels (GAS, COAL, WIND, ...) are its own
    taxonomy, not identical to Elexon's BM Unit fuel types (CCGT, OCGT,
    WIND, ...). They're loaded as their own fuel_type values rather than
    forced into a mapping that doesn't really exist -- see the build log
    for why. WIND and NUCLEAR happen to be named the same in both and are
    directly comparable across source; most others aren't.
  - demand_forecast deliberately stays at NESO's own (target_date,
    days_ahead, cardinal_point) grain rather than settlement_period --
    cardinal points don't align to half-hours.
"""
from __future__ import annotations

from load_raw import get_connection

FUELHH_TO_STAGING_SQL = """
INSERT INTO staging.generation_outturn
    (settlement_date, settlement_period, fuel_type, source, generation_mw, publish_time)
SELECT DISTINCT ON (settlement_date, settlement_period, fuel_type, source)
    settlement_date, settlement_period, fuel_type, 'elexon' AS source,
    generation_mw, publish_time
FROM raw.elexon_fuelhh
ORDER BY settlement_date, settlement_period, fuel_type, source, publish_time DESC;
"""

# NESO generation mix is half-hourly by `datetime` (naive, already UK local
# clock time) rather than settlement_date/period, and wide (one column per
# fuel) rather than long -- both need converting before it matches the
# generation_outturn grain.
NESO_GENMIX_TO_STAGING_SQL = """
INSERT INTO staging.generation_outturn
    (settlement_date, settlement_period, fuel_type, source, generation_mw, publish_time)
SELECT DISTINCT ON (settlement_date, settlement_period, fuel_type, source)
    settlement_date, settlement_period, fuel_type, 'neso' AS source,
    generation_mw, datetime AS publish_time
FROM (
    SELECT
        datetime::date AS settlement_date,
        (EXTRACT(HOUR FROM datetime) * 2 + EXTRACT(MINUTE FROM datetime) / 30)::int + 1 AS settlement_period,
        datetime,
        unnest(ARRAY['GAS','COAL','NUCLEAR','WIND','WIND_EMB','HYDRO','IMPORTS','BIOMASS','OTHER','SOLAR','STORAGE']) AS fuel_type,
        unnest(ARRAY[gas_mw, coal_mw, nuclear_mw, wind_mw, wind_embedded_mw, hydro_mw, imports_mw, biomass_mw, other_mw, solar_mw, storage_mw]) AS generation_mw
    FROM raw.neso_generation_mix
) unpivoted
WHERE generation_mw IS NOT NULL
ORDER BY settlement_date, settlement_period, fuel_type, source, datetime DESC;
"""

# WINDFOR is hourly; expand each row into the two half-hour settlement
# periods it covers (i * 30 minutes, i in {0, 1}), converting the UTC
# start_time to a UK-local settlement_date/period along the way.
WINDFOR_TO_STAGING_SQL = """
INSERT INTO staging.generation_forecast
    (settlement_date, settlement_period, fuel_type, source, forecast_mw, publish_time)
SELECT DISTINCT ON (settlement_date, settlement_period, fuel_type, source)
    settlement_date, settlement_period, 'WIND' AS fuel_type, 'elexon' AS source,
    generation_mw AS forecast_mw, publish_time
FROM (
    SELECT
        (local_start.dt + (half.i * interval '30 minutes'))::date AS settlement_date,
        (EXTRACT(HOUR FROM local_start.dt + (half.i * interval '30 minutes')) * 2
            + EXTRACT(MINUTE FROM local_start.dt + (half.i * interval '30 minutes')) / 30)::int + 1 AS settlement_period,
        w.generation_mw,
        w.publish_time
    FROM raw.elexon_windfor w
    CROSS JOIN generate_series(0, 1) AS half(i)
    CROSS JOIN LATERAL (SELECT (w.start_time AT TIME ZONE 'Europe/London') AS dt) AS local_start
) expanded
ORDER BY settlement_date, settlement_period, fuel_type, source, publish_time DESC;
"""

DEMAND_OUTTURN_TO_STAGING_SQL = """
INSERT INTO staging.demand_outturn
    (settlement_date, settlement_period, source, demand_mw, publish_time)
SELECT DISTINCT ON (settlement_date, settlement_period, source)
    settlement_date, settlement_period, 'elexon' AS source, demand_mw, publish_time
FROM raw.elexon_demand_outturn
ORDER BY settlement_date, settlement_period, source, publish_time DESC;
"""

DEMAND_FORECAST_TO_STAGING_SQL = """
INSERT INTO staging.demand_forecast
    (target_date, days_ahead, cardinal_point, source, forecast_demand_mw, forecast_timestamp)
SELECT DISTINCT ON (target_date, days_ahead, cardinal_point, source)
    target_date, days_ahead, cardinal_point, 'neso' AS source,
    forecast_demand_mw, forecast_timestamp
FROM raw.neso_demand_forecast
WHERE cardinal_point IS NOT NULL
ORDER BY target_date, days_ahead, cardinal_point, source, forecast_timestamp DESC;
"""

STEPS = [
    ("staging.generation_outturn (elexon FUELHH)", "TRUNCATE staging.generation_outturn", FUELHH_TO_STAGING_SQL),
    ("staging.generation_outturn (neso generation mix)", None, NESO_GENMIX_TO_STAGING_SQL),
    ("staging.generation_forecast (elexon WINDFOR)", "TRUNCATE staging.generation_forecast", WINDFOR_TO_STAGING_SQL),
    ("staging.demand_outturn (elexon)", "TRUNCATE staging.demand_outturn", DEMAND_OUTTURN_TO_STAGING_SQL),
    ("staging.demand_forecast (neso)", "TRUNCATE staging.demand_forecast", DEMAND_FORECAST_TO_STAGING_SQL),
]


def main():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for label, truncate_sql, insert_sql in STEPS:
                if truncate_sql:
                    cur.execute(truncate_sql)
                cur.execute(insert_sql)
                print(f"{label}: inserted {cur.rowcount} rows")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
