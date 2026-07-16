"""Persistence for strategies, backtests, signal runs and paper trades (DuckDB)."""
from __future__ import annotations

import datetime as dt
import json
import uuid

from .data.store import connect
from .jsonsafe import clean

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id VARCHAR PRIMARY KEY, name VARCHAR, config_json VARCHAR,
    created_at TIMESTAMP, updated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backtests (
    id VARCHAR PRIMARY KEY, strategy_id VARCHAR, name VARCHAR, config_hash VARCHAR,
    created_at TIMESTAMP, summary_json VARCHAR, result_json VARCHAR
);
CREATE TABLE IF NOT EXISTS signal_runs (
    id VARCHAR PRIMARY KEY, strategy_id VARCHAR, run_date DATE,
    created_at TIMESTAMP, signals_json VARCHAR
);
CREATE TABLE IF NOT EXISTS paper_positions (
    id VARCHAR PRIMARY KEY, strategy_id VARCHAR, ticker VARCHAR, status VARCHAR,
    entry_date DATE, entry DOUBLE, stop DOUBLE, target DOUBLE, weight DOUBLE, shares DOUBLE,
    last_price DOUBLE, last_date DATE, exit_date DATE, exit DOUBLE,
    return_pct DOUBLE, r_multiple DOUBLE, reason VARCHAR, created_at TIMESTAMP
);
"""


def _init():
    con = connect()
    con.execute(_META_SCHEMA)
    return con


def _now():
    return dt.datetime.now()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── strategies ───────────────────────────────────────────────────────────────

def save_strategy(name: str, config: dict, sid: str | None = None) -> str:
    con = _init()
    try:
        sid = sid or new_id("strat")
        existing = con.execute("SELECT id FROM strategies WHERE id = ?", [sid]).fetchone()
        payload = json.dumps(config)
        if existing:
            con.execute(
                "UPDATE strategies SET name=?, config_json=?, updated_at=? WHERE id=?",
                [name, payload, _now(), sid])
        else:
            con.execute("INSERT INTO strategies VALUES (?,?,?,?,?)",
                        [sid, name, payload, _now(), _now()])
        return sid
    finally:
        con.close()


def get_strategy(sid: str) -> dict | None:
    con = connect(read_only=True)
    try:
        r = con.execute("SELECT id,name,config_json,created_at,updated_at FROM strategies WHERE id=?",
                        [sid]).fetchone()
    finally:
        con.close()
    if not r:
        return None
    return {"id": r[0], "name": r[1], "config": json.loads(r[2]),
            "created_at": str(r[3]), "updated_at": str(r[4])}


def list_strategies() -> list[dict]:
    con = connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT id,name,config_json,updated_at FROM strategies ORDER BY updated_at DESC").fetchall()
    finally:
        con.close()
    return [{"id": r[0], "name": r[1], "config": json.loads(r[2]), "updated_at": str(r[3])}
            for r in rows]


def delete_strategy(sid: str) -> None:
    con = _init()
    try:
        con.execute("DELETE FROM strategies WHERE id=?", [sid])
    finally:
        con.close()


# ── backtests ────────────────────────────────────────────────────────────────

def save_backtest(result_dict: dict, strategy_id: str | None) -> str:
    result_dict = clean(result_dict)  # ensure on-disk JSON is strict-valid (no NaN tokens)
    con = _init()
    try:
        bid = new_id("bt")
        con.execute("INSERT INTO backtests VALUES (?,?,?,?,?,?,?)", [
            bid, strategy_id, result_dict.get("name"), result_dict.get("config_hash"),
            _now(), json.dumps(result_dict.get("summary", {})), json.dumps(result_dict),
        ])
        return bid
    finally:
        con.close()


def get_backtest(bid: str) -> dict | None:
    con = connect(read_only=True)
    try:
        r = con.execute("SELECT result_json FROM backtests WHERE id=?", [bid]).fetchone()
    finally:
        con.close()
    return json.loads(r[0]) if r else None


def list_backtests(strategy_id: str | None = None, limit: int | None = None,
                   offset: int = 0) -> list[dict]:
    # limit/offset paginate the global list so a leaderboard can page past the newest rows instead of
    # fetching per-strategy (audit #97). Defaults preserve the prior behavior EXACTLY: limit=None →
    # global list capped at 200, per-strategy list uncapped. An explicit limit>0 paginates either path;
    # limit<=0 means "no cap".
    offset = max(0, int(offset))
    if limit is None:
        lim_clause = "" if strategy_id else " LIMIT 200"
    else:
        limit = int(limit)
        lim_clause = "" if limit <= 0 else f" LIMIT {limit} OFFSET {offset}"
    con = connect(read_only=True)
    try:
        if strategy_id:
            rows = con.execute(
                "SELECT id,strategy_id,name,config_hash,created_at,summary_json FROM backtests "
                "WHERE strategy_id=? ORDER BY created_at DESC" + lim_clause, [strategy_id]).fetchall()
        else:
            rows = con.execute(
                "SELECT id,strategy_id,name,config_hash,created_at,summary_json FROM backtests "
                "ORDER BY created_at DESC" + lim_clause).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "strategy_id": r[1], "name": r[2], "config_hash": r[3],
             "created_at": str(r[4]), "summary": json.loads(r[5])} for r in rows]


# ── signal runs ──────────────────────────────────────────────────────────────

def save_signal_run(strategy_id: str | None, run_date: str, signals: list[dict]) -> str:
    con = _init()
    try:
        rid = new_id("sig")
        con.execute("INSERT INTO signal_runs VALUES (?,?,?,?,?)",
                    [rid, strategy_id, run_date, _now(), json.dumps(signals)])
        return rid
    finally:
        con.close()


def get_signal_run(rid: str) -> dict | None:
    con = connect(read_only=True)
    try:
        r = con.execute("SELECT id,strategy_id,run_date,signals_json FROM signal_runs WHERE id=?",
                        [rid]).fetchone()
    finally:
        con.close()
    if not r:
        return None
    return {"id": r[0], "strategy_id": r[1], "run_date": str(r[2]), "signals": json.loads(r[3])}


def list_signal_runs() -> list[dict]:
    con = connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT id,strategy_id,run_date,created_at FROM signal_runs "
            "ORDER BY created_at DESC LIMIT 100").fetchall()
    finally:
        con.close()
    return [{"id": r[0], "strategy_id": r[1], "run_date": str(r[2]), "created_at": str(r[3])}
            for r in rows]
