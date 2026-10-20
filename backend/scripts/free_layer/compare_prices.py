"""iter-200 (free layer, item 1461): in-house split-adjusted prices vs Trendlyne's, name by name.

The in-house series is raw NSE Bhavcopy divided, before every split/bonus ex-date, by that event's
ratio (adr-049's convention: splits/bonuses adjusted, demergers not). Trendlyne's adjusted `ohlcv`
is the reference: for each live name, the factor f(t) = tl_close / raw_close it applied on day t
is compared with the factor g(t) the in-house layer would apply on the same day, using only the
events up to that name's last Trendlyne bar (the date Trendlyne's series is anchored at).

Three event sources are measured, so the report says what each one buys:
  nse      NSE's corporate-actions list (data/free_layer.duckdb nse_ca), combined subjects
           ("Bonus 1:1 / Face Value Split From Rs 10 To Re 1") parsed as the PRODUCT of their parts
  app      the app's own share-step-confirmed events (trendlyne.duckdb ca_events)
  nse+app  NSE's list, plus app events NSE does not list within +/-3 days

Read-only on trendlyne/bhavcopy; writes tables into data/free_layer.duckdb only.

    .venv/bin/python scripts/free_layer/compare_prices.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parse import parse_all  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
FREE, TL, BC = DATA / "free_layer.duckdb", DATA / "trendlyne.duckdb", DATA / "bhavcopy.duckdb"
TOL = 0.01          # a day agrees when the two factors are within 1%
CLEAN = 0.99        # a name is clean when >= 99% of its days agree

_RIGHTS = re.compile(r"Rights\s+(\d+)\s*:\s*(\d+)\s*@\s*Premium\s+(?:Rs|Re)\.?\s*([\d.]+)", re.I)


def rights_events(con) -> pd.DataFrame:
    """Rights issues as a price ratio by the standard theoretical ex-rights price (TERP).

    "Rights a:b @ Premium Rs X" = a new shares for every b held, at S = face value + X. With P the
    last close before the ex-date, TERP = (b*P + a*S) / (a+b) and the adjustment ratio is P / TERP
    (> 1 when the issue is priced below the market). Rights priced at or above the market do not
    dilute and are skipped.
    """
    r = con.execute(r"""
        SELECT n.symbol, n.ex_date, n.subject, n.face_value,
               (SELECT b.close FROM bc.bhavcopy_prices b
                 WHERE upper(regexp_replace(b.ticker, '\.NS$', '')) = n.symbol
                   AND b.date < n.ex_date AND b.close > 0 AND b.series IN ('EQ', 'BE')
                 ORDER BY b.date DESC LIMIT 1) AS cum_close
        FROM nse_ca n WHERE n.kind = 'rights'""").fetchdf()
    rows = []
    for x in r.itertuples():
        m = _RIGHTS.search(x.subject or "")
        if not m or not x.face_value or not x.cum_close:
            continue
        a, b, prem = int(m.group(1)), int(m.group(2)), float(m.group(3))
        s, p = x.face_value + prem, float(x.cum_close)
        if b <= 0 or s >= p:
            continue
        terp = (b * p + a * s) / (a + b)
        rows.append({"symbol": x.symbol, "ex_date": x.ex_date, "ratio": p / terp})
    out = pd.DataFrame(rows, columns=["symbol", "ex_date", "ratio"]).drop_duplicates(["symbol", "ex_date"])
    print(f"rights issues priced below market (adjusting): {len(out)} of {len(r)}")
    return out


def events(con) -> dict[str, pd.DataFrame]:
    raw = con.execute("SELECT DISTINCT symbol, ex_date, subject FROM nse_ca WHERE kind <> 'rights'").fetchdf()
    raw["ratio"] = raw["subject"].map(parse_all)
    nse = (raw.dropna(subset=["ratio"]).drop_duplicates(["symbol", "ex_date", "ratio"])
              .groupby(["symbol", "ex_date"], as_index=False)["ratio"].prod())
    app = con.execute("SELECT ticker AS symbol, ex_date, ca_ratio AS ratio FROM tl.ca_events").fetchdf()
    m = app.merge(nse[["symbol", "ex_date"]], on="symbol", how="left", suffixes=("", "_n"))
    near = m[(pd.to_datetime(m["ex_date_n"]) - pd.to_datetime(m["ex_date"])).abs() <= pd.Timedelta(days=3)]
    app_only = app.merge(near[["symbol", "ex_date"]].drop_duplicates(), how="left", indicator=True)
    app_only = app_only[app_only["_merge"] == "left_only"].drop(columns="_merge")
    both = pd.concat([nse, app_only], ignore_index=True)
    rights = rights_events(con)
    nse_r = (pd.concat([nse, rights], ignore_index=True)
               .groupby(["symbol", "ex_date"], as_index=False)["ratio"].prod())
    for df in (nse, app, both, nse_r):
        df["ex_date"] = pd.to_datetime(df["ex_date"])
    print(f"events: nse {len(nse)}, app {len(app)}, app-only added to nse {len(app_only)}, "
          f"nse+rights {len(nse_r)}")
    return {"nse": nse, "app": app, "nse+app": both, "nse+rights": nse_r}


def factors(con) -> pd.DataFrame:
    """Per live name per day: Trendlyne's applied factor tl_close / raw_close, and its last bar."""
    return con.execute(r"""
        WITH sym AS (SELECT upper(nsecode) s, pk FROM tl.stocks WHERE nsecode <> ''),
             last AS (SELECT pk, max(date) last_tl FROM tl.ohlcv GROUP BY pk)
        SELECT sym.s AS symbol, y.date, y.close / b.close AS f, last.last_tl
        FROM tl.ohlcv y JOIN sym USING (pk) JOIN last USING (pk)
        JOIN bc.bhavcopy_prices b
          ON upper(regexp_replace(b.ticker, '\.NS$', '')) = sym.s AND b.date = y.date
        WHERE b.series IN ('EQ', 'BE') AND b.close > 0 AND y.close > 0
          AND y.date >= DATE '2010-01-04'""").fetchdf()


