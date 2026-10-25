"""iter-206 (#970): NSE quarterly-results XBRL -> point-in-time TTM EPS.

The XBRL snippets are cut down from real filings (TCS Dec-2024 legacy, HDFCBANK Dec-2024 banking
taxonomy, TCS Sep-2026 integrated) keeping their tag spellings, contexts and value formats.
"""
import datetime as dt

import duckdb
import pandas as pd
import pytest

from windfall.data import nse_filings as nf

HEAD = '<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-bse-fin="x">'


def _ctx(cid, start, end):
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">TCS</xbrli:identifier>'
            f'</xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
            f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')


INDUSTRIAL = (HEAD + _ctx("OneD", "2024-10-01", "2024-12-31") + _ctx("FourD", "2024-04-01", "2024-12-31")
    + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR" decimals="-7">124440000000.00</in-bse-fin:ProfitLossForPeriod>'
      '<in-bse-fin:ProfitLossForPeriod contextRef="FourD" unitRef="INR" decimals="-7">365040000000.00</in-bse-fin:ProfitLossForPeriod>'
      '<in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations contextRef="OneD" unitRef="INRPerShare" decimals="INF">34.20</in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations>'
      '<in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare" decimals="INF">34.21</in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>'
      '<in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="FourD" unitRef="INRPerShare" decimals="INF">100.40</in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>'
      '<in-bse-fin:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare" decimals="INF">34.19</in-bse-fin:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations>'
      '<in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-7">639730000000.00</in-bse-fin:RevenueFromOperations>'
      '<in-bse-fin:PaidUpValueOfEquityShareCapital contextRef="OneD" unitRef="INR" decimals="-7">3620000000.00</in-bse-fin:PaidUpValueOfEquityShareCapital>'
      '<in-bse-fin:FaceValueOfEquityShareCapital contextRef="OneD" unitRef="INRPerShare" decimals="INF">1</in-bse-fin:FaceValueOfEquityShareCapital>'
      '<in-bse-fin:RevenueFromOperations contextRef="OneOperatingExpenses01D" unitRef="INR">1.0</in-bse-fin:RevenueFromOperations>'
      '</xbrli:xbrl>')

BANK = (HEAD + _ctx("OneD", "2024-10-01", "2024-12-31") + _ctx("FourD", "2024-04-01", "2024-12-31")
    + '<in-bse-fin:InterestEarned contextRef="OneD" unitRef="INR">850401700000.00</in-bse-fin:InterestEarned>'
      '<in-bse-fin:Income contextRef="OneD" unitRef="INR">1121939400000.00</in-bse-fin:Income>'
      '<in-bse-fin:ProfitLossForThePeriod contextRef="OneD" unitRef="INR">183401100000.00</in-bse-fin:ProfitLossForThePeriod>'
      '<in-bse-fin:BasicEarningsPerShareAfterExtraordinaryItems contextRef="OneD" unitRef="INRPerShare">23.11</in-bse-fin:BasicEarningsPerShareAfterExtraordinaryItems>'
      '<in-bse-fin:BasicEarningsPerShareAfterExtraordinaryItems contextRef="FourD" unitRef="INRPerShare">68.18</in-bse-fin:BasicEarningsPerShareAfterExtraordinaryItems>'
      '</xbrli:xbrl>')

LOSS = (HEAD + _ctx("OneD", "2026-07-01", "2026-09-30")
    + '<in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">-5200000</in-capmkt:ProfitLossForPeriod>'
      '<in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">-0.52</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>'
      '</xbrli:xbrl>')


def test_industrial_quarter_picks_the_preferred_tags_and_the_quarter_context():
    p = nf.parse_xbrl(INDUSTRIAL)
    assert p["period_end"] == dt.date(2024, 12, 31) and p["period_months"] == 3 and p["ytd_months"] == 9
    assert p["eps_basic"] == 34.21, "continuing-AND-discontinued beats continuing-only"
    assert p["eps_diluted"] == 34.19 and p["np"] == 124440000000.0
    assert p["np_ytd"] == 365040000000.0 and p["eps_ytd"] == 100.40, "FourD is the fiscal year to date"
    assert p["revenue"] == 639730000000.0, "a segment context (OneOperatingExpenses01D) is not the company fact"
    assert p["paid_up"] / p["face_value"] == 3620000000.0 and p["taxonomy"] == "industrial"


