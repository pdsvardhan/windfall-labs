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
import threading
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

from ..config import DATA_DIR

TRENDLYNE_DB = Path(os.environ.get("WINDFALL_TRENDLYNE_DB", DATA_DIR / "trendlyne.duckdb"))
BHAVCOPY_DB = Path(os.environ.get("WINDFALL_BHAVCOPY_DB", DATA_DIR / "bhavcopy.duckdb"))
# NSE's official market cap + the ISIN company map, built nightly on the host by
# scripts/nse_mcap_ingest.py in the EOD window (adr-050). Attached read-only like Bhavcopy.
NSE_LAYER_DB = Path(os.environ.get("WINDFALL_NSE_LAYER_DB", DATA_DIR / "nse_layer.duckdb"))

MCAP_FLOOR_CR = 500.0   # investable-universe floor: NSE-listed + market cap > Rs500 Cr (adr-015)
# NSE publishes its daily MCAP file (issue size x close, every listed security) from 2024-02-01;
# from that day membership and the mcap feature are NSE's own number, before it the
# Trendlyne-derived pit_mcap (adr-050 step 3).
MCAP_CUTOVER = pd.Timestamp("2024-02-01")
# The NSE gate is point-in-time (adr-050 step 4, #957): a company counts from its first NSE EQ bar
# and only while it has traded on the NSE mainboard within this many calendar days.
GATE_RECENT_DAYS = 90

# NSE mainboard equity series for PRICING a name we already hold or track (iter-171, item 1228).
# EQ is rolling settlement; BE and BZ are trade-for-trade / surveillance segments — same shares, same
# exchange, still deliverable, just no intraday netting. A holding that moves EQ -> BE (which is
# exactly what happens when a name draws surveillance attention) must keep getting a real mark:
# filtering the live splice to EQ alone silently froze 10 open paper positions on dead prices for up
# to 8 weeks, e.g. STALLION marked 254.00 from 10-Aug while it actually closed 206.68 on 04-Sep.
# SME series (SM/ST) are deliberately excluded — a different platform, not the mainboard.
# NOTE this constant governs PRICING only. The investable-universe gate (_nse_symbols), the dead-name
# history splice and the ADTV/turnover panel still read EQ-only; widening those changes which names
# a strategy may select and re-baselines ten years of backtests, so they need an owner decision and
# an ADR rather than a silent edit (raised as a finding in iter-171).
MAINBOARD_SERIES = ("EQ", "BE", "BZ")
_MAINBOARD_SQL_IN = "(" + ",".join(f"'{s}'" for s in MAINBOARD_SERIES) + ")"


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
    px_n, px_min, px_max = con.execute(
        "SELECT COUNT(DISTINCT pk), MIN(date), MAX(date) FROM ohlcv").fetchone()
    dead = con.execute("SELECT COUNT(*) FROM delistings").fetchone()[0]
    if _has_nl():
        # adr-050: NSE's official market cap from MCAP_CUTOVER, so "now" is NSE's latest day and
        # "ever" spans both sources; prices run to the latest Bhavcopy, not the frozen harvest.
        last = con.execute("SELECT MAX(date) FROM nl.mcap_daily").fetchone()[0]
        ever = len(universe_over_window("2000-01-01", str(last), floor_cr))
        now = len(pit_universe(last, floor_cr))
    else:
        ever = con.execute(
            "SELECT COUNT(DISTINCT symbol) FROM universe_membership WHERE mcap_cr > ?",
            [floor_cr]).fetchone()[0]
        last = con.execute("SELECT MAX(date) FROM universe_membership").fetchone()[0]
        now = con.execute(
            "SELECT COUNT(DISTINCT symbol) FROM universe_membership "
            "WHERE mcap_cr > ? AND date >= CAST(? AS DATE) - 14", [floor_cr, str(last)]).fetchone()[0]
    return {"available": True,
            "universe_ever": int(ever or 0), "universe_now": int(now or 0),
            "price_tickers": int(px_n or 0), "delisted": int(dead or 0),
            "survivors_added": len(survivors()),
            "date_min": str(px_min) if px_min else None,
            # date_max stays Trendlyne's own last bar (the frozen harvest, and the end of the DVM
            # history row); prices_to is where prices actually run — the latest Bhavcopy (adr-050).
            "date_max": str(px_max) if px_max else None,
            "prices_to": _prices_to(),
            "floor_cr": floor_cr}


# Serialises the FIRST build of the shared connection. lru_cache is thread-safe for its own dict
# but does not hold a lock across the wrapped call, so every thread that arrives on a cold cache
# runs the body — including the check-then-ATTACH pair below, which is a TOCTOU. Measured
# 2026-09-07 (iter-172, to-do #250): 12 threads on a cleared cache, 11 of them died with
# `Binder Error: Failed to attach database: database with name "bc" already exists`. That is the
# reported "transient 400 on a valid call, fine on retry" — it needs concurrent first-calls, which
# is why it never showed up in single-threaded use or in the tests.
_CON_LOCK = threading.Lock()


def _attach_ro(con, path: Path, alias: str) -> None:
    # DuckDB shares one instance per file path within a process, so another read-only
    # connection may have already attached it — attach only if absent. The probe stays
    # (it is the cheap path), but the ATTACH is idempotent as well: the lock cannot stop a
    # DIFFERENT module holding its own connection to this file from attaching between our
    # check and our act.
    if not path.exists():
        return
    already = con.execute(
        "SELECT count(*) FROM duckdb_databases() WHERE database_name=?", [alias]).fetchone()[0]
    if not already:
        try:
            con.execute(f"ATTACH '{path}' AS {alias} (READ_ONLY)")
        except duckdb.Error as exc:
            if "already exists" not in str(exc):
                raise


@functools.lru_cache(maxsize=1)
def _base_con() -> duckdb.DuckDBPyConnection:
    """Process-wide read-only connection; bhavcopy (`bc`) and the NSE layer (`nl`) attached read-only."""
    with _CON_LOCK:
        con = duckdb.connect(str(TRENDLYNE_DB), read_only=True)
        _attach_ro(con, BHAVCOPY_DB, "bc")
        _attach_ro(con, NSE_LAYER_DB, "nl")
        return con


_TLS = threading.local()


def _con() -> duckdb.DuckDBPyConnection:
    """This thread's cursor on the shared read-only connection.

    A DuckDBPyConnection is not safe to query from two threads at once: `execute()` returns the
    connection itself and the result waits on it until fetched, so a second thread's execute in
    between replaces the first thread's pending result and its `.fetchdf()` comes back None. That
    is the intermittent /api/paper/equity 500 (iter-197, item 1420): `'NoneType' object has no
    attribute 'empty'` in adjusted_close_panel, 1 of 8 loads over 72h, whenever the page's four
    parallel requests overlapped. DuckDB's answer is one cursor per thread — cursors share the
    database instance (and the attached `bc`) but each holds its own result.
    """
    base = _base_con()
    cur = getattr(_TLS, "cur", None)
    if cur is None or getattr(_TLS, "base", None) is not base:
        cur = base.cursor()
        _TLS.cur, _TLS.base = cur, base
    return cur


