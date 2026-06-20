"""iter-28: derive a corporate-action (split/bonus) adjustment master for NSE equities.

Why this exists: live Trendlyne names carry a correct split/bonus-adjusted `ohlcv`, but DELISTED
names exist only as raw NSE Bhavcopy prices. A backtest that holds a dead name through a split
would see a phantom overnight crash (a false stop-out -> optimistic survivorship bias). We need a
split/bonus-adjusted price series for dead names too — with no external corporate-action feed
(none is reliably available for delisted names, and NSE Bhavcopy `prev_close` is NOT CA-adjusted,
verified on IRCTC's 1:5 split).

Method (validated): a corporate action is the rare event that gaps the *price* AND steps the
*share count* by the same canonical factor. A crash gaps price only; an issuance/buyback steps
shares only; a dividend does neither. So:
  1. candidate = overnight raw-price gap (pc/close) snapping to a canonical split/bonus ratio;
  2. confirm  = a share-count step of the same factor within +/-1 year, from ANY of three proxies
     (Trendlyne NP_TTM/EPS_TTM, Trendlyne book-value shares, or screener NP_owner/EPS for dead names).
Validated vs Trendlyne's own adjusted/raw ground truth on live names: precision ~0.90.
Unconfirmed-but-large gaps on dead names are flagged `ca_uncertain` (caller may exclude them
rather than risk a mis-adjustment) — honest over optimistic.

Writes to trendlyne.duckdb (standalone store, no persistent writer):
  ca_events  (ticker, ex_date, ca_ratio, gap_raw, confirmed_by, same_day_ret)
  ca_factor  (ticker, from_date, cum_mult, adj_factor)      -- adj_factor=1 latest, <1 in the past
  delistings (symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain)
"""
from __future__ import annotations

import sys

import duckdb
import numpy as np
import pandas as pd

TL = sys.argv[1] if len(sys.argv) > 1 else "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = sys.argv[2] if len(sys.argv) > 2 else "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
SC = sys.argv[3] if len(sys.argv) > 3 else "/mnt/storage/websites/windfall-labs/backend/data/screener_fundamentals.duckdb"

# Canonical split/bonus factors (raw price drops by this on the ex-date). Excludes <1.25 to keep
# ordinary volatility out; reciprocals (reverse splits) handled by snapping 1/g.
CANON = np.array([1.25, 1.33, 1.5, 1.67, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 10.0, 11.0])
GAP_TOL = 0.12     # the overnight gap carries the ex-date's own return -> looser snap tolerance
STEP_TOL = 0.10    # share-step factor snap tolerance
CONF_DAYS = 380    # annual fundamentals lag the daily ex-date by up to ~1 year
CONF_TOL = 0.08    # |share-step factor / price-gap factor - 1| to call it a confirmation
UNCERTAIN_GAP = 0.35  # an unconfirmed overnight move this large on a dead name -> flag ca_uncertain


def snap(g: float, tol: float) -> float | None:
    if g is None or g <= 0:
        return None
    g = g if g >= 1 else 1.0 / g
    i = int(np.argmin(np.abs(CANON / g - 1)))
    return float(CANON[i]) if abs(CANON[i] / g - 1) < tol else None


