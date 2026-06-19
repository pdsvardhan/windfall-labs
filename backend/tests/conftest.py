"""Test fixtures: an isolated DuckDB seeded with deterministic synthetic price data.

Env vars are set BEFORE importing windfall so the package points at a throwaway DB.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="windfall_test_"))
os.environ["WINDFALL_DATA_DIR"] = str(_TMP)
os.environ["WINDFALL_DB"] = str(_TMP / "test.duckdb")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402


def _synth(ticker: str, n: int, drift: float, seed: int, start_price: float = 100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.015, n)
    close = start_price * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    vol = rng.uniform(5e5, 5e6, n)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame(
        {"open": open_, "high": np.maximum.reduce([open_, high, close]),
         "low": np.minimum.reduce([open_, low, close]), "close": close,
         "adj_close": close, "volume": vol}, index=idx)


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    from windfall.data import store
    from windfall.data.universe import UniverseMember

    store.init_db()
    n = 700
    specs = [
        ("AAA.NS", 0.0012, 1), ("BBB.NS", 0.0008, 2), ("CCC.NS", 0.0010, 3),
        ("DDD.NS", -0.0002, 4), ("EEE.NS", 0.0006, 5), ("FFF.NS", 0.0004, 6),
    ]
    frames = {t: _synth(t, n, d, s) for t, d, s in specs}
    frames["^CRSLDX"] = _synth("^CRSLDX", n, 0.0005, 99, start_price=10000.0)
    store.upsert_prices(frames)
    members = [UniverseMember(symbol=t.replace(".NS", ""), ticker=t,
                              sector="Tech" if i % 2 else "Energy")
               for i, (t, _, _) in enumerate(specs)]
    store.record_universe("nifty500", members)
    yield store