# Tests re-point TRENDLYNE_DB and clear the cache; clearing the base connection makes every
# thread's cursor stale (the identity check above), so the next call re-opens on the new file.
_con.cache_clear = _base_con.cache_clear


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


@functools.lru_cache(maxsize=1)
def _ticker_aliases() -> dict:
    """NSE symbol -> frozenset of ALL tickers that ever shared its ISIN (ticker renames; e.g. NAVA
    was NBVENTURES until 2022). Bhavcopy keeps a company's pre-rename history under its OLD ticker,
    so symbol-keyed lookups (turnover, dead-name prices, pit-mcap) miss it — making renamed names
    spuriously fail the liquidity filter and lose price history in their pre-rename window (adr-025).
    ISIN is the stable company id, so all tickers under one ISIN are the same company."""
    rows = _con().execute(
        "SELECT isin, upper(regexp_replace(ticker,'\\.NS$','')) FROM bc.bhavcopy_prices "
        "WHERE series='EQ' AND isin IS NOT NULL AND isin<>'' GROUP BY 1,2").fetchall()
    by_isin: dict = {}
    for isin, sym in rows:
        by_isin.setdefault(isin, set()).add(sym)
    # ACCUMULATE across every ISIN a symbol touches (a name can have >1 ISIN after a face-value change,
    # e.g. NAVA has INE725A01022 [shared with NBVENTURES] AND a later INE725A01030) — don't overwrite.
    out: dict = {}
    for syms in by_isin.values():
        for s in syms:
            out.setdefault(s, set()).update(syms)
    return {s: frozenset(v) for s, v in out.items()}


def _alias_to_canonical(symbols) -> dict:
    """{every historical ticker -> the requested (current) symbol}, so Bhavcopy rows found under an
    old ticker can be relabelled to the symbol the caller asked for."""
    al = _ticker_aliases()
    req = sorted({s.upper() for s in symbols})
    asked = set(req)
    m: dict = {}
    for s in req:
        for a in sorted(al.get(s, frozenset({s}))):
            if a in asked and a != s:
                continue          # a ticker that is itself requested keeps its own label (#967)
            m.setdefault(a, s)    # an alias two requested symbols share goes to the alphabetically first
        m[s] = s
    return m


# ── the point-in-time NSE gate (adr-050 step 4, #957) ────────────────────────────────────────
#
# adr-024 gated the universe on "the name EVER traded in series EQ". Measured against NSE's
# official market cap (iter-200, explain_membership.py) that admits ~95 companies per month-end
# before their first NSE bar (BSE-only names that joined NSE later: ACGL, AKCAPIT, ASHIKA) and ~15
# whose NSE line had gone idle (GOODYEAR, KENNAMET, KOVAI) — a look-ahead in every backtest and
# signal. The gate is now by company (every ticker sharing its ISIN, adr-025) and by date: a
# company counts on day d only if its first EQ bar is on or before d AND it traded on the NSE
# mainboard (EQ/BE/BZ) within GATE_RECENT_DAYS before d.

@functools.lru_cache(maxsize=1)
def _first_eq_by_ticker() -> dict[str, pd.Timestamp]:
    return {s: pd.Timestamp(d) for s, d in _con().execute(
        "SELECT upper(regexp_replace(ticker,'\\.NS$','')), min(date) FROM bc.bhavcopy_prices "
        "WHERE series='EQ' GROUP BY 1").fetchall()}


def first_nse_bar(symbols) -> dict[str, pd.Timestamp]:
    """{symbol: the company's first EQ bar on NSE} across every ticker it has used; absent = never."""
    fe, al = _first_eq_by_ticker(), _ticker_aliases()
    out = {}
    for s in symbols:
        s = s.upper()
        ds = [fe[a] for a in al.get(s, frozenset({s})) | {s} if a in fe]
        if ds:
            out[s] = min(ds)
    return out


@functools.lru_cache(maxsize=1)
def _bhav_start() -> pd.Timestamp:
    """First day NSE Bhavcopy covers (2010-01-04). Before it neither a listing date nor recent
    trading can be observed."""
    d = _con().execute("SELECT min(date) FROM bc.bhavcopy_prices").fetchone()[0]
    return pd.Timestamp(d) if d else pd.Timestamp("2010-01-04")


# A company whose first Bhavcopy bar falls within this many days of Bhavcopy's start was already
# listed when coverage began; that is all the gate can know about dates before 2010 (Trendlyne's
# history starts 2006, and adr-040's untouched 2007–2016 validation decade runs there).
_PRE_COVERAGE_SLACK_DAYS = 30


def _listed_by(first: pd.Timestamp | None, d: pd.Timestamp) -> bool:
    if first is None:
        return False
    start = _bhav_start()
    if d < start:
        return first <= start + pd.Timedelta(days=_PRE_COVERAGE_SLACK_DAYS)
    return first <= d


def nse_gate_at(symbols, asof) -> set[str]:
    """The symbols that pass the point-in-time NSE gate on `asof`."""
    asof = pd.Timestamp(asof)
    first = first_nse_bar(symbols)
    if asof < _bhav_start():          # no tape before coverage: listed-at-coverage-start is the test
        return {s.upper() for s in symbols if _listed_by(first.get(s.upper()), asof)}
    # Same window as nse_gate_panel: a trade on or after asof - GATE_RECENT_DAYS counts.
    recent = {r[0] for r in _con().execute(
        f"SELECT DISTINCT upper(regexp_replace(ticker,'\\.NS$','')) FROM bc.bhavcopy_prices "
        f"WHERE series IN {_MAINBOARD_SQL_IN} AND date >= CAST(? AS DATE) - {GATE_RECENT_DAYS} "
        f"AND date <= CAST(? AS DATE)", [str(asof.date()), str(asof.date())]).fetchall()}
    al = _ticker_aliases()
    return {s.upper() for s in symbols
            if _listed_by(first.get(s.upper()), asof)
            and (al.get(s.upper(), frozenset()) | {s.upper()}) & recent}


