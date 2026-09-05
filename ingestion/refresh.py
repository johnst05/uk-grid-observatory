"""Phase 5 scheduled refresh: pull the latest day of outturn data, snapshot
WINDFOR (its only historical archive is whatever gets snapshotted here),
load everything into raw, and rerun the raw -> staging -> clean transform.

Meant to run once a day via cron / Task Scheduler / a GitHub Action (see
docs/refresh_schedule.md for why WINDFOR snapshotting specifically can't
be caught up on later, and for how to wire this into each of those).

Idempotent: ingestion/load_raw.py's raw._loaded_files ledger means running
this twice on the same day (or re-running after a partial failure) does
not double-insert -- the second run just finds nothing new to load for
that day's filenames.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, timedelta

import time

import load_raw
from common import REPO_ROOT, save_csv, utcnow_stamp
from elexon_ingest import fetch_demand_outturn, fetch_fuelhh, fetch_windfor_snapshot
from neso_ingest import RATE_LIMIT_SLEEP_SECONDS, fetch_demand_forecast, fetch_generation_mix

LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "refresh.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("refresh")


def step(name, fn, *args, **kwargs):
    """Run one refresh step, logging success/failure. A single step
    failing (e.g. one API being briefly down) doesn't stop the others --
    each source is independent, so a NESO outage shouldn't also skip the
    day's Elexon pull."""
    try:
        result = fn(*args, **kwargs)
        log.info(f"OK: {name}")
        return result
    except Exception:
        log.exception(f"FAILED: {name}")
        return None


def ingest_latest_day():
    """Returns the list of transient CSV paths written (everything except
    the WINDFOR snapshot, which is kept permanently -- see cleanup_transient_files)."""
    yesterday = date.today() - timedelta(days=1)
    transient_paths = []

    fuelhh = step("fetch FUELHH (yesterday)", fetch_fuelhh, yesterday, yesterday)
    if fuelhh is not None and not fuelhh.empty:
        transient_paths.append(save_csv(fuelhh, f"elexon_fuelhh_{yesterday}_{yesterday}.csv"))

    demand = step("fetch demand outturn (yesterday)", fetch_demand_outturn, yesterday, yesterday)
    if demand is not None and not demand.empty:
        transient_paths.append(save_csv(demand, f"elexon_demand_outturn_{yesterday}_{yesterday}.csv"))

    # WINDFOR is deliberately NOT transient -- it's the only record of
    # what the forecast said at this moment, so this file is kept
    # permanently (see docs/refresh_schedule.md).
    windfor = step("snapshot WINDFOR", fetch_windfor_snapshot)
    if windfor is not None and not windfor.empty:
        save_csv(windfor, f"elexon_windfor_snapshot_{utcnow_stamp()}.csv")

    genmix = step("fetch NESO generation mix (yesterday)", fetch_generation_mix,
                  yesterday, yesterday + timedelta(days=1))
    if genmix is not None and not genmix.empty:
        transient_paths.append(save_csv(genmix, f"neso_generation_mix_{yesterday}_{yesterday}.csv"))

    time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    demand_fc = step("fetch NESO demand forecast (yesterday)", fetch_demand_forecast,
                     yesterday, yesterday)
    if demand_fc is not None and not demand_fc.empty:
        transient_paths.append(save_csv(demand_fc, f"neso_demand_forecast_{yesterday}_{yesterday}.csv"))

    return transient_paths


def load_and_transform():
    conn = load_raw.get_connection()
    try:
        load_raw.ensure_loaded_files_table(conn)
        for name, fn in load_raw.LOADERS.items():
            count = step(f"load raw.{name}", fn, conn)
            log.info(f"  raw.{name}: {count} new rows")
    finally:
        conn.close()

    step("rerun staging + clean transform",
         lambda: subprocess.run([sys.executable, str(REPO_ROOT / "ingestion" / "transform_staging.py")],
                                 check=True, cwd=REPO_ROOT / "ingestion"))


def cleanup_transient_files(paths):
    """Everything except WINDFOR snapshots is re-fetchable from the
    source APIs for any past date -- once loaded into raw (which keeps
    the full payload as JSONB), the landing CSV doesn't need to persist
    and would just accumulate in data/raw/ forever otherwise."""
    for path in paths:
        path.unlink(missing_ok=True)
        log.info(f"  removed transient file {path.name} (already in raw)")


def main():
    log.info("=== Starting scheduled refresh ===")
    transient_paths = ingest_latest_day()
    load_and_transform()
    cleanup_transient_files(transient_paths)
    log.info("=== Refresh complete ===")


if __name__ == "__main__":
    main()
