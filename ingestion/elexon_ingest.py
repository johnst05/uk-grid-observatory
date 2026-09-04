"""Pull generation/demand data from Elexon's BMRS Insights API and land it
as CSVs under data/raw/. This script only fetches and saves -- loading into
Postgres is a separate step (see ingestion/load_raw.py).

Datasets pulled:
  - FUELHH: half-hourly outturn generation by fuel type.
  - WINDFOR: rolling wind generation forecast (current horizon only --
    there is no historical WINDFOR archive; see docs/refresh_schedule.md
    for why this has to be snapshotted repeatedly over time instead).
  - INDO/ITSDO: half-hourly initial (transmission system) demand outturn,
    via the /demand/outturn endpoint.

Gotchas:
  - FUELHH rejects any single request spanning more than 7 days (HTTP 400:
    "date range ... must not exceed 7 days").
  - /demand/outturn rejects more than 28 days in one request (same error,
    different limit). The generic /datasets/INDO endpoint looked like it
    should work the same way as FUELHH, but silently ignores
    settlementDateFrom/To entirely and always returns just the single
    latest settlement period -- /demand/outturn is the endpoint that
    actually respects a date range for demand history.
Both are handled by chunking date ranges via common.daterange_chunks with
the endpoint's own limit.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

import pandas as pd

from common import ELEXON_API_BASE, daterange_chunks, http_get_json, save_csv, utcnow_stamp


def fetch_fuelhh(start: date, end: date) -> pd.DataFrame:
    frames = []
    for chunk_start, chunk_end in daterange_chunks(start, end, max_days=7):
        payload = http_get_json(
            f"{ELEXON_API_BASE}/datasets/FUELHH",
            params={
                "settlementDateFrom": chunk_start.isoformat(),
                "settlementDateTo": chunk_end.isoformat(),
            },
        )
        frames.append(pd.DataFrame(payload.get("data", [])))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_demand_outturn(start: date, end: date) -> pd.DataFrame:
    frames = []
    for chunk_start, chunk_end in daterange_chunks(start, end, max_days=28):
        payload = http_get_json(
            f"{ELEXON_API_BASE}/demand/outturn",
            params={
                "settlementDateFrom": chunk_start.isoformat(),
                "settlementDateTo": chunk_end.isoformat(),
            },
        )
        frames.append(pd.DataFrame(payload.get("data", [])))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_windfor_snapshot() -> pd.DataFrame:
    """WINDFOR is a rolling forecast: querying it with a past date range
    does NOT return historical forecasts, it just returns whatever the
    current forecast horizon is. So there's only ever a "latest snapshot"
    to fetch here."""
    payload = http_get_json(f"{ELEXON_API_BASE}/datasets/WINDFOR")
    return pd.DataFrame(payload.get("data", []))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90,
                         help="How many days of FUELHH/INDO history to pull, ending yesterday.")
    args = parser.parse_args()

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)

    print(f"Fetching FUELHH {start} .. {end} ...")
    fuelhh = fetch_fuelhh(start, end)
    path = save_csv(fuelhh, f"elexon_fuelhh_{start}_{end}.csv")
    print(f"  -> {len(fuelhh)} rows -> {path}")

    print(f"Fetching demand outturn (INDO/ITSDO) {start} .. {end} ...")
    demand_outturn = fetch_demand_outturn(start, end)
    path = save_csv(demand_outturn, f"elexon_demand_outturn_{start}_{end}.csv")
    print(f"  -> {len(demand_outturn)} rows -> {path}")

    print("Fetching WINDFOR (current rolling snapshot) ...")
    windfor = fetch_windfor_snapshot()
    stamp = utcnow_stamp()
    path = save_csv(windfor, f"elexon_windfor_snapshot_{stamp}.csv")
    print(f"  -> {len(windfor)} rows -> {path}")


if __name__ == "__main__":
    main()
