#!/usr/bin/env python3
"""Ingest Trendlyne Data Downloader exports into the point-in-time fundamentals table.

    python scripts/ingest_fundamentals.py file1.xlsx file2.xlsx file3.xlsx [--snapshot YYYY-MM-DD]

Snapshot date defaults to the latest price bar so live signals pick the fundamentals up.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windfall.data.fundamentals import coverage, ingest  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="Trendlyne .xlsx exports (column groups)")
    ap.add_argument("--snapshot", default=None, help="snapshot date YYYY-MM-DD")
    args = ap.parse_args()
    summary = ingest(args.files, snapshot_date=args.snapshot)
    summary["coverage"] = coverage()
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
