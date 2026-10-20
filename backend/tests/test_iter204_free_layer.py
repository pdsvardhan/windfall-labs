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
            survivor BOOLEAN, membership_symbol VARCHAR);
    """)
    return con


_CACHED = ("symbol_pk_map", "_nse_symbols", "_ticker_aliases", "_first_eq_by_ticker", "survivors",
           "_survivor_pre_mcap", "_ohlcv_pks", "ca_uncertain_symbols", "_frozen_alias", "_bhav_start")


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
                 "800.0, 800.0, true, NULL)")
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
        ('2025-06-01', 'SHRUNK.NS', 'INE222B01011', 'BE'), ('2025-06-01', 'NIFTYBEES.NS', 'INF204K01EY0', 'EQ'),
        ('2025-06-01', 'ADANI-RE.NS', 'INE423A20013', 'EQ')""")
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
        ('2025-06-01', 'SHRUNK', 'BE', 1, 1, 1, 300), ('2025-06-01', 'ADANI-RE', 'EQ', 1, 1, 1, 7000)""")
    out = ing.build_map(con)
    tm = dict(con.execute("SELECT ticker, engine_symbol FROM ticker_map").fetchall())
    assert tm == {"ZOMATO": "ETERNAL", "ETERNAL": "ETERNAL", "SHRUNK": "SHRUNK"}   # no ETF, no -RE line
    surv = {r[0]: r[1] for r in con.execute("SELECT engine_symbol, survivor FROM companies").fetchall()}
    assert surv == {"ETERNAL": False, "SHRUNK": True}
    assert out["trendlyne_unplaced"] == []


# ── iter-204 verifier round 1 regressions ────────────────────────────────────

def test_same_day_bonus_and_split_with_one_ratio_are_two_events():
    """B1: a bonus 1:1 and a split 10->5 on one day both multiply by 2 — x4, not x2."""
    win = (D(2033, 1, 1), D(2033, 12, 31))
    base = {"symbol": "T204BS", "ex_date": D(2033, 3, 1), "record_date": None, "face_value": 10.0}
    try:
        corp_actions.ingest([
            {**base, "subject": "Bonus 1:1", "kind": "bonus", "ratio": 2.0},
            {**base, "subject": "Face Value Split From Rs 10/- To Rs 5/-", "kind": "split", "ratio": 2.0},
            {**base, "subject": "Bonus 1:1 (revised)", "kind": "bonus", "ratio": 2.0},   # a re-filing
        ], win)
        assert corp_actions.ratio_events(["T204BS"]) == {"T204BS": [(D(2033, 3, 1), 2.0)] * 2}
    finally:
        _init().execute("DELETE FROM nse_corporate_actions WHERE symbol='T204BS'")


def test_an_explicit_end_after_the_freeze_still_extends_trendlyne_names(fake):
    """B2: a backtest ending after the last Trendlyne bar keeps pricing from Bhavcopy, up to `end`."""
    days = pd.bdate_range("2026-10-01", "2026-10-30")
    fake.execute("INSERT INTO stocks VALUES (5, 'FROZEN', 'Frozen Co', 1, 1, 1, 1)")
    for d in days[:8]:
        fake.execute("INSERT INTO ohlcv VALUES (5, ?, 50, 50, 50, 50, 1)", [d])
    _bars(fake, "FROZEN", "INE000G01011", "EQ", days, close=50.0)
    px = ts.adjusted_close_panel(["FROZEN"], "2026-10-01", "2026-10-20")
    assert px["FROZEN"].dropna().index.max() == pd.Timestamp("2026-10-20")
    early = ts.adjusted_close_panel(["FROZEN"], "2026-10-01", "2026-10-07")
    assert early["FROZEN"].dropna().index.max() == pd.Timestamp("2026-10-07")


def test_duplicate_trendlyne_rows_average_as_before_without_the_nse_layer(fake, monkeypatch):
    """B3: universe_membership's live+dead twins (SHALPAINTS, MAZDA) are averaged, as on master."""
    monkeypatch.setattr(ts, "_has_nl", lambda: False)
    days = pd.bdate_range("2019-04-01", "2019-04-05")
    for d in days:
        fake.execute("INSERT INTO universe_membership VALUES ('TWIN', ?, 900.0), ('TWIN', ?, 155.0)", [d, d])
    m = ts.mcap_panel(["TWIN"], days)
    assert m["TWIN"].tolist() == [527.5] * len(days)


def test_a_company_renamed_after_the_freeze_is_one_company(fake):
    """B5: frozen rows under OLD are read as NEW; OLD is not a second member before the cutover."""
    days = pd.bdate_range("2023-07-03", "2023-12-29")
    _bars(fake, "OLD", "INE000H01011", "EQ", pd.bdate_range("2023-01-02", "2023-12-29"))
    _bars(fake, "NEW", "INE000H01011", "EQ", pd.bdate_range("2024-01-01", "2024-01-05"))
    fake.execute("INSERT INTO stocks VALUES (9, 'NEW', 'Renamed Co', 1, 1, 1, 1)")
    fake.execute("INSERT INTO universe_membership SELECT 'OLD', d, 900.0 FROM "
                 "unnest(generate_series(DATE '2023-06-01', DATE '2023-12-31', INTERVAL 1 DAY)) t(d)")
    fake.execute("INSERT INTO nl.ticker_map VALUES ('OLD', 'NEW', 'g9', true), ('NEW', 'NEW', 'g9', true)")
    fake.execute("INSERT INTO nl.companies VALUES ('NEW', 'g9', true, true, DATE '2024-02-01', 900, 900, "
                 "false, 'OLD')")
    m = ts.membership_panel(["OLD", "NEW"], days)
    assert m["NEW"].all() and not m["OLD"].any()
    assert ts.pit_universe("2023-10-02") == ["NEW"]
    assert ts.universe_over_window("2023-07-01", "2023-12-31") == ["NEW"]


