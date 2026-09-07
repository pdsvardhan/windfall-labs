"""write_rename_map must survive an empty map (iter-172, Stage 4.7 verifier finding on item 1249).

The chain-resolution rewrite replaced a CREATE-TABLE-AS-SELECT — which handles a zero-row result
silently — with an explicit executemany, and DuckDB rejects an empty parameter list:

    duckdb.InvalidInputException: executemany requires a non-empty list of parameter sets

Latent against today's data (127 rows) and a real regression regardless. gen_dead_list.py cannot be
imported for a test (it opens the live DB read-write at import), which is why the write moved into
windfall.data.renames where it can be exercised against a throwaway DuckDB.
"""
import duckdb
import pytest

from windfall.data.renames import resolve_rename_chains, write_rename_map

COLS = ["old_sym", "isin", "live_sym", "live_in_tl", "resolved_via"]


@pytest.fixture()
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    yield c
    c.close()


def test_empty_map_writes_an_empty_table_rather_than_raising(con):
    assert write_rename_map(con, []) == 0
    assert con.execute("SELECT COUNT(*) FROM rename_map").fetchone()[0] == 0
    # The table must still EXIST with the right shape - consumers select named columns from it.
    assert [r[0] for r in con.execute("DESCRIBE rename_map").fetchall()] == COLS


def test_rows_are_written_in_the_declared_column_order(con):
    resolved = resolve_rename_chains(
        [("TATAMTRDVR", "IN9155A01020", "TATAMOTORS", False),
         ("TATAMOTORS", "INE155A01022", "TMPV", True)],
        {"TMPV"})
    assert write_rename_map(con, resolved) == 2

    row = con.execute("SELECT old_sym, isin, live_sym, live_in_tl, resolved_via FROM rename_map "
                      "WHERE old_sym='TATAMTRDVR'").fetchone()
    assert row == ("TATAMTRDVR", "IN9155A01020", "TMPV", True, "TATAMOTORS")


def test_rewriting_replaces_rather_than_appends(con):
    rows = resolve_rename_chains([("AAA", "I1", "TMPV", True)], {"TMPV"})
    write_rename_map(con, rows)
    write_rename_map(con, rows)
    assert con.execute("SELECT COUNT(*) FROM rename_map").fetchone()[0] == 1


def test_going_from_populated_to_empty_leaves_a_usable_empty_table(con):
    """The exact sequence that would have crashed: a populated map rebuilt as an empty one."""
    write_rename_map(con, resolve_rename_chains([("AAA", "I1", "TMPV", True)], {"TMPV"}))
    assert write_rename_map(con, []) == 0
    assert con.execute("SELECT COUNT(*) FROM rename_map").fetchone()[0] == 0
