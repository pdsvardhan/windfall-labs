"""Shared NSE corporate-action subject parsing for the free-layer research scripts (iter-200).

corp_actions.parse (production) reads ONE event per subject: in "Bonus 1:1 / Face Value Split From
Rs.10/- To Re.1/-" it returns the split and drops the bonus. Pre-2018 NSE filings combine events
that way (27 subjects 2010-2018), so the research layer parses every part and multiplies.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data.corp_actions import parse  # noqa: E402

# "/" joins two events but also appears inside "Rs 10/- Per Share": only a slash NOT followed by
# "-" separates.
_SEP = re.compile(r"\s*(?:/(?!-)|\band\b|&)\s*", re.I)


def parse_all(subject: str) -> float | None:
    """Price ratio of a whole NSE subject, combined events multiplied (None if none parse)."""
    ratios = [r for part in _SEP.split(subject or "") for _k, r in [parse(part)] if r]
    return float(np.prod(ratios)) if ratios else None


def kinds_all(subject: str) -> str | None:
    ks = sorted({k for part in _SEP.split(subject or "") for k, _r in [parse(part)] if k})
    return "+".join(ks) if ks else None
