"""A partial DVM harvest must not delete the series it omits.

Regression test for the 2026-09-07 refresh. dvm_history holds three independent series
per stock (d/v/m), each fetched as its own rate-limited request, so a harvest routinely
comes back with only some of them. The ingest used to replace per pk, which deleted the
missing series outright - 446 series across 445 stocks, with the shrink guard silent
because losing 1 of 3 is a ~35% row drop, under its 50% bar.
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_refresh.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_refresh", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(db_path: Path):
    """A stock with all three series, plus a second stock the harvest never mentions."""
    con = duckdb.connect(str(db_path))
    con.execute('CREATE TABLE dvm_history (pk BIGINT, score VARCHAR, "date" DATE, "value" DOUBLE)')
    rows = []
    base = dt.date(2020, 1, 1)
    for pk in (1, 2):
        for score in ("d", "v", "m"):
            for i in range(100):
                rows.append((pk, score, base + dt.timedelta(days=i), float(i)))
    con.executemany('INSERT INTO dvm_history VALUES (?, ?, ?, ?)', rows)
    con.close()


def _staging(tmp_path: Path, scores) -> Path:
    """A harvest carrying only `scores` for pk=1, with fresher values."""
    src = tmp_path / "staging"
    src.mkdir()
    lines = ["pk,score,date,value"]
    base = dt.date(2020, 1, 1)
    for score in scores:
        for i in range(120):          # longer than the DB's 100 -> no shrink warning
            lines.append(f"1,{score},{base + dt.timedelta(days=i)},{i + 1000}")
    (src / "tl_dvm_history_part01.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return src


def _run(mod, src, db_path, apply=True):
    argv = [str(SCRIPT), str(src)] + (["--apply"] if apply else [])
    old_argv, old_db = sys.argv, mod.DB
    sys.argv, mod.DB = argv, db_path
    try:
        mod.main()
    finally:
        sys.argv, mod.DB = old_argv, old_db


def _series(db_path, pk):
    con = duckdb.connect(str(db_path), read_only=True)
    out = dict(con.execute(
        'SELECT score, count(*) FROM dvm_history WHERE pk = ? GROUP BY score', [pk]
    ).fetchall())
    con.close()
    return out


def test_omitted_series_survives(tmp_path):
    """THE regression: a harvest with only m+v must leave d untouched."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ("m", "v")), db)

    got = _series(db, 1)
    assert got.get("d") == 100, f"durability was deleted by a harvest that never mentioned it: {got}"
    assert got.get("m") == 120, "momentum should have been replaced with the fresher 120 rows"
    assert got.get("v") == 120, "valuation should have been replaced with the fresher 120 rows"


def test_uncovered_pk_untouched(tmp_path):
    """The original merge-never-replace guarantee still holds at pk level."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ("m", "v")), db)

    assert _series(db, 2) == {"d": 100, "v": 100, "m": 100}


def test_full_harvest_replaces_every_series(tmp_path):
    """A complete harvest still supersedes all three series."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ("d", "v", "m")), db)

    assert _series(db, 1) == {"d": 120, "v": 120, "m": 120}


def test_shrink_guard_sees_a_truncated_series(tmp_path, capsys):
    """A single truncated series must now trip the guard, which pk-level counting missed.

    pk=1 has 300 rows across 3 series. A harvest carrying 10 rows of `d` alone is 290/300
    below at pk level - but per (pk, score) it is 10 vs 100, a 90% drop on that series.
    """
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    src = tmp_path / "staging"
    src.mkdir()
    base = dt.date(2020, 1, 1)
    lines = ["pk,score,date,value"] + [
        f"1,d,{base + dt.timedelta(days=i)},{i}" for i in range(10)
    ]
    (src / "tl_dvm_history_part01.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    mod = _load_module()
    with pytest.raises(SystemExit):
        _run(mod, src, db, apply=True)
    assert "HISTORY-SHRINK" in capsys.readouterr().out
