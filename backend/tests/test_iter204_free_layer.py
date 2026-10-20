"""iter-204 (adr-050): free prices and a point-in-time universe.

Pins, on synthetic stores so the expectations are exact:
  - corporate actions: combined subjects multiply (#958), rights issues parse in NSE's many
    wordings and price at P/TERP, duplicates collapse, share scaling ignores rights
  - names Trendlyne has no bars for are priced from Bhavcopy adjusted with NSE's events
  - the NSE gate is point-in-time: not before the first EQ bar, not while the NSE line is idle
  - membership reads Trendlyne before MCAP_CUTOVER and NSE's official market cap from it, and
    the companies Trendlyne never listed enter (#959)
  - the gap detector flags an unannounced split-shaped move and nothing else
  - the MCAP ingest parses NSE's file and maps tickers to companies by ISIN
"""
import datetime as dt
import io
import zipfile

import duckdb
import pandas as pd
import pytest

from windfall.data import corp_actions, gap_check
from windfall.data import trendlyne_store as ts
from windfall.store_meta import _init

D = dt.date


# ── corporate-action parsing ─────────────────────────────────────────────────

@pytest.mark.parametrize("subject,kinds,ratio", [
    ("Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-", "bonus+split", 20.0),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", 5.0),
    ("Bonus 1:2", "bonus", 1.5),
    ("Demerger", "demerger", None),
    ("Rights 1:5 @ Premium Rs 45/-", "rights", None),
    ("Dividend - Rs 5 Per Share", None, None),
])
def test_parse_all_multiplies_combined_subjects(subject, kinds, ratio):
    k, r = corp_actions.parse_all(subject)
    assert k == kinds
    assert (r is None and ratio is None) or r == pytest.approx(ratio)


@pytest.mark.parametrize("subject,expected", [
    ("Rights 1:5 @ Premium Rs 45/-", (1, 5, 45)),
    ("Rights 2:3@Prem Rs.345/-", (2, 3, 345)),
    ("Rights Issue - 3:5 @ Premium Rs.93/-", (3, 5, 93)),
    ("Rights At 2:1 At A Premium Of Rs.39.50 Per Share", (2, 1, 39.5)),
    ("Rights 7:10 @ Prm Rs 102/-", (7, 10, 102)),
    ("Rights - 2:3@ Par Rs 10 Per Share", (2, 3, 0)),
    ("Rights : 24:10 At Par", (24, 10, 0)),
    ("Rights 1:11.10 @ Premium Rs 0/-", (1, 11.1, 0)),
    ("Rights Eq 1:20 @ Premium Rs.715 Per Share And 3 Warrants : 1 Eq", (1, 20, 715)),
    ("Rights 2:7", None),                                          # no price stated
    ("Rights 9:77 Partly Paid @ Premium Rs 100/-", None),          # partly paid
    ("Rights:14 Compulosry Convertible Debentures For Every 15 Equity Shares", None),
    ("To Distribute Net Proceeds From The Sale Of Rights Entitlement", None),
])
def test_rights_subjects_parse_in_nse_wordings(subject, expected):
    got = corp_actions.parse_rights(subject)
    assert got == (pytest.approx(expected) if expected else None)


def test_rights_ratio_is_p_over_terp_and_skips_issues_at_or_above_market():
    # 1 new for 5 held at Rs 10 + 40 = 50 with the stock at 110: TERP = (5*110 + 50)/6 = 100
    assert corp_actions.rights_ratio("Rights 1:5 @ Premium Rs 40/-", 10.0, 110.0) == pytest.approx(1.1)
    assert corp_actions.rights_ratio("Rights 1:5 @ Premium Rs 100/-", 10.0, 110.0) is None
    assert corp_actions.rights_ratio("Rights 2:7", 10.0, 110.0) is None


