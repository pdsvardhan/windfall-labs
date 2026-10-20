"""iter-200 (item 1462): the current Rs500cr universe scored against NSE's OFFICIAL market cap, each
disagreement attributed to a cause.

From 2024-02-29 NSE's daily MCAP file gives every listed security's official market cap. At each
month-end (Feb 2024 - Jul 2026, inside Trendlyne's coverage) this compares:
  official  every company in that day's file above Rs500cr (any series it trades in that day)
  current   tl.universe_membership above Rs500cr within the 14-day lookback
Both sides pass the strategies' own NSE-only gate — the company EVER traded in series EQ
(trendlyne_store._nse_symbols, adr-024) — so SME (SM/ST-only) names, which no strategy can hold,
count on neither side.

Symbols are matched by COMPANY, not ticker: universe_membership keys history by today's symbol while
the MCAP file uses the symbol of that day (ETERNAL vs ZOMATO), so tickers sharing an ISIN in Bhavcopy
form one group (the same rule as trendlyne_store._ticker_aliases, adr-025, across all mainboard
series).

Each current-but-not-official name is attributed to exactly one cause:
  not_listed_yet  the company has no NSE bar on or before the date — the "ever traded EQ" gate is not
                  point-in-time, so a name that listed on NSE later passes it (look-ahead)
  official_below  it is in that day's file and NSE puts it at <= Rs500cr — a share-count/price error
  absent          listed on NSE before the date but not in that day's file (suspended, delisted,
                  merged — the file covers listed securities)
Each official-but-not-current name is attributed to:
  no_row          no universe_membership row for the company in the window (not priced/mapped)
  ours_below      a row exists but ours is <= Rs500cr

The free universe from 2024-02 IS the official one, so it is not "scored" here — its open question
is mapping: how many official companies have no engine symbol at all (no_row) is the coverage a
switch must close.

Also checks that no paper position (current record or archives) ever held a non-EQ symbol, reading
the meta DB only through a throwaway COPY.

Read-only.  .venv/bin/python scripts/free_layer/explain_membership.py
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
FLOOR = 500.0
SERIES = ("EQ", "BE", "BZ", "SM", "ST")


def groups(con) -> dict[str, str]:
    """ticker -> company id (the smallest ticker of its ISIN-connected group)."""
    rows = con.execute(r"""
        SELECT DISTINCT isin, upper(regexp_replace(ticker,'\.NS$','')) FROM bc.bhavcopy_prices
        WHERE isin IS NOT NULL AND isin <> ''""").fetchall()
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_isin: dict[str, list[str]] = {}
    for isin, sym in rows:
        by_isin.setdefault(isin, []).append(sym)
    for syms in by_isin.values():
        root = find(syms[0])
        for s in syms[1:]:
            r = find(s)
            if r != root:
                parent[r] = root
    comp: dict[str, list[str]] = {}
    for s in list(parent):
        comp.setdefault(find(s), []).append(s)
    return {s: min(members) for members in comp.values() for s in members}


def main() -> None:
    con = duckdb.connect(str(DATA / "free_layer.duckdb"), read_only=True)
    con.execute(f"ATTACH '{DATA / 'trendlyne.duckdb'}' AS tl (READ_ONLY)")
    con.execute(f"ATTACH '{DATA / 'bhavcopy.duckdb'}' AS bc (READ_ONLY)")
    grp = groups(con)
    g = lambda s: grp.get(s, s)                                   # noqa: E731
    eq_ever = {r[0] for r in con.execute(
        r"SELECT DISTINCT upper(regexp_replace(ticker,'\.NS$','')) FROM bc.bhavcopy_prices "
        "WHERE series = 'EQ'").fetchall()}
    eq_grp = {g(s) for s in eq_ever}
    first_bar: dict[str, pd.Timestamp] = {}
    for sym, d in con.execute(r"""
            SELECT upper(regexp_replace(ticker,'\.NS$','')), min(date) FROM bc.bhavcopy_prices
            WHERE series IN ('EQ','BE','BZ') GROUP BY 1""").fetchall():
        k = g(sym)
        first_bar[k] = min(first_bar.get(k, pd.Timestamp(d)), pd.Timestamp(d))

    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM nse_mcap WHERE date <= DATE '2026-08-28' ORDER BY 1").fetchall()]
    rows, sample = [], {}
    for d in dates:
        f = con.execute(f"""SELECT symbol, max(mcap_rs) / 1e7 m FROM nse_mcap
                            WHERE date = ? AND series IN {SERIES} GROUP BY symbol""", [d]).fetchdf()
        in_file = {g(s): m for s, m in zip(f["symbol"], f["m"])}
        official = {k for k, m in in_file.items() if m > FLOOR and k in eq_grp}
        cur = con.execute("""SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                             WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
                             GROUP BY symbol""", [d, d]).fetchdf()
        cur_m = {g(s): m for s, m in zip(cur["symbol"], cur["m"]) if g(s) in eq_grp}
        current = {k for k, m in cur_m.items() if m > FLOOR}

        extra = current - official
        cause = {"not_listed_yet": set(), "official_below": set(), "absent": set()}
        for k in extra:
            fb = first_bar.get(k)
            if fb is None or fb > pd.Timestamp(d):
                cause["not_listed_yet"].add(k)
            elif k in in_file:
                cause["official_below"].add(k)
            else:
                cause["absent"].add(k)
        missed = official - current
        miss = {"no_row": {k for k in missed if k not in cur_m},
                "ours_below": {k for k in missed if k in cur_m}}
        rows.append({"date": d, "official": len(official), "current": len(current),
                     **{f"in_{c}": len(v) for c, v in cause.items()},
                     **{f"miss_{c}": len(v) for c, v in miss.items()}})
        if str(d) in ("2024-02-29", "2026-07-31"):
            sample[str(d)] = {c: sorted(v)[:8] for c, v in {**cause, **miss}.items()}
    m = pd.DataFrame(rows)
    print("month-end | official | current | current-not-official: not-listed-yet / official<=500 / absent"
          " | official-not-current: no row / ours<=500")
    for r in m.itertuples():
        print(f"  {r.date} | {r.official} | {r.current} | {r.in_not_listed_yet} / {r.in_official_below}"
              f" / {r.in_absent} | {r.miss_no_row} / {r.miss_ours_below}")
    t = m.sum(numeric_only=True)
    n = len(m)
    print(f"\nper month-end averages over {n}: official {t.official / n:.0f}; current admits "
          f"{t.in_not_listed_yet / n:.0f} not-yet-NSE-listed, {t.in_official_below / n:.1f} officially "
          f"<=Rs500cr, {t.in_absent / n:.1f} absent; misses {t.miss_no_row / n:.1f} with no row, "
          f"{t.miss_ours_below / n:.1f} with ours <=Rs500cr")
    print(f"share-count/price errors (official<=500 + ours<=500) as a share of official: "
          f"{(t.in_official_below + t.miss_ours_below) / t.official:.2%}")
    for d, s in sample.items():
        print(f"\nexamples at {d}:")
        for c, names in s.items():
            print(f"  {c}: {names}")

    tmp = Path(tempfile.mkdtemp(prefix="v200meta_"))
    try:
        for fn in ("windfall.duckdb", "windfall.duckdb.wal"):
            if (DATA / fn).exists():
                shutil.copy2(DATA / fn, tmp / fn)
        mc = duckdb.connect(str(tmp / "windfall.duckdb"), read_only=True)
        tabs = [r[0] for r in mc.execute("SELECT table_name FROM duckdb_tables() "
                                         "WHERE table_name LIKE 'paper_positions%'").fetchall()]
        held = set()
        for tname in tabs:
            held |= {r[0].upper() for r in mc.execute(f"SELECT DISTINCT ticker FROM {tname}").fetchall()}
        mc.close()
        print(f"\npaper tickers ever held across {tabs}: {len(held)}; never EQ-series: {sorted(held - eq_ever)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    con.close()


if __name__ == "__main__":
    main()
