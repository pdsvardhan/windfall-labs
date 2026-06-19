"""Validate our own D/V/M scores against Trendlyne's snapshot scores.

Run with the api STOPPED (it opens the DuckDB host-side; never open it while the container runs):

    docker stop windfall-api
    cd /mnt/storage/websites/windfall-labs/backend && . .venv/bin/activate
    python scripts/validate_own_dvm.py
    docker start windfall-api

(Or, with the api running, just call the endpoint: GET /api/scores/own-validate.)

Prints per-component Spearman rank correlation (ours vs Trendlyne) on the snapshot cross-section.
Tune the weights in windfall/scores/own_dvm.py to raise the correlations.
"""
import json
import sys
from pathlib import Path

# Make `windfall` importable when run as a plain script (cwd isn't auto-added to sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windfall.scores.validate import validate_own_dvm  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(validate_own_dvm(), indent=2))
