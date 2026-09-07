"""Every (pk, metric, date, value) table the leg1 harvester emits must ingest, not just one.

to-do #851. #849 wired valuation_ratios and left pnl_quarterly, growth_quality and ownership in
exactly the position it had been in: produced by a harvester, ignored by ingest_refresh.py, then
deleted by Phase 3 step 5 of the runbook. Fixing one and leaving three is a slower version of the
same bug, so the ingest is now generic over METRIC_TABLES.
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_refresh.py"


def _load():
    spec = importlib.util.spec_from_file_location("ingest_refresh_metrics", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()
BASE = dt.date(2020, 1, 1)


def _seed(db: Path, tables):
    con = duckdb.connect(str(db))
    for t in tables:
        con.execute(f'CREATE TABLE {t} (pk BIGINT, metric VARCHAR, "date" DATE, "value" DOUBLE)')
        con.executemany(
            f"INSERT INTO {t} VALUES (?, ?, ?, ?)",
            [(pk, m, BASE + dt.timedelta(days=i), float(i))
             for pk in (1, 2) for m in ("M_A", "M_B") for i in range(60)])
    con.close()


def _staging(tmp: Path, table: str, metric: str):
    src = tmp / "staging"
    src.mkdir(exist_ok=True)
    lines = ["pk,metric,date,value"] + [
        f"1,{metric},{BASE + dt.timedelta(days=i)},{i + 500}" for i in range(80)]
    (src / f"tl_{table}_part01.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return src


def _run(src, db, apply=True):
    argv = [str(SCRIPT), str(src)] + (["--apply"] if apply else [])
    old_argv, old_db = sys.argv, MOD.DB
    sys.argv, MOD.DB = argv, db
    try:
        MOD.main()
    finally:
        sys.argv, MOD.DB = old_argv, old_db


def _counts(db, table):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return {(pk, m): n for pk, m, n in con.execute(
            f"SELECT pk, metric, COUNT(*) FROM {table} GROUP BY 1,2").fetchall()}
    finally:
        con.close()


def test_metric_tables_covers_every_leg1_output():
    """If a new (pk,metric,...) table is added and not registered, this is the reminder."""
    assert set(MOD.METRIC_TABLES) >= {
        "valuation_ratios", "pnl_quarterly", "growth_quality", "ownership"}


@pytest.mark.parametrize("table", ["pnl_quarterly", "growth_quality", "ownership"])
def test_each_metric_table_ingests_per_pk_metric(tmp_path, table):
    """The tables #849 left behind now refresh - and still cannot delete a metric they omit."""
    db = tmp_path / f"{table}.duckdb"
    _seed(db, [table])
    _run(_staging(tmp_path, table, "M_A"), db)

    c = _counts(db, table)
    assert c[(1, "M_A")] == 80, "the harvested metric should be replaced with the fresher series"
    assert c[(1, "M_B")] == 60, "a metric the harvest omitted must be preserved, not deleted"
    assert c[(2, "M_A")] == 60, "a pk the harvest never mentions must be preserved"


def test_several_metric_tables_in_one_staging_dir_all_apply(tmp_path):
    """A real leg1 run drops all of them at once."""
    tables = ["valuation_ratios", "pnl_quarterly", "growth_quality", "ownership"]
    db = tmp_path / "all.duckdb"
    _seed(db, tables)
    src = tmp_path / "staging"
    src.mkdir(exist_ok=True)
    for t in tables:
        _staging(tmp_path, t, "M_A")
    _run(src, db)
    for t in tables:
        assert _counts(db, t)[(1, "M_A")] == 80, f"{t} did not ingest"
        assert _counts(db, t)[(1, "M_B")] == 60, f"{t} lost an omitted metric"
