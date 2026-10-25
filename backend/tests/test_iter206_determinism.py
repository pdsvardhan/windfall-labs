"""iter-206 (#967): the same code and data must give the same universe and the same labels.

Two sources of run-to-run difference were measured on 2026-10-20:
  - pit_universe took arg_max(mcap_cr, date) over universe_membership, which holds twin rows (live +
    dead) for MBECL, MAZDA, SHALPAINTS: on a tie the row the scan met first won, and that differs
    between processes (856 vs 857 names on 2016-10-31);
  - the dead-name alias map was built in whatever order SELECT DISTINCT returned, so two delisted
    symbols sharing an ISIN (DEEPIND/DEEPENR) labelled the shared bars either way.
"""
import itertools

import pytest

from windfall.data import trendlyne_store as ts
from tests.test_iter204_free_layer import _bars, _store, _CACHED, fake  # noqa: F401  (fixture)


def test_a_tie_on_the_latest_date_takes_the_larger_market_cap(fake, monkeypatch):
    monkeypatch.setattr(ts, "_has_nl", lambda: False)
    import pandas as pd
    _bars(fake, "TWIN", "INE000F01011", "EQ", pd.bdate_range("2016-09-01", "2016-10-31"))
    # twin rows on the SAME date, one below and one above the floor, inserted in both orders
    for order in (("TWIN", 400.0), ("TWIN", 900.0)), (("TWIN", 900.0), ("TWIN", 400.0)):
        fake.execute("DELETE FROM universe_membership")
        for sym, mc in order:
            fake.execute("INSERT INTO universe_membership VALUES (?, DATE '2016-10-28', ?)", [sym, mc])
        assert ts.pit_universe("2016-10-31") == ["TWIN"], f"insertion order {order} changed the answer"


def test_the_latest_date_still_beats_an_older_larger_value(fake, monkeypatch):
    monkeypatch.setattr(ts, "_has_nl", lambda: False)
    import pandas as pd
    _bars(fake, "SHRUNK", "INE000G01011", "EQ", pd.bdate_range("2016-09-01", "2016-10-31"))
    fake.execute("INSERT INTO universe_membership VALUES ('SHRUNK', DATE '2016-10-20', 900.0)")
    fake.execute("INSERT INTO universe_membership VALUES ('SHRUNK', DATE '2016-10-28', 300.0)")
    assert ts.pit_universe("2016-10-31") == [], "the most recent reading (300) governs, not the max"


@pytest.mark.parametrize("order", list(itertools.permutations(["DEEPIND", "DEEPENR", "OTHER"])))
def test_alias_labels_do_not_depend_on_request_order(fake, order):
    # DEEPIND and DEEPENR are two delisted symbols of one company (shared ISIN); OTHER is unrelated
    _bars(fake, "DEEPIND", "INE000H01011", "EQ", ["2016-01-04"])
    _bars(fake, "DEEPENR", "INE000H01011", "EQ", ["2016-01-05"])
    _bars(fake, "OTHER", "INE000I01011", "EQ", ["2016-01-04"])
    m = ts._alias_to_canonical(list(order))
    assert m == {"DEEPENR": "DEEPENR", "DEEPIND": "DEEPIND", "OTHER": "OTHER"}


def test_an_unrequested_old_ticker_goes_to_the_alphabetically_first_requested_symbol(fake):
    _bars(fake, "OLDNAME", "INE000J01011", "EQ", ["2016-01-04"])
    _bars(fake, "ALPHA", "INE000J01011", "EQ", ["2017-01-04"])
    _bars(fake, "BETA", "INE000J01011", "EQ", ["2018-01-04"])
    for order in (["BETA", "ALPHA"], ["ALPHA", "BETA"]):
        m = ts._alias_to_canonical(order)
        assert m["OLDNAME"] == "ALPHA"
        assert m["ALPHA"] == "ALPHA" and m["BETA"] == "BETA"


def test_a_renamed_company_still_relabels_its_old_ticker_to_the_current_symbol(fake):
    _bars(fake, "NBVENTURES", "INE000K01011", "EQ", ["2016-01-04"])
    _bars(fake, "NAVA", "INE000K01011", "EQ", ["2023-01-04"])
    assert ts._alias_to_canonical(["NAVA"]) == {"NAVA": "NAVA", "NBVENTURES": "NAVA"}
