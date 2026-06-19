"""Alert rules. v1 builds alert events and logs them; it does NOT send anything externally.

Wiring Telegram/email is a later step: implement a `Channel` and call it from `dispatch`. The rule
layer and the event shape are stable so that change is additive.
"""
from __future__ import annotations

import datetime as dt

from ..data.store import connect

_ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts_log (
    created_at TIMESTAMP, kind VARCHAR, strategy_id VARCHAR, ticker VARCHAR, message VARCHAR
);
"""


def build_alerts(
    signals: dict | None = None,
    paper_mark: dict | None = None,
    paper_positions: list[dict] | None = None,
    drawdown_threshold: float = -0.15,
    paper_scoreboard: list[dict] | None = None,
) -> list[dict]:
    """Derive alert events from the latest signal run, paper mark-to-market and scoreboard."""
    events: list[dict] = []
    if signals:
        sid = signals.get("strategy")
        for s in signals.get("signals", []):
            if s.get("action") == "buy":
                events.append({"kind": "new_signal", "strategy_id": sid, "ticker": s["ticker"],
                               "message": f"New BUY signal {s['ticker']} ({s.get('entry_zone')})"})
            elif s.get("action") == "sell":
                events.append({"kind": "exit_signal", "strategy_id": sid, "ticker": s["ticker"],
                               "message": f"EXIT signal {s['ticker']} (dropped from top-N)"})
    for p in (paper_positions or []):
        if p.get("status") == "closed" and p.get("reason") in ("stop", "target"):
            events.append({"kind": f"{p['reason']}_hit", "strategy_id": p.get("strategy_id"),
                           "ticker": p["ticker"],
                           "message": f"{p['ticker']} {p['reason'].upper()} hit at {p.get('exit')}"})
    for row in (paper_scoreboard or []):
        if row.get("avg_return_pct", 0) <= drawdown_threshold:
            events.append({"kind": "drawdown_breach", "strategy_id": row.get("strategy_id"),
                           "ticker": None,
                           "message": f"Paper drawdown breach: avg return {row.get('avg_return_pct')}"})
    return events


def dispatch(events: list[dict]) -> dict:
    """Log alert events (console + alerts_log). No external delivery in v1."""
    con = connect()
    try:
        con.execute(_ALERT_SCHEMA)
        for e in events:
            con.execute("INSERT INTO alerts_log VALUES (?,?,?,?,?)",
                        [dt.datetime.now(), e["kind"], e.get("strategy_id"), e.get("ticker"),
                         e["message"]])
            print(f"[alert:{e['kind']}] {e['message']}")
    finally:
        con.close()
    return {"dispatched": len(events), "delivery": "log-only (external delivery deferred)"}
