"""Validate our own D/V/M scores against Trendlyne's snapshot scores.

    cd /mnt/storage/websites/windfall-labs/backend && . .venv/bin/activate
    python scripts/validate_own_dvm.py

Prints per-component Spearman rank correlation (ours vs Trendlyne) on the snapshot cross-section.
Tune the weights in windfall/scores/own_dvm.py to raise the correlations.
"""
import json

from windfall.scores.validate import validate_own_dvm

if __name__ == "__main__":
    print(json.dumps(validate_own_dvm(), indent=2))
