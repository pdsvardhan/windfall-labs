"""iter-8: screener historical fundamentals wired into the engine (durability), point-in-time + lag.

Each test gets an ISOLATED screener_fundamentals.duckdb (monkeypatched to a per-test tmp_path) so the
seeded history never leaks into other tests — a durability strategy is only history-backed when the
screener store actually has data, which is exactly the invariant under test.
"""
import duckdb
import pandas as pd
import pytest

from windfall.data import fundamentals as fund

_LAG = fund.PIT_LAG_DAYS  # 120

_DDL = """CREATE TABLE IF NOT EXISTS fundamentals_history (
    ticker VARCHAR NOT NULL, period_end DATE NOT NULL, basis VARCHAR NOT NULL,
    confidence VARCHAR, roe DOUBLE, opm DOUBLE, np_yoy DOUBLE,
    net_profit_owner DOUBLE, total_assets DOUBLE,
    PRIMARY KEY (ticker, period_end, basis))"""


@pytest.fixture
def seed_screener(tmp_path, monkeypatch):
    path = tmp_path / "screener_fundamentals.duckdb"
    monkeypatch.setattr(fund, "SCREENER_DB_PATH", path)   # isolate: functions read this global at call time

    def _seed(rows):
        con = duckdb.connect(str(path))
        con.execute(_DDL)
        con.execute("DELETE FROM fundamentals_history")
        for r in rows:
            con.execute(
                "INSERT INTO fundamentals_history "
                "(ticker, period_end, basis, confidence, roe, opm, np_yoy, net_profit_owner, total_assets) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [r["ticker"], r["period_end"], "consolidated", r.get("confidence", "high"),
                 r.get("roe"), r.get("opm"), r.get("np_yoy"),
                 r.get("net_profit_owner"), r.get("total_assets")])
        con.close()
    return _seed


def _known(period_end: str) -> pd.Timestamp:
    return pd.Timestamp(period_end) + pd.Timedelta(days=_LAG)


# ── point-in-time / no look-ahead ────────────────────────────────────────────
def test_screener_history_panel_no_lookahead(seed_screener):
    seed_screener([
        {"ticker": "AAA.NS", "period_end": "2020-03-31", "roe": 18.0},
        {"ticker": "AAA.NS", "period_end": "2021-03-31", "roe": 20.0},
    ])
    dates = pd.bdate_range("2020-01-01", "2021-12-31")
    panel = fund.screener_history_panel("roe", dates, ["AAA.NS"])
    k1, k2 = _known("2020-03-31"), _known("2021-03-31")
    assert panel.loc[panel.index < k1, "AAA.NS"].isna().all()           # FY2020 not public yet
    mid = panel.loc[(panel.index >= k1) & (panel.index < k2), "AAA.NS"].dropna()
    assert (mid == 18.0).all() and len(mid) > 0
    assert (panel.loc[panel.index >= k2, "AAA.NS"].dropna() == 20.0).all()


def test_screener_history_roa_computed(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2020-03-31",
                    "net_profit_owner": 100.0, "total_assets": 1000.0}])
    dates = pd.bdate_range("2020-01-01", "2021-06-30")
    panel = fund.screener_history_panel("roa", dates, ["AAA.NS"])
    after = panel.loc[panel.index >= _known("2020-03-31"), "AAA.NS"].dropna()
    assert (after == 10.0).all() and len(after) > 0                      # 100/1000*100


def test_screener_history_excludes_quarantined(seed_screener):
    seed_screener([
        {"ticker": "GOOD.NS", "period_end": "2020-03-31", "roe": 15.0, "confidence": "high"},
        {"ticker": "LOWC.NS", "period_end": "2020-03-31", "roe": 12.0, "confidence": "low"},
        {"ticker": "BAD.NS", "period_end": "2020-03-31", "roe": 99.0, "confidence": "quarantined"},
    ])
    dates = pd.bdate_range("2020-06-01", "2021-06-30")
    panel = fund.screener_history_panel("roe", dates, ["GOOD.NS", "LOWC.NS", "BAD.NS"])
    k = _known("2020-03-31")
    assert (panel.loc[panel.index >= k, "GOOD.NS"].dropna() == 15.0).all()
    assert (panel.loc[panel.index >= k, "LOWC.NS"].dropna() == 12.0).all()   # 'low' kept
    assert panel["BAD.NS"].isna().all()                                      # quarantined excluded


def test_screener_history_uncovered_field_is_none(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2020-03-31", "roe": 15.0}])
    dates = pd.bdate_range("2020-06-01", "2020-12-31")
    assert fund.screener_history_panel("pe", dates, ["AAA.NS"]) is None       # pe not covered


def test_screener_history_unavailable_db_is_none(tmp_path, monkeypatch):
    # missing store -> None (caller falls back to the snapshot; a backtest never crashes)
    monkeypatch.setattr(fund, "SCREENER_DB_PATH", tmp_path / "does_not_exist.duckdb")
    dates = pd.bdate_range("2020-06-01", "2020-12-31")
    assert fund.screener_history_panel("roe", dates, ["AAA.NS"]) is None
    assert fund.screener_coverage()["available"] is False


def test_screener_coverage(seed_screener):
    seed_screener([
        {"ticker": "AAA.NS", "period_end": "2018-03-31", "roe": 15.0},
        {"ticker": "BBB.NS", "period_end": "2020-03-31", "roe": 12.0},
    ])
    cov = fund.screener_coverage()
    assert cov["available"] and cov["tickers"] == 2
    assert cov["history_from"] == str(_known("2018-03-31").date())            # earliest + lag


# ── readiness honesty ────────────────────────────────────────────────────────
def test_readiness_durability_rank_is_history_backed(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "roe": 15.0, "opm": 20.0,
                    "np_yoy": 5.0, "net_profit_owner": 50.0, "total_assets": 500.0}])
    from windfall.strategy.readiness import data_readiness
    cfg = {"name": "d", "universe": {"index": "nifty500", "filters": []},
           # durability_own removed (adr-019); roe is the history-backed durability input it was built on
           "rank_blend": [{"factor": "roe", "weight": 1.0}],
           "start": "2018-06-01", "end": "2019-06-01"}
    r = data_readiness(cfg)
    assert r["screener_history"]["available"]
    assert r["verdict"] == "price-backtestable"
    assert "history-backed" in r["summary"]                                  # not the old snapshot-only line


def test_readiness_history_backed_filter_not_live_only(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "roe": 18.0}])
    from windfall.strategy.readiness import data_readiness
    cfg = {"name": "f", "universe": {"index": "nifty500", "filters": ["roe > 15"]},
           "rank_by": "roc21", "start": "2018-06-01", "end": "2019-06-01"}
    r = data_readiness(cfg)
    assert r["verdict"] == "backtestable"                                    # was "live-only"
    assert r["backtestable_from"] == fund.screener_coverage()["history_from"]
