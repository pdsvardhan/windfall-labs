"""Fundamentals: point-in-time panel semantics + resolver integration."""
import datetime as dt

import numpy as np
import pandas as pd

from windfall.data.fundamentals import FUND_SCHEMA, fundamental_panel
from windfall.data.store import connect


def _insert_snapshot():
    con = connect()
    con.execute(FUND_SCHEMA)
    con.execute("DELETE FROM fundamentals")
    con.execute(
        "INSERT INTO fundamentals (ticker, snapshot_date, durability, pe, sector_pe, mcap_cr, "
        "promoter_pledge) VALUES (?,?,?,?,?,?,?)",
        ["AAA.NS", dt.date(2019, 1, 1), 80.0, 10.0, 20.0, 1000.0, 0.0])


def test_point_in_time_panel_is_nan_before_snapshot():
    _insert_snapshot()
    dates = pd.bdate_range("2018-06-01", "2019-06-01")
    panel = fundamental_panel("durability", dates, ["AAA.NS", "BBB.NS"])
    snap = pd.Timestamp("2019-01-01")
    before = panel.loc[panel.index < snap, "AAA.NS"]
    after = panel.loc[panel.index >= snap, "AAA.NS"]
    assert before.isna().all()                       # no look-ahead before the snapshot
    assert (after.dropna() == 80.0).all()            # value applies on/after the snapshot
    assert panel["BBB.NS"].isna().all()              # unknown ticker -> all NaN


def test_resolver_accepts_fundamental_features(seeded_db):
    from windfall.strategy.resolve import resolve
    from windfall.strategy.schema import StrategyConfig
    _insert_snapshot()
    cfg = StrategyConfig(name="f", universe={"index": "nifty500",
                         "filters": ["durability > 50", "pe_to_sector <= 2.5"]},
                         rank_by="roc21", start="2018-06-01", end="2019-06-01")
    rs = resolve(cfg)
    # fundamental tokens are recognised (no 'unknown feature' warning for them)
    assert not any("unknown feature 'durability'" in w for w in rs.warnings)
    # the snapshot-only honesty warning is present
    assert any("snapshot" in w.lower() for w in rs.warnings)
