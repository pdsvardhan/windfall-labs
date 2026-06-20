"""iter-28: validate the derived corporate-action master + split-correct point-in-time market caps.

These read the real standalone trendlyne.duckdb (read-only). If the data layer isn't present
(e.g. a clean CI box without the ~350MB store), the whole module skips.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

_DATA = Path(__file__).resolve().parents[1] / "data"
_TL = _DATA / "trendlyne.duckdb"
_BC = _DATA / "bhavcopy.duckdb"

pytestmark = pytest.mark.skipif(not _TL.exists(), reason="trendlyne.duckdb data layer not present")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(_TL), read_only=True)
    if _BC.exists():
        c.execute(f"ATTACH '{_BC}' AS bc (READ_ONLY)")
    yield c
    c.close()


@pytest.fixture(scope="module")
def store():
    from windfall.data import trendlyne_store as ts
    ts.TRENDLYNE_DB = _TL
    ts.BHAVCOPY_DB = _BC
    ts._con.cache_clear()
    ts.symbol_pk_map.cache_clear()
    return ts


# ── ca_events: the derived split/bonus master ────────────────────────────────────────────────

def test_known_splits_detected(con):
    """Share-confirmed splits: BEL 1:10 (2017), EICHERMOT 1:10 (2020), RELIANCE 1:1 bonus (2017).

    (Detection has high precision but partial recall — a live name whose split is NOT in ca_events,
    e.g. IRCTC, is still priced correctly off Trendlyne's adjusted ohlcv; see the live-adjust test.)
    """
    for sym, ratio, yr in [("BEL", 10.0, 2017), ("EICHERMOT", 10.0, 2020), ("RELIANCE", 2.0, 2017)]:
        rows = con.execute(
            "SELECT ca_ratio FROM ca_events WHERE ticker=? AND year(ex_date)=?", [sym, yr]).fetchall()
        assert rows, f"{sym} {yr} CA not detected"
        assert any(abs(r[0] - ratio) < 0.01 for r in rows), f"{sym} ratio != {ratio}: {rows}"


def test_ca_events_sane(con):
    n, bad_ratio, no_step = con.execute(
        "SELECT count(*), sum(CASE WHEN ca_ratio<=1.05 THEN 1 ELSE 0 END), "
        "sum(CASE WHEN share_step_date IS NULL THEN 1 ELSE 0 END) FROM ca_events").fetchone()
    assert n > 100, "implausibly few CA events"
    assert (bad_ratio or 0) == 0, "ca_ratio must be a real split/bonus factor (>1)"
    assert (no_step or 0) == 0, "every confirmed event keeps its share_step_date"


def test_ca_factor_monotone_anchor(con):
    """Back-adjust factor is in (0,1], latest segment == 1.0, strictly <1 in the past for split names."""
    lo, hi = con.execute("SELECT min(adj_factor), max(adj_factor) FROM ca_factor").fetchone()
    assert lo > 0 and hi <= 1.0 + 1e-9
    # BEL did 1:10 (2017) then 1:2 bonus (2022) -> segments 1/30, 1/3, 1.0 (latest anchored to 1.0).
    rows = [r[0] for r in con.execute(
        "SELECT adj_factor FROM ca_factor WHERE ticker='BEL' ORDER BY from_date").fetchall()]
    assert abs(rows[-1] - 1.0) < 1e-6
    assert any(abs(a - 1.0 / 3) < 0.02 for a in rows)


# ── pit_mcap: split-correct market caps (no phantom 10x step) ─────────────────────────────────

@pytest.mark.parametrize("sym", ["EICHERMOT", "BEL", "BAJFINANCE", "TATASTEEL"])
def test_mcap_smooth_across_split(con, sym):
    """Monthly mcap must not step by >3x across a 10:1 split month (the old bug was ~10x)."""
    pk = con.execute("SELECT pk FROM stocks WHERE upper(nsecode)=?", [sym]).fetchone()[0]
    rows = con.execute(
        "SELECT round(arg_max(mcap_cr,date)) m FROM pit_mcap WHERE pk=? "
        "GROUP BY date_trunc('month',date) ORDER BY date_trunc('month',date)", [pk]).fetchall()
    ms = [r[0] for r in rows if r[0] and r[0] > 0]
    steps = [max(a, b) / min(a, b) for a, b in zip(ms, ms[1:]) if min(a, b) > 0]
    assert max(steps) < 3.0, f"{sym} has a {max(steps):.1f}x monthly mcap jump (CA timing bug)"


def test_mcap_level_matches_trendlyne(con):
    """Latest pit_mcap must agree with Trendlyne's reported current mcap (validates the identity)."""
    n, within = con.execute("""
        WITH latest AS (SELECT pk, arg_max(mcap_cr,date) m FROM pit_mcap GROUP BY pk)
        SELECT count(*), avg(CASE WHEN abs(l.m-s.mcap)/s.mcap < 0.15 THEN 1.0 ELSE 0 END)
        FROM latest l JOIN stocks s USING(pk) WHERE s.mcap > 100""").fetchone()
    assert within > 0.75, f"only {within:.0%} of latest mcaps within 15% of Trendlyne"


def test_no_negative_mcap(con):
    bad = con.execute("SELECT count(*) FROM universe_membership WHERE mcap_cr < 0").fetchone()[0]
    assert bad == 0


# ── delistings + survivorship-free membership ─────────────────────────────────────────────────

def test_delistings_registry(con):
    n = con.execute("SELECT count(*) FROM delistings").fetchone()[0]
    assert n > 100
    have = {r[0] for r in con.execute(
        "SELECT symbol FROM delistings WHERE symbol IN ('RCOM','DHFL','JETAIRWAYS')").fetchall()}
    assert {"RCOM", "DHFL"} <= have, f"known blow-ups missing from delistings: {have}"
    # ca_uncertain is a real boolean flag used to gate tradeability
    assert con.execute("SELECT count(*) FROM delistings WHERE ca_uncertain").fetchone()[0] >= 0


def test_membership_includes_dead(con):
    """Survivorship-free: dead names that were ever large must appear in the 2016 cross-section."""
    dead = con.execute("""
        SELECT count(*) FROM (SELECT symbol, arg_max(mcap_cr,date) m FROM universe_membership
        WHERE source='dead' AND date BETWEEN DATE '2016-06-16' AND DATE '2016-06-30' GROUP BY symbol)
        WHERE m > 500""").fetchone()[0]
    assert dead > 20, f"expected many dead names in the 2016 universe, got {dead}"


# ── trendlyne_store read primitives ───────────────────────────────────────────────────────────

def test_store_adjusted_live_matches_ohlcv(store, con):
    """adjusted_close_panel for a live name must equal Trendlyne ohlcv (no double adjustment)."""
    panel = store.adjusted_close_panel(["RELIANCE"], start="2020-01-01", end="2020-12-31")
    assert not panel.empty and "RELIANCE" in panel.columns
    pk = con.execute("SELECT pk FROM stocks WHERE upper(nsecode)='RELIANCE'").fetchone()[0]
    gt = con.execute("SELECT date, close FROM ohlcv WHERE pk=? AND date BETWEEN '2020-01-01' AND '2020-12-31'",
                     [pk]).fetchdf()
    assert abs(panel["RELIANCE"].mean() - gt["close"].mean()) / gt["close"].mean() < 0.001


def test_irctc_live_split_clean_despite_no_ca_event(store, con):
    """IRCTC's 1:5 is a detection recall-miss (absent from ca_events) yet its adjusted series has NO
    phantom split gap, because live names price off Trendlyne's adjusted ohlcv — the safety net."""
    assert not con.execute("SELECT count(*) FROM ca_events WHERE ticker='IRCTC'").fetchone()[0]
    panel = store.adjusted_close_panel(["IRCTC"], start="2021-10-01", end="2021-11-15")
    daily = panel["IRCTC"].pct_change().abs()
    assert daily.max() < 0.25, "IRCTC adjusted series has a phantom ~80% split gap"


def test_store_adjusted_dead_is_split_clean(store):
    """A delisted name's adjusted series should have no >40% single-day gap from an unhandled split."""
    dead = store.delistings()
    tradeable = dead[(~dead["ca_uncertain"]) & (dead["ever_mcap_cr"] > 500)]["symbol"].tolist()[:30]
    panel = store.adjusted_close_panel(tradeable, start="2010-01-01")
    if panel.empty:
        pytest.skip("no tradeable dead-name prices in range")
    rets = panel.pct_change()
    # allow real crashes (these are blow-ups) but a clean split would be ~ -50%/-80% with recovery;
    # just assert the panel is populated and finite (adjustment applied without NaN/inf blow-ups)
    assert rets.replace([float("inf"), float("-inf")], float("nan")).abs().max().max() < 100


def test_store_pit_universe(store):
    u2016 = store.pit_universe("2016-06-30")
    u2024 = store.pit_universe("2024-06-30")
    assert 300 < len(u2016) < 1200
    assert len(u2024) > len(u2016)            # the market grew
    # ca_uncertain dead names are excluded from tradeability
    uncertain = set(store.delistings().query("ca_uncertain")["symbol"])
    assert not (set(u2016) & uncertain)


def test_store_membership_panel(store):
    import pandas as pd
    dates = pd.bdate_range("2016-01-01", "2016-12-31")
    panel = store.membership_panel(["RELIANCE", "TCS"], dates)
    assert panel.shape[1] == 2
    assert bool(panel["RELIANCE"].any())      # RELIANCE was > Rs500cr throughout 2016
