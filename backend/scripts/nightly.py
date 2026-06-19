#!/usr/bin/env python3
"""Nightly job: incremental data update, regenerate signals for saved strategies, mark paper, alert.

Wire via cron, e.g.:
    30 19 * * 1-5  cd /app && python scripts/nightly.py >> data/nightly.log 2>&1
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windfall import store_meta  # noqa: E402
from windfall.alerts import build_alerts, dispatch  # noqa: E402
from windfall.data.pipeline import incremental_update  # noqa: E402
from windfall.paper import list_positions, mark_to_market, scoreboard  # noqa: E402
from windfall.signals_live import generate_signals  # noqa: E402


def main():
    report = {"data": incremental_update("nifty500")}
    all_events = []
    runs = []
    for strat in store_meta.list_strategies():
        try:
            sig = generate_signals(strat["config"])
            store_meta.save_signal_run(strat["id"], sig.get("as_of"), sig.get("signals", []))
            runs.append({"strategy": strat["name"], "as_of": sig.get("as_of"),
                         "n_signals": len(sig.get("signals", []))})
            all_events += build_alerts(signals=sig)
        except Exception as exc:  # noqa: BLE001
            runs.append({"strategy": strat["name"], "error": repr(exc)})
    report["signal_runs"] = runs
    report["paper"] = mark_to_market()
    all_events += build_alerts(paper_positions=list_positions(status="closed"),
                               paper_scoreboard=scoreboard())
    report["alerts"] = dispatch(all_events)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