def compare(fac: pd.DataFrame, ev: pd.DataFrame, label: str) -> pd.DataFrame:
    fac = fac.sort_values(["symbol", "date"])
    evg = {s: g.sort_values("ex_date") for s, g in ev.groupby("symbol")}
    rows = []
    for sym, g in fac.groupby("symbol", sort=False):
        lt = pd.Timestamp(g["last_tl"].iloc[0])
        e = evg.get(sym)
        d = pd.to_datetime(g["date"]).to_numpy()
        gfac = np.ones(len(g))
        if e is not None:
            for ex, r in zip(e["ex_date"], e["ratio"]):
                if ex <= lt:
                    gfac[d < np.datetime64(ex)] /= r
        ok = np.abs(g["f"].to_numpy() / gfac - 1) < TOL
        bad_idx = np.where(~ok)[0]
        rows.append({"symbol": sym, "days": len(g), "agree": float(ok.mean()),
                     "first_bad": pd.Timestamp(d[bad_idx[0]]).date() if len(bad_idx) else None,
                     "last_bad": pd.Timestamp(d[bad_idx[-1]]).date() if len(bad_idx) else None,
                     "worst": float(np.max(np.abs(g["f"].to_numpy() / gfac - 1))) if len(g) else 0.0})
    out = pd.DataFrame(rows)
    clean = (out["agree"] >= CLEAN).mean()
    day_agree = (out["agree"] * out["days"]).sum() / out["days"].sum()
    print(f"\n[{label}] names {len(out)}: clean (>=99% of days agree) {clean:.1%}; "
          f"all name-days agreeing {day_agree:.2%}")
    return out


def main() -> None:
    con = duckdb.connect(str(FREE))
    con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
    con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
    ev = events(con)
    fac = factors(con)
    print(f"Trendlyne-vs-raw factor rows: {len(fac):,} across {fac['symbol'].nunique():,} live names")
    results = {}
    for label, e in ev.items():
        results[label] = compare(fac, e, label)
    best = results["nse+rights"].sort_values("agree")
    con.register("best", best)
    con.execute("CREATE OR REPLACE TABLE price_compare AS SELECT * FROM best")
    print("\nworst 25 names under nse+rights (agree share, first/last disagreeing day, worst gap):")
    for r in best.head(25).itertuples():
        print(f"  {r.symbol:12s} {r.agree:6.1%} of {r.days} days  {r.first_bad} .. {r.last_bad}  "
              f"max gap {r.worst:.1%}")
    # Since 2016 (the backtest windows): how many names are clean over just that span?
    f16 = fac[pd.to_datetime(fac["date"]) >= "2016-01-01"]
    for label in ("nse", "nse+rights"):
        compare(f16, ev[label], f"{label}, 2016 onward")
    con.close()


if __name__ == "__main__":
    main()
