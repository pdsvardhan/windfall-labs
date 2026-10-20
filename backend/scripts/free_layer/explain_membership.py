"""iter-200 (item 1462, part 3): fair scoring + explanations.

1. Re-score current vs free membership against NSE's official >Rs500cr set WITH the strategies'
   own NSE-only gate (symbol ever traded in series EQ — trendlyne_store._nse_symbols, adr-024)
   applied to all three sets. REITs (RR) and InvITs (IV) never reach a strategy, so counting them
   as "wrongly in" overstated the current method's error.
2. Categorise the free method's misses at 2026-04-30 and 2026-07-31.
3. Test the pre-2024 rule: hold the 2024-02-29 NSE issue size constant (scaled through NSE
   split/bonus ratios) and score it at each later month-end — how fast does a frozen share count
   go wrong?
4. Did any paper position (current record or either archive) ever hold a non-EQ symbol?

Read-only: trendlyne/bhavcopy read-only, free_layer.duckdb read-only, the meta DB only through a
throwaway COPY (the live windfall.duckdb is never opened).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
FLOOR = 500.0


def main() -> None:
    con = duckdb.connect(str(DATA / "free_layer.duckdb"), read_only=True)
    con.execute(f"ATTACH '{DATA / 'trendlyne.duckdb'}' AS tl (READ_ONLY)")
    con.execute(f"ATTACH '{DATA / 'bhavcopy.duckdb'}' AS bc (READ_ONLY)")
    eq = set(r[0] for r in con.execute(
        r"SELECT DISTINCT upper(regexp_replace(ticker,'\.NS$','')) FROM bc.bhavcopy_prices "
        "WHERE series = 'EQ'").fetchall())
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM nse_mcap WHERE date <= DATE '2026-08-28' ORDER BY 1").fetchall()]
    first = dates[0]
    base = con.execute("""SELECT symbol, max(issue_size) i0 FROM nse_mcap
                          WHERE date = ? AND series IN ('EQ','BE') GROUP BY symbol""", [first]).fetchdf()
    base = dict(zip(base["symbol"], base["i0"]))
    ca = con.execute("SELECT symbol, ex_date, ratio FROM ca_events_nse WHERE ratio IS NOT NULL").fetchdf()
    ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.date

    rows, misses = [], {}
    for d in dates:
        truth_df = con.execute("""SELECT symbol, max(mcap_rs) / 1e7 m FROM nse_mcap
                                  WHERE date = ? AND series IN ('EQ','BE') GROUP BY symbol""", [d]).fetchdf()
        truth_all = set(truth_df.loc[truth_df["m"] > FLOOR, "symbol"])
        cur = con.execute("""SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                             WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
                             GROUP BY symbol""", [d, d]).fetchdf()
        px = con.execute("""
            WITH sym AS (SELECT upper(nsecode) s, pk FROM tl.stocks WHERE nsecode <> '')
            SELECT sym.s AS symbol, arg_max(y.close, y.date) c FROM tl.ohlcv y JOIN sym USING (pk)
            WHERE y.date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE) GROUP BY sym.s""",
                         [d, d]).fetchdf()
        px = dict(zip(px["symbol"], px["c"]))
        sh = con.execute("""SELECT symbol, max(issue_size) i FROM nse_mcap
                            WHERE date = ? AND series IN ('EQ','BE') GROUP BY symbol""", [d]).fetchdf()
        sh = dict(zip(sh["symbol"], sh["i"]))
        free = {s for s, c in px.items() if s in sh and c * sh[s] / 1e7 > FLOOR}
        # frozen 2024-02 share count, scaled through splits/bonuses up to d
        k = ca[(ca["ex_date"] > first) & (ca["ex_date"] <= d)].groupby("symbol")["ratio"].prod().to_dict()
        frozen = {s for s, c in px.items() if s in base and c * base[s] * k.get(s, 1.0) / 1e7 > FLOOR}
        seen = (set(cur["symbol"]) | set(px)) & eq
        truth = truth_all & seen
        cur_set = set(cur.loc[cur["m"] > FLOOR, "symbol"]) & eq

        def err(s):
            s = s & seen
            return len(s - truth), len(truth - s)

        r = {"date": d, "truth": len(truth)}
        for name, s in (("current", cur_set), ("free", free), ("frozen24", frozen)):
            wi, mi = err(s)
            r[f"{name}_in"], r[f"{name}_miss"] = wi, mi
        rows.append(r)
        if str(d) in ("2026-04-30", "2026-07-31"):
            miss = truth - free
            cats = {"no Trendlyne price in window": [s for s in miss if s not in px],
                    "no NSE issue size": [s for s in miss if s in px and s not in sh],
                    "priced, but our mcap <= 500": [s for s in miss if s in px and s in sh]}
            misses[str(d)] = (cats, truth_df.set_index("symbol")["m"], px, sh)
    m = pd.DataFrame(rows)
    print("month-end | official (EQ-gated, seen) | current wrongly-in / missed | free (that month's NSE "
          "shares) | frozen 2024-02 shares")
    for r in m.itertuples():
        print(f"  {r.date} | {r.truth} | {r.current_in} / {r.current_miss} | {r.free_in} / {r.free_miss}"
              f" | {r.frozen24_in} / {r.frozen24_miss}")
    t = m.sum(numeric_only=True)
    for name in ("current", "free", "frozen24"):
        e = t[f"{name}_in"] + t[f"{name}_miss"]
        print(f"{name:9s}: {int(e)} errors over {len(m)} month-ends = {e / t['truth']:.2%} of official")

    for d, (cats, tm, px, sh) in misses.items():
        print(f"\nfree-method misses at {d}:")
        for c, names in cats.items():
            print(f"  {c}: {len(names)}  e.g. {sorted(names)[:10]}")
        pr = cats["priced, but our mcap <= 500"]
        for s in sorted(pr)[:8]:
            print(f"     {s}: official Rs{tm.get(s, float('nan')):,.0f}cr, ours "
                  f"Rs{px[s] * sh[s] / 1e7:,.0f}cr (TL close {px[s]:.2f}, NSE shares {sh[s]:,.0f})")

    # 4. paper holdings ever in a non-EQ symbol — via a throwaway copy of the meta DB
    tmp = Path(tempfile.mkdtemp(prefix="v200meta_"))
    try:
        for f in ("windfall.duckdb", "windfall.duckdb.wal"):
            if (DATA / f).exists():
                shutil.copy2(DATA / f, tmp / f)
        mc = duckdb.connect(str(tmp / "windfall.duckdb"), read_only=True)
        tabs = [r[0] for r in mc.execute("SELECT table_name FROM duckdb_tables() WHERE table_name "
                                         "LIKE 'paper_positions%'").fetchall()]
        held = set()
        for tname in tabs:
            held |= {r[0].upper() for r in mc.execute(f"SELECT DISTINCT ticker FROM {tname}").fetchall()}
        mc.close()
        non_eq = sorted(held - eq)
        print(f"\npaper tickers ever held across {tabs}: {len(held)}; not EQ-series: {non_eq}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    con.close()


if __name__ == "__main__":
    main()
