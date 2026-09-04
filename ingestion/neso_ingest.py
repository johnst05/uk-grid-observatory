"""Pull data from NESO's CKAN datastore API and land it as CSVs under
data/raw/. Used as an independent (non-Elexon) cross-check source:
  - Historic GB Generation Mix -- actual generation by fuel type.
  - Historic Day Ahead Demand Forecasts -- a second forecast source.

Gotchas (see docs/build-log for how these were found):
  - Column names in the SELECT/WHERE clause of the `datastore_search_sql`
    action MUST be double-quoted ("DATETIME", not DATETIME), or Postgres
    lower-cases them and the query fails with
    'column "datetime" does not exist'.
  - `&format=csv` is ignored on the `_sql` action -- it always returns
    JSON. Only the plain `datastore_search` action respects format=csv.
  - NESO rate-limits to roughly 2 requests/minute; this script sleeps
    between calls accordingly.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

import pandas as pd

from common import NESO_API_BASE, http_get_json, save_csv

GENERATION_MIX_RESOURCE_ID = "f93d1835-75bc-43e5-84ad-12472b180a98"
DEMAND_FORECAST_RESOURCE_ID = "9847e7bb-986e-49be-8138-717b25933fbb"

RATE_LIMIT_SLEEP_SECONDS = 31  # ~2 requests/minute


def _sql_query(sql: str) -> pd.DataFrame:
    payload = http_get_json(f"{NESO_API_BASE}/datastore_search_sql", params={"sql": sql})
    return pd.DataFrame(payload["result"]["records"])


def fetch_generation_mix(start: date, end_exclusive: date) -> pd.DataFrame:
    sql = (
        f'SELECT * FROM "{GENERATION_MIX_RESOURCE_ID}" '
        f'WHERE "DATETIME" >= \'{start.isoformat()}\' AND "DATETIME" < \'{end_exclusive.isoformat()}\' '
        f'ORDER BY "DATETIME"'
    )
    return _sql_query(sql)


def fetch_demand_forecast(start: date, end: date, days_ahead: int = 1) -> pd.DataFrame:
    sql = (
        f'SELECT * FROM "{DEMAND_FORECAST_RESOURCE_ID}" '
        f'WHERE "DAYSAHEAD" = {int(days_ahead)} '
        f'AND "TARGETDATE" >= \'{start.isoformat()}\' AND "TARGETDATE" <= \'{end.isoformat()}\' '
        f'ORDER BY "TARGETDATE"'
    )
    return _sql_query(sql)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90,
                         help="How many days of history to pull, ending yesterday.")
    args = parser.parse_args()

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)

    print(f"Fetching NESO generation mix {start} .. {end} ...")
    gen_mix = fetch_generation_mix(start, end + timedelta(days=1))
    path = save_csv(gen_mix, f"neso_generation_mix_{start}_{end}.csv")
    print(f"  -> {len(gen_mix)} rows -> {path}")

    print(f"Sleeping {RATE_LIMIT_SLEEP_SECONDS}s to respect NESO's rate limit ...")
    time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    print(f"Fetching NESO day-ahead demand forecast {start} .. {end} ...")
    demand_fc = fetch_demand_forecast(start, end)
    path = save_csv(demand_fc, f"neso_demand_forecast_{start}_{end}.csv")
    print(f"  -> {len(demand_fc)} rows -> {path}")


if __name__ == "__main__":
    main()
