"""Runtime configuration and filesystem paths."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("WINDFALL_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = Path(os.environ.get("WINDFALL_DB", DATA_DIR / "windfall.duckdb"))

CACHE_DIR = DATA_DIR / "cache"
RESULTS_DIR = DATA_DIR / "results"
UNIVERSE_DIR = DATA_DIR / "universe"

# Default benchmark used when a strategy does not name one explicitly.
DEFAULT_BENCHMARK = "NIFTY500"

# yfinance fetch politeness — keep the server off Yahoo's rate-limit radar.
FETCH_BATCH_SIZE = int(os.environ.get("WINDFALL_FETCH_BATCH", "25"))
FETCH_SLEEP_SECONDS = float(os.environ.get("WINDFALL_FETCH_SLEEP", "1.5"))
FETCH_MAX_RETRIES = int(os.environ.get("WINDFALL_FETCH_RETRIES", "4"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, RESULTS_DIR, UNIVERSE_DIR):
        d.mkdir(parents=True, exist_ok=True)