def test_banking_taxonomy_uses_its_own_spellings():
    p = nf.parse_xbrl(BANK)
    assert p["taxonomy"] == "banking" and p["revenue"] == 850401700000.0
    assert p["np"] == 183401100000.0 and p["eps_basic"] == 23.11 and p["eps_ytd"] == 68.18


def test_a_loss_is_kept_negative_and_a_non_results_file_is_refused():
    assert nf.parse_xbrl(LOSS)["eps_basic"] == -0.52
    assert nf.parse_xbrl("<html>governance filing</html>") is None
    assert nf.parse_xbrl(HEAD + _ctx("OneD", "2026-07-01", "2026-09-30") + "</xbrli:xbrl>") is None


# ── which filings to fetch ──────────────────────────────────────────────────────────────────────

def _legacy(to, bc, basis="Consolidated", cum="Non-cumulative", xml=True):
    return {"toDate": to, "broadCastDate": bc, "consolidated": basis, "cumulative": cum,
            "audited": "Audited", "xbrl": f"https://x/{to}-{basis}-{bc}" + (".xml" if xml else ".pdf")}


def _integ(qe, bc, basis="Consolidated", typ="Integrated Filing- Financials"):
    return {"qe_Date": qe, "broadcast_Date": bc, "consolidated": basis, "type": typ,
            "audited": "Audited", "xbrl": f"https://x/{qe}-{basis}-{bc}.xml"}


def test_selection_keeps_the_earliest_broadcast_and_prefers_consolidated():
    legacy = [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00"),
              _legacy("31-Dec-2024", "05-Feb-2025 10:00:00"),                      # a later revision
              _legacy("31-Dec-2024", "10-Jan-2025 10:00:00", basis="Standalone"),  # standalone is dropped
              _legacy("30-Sep-2024", "01-Nov-2024 10:00:00", basis="Standalone"),  # only standalone exists
              _legacy("30-Sep-2024", "01-Nov-2024 10:00:00", cum="Cumulative"),    # a YTD filing: skipped
              _legacy("30-Jun-2024", "01-Aug-2024 10:00:00", xml=False)]            # no XBRL: skipped
    got = nf.select_filings(legacy, [])
    assert [(c["period_end"], c["basis"], c["broadcast_ts"].day) for c in got] == [
        (dt.date(2024, 9, 30), "standalone", 1), (dt.date(2024, 12, 31), "consolidated", 20)]


def test_integrated_filings_extend_the_legacy_series_and_ignore_other_filing_types():
    got = nf.select_filings(
        [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00")],
        [_integ("31-MAR-2025", "20-Apr-2025 10:00:00"),
         _integ("30-JUN-2025", "20-Jul-2025 10:00:00", typ="Integrated Filing- Governance")])
    assert [c["period_end"] for c in got] == [dt.date(2024, 12, 31), dt.date(2025, 3, 31)]
    assert got[1]["source"] == "integrated"


# ── TTM EPS and the P/E ─────────────────────────────────────────────────────────────────────────

def _q(sym, ends, eps, basis="consolidated", bc_lag=30):
    return pd.DataFrame([{"symbol": sym, "period_end": pd.Timestamp(e), "basis": basis,
                          "broadcast_ts": pd.Timestamp(e) + pd.Timedelta(days=bc_lag), "eps_basic": x, "np": None if x is None else x * 10}
                         for e, x in zip(ends, eps)])


ENDS = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]


def test_ttm_is_the_sum_of_four_consecutive_quarters_known_when_the_last_was_broadcast():
    t = nf.ttm_eps(_q("AAA", ENDS, [1, 2, 3, 4, 5]))
    assert list(t["ttm_eps"]) == [10, 14]
    assert t.iloc[0]["known_date"] == pd.Timestamp("2024-01-30") and t.iloc[1]["known_date"] == pd.Timestamp("2024-04-30")


def test_a_missing_quarter_or_a_basis_change_leaves_no_ttm_across_the_gap():
    gap = _q("AAA", ["2023-03-31", "2023-06-30", "2023-12-31", "2024-03-31", "2024-06-30"], [1, 2, 3, 4, 5])
    assert nf.ttm_eps(gap).empty, "the Sep-2023 quarter is missing: no four consecutive quarters"
    mixed = _q("AAA", ENDS, [1, 2, 3, 4, 5])
    mixed.loc[4, "basis"] = "standalone"
    assert list(nf.ttm_eps(mixed)["ttm_eps"]) == [10], "the 5th quarter is standalone: its window is skipped"
    nan = _q("AAA", ENDS, [1, 2, None, 4, 5])
    assert nf.ttm_eps(nan).empty


def test_eps_is_restated_into_todays_share_units_for_a_split_after_the_broadcast():
    q = _q("AAA", ENDS, [10, 10, 10, 10, 10])
    # a 5:1 split goes ex on 2023-11-10: the Mar/Jun/Sep-2023 quarters were broadcast (30 Apr, 30 Jul,
    # 30 Oct) before it, so they are divided by 5; Dec-2023 (30 Jan) and Mar-2024 were broadcast after it
    # and are already in post-split units — dividing those again would double-count the split
    t = nf.ttm_eps(q, {"AAA": [(dt.date(2023, 11, 10), 5.0)]})
    assert t.iloc[0]["ttm_eps"] == pytest.approx(2 + 2 + 2 + 10)    # Mar23..Dec23
    assert t.iloc[1]["ttm_eps"] == pytest.approx(2 + 2 + 10 + 10)   # Jun23..Mar24


def test_pe_is_adjusted_close_over_the_latest_known_ttm_and_blank_for_losses_and_stale_filers():
    ttm = pd.DataFrame({"symbol": ["AAA", "AAA", "LOSS", "OLD"],
                        "known_date": pd.to_datetime(["2024-01-30", "2024-04-30", "2024-01-30", "2022-01-01"]),
                        "ttm_eps": [10.0, 20.0, -3.0, 5.0]})
    idx = pd.to_datetime(["2024-01-15", "2024-02-01", "2024-05-02", "2024-12-31"])
    close = pd.DataFrame({"AAA": 100.0, "LOSS": 50.0, "OLD": 100.0, "NOFILING": 10.0}, index=idx)
    pe = nf.pe_ttm_panel(close, ttm)
    assert pd.isna(pe.loc["2024-01-15", "AAA"]), "nothing known yet on 15 Jan"
    assert pe.loc["2024-02-01", "AAA"] == 10.0 and pe.loc["2024-05-02", "AAA"] == 5.0
    assert pe["LOSS"].isna().all(), "TTM EPS <= 0 is no P/E"
    assert pe["OLD"].isna().all(), "a TTM older than the age limit is dropped, not carried forever"
    assert pe["NOFILING"].isna().all()


def test_store_round_trip_keeps_the_earliest_broadcast_and_resumes(tmp_path):
    con = nf.connect(tmp_path / "f.duckdb")

    class Fake:
        n = 0

        def get(self, url, landing, params=None, json_=True):
            if json_:
                return [] if "integrated" in url else [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00")]
            return INDUSTRIAL

    r = nf.fetch_symbol(con, Fake(), "TCS")
    assert (r["status"], r["listed"], r["new"], r["failed"]) == ("done", 1, 1, 0)
    row = con.execute("SELECT eps_basic, np, basis, period_months FROM filings").fetchone()
    assert row == (34.21, 124440000000.0, "consolidated", 3)
    r2 = nf.fetch_symbol(con, Fake(), "TCS")
    assert r2["new"] == 0, "already stored: no refetch"
    assert nf.status(con)["filings"] == 1


OLD_STYLE = (HEAD + _ctx("OneOperatingExpenses01D", "2019-10-01", "2019-12-31")
    + _ctx("OneOperatingExpenses02D", "2019-10-01", "2019-12-31")
    + _ctx("FourOperatingExpenses01D", "2019-04-01", "2019-12-31")
    + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR">81430000000.00</in-bse-fin:ProfitLossForPeriod>'
      '<in-bse-fin:ProfitLossForPeriod contextRef="FourD" unitRef="INR">243540000000.00</in-bse-fin:ProfitLossForPeriod>'
      '<in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">21.63</in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>'
      '</xbrli:xbrl>')


def test_filings_that_never_define_oned_take_the_quarter_from_their_dimensional_contexts():
    """2017 to mid-2022 filings reference OneD / FourD without declaring them (TCS Dec-2019 is one)."""
    p = nf.parse_xbrl(OLD_STYLE)
    assert p["period_end"] == dt.date(2019, 12, 31) and p["period_months"] == 3 and p["ytd_months"] == 9
    assert p["eps_basic"] == 21.63 and p["np"] == 81430000000.0 and p["np_ytd"] == 243540000000.0


def test_a_renamed_company_is_found_under_its_current_ticker(tmp_path):
    con = nf.connect(tmp_path / "f.duckdb")
    asked = []

    class Fake:
        n = 0

        def get(self, url, landing, params=None, json_=True):
            if json_:
                asked.append(params["symbol"])
                return [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00")] if params["symbol"] == "ETERNAL" and "integrated" not in url else []
            return INDUSTRIAL

    r = nf.fetch_symbol(con, Fake(), "ZOMATO", alts=["ETERNAL"])
    assert r["new"] == 1 and asked[:2] == ["ZOMATO", "ZOMATO"] and "ETERNAL" in asked
    assert con.execute("SELECT symbol FROM filings").fetchone() == ("ZOMATO",), "stored under the engine symbol"


def test_a_filing_with_no_dated_context_takes_its_quarter_from_the_listing_row():
    bare = (HEAD + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR">5000000.00</in-bse-fin:ProfitLossForPeriod>'
            '<in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations contextRef="OneD" unitRef="INRPerShare">0.40</in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations>'
            '</xbrli:xbrl>')
    assert nf.parse_xbrl(bare) is None, "without a hint there is no way to date it"
    p = nf.parse_xbrl(bare, (dt.date(2019, 7, 1), dt.date(2019, 9, 30)))
    assert p["period_end"] == dt.date(2019, 9, 30) and p["period_months"] == 3 and p["eps_basic"] == 0.40
    assert p["ytd_months"] is None


def test_raw_filings_are_kept_so_a_parser_fix_can_be_replayed_without_a_refetch(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "RAW_DIR", tmp_path / "raw")
    con = nf.connect(tmp_path / "f.duckdb")

    class Fake:
        n = 0

        def get(self, url, landing, params=None, json_=True):
            if json_:
                return [] if "integrated" in url else [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00")]
            return INDUSTRIAL

    nf.fetch_symbol(con, Fake(), "TCS")
    assert len(list((tmp_path / "raw" / "TCS").glob("*.xml.gz"))) == 1
    con.execute("DELETE FROM filings")                      # as if the parser had been wrong
    assert nf.reparse(con) == {"reparsed": 1, "unparseable": 0}
    row = con.execute("SELECT symbol, period_end, eps_basic, basis, broadcast_ts FROM filings").fetchone()
    assert row[:4] == ("TCS", dt.date(2024, 12, 31), 34.21, "consolidated")
    assert row[4] == dt.datetime(2025, 1, 20, 10, 0)


def test_nses_legacy_label_for_a_standalone_filing_is_non_consolidated():
    """The first version dropped every legacy standalone filing: the real label is 'Non-Consolidated'."""
    got = nf.select_filings([_legacy("31-Dec-2024", "20-Jan-2025 10:00:00", basis="Non-Consolidated")], [])
    assert [(c["period_end"], c["basis"]) for c in got] == [(dt.date(2024, 12, 31), "standalone")]
    both = nf.select_filings([_legacy("31-Dec-2024", "20-Jan-2025 10:00:00", basis="Non-Consolidated"),
                              _legacy("31-Dec-2024", "21-Jan-2025 10:00:00", basis="Consolidated")], [])
    assert [c["basis"] for c in both] == ["consolidated"]


def _eps_file(total, cont, disc):
    tag = "in-bse-fin:BasicEarningsLossPerShare"
    return (HEAD + _ctx("OneD", "2022-07-01", "2022-09-30")
            + f'<{tag}FromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">{total}</{tag}FromContinuingAndDiscontinuedOperations>'
            + f'<{tag}FromContinuingOperations contextRef="OneD" unitRef="INRPerShare">{cont}</{tag}FromContinuingOperations>'
            + f'<{tag}FromDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">{disc}</{tag}FromDiscontinuedOperations>'
            + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR">1</in-bse-fin:ProfitLossForPeriod></xbrli:xbrl>')


def test_a_total_eps_that_is_the_sum_of_two_identical_parts_is_read_as_the_continuing_eps():
    """ADANIENT Sep-2022 tags continuing 4.05, discontinued 4.05 (there is none) and total 8.10."""
    assert nf.parse_xbrl(_eps_file("8.10", "4.05", "4.05"))["eps_basic"] == 4.05
    assert nf.parse_xbrl(_eps_file("4.05", "4.05", "0.00"))["eps_basic"] == 4.05, "no discontinued: unchanged"
    assert nf.parse_xbrl(_eps_file("3.00", "4.05", "-1.05"))["eps_basic"] == 3.00, "a real discontinued loss: the total stands"
    assert nf.parse_xbrl(_eps_file("-8.10", "-4.05", "-4.05"))["eps_basic"] == -4.05, "ABAN: a loss doubled the same way"


def test_a_file_that_names_a_different_quarter_than_its_listing_is_not_stored(tmp_path, monkeypatch):
    """AARTIDRUGS Jun-2025's file carries Jun-2024's contexts; storing it would overwrite the real Jun-2024 row."""
    assert nf.dates_agree(dt.date(2024, 12, 31), dt.date(2024, 12, 31))
    assert nf.dates_agree(dt.date(2024, 12, 30), dt.date(2024, 12, 31))
    assert not nf.dates_agree(dt.date(2024, 6, 30), dt.date(2025, 6, 30))
    monkeypatch.setattr(nf, "RAW_DIR", tmp_path / "raw")
    con = nf.connect(tmp_path / "f.duckdb")

    class Fake:
        n = 0

        def get(self, url, landing, params=None, json_=True):
            if json_:
                return [] if "integrated" in url else [_legacy("31-Dec-2025", "20-Jan-2026 10:00:00")]
            return INDUSTRIAL          # its own quarter is Dec-2024

    r = nf.fetch_symbol(con, Fake(), "TCS")
    assert (r["new"], r["failed"], r["status"]) == (0, 1, "partial")
    assert con.execute("SELECT count(*) FROM filings").fetchone() == (0,)


def test_an_empty_answer_is_retried_after_a_fresh_landing_before_it_is_believed(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "RAW_DIR", tmp_path / "raw")
    con = nf.connect(tmp_path / "f.duckdb")

    class Flaky:
        n, landed, calls = 0, {"x": 1}, 0

        def get(self, url, landing, params=None, json_=True):
            if json_:
                if "integrated" in url:
                    return {}
                Flaky.calls += 1
                return {} if Flaky.calls == 1 else [_legacy("31-Dec-2024", "20-Jan-2025 10:00:00")]
            return INDUSTRIAL

    r = nf.fetch_symbol(con, Flaky(), "TCS")
    assert r["new"] == 1 and r["status"] == "done", "a stale session's empty first answer must not mark the symbol empty"