def nse_gate_panel(symbols, idx) -> pd.DataFrame:
    """Bool date x symbol: True where the symbol passes the point-in-time NSE gate that day."""
    syms = [s.upper() for s in symbols]
    idx = pd.DatetimeIndex(idx)
    out = pd.DataFrame(False, index=idx, columns=syms)
    if not syms or len(idx) == 0:
        return out
    first = first_nse_bar(syms)
    al = _ticker_aliases()
    # Per symbol, every ticker its company used — kept as sets, not inverted into one dict, so a
    # ticker two requested symbols share (a renamed company listed under both) counts for both.
    own = {s: (al.get(s, frozenset()) | {s}) for s in syms}
    tick = sorted(set().union(*own.values()))
    lo = (idx.min() - pd.Timedelta(days=GATE_RECENT_DAYS)).date()
    df = _con().execute(
        f"SELECT DISTINCT upper(regexp_replace(ticker,'\\.NS$','')) AS t, date FROM bc.bhavcopy_prices "
        f"WHERE series IN {_MAINBOARD_SQL_IN} AND date >= ? AND date <= ? "
        f"AND upper(regexp_replace(ticker,'\\.NS$','')) IN ({','.join(['?'] * len(tick))})",
        [str(lo), str(idx.max().date())] + tick).fetchdf()
    if df.empty:
        return _pre_coverage(out, first)
    df["date"] = pd.to_datetime(df["date"])
    # Integer nanoseconds on BOTH sides: pandas 3 builds date indexes in microseconds while
    # Timedelta.value is always ns — mixing them made "90 days" mean 90,000 days.
    df["v"] = df["date"].astype("datetime64[ns]").astype("int64")
    by_t = df.pivot_table(index="date", columns="t", values="v", aggfunc="max").sort_index()
    by_t = by_t.reindex(by_t.index.union(idx)).ffill().reindex(idx)   # last trade on/before each day
    cols = {s: by_t[[t for t in ts_ if t in by_t.columns]].max(axis=1)
            for s, ts_ in own.items() if any(t in by_t.columns for t in ts_)}
    if not cols:
        return _pre_coverage(out, first)
    last = pd.DataFrame(cols, index=idx)
    age = last.rsub(pd.Series(idx.astype("datetime64[ns]").asi8, index=idx), axis=0)   # ns since
    recent = age.le(pd.Timedelta(days=GATE_RECENT_DAYS).value) & last.notna()
    listed = pd.DataFrame({s: idx >= first[s] if s in first else [False] * len(idx)
                           for s in last.columns}, index=idx)
    gate = (recent & listed).reindex(columns=syms).fillna(False).astype(bool)
    return _pre_coverage(gate, first)


def _pre_coverage(gate: pd.DataFrame, first: dict) -> pd.DataFrame:
    """Before Bhavcopy's first day there is no tape: a company passes if it was already listed
    when coverage began (else every pre-2010 date would have an empty universe)."""
    start = _bhav_start()
    early = gate.index < start
    if early.any():
        for s in gate.columns:
            gate.loc[early, s] = _listed_by(first.get(s), gate.index[0])
    return gate


# ── NSE's official market cap and the companies Trendlyne never listed (adr-050 steps 3, 5) ───

def _has_nl() -> bool:
    try:
        return bool(_con().execute(
            "SELECT count(*) FROM duckdb_databases() WHERE database_name='nl'").fetchone()[0])
    except duckdb.Error:
        return False


@functools.lru_cache(maxsize=1)
def survivors() -> dict[str, tuple[pd.Timestamp, float]]:
    """{engine symbol: (first NSE MCAP date, official mcap that day)} for every company NSE put
    above the floor on some day from MCAP_CUTOVER that has no Trendlyne row at all (#959: 157 such
    companies in 2024-26, 142 of the 149 still listed now under Rs500cr — the stock list had
    dropped them, which biased every backtest upward). Empty without the NSE layer."""
    if not _has_nl():
        return {}
    return {s: (pd.Timestamp(d), float(m)) for s, d, m in _con().execute(
        "SELECT engine_symbol, first_mcap_date, first_mcap_cr FROM nl.companies "
        "WHERE survivor").fetchall()}


@functools.lru_cache(maxsize=1)
def _frozen_alias() -> dict[str, str]:
    """{frozen universe_membership symbol: engine symbol} for companies renamed after the last
    membership build. universe_membership is frozen with the price history (adr-050) while
    stocks.nsecode follows renames, so the company's pre-2024 rows sit under its old symbol; they
    are read under the new one rather than as a second company (iter-204 verifier B5)."""
    if not _has_nl():
        return {}
    try:
        return {o: e for e, o in _con().execute(
            "SELECT engine_symbol, membership_symbol FROM nl.companies "
            "WHERE membership_symbol IS NOT NULL AND membership_symbol <> engine_symbol").fetchall()}
    except duckdb.Error:          # a layer built before iter-204's membership_symbol column
        return {}


@functools.lru_cache(maxsize=1)
def _survivor_pre_mcap() -> pd.DataFrame:
    """Long (symbol, date, mcap_cr) for survivors BEFORE MCAP_CUTOVER: their split/bonus/rights-
    adjusted Bhavcopy close x the share count implied by their first NSE MCAP reading — pit_mcap's
    own method (adjusted close x one share count held constant), so a survivor and a Trendlyne name
    are measured the same way before 2024. Computed once per process (the api restarts nightly)."""
    sv = survivors()
    if not sv:
        return pd.DataFrame(columns=["symbol", "date", "mcap_cr"])
    adj = _bhavcopy_adjusted(list(sv), None, None, "close")
    parts = []
    for s, (d0, m0) in sv.items():
        if s not in adj.columns:
            continue
        col = adj[s].dropna()
        at = col[col.index <= d0]
        if at.empty or not at.iloc[-1] > 0:
            continue
        shares = m0 / float(at.iloc[-1])
        pre = col[col.index < MCAP_CUTOVER] * shares
        if not pre.empty:
            parts.append(pd.DataFrame({"symbol": s, "date": pre.index, "mcap_cr": pre.values}))
    return (pd.concat(parts, ignore_index=True) if parts
            else pd.DataFrame(columns=["symbol", "date", "mcap_cr"]))


