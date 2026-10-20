"""iter-200 (item 1462): the current Rs500cr universe scored against NSE's OFFICIAL market cap, each
disagreement attributed to a cause.

From 2024-02-01 NSE's daily MCAP file gives every listed security's official market cap. At each
month-end (Feb 2024 - Jul 2026, inside Trendlyne's coverage) this compares:
  official  every company trading in a MAINBOARD series that day (EQ, BE, BZ — read point-in-time
            from that day's file, so an SME name that later moved to EQ is not counted early)
            with official market cap above Rs500cr
  current   tl.universe_membership above Rs500cr within the 14-day lookback, behind the strategies'
            own NSE-only gate — the company EVER traded in series EQ (trendlyne_store._nse_symbols,
            adr-024)

Symbols are matched by COMPANY, not ticker: universe_membership keys history by today's symbol while
the MCAP file uses the symbol of that day (ETERNAL vs ZOMATO), so tickers sharing an ISIN in Bhavcopy
form one group (the rule of trendlyne_store._ticker_aliases, adr-025, across all series). Known limit:
a few ISIN families join unrelated tickers (ETF families, one IBULISL group) and an ISIN change at a
rename is not linked — negligible to the totals.

Current-but-not-official, one cause each:
  not_listed_yet  no NSE bar for the company on or before the date — the "ever traded EQ" gate is
                  not point-in-time (look-ahead)
  official_below  in that day's file at <= Rs500cr — a share-count/price error
  absent          listed on NSE before the date but not in that day's file; split into
                    dormant      no NSE trade in the prior 90 days (BSE companies whose NSE line is
                                 idle — the gate should also require recent NSE trading)
                    gone         never in any later file (delisted / merged)
                    missing      traded recently, returns later (suspension, file gap)
Official-but-not-current, one cause each:
  never_mapped    the company has no universe_membership row at ANY date — not in Trendlyne's stock
                  list at all (survivorship evidence: see the shrink check printed at the end)
  stale_window    rows exist within 60 days before the date but none in the 14-day window (a
                  harvest-end artifact; the engine bridges it with the Bhavcopy fallback, adr-046)
  interior_gap    rows exist for the company, but none within 60 days
  ours_below      a row exists in the window but ours is <= Rs500cr

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
MAINBOARD = ("EQ", "BE", "BZ")


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
    eq_grp = {g(r[0]) for r in con.execute(
        r"SELECT DISTINCT upper(regexp_replace(ticker,'\.NS$','')) FROM bc.bhavcopy_prices "
        "WHERE series = 'EQ'").fetchall()}
    trades: dict[str, list] = {}
    for sym, d in con.execute(r"""
            SELECT DISTINCT upper(regexp_replace(ticker,'\.NS$','')), date FROM bc.bhavcopy_prices
            WHERE series IN ('EQ','BE','BZ') AND date >= DATE '2023-09-01'""").fetchall():
        trades.setdefault(g(sym), []).append(pd.Timestamp(d))
    first_bar: dict[str, pd.Timestamp] = {}
    for sym, d in con.execute(r"""
            SELECT upper(regexp_replace(ticker,'\.NS$','')), min(date) FROM bc.bhavcopy_prices
            WHERE series IN ('EQ','BE','BZ') GROUP BY 1""").fetchall():
        k = g(sym)
        first_bar[k] = min(first_bar.get(k, pd.Timestamp(d)), pd.Timestamp(d))
    um_dates: dict[str, list] = {}
    for sym, d in con.execute("SELECT DISTINCT symbol, date FROM tl.universe_membership").fetchall():
        um_dates.setdefault(g(sym), []).append(pd.Timestamp(d))

    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM nse_mcap WHERE date <= DATE '2026-08-28' ORDER BY 1").fetchall()]
    file_members = {d: set() for d in dates}
    files = {}
    for d in dates:
        f = con.execute(f"""SELECT symbol, max(mcap_rs) / 1e7 m FROM nse_mcap
                            WHERE date = ? AND series IN {MAINBOARD} GROUP BY symbol""", [d]).fetchdf()
        files[d] = {g(s): m for s, m in zip(f["symbol"], f["m"])}
        file_members[d] = set(files[d])
    latest_file = con.execute("""SELECT symbol, max(mcap_rs) / 1e7 m FROM nse_mcap
                                 WHERE date = (SELECT max(date) FROM nse_mcap) GROUP BY symbol""").fetchdf()
    latest_m = {g(s): m for s, m in zip(latest_file["symbol"], latest_file["m"])}

    rows, sample, never_mapped_ever = [], {}, set()
    for i, d in enumerate(dates):
        ts = pd.Timestamp(d)
        in_file = files[d]
        official = {k for k, m in in_file.items() if m > FLOOR}
        cur = con.execute("""SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                             WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
                             GROUP BY symbol""", [d, d]).fetchdf()
        cur_m = {g(s): m for s, m in zip(cur["symbol"], cur["m"]) if g(s) in eq_grp}
        current = {k for k, m in cur_m.items() if m > FLOOR}
        later = set().union(*(file_members[x] for x in dates[i + 1:])) if i + 1 < len(dates) else set()

        c = {k: set() for k in ("not_listed_yet", "official_below", "dormant", "gone", "missing")}
        for k in current - official:
            fb = first_bar.get(k)
            if fb is None or fb > ts:
                c["not_listed_yet"].add(k)
            elif k in in_file:
                c["official_below"].add(k)
            elif not any(ts - pd.Timedelta(days=90) <= t <= ts for t in trades.get(k, [])):
                c["dormant"].add(k)
            elif k not in later and i + 1 < len(dates):
                c["gone"].add(k)
            else:
                c["missing"].add(k)
        o = {k: set() for k in ("never_mapped", "stale_window", "interior_gap", "ours_below")}
        for k in official - current:
            if k in cur_m:
                o["ours_below"].add(k)
            elif k not in um_dates:
                o["never_mapped"].add(k)
                never_mapped_ever.add(k)
            elif any(ts - pd.Timedelta(days=60) <= t <= ts for t in um_dates[k]):
                o["stale_window"].add(k)
            else:
                o["interior_gap"].add(k)
        rows.append({"date": d, "official": len(official), "current": len(current),
                     **{x: len(v) for x, v in c.items()}, **{x: len(v) for x, v in o.items()}})
        if str(d) in ("2024-02-29", "2026-07-31"):
            sample[str(d)] = {x: sorted(v)[:8] for x, v in {**c, **o}.items()}

    m = pd.DataFrame(rows)
    cols = ["not_listed_yet", "official_below", "dormant", "gone", "missing",
            "never_mapped", "stale_window", "interior_gap", "ours_below"]
    print("month-end | official | current | admitted: not-listed-yet / official<=500 / dormant / gone /"
          " missing | missed: never-mapped / stale-window / interior-gap / ours<=500")
    for r in m.itertuples():
        print(f"  {r.date} | {r.official} | {r.current} | {r.not_listed_yet} / {r.official_below} / "
              f"{r.dormant} / {r.gone} / {r.missing} | {r.never_mapped} / {r.stale_window} / "
              f"{r.interior_gap} / {r.ours_below}")
    n = len(m)
    print(f"\nper month-end averages over {n}: official {m['official'].mean():.0f}")
    for c_ in cols:
        print(f"  {c_:15s} {m[c_].mean():6.1f}")
    print(f"share-count/price errors (official<=500 + ours<=500) as a share of official: "
          f"{(m['official_below'].sum() + m['ours_below'].sum()) / m['official'].sum():.2%}")

    shrunk = [k for k in never_mapped_ever if k in latest_m and latest_m[k] <= FLOOR]
    still = [k for k in never_mapped_ever if k in latest_m]
    med = pd.Series([latest_m[k] for k in still]).median() if still else float("nan")
    print(f"\nshrink check — companies officially >Rs500cr at some month-end but never in "
          f"universe_membership: {len(never_mapped_ever)}; still in NSE's latest file: {len(still)}; "
          f"of those now <=Rs500cr: {len(shrunk)} (median latest mcap Rs{med:,.0f}cr)")
    for d, s in sample.items():
        print(f"\nexamples at {d}:")
        for c_, names in s.items():
            print(f"  {c_}: {names}")

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
        print(f"\npaper tickers ever held across {tabs}: {len(held)}; "
              f"never EQ-series: {sorted(s for s in held if g(s) not in eq_grp)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    con.close()


if __name__ == "__main__":
    main()
