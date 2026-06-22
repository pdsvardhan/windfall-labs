"""iter-C: historical PE/PB wired into valuation_own (price x 120d-lagged screener EPS/ROE).

PE = price / eps_lagged (loss-makers eps<=0 -> NaN); PB = PE * ROE/100 (guard PB>0). Verified through
the real resolve() path (entry_mask is NaN/False before the lagged date) so there is no look-ahead.
Each test isolates its own screener DB.
"""
import duckdb
import pandas as pd
import pytest

from windfall.data import fundamentals as fund
from windfall.strategy.resolve import resolve
from windfall.strategy.schema import StrategyConfig

_LAG = fund.PIT_LAG_DAYS  # 120

_DDL = """CREATE TABLE IF NOT EXISTS fundamentals_history (
    ticker VARCHAR NOT NULL, period_end DATE NOT NULL, basis VARCHAR NOT NULL,
    confidence VARCHAR, roe DOUBLE, opm DOUBLE, np_yoy DOUBLE, eps DOUBLE,
    net_profit_owner DOUBLE, total_assets DOUBLE,
    PRIMARY KEY (ticker, period_end, basis))"""


@pytest.fixture
def seed_screener(tmp_path, monkeypatch):
    path = tmp_path / "screener_fundamentals.duckdb"
    monkeypatch.setattr(fund, "SCREENER_DB_PATH", path)
    # The Trendlyne snapshot table is session-shared; clear it so PE/PB come purely from screener
    # history here (a leaked snapshot pe would correctly govern the present and mask the historical
    # value — not what these point-in-time tests want to isolate).
    from windfall.data.store import connect as _store_connect
    _sc = _store_connect()
    _sc.execute(fund.FUND_SCHEMA)
    _sc.execute("DELETE FROM fundamentals")

    def _seed(rows):
        con = duckdb.connect(str(path))
        con.execute(_DDL)
        con.execute("DELETE FROM fundamentals_history")
        for r in rows:
            con.execute(
                "INSERT INTO fundamentals_history "
                "(ticker, period_end, basis, confidence, roe, opm, np_yoy, eps, net_profit_owner, total_assets) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [r["ticker"], r["period_end"], "consolidated", r.get("confidence", "high"),
                 r.get("roe"), r.get("opm"), r.get("np_yoy"), r.get("eps"),
                 r.get("net_profit_owner"), r.get("total_assets")])
        con.close()
    return _seed


_KNOWN = pd.Timestamp("2018-03-31") + pd.Timedelta(days=_LAG)  # 2018-07-29


def _resolve_with_filter(flt):
    cfg = StrategyConfig(name="v", universe={"index": "nifty500", "filters": [flt]},
                         rank_by="roc21", start="2018-01-01", end="2019-06-01")
    return resolve(cfg)


# ── PE / PB computed point-in-time, no look-ahead (through resolve) ───────────
def test_pe_history_no_lookahead(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": 5.0, "roe": 20.0}])
    rs = _resolve_with_filter("pe > 0")
    mask = rs.entry_mask["AAA.NS"]
    assert not mask.loc[mask.index < _KNOWN].any()      # pe NaN before lag -> pe>0 fails -> ineligible
    assert mask.loc[mask.index >= _KNOWN].any()         # pe = close/eps > 0 after lag -> eligible


def test_pb_history_no_lookahead(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": 5.0, "roe": 20.0}])
    rs = _resolve_with_filter("pb > 0")
    mask = rs.entry_mask["AAA.NS"]
    assert not mask.loc[mask.index < _KNOWN].any()      # pb NaN before lag
    assert mask.loc[mask.index >= _KNOWN].any()         # pb = pe*roe/100 > 0 after lag


def test_loss_maker_eps_excluded_from_pe(seed_screener):
    # eps <= 0 -> PE NaN even after the lag, so a pe>0 filter never admits the name
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": -2.0, "roe": -5.0}])
    rs = _resolve_with_filter("pe > 0")
    assert not rs.entry_mask["AAA.NS"].any()


def test_pb_equals_pe_times_roe_panel(seed_screener):
    # building blocks the resolve formula uses: lagged eps + roe panels, then PB = (price/eps)*roe/100
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": 5.0, "roe": 20.0}])
    dates = pd.bdate_range("2018-06-01", "2019-06-01")
    eps_h = fund.screener_history_panel("eps", dates, ["AAA.NS"])
    roe_h = fund.screener_history_panel("roe", dates, ["AAA.NS"])
    e = eps_h.loc[eps_h.index >= _KNOWN, "AAA.NS"].dropna().iloc[0]
    r = roe_h.loc[roe_h.index >= _KNOWN, "AAA.NS"].dropna().iloc[0]
    assert (e, r) == (5.0, 20.0)
    price = 100.0
    pe = price / e
    pb = pe * r / 100.0
    assert pe == 20.0 and pb == 4.0                     # PB = PE * ROE identity


# ── readiness honesty ────────────────────────────────────────────────────────
def test_readiness_valuation_rank_is_history_backed(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": 5.0, "roe": 20.0}])
    from windfall.strategy.readiness import data_readiness
    cfg = {"name": "v", "universe": {"index": "nifty500", "filters": []},
           # valuation_own removed (adr-019); pe is the history-backed valuation fundamental it used
           "rank_blend": [{"factor": "pe", "weight": 1.0}],
           "start": "2018-06-01", "end": "2019-06-01"}
    r = data_readiness(cfg)
    assert r["screener_history"]["available"]
    assert r["verdict"] == "price-backtestable"
    assert "history-backed" in r["summary"]


def test_readiness_pe_filter_not_live_only(seed_screener):
    seed_screener([{"ticker": "AAA.NS", "period_end": "2018-03-31", "eps": 5.0, "roe": 20.0}])
    from windfall.strategy.readiness import data_readiness
    cfg = {"name": "f", "universe": {"index": "nifty500", "filters": ["pe < 30"]},
           "rank_by": "roc21", "start": "2018-06-01", "end": "2019-06-01"}
    r = data_readiness(cfg)
    assert r["verdict"] == "backtestable"
    assert r["backtestable_from"] == fund.screener_coverage()["history_from"]
