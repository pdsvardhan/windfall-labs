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
def coverage(floor_cr: float = MCAP_FLOOR_CR) -> dict:
    """Survivorship-free Trendlyne-layer coverage for the Reference page — the data that backtests
    ACTUALLY run on, not the legacy yfinance store (whose 755/1505 counts confused the owner).
    `universe_ever` = every name that cleared the ₹500cr floor at any point (live + delisted);
    `universe_now` = names clearing it in the latest fortnight; `price_tickers` = adjusted-OHLCV pks."""
    if not available():
        return {"available": False}
    con = _con()
    ever = con.execute(
        "SELECT COUNT(DISTINCT symbol) FROM universe_membership WHERE mcap_cr > ?", [floor_cr]).fetchone()[0]
    last = con.execute("SELECT MAX(date) FROM universe_membership").fetchone()[0]
    now = con.execute(
        "SELECT COUNT(DISTINCT symbol) FROM universe_membership "
        "WHERE mcap_cr > ? AND date >= CAST(? AS DATE) - 14", [floor_cr, str(last)]).fetchone()[0]
    px_n, px_min, px_max = con.execute(
        "SELECT COUNT(DISTINCT pk), MIN(date), MAX(date) FROM ohlcv").fetchone()
    dead = con.execute("SELECT COUNT(*) FROM delistings").fetchone()[0]
    return {"available": True,
            "universe_ever": int(ever or 0), "universe_now": int(now or 0),
            "price_tickers": int(px_n or 0), "delisted": int(dead or 0),
            "date_min": str(px_min) if px_min else None,
            "date_max": str(px_max) if px_max else None,
            "floor_cr": floor_cr}


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


@functools.lru_cache(maxsize=1)
def _nse_symbols() -> frozenset[str]:
    """Symbols with real NSE-traded presence (Bhavcopy EQ series). The investable universe is gated to
    this set so BSE-only / non-NSE names — which Trendlyne still scores and prices on BSE — can NEVER
    be selected, regardless of whether a strategy sets a liquidity filter. NSE-only by construction,
    not by user discipline (adr-024). A name we have no NSE price/turnover for is not NSE-tradeable."""
    return frozenset(r[0] for r in _con().execute(
        "SELECT DISTINCT upper(regexp_replace(ticker,'\\.NS$','')) FROM bc.bhavcopy_prices WHERE series='EQ'"
    ).fetchall())


def adjusted_close_panel(symbols, start=None, end=None, field: str = "close",
                         extend_live: bool = False) -> pd.DataFrame:
    """Wide date x symbol panel of split/bonus-ADJUSTED prices.

    Live names use Trendlyne's adjusted `ohlcv`; delisted names use raw Bhavcopy x the derived
    `ca_factor.adj_factor` so their returns are split-clean and tradeable. ca_uncertain dead names
    (a large unexplained gap we could not confirm as a CA) are EXCLUDED rather than mis-adjusted.

    `extend_live` (iter-31): for live signals (end=None) only, append the most recent Bhavcopy EOD
    beyond the last Trendlyne bar so signals reflect the latest close we hold — read-only, no write.
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
        if extend_live:
            # Extend live names with Bhavcopy EOD beyond the last Trendlyne bar (back-adjusted series'
            # tail = raw price, so no split adjustment needed for the recent window).
            last_tl = con.execute(
                f"SELECT MAX(date) FROM ohlcv WHERE pk IN ({','.join(['?'] * len(pks))})", pks).fetchone()[0]
            fcol = {"close": "close", "open": "open", "high": "high", "low": "low"}.get(field, "close")
            syms_live = list(live.keys())
            if last_tl is not None and syms_live:
                ext = con.execute(
                    f"SELECT upper(regexp_replace(ticker,'\\.NS$','')) symbol, date, {fcol} v "
                    f"FROM bc.bhavcopy_prices WHERE series='EQ' AND {fcol}>0 AND date > ? "
                    f"AND upper(regexp_replace(ticker,'\\.NS$','')) IN ({','.join(['?'] * len(syms_live))})",
                    [last_tl] + syms_live).fetchdf()
                if not ext.empty:
                    parts.append(ext[["date", "symbol", "v"]])

    dead = [s for s in syms if s not in pkmap]
    if dead:
        # Include ALL delisted names (not just CA-confirmed ones): excluding a name because it has a
        # large unexplained gap silently drops blow-ups (RCOM) and mergers (HDFC/RANBAXY) — that is
        # OPTIMISTIC survivorship bias, the very thing this layer exists to remove. A large gap is
        # usually a real crash/merger, not an unconfirmed split; ca_uncertain is surfaced as a
        # data-quality warning by the caller, never a silent exclusion.
        ok_dead = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM delistings WHERE symbol IN ("
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
          GROUP BY symbol)
        WHERE m > ?""", [str(asof_date), str(asof_date), floor_cr]).fetchall()
    return sorted(r[0] for r in rows if r[0] in _nse_symbols())  # NSE-only gate (adr-024)


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
    # Bridge small daily gaps (≈2 trading weeks) but DO NOT forward-fill past a name's last
    # observation — a delisted name must drop out of the universe, not look perpetually eligible.
    wide = wide.reindex(wide.index.union(idx)).ffill(limit=10).reindex(idx)
    out = (wide > floor_cr).reindex(columns=syms).fillna(False)
    bad = [s for s in out.columns if s not in _nse_symbols()]  # NSE-only gate (adr-024)
    if bad:
        out[bad] = False
    return out


