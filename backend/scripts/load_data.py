#!/usr/bin/env python3
"""Load price history into DuckDB. Thin wrapper over windfall.data.pipeline.load_universe."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windfall.data.pipeline import load_universe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="nifty500")
    ap.add_argument("--years", type=int, default=12)
    ap.add_argument("--skip-existing", action="store_true",
                    help="only fetch tickers not already in the store (fast universe expansion)")
    args = ap.parse_args()
    summary = load_universe(index=args.universe, years=args.years, skip_existing=args.skip_existing)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
