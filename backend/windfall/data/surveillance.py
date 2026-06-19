"""NSE ASM/GSM surveillance flags — the pre-deploy safety guardrail.

ASM (Additional Surveillance Measure) and GSM (Graded Surveillance Measure) are NSE lists of
stocks under heightened surveillance (price bands, 100% margin, trade-to-trade, periodic call
auction) for unusual price/volume or weak fundamentals. Buying into one is a known hazard — the
circuit-prone-name problem (e.g. Silver Touch). We snapshot the lists by fetch_date so they
accrue history, and annotate live signals so a buy into a surveilled name is flagged before any
deploy.

Fetched in-process by the api, which owns the windfall.duckdb write lock — so there is no second
SQLite/DuckDB client opening the DB (adr-018 ONE DOOR). The lists are current-state; snapshotting
forward builds the history we'd need to also exclude surveilled names in backtests later.
"""
from __future__ import annotations

import datetime as dt

import requests

from .store import connect

ASM_URL = "https://www.nseindia.com/api/reportASM"
GSM_URL = "https://www.nseindia.com/api/reportGSM"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/market-data/securities-under-surveillance",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS surveillance (
    fetch_date DATE NOT NULL, symbol VARCHAR NOT NULL, isin VARCHAR,
    list_type VARCHAR NOT NULL, stage VARCHAR, surv_code VARCHAR, surv_desc VARCHAR, as_of VARCHAR,
    PRIMARY KEY (fetch_date, symbol, list_type)
);
"""


def normalize(asm: dict, gsm) -> list[dict]:
    """Flatten the NSE reportASM / reportGSM payloads into surveillance rows."""
    rows: list[dict] = []
    for key, lt in (("longterm", "ASM-LT"), ("shortterm", "ASM-ST")):
        for d in ((asm or {}).get(key) or {}).get("data", []):
            rows.append({"symbol": d.get("symbol"), "isin": d.get("isin"), "list_type": lt,
                         "stage": d.get("asmSurvIndicator"), "surv_code": d.get("survCode"),
                         "surv_desc": d.get("survDesc"), "as_of": d.get("asmTime")})
    gsm_list = gsm if isinstance(gsm, list) else (gsm or {}).get("data", [])
    for d in gsm_list:
        rows.append({"symbol": d.get("symbol"), "isin": d.get("isin"), "list_type": "GSM",
                     "stage": d.get("gsmStage"), "surv_code": d.get("survCode"),
                     "surv_desc": d.get("survDesc"), "as_of": d.get("gsmTime")})
    return [r for r in rows if r.get("symbol")]


def fetch_asm_gsm() -> list[dict]:
    def _get(url):
        r = requests.get(url, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    return normalize(_get(ASM_URL), _get(GSM_URL))


def ingest(rows: list[dict] | None = None, fetch_date: str | None = None) -> dict:
    con = connect()
    con.execute(SCHEMA)
    rows = fetch_asm_gsm() if rows is None else rows
    fd = dt.date.fromisoformat(fetch_date) if fetch_date else dt.date.today()
    con.execute("DELETE FROM surveillance WHERE fetch_date = ?", [fd])
    for r in rows:
        con.execute(
            "INSERT OR REPLACE INTO surveillance VALUES (?,?,?,?,?,?,?,?)",
            [fd, str(r["symbol"]).strip().upper(), r.get("isin"), r["list_type"],
             r.get("stage"), r.get("surv_code"), r.get("surv_desc"), r.get("as_of")])
    by_list: dict[str, int] = {}
    for r in rows:
        by_list[r["list_type"]] = by_list.get(r["list_type"], 0) + 1
    return {"fetch_date": str(fd), "count": len(rows), "by_list": by_list}


def latest_flags() -> dict:
    """{ fetch_date, flags: { SYMBOL -> [ {list, stage, desc}, ... ] } } for the newest snapshot."""
    con = connect()
    con.execute(SCHEMA)
    row = con.execute("SELECT MAX(fetch_date) FROM surveillance").fetchone()
    if not row or row[0] is None:
        return {"fetch_date": None, "flags": {}}
    fd = row[0]
    flags: dict[str, list] = {}
    for sym, lt, stage, desc in con.execute(
            "SELECT symbol, list_type, stage, surv_desc FROM surveillance WHERE fetch_date = ?",
            [fd]).fetchall():
        flags.setdefault(sym, []).append({"list": lt, "stage": stage, "desc": desc})
    return {"fetch_date": str(fd), "flags": flags}


def annotate_signals(out: dict) -> dict:
    """Tag each signal in a /api/signals payload with its surveillance flag; warn on surveilled buys."""
    flags = latest_flags().get("flags", {})
    if not flags:
        return out
    surveilled_buys = []
    for s in out.get("signals", []):
        sym = str(s.get("ticker", "")).replace(".NS", "").upper()
        hits = flags.get(sym)
        if hits:
            s["surveillance"] = "; ".join(f"{h['list']} {h['stage'] or ''}".strip() for h in hits)
            if s.get("action") in ("buy", "hold"):
                surveilled_buys.append(s.get("ticker"))
    if surveilled_buys:
        out.setdefault("warnings", []).append(
            f"surveillance: {len(surveilled_buys)} signal(s) under ASM/GSM — avoid deploying into "
            f"these without review: {', '.join(surveilled_buys[:8])}")
    return out
