"""iter-202 (#954): a book that ranks on Trendlyne factors never rebalances on stale ones.

Owner's decision 2026-10-20: HOLD + ALERT at 7 days. Pinned here: which configs count as factor
books, how age is measured, that a held book trades nothing AND records no run (so it stays due),
that price-only books are unaffected, and that the cron-facing data_health says so.
"""
from __future__ import annotations

import datetime as dt

import pytest

from windfall.data import trendlyne_store as ts
from windfall.paper import rebalance as rb

D = dt.date
DVM = {"rank_by": "tl_durability", "rank_blend": [
    {"factor": "tl_durability", "weight": 1}, {"factor": "tl_valuation", "weight": 1},
    {"factor": "tl_momentum", "weight": 1}], "universe": {"filters": ["adtv_cr >= 0.5"]}}
CMP = {"rank_by": "tl_pe", "rank_blend": [{"factor": "tl_pe", "weight": 1},
                                           {"factor": "roc126", "weight": 1}],
       "universe": {"filters": ["adtv_cr >= 0.5"]}}
MOM = {"rank_by": "roc252", "rank_blend": [], "universe": {"filters": ["adtv_cr >= 0.5"]}}
SCREEN = {"rank_by": "roc126", "universe": {
    "filters": ["(tl_durability + tl_valuation + tl_momentum) / 3 >= 55"]}}


def test_factor_families_come_from_ranking_and_filters():
    assert rb.config_factor_families(DVM) == {"dvm"}
    assert rb.config_factor_families(CMP) == {"valuation"}
    assert rb.config_factor_families(MOM) == set()
    assert rb.config_factor_families(SCREEN) == {"dvm"}           # a factor used only to FILTER


@pytest.fixture
def world(monkeypatch):
    cfgs = {"F": DVM, "V": CMP, "P": MOM, "S1": MOM, "S2": CMP}
    monkeypatch.setattr(rb.store_meta, "get_strategy",
                        lambda sid: {"config": cfgs[sid]} if sid in cfgs else None)
    return monkeypatch


def test_age_is_measured_against_the_rebalance_day(world):
    world.setattr(ts, "factor_last_dates", lambda: {"dvm": D(2026, 10, 16), "valuation": D(2026, 9, 4)})
    fresh = rb.factor_staleness({"sid": "F", "kind": "saved"}, D(2026, 10, 19))
    assert fresh["factor_age_days"] == 3 and not fresh["factor_stale"]
    old = rb.factor_staleness({"sid": "V", "kind": "saved"}, D(2026, 10, 19))
    assert old["factor_age_days"] == 45 and old["factor_stale"]
    assert rb.factor_staleness({"sid": "P", "kind": "saved"}, D(2026, 10, 19)) is None
    blend = rb.factor_staleness({"sid": "B", "kind": "blend", "sleeves": ["S1", "S2"]}, D(2026, 10, 19))
    assert blend["factor_families"] == ["valuation"] and blend["factor_stale"]


def test_exactly_the_limit_is_not_stale_and_one_day_more_is(world):
    world.setattr(ts, "factor_last_dates", lambda: {"dvm": D(2026, 10, 12), "valuation": None})
    assert not rb.factor_staleness({"sid": "F", "kind": "saved"}, D(2026, 10, 19))["factor_stale"]
    assert rb.factor_staleness({"sid": "F", "kind": "saved"}, D(2026, 10, 20))["factor_stale"]


def test_a_factor_table_that_cannot_be_dated_holds(world):
    world.setattr(ts, "factor_last_dates", lambda: {"dvm": D(2026, 10, 18), "valuation": None})
    assert rb.factor_staleness({"sid": "V", "kind": "saved"}, D(2026, 10, 19))["factor_stale"]


def _run(world, last, allow_stale=False):
    world.setattr(rb, "ROSTER", [{"sid": "F", "kind": "saved", "capital": 500000.0},
                                 {"sid": "P", "kind": "saved", "capital": 500000.0}])
    world.setattr(ts, "factor_last_dates", lambda: last)
    world.setattr(rb, "is_due", lambda e, today: (True, "monthly"))
    targets_asked, runs = [], []
    world.setattr(rb, "_target_book", lambda e: (targets_asked.append(e["sid"]) or
                                                 ({"AAA": {"ticker": "AAA", "weight": 1.0}},
                                                  {"as_of": "2026-10-19", "data_age_days": 0,
                                                   "stale_warnings": [], "is_stale": False})))
    world.setattr(rb, "list_positions", lambda sid, status=None: [])
    world.setattr(rb, "available_cash", lambda sid, n: n)
    world.setattr(rb, "commit_pending_signal", lambda sid, sig, cap: "pp_x")
    world.setattr(rb, "_record_run", lambda sid, *a: runs.append(sid))
    world.setattr(rb, "mark_to_market", lambda: {})
    out = rb.rebalance_paper(today=D(2026, 10, 19), allow_stale=allow_stale)
    return out, targets_asked, runs


def test_a_stale_factor_book_is_held_and_stays_due(world):
    out, asked, runs = _run(world, {"dvm": D(2026, 9, 4), "valuation": D(2026, 9, 4)})
    assert out["strategies"]["F"]["skipped"] == "stale-factors"
    assert out["strategies"]["F"]["factor_age_days"] == 45
    assert "F" not in asked and "F" not in runs        # no signals, no trades, no run recorded
    assert "P" in runs                                 # the price-only book still rebalanced
    h = out["data_health"]
    assert h["stale"] is True and h["held_books"] == ["F"]
    assert "HELD 1 book" in h["message"] and "2026-09-04" in h["message"]


def test_fresh_factors_rebalance_normally(world):
    out, asked, runs = _run(world, {"dvm": D(2026, 10, 17), "valuation": D(2026, 10, 17)})
    assert runs == ["F", "P"] and out["data_health"]["held_books"] == []
    assert out["data_health"]["stale"] is False


def test_the_operator_override_is_explicit(world):
    out, asked, runs = _run(world, {"dvm": D(2026, 9, 4), "valuation": D(2026, 9, 4)}, allow_stale=True)
    assert runs == ["F", "P"]


def test_a_signal_run_warning_about_a_stale_factor_now_counts_as_stale():
    assert any(m in "stale factor: 'tl_pe' was last published 2026-09-04" for m in rb.STALE_WARNING_MARKERS)
