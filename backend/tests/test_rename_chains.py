"""Ticker-rename chains must resolve to a terminal live symbol (iter-172, to-do #246).

The real case, measured 2026-09-07:
    TATAMTRDVR --(IN9155A01020)--> TATAMOTORS --(INE155A01022)--> TMPV
rename_map is built by a single ISIN join, so it stopped at TATAMOTORS, which is not in Trendlyne's
live list - leaving the row flagged live_in_tl=False and its consumers with an unusable successor.
"""
from windfall.data.renames import resolve_rename_chains

# Trendlyne's live list post-demerger: TATAMOTORS is gone, TMPV and TMCV are there.
LIVE = {"TMPV", "TMCV", "A2ZINFRA", "ATLANTAA"}


def _by_old(rows):
    return {r["old_sym"]: r for r in rows}


def test_the_tata_chain_resolves_through_to_the_live_successor():
    rows = [
        ("TATAMTRDVR", "IN9155A01020", "TATAMOTORS", False),
        ("TATAMOTORS", "INE155A01022", "TMPV", True),
    ]
    got = _by_old(resolve_rename_chains(rows, LIVE))

    assert got["TATAMTRDVR"]["live_sym"] == "TMPV"
    assert got["TATAMTRDVR"]["live_in_tl"] is True
    assert got["TATAMTRDVR"]["resolved_via"] == "TATAMOTORS"   # the hop is disclosed, not hidden
    # The single-hop row is unchanged and carries no via - only followed rows are marked.
    assert got["TATAMOTORS"]["live_sym"] == "TMPV"
    assert got["TATAMOTORS"]["resolved_via"] == ""


def test_single_hop_rows_are_left_exactly_as_they_were():
    rows = [("A2ZMES", "INE619I01012", "A2ZINFRA", True),
            ("ATLANTA", "INE285H01022", "ATLANTAA", True)]
    for r in resolve_rename_chains(rows, LIVE):
        assert r["resolved_via"] == ""
        assert r["live_in_tl"] is True


def test_a_dead_end_stays_a_dead_end_rather_than_being_invented():
    """CAREERP -> CPCAP, and CPCAP is in no further row and not live. Do not fabricate a successor."""
    rows = [("CAREERP", "INE521J01018", "CPCAP", False)]
    got = resolve_rename_chains(rows, LIVE)[0]
    assert got["live_sym"] == "CPCAP"
    assert got["live_in_tl"] is False
    assert got["resolved_via"] == ""


def test_three_hop_chain_walks_all_the_way():
    rows = [("AAA", "I1", "BBB", False),
            ("BBB", "I2", "CCC", False),
            ("CCC", "I3", "TMPV", True)]
    got = _by_old(resolve_rename_chains(rows, LIVE))
    assert got["AAA"]["live_sym"] == "TMPV"
    assert got["AAA"]["resolved_via"] == "BBB>CCC"
    assert got["BBB"]["resolved_via"] == "CCC"


def test_a_cycle_terminates_instead_of_hanging():
    """A->B->A is a data artefact. It must stop, not spin."""
    rows = [("AAA", "I1", "BBB", False), ("BBB", "I2", "AAA", False)]
    got = _by_old(resolve_rename_chains(rows, LIVE))
    assert got["AAA"]["live_sym"] in {"AAA", "BBB"}
    assert got["BBB"]["live_sym"] in {"AAA", "BBB"}
    for r in got.values():
        assert r["live_in_tl"] is False


def test_self_referential_row_terminates():
    got = resolve_rename_chains([("AAA", "I1", "AAA", False)], LIVE)[0]
    assert got["live_sym"] == "AAA"


def test_live_in_tl_is_recomputed_against_the_terminal_not_the_first_hop():
    """The bug in one line: the flag described TATAMOTORS while the answer should be about TMPV."""
    rows = [("TATAMTRDVR", "IN9155A01020", "TATAMOTORS", False),
            ("TATAMOTORS", "INE155A01022", "TMPV", True)]
    got = _by_old(resolve_rename_chains(rows, LIVE))["TATAMTRDVR"]
    assert got["live_in_tl"] is True, "chain terminal TMPV is live, so the row is usable"


def test_empty_input_is_not_an_error():
    assert resolve_rename_chains([], LIVE) == []