def delistings() -> pd.DataFrame:
    """Terminal-exit registry: symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain."""
    return _con().execute(
        "SELECT symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain FROM delistings"
    ).fetchdf()


@functools.lru_cache(maxsize=1)
def ca_uncertain_symbols() -> frozenset[str]:
    """Delisted names whose corporate-action adjustment could not be confirmed (a large unexplained
    gap). Surfaced as a data-quality WARNING — these names are still tradeable (excluding them would
    drop real blow-ups/mergers = optimistic survivorship bias)."""
    return frozenset(r[0] for r in _con().execute(
        "SELECT symbol FROM delistings WHERE ca_uncertain").fetchall())


def universe_over_window(start, end, floor_cr: float = MCAP_FLOOR_CR) -> list[str]:
    """Every symbol that was EVER above the floor between start and end (live + ALL delisted).

    This is the survivorship-free candidate set for a backtest window; membership_panel then gates
    each name to the specific dates it actually qualified. Delisted names are included regardless of
    ca_uncertain (excluding them would bias out blow-ups/mergers); ca_uncertain is a warning only.
    """
    rows = _con().execute("""
        SELECT DISTINCT symbol FROM universe_membership
        WHERE date >= CAST(? AS DATE) AND date <= CAST(? AS DATE) AND mcap_cr > ?
        GROUP BY symbol HAVING max(mcap_cr) > ?""",
        [str(start), str(end), floor_cr, floor_cr]).fetchall()
    return sorted(r[0] for r in rows if r[0] in _nse_symbols())  # NSE-only gate (adr-024)


def traded_value_panel(symbols, start=None, end=None) -> pd.DataFrame:
    """Daily rupee turnover (raw NSE Bhavcopy `turnover`) for ADTV / liquidity sizing — wide
    date x symbol. Uses real traded value (split-invariant), live and dead names alike."""
    syms = [s.upper() for s in symbols]
    cond = ("WHERE series='EQ' AND turnover>0 AND upper(regexp_replace(ticker,'\\.NS$','')) IN ("
            + ",".join(["?"] * len(syms)) + ")")
    params = syms[:]
    if start:
        cond += " AND date >= ?"; params.append(start)
    if end:
        cond += " AND date <= ?"; params.append(end)
    df = _con().execute(
        f"SELECT upper(regexp_replace(ticker,'\\.NS$','')) symbol, date, turnover v "
        f"FROM bc.bhavcopy_prices {cond}", params).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="symbol", values="v").sort_index()


_DVM = {"durability": "d", "valuation": "v", "momentum": "m",
        "tl_durability": "d", "tl_valuation": "v", "tl_momentum": "m"}
_VAL = {"tl_pe": "PE_TTM", "tl_peg": "PEG_TTM", "tl_pbv": "PBV_A",
        "pe_ttm": "PE_TTM", "peg_ttm": "PEG_TTM", "pbv": "PBV_A"}