def test_the_gate_before_bhavcopy_starts_counts_companies_listed_when_coverage_began(fake):
    """Verifier 1488 note: Bhavcopy starts 2010-01-04, Trendlyne in 2006 — no empty pre-2010 universe."""
    _bars(fake, "ATSTART", "INE000J01011", "EQ", pd.bdate_range("2010-01-04", "2010-03-31"))
    _bars(fake, "LATER", "INE000K01011", "EQ", pd.bdate_range("2012-01-02", "2012-03-30"))
    early = pd.bdate_range("2008-06-02", "2008-06-30")
    g = ts.nse_gate_panel(["ATSTART", "LATER"], early)
    assert g["ATSTART"].all() and not g["LATER"].any()
    assert ts.nse_gate_at(["ATSTART", "LATER"], "2008-06-16") == {"ATSTART"}


def test_gate_at_and_gate_panel_agree_at_exactly_the_window_edge(fake):
    days = pd.bdate_range("2023-01-02", "2023-01-31")
    _bars(fake, "EDGE", "INE000L01011", "EQ", days)
    d = pd.Timestamp("2023-01-31") + pd.Timedelta(days=ts.GATE_RECENT_DAYS)
    assert bool(ts.nse_gate_panel(["EDGE"], [d])["EDGE"].iloc[0])
    assert ts.nse_gate_at(["EDGE"], d) == {"EDGE"}


def test_a_trendlyne_factor_blend_leaves_out_names_trendlyne_does_not_cover():
    """B4: a survivor has no P/E at all, so a tl_pe + momentum blend must not rank it on momentum alone."""
    import importlib
    rv = importlib.import_module("windfall.strategy.resolve")   # the package re-exports a resolve() function
    idx = pd.bdate_range("2025-01-01", periods=3)
    rank = pd.DataFrame({"COVERED": [0.4, 0.5, 0.6], "SURVIVOR": [0.9, 0.9, 0.9],
                         "DELISTED": [0.7, 0.7, 0.7]}, index=idx)
    warns: list[str] = []
    out = rv._mask_uncovered(rank, ["tl_pe", "roc126"], {"SURVIVOR"}, warns)
    assert out["SURVIVOR"].isna().all() and out["COVERED"].tolist() == [0.4, 0.5, 0.6]
    assert out["DELISTED"].tolist() == [0.7] * 3, "the adr-030 dead set keeps ranking as before"
    assert warns and "tl_pe" in warns[0]
    same = rv._mask_uncovered(rank, ["roc126", "mcap"], {"SURVIVOR"}, [])   # price-only: untouched
    pd.testing.assert_frame_equal(same, rank)


def test_build_map_keeps_a_renamed_company_off_the_survivor_list(tmp_path, monkeypatch):
    import scripts.nse_mcap_ingest as ing
    bc, tl = tmp_path / "bc.duckdb", tmp_path / "tl.duckdb"
    b = duckdb.connect(str(bc))
    b.execute("CREATE TABLE bhavcopy_prices (date DATE, ticker VARCHAR, isin VARCHAR, series VARCHAR)")
    b.execute("INSERT INTO bhavcopy_prices VALUES ('2025-01-02', 'OLD.NS', 'INE333C01011', 'EQ'), "
              "('2027-01-04', 'NEW.NS', 'INE333C01011', 'EQ')")
    b.close()
    t = duckdb.connect(str(tl))
    t.execute("CREATE TABLE stocks (pk INTEGER, nsecode VARCHAR)")
    t.execute("INSERT INTO stocks VALUES (1, 'NEW')")
    t.execute("CREATE TABLE recovered_symbols (pk INTEGER, nse_symbol VARCHAR)")
    t.execute("CREATE TABLE universe_membership (symbol VARCHAR, date DATE, mcap_cr DOUBLE)")
    t.execute("INSERT INTO universe_membership VALUES ('OLD', '2026-10-12', 900)")
    t.execute("CREATE TABLE delistings (symbol VARCHAR)")
    t.close()
    monkeypatch.setattr(ing, "BC", bc)
    monkeypatch.setattr(ing, "TL", tl)
    con = duckdb.connect(str(tmp_path / "nl.duckdb"))
    con.execute(ing.SCHEMA)
    con.execute("INSERT INTO mcap_daily VALUES ('2024-02-01', 'OLD', 'EQ', 1, 1, 1, 900)")
    ing.build_map(con)
    rows = con.execute("SELECT engine_symbol, has_membership, survivor, membership_symbol FROM companies").fetchall()
    assert rows == [("NEW", True, False, "OLD")]
