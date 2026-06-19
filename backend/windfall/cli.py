"""Command-line interface — the headless way to drive the engine.

    python -m windfall.cli load-data --universe nifty500 --years 12
    python -m windfall.cli backtest strategies/breakout_validation.json --save
    python -m windfall.cli validate
    python -m windfall.cli signals strategies/momentum_v22.json --save
    python -m windfall.cli sweep strategies/momentum_v22.json --grid grids/momentum.json
    python -m windfall.cli walk-forward strategies/momentum_v22.json --grid grids/momentum.json
    python -m windfall.cli paper-mark
    python -m windfall.cli coverage
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import RESULTS_DIR, ensure_dirs


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def cmd_load_data(a):
    from .data.pipeline import load_universe
    _print(load_universe(index=a.universe, years=a.years))


def cmd_backtest(a):
    from .engine.backtest import run_backtest
    res = run_backtest(_load(a.config))
    d = res.model_dump()
    if a.save:
        from . import store_meta
        ensure_dirs()
        bid = store_meta.save_backtest(d, a.strategy_id)
        out = RESULTS_DIR / f"{bid}.json"
        out.write_text(json.dumps(d, default=str))
        d["_backtest_id"] = bid
        d["_saved_to"] = str(out)
    # print summary, not the whole curve, to stdout
    _print({"name": d["name"], "config_hash": d["config_hash"], "period": d["period"],
            "summary": d["summary"], "n_trades": len(d["trades"]),
            "warnings": d["warnings"], **({"backtest_id": d.get("_backtest_id")} if a.save else {})})


def cmd_validate(a):
    from .scripts_validation import run_validation
    _print(run_validation())


def cmd_signals(a):
    from .signals_live import generate_signals
    from .signals_live.generate import signals_to_csv
    out = generate_signals(_load(a.config))
    if a.save:
        from . import store_meta
        rid = store_meta.save_signal_run(a.strategy_id, out.get("as_of"), out.get("signals", []))
        out["_signal_run_id"] = rid
    if a.csv:
        Path(a.csv).write_text(signals_to_csv(out))
        out["_csv_written"] = a.csv
    _print(out)


def cmd_sweep(a):
    from .walkforward import sweep
    grid = _load(a.grid) if a.grid else {}
    _print(sweep(_load(a.config), grid, metric=a.metric))


def cmd_walk_forward(a):
    from .walkforward import walk_forward
    grid = _load(a.grid) if a.grid else {}
    _print(walk_forward(_load(a.config), grid, metric=a.metric, is_years=a.is_years,
                        oos_years=a.oos_years))


def cmd_paper_mark(a):
    from .paper import mark_to_market, scoreboard
    _print({"mark": mark_to_market(), "scoreboard": scoreboard()})


def cmd_coverage(a):
    from .data.store import coverage_summary
    _print(coverage_summary())


def main(argv=None):
    p = argparse.ArgumentParser(prog="windfall")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("load-data"); s.add_argument("--universe", default="nifty500")
    s.add_argument("--years", type=int, default=12); s.set_defaults(func=cmd_load_data)

    s = sub.add_parser("backtest"); s.add_argument("config")
    s.add_argument("--save", action="store_true"); s.add_argument("--strategy-id", default=None)
    s.set_defaults(func=cmd_backtest)

    s = sub.add_parser("validate"); s.set_defaults(func=cmd_validate)

    s = sub.add_parser("signals"); s.add_argument("config")
    s.add_argument("--save", action="store_true"); s.add_argument("--strategy-id", default=None)
    s.add_argument("--csv", default=None, help="also write the signal list to this CSV path")
    s.set_defaults(func=cmd_signals)

    s = sub.add_parser("sweep"); s.add_argument("config"); s.add_argument("--grid", default=None)
    s.add_argument("--metric", default="sharpe"); s.set_defaults(func=cmd_sweep)

    s = sub.add_parser("walk-forward"); s.add_argument("config"); s.add_argument("--grid", default=None)
    s.add_argument("--metric", default="sharpe"); s.add_argument("--is-years", dest="is_years",
                   type=float, default=3.0); s.add_argument("--oos-years", dest="oos_years",
                   type=float, default=1.0); s.set_defaults(func=cmd_walk_forward)

    s = sub.add_parser("paper-mark"); s.set_defaults(func=cmd_paper_mark)
    s = sub.add_parser("coverage"); s.set_defaults(func=cmd_coverage)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
