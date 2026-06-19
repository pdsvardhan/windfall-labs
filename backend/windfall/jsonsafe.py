"""Recursively replace non-finite floats (NaN/Inf) with None so payloads are strict-JSON safe.

FastAPI/Starlette reject NaN/Inf (unlike Python's json.dumps), so every engine payload that
crosses the HTTP boundary or is persisted goes through here.
"""
from __future__ import annotations

import math
from typing import Any


def clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj
