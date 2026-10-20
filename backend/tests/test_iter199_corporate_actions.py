"""iter-199 (#952): NSE corporate actions, the live-tail adjustment, and the paper re-base.

The parse cases are NSE's own subject strings. The tail tests pin the convention to Trendlyne's:
an ex-date already inside Trendlyne's history must not be adjusted twice, and the latest bar must
stay the raw traded price. The re-base tests check that a re-base only happens on price evidence,
and only once.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from windfall.data import corp_actions
from windfall.data import trendlyne_store as ts
from windfall.paper import book
from windfall.store_meta import _init

D = dt.date


# ── parsing NSE subjects ─────────────────────────────────────────────────────

@pytest.mark.parametrize("subject,kind,ratio", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", 5.0),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", "split", 5.0),
    ("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share", "split", 2.0),
    ("Bonus 1:1", "bonus", 2.0),
    ("Bonus 2:1", "bonus", 3.0),            # Trendlyne GOODLUCK: x1/3 before the ex-date
    ("Bonus 1:2", "bonus", 1.5),            # Trendlyne TRENT: x2/3
    ("Bonus 2:5", "bonus", 1.4),
    ("Consolidation Of Shares From Re 1/- Per Share To Rs 10/- Per Share", "consolidation", 0.1),
    ("Demerger", "demerger", None),
    ("Scheme Of Arrangement - Bonus Ncrps 4:1", "scheme", None),
])
def test_parse_reads_the_price_ratio(subject, kind, ratio):
    k, r = corp_actions.parse(subject)
    assert k == kind
    assert (r is None and ratio is None) or r == pytest.approx(ratio)


@pytest.mark.parametrize("subject", [
    "Dividend - Rs 5 Per Share", "Buy Back",
    "Distribution - Rs 1.55 Per Unit", "Interest Payment"])
def test_parse_ignores_events_that_do_not_move_the_share_count(subject):
    assert corp_actions.parse(subject) == (None, None)


def test_parse_types_a_rights_issue_without_a_ratio():
    """iter-204 (adr-050): rights are typed here and priced at P/TERP when the list is refreshed
    (corp_actions.price_rights) — the ratio needs the close before the ex-date, not the subject."""
    assert corp_actions.parse("Rights 3:5 @ Premium Rs 45/-") == ("rights", None)


# ── the live-tail adjustment ─────────────────────────────────────────────────

def _wide():
    idx = pd.bdate_range("2026-10-01", periods=8)        # 1..8 Oct (bdays: 1,2,5,6,7,8,9,12)
    return pd.DataFrame({"AAA": [100, 101, 102, 104, 103, 20.8, 21.0, 21.5],
                         "BBB": [50.0] * 8}, index=idx)


def test_a_split_in_the_raw_tail_is_back_adjusted_and_the_latest_bar_stays_raw():
    w = ts.apply_tail_corporate_actions(_wide(), {"AAA": pd.Timestamp("2026-09-30")},
                                        {"AAA": [(D(2026, 10, 8), 5.0)]})
    assert w["AAA"].iloc[-1] == 21.5                       # raw traded price, untouched
    assert w["AAA"].iloc[0] == pytest.approx(20.0)         # 100 / 5
    assert w["AAA"].pct_change().abs().max() < 0.05        # no phantom -80% day left
    assert (w["BBB"] == 50.0).all()                        # other names untouched


def test_an_ex_date_trendlyne_already_covers_is_not_adjusted_twice():
    w = ts.apply_tail_corporate_actions(_wide(), {"AAA": pd.Timestamp("2026-10-09")},
                                        {"AAA": [(D(2026, 10, 8), 5.0)]})
    assert w["AAA"].iloc[0] == 100


def test_an_announced_future_ex_date_changes_nothing_yet():
    w = ts.apply_tail_corporate_actions(_wide(), {"AAA": pd.Timestamp("2026-09-30")},
                                        {"AAA": [(D(2026, 11, 2), 2.0)]})
    assert w["AAA"].iloc[0] == 100


def test_the_mcap_fallback_scales_shares_from_the_ex_date():
    idx = pd.bdate_range("2026-10-06", periods=4)          # 6,7,8,9 Oct
    w = pd.DataFrame({"AAA": [1000.0, 1000.0, 200.0, 205.0]}, index=idx)
    out = ts.scale_shares_after_corporate_actions(w, {"AAA": pd.Timestamp("2026-08-28")},
                                                  {"AAA": [(D(2026, 10, 8), 5.0)]})
    assert list(out["AAA"]) == [1000.0, 1000.0, 1000.0, 1025.0]
    same = ts.scale_shares_after_corporate_actions(
        pd.DataFrame({"AAA": [1000.0, 200.0]}, index=idx[1:3]),
        {"AAA": pd.Timestamp("2026-10-09")}, {"AAA": [(D(2026, 10, 8), 5.0)]})
    assert list(same["AAA"]) == [1000.0, 200.0]           # shares already post-split


def test_real_tail_buildpro_split_is_continuous_and_tembo_is_not_doubled():
    """Real data: BUILDPRO's 1:5 split (ex 8 Oct) is in the raw tail; TEMBO's 1:10 (ex 5 Aug) is
    inside Trendlyne's history, which already back-adjusts it."""
    if not ts.available():
        pytest.skip("trendlyne.duckdb not present in this environment")
    before = {s: ts.adjusted_close_panel([s], start="2026-07-20", extend_live=True)
              for s in ("BUILDPRO", "TEMBO")}
    if any(s not in p.columns for s, p in before.items()):
        pytest.skip("BUILDPRO/TEMBO not in this data snapshot")
    corp_actions.ingest([
        {"symbol": "BUILDPRO", "ex_date": D(2026, 10, 8), "subject": "t199 split", "kind": "split",
         "ratio": 5.0, "record_date": None},
        {"symbol": "TEMBO", "ex_date": D(2026, 8, 5), "subject": "t199 split", "kind": "split",
         "ratio": 10.0, "record_date": None}])
    try:
        after = {s: ts.adjusted_close_panel([s], start="2026-07-20", extend_live=True)[s]
                 for s in ("BUILDPRO", "TEMBO")}
    finally:
        _init().execute("DELETE FROM nse_corporate_actions WHERE subject = 't199 split'")
    # Which property this snapshot can show depends on where each ex-date falls against the name's
    # last Trendlyne bar: in the raw tail it must be adjusted, inside Trendlyne's history it must
    # not be applied twice. (The 2026-10-20 harvest moved BUILDPRO's 8 Oct split inside history.)
    last = ts._last_tl_dates({s: ts.symbol_pk_map()[s] for s in ("BUILDPRO", "TEMBO")})
    for sym, ex in (("BUILDPRO", D(2026, 10, 8)), ("TEMBO", D(2026, 8, 5))):
        raw = before[sym][sym]
        if pd.Timestamp(ex) <= last[sym]:
            pd.testing.assert_series_equal(after[sym], raw)          # inside history: not doubled
        else:
            assert raw.pct_change().min() < -0.6                     # the phantom crash, unadjusted
            assert after[sym].pct_change().min() > -0.3              # gone
            assert after[sym].iloc[-1] == raw.iloc[-1]               # latest stays the raw price


# ── the paper re-base ────────────────────────────────────────────────────────

def _seed(pid, entry_date, entry, shares, stop=None, status="open", exit_=None, exit_date=None,
          reason=None):
    con = _init()
    con.execute("DELETE FROM paper_positions WHERE id=?", [pid])
    con.execute(
        "INSERT INTO paper_positions (id,strategy_id,ticker,status,entry_date,entry,stop,target,"
        "weight,shares,last_price,last_date,exit_date,exit,return_pct,r_multiple,reason,created_at,"
        "planned_capital,origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [pid, "T199", "SPLITCO", status, entry_date, entry, stop, None, 0.1, shares, entry,
         entry_date, exit_date, exit_, 0.0, None, reason, dt.datetime.now(), entry * shares, "live"])


def _row(pid):
    return _init().execute("SELECT entry, shares, stop FROM paper_positions WHERE id=?",
                           [pid]).fetchone()


@pytest.fixture
def split_world(monkeypatch):
    monkeypatch.setattr(corp_actions, "ratio_events",
                        lambda syms: {"SPLITCO": [(D(2026, 10, 8), 5.0)]})
    yield monkeypatch
    _init().execute("DELETE FROM paper_positions WHERE strategy_id='T199'")


def test_a_position_spanning_a_split_is_rebased_once(split_world):
    split_world.setattr(book, "_panel_price", lambda t, d: [20.0, 20.4])   # adjusted fill day
    _seed("t199a", D(2026, 10, 1), 100.0, 100.0, stop=85.0)
    out = book.rebase_corporate_actions(today=D(2026, 10, 19))
    assert out["ca_rebased"] == 1 and out["ca_unresolved"] == 0
    assert _row("t199a") == pytest.approx((20.0, 500.0, 17.0))
    again = book.rebase_corporate_actions(today=D(2026, 10, 19))            # idempotent
    assert again["ca_rebased"] == 0
    assert _row("t199a") == pytest.approx((20.0, 500.0, 17.0))


def test_an_entry_already_on_the_adjusted_basis_is_left_alone(split_world):
    split_world.setattr(book, "_panel_price", lambda t, d: [20.0, 20.4])
    _seed("t199b", D(2026, 10, 1), 20.0, 500.0)
    assert book.rebase_corporate_actions(today=D(2026, 10, 19))["ca_rebased"] == 0
    assert _row("t199b")[:2] == pytest.approx((20.0, 500.0))


def test_evidence_that_does_not_match_the_ratio_changes_nothing(split_world):
    split_world.setattr(book, "_panel_price", lambda t, d: [50.0, 50.0])  # 2x, not 5x
    _seed("t199c", D(2026, 10, 1), 100.0, 100.0)
    out = book.rebase_corporate_actions(today=D(2026, 10, 19))
    assert out["ca_rebased"] == 0 and out["ca_unresolved"] == 1
    assert _row("t199c")[:2] == pytest.approx((100.0, 100.0))


def _prices(by_day):
    return lambda t, d: by_day[d]


def _full(pid):
    return _init().execute(
        "SELECT entry, shares, exit, last_price, return_pct FROM paper_positions WHERE id=?",
        [pid]).fetchone()


def test_a_position_sold_before_the_split_is_rebased_whole(split_world):
    """Verifier finding 1: the adjusted series rescales its whole holding period too, so entry AND
    exit move by the ratio — the return is unchanged and the equity curve no longer dips."""
    split_world.setattr(book, "_panel_price", _prices({D(2026, 9, 1): [20.0, 20.0],
                                                       D(2026, 10, 5): [22.0, 22.0]}))
    _seed("t199d", D(2026, 9, 1), 100.0, 100.0, status="closed", exit_=110.0,
          exit_date=D(2026, 10, 5))
    assert book.rebase_corporate_actions(today=D(2026, 10, 19))["ca_rebased"] == 1
    entry, shares, exit_, _last, ret = _full("t199d")
    assert (entry, shares, exit_) == pytest.approx((20.0, 500.0, 22.0))
    assert ret == pytest.approx(0.10)


def test_a_stop_fired_on_a_phantom_crash_is_reported_not_turned_into_a_gain(split_world):
    """Verifier finding 2: a pre-split stop level booked as the exit after the ex-date. Re-basing
    only the entry would read +70%; the row is left alone and reported instead."""
    split_world.setattr(corp_actions, "ratio_events",
                        lambda syms: {"SPLITCO": [(D(2026, 10, 9), 2.0)]})
    split_world.setattr(book, "_panel_price", _prices({D(2026, 10, 1): [330.3, 331.0],
                                                       D(2026, 10, 9): [329.0, 330.0]}))
    _seed("t199e", D(2026, 10, 1), 660.6, 40.0, stop=561.51, status="closed", exit_=561.51,
          exit_date=D(2026, 10, 9), reason="stop")
    out = book.rebase_corporate_actions(today=D(2026, 10, 19))
    assert out["ca_rebased"] == 0 and out["ca_unresolved"] == 1
    assert _full("t199e")[:3] == pytest.approx((660.6, 40.0, 561.51))


def test_a_phantom_stop_on_a_small_ratio_bonus_is_also_reported(split_world):
    """Round-2 finding: a 1:2 bonus (ratio 1.5) with a 15% stop. The stop fired at 85 in the old
    units; a distance threshold would re-base it into +27.5%. The rule is structural instead."""
    split_world.setattr(corp_actions, "ratio_events",
                        lambda syms: {"SPLITCO": [(D(2026, 10, 8), 1.5)]})
    split_world.setattr(book, "_panel_price", _prices({D(2026, 10, 1): [66.67, 66.8]}))
    _seed("t199h", D(2026, 10, 1), 100.0, 100.0, stop=85.0, status="closed", exit_=85.0,
          exit_date=D(2026, 10, 8), reason="stop")
    out = book.rebase_corporate_actions(today=D(2026, 10, 19))
    assert out["ca_rebased"] == 0 and out["ca_unresolved"] == 1
    assert _full("t199h")[:3] == pytest.approx((100.0, 100.0, 85.0))


def test_a_rebalance_exit_after_the_split_is_a_real_close_and_kept(split_world):
    split_world.setattr(book, "_panel_price", _prices({D(2026, 10, 1): [20.0, 20.4]}))
    _seed("t199i", D(2026, 10, 1), 100.0, 100.0, status="closed", exit_=21.0,
          exit_date=D(2026, 10, 12), reason="rebalance")
    assert book.rebase_corporate_actions(today=D(2026, 10, 19))["ca_rebased"] == 1
    entry, shares, exit_, _last, ret = _full("t199i")
    assert (entry, shares, exit_) == pytest.approx((20.0, 500.0, 21.0))
    assert ret == pytest.approx(0.05)


def test_a_real_gap_through_stop_before_the_split_is_still_rebased(split_world):
    """Round-2 N2: a stop that gapped far below its level BEFORE the event is a real exit."""
    split_world.setattr(book, "_panel_price", _prices({D(2026, 9, 1): [20.0, 20.0]}))
    _seed("t199j", D(2026, 9, 1), 100.0, 100.0, stop=90.0, status="closed", exit_=90.0,
          exit_date=D(2026, 9, 20), reason="stop")
    assert book.rebase_corporate_actions(today=D(2026, 10, 19))["ca_rebased"] == 1
    assert _full("t199j")[:3] == pytest.approx((20.0, 500.0, 18.0))


def test_a_short_or_empty_fetch_never_wipes_the_stored_list():
    """Round-2 N1: an HTTP 200 with [] (or a truncated list) must not delete the events."""
    win = (D(2032, 1, 1), D(2032, 1, 31))
    rows = [{"symbol": f"T199N{i}", "ex_date": D(2032, 1, 10 + i), "subject": "Bonus 1:1",
             "kind": "bonus", "ratio": 2.0, "record_date": None} for i in range(6)]
    held = lambda: _init().execute(                                   # noqa: E731
        "SELECT count(*) FROM nse_corporate_actions WHERE symbol LIKE 'T199N%'").fetchone()[0]
    try:
        corp_actions.ingest(rows, win)
        with pytest.raises(ValueError):
            corp_actions.ingest([], win)
        with pytest.raises(ValueError):
            corp_actions.ingest(rows[:3], win)
        assert held() == 6
        corp_actions.ingest(rows[:5] + [{**rows[5], "subject": "Bonus 1:1 (revised)"}], win)
        assert held() == 6
    finally:
        _init().execute("DELETE FROM nse_corporate_actions WHERE symbol LIKE 'T199N%'")


def test_a_second_split_after_a_rebase_is_applied_alone(split_world):
    """Verifier finding 3: the row already carries the first event; only the second is missing."""
    split_world.setattr(corp_actions, "ratio_events", lambda syms: {
        "SPLITCO": [(D(2026, 10, 8), 5.0), (D(2026, 10, 14), 2.0)]})
    split_world.setattr(book, "_panel_price", _prices({D(2026, 10, 1): [10.0, 10.2]}))
    _seed("t199f", D(2026, 10, 1), 20.0, 500.0)
    assert book.rebase_corporate_actions(today=D(2026, 10, 19))["ca_rebased"] == 1
    assert _full("t199f")[:2] == pytest.approx((10.0, 1000.0))