def test_rights_are_priced_from_the_close_before_the_ex_date_and_future_ones_wait():
    rows = [{"symbol": "R", "ex_date": D(2025, 3, 3), "subject": "Rights 1:5 @ Premium Rs 40/-",
             "kind": "rights", "ratio": None, "face_value": 10.0},
            {"symbol": "R", "ex_date": D(2099, 1, 1), "subject": "Rights 1:5 @ Premium Rs 40/-",
             "kind": "rights", "ratio": None, "face_value": 10.0},
            {"symbol": "S", "ex_date": D(2025, 3, 3), "subject": "Bonus 1:1", "kind": "bonus",
             "ratio": 2.0, "face_value": 10.0}]
    seen = []
    n = corp_actions.price_rights(rows, last_close_before=lambda s, d: seen.append((s, d)) or 110.0)
    assert n == 1 and seen == [("R", D(2025, 3, 3))]
    assert rows[0]["ratio"] == pytest.approx(1.1)
    assert rows[1]["ratio"] is None and rows[2]["ratio"] == 2.0


def test_duplicate_filings_collapse_and_share_events_ignore_rights():
    win = (D(2032, 1, 1), D(2032, 12, 31))
    base = {"symbol": "T204DUP", "record_date": None, "face_value": 10.0}
    try:
        corp_actions.ingest([
            {**base, "ex_date": D(2032, 2, 1), "subject": "Split From Rs 10 To Rs 2", "kind": "split", "ratio": 5.0},
            {**base, "ex_date": D(2032, 2, 1), "subject": "Face Value Split From Rs 10 To Rs 2", "kind": "split", "ratio": 5.0},
            {**base, "ex_date": D(2032, 6, 1), "subject": "Rights 1:5 @ Premium Rs 40/-", "kind": "rights", "ratio": 1.1},
        ], win)
        assert corp_actions.ratio_events(["T204DUP"]) == {
            "T204DUP": [(D(2032, 2, 1), 5.0), (D(2032, 6, 1), 1.1)]}
        assert corp_actions.share_events(["T204DUP"]) == {"T204DUP": [(D(2032, 2, 1), 5.0)]}
    finally:
        _init().execute("DELETE FROM nse_corporate_actions WHERE symbol='T204DUP'")


def test_back_adjustment_divides_bars_before_each_ex_date_in_the_names_own_history():
    idx = pd.bdate_range("2025-01-01", periods=6)
    w = pd.DataFrame({"A": [100, 100, 20, 21, 22, 23.0], "B": [50, 51, 52, 53, 54, 55.0]}, index=idx)
    out = ts.apply_corporate_actions(w.copy(), {"A": [(idx[2].date(), 5.0)],
                                                "B": [(D(2026, 1, 1), 2.0)]})   # after B's last bar
    assert list(out["A"]) == [20, 20, 20, 21, 22, 23]
    assert list(out["B"]) == list(w["B"])


# ── a synthetic Trendlyne + Bhavcopy + NSE-layer store ───────────────────────