def _pk_panel(table, col, key, symbols) -> pd.DataFrame:
    """Wide date x symbol panel for a pk-keyed (score|metric, date, value) table."""
    syms = [s.upper() for s in symbols]
    pkmap = symbol_pk_map()
    live = {pk: s for s, pk in ((s, pkmap[s]) for s in syms if s in pkmap)}
    if not live:
        return pd.DataFrame()
    pks = list(live.keys())
    df = _con().execute(
        f"SELECT pk, date, value FROM {table} WHERE {col}=? AND pk IN ("
        + ",".join(["?"] * len(pks)) + ")", [key] + pks).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = df["pk"].map(live)
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="symbol", values="value").sort_index()


def dvm_panel(score: str, symbols) -> pd.DataFrame:
    """Trendlyne's own daily Durability/Valuation/Momentum score (0-100). Published daily, so it is
    inherently point-in-time (no look-ahead lag needed)."""
    return _pk_panel("dvm_history", "score", _DVM[score], symbols)


def valuation_panel(metric: str, symbols) -> pd.DataFrame:
    """Trendlyne daily valuation multiple: PE_TTM / PEG_TTM / PBV_A. Published daily -> point-in-time.

    PE_TTM and PEG_TTM are NEGATIVE for loss-makers and explode near zero earnings (caveat #7). A
    negative PE is NOT 'cheap', so we mask PE/PEG <= 0 -> NaN: a `tl_pe < N` filter then EXCLUDES
    loss-makers (instead of admitting every negative), and an ascending 'prefer-low PE' rank no
    longer ranks loss-makers as the cheapest. PBV is left as-is (negative book is rare and real)."""
    df = _pk_panel("valuation_ratios", "metric", _VAL[metric], symbols)
    if not df.empty and _VAL[metric] in ("PE_TTM", "PEG_TTM"):
        df = df.where(df > 0)
    return df


# Raw earnings-derived fundamentals that DO need an announcement-date lag (result_lag, adr-016).
# All have the long (pk, metric, date, value) shape and a quarterly/annual period_end that joins
# result_lag, so raw_fundamental_panel handles every one identically (iter-32 widened the set).
_RAW_FUND = {"tl_roe": ("ratios_annual", "ROE_A"), "tl_roce": ("ratios_annual", "ROCE_A"),
             "tl_de": ("ratios_annual", "DEBT_CE_A"), "tl_opm": ("ratios_annual", "OPM_A"),
             "tl_eps": ("pnl_annual", "EPS_A"),
             # iter-32 curated factor library:
             "tl_roic": ("ratios_annual", "ROIC_A"), "tl_eyield": ("ratios_annual", "EYield_A"),
             "tl_ps": ("ratios_annual", "PriceToSales_A"),
             "tl_current_ratio": ("ratios_annual", "CRATIO_A"),
             "tl_quick_ratio": ("ratios_annual", "QuickRatio_A"),
             "tl_int_cover": ("ratios_annual", "InterestCoveragePostTax_A"),
             "tl_cfo": ("cashflow", "CFO_A"),
             "tl_piotroski": ("growth_quality", "PITROSKI_F"),
             "tl_np_growth": ("growth_quality", "NP_TTM_GROWTH"),
             "tl_rev_growth": ("growth_quality", "SR_TTM_GROWTH")}

# Unit fix: EYield_A is stored as a FRACTION (0.03 = 3%); scale to a percentage so `tl_eyield > 4`
# means ">4%" (Trendlyne's "Earnings Yield %" convention). Other ratios are already %/ratio-scaled.
_FUND_SCALE = {"tl_eyield": 100.0}


def raw_fundamental_panel(metric: str, symbols, dates) -> pd.DataFrame:
    """Point-in-time annual fundamental, readable only on/after its real result-announcement date.

    Joins the metric's period_end value to `result_lag.available_from` (board-meeting/result date,
    else period_end+45d) so a value is visible only once it was genuinely public — no look-ahead
    (adr-016). Reindexed to `dates` and forward-filled within each name.
    """
    table, col = _RAW_FUND[metric]
    syms = [s.upper() for s in symbols]
    pkmap = symbol_pk_map()
    live = {pk: s for s, pk in ((s, pkmap[s]) for s in syms if s in pkmap)}
    if not live:
        return pd.DataFrame()
    pks = list(live.keys())
    df = _con().execute(f"""
        SELECT f.pk, r.available_from AS avail, f.value
        FROM {table} f JOIN result_lag r ON f.pk=r.pk AND f.date=r.period_end
        WHERE f.metric=? AND f.pk IN ({",".join(["?"]*len(pks))})""",
        [col] + pks).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = df["pk"].map(live)
    df["avail"] = pd.to_datetime(df["avail"])
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    wide = df.pivot_table(index="avail", columns="symbol", values="value").sort_index()
    wide = wide.reindex(wide.index.union(idx)).ffill().reindex(idx)
    return wide * _FUND_SCALE.get(metric, 1.0)