def test_a_last_mark_taken_before_the_split_is_rescaled_with_the_entry(split_world):
    """Verifier finding 6: an unpriced holding must not read +400% after a 1:5 re-base."""
    split_world.setattr(book, "_panel_price", _prices({D(2026, 10, 1): [20.0, 20.4]}))
    _seed("t199g", D(2026, 10, 1), 100.0, 100.0)
    _init().execute("UPDATE paper_positions SET last_price=104.0, last_date=? WHERE id='t199g'",
                    [D(2026, 10, 7)])
    book.rebase_corporate_actions(today=D(2026, 10, 19))
    entry, shares, _exit, last, ret = _full("t199g")
    assert (entry, shares, last) == pytest.approx((20.0, 500.0, 20.8))
    assert ret == pytest.approx(0.04)


def test_a_name_with_no_bar_after_its_ex_date_keeps_its_latest_price_raw():
    """Verifier finding 5: the batch extends past the ex-date, this name does not."""
    w = _wide()
    w.loc[w.index >= pd.Timestamp("2026-10-08"), "AAA"] = float("nan")
    out = ts.apply_tail_corporate_actions(w, {"AAA": pd.Timestamp("2026-09-30")},
                                          {"AAA": [(D(2026, 10, 8), 5.0)]})
    assert out["AAA"].dropna().iloc[-1] == 103


def test_a_refresh_replaces_its_window_so_a_revised_event_is_not_applied_twice():
    """Verifier finding 4: NSE revising a subject must not leave a stale twin."""
    win = (D(2031, 1, 1), D(2031, 1, 31))
    row = {"symbol": "T199REV", "ex_date": D(2031, 1, 15), "kind": "split", "ratio": 5.0,
           "record_date": None}
    try:
        corp_actions.ingest([{**row, "subject": "Split From Rs 10 To Rs 2"}], win)
        corp_actions.ingest([{**row, "subject": "Face Value Split From Rs 10 To Rs 2"}], win)
        assert corp_actions.ratio_events(["T199REV"]) == {"T199REV": [(D(2031, 1, 15), 5.0)]}
    finally:
        _init().execute("DELETE FROM nse_corporate_actions WHERE symbol='T199REV'")


# ── the demerger flag ────────────────────────────────────────────────────────

def test_a_holding_through_a_demerger_is_flagged_and_one_sold_before_is_not(monkeypatch):
    monkeypatch.setattr(corp_actions, "demergers",
                        lambda syms: {"DEMCO": [(D(2026, 10, 8), "Demerger")]})
    out = [
        {"ticker": "DEMCO", "status": "open", "entry_date": "2026-09-02", "exit_date": None},
        {"ticker": "DEMCO", "status": "closed", "entry_date": "2026-09-02", "exit_date": "2026-10-01"},
        {"ticker": "DEMCO", "status": "void", "entry_date": None, "exit_date": None},
    ]
    book._annotate_demergers(out)
    assert out[0]["corporate_action"]["kind"] == "demerger"
    assert out[0]["corporate_action"]["ex_date"] == "2026-10-08"
    assert out[0]["corporate_action"]["note"] == "new company's shares not counted"
    assert "corporate_action" not in out[1] and "corporate_action" not in out[2]


def test_a_scheme_is_not_described_as_a_new_company(monkeypatch):
    """Verifier finding 7: 'Bonus Ncrps' schemes issue preference shares, not a new company."""
    monkeypatch.setattr(corp_actions, "demergers", lambda syms: {
        "SCHEMECO": [(D(2026, 9, 8), "Scheme Of Arrangement - Bonus Ncrps 46:1")]})
    out = [{"ticker": "SCHEMECO", "status": "open", "entry_date": "2026-09-01", "exit_date": None}]
    book._annotate_demergers(out)
    assert out[0]["corporate_action"]["kind"] == "scheme"
    assert "new company" not in out[0]["corporate_action"]["note"]