def _membership_long(syms) -> pd.DataFrame:
    """Long (symbol, date, mcap_cr): the point-in-time market cap membership is read from.

    Before MCAP_CUTOVER, Trendlyne's `universe_membership` (pit_mcap) plus survivors' Bhavcopy-
    derived figure; from it, NSE's official market cap mapped to engine symbols by ISIN. Without
    the NSE layer (tests, a bare checkout), `universe_membership` alone, as before adr-050.
    """
    ph = ",".join(["?"] * len(syms))
    nl = _has_nl()
    cond = " AND date < CAST(? AS DATE)" if nl else ""
    src = {o: e for o, e in _frozen_alias().items() if e in syms}     # renamed after the freeze
    want = syms + [o for o in src if o not in syms]
    tl_part = _con().execute(
        f"SELECT symbol, date, mcap_cr FROM universe_membership "
        f"WHERE symbol IN ({','.join(['?'] * len(want))}){cond}",
        want + ([str(MCAP_CUTOVER.date())] if nl else [])).fetchdf()
    if src and not tl_part.empty:
        tl_part["symbol"] = tl_part["symbol"].map(lambda x: src.get(x, x))
    parts = [tl_part]
    if nl:
        parts.append(_con().execute(f"""
            SELECT t.engine_symbol AS symbol, m.date, max(m.mcap_cr) AS mcap_cr
            FROM nl.mcap_daily m JOIN nl.ticker_map t ON t.ticker = m.symbol
            WHERE t.engine_symbol IN ({ph}) AND m.date >= CAST(? AS DATE)
            GROUP BY 1, 2""", syms + [str(MCAP_CUTOVER.date())]).fetchdf())
        sv = [s for s in syms if s in survivors()]
        if sv:
            pre = _survivor_pre_mcap()
            parts.append(pre[pre["symbol"].isin(sv)])
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=["symbol", "date", "mcap_cr"])
    out = pd.concat(parts, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


def adjusted_close_panel(symbols, start=None, end=None, field: str = "close",
                         extend_live: bool = False) -> pd.DataFrame:
    """Wide date x symbol panel of split/bonus-ADJUSTED prices.

    Live names use Trendlyne's adjusted `ohlcv`; delisted names use raw Bhavcopy x the derived
    `ca_factor.adj_factor` so their returns are split-clean and tradeable. ca_uncertain dead names
    (a large unexplained gap we could not confirm as a CA) are EXCLUDED rather than mis-adjusted.

    `extend_live` (iter-31): for live signals (end=None) only, append the most recent Bhavcopy EOD
    beyond the last Trendlyne bar so signals reflect the latest close we hold — read-only, no write.

    Names with NO Trendlyne bars — listed after the price history was frozen (adr-050 step 1) or
    never in Trendlyne's stock list at all (step 5, #959) — and not in the delisting registry are
    priced from raw Bhavcopy back-adjusted with NSE's corporate actions (`_bhavcopy_adjusted`):
    the free layer that matched Trendlyne's own factor on 95.9% of names since 2016 (iter-200).
    """
    syms = [s.upper() for s in symbols]
    pkmap = symbol_pk_map()
    has_bars = _ohlcv_pks()
    live = {s: pkmap[s] for s in syms if s in pkmap and pkmap[s] in has_bars}
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
        # Trendlyne's history is frozen (adr-050), so a window with an explicit end past a name's
        # last bar needs the Bhavcopy tail just as a live one does — otherwise a backtest ending
        # after the freeze (the builder's End field, every walk-forward OOS window) silently loses
        # every Trendlyne-priced name from the freeze on (iter-204 verifier B2). Bounded by `end`.
        if extend_live or end:
            # Extend live names with Bhavcopy EOD beyond the last Trendlyne bar (back-adjusted series'
            # tail = raw price, so no split adjustment needed for the recent window).
            #
            # PER SYMBOL, not per batch (iter-172, to-do #820 / adr-044). This used to take ONE
            # scalar — MAX(date) across every requested pk — and splice only `date > last_tl` for
            # everybody. Any name whose own history ended earlier than the batch maximum got no
            # Bhavcopy rows for the gap between its last bar and last_tl, so its column carried
            # leading NaNs that .ffill() cannot repair. The same stock returned different data
            # depending on who else you asked for: SCPL alone was a clean series from 2026-06-29;
            # SCPL inside the 98-name paper batch was NaN until 2026-07-09, and book_equity valued
            # it at entry price for its whole holding period (+14.9% reported as a flat 0.0%).
            # Measured 2026-09-07: 1,529 of 1,782 names lagged the batch maximum.
            fcol = {"close": "close", "open": "open", "high": "high", "low": "low"}.get(field, "close")
            syms_live = list(live.keys())
            if syms_live:
                ph_pk = ",".join(["?"] * len(pks))
                ph_sym = ",".join(["?"] * len(syms_live))
                ext = con.execute(f"""
                    WITH sym AS (
                        SELECT upper(nsecode) s, pk FROM stocks WHERE nsecode <> ''
                        UNION SELECT upper(nse_symbol), pk FROM recovered_symbols
                        WHERE nse_symbol <> ''),
                    tails AS (
                        SELECT pk, MAX(date) AS last_tl FROM ohlcv
                        WHERE pk IN ({ph_pk}) GROUP BY pk)
                    SELECT m.s AS symbol, b.date, b.{fcol} AS v
                    FROM bc.bhavcopy_prices b
                    JOIN sym m ON upper(regexp_replace(b.ticker, '\\.NS$', '')) = m.s
                    JOIN tails t ON t.pk = m.pk
                    WHERE b.series IN {_MAINBOARD_SQL_IN} AND b.{fcol} > 0
                      AND b.date > t.last_tl
                      AND m.s IN ({ph_sym}) {"AND b.date <= ?" if end else ""}
                """, pks + syms_live + ([end] if end else [])).fetchdf()
                if not ext.empty:
                    parts.append(ext[["date", "symbol", "v"]])

    unpriced = [s for s in syms if s not in live]
    registry = set()
    if unpriced:
        registry = {r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM delistings WHERE symbol IN ("
            + ",".join(["?"] * len(unpriced)) + ")", unpriced).fetchall()}
    free = [s for s in unpriced if s not in registry]
    if free:
        bh = _bhavcopy_adjusted(free, start, end, field)
        if not bh.empty:
            long_bh = bh.stack().rename("v").reset_index()
            long_bh.columns = ["date", "symbol", "v"]
            parts.append(long_bh)

    dead = [s for s in unpriced if s in registry]
    if dead:
        # Include ALL delisted names (not just CA-confirmed ones): excluding a name because it has a
        # large unexplained gap silently drops blow-ups (RCOM) and mergers (HDFC/RANBAXY) — that is
        # OPTIMISTIC survivorship bias, the very thing this layer exists to remove. A large gap is
        # usually a real crash/merger, not an unconfirmed split; ca_uncertain is surfaced as a
        # data-quality warning by the caller, never a silent exclusion.
        ok_dead = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM delistings WHERE symbol IN ("
            + ",".join(["?"] * len(dead)) + ") ORDER BY symbol", dead).fetchall()]
        if ok_dead:
            a2c = _alias_to_canonical(ok_dead)   # incl pre-rename tickers of renamed-then-dead names (adr-025)
            dtick = list(a2c.keys())
            cond = ("WHERE b.series='EQ' AND b.close>0 AND upper(regexp_replace(b.ticker,'\\.NS$',''))"
                    " IN (" + ",".join(["?"] * len(dtick)) + ")")
            params = dtick[:]
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
                df["symbol"] = df["symbol"].map(a2c)   # relabel old tickers to the delisted name
                parts.append(df[["date", "symbol", "v"]])

    if not parts:
        return pd.DataFrame()
    long = pd.concat(parts, ignore_index=True)
    long["date"] = pd.to_datetime(long["date"])
    wide = long.pivot_table(index="date", columns="symbol", values="v").sort_index()
    if (extend_live or end) and live:
        wide = _adjust_live_tail(wide, live)
    return wide


def _last_tl_dates(live: dict[str, int]) -> dict[str, pd.Timestamp]:
    """{symbol: its last Trendlyne ohlcv bar} — where its raw Bhavcopy tail begins."""
    pk2sym = {pk: s for s, pk in live.items()}
    rows = _con().execute(
        f"SELECT pk, max(date) FROM ohlcv WHERE pk IN ({','.join(['?'] * len(pk2sym))}) GROUP BY pk",
        list(pk2sym)).fetchall()
    return {pk2sym[pk]: pd.Timestamp(d) for pk, d in rows if d is not None}


