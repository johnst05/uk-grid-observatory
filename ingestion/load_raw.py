"""Load the CSVs already sitting in data/raw/ into the raw.* Postgres
tables. Raw is append-only and immutable -- this script only inserts, it
never updates or deletes; re-running it after a fresh ingestion pull (a
new dated CSV) just adds those new rows alongside what's already loaded.

Each raw table keeps the exact API response as `source_payload` JSONB
(so any row can be audited back to the original record) plus a handful of
typed columns useful for filtering/joining.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

from common import DATA_RAW_DIR, REPO_ROOT

import os
from dotenv import load_dotenv

load_dotenv()


def _clean(value):
    """NaN -> None so it lands as SQL NULL instead of the string 'nan'."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _row_to_payload(row: dict) -> str:
    return json.dumps({k: _clean(v) for k, v in row.items()})


def _load_csvs(pattern: str) -> pd.DataFrame:
    paths = sorted(DATA_RAW_DIR.glob(pattern))
    if not paths:
        print(f"  (no files matching {pattern}, skipping)")
        return pd.DataFrame()
    frames = [pd.read_csv(p) for p in paths]
    print(f"  loading {len(paths)} file(s) matching {pattern}: "
          f"{', '.join(p.name for p in paths)}")
    return pd.concat(frames, ignore_index=True)


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "grid_observatory"),
        user=os.environ.get("PGUSER", "grid"),
        password=os.environ.get("PGPASSWORD", ""),
    )


def load_fuelhh(conn):
    df = _load_csvs("elexon_fuelhh_*.csv")
    if df.empty:
        return 0
    rows = [
        (
            r["settlementDate"], r["settlementPeriod"], r["fuelType"], r["generation"],
            r["publishTime"], r["startTime"], _row_to_payload(r),
        )
        for r in df.to_dict(orient="records")
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO raw.elexon_fuelhh
               (settlement_date, settlement_period, fuel_type, generation_mw,
                publish_time, start_time, source_payload)
               VALUES %s""",
            rows,
        )
    conn.commit()
    return len(rows)


def load_demand_outturn(conn):
    df = _load_csvs("elexon_demand_outturn_*.csv")
    if df.empty:
        return 0
    rows = [
        (
            r["settlementDate"], r["settlementPeriod"], r["initialDemandOutturn"],
            r.get("initialTransmissionSystemDemandOutturn"),
            r["publishTime"], r["startTime"], _row_to_payload(r),
        )
        for r in df.to_dict(orient="records")
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO raw.elexon_demand_outturn
               (settlement_date, settlement_period, demand_mw, itsdo_mw,
                publish_time, start_time, source_payload)
               VALUES %s""",
            rows,
        )
    conn.commit()
    return len(rows)


def load_windfor(conn):
    df = _load_csvs("elexon_windfor_snapshot_*.csv")
    if df.empty:
        return 0
    rows = [
        (r["publishTime"], r["startTime"], r["generation"], _row_to_payload(r))
        for r in df.to_dict(orient="records")
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO raw.elexon_windfor
               (publish_time, start_time, generation_mw, source_payload)
               VALUES %s""",
            rows,
        )
    conn.commit()
    return len(rows)


def load_neso_generation_mix(conn):
    df = _load_csvs("neso_generation_mix_*.csv")
    if df.empty:
        return 0
    rows = [
        (
            r["DATETIME"], r.get("GAS"), r.get("COAL"), r.get("NUCLEAR"), r.get("WIND"),
            r.get("WIND_EMB"), r.get("HYDRO"), r.get("IMPORTS"), r.get("BIOMASS"),
            r.get("OTHER"), r.get("SOLAR"), r.get("STORAGE"), r.get("GENERATION"),
            r.get("CARBON_INTENSITY"), _row_to_payload(r),
        )
        for r in df.to_dict(orient="records")
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO raw.neso_generation_mix
               (datetime, gas_mw, coal_mw, nuclear_mw, wind_mw, wind_embedded_mw,
                hydro_mw, imports_mw, biomass_mw, other_mw, solar_mw, storage_mw,
                generation_mw, carbon_intensity, source_payload)
               VALUES %s""",
            rows,
        )
    conn.commit()
    return len(rows)


def load_neso_demand_forecast(conn):
    df = _load_csvs("neso_demand_forecast_*.csv")
    if df.empty:
        return 0
    rows = [
        (
            r.get("DAYSAHEAD"), r["TARGETDATE"], r.get("FORECASTDEMAND"),
            r.get("CARDINALPOINT"), r.get("CP_TYPE"), r.get("FORECAST_TIMESTAMP"),
            _row_to_payload(r),
        )
        for r in df.to_dict(orient="records")
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO raw.neso_demand_forecast
               (days_ahead, target_date, forecast_demand_mw, cardinal_point,
                cp_type, forecast_timestamp, source_payload)
               VALUES %s""",
            rows,
        )
    conn.commit()
    return len(rows)


LOADERS = {
    "elexon_fuelhh": load_fuelhh,
    "elexon_demand_outturn": load_demand_outturn,
    "elexon_windfor": load_windfor,
    "neso_generation_mix": load_neso_generation_mix,
    "neso_demand_forecast": load_neso_demand_forecast,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=list(LOADERS), action="append",
                         help="Load only this table (repeatable). Default: load all.")
    args = parser.parse_args()

    targets = args.only or list(LOADERS)
    conn = get_connection()
    try:
        for name in targets:
            print(f"Loading raw.{name} ...")
            count = LOADERS[name](conn)
            print(f"  -> inserted {count} rows into raw.{name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