def _store(tmp=None):
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE universe_membership (symbol VARCHAR, date DATE, mcap_cr DOUBLE);
        CREATE TABLE stocks (pk INTEGER, nsecode VARCHAR, name VARCHAR, mcap DOUBLE,
                             d_now DOUBLE, v_now DOUBLE, m_now DOUBLE);
        CREATE TABLE recovered_symbols (pk INTEGER, nse_symbol VARCHAR);
        CREATE TABLE delistings (symbol VARCHAR, last_date DATE, last_raw_close DOUBLE,
                                 ever_mcap_cr DOUBLE, ca_uncertain BOOLEAN);
        CREATE TABLE ohlcv (pk INTEGER, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
                            close DOUBLE, volume DOUBLE);
        CREATE TABLE pit_mcap (pk INTEGER, date DATE, shares_cr DOUBLE);
        CREATE TABLE ca_factor (ticker VARCHAR, from_date DATE, adj_factor DOUBLE);
        ATTACH ':memory:' AS bc;
        CREATE TABLE bc.bhavcopy_prices (date DATE, ticker VARCHAR, isin VARCHAR, series VARCHAR,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, last DOUBLE, prev_close DOUBLE,
            volume DOUBLE, turnover DOUBLE, n_trades DOUBLE);
        ATTACH ':memory:' AS nl;
        CREATE TABLE nl.mcap_daily (date DATE, symbol VARCHAR, series VARCHAR, face_value DOUBLE,
            issue_size DOUBLE, close DOUBLE, mcap_cr DOUBLE);
        CREATE TABLE nl.ticker_map (ticker VARCHAR, engine_symbol VARCHAR, isin_group VARCHAR,
            in_trendlyne BOOLEAN);
        CREATE TABLE nl.companies (engine_symbol VARCHAR, isin_group VARCHAR, in_trendlyne BOOLEAN,
            has_membership BOOLEAN, first_mcap_date DATE, first_mcap_cr DOUBLE, max_mcap_cr DOUBLE,
            survivor BOOLEAN);
    """)
    return con


_CACHED = ("symbol_pk_map", "_nse_symbols", "_ticker_aliases", "_first_eq_by_ticker", "survivors",
           "_survivor_pre_mcap", "_ohlcv_pks", "ca_uncertain_symbols")


@pytest.fixture
def fake(monkeypatch):
    con = _store()
    for f in _CACHED:
        getattr(ts, f).cache_clear()
    monkeypatch.setattr(ts, "_con", lambda: con)
    monkeypatch.setattr(corp_actions, "ratio_events", lambda syms: {})
    yield con
    for f in _CACHED:
        getattr(ts, f).cache_clear()


def _bars(con, ticker, isin, series, days, close=100.0):
    for d in days:
        con.execute("INSERT INTO bc.bhavcopy_prices (date, ticker, isin, series, close, open, high, low) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [d, ticker + ".NS", isin, series, close, close, close, close])


def test_gate_is_closed_before_the_first_eq_bar_and_while_the_nse_line_is_idle(fake):
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    _bars(fake, "LATE", "INE000A01011", "EQ", days[days >= "2023-07-03"])      # joins NSE in July
    _bars(fake, "IDLE", "INE000B01011", "EQ", days[days < "2023-03-01"])       # NSE line goes quiet
    g = ts.nse_gate_panel(["LATE", "IDLE"], days)
    assert not g.loc[:"2023-06-30", "LATE"].any() and g.loc["2023-07-03":, "LATE"].all()
    assert g.loc["2023-01-02":"2023-05-29", "IDLE"].all()      # traded within 90 days
    assert not g.loc["2023-06-01":, "IDLE"].any()              # 90+ days without an NSE trade
    assert ts.nse_gate_at(["LATE", "IDLE"], "2023-08-01") == {"LATE"}
    assert ts.nse_gate_at(["LATE", "IDLE"], "2023-02-01") == {"IDLE"}


def test_gate_counts_a_renamed_companys_old_ticker(fake):
    days = pd.bdate_range("2023-01-02", "2023-06-30")
    _bars(fake, "OLDNAME", "INE000C01011", "EQ", days[days < "2023-04-03"])
    _bars(fake, "NEWNAME", "INE000C01011", "EQ", days[days >= "2023-04-03"])
    g = ts.nse_gate_panel(["NEWNAME"], days)
    assert g["NEWNAME"].all(), "the company listed in January under its old ticker"


def test_membership_switches_to_nse_official_market_cap_at_the_cutover(fake):
    days = pd.bdate_range("2024-01-15", "2024-02-28")
    _bars(fake, "BIGCO", "INE000D01011", "EQ", pd.bdate_range("2023-01-02", "2024-02-28"))
    fake.execute("INSERT INTO universe_membership SELECT 'BIGCO', d, 900.0 FROM "
                 "unnest(generate_series(DATE '2024-01-01', DATE '2024-02-28', INTERVAL 1 DAY)) t(d)")
    fake.execute("INSERT INTO nl.ticker_map VALUES ('BIGCO', 'BIGCO', 'g1', true)")
    fake.execute("INSERT INTO nl.mcap_daily SELECT d, 'BIGCO', 'EQ', 10, 1, 1, 400.0 FROM "
                 "unnest(generate_series(DATE '2024-02-01', DATE '2024-02-28', INTERVAL 1 DAY)) t(d)")
    m = ts.membership_panel(["BIGCO"], days)
    assert m.loc[:"2024-01-31", "BIGCO"].all(), "Trendlyne's 900 before the cutover"
    assert not m.loc["2024-02-01":, "BIGCO"].any(), "NSE's official 400 from it"
    assert ts.universe_over_window("2024-01-01", "2024-01-31") == ["BIGCO"]
    assert ts.universe_over_window("2024-02-01", "2024-02-28") == []


def test_a_company_trendlyne_never_listed_enters_with_prices_and_membership(fake):
    days = pd.bdate_range("2023-10-02", "2024-03-29")
    _bars(fake, "GONECO", "INE000E01011", "EQ", days, close=50.0)
    fake.execute("INSERT INTO nl.ticker_map VALUES ('GONECO', 'GONECO', 'g2', false)")
    fake.execute("INSERT INTO nl.mcap_daily SELECT d, 'GONECO', 'EQ', 10, 1, 50, 800.0 FROM "
                 "unnest(generate_series(DATE '2024-02-01', DATE '2024-03-29', INTERVAL 1 DAY)) t(d)")
    fake.execute("INSERT INTO nl.companies VALUES ('GONECO', 'g2', false, false, DATE '2024-02-01', "
                 "800.0, 800.0, true)")
    assert "GONECO" in ts.survivors()
    px = ts.adjusted_close_panel(["GONECO"], "2023-10-01", "2024-03-29")
    assert px["GONECO"].dropna().iloc[0] == 50.0, "priced from Bhavcopy — no Trendlyne pk needed"
    m = ts.membership_panel(["GONECO"], days)
    assert m["GONECO"].all(), "pre-cutover: adjusted close x the share count of its first MCAP reading"
    assert "GONECO" in ts.universe_over_window("2023-10-01", "2024-01-31")
    assert ts.pit_universe("2023-12-01") == ["GONECO"]
    assert ts.pit_universe("2024-03-01") == ["GONECO"]


def test_a_trendlyne_name_without_bars_is_priced_from_bhavcopy_adjusted(fake, monkeypatch):
    days = pd.bdate_range("2026-11-02", "2026-11-13")
    fake.execute("INSERT INTO stocks VALUES (77, 'NEWIPO', 'New IPO', 1, 1, 1, 1)")
    _bars(fake, "NEWIPO", "INE000F01011", "EQ", days[:5], close=200.0)
    _bars(fake, "NEWIPO", "INE000F01011", "EQ", days[5:], close=100.0)
    monkeypatch.setattr(corp_actions, "ratio_events", lambda syms: {"NEWIPO": [(days[5].date(), 2.0)]})
    px = ts.adjusted_close_panel(["NEWIPO"], None, None)
    assert px["NEWIPO"].tolist() == [100.0] * len(days), "the 1:1 bonus is back-adjusted, not a crash"


# ── gap detector ─────────────────────────────────────────────────────────────

def test_gap_check_flags_only_an_unannounced_split_shaped_move(monkeypatch):
    idx = pd.bdate_range("2026-10-01", "2026-10-16")
    raw = pd.DataFrame({
        "SPLIT": [100.0] * 8 + [50.2] * 4,     # x1.99 overnight, nothing filed -> suspect
        "KNOWN": [100.0] * 8 + [20.0] * 4,     # x5 with an NSE split filed -> explained
        "CRASH": [100.0] * 8 + [80.0] * 4,     # x1.25: a 20% circuit move -> never flagged
        "QUIET": [100.0] * 12,
    }, index=idx)
    monkeypatch.setattr(ts, "raw_close_panel", lambda syms, start=None: raw)
    monkeypatch.setattr(corp_actions, "_rows", lambda syms, where: [
        ("KNOWN", idx[8].date(), 5.0, "split", "Face Value Split From Rs 10 To Rs 2")])
    got = gap_check.scan(raw.columns, sessions=5, today=D(2026, 10, 16))
    assert [(g["symbol"], g["canonical"]) for g in got] == [("SPLIT", 2.0)]


# ── the MCAP ingest ──────────────────────────────────────────────────────────

def test_mcap_file_parses_mainboard_rows_in_crore():
    from scripts.nse_mcap_ingest import parse_mcap
    csv = ("Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),"
           "Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n"
           "01 Feb 2024,ABC,EQ,ABC Ltd,Listed,01 Feb 2024,10,10000000,500,5000000000\n"
           "01 Feb 2024,SMEX,SM,SME Ltd,Listed,01 Feb 2024,10,100,5,500\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("MCAP01022024.csv", csv)
    df = parse_mcap(buf.getvalue(), D(2024, 2, 1))
    assert df[["symbol", "series", "mcap_cr"]].values.tolist() == [["ABC", "EQ", 500.0]]


def test_ticker_groups_join_renames_transitively():
    from scripts.nse_mcap_ingest import _groups
    g = _groups([("ZOMATO", "INE758T01015"), ("ETERNAL", "INE758T01015"), ("ETERNAL", "INE758T01023"),
                 ("OTHER", "INE111A01011")])
    assert g["ZOMATO"] == g["ETERNAL"] != g["OTHER"]


def test_build_map_names_companies_by_their_trendlyne_symbol_and_flags_survivors(tmp_path, monkeypatch):
    import scripts.nse_mcap_ingest as ing
    bc, tl = tmp_path / "bc.duckdb", tmp_path / "tl.duckdb"
    b = duckdb.connect(str(bc))
    b.execute("CREATE TABLE bhavcopy_prices (date DATE, ticker VARCHAR, isin VARCHAR, series VARCHAR)")
    b.execute("""INSERT INTO bhavcopy_prices VALUES
        ('2023-06-01', 'ZOMATO.NS', 'INE758T01015', 'EQ'), ('2025-06-01', 'ETERNAL.NS', 'INE758T01015', 'EQ'),
        ('2025-06-01', 'SHRUNK.NS', 'INE222B01011', 'BE'), ('2025-06-01', 'NIFTYBEES.NS', 'INF204K01EY0', 'EQ')""")
    b.close()
    t = duckdb.connect(str(tl))
    t.execute("CREATE TABLE stocks (pk INTEGER, nsecode VARCHAR)")
    t.execute("INSERT INTO stocks VALUES (1, 'ETERNAL')")
    t.execute("CREATE TABLE recovered_symbols (pk INTEGER, nse_symbol VARCHAR)")
    t.execute("CREATE TABLE universe_membership (symbol VARCHAR, date DATE, mcap_cr DOUBLE)")
    t.execute("INSERT INTO universe_membership VALUES ('ETERNAL', '2025-06-01', 2e5)")
    t.execute("CREATE TABLE delistings (symbol VARCHAR)")
    t.close()
    monkeypatch.setattr(ing, "BC", bc)
    monkeypatch.setattr(ing, "TL", tl)
    con = duckdb.connect(str(tmp_path / "nl.duckdb"))
    con.execute(ing.SCHEMA)
    con.execute("""INSERT INTO mcap_daily VALUES
        ('2024-02-01', 'ZOMATO', 'EQ', 1, 1, 1, 150000), ('2024-02-01', 'SHRUNK', 'EQ', 1, 1, 1, 900),
        ('2025-06-01', 'SHRUNK', 'BE', 1, 1, 1, 300)""")
    out = ing.build_map(con)
    tm = dict(con.execute("SELECT ticker, engine_symbol FROM ticker_map").fetchall())
    assert tm == {"ZOMATO": "ETERNAL", "ETERNAL": "ETERNAL", "SHRUNK": "SHRUNK"}   # no ETF
    surv = {r[0]: r[1] for r in con.execute("SELECT engine_symbol, survivor FROM companies").fetchall()}
    assert surv == {"ETERNAL": False, "SHRUNK": True}
    assert out["trendlyne_unplaced"] == []