def apply_tail_corporate_actions(wide: pd.DataFrame, last_tl: dict, events: dict) -> pd.DataFrame:
    """Back-adjust split/bonus/consolidation ex-dates that fall inside a name's raw Bhavcopy tail.

    Trendlyne's `ohlcv` is back-adjusted for every event up to its harvest, so an ex-date on or
    before the name's last Trendlyne bar is already in the series and is left alone (adjusting it
    again would double it). An ex-date AFTER that bar sits in the raw tail: every bar before it is
    divided by the event's ratio, so the latest bar stays the raw traded price — the same series
    Trendlyne publishes once it catches up (iter-199, #952). Events not yet in the panel (an
    announced future ex-date) do nothing.
    """
    if wide.empty or not events:
        return wide
    for sym, evs in events.items():
        lt = last_tl.get(sym)
        if sym not in wide.columns or lt is None:
            continue
        # This name's own last bar, not the batch's: a name with no bar on/after the ex-date has
        # not traded post-event yet, and its latest price must stay raw (verifier finding 5).
        last_bar = wide[sym].last_valid_index()
        if last_bar is None:
            continue
        for exd, ratio in evs:
            ex = pd.Timestamp(exd)
            if ex <= lt or ex > last_bar or not ratio:
                continue
            before = wide.index < ex
            wide.loc[before, sym] = wide.loc[before, sym] / ratio
    return wide


def _adjust_live_tail(wide: pd.DataFrame, live: dict[str, int]) -> pd.DataFrame:
    from .corp_actions import ratio_events     # meta-store read; imported lazily (no cycle at import)
    events = ratio_events(live.keys())
    if not events:
        return wide
    return apply_tail_corporate_actions(wide, _last_tl_dates({s: live[s] for s in events if s in live}),
                                        events)


@functools.lru_cache(maxsize=1)
def _ohlcv_pks() -> frozenset[int]:
    """Trendlyne pks that have any adjusted bar. A pk without one (a listing after the frozen
    harvest, adr-050) is priced from Bhavcopy instead of returning nothing."""
    return frozenset(r[0] for r in _con().execute("SELECT DISTINCT pk FROM ohlcv").fetchall())


def last_raw_close_before(symbol: str, day) -> float | None:
    """The last raw mainboard close strictly before `day` — the cum-rights price P a rights issue's
    theoretical ex-rights price is computed from (corp_actions.price_rights). NSE's list files an
    old event under the company's CURRENT symbol, so every ticker it has used is searched."""
    s = str(symbol).upper()
    tick = sorted(_ticker_aliases().get(s, frozenset()) | {s})
    r = _con().execute(
        f"SELECT close FROM bc.bhavcopy_prices WHERE upper(regexp_replace(ticker,'\\.NS$','')) IN "
        f"({','.join(['?'] * len(tick))}) "
        f"AND series IN {_MAINBOARD_SQL_IN} AND close > 0 AND date < CAST(? AS DATE) "
        f"ORDER BY date DESC LIMIT 1", tick + [str(day)]).fetchone()
    return float(r[0]) if r else None


def _prices_to() -> str | None:
    try:
        d = _con().execute("SELECT max(date) FROM bc.bhavcopy_prices").fetchone()[0]
    except duckdb.Error:
        return None
    return str(d) if d else None


def apply_corporate_actions(wide: pd.DataFrame, events: dict) -> pd.DataFrame:
    """Back-adjust a RAW price panel for every event inside each name's own history: bars before an
    ex-date divide by its ratio, so the latest bar stays the traded price (Trendlyne's convention).
    An ex-date after a name's last bar (announced, or after a delisting) does nothing."""
    for sym, evs in events.items():
        if sym not in wide.columns:
            continue
        last_bar = wide[sym].last_valid_index()
        if last_bar is None:
            continue
        for exd, ratio in evs:
            ex = pd.Timestamp(exd)
            if ex > last_bar or not ratio:
                continue
            before = wide.index < ex
            wide.loc[before, sym] = wide.loc[before, sym] / ratio
    return wide


def _bhavcopy_adjusted(symbols, start=None, end=None, field: str = "close") -> pd.DataFrame:
    """Wide date x symbol of raw NSE mainboard Bhavcopy, back-adjusted with NSE's corporate actions
    (splits, bonuses, consolidations, combined subjects and rights at P/TERP — corp_actions).

    Rows filed under a company's earlier tickers are relabelled to the requested symbol (adr-025),
    and so are the events NSE filed under them. Used for every name Trendlyne has no bars for
    (adr-050): the companies it never listed and listings after its frozen harvest.
    """
    from .corp_actions import ratio_events     # meta-store read; imported lazily (no cycle at import)

    syms = [s.upper() for s in symbols]
    if not syms:
        return pd.DataFrame()
    a2c = _alias_to_canonical(syms)
    tick = list(a2c)
    fcol = {"close": "close", "open": "open", "high": "high", "low": "low"}.get(field, "close")
    cond = (f"WHERE series IN {_MAINBOARD_SQL_IN} AND {fcol} > 0 "
            "AND upper(regexp_replace(ticker,'\\.NS$','')) IN (" + ",".join(["?"] * len(tick)) + ")")
    params = tick[:]
    if start:
        cond += " AND date >= ?"; params.append(start)
    if end:
        cond += " AND date <= ?"; params.append(end)
    df = _con().execute(
        f"SELECT upper(regexp_replace(ticker,'\\.NS$','')) t, date, {fcol} v "
        f"FROM bc.bhavcopy_prices {cond}", params).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = df["t"].map(a2c)
    df["date"] = pd.to_datetime(df["date"])
    # One bar per company-day: a day it traded under two tickers/series is a re-listing overlap.
    wide = df.pivot_table(index="date", columns="symbol", values="v", aggfunc="last").sort_index()
    # ratio_events already collapses a duplicate filing per symbol and keeps a same-day split +
    # bonus pair (two events, one ratio). Across a company's tickers an event filed under both its
    # old and new symbol must count once: per (ex_date, ratio), take the largest count any single
    # ticker carries (Counter union), so a shared event is applied once and a pair still twice.
    merged: dict[str, Counter] = {}
    for alias, evs in ratio_events(tick).items():
        canon = a2c.get(alias, alias)
        merged[canon] = merged.get(canon, Counter()) | Counter(evs)
    events = {s: sorted(c.elements()) for s, c in merged.items()}
    return apply_corporate_actions(wide, events)