def main() -> None:
    con = duckdb.connect(TL)
    con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
    con.execute(f"ATTACH '{SC}' AS sc (READ_ONLY)")
    smap = {r[0]: r[1] for r in con.execute(
        "SELECT pk, upper(nsecode) FROM stocks WHERE nsecode<>''").fetchall()}

    # ── candidate overnight price gaps (all EQ names) ────────────────────────────────────────
    gaps = con.execute(r"""
        WITH px AS (
          SELECT upper(regexp_replace(ticker,'\.NS$','')) sym, date, open, close,
                 lag(close) OVER w pc
          FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0
          WINDOW w AS (PARTITION BY upper(regexp_replace(ticker,'\.NS$','')) ORDER BY date))
        SELECT sym, date AS ex_date, pc/close AS gap_raw, close/pc - 1.0 AS same_day_ret
        FROM px WHERE pc IS NOT NULL AND (pc/close > 1.18 OR pc/close < 0.84)
    """).fetchdf()
    gaps["ca_ratio"] = gaps["gap_raw"].apply(lambda g: snap(g, GAP_TOL))
    cand = gaps.dropna(subset=["ca_ratio"]).copy()
    cand["ex_date"] = pd.to_datetime(cand["ex_date"])
    print(f"candidate canonical price gaps: {len(cand):,} across {cand['sym'].nunique():,} names")

    # ── share-count step proxies ─────────────────────────────────────────────────────────────
    def step_table(df: pd.DataFrame, sym_col_from_pk: bool) -> pd.DataFrame:
        df = df.dropna(subset=["sh"]).copy()
        df["sym"] = df["pk"].map(smap) if sym_col_from_pk else df["sym"]
        df = df.dropna(subset=["sym"]).sort_values(["sym", "date"])
        df["prev"] = df.groupby("sym")["sh"].shift(1)
        df = df.dropna(subset=["prev"])
        df["f"] = df["sh"] / df["prev"]
        df = df[(df.f > 1.4) | (df.f < 0.72)].copy()
        df["sf"] = df["f"].apply(lambda g: snap(g, STEP_TOL))
        df = df.dropna(subset=["sf"])
        df["date"] = pd.to_datetime(df["date"])
        return df[["sym", "date", "sf"]]

    npeps = con.execute("""
        WITH q AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='NP_TTM'),
             e AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='EPS_TTM' AND value>0)
        SELECT q.pk, q.date, q.v/e.v sh FROM q JOIN e USING(pk,date)""").fetchdf()
    bvps = con.execute("""
        WITH f AS (SELECT pk,date,value v FROM balance_sheet WHERE metric='TotalShareHoldersFunds_A' AND value>0),
             b AS (SELECT pk,date,value v FROM ratios_annual WHERE metric='BVSH_A' AND value>0)
        SELECT f.pk, f.date, f.v/b.v sh FROM f JOIN b USING(pk,date)""").fetchdf()
    dead = con.execute("""
        SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, period_end AS date,
               coalesce(net_profit_owner,net_profit)/eps AS sh
        FROM sc.fundamentals_history WHERE eps>0 AND coalesce(net_profit_owner,net_profit)>0""").fetchdf()

    proxies = [step_table(npeps, True), step_table(bvps, True), step_table(dead, False)]
    steps = pd.concat(proxies, ignore_index=True)
    by_sym = {s: g.reset_index(drop=True) for s, g in steps.groupby("sym")}
    print(f"share-step events (3 proxies): {len(steps):,} across {steps['sym'].nunique():,} names")

    def confirm_step(row):
        """Return the matched share-step DATE (the period where the share count stepped by this CA
        factor), or NaT. We keep it so the pit_mcap rebuild can reconcile the two timelines: the
        price splits on `ex_date` but Trendlyne's EPS reflects the split on this share-step date."""
        g = by_sym.get(row.sym)
        if g is None:
            return pd.NaT
        near = g[(g["date"] - row.ex_date).abs() <= pd.Timedelta(days=CONF_DAYS)]
        if near.empty:
            return pd.NaT
        ok = near[np.abs(near["sf"].to_numpy() / row.ca_ratio - 1) < CONF_TOL]
        if ok.empty:
            return pd.NaT
        # the share-step closest in time to the price ex-date
        return ok.iloc[(ok["date"] - row.ex_date).abs().to_numpy().argmin()]["date"]

    cand["share_step_date"] = cand.apply(confirm_step, axis=1)
    cand["confirmed"] = cand["share_step_date"].notna()
    ev = cand[cand["confirmed"]].copy()
    ev["confirmed_by"] = "share-step"
    # de-dupe: keep one event per (sym, ex_date)
    ev = ev.sort_values(["sym", "ex_date"]).drop_duplicates(["sym", "ex_date"])
    print(f"CONFIRMED CA events: {len(ev):,} across {ev['sym'].nunique():,} names")

    con.execute("DROP TABLE IF EXISTS ca_events")
    out = ev[["sym", "ex_date", "ca_ratio", "gap_raw", "confirmed_by", "same_day_ret",
              "share_step_date"]].rename(columns={"sym": "ticker"})
    out["ex_date"] = pd.to_datetime(out["ex_date"]).dt.date
    out["share_step_date"] = pd.to_datetime(out["share_step_date"]).dt.date
    con.register("ev_df", out)
    con.execute("CREATE TABLE ca_events AS SELECT ticker, ex_date::DATE ex_date, ca_ratio, gap_raw, "
                "confirmed_by, same_day_ret, share_step_date::DATE share_step_date FROM ev_df")
    con.execute("CREATE INDEX idx_caev ON ca_events(ticker, ex_date)")

    # ── segmented cumulative multiple + back-adjust factor ───────────────────────────────────
    first_dates = {t: pd.Timestamp(d) for t, d in con.execute(
        r"SELECT upper(regexp_replace(ticker,'\.NS$','')) t, min(date) FROM bc.bhavcopy_prices "
        "WHERE series='EQ' AND close>0 GROUP BY 1").fetchall()}
    seg_rows: list[dict] = []
    for ticker, g in ev.groupby("sym", sort=False):
        g = g.sort_values("ex_date")
        ratios = g["ca_ratio"].to_numpy()
        ex_dates = g["ex_date"].tolist()
        cum = np.cumprod(ratios)               # R just after each event
        r_max = float(cum[-1])
        start = first_dates.get(ticker)
        if start is not None and start < ex_dates[0]:
            seg_rows.append({"ticker": ticker, "from_date": start, "cum_mult": 1.0,
                             "adj_factor": 1.0 / r_max})    # pre-first-CA: scaled down by all CAs
        for k, exd in enumerate(ex_dates):
            R = float(cum[k])
            seg_rows.append({"ticker": ticker, "from_date": exd, "cum_mult": R,
                             "adj_factor": R / r_max})       # latest segment -> 1.0
    seg = pd.DataFrame(seg_rows) if seg_rows else pd.DataFrame(
        columns=["ticker", "from_date", "cum_mult", "adj_factor"])
    con.execute("DROP TABLE IF EXISTS ca_factor")
    con.register("seg_df", seg)
    con.execute("CREATE TABLE ca_factor AS SELECT ticker, from_date::DATE from_date, "
                "cum_mult, adj_factor FROM seg_df")
    con.execute("CREATE INDEX idx_caf ON ca_factor(ticker, from_date)")
    print(f"ca_factor: {len(seg):,} segments")

    # ── delistings registry + ca_uncertain flag ──────────────────────────────────────────────
    confirmed_keys = {(r.sym, r.ex_date) for r in ev.itertuples()}
    big_unconf = cand[(~cand["confirmed"]) & (cand["gap_raw"].apply(
        lambda x: abs(x - 1) > UNCERTAIN_GAP if x >= 1 else abs(1/x - 1) > UNCERTAIN_GAP))]
    uncertain_syms = set(big_unconf["sym"]) - {s for (s, _) in confirmed_keys}

    con.execute("DROP TABLE IF EXISTS delistings")
    con.execute("""
        CREATE TABLE delistings AS
        WITH last_px AS (
            SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym,
                   arg_max(close,date) last_raw_close, max(date) last_date
            FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0
              AND upper(regexp_replace(ticker,'\\.NS$','')) IN (SELECT sym FROM dead_names)
            GROUP BY 1)
        SELECT l.sym AS symbol, l.last_date, l.last_raw_close,
               (SELECT max(mcap_cr) FROM pit_mcap_dead d WHERE d.sym=l.sym) AS ever_mcap_cr,
               FALSE AS ca_uncertain
        FROM last_px l""")
    if uncertain_syms:
        con.execute("UPDATE delistings SET ca_uncertain=TRUE WHERE symbol IN ("
                    + ",".join("'%s'" % s.replace("'", "''") for s in uncertain_syms) + ")")
    nd = con.execute("SELECT count(*), sum(CASE WHEN ca_uncertain THEN 1 ELSE 0 END), "
                     "count(ever_mcap_cr) FROM delistings").fetchone()
    print(f"delistings: {nd[0]} dead names · {nd[1] or 0} ca_uncertain · {nd[2]} with pit_mcap history")

    # ── validation vs Trendlyne adjusted/raw ground truth (live names) ───────────────────────
    gt = con.execute(r"""
        WITH sym AS (SELECT pk, upper(nsecode) s FROM stocks WHERE nsecode<>''),
        j AS (SELECT m.s sym, y.date, y.close/b.close f FROM ohlcv y JOIN sym m USING(pk)
              JOIN bc.bhavcopy_prices b ON upper(regexp_replace(b.ticker,'\.NS$',''))=m.s AND b.date=y.date
              WHERE b.series='EQ' AND b.close>0),
        s AS (SELECT sym,date,f,lag(f) OVER (PARTITION BY sym ORDER BY date) pf FROM j)
        SELECT sym, date, f/pf sf FROM s WHERE pf IS NOT NULL AND abs(f/pf-1)>0.05""").fetchdf()
    gt["sf"] = gt["sf"].apply(lambda g: snap(g, 0.06))
    gt = gt.dropna(subset=["sf"]); gt["date"] = pd.to_datetime(gt["date"])
    gt_by = {s: list(zip(d["date"], d["sf"])) for s, d in gt.groupby("sym")}
    tp = fp = 0; matched = set()
    for r in ev.itertuples():
        hit = None
        for (gd, gsf) in gt_by.get(r.sym, []):
            if abs((gd - r.ex_date).days) <= 3 and abs(gsf / r.ca_ratio - 1) < 0.10:
                hit = (r.sym, gd); break
        if hit and hit not in matched:
            tp += 1; matched.add(hit)
        elif r.sym in gt_by:          # only count FP where we HAVE ground truth (live names)
            fp += 1
    fn = len(gt) - len(matched)
    print(f"\nvalidation vs Trendlyne GT (live): TP={tp} FP={fp} FN={fn}  "
          f"precision={tp/max(tp+fp,1):.2f} recall={tp/max(tp+fn,1):.2f}")
    con.close()


if __name__ == "__main__":
    main()
