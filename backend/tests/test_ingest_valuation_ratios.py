"""valuation_ratios must refresh, and a partial harvest must not delete the metrics it omits.

iter-172 / to-do #849. Until now ingest_refresh.py handled only dvm_history / ohlcv / stocks, so
valuation_ratios (PE_TTM / PEG_TTM / PBV_A) had no refresh path in the monthly procedure at all -
it sat at 2026-07-15 while dvm_history reached 2026-09-04. The megacap harvester had been writing
tl_valuation_ratios_megacap.csv into the staging dir the whole time; the ingest just never read it.

Keyed per (pk, metric) for the same reason dvm_history is keyed per (pk, score): the harvest fetches
each metric separately and routinely returns only some of them.
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_refresh.py"
METRICS = ("PE_TTM", "PEG_TTM", "PBV_A")


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_refresh_val", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(db_path: Path):
    """Two stocks, all three metrics, 100 rows each."""
    con = duckdb.connect(str(db_path))
    con.execute('CREATE TABLE valuation_ratios (pk BIGINT, metric VARCHAR, '
                '"date" DATE, "value" DOUBLE)')
    base = dt.date(2020, 1, 1)
    rows = [(pk, m, base + dt.timedelta(days=i), float(i))
            for pk in (1, 2) for m in METRICS for i in range(100)]
    con.executemany("INSERT INTO valuation_ratios VALUES (?, ?, ?, ?)", rows)
    con.close()


def _staging(tmp_path: Path, metrics, pk: int = 1, name: str = "tl_valuation_ratios_megacap.csv"):
    """A harvest carrying only `metrics` for `pk`, with fresher values and longer history."""
    src = tmp_path / "staging"
    src.mkdir(exist_ok=True)
    base = dt.date(2020, 1, 1)
    lines = ["pk,metric,date,value"]
    for m in metrics:
        for i in range(120):          # longer than the DB's 100 -> no shrink guard trip
            lines.append(f"{pk},{m},{base + dt.timedelta(days=i)},{i + 1000}")
    (src / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return src


def _run(mod, src, db_path, apply=True):
    argv = [str(SCRIPT), str(src)] + (["--apply"] if apply else [])
    old_argv, old_db = sys.argv, mod.DB
    sys.argv, mod.DB = argv, db_path
    try:
        mod.main()
    finally:
        sys.argv, mod.DB = old_argv, old_db


def _counts(db_path: Path):
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return {(pk, m): n for pk, m, n in con.execute(
            "SELECT pk, metric, COUNT(*) FROM valuation_ratios GROUP BY 1, 2").fetchall()}
    finally:
        con.close()


def test_partial_harvest_leaves_the_metrics_it_omits_alone(tmp_path):
    """The whole point of the (pk, metric) key: PE_TTM only must not delete PEG_TTM / PBV_A."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ["PE_TTM"]), db)

    counts = _counts(db)
    assert counts[(1, "PE_TTM")] == 120        # replaced with the fresher, longer series
    assert counts[(1, "PEG_TTM")] == 100       # untouched, NOT deleted
    assert counts[(1, "PBV_A")] == 100         # untouched, NOT deleted
    assert counts[(2, "PE_TTM")] == 100        # a pk the harvest never mentions is preserved


def test_refreshed_metric_actually_takes_the_new_values(tmp_path):
    """A refresh that keeps stale values would pass the count assertions above and still be wrong."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ["PE_TTM"]), db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        mx_date, mx_val = con.execute(
            'SELECT MAX("date"), MAX("value") FROM valuation_ratios '
            "WHERE pk=1 AND metric='PE_TTM'").fetchone()
        untouched = con.execute(
            'SELECT MAX("date"), MAX("value") FROM valuation_ratios '
            "WHERE pk=1 AND metric='PBV_A'").fetchone()
    finally:
        con.close()
    assert mx_date == dt.date(2020, 1, 1) + dt.timedelta(days=119)
    assert mx_val == 1119.0                    # harvest values, not the seeded 0..99
    assert untouched == (dt.date(2020, 1, 1) + dt.timedelta(days=99), 99.0)


def test_all_three_metrics_refresh_together(tmp_path):
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, list(METRICS)), db)
    counts = _counts(db)
    assert all(counts[(1, m)] == 120 for m in METRICS)
    assert all(counts[(2, m)] == 100 for m in METRICS)


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    before = _counts(db)
    mod = _load_module()
    _run(mod, _staging(tmp_path, ["PE_TTM"]), db, apply=False)
    assert _counts(db) == before


def test_valuation_only_staging_dir_is_a_valid_ingest(tmp_path):
    """A dir holding ONLY tl_valuation_ratios_*.csv must not be rejected as 'no input files'."""
    db = tmp_path / "trendlyne.duckdb"
    _seed(db)
    mod = _load_module()
    try:
        _run(mod, _staging(tmp_path, ["PE_TTM"]), db, apply=False)
    except SystemExit as exc:                  # the pre-fix behaviour: exits 'no tl_* files'
        pytest.fail(f"valuation-only staging dir rejected: {exc}")
