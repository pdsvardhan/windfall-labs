"""A Forecaster harvest must ACCUMULATE snapshots, never replace them.

The endpoint behind this table serves only today's analyst estimates - there is no history to
fetch, and estimates revise. So the history IS the pile of snapshots, and a replace at any key
would delete every earlier one on the first run. That is the same failure mode as the 2026-09-07
dvm_history loss (0b0ecce), except here it would be total rather than partial: not 446 series,
but every snapshot ever taken.

These tests pin the three properties the design depends on:
  1. a later snapshot does not disturb an earlier one (accumulation),
  2. re-running the same harvest changes nothing (idempotence),
  3. a stock the harvest never mentions is untouched (merge-never-replace, at pk level).
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_forecaster.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_forecaster", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _staging(tmp_path: Path, as_of: str, eps: float, name: str, pks=(1, 2), n_pad=1200) -> Path:
    """A harvest snapshot: `pks` covered with FY27 EPS = `eps`, padded to clear the stock floor."""
    src = tmp_path / name
    src.mkdir()
    est = ["pk,metric,period_end,as_of,value"]
    cov = ["pk,as_of,covered,annual_rows,http_status"]
    for pk in pks:
        est.append(f"{pk},EPS_AVG,2027-03-31,{as_of},{eps}")
        est.append(f"{pk},EPS_AVG,2028-03-31,{as_of},{eps + 5}")
        cov.append(f"{pk},{as_of},1,2,200")
    # uncovered filler so the >=1000-stock floor passes, as a real harvest would
    for pk in range(1000, 1000 + n_pad):
        cov.append(f"{pk},{as_of},0,0,200")
    (src / "tl_forecaster_estimates_part01.csv").write_text("\n".join(est) + "\n", encoding="utf-8")
    (src / "tl_forecaster_coverage_part01.csv").write_text("\n".join(cov) + "\n", encoding="utf-8")
    return src


def _run(mod, src, db_path, apply=True):
    argv = [str(SCRIPT), str(src)] + (["--apply"] if apply else [])
    old_argv, old_db = sys.argv, mod.DB
    sys.argv, mod.DB = argv, db_path
    try:
        mod.main()
    finally:
        sys.argv, mod.DB = old_argv, old_db


def _rows(db_path, **where):
    con = duckdb.connect(str(db_path), read_only=True)
    sql = "SELECT pk, metric, period_end, as_of, value FROM forecaster_estimates"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
    out = con.execute(sql, list(where.values())).fetchall()
    con.close()
    return out


def test_a_later_snapshot_does_not_delete_the_earlier_one(tmp_path):
    """THE property. Two harvests a month apart must both survive, with their own values."""
    db = tmp_path / "trendlyne.duckdb"
    mod = _load_module()
    _run(mod, _staging(tmp_path, "2026-09-08", 64.0, "sep"), db)
    _run(mod, _staging(tmp_path, "2026-10-08", 70.0, "oct"), db)

    sep = _rows(db, as_of=dt.date(2026, 9, 8))
    oct_ = _rows(db, as_of=dt.date(2026, 10, 8))
    assert len(sep) == 4, f"the September snapshot was destroyed by October's harvest: {sep}"
    assert len(oct_) == 4, f"the October snapshot did not land: {oct_}"

    # and the revision is visible as a revision, not as an overwrite
    vals = {r[3]: r[4] for r in _rows(db, pk=1, metric="EPS_AVG",
                                      period_end=dt.date(2027, 3, 31))}
    assert vals == {dt.date(2026, 9, 8): 64.0, dt.date(2026, 10, 8): 70.0}, (
        f"FY27 EPS should read 64.0 as of 8 Sep and 70.0 as of 8 Oct, got {vals}")


def test_reingesting_the_same_harvest_is_idempotent(tmp_path):
    """Re-running a harvest must not duplicate rows - the anti-join is on the full key."""
    db = tmp_path / "trendlyne.duckdb"
    mod = _load_module()
    src = _staging(tmp_path, "2026-09-08", 64.0, "sep")
    _run(mod, src, db)
    first = _rows(db)
    _run(mod, src, db)
    assert _rows(db) == first, "a second ingest of the same harvest changed the table"


def test_a_stock_the_harvest_never_mentions_is_untouched(tmp_path):
    """Merge-never-replace at pk level: dropping out of the screener must not erase history."""
    db = tmp_path / "trendlyne.duckdb"
    mod = _load_module()
    _run(mod, _staging(tmp_path, "2026-09-08", 64.0, "sep", pks=(1, 2)), db)
    # next month pk=2 has fallen below the Rs500cr floor and is simply absent
    _run(mod, _staging(tmp_path, "2026-10-08", 70.0, "oct", pks=(1,)), db)

    kept = _rows(db, pk=2)
    assert len(kept) == 2, f"pk=2's history was deleted by a harvest that never mentioned it: {kept}"
    assert {r[3] for r in kept} == {dt.date(2026, 9, 8)}


def test_a_truncated_harvest_is_refused(tmp_path):
    """The screener returning a short list is the known failure; it must not ingest silently."""
    db = tmp_path / "trendlyne.duckdb"
    mod = _load_module()
    src = _staging(tmp_path, "2026-09-08", 64.0, "short", n_pad=10)
    with pytest.raises(SystemExit) as exc:
        _run(mod, src, db)
    assert "floor" in str(exc.value).lower() or "truncated" in str(exc.value).lower()


def test_the_coverage_ledger_is_required(tmp_path):
    """Without it, 'no rows for this pk' cannot distinguish uncovered from unreached."""
    db = tmp_path / "trendlyne.duckdb"
    mod = _load_module()
    src = _staging(tmp_path, "2026-09-08", 64.0, "nocov")
    (src / "tl_forecaster_coverage_part01.csv").unlink()
    with pytest.raises(SystemExit) as exc:
        _run(mod, src, db)
    assert "coverage" in str(exc.value).lower()