def pit_universe(asof_date, floor_cr: float = MCAP_FLOOR_CR) -> list[str]:
    """Survivorship-free investable universe at `asof_date`: symbols whose most-recent point-in-time
    market cap within the prior ~2 weeks exceeds the floor (live + confirmed-tradeable dead +
    the companies Trendlyne never listed), behind the point-in-time NSE gate (adr-050)."""
    asof = pd.Timestamp(asof_date)
    d = str(asof.date())
    if _has_nl() and asof >= MCAP_CUTOVER:
        # The latest reading in the window; where several rows share that date (a company's tickers
        # map to one engine symbol) the LARGEST wins — arg_max over a tie returns whichever row the
        # scan met first, which differs between processes (#967).
        rows = _con().execute("""
            SELECT symbol FROM (
              SELECT symbol, max(mcap_cr) AS mc FROM (
                SELECT t.engine_symbol AS symbol, m.date, m.mcap_cr,
                       max(m.date) OVER (PARTITION BY t.engine_symbol) AS last_date
                FROM nl.mcap_daily m JOIN nl.ticker_map t ON t.ticker = m.symbol
                WHERE m.date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE))
              WHERE date = last_date
              GROUP BY symbol)
            WHERE mc > ?""", [d, d, floor_cr]).fetchall()
        cands = {r[0] for r in rows}
    else:
        # universe_membership holds twin rows (live + dead) for a few symbols (MBECL, MAZDA,
        # SHALPAINTS); same rule as above — the latest date, then the larger value (#967).
        rows = _con().execute("""
            SELECT symbol FROM (
              SELECT symbol, max(mcap_cr) AS m FROM (
                SELECT symbol, date, mcap_cr, max(date) OVER (PARTITION BY symbol) AS last_date
                FROM universe_membership
                WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE))
              WHERE date = last_date
              GROUP BY symbol)
            WHERE m > ?""", [d, d, floor_cr]).fetchall()
        alias = _frozen_alias()
        cands = {alias.get(r[0], r[0]) for r in rows}
        pre = _survivor_pre_mcap()
        if not pre.empty:
            win = pre[(pre["date"] > asof - pd.Timedelta(days=14)) & (pre["date"] <= asof)]
            last = win.sort_values("date").groupby("symbol")["mcap_cr"].last()
            cands |= set(last[last > floor_cr].index)
    return sorted(nse_gate_at(cands, asof))   # point-in-time NSE gate (adr-050, #957)


def _bhavcopy_mcap_panel(symbols, idx) -> pd.DataFrame:
    """Market cap (Rs cr) from Bhavcopy close x the share count the main pipeline used.

    The shares figure is read back out of `pit_mcap` rather than re-derived, so this is the same
    `shares_now` that built `universe_membership` — a fallback that disagreed with the primary
    path about share count would be worse than no fallback at all.

    That count is as of pit_mcap's last row. A split or bonus after it multiplies the shares while
    the raw close falls by the same ratio, so from its ex-date the count is scaled up (iter-199,
    #952) — otherwise a 1:5 split read as an 80% market-cap collapse and could drop the name
    under the Rs500cr floor.
    """
    syms = [s.upper() for s in symbols]
    if not syms:
        return pd.DataFrame(index=idx)
    ph = ",".join(["?"] * len(syms))
    df = _con().execute(f"""
        WITH shares AS (
            SELECT pk, arg_max(shares_cr, date) AS shares_cr, max(date) AS shares_date
            FROM pit_mcap WHERE shares_cr IS NOT NULL GROUP BY pk),
        sym AS (
            SELECT upper(nsecode) s, pk FROM stocks WHERE nsecode <> ''
            UNION SELECT upper(nse_symbol), pk FROM recovered_symbols WHERE nse_symbol <> '')
        SELECT m.s AS symbol, b.date, b.close * sh.shares_cr AS mcap_cr, sh.shares_date
        FROM bc.bhavcopy_prices b
        JOIN sym m ON upper(regexp_replace(b.ticker, '\\.NS$', '')) = m.s
        JOIN shares sh ON sh.pk = m.pk
        WHERE b.series IN {_MAINBOARD_SQL_IN} AND b.close > 0 AND m.s IN ({ph})
    """, syms).fetchdf()
    if df.empty:
        return pd.DataFrame(index=idx)
    df["date"] = pd.to_datetime(df["date"])
    shares_date = {s: pd.Timestamp(d) for s, d in
                   df.groupby("symbol")["shares_date"].first().items() if pd.notna(d)}
    wide = df.pivot_table(index="date", columns="symbol", values="mcap_cr").sort_index()
    from .corp_actions import share_events    # split/bonus/consolidation — not a rights P/TERP
    return scale_shares_after_corporate_actions(wide, shares_date,
                                                share_events(wide.columns)).reindex(index=idx)


def scale_shares_after_corporate_actions(wide: pd.DataFrame, shares_date: dict,
                                         events: dict) -> pd.DataFrame:
    """Raw close x a pre-event share count: from each later ex-date on, multiply by the ratio."""
    for sym, evs in events.items():
        sd = shares_date.get(sym)
        if sym not in wide.columns or sd is None:
            continue
        for exd, ratio in evs:
            ex = pd.Timestamp(exd)
            if ex <= sd or not ratio:
                continue
            after = wide.index >= ex
            wide.loc[after, sym] = wide.loc[after, sym] * ratio
    return wide


def _pit_mcap_wide(syms, idx, warnings: list | None = None):
    """Wide date x symbol point-in-time market cap (Rs cr), with the Bhavcopy tail fallback.

    Extracted so `membership_panel` and `mcap_panel` cannot disagree (iter-172, to-do #92). They had
    the same query and the same `ffill(limit=10)` written out twice, and adr-046 added the fallback
    to only one of them — leaving the `mcap` FEATURE holed on exactly the dates the ELIGIBILITY gate
    had just been taught to repair. Membership is derived from market cap; two copies of that
    derivation drifting apart is a bug waiting for a rebalance.

    Returns None when the store has nothing for these symbols, so callers can pick their own empty
    shape (all-False mask vs empty frame).

    The readings come from `_membership_long`: Trendlyne's pit_mcap before MCAP_CUTOVER, NSE's
    official market cap from it (adr-050). The Bhavcopy fallback below then only engages when the
    nightly NSE pull is behind (or, without the NSE layer, past the last Trendlyne bar).
    """
    df = _membership_long(syms)
    if df.empty:
        return None
    # mean, as before adr-050: universe_membership holds ~8k duplicate (symbol, date) rows (a live
    # and a dead row for one symbol — SHALPAINTS, MAZDA, MBECL) and master averages them. The
    # sources never overlap on a date (Trendlyne before MCAP_CUTOVER, NSE from it), so the mean
    # only ever meets those Trendlyne twins (iter-204 verifier B3).
    wide = df.pivot_table(index="date", columns="symbol", values="mcap_cr", aggfunc="mean").sort_index()
    # Each symbol's last genuine reading, BEFORE any reindex/ffill invents shape around it.
    last_obs = wide.apply(lambda c: c.last_valid_index())
    # Bridge small daily gaps (≈2 trading weeks) but DO NOT forward-fill past a name's last
    # observation — a delisted name must drop out of the universe, not look perpetually eligible.
    wide = wide.reindex(wide.index.union(idx)).ffill(limit=10).reindex(idx)

    stale = [s for s in wide.columns
             if pd.notna(last_obs.get(s)) and wide[s].isna().any()
             and last_obs[s] < idx.max()]
    if stale:
        fb = _bhavcopy_mcap_panel(stale, idx)
        filled_obs = []
        for s in stale:
            if s not in fb.columns:
                continue
            # Only dates strictly after this symbol's own last real reading, and only where
            # Bhavcopy genuinely priced it — so a delisted name is never resurrected.
            cells = wide[s].isna() & (idx > last_obs[s]) & fb[s].notna()
            if cells.any():
                wide.loc[cells, s] = fb.loc[cells, s]
                filled_obs.append(last_obs[s])
        if filled_obs and warnings is not None:
            gap = (idx.max() - min(filled_obs)).days
            fix = ("NSE's market-cap pull (scripts/nse_mcap_ingest.py, nightly EOD) is behind — "
                   "check the eod-refresh log." if _has_nl() else
                   "Build the NSE layer (scripts/nse_mcap_ingest.py --backfill) to restore it.")
            warnings.append(
                f"universe eligibility: {len(filled_obs)} of {len(wide.columns)} names had no "
                f"point-in-time market cap past their last reading (the oldest {gap} days "
                f"back) and were priced from Bhavcopy instead (adr-046). {fix}")
    return wide


