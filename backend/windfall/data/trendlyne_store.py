"""Read-only access to the standalone Trendlyne full-history store (`trendlyne.duckdb`).

This store is built and owned by the offline data-layer scripts (load_trendlyne / build_ca_factor /
rebuild_pit_mcap_ca / phase3_build). Nothing writes it at runtime, so the engine opens it READ-ONLY
and never through the windfall.duckdb door (ONE-DOOR safe — adr-018). It carries:

- `ohlcv`               Trendlyne split+bonus-adjusted daily OHLCV (live names), pk-keyed
- `ca_factor`           derived corporate-action back-adjustment for DEAD names (iter-28)
- `delistings`          terminal-exit registry for delisted names (last_date, last_close, ca_uncertain)
- `universe_membership` survivorship-free point-in-time membership (live+dead), symbol-keyed, mcap_cr
- `result_lag`          real announcement-date availability for point-in-time fundamentals
- `dvm_history` / `valuation_ratios`  Trendlyne's own daily D/V/M scores and valuation multiples

iter-28 provides the price/membership/delisting primitives here; iter-29 wires them into resolve().
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import duckdb
import pandas as pd

from ..config import DATA_DIR

TRENDLYNE_DB = Path(os.environ.get("WINDFALL_TRENDLYNE_DB", DATA_DIR / "trendlyne.duckdb"))
BHAVCOPY_DB = Path(os.environ.get("WINDFALL_BHAVCOPY_DB", DATA_DIR / "bhavcopy.duckdb"))

MCAP_FLOOR_CR = 500.0   # investable-universe floor: NSE-listed + market cap > Rs500 Cr (adr-015)


def available() -> bool:
    return TRENDLYNE_DB.exists()


@functools.lru_cache(maxsize=1)
def _con() -> duckdb.DuckDBPyConnection:
    """Process-wide read-only connection; bhavcopy attached read-only for dead-name raw prices."""
    con = duckdb.connect(str(TRENDLYNE_DB), read_only=True)
    if BHAVCOPY_DB.exists():
        # DuckDB shares one instance per file path within a process, so another read-only connection
        # may have already attached `bc` — attach only if absent.
        already = con.execute(
            "SELECT count(*) FROM duckdb_databases() WHERE database_name='bc'").fetchone()[0]
        if not already:
            con.execute(f"ATTACH '{BHAVCOPY_DB}' AS bc (READ_ONLY)")
    return con


@functools.lru_cache(maxsize=1)
def symbol_pk_map() -> dict[str, int]:
    """NSE symbol -> Trendlyne pk (includes recovered megacap symbols)."""
    rows = _con().execute(
        "SELECT upper(nsecode) s, pk FROM stocks WHERE nsecode<>'' "
        "UNION SELECT upper(nse_symbol) s, pk FROM recovered_symbols WHERE nse_symbol<>''"
    ).fetchall()
    return {s: pk for s, pk in rows}


def adjusted_close_panel(symbols, start=None, end=None, field: str = "close") -> pd.DataFrame:
    """Wide date x symbol panel of split/bonus-ADJUSTED prices.

    Live names use Trendlyne's adjusted `ohlcv`; delisted names use raw Bhavcopy x the derived
    `ca_factor.adj_factor` so their returns are split-clean and tradeable. ca_uncertain dead names
    (a large unexplained gap we could not confirm as a CA) are EXCLUDED rather than mis-adjusted.
    """
    syms = [s.upper() for s in symbols]
    pkmap = symbol_pk_map()
    live = {s: pkmap[s] for s in syms if s in pkmap}
    con = _con()
    parts = []

    if live:
        pks = list(live.values())
        pk2sym = {pk: s for s, pk in live.items()}
        cond = f"WHERE pk IN ({','.join(['?']*len(pks))}) AND {field} IS NOT NULL"
        params = pks[:]
        if start:
            cond += " AND date >= ?"; params.append(start)
        if end:
            cond += " AND date <= ?"; params.append(end)
        df = con.execute(f"SELECT pk, date, {field} v FROM ohlcv {cond}", params).fetchdf()
        if not df.empty:
            df["symbol"] = df["pk"].map(pk2sym)
            parts.append(df[["date", "symbol", "v"]])

    dead = [s for s in syms if s not in pkmap]
    if dead:
        ok_dead = [r[0] for r in con.execute(
            "SELECT symbol FROM delistings WHERE NOT ca_uncertain AND symbol IN ("
            + ",".join(["?"] * len(dead)) + ")", dead).fetchall()]
        if ok_dead:
            cond = ("WHERE b.series='EQ' AND b.close>0 AND upper(regexp_replace(b.ticker,'\\.NS$',''))"
                    " IN (" + ",".join(["?"] * len(ok_dead)) + ")")
            params = ok_dead[:]
            if start:
                cond += " AND b.date >= ?"; params.append(start)
            if end:
                cond += " AND b.date <= ?"; params.append(end)
            fcol = {"close": "close", "open": "open", "high": "high", "low": "low"}.get(field, "close")
            df = con.execute(f"""
                SELECT sym AS symbol, date, {fcol} * adj AS v FROM (
                  SELECT upper(regexp_replace(b.ticker,'\\.NS$','')) sym, b.date, b.{fcol},
                         coalesce((SELECT f.adj_factor FROM ca_factor f
                                   WHERE f.ticker=upper(regexp_replace(b.ticker,'\\.NS$',''))
                                     AND f.from_date<=b.date ORDER BY f.from_date DESC LIMIT 1), 1.0) adj
                  FROM bc.bhavcopy_prices b {cond})""", params).fetchdf()
            if not df.empty:
                parts.append(df[["date", "symbol", "v"]])

    if not parts:
        return pd.DataFrame()
    long = pd.concat(parts, ignore_index=True)
    long["date"] = pd.to_datetime(long["date"])
    return long.pivot_table(index="date", columns="symbol", values="v").sort_index()


def pit_universe(asof_date, floor_cr: float = MCAP_FLOOR_CR) -> list[str]:
    """Survivorship-free investable universe at `asof_date`: symbols whose most-recent point-in-time
    market cap within the prior ~2 weeks exceeds the floor (live + confirmed-tradeable dead)."""
    rows = _con().execute("""
        SELECT symbol FROM (
          SELECT symbol, arg_max(mcap_cr, date) m FROM universe_membership
          WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
            AND symbol NOT IN (SELECT symbol FROM delistings WHERE ca_uncertain)
          GROUP BY symbol)
        WHERE m > ?""", [str(asof_date), str(asof_date), floor_cr]).fetchall()
    return sorted(r[0] for r in rows)


def membership_panel(symbols, dates, floor_cr: float = MCAP_FLOOR_CR) -> pd.DataFrame:
    """Bool date x symbol panel: True where the symbol's point-in-time mcap > floor on that date.

    Forward-filled within each symbol's window (mcap is daily but we tolerate gaps), so a name is
    'in the universe' from when it first clears the floor until it stops trading.
    """
    syms = [s.upper() for s in symbols]
    df = _con().execute(
        "SELECT symbol, date, mcap_cr FROM universe_membership WHERE symbol IN ("
        + ",".join(["?"] * len(syms)) + ")", syms).fetchdf()
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    if df.empty:
        return pd.DataFrame(False, index=idx, columns=syms)
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="symbol", values="mcap_cr").sort_index()
    wide = wide.reindex(wide.index.union(idx)).ffill().reindex(idx)
    return (wide > floor_cr).reindex(columns=syms).fillna(False)


def delistings() -> pd.DataFrame:
    """Terminal-exit registry: symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain."""
    return _con().execute(
        "SELECT symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain FROM delistings"
    ).fetchdf()
