#!/usr/bin/env python3
"""Run the validation harness (reproduce-Trendlyne + integrity + indicator checks)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windfall.scripts_validation import run_validation  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(run_validation(), indent=2, default=str))