def membership_panel(symbols, dates, floor_cr: float = MCAP_FLOOR_CR,
                     warnings: list | None = None) -> pd.DataFrame:
    """Bool date x symbol panel: True where the symbol's point-in-time mcap > floor on that date.

    Forward-filled within each symbol's window (mcap is daily but we tolerate gaps), so a name is
    'in the universe' from when it first clears the floor until it stops trading.

    **Bhavcopy fallback (iter-172, adr-046).** `universe_membership` is derived from the Trendlyne
    `ohlcv` table, which only advances on a manual in-browser harvest. Skipping that harvest was
    documented as safe — "Bhavcopy carries prices to today and adjusted_close_panel splices it on"
    — and that is true of PRICES and false of ELIGIBILITY, which has no such fallback. Measured
    2026-09-07: 1,690 stocks' membership stopped at 2026-07-08 while 257 megacaps reached
    2026-08-28, which dragged the resolved bar to 2026-09-04 and pushed everyone else outside the
    10-row bridge. Every one of 140 held/bought positions across 8 live paper books came from the
    293 survivors; not one from the other 1,897. Nothing warned, because the existing guard asks
    "is the eligible set EMPTY?" and 293 is not empty.

    So where the primary panel has no value, fall back to Bhavcopy (automated nightly, currently
    3,385 tickers) x the same share count the primary path used. Three properties make this safe:

    1. **NaN cells only.** A real Trendlyne-derived value always wins, so any date that already had
       data is untouched — no published backtest moves.
    2. **Only past a symbol's own last real observation.** An interior historical hole is left
       alone (that is to-do #92, which needs its own measurement); only the un-refreshed tail is
       filled.
    3. **Only where Bhavcopy actually priced the symbol that day.** A delisted name has no such
       rows, so it still drops out of the universe rather than looking perpetually eligible — the
       property the original docstring was written to protect.
    """
    syms = [s.upper() for s in symbols]
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    wide = _pit_mcap_wide(syms, idx, warnings)
    if wide is None:
        return pd.DataFrame(False, index=idx, columns=syms)
    out = (wide > floor_cr).reindex(columns=syms).fillna(False)
    if warnings is not None and len(idx) and idx.min() < _bhav_start():
        warnings.append(
            f"NSE gate: NSE Bhavcopy starts {_bhav_start().date()}, so before it a company counts if "
            f"it was already listed when coverage began — listing dates and idle NSE lines before "
            f"then cannot be checked (adr-050).")
    # Point-in-time NSE gate (adr-050 step 4, #957): listed on NSE by that day and trading on it.
    return out & nse_gate_panel(syms, idx).reindex(index=idx, columns=syms).fillna(False)


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

    Sources follow `_membership_long` (adr-050): Trendlyne's pit_mcap before MCAP_CUTOVER plus the
    companies it never listed, NSE's official market cap from it. A candidate must have listed on
    NSE (first EQ bar) by the window's end; the per-day gate is membership_panel's.
    """
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    nl = _has_nl()
    tl_end = min(e, MCAP_CUTOVER - pd.Timedelta(days=1)) if nl else e
    cands: set[str] = set()
    if s <= tl_end:
        alias = _frozen_alias()
        cands |= {alias.get(r[0], r[0]) for r in _con().execute("""
            SELECT DISTINCT symbol FROM universe_membership
            WHERE date >= CAST(? AS DATE) AND date <= CAST(? AS DATE) AND mcap_cr > ?""",
            [str(s.date()), str(tl_end.date()), floor_cr]).fetchall()}
    if nl:
        if e >= MCAP_CUTOVER:
            cands |= {r[0] for r in _con().execute("""
                SELECT DISTINCT t.engine_symbol FROM nl.mcap_daily m
                JOIN nl.ticker_map t ON t.ticker = m.symbol
                WHERE m.date >= CAST(? AS DATE) AND m.date <= CAST(? AS DATE) AND m.mcap_cr > ?""",
                [str(max(s, MCAP_CUTOVER).date()), str(e.date()), floor_cr]).fetchall()}
        if s < MCAP_CUTOVER:
            pre = _survivor_pre_mcap()
            if not pre.empty:
                w = pre[(pre["date"] >= s) & (pre["date"] <= tl_end) & (pre["mcap_cr"] > floor_cr)]
                cands |= set(w["symbol"])
    first = first_nse_bar(cands)
    return sorted(c for c in cands if _listed_by(first.get(c), e))   # listed on NSE (adr-050)


def raw_close_panel(symbols, start=None, end=None, field: str = "close") -> pd.DataFrame:
    """RAW (unadjusted) Bhavcopy closes, wide date x symbol, for NSE mainboard series.

    A last-resort price source for a name the adjusted panel does not carry at all — e.g. a paper
    holding that never made it into the Trendlyne store. Raw prices are only safe over a short
    window: any split or bonus inside it shows up as a step. Callers spanning years must use
    adjusted_close_panel instead (iter-171, item 1229).
    """
    syms = [s.upper() for s in symbols]
    if not syms:
        return pd.DataFrame()
    fcol = {"close": "close", "open": "open", "high": "high", "low": "low"}.get(field, "close")
    cond = (f"WHERE series IN {_MAINBOARD_SQL_IN} AND {fcol}>0 "
            "AND upper(regexp_replace(ticker,'\\.NS$','')) IN ("
            + ",".join(["?"] * len(syms)) + ")")
    params = syms[:]
    if start:
        cond += " AND date >= ?"; params.append(start)
    if end:
        cond += " AND date <= ?"; params.append(end)
    df = _con().execute(
        f"SELECT upper(regexp_replace(ticker,'\\.NS$','')) symbol, date, {fcol} v "
        f"FROM bc.bhavcopy_prices {cond}", params).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="symbol", values="v").sort_index()


def traded_value_panel(symbols, start=None, end=None) -> pd.DataFrame:
    """Daily rupee turnover (raw NSE Bhavcopy `turnover`) for ADTV / liquidity sizing — wide
    date x symbol. Resolves ticker renames via ISIN (adr-025) so a company's pre-rename turnover
    (e.g. NAVA's years as NBVENTURES) is counted under its current symbol — otherwise renamed names
    spuriously fail the liquidity filter in their pre-rename window."""
    a2c = _alias_to_canonical([s.upper() for s in symbols])   # historical ticker -> requested symbol
    tickers = list(a2c.keys())
    cond = ("WHERE series='EQ' AND turnover>0 AND upper(regexp_replace(ticker,'\\.NS$','')) IN ("
            + ",".join(["?"] * len(tickers)) + ")")
    params = tickers[:]
    if start:
        cond += " AND date >= ?"; params.append(start)
    if end:
        cond += " AND date <= ?"; params.append(end)
    df = _con().execute(
        f"SELECT upper(regexp_replace(ticker,'\\.NS$','')) symbol, date, turnover v "
        f"FROM bc.bhavcopy_prices {cond}", params).fetchdf()
    if df.empty:
        return pd.DataFrame()
    df["symbol"] = df["symbol"].map(a2c)   # relabel old tickers to the current symbol
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


def factor_last_dates() -> dict:
    """{family: newest date published} for the Trendlyne factor tables a strategy can rank on —
    `dvm` (dvm_history: tl_durability / tl_valuation / tl_momentum) and `valuation`
    (valuation_ratios: tl_pe / tl_peg / tl_pbv). What the paper rebalance's stale-factor guard
    measures a book against (iter-202, #954)."""
    out = {}
    for fam, table in (("dvm", "dvm_history"), ("valuation", "valuation_ratios")):
        try:
            r = _con().execute(f"SELECT max(date) FROM {table}").fetchone()
            out[fam] = r[0] if r else None
        except duckdb.Error:
            out[fam] = None
    return out


def valuation_panel(metric: str, symbols) -> pd.DataFrame:
    """Trendlyne daily valuation multiple: PE_TTM / PEG_TTM / PBV_A. Published daily -> point-in-time.

    All three go NEGATIVE for distressed names and explode near zero (caveat #7): PE/PEG for
    loss-makers, PBV for negative net worth (accumulated losses wipe out book value). A negative
    multiple is NOT 'cheap', so we mask <= 0 -> NaN for ALL THREE: a `tl_pe < N` / `tl_pbv < N`
    filter then EXCLUDES the distressed name (instead of admitting every negative), and an ascending
    'prefer-low' rank no longer ranks it as the cheapest. The audit (2026-06-24, F1) found PBV_A <= 0
    on ~30 names currently / 158 ever — masking it for consistency with the PE/PEG guard (adr-027)."""
    df = _pk_panel("valuation_ratios", "metric", _VAL[metric], symbols)
    if not df.empty and _VAL[metric] in ("PE_TTM", "PEG_TTM", "PBV_A"):
        df = df.where(df > 0)
    return df


# Raw earnings-derived fundamentals that DO need an announcement-date lag (result_lag, adr-016).
# All have the long (pk, metric, date, value) shape and a quarterly/annual period_end that joins
# result_lag, so raw_fundamental_panel handles every one identically (iter-32 widened the set).
_RAW_FUND = {"tl_roe": ("ratios_annual", "ROE_A"), "tl_roce": ("ratios_annual", "ROCE_A"),
             "tl_de": ("ratios_annual", "DEBT_CE_A"),
             # tl_opm: OPM_A is a broken Trendlyne export column — only 40/1962 names, negative median
             # (audit #94). PBDITMargin_A (PBDIT/EBITDA margin, the standard operating-margin proxy) has
             # 1924/1962 names and a sane +15.9% median, so tl_opm resolves that instead.
             "tl_opm": ("ratios_annual", "PBDITMargin_A"),
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


# Quarterly, result-lag-gated data refreshes every ~90 days plus a ~45-day announcement lag, so a
# value roughly 135 days old is NORMAL and a 14-day rule like _STALE_FACTOR_DAYS would fire on every
# healthy read. 270 days is three missed quarters: no longer a reporting cadence, a reporting gap.
_STALE_FUNDAMENTAL_DAYS = 270


def _ffill_periodic(wide, idx, name, warnings) -> pd.DataFrame:
    """Forward-fill a quarterly/annual panel onto `idx`, disclosing a table-wide reporting gap.

    Same reasoning as `_ffill_daily_tl` in resolve.py (adr-045), different clock. These panels are
    keyed on the real announcement date, so carrying a value forward between results is not just
    acceptable, it is the point — a Q2 number IS the best public knowledge until Q3 is published.
    What is not acceptable is carrying it silently for years because the source table stopped
    being refreshed (to-do #852: `valuation_ratios` did exactly that for 54 days undetected).

    Table-wide, not per-symbol: one company that stopped reporting is a real-world event the
    engine should reflect, not a data bug. Every company stopping at once is a data bug.
    """
    out = wide.reindex(wide.index.union(idx)).ffill().reindex(idx)
    if warnings is None or wide.empty or len(idx) == 0:
        return out
    observed = wide.dropna(how="all")
    if observed.empty:
        return out
    last_obs, last_bar = observed.index.max(), idx.max()
    age = (last_bar - last_obs).days
    if age > _STALE_FUNDAMENTAL_DAYS:
        warnings.append(
            f"stale fundamental: '{name}' has no reading published after {last_obs.date()} while "
            f"prices run to {last_bar.date()} — {age} days, about {age // 90} quarters. Every name "
            f"ranked or filtered on it is using pre-{last_obs.date()} figures.")
    return out


def raw_fundamental_panel(metric: str, symbols, dates, warnings: list | None = None) -> pd.DataFrame:
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
    wide = _ffill_periodic(wide, idx, metric, warnings)
    return wide * _FUND_SCALE.get(metric, 1.0)


def mcap_panel(symbols, dates, warnings: list | None = None) -> pd.DataFrame:
    """Point-in-time market cap (Rs cr), SURVIVORSHIP-FREE: from universe_membership.mcap_cr (the same
    PIT series that feeds the >500cr universe floor, live + delisted). Exposed as a feature so a
    backtest can reproduce Trendlyne 'Market Capitalization' bands (e.g. mcap > 1000, mcap < 50000)
    over history, not just the snapshot value. Forward-filled (<=2 wks) within each name's window."""
    syms = [s.upper() for s in symbols]
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique()))
    wide = _pit_mcap_wide(syms, idx, warnings)
    return pd.DataFrame(index=idx) if wide is None else wide


_SHARE_CAT = {"tl_pledge": "Pledged", "tl_fii": "FII", "tl_dii": "DII"}


def shareholding_panel(metric: str, symbols, dates, warnings: list | None = None) -> pd.DataFrame:
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
    return _ffill_periodic(wide, idx, metric, warnings)


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


@functools.lru_cache(maxsize=1)
def industry_map() -> dict[str, str]:
    """NSE symbol -> industry (Trendlyne `sector_map.industry`, pk-keyed).

    Finer than `sector_map`: 125 industries against 29 sectors, so an industry peer group is a much
    tighter comparison for a valuation multiple. Added iter-172 so `industry_pe` can be computed
    from data we hold rather than read from a snapshot that covers 79% of the universe.
    """
    rows = _con().execute("""
        SELECT m.sym, coalesce(sm.industry, 'Unknown') FROM sector_map sm
        JOIN (SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode<>''
              UNION SELECT pk, upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol<>'') m
          ON sm.pk=m.pk""").fetchall()
    return {s: ind for s, ind in rows}


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
