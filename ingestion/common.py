"""Shared HTTP + I/O helpers for the ingestion scripts."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"

ELEXON_API_BASE = os.environ.get("ELEXON_API_BASE", "https://data.elexon.co.uk/bmrs/api/v1")
NESO_API_BASE = os.environ.get("NESO_API_BASE", "https://api.neso.energy/api/3/action")

_RETRYABLE = retry_if_exception_type((requests.exceptions.RequestException,))


@retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30),
       retry=_RETRYABLE)
def http_get_json(url: str, params: dict | None = None) -> dict:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def daterange_chunks(start: date, end: date, max_days: int = 7):
    """Yield (chunk_start, chunk_end) inclusive date pairs, each spanning at
    most max_days, covering [start, end] inclusive. Elexon's dataset endpoint
    rejects any single request spanning more than 7 days."""
    cursor = start
    step = timedelta(days=max_days - 1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def save_csv(df: pd.DataFrame, filename: str) -> Path:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_RAW_DIR / filename
    df.to_csv(out_path, index=False)
    return out_path


def utcnow_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
