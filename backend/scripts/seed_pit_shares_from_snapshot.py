#!/usr/bin/env python3
"""Seed pit_shares from a Trendlyne Data Downloader snapshot (iter-172, to-do #860).

    python scripts/seed_pit_shares_from_snapshot.py <export.xlsx> [more.xlsx ...] \
        [--snapshot YYYY-MM-DD] [--apply]

WHY
pit_mcap is `adjusted_close x shares_cr`, and shares_cr comes from pit_shares, which is DERIVED
(net profit / EPS). That derivation is wrong for two populations, measured 2026-09-07 against
Trendlyne's own market cap for 1,600 overlapping names:

  * too FEW shares - recent listings whose only pit_shares row predates their IPO. INDIQUBE has a
    single row dated 2022-03-31 and listed in 2025, so its market cap reads Rs37cr against
    Trendlyne's Rs4,285cr. Also ANANTAM, SWANDEF, BAGMANE, KRT, E2E.
  * too MANY shares - NAZARA 5.3x, ELDEHSG 7.6x, INDIAGLYCO 4.1x, HEG 2.7x. These have 30+ rows;
    the derivation itself is off for them, most likely bad EPS.

31 of 1,600 names (1.9%) were off by more than 50%. Each one is a stock the Rs500cr universe gate
admits or excludes wrongly.

WHAT THIS DOES
The export carries Trendlyne's own Market Capitalization AND Current Price. Their ratio IS their
share count - internally consistent, and independent of our price data, so it cannot inherit our
own errors. This writes that count into pit_shares dated the snapshot, where the ASOF join in
rebuild_pit_mcap_ca.py picks it up for recent dates.

STATUS 2026-09-07: TRIED, MEASURED, ROLLED BACK. DO NOT RUN EXPECTING A FIX.

Run against the 2026-09-07 snapshot it rewrote 93 share counts and moved the needle almost not at
all, while breaking a name that had been correct:

    before   85.6% of 1,600 names within 10% of Trendlyne,  31 off by >50%
    after    85.9%                                          30 off by >50%
    PRAJIND  6,395 (right) -> 3 (wrong)

WHY IT DID NOT WORK, so the next attempt starts here instead of repeating this:

  1. The rows must be dated at or before the price bar they are meant to apply to. The ASOF join in
     rebuild_pit_mcap_ca.py is `ps.from_date <= y.date`, so rows dated after the newest ohlcv bar
     are unreachable. The first run wrote them at the snapshot date and changed nothing at all.
  2. Clamping to the GLOBAL last bar is still not enough. The names this was built for - BAGMANE,
     INDIQUBE, ANANTAM, SWANDEF, KRT, E2E - are recent listings whose OWN price history ends
     earlier, so the ASOF at their last bar still picks an older row. A working version has to
     clamp PER SYMBOL to that symbol's own last priced date.
  3. A single current share count cannot repair history anyway. It fixes the tail and leaves every
     earlier date on the old derived value, which is where most of the error lives.

The real fix is a per-quarter share-count source, not a snapshot. Kept as groundwork: the export
parsing and the implied-count arithmetic (mcap / price, both Trendlyne's own, so it cannot inherit
our price errors) are sound and reusable.

DELIBERATELY BOUNDED
  * It writes ONE row per name, dated the snapshot. History keeps whatever it had - correcting the
    past needs a per-quarter source, which this is not (that is the rest of #860).
  * It only writes where the implied count differs from the newest stored count by more than
    --threshold (default 20%), so a normal buyback does not churn the table.
  * Dry-run by default. --apply needs the api stopped (it writes trendlyne.duckdb).
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB = Path(__file__).resolve().parents[1] / "data" / "trendlyne.duckdb"
MCAP_COL, PRICE_COL, CODE_COL = "Market Capitalization", "Current Price", "NSE Code"


def _read(path: str) -> dict[str, tuple[float, float]]:
    """{NSE code: (mcap_cr, price)} from one export. Header row is found, never assumed."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        hdr, hdr_row = None, None
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(c.lower() in ("nse code", "nsecode") for c in cells):
                hdr, hdr_row = cells, i
                break
        if hdr is None or MCAP_COL not in hdr or PRICE_COL not in hdr:
            return {}
        ci, mi, pi = hdr.index(CODE_COL), hdr.index(MCAP_COL), hdr.index(PRICE_COL)
        out = {}
        for r in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
            code = str(r[ci]).strip().upper() if r[ci] else ""
            m, p = r[mi], r[pi]
            if code and isinstance(m, (int, float)) and isinstance(p, (int, float)) and p > 0 and m > 0:
                out[code] = (float(m), float(p))
        return out
    finally:
        wb.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--snapshot", default=str(dt.date.today()))
    ap.add_argument("--threshold", type=float, default=0.20,
                    help="only rewrite where the implied count differs by more than this fraction")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    snap = dt.date.fromisoformat(args.snapshot[:10])

    merged: dict[str, tuple[float, float]] = {}
    for f in args.files:
        got = _read(f)
        print(f"  {Path(f).name}: {len(got):,} names with both mcap and price")
        merged.update(got)
    if not merged:
        sys.exit("no usable rows - do the exports carry 'Market Capitalization' and 'Current Price'?")
    print(f"\n{len(merged):,} distinct names across all files")

    con = duckdb.connect(str(DB), read_only=not args.apply)

    # CLAMP the row date to the last price bar. rebuild_pit_mcap_ca.py joins
    #     ASOF LEFT JOIN pit_shares ps ON ps.pk = y.pk AND ps.from_date <= y.date
    # so a row dated AFTER the newest ohlcv bar is never reachable - it sits in the future and does
    # nothing. Learned the hard way on the first run of this script: 91 rows written at 2026-09-07
    # against prices ending 2026-08-28, and every corrected market cap came back unchanged.
    # Share counts move slowly, so applying an export taken today to the last available bar is a
    # small and disclosed approximation; leaving a 563x error in place is not.
    px_max = con.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
    if px_max and snap > px_max:
        print(f"  snapshot {snap} is after the last price bar {px_max} — dating the rows "
              f"{px_max} so the ASOF join can reach them")
        snap = px_max

    pkmap = {r[0].upper(): r[1] for r in con.execute(
        "SELECT upper(nsecode), pk FROM stocks WHERE nsecode <> '' "
        "UNION SELECT upper(nse_symbol), pk FROM recovered_symbols WHERE nse_symbol <> ''").fetchall()}
    current = {r[0]: r[1] for r in con.execute(
        "SELECT pk, arg_max(shares_cr, from_date) FROM pit_shares WHERE shares_cr > 0 "
        "GROUP BY pk").fetchall()}

    rows, unchanged, no_pk = [], 0, 0
    for code, (mcap, price) in merged.items():
        pk = pkmap.get(code)
        if pk is None:
            no_pk += 1
            continue
        implied = mcap / price                      # Rs cr / Rs = crore shares
        have = current.get(pk)
        if have and abs(implied - have) / have <= args.threshold:
            unchanged += 1
            continue
        rows.append((pk, code, implied, have))

    print(f"  matched to a Trendlyne pk : {len(merged) - no_pk:,}   (unmatched {no_pk:,})")
    print(f"  within {args.threshold:.0%} of the stored count, left alone : {unchanged:,}")
    print(f"  WOULD REWRITE : {len(rows):,}")

    big = sorted((r for r in rows if r[3]), key=lambda r: -abs(r[2] - r[3]) / r[3])[:15]
    print(f"\n  largest corrections (stored -> implied, crore shares):")
    for pk, code, implied, have in big:
        print(f"    {code:<14} {have:>12,.2f} -> {implied:>12,.2f}   ({implied / have:>7,.1f}x)")
    fresh = [r for r in rows if not r[3]]
    if fresh:
        print(f"\n  names with NO stored share count at all: {len(fresh):,}"
              f"  e.g. {[r[1] for r in fresh[:8]]}")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply (api stopped).")
        con.close()
        return

    # Clear both the clamped date and the raw snapshot date — an earlier run of this script may
    # have left unreachable rows at the un-clamped date.
    con.execute("DELETE FROM pit_shares WHERE from_date IN (?, ?)",
                [snap, dt.date.fromisoformat(args.snapshot[:10])])
    con.executemany("INSERT INTO pit_shares (pk, from_date, shares_cr) VALUES (?, ?, ?)",
                    [(pk, snap, implied) for pk, _c, implied, _h in rows])
    n = con.execute("SELECT COUNT(*) FROM pit_shares WHERE from_date = ?", [snap]).fetchone()[0]
    con.close()
    print(f"\nwrote {n:,} pit_shares rows dated {snap}.")
    print("NEXT: rebuild_pit_mcap_ca.py, then build_membership.py, then restart the api.")


if __name__ == "__main__":
    main()