def mcap_panel(symbols, dates) -> pd.DataFrame:
    """Point-in-time market cap (Rs cr), SURVIVORSHIP-FREE: from universe_membership.mcap_cr (the same
    PIT series that feeds the >500cr universe floor, live + delisted). Exposed as a feature so a
    backtest can reproduce Trendlyne 'Market Capitalization' bands (e.g. mcap > 1000, mcap < 50000)
    over history, not just the snapshot value. Forward-filled (<=2 wks) within each name's window."""
    syms = [s.upper() for s in symbols]
    df = _con().execute(
        "SELECT symbol, date, mcap_cr FROM universe_membership WHERE symbol IN ("
        + ",".join(["?"] * len(syms)) + ")", syms).fetchdf()
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    if df.empty:
        return pd.DataFrame(index=idx)
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="symbol", values="mcap_cr").sort_index()
    return wide.reindex(wide.index.union(idx)).ffill(limit=10).reindex(idx)


_SHARE_CAT = {"tl_pledge": "Pledged", "tl_fii": "FII", "tl_dii": "DII"}


def shareholding_panel(metric: str, symbols, dates) -> pd.DataFrame:
    """Quarterly shareholding % (promoter pledge / FII / DII) from shareholding_summary, readable only
    on/after the real result-announcement date (result_lag join) -> no look-ahead. FFilled to `dates`."""
    cat = _SHARE_CAT[metric]
    syms = [s.upper() for s in symbols]
    pkmap = symbol_pk_map()
    live = {pk: s for s, pk in ((s, pkmap[s]) for s in syms if s in pkmap)}
    if not live:
        return pd.DataFrame()
    pks = list(live.keys())
    df = _con().execute(f"""
        SELECT sh.pk, r.available_from AS avail, sh.pct AS value
        FROM shareholding_summary sh JOIN result_lag r ON sh.pk=r.pk AND sh.date=r.period_end
        WHERE sh.category=? AND sh.pk IN ({",".join(["?"]*len(pks))})""",
        [cat] + pks).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = df["pk"].map(live)
    df["avail"] = pd.to_datetime(df["avail"])
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    wide = df.pivot_table(index="avail", columns="symbol", values="value").sort_index()
    return wide.reindex(wide.index.union(idx)).ffill().reindex(idx)


_BENCH_PK = {"NIFTY50": 1887, "NIFTY500": 1893, "NIFTYNEXT50": 1888,
             "NIFTYMIDCAP": 910393, "NIFTYSMALLCAP": 910398}


@functools.lru_cache(maxsize=1)
def sector_map() -> dict[str, str]:
    """NSE symbol -> sector (Trendlyne `sector_map`, pk-keyed)."""
    rows = _con().execute("""
        SELECT m.sym, coalesce(sm.sector, 'Unknown') FROM sector_map sm
        JOIN (SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode<>''
              UNION SELECT pk, upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol<>'') m
          ON sm.pk=m.pk""").fetchall()
    return {s: sec for s, sec in rows}


def benchmark_series(name: str, start=None, end=None) -> pd.Series:
    """Real index close from Trendlyne `index_ohlcv` (e.g. Nifty 500), not a yfinance proxy."""
    pk = _BENCH_PK.get(name.upper().replace(" ", ""), 1893)
    cond = "WHERE pk=? AND close>0"
    params = [pk]
    if start:
        cond += " AND date >= ?"; params.append(start)
    if end:
        cond += " AND date <= ?"; params.append(end)
    df = _con().execute(f"SELECT date, close FROM index_ohlcv {cond} ORDER BY date", params).fetchdf()
    if df.empty:
        return pd.Series(dtype=float)
    return pd.Series(df["close"].values, index=pd.to_datetime(df["date"]), name=name)
