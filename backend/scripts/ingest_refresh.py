#!/usr/bin/env python3
"""Merge a Trendlyne harvest (DVM + OHLCV + stocks) into trendlyne.duckdb — refresh ingest.

MERGE, NEVER REPLACE (iter-22 rule, adr-030): a harvest only covers names in the screener
universe TODAY. Replacing tables deletes the history of names that legitimately fell below
the Rs500cr floor or delisted — silently reintroducing the survivorship bias the engine
exists to avoid. Correct op: for every KEY the harvest covers, drop those rows and reinsert
(each harvest is full history per series, so it supersedes); every other key is untouched.

The replace key is per-table, and it is NOT always the pk (changed 2026-09-07):
    dvm_history -> (pk, score)     ohlcv -> (pk)     stocks -> (pk)
dvm_history holds three independent series per stock (d/v/m), fetched as three separate
requests. A rate-limited harvest routinely returns only some of them. Replacing per pk
therefore DELETED the series the harvest happened to miss: on 2026-09-07 that silently
dropped 446 series across 445 stocks (SRF, BERGEPAINT, NAUKRI, YESBANK...), and the
shrink guard stayed quiet because losing 1 of 3 series is a ~35% row drop, under its 50%
bar. Replacing per (pk, score) makes a partial harvest harmless by construction: an
absent series is simply not touched. See tests/test_ingest_refresh_partial.py.

NEVER ingests index_ohlcv — the automated NSE index feed (adr-038, scripts/index_ingest.py
in the EOD cron) is fresher than Trendlyne's index OHLC; a harvest would move it backwards.

Usage (on the server, host venv — the api opens this DB read-only, so --apply needs it stopped):
    cd /mnt/storage/websites/windfall-labs/backend
    .venv/bin/python scripts/ingest_refresh.py /path/to/staged_csvs             # DRY RUN
    docker compose stop api
    .venv/bin/python scripts/ingest_refresh.py /path/to/staged_csvs --apply
    .venv/bin/python scripts/rebuild_pit_mcap_ca.py
    .venv/bin/python scripts/build_membership.py
    docker compose start api

Input files (from the browser harvesters, see docs/ops/trendlyne-refresh-runbook.md):
    tl_dvm_history_part*.csv / tl_dvm_history_megacap.csv / tl_dvm_history_gapfill.csv
    tl_ohlcv_part*.csv       / tl_ohlcv_megacap.csv       / tl_ohlcv_gapfill.csv
    tl_stocks.csv            / tl_stocks_megacap.csv      / tl_stocks_gapfill.csv
    (tl_index_ohlcv.csv / tl_index_map.csv are ignored on purpose)

Encoded gotchas from the 2026-07-16 refresh (the previous script lived only in a scratchpad):
    - "name" is a DuckDB reserved word — always quoted;
    - megacap/gapfill tl_stocks_*.csv can lack the mcap column — probed, typed-NULL, and
      coalesced with the existing DB value so a gapfill never blanks a real mcap;
    - a by-pk harvest's scraped name can be an SEO title blob — newline/length guarded;
    - overlapping sources (a pk in both megacap and gapfill) deduped by file priority.
"""
import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parents[1] / "data" / "trendlyne.duckdb"
MIN_STOCKS = 1000  # mirrors the harvester's own truncation guard


def _files(src: Path, pattern_stem: str) -> list[Path]:
    out = [p for p in sorted(src.glob(f"tl_{pattern_stem}*.csv")) if "index" not in p.name]
    return out


# dedupe priority when the same (pk, date) appears in several files: targeted pulls beat bulk
PRIO = ("CASE WHEN filename LIKE '%gapfill%' THEN 3 "
        "WHEN filename LIKE '%megacap%' THEN 2 ELSE 1 END")


def _read_union(con, files: list[Path], view: str):
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW {view} AS
        SELECT * FROM read_csv([{','.join(repr(str(f)) for f in files)}],
                               header=true, union_by_name=true, filename=true)
    """)
    return {r[0] for r in con.execute(f"DESCRIBE {view}").fetchall()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="directory holding the staged tl_*.csv harvest files")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry-run report)")
    ap.add_argument("--allow-small", action="store_true",
                    help="skip the >=1000-stock floor (gapfill-only ingest)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="permit a pk's history to shrink >50%% (deliberate upstream correction)")
    args = ap.parse_args()
    src = Path(args.src).expanduser()

    dvm_f, ohlcv_f, stocks_f = _files(src, "dvm_history"), _files(src, "ohlcv"), _files(src, "stocks")
    ignored = sorted(src.glob("tl_index_*.csv"))
    if ignored:
        print(f"ignoring on purpose (adr-038 index feed is fresher): {[p.name for p in ignored]}")
    if not (dvm_f or ohlcv_f or stocks_f):
        sys.exit(f"no tl_dvm_history*/tl_ohlcv*/tl_stocks* files in {src}")

    mode = "rw" if args.apply else "ro"
    if args.apply:
        bak = DB.with_name(f"{DB.name}.pre-refresh-{dt.date.today()}-bak")
        if not bak.exists():
            print(f"backing up {DB.name} -> {bak.name} ...")
            shutil.copy2(DB, bak)
        try:
            con = duckdb.connect(str(DB))
        except duckdb.Error as exc:
            sys.exit(f"cannot open read-write ({exc}) — is windfall-api still running? "
                     f"docker compose stop api first.")
    else:
        con = duckdb.connect(str(DB), read_only=True)

    # (table, view, insert_sql, key) — `key` is the granularity at which the apply loop
    # REPLACES. dvm_history replaces per (pk, score), NOT per pk: a harvest that returns only
    # 2 of a stock's 3 score series must leave the third alone, not delete it. See adr note
    # + to-do #833; on 2026-09-07 a pk-level replace silently dropped 446 score series.
    plans = []

    if dvm_f:
        _read_union(con, dvm_f, "h_dvm")
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW h_dvm_d AS
            SELECT CAST(pk AS BIGINT) pk, CAST(score AS VARCHAR) score,
                   CAST("date" AS DATE) "date", CAST("value" AS DOUBLE) "value"
            FROM h_dvm
            QUALIFY row_number() OVER (PARTITION BY pk, score, "date" ORDER BY {PRIO} DESC) = 1
        """)
        plans.append(("dvm_history", "h_dvm_d",
                      'INSERT INTO dvm_history SELECT pk, score, "date", "value" FROM h_dvm_d',
                      ("pk", "score")))
    if ohlcv_f:
        _read_union(con, ohlcv_f, "h_ohlcv")
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW h_ohlcv_d AS
            SELECT CAST(pk AS BIGINT) pk, CAST("date" AS DATE) "date",
                   CAST("open" AS DOUBLE) "open", CAST("high" AS DOUBLE) "high",
                   CAST("low" AS DOUBLE) "low", CAST("close" AS DOUBLE) "close",
                   CAST("last" AS DOUBLE) "last", CAST(volume AS BIGINT) volume
            FROM h_ohlcv
            QUALIFY row_number() OVER (PARTITION BY pk, "date" ORDER BY {PRIO} DESC) = 1
        """)
        plans.append(("ohlcv", "h_ohlcv_d",
                      'INSERT INTO ohlcv SELECT pk,"date","open","high","low","close","last",volume '
                      "FROM h_ohlcv_d",
                      ("pk",)))
    if stocks_f:
        have = _read_union(con, stocks_f, "h_stocks")
        mcap_src = "CAST(h.mcap AS DOUBLE)" if "mcap" in have else "CAST(NULL AS DOUBLE)"
        # TEMP TABLE, not VIEW (verifier-936 hard failure): this plan LEFT JOINs the target
        # `stocks` table for the mcap/name fallbacks. A lazy view re-evaluates at INSERT time —
        # AFTER the apply loop's DELETE — so COALESCE(.., s.mcap) saw NULL and a no-mcap gapfill
        # blanked real mcaps (which feed pit_mcap's shares calc). Materializing freezes the
        # pre-delete state. dvm/ohlcv plans read only CSVs, so lazy views stay fine there.
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE h_stocks_d AS
            SELECT CAST(h.pk AS BIGINT) pk, CAST(h.nsecode AS VARCHAR) nsecode,
                   -- SEO-blob guard: a by-pk scrape can return a page title; keep the DB name then
                   CASE WHEN h."name" IS NULL OR length(h."name") > 120
                             OR h."name" LIKE '%' || chr(10) || '%'
                        THEN COALESCE(s."name", left(CAST(h."name" AS VARCHAR), 120))
                        ELSE CAST(h."name" AS VARCHAR) END AS "name",
                   COALESCE({mcap_src}, s.mcap) AS mcap,
                   CAST(h.d_now AS BIGINT) d_now, CAST(h.v_now AS DOUBLE) v_now,
                   CAST(h.m_now AS DOUBLE) m_now
            FROM h_stocks h LEFT JOIN stocks s ON s.pk = CAST(h.pk AS BIGINT)
            QUALIFY row_number() OVER (PARTITION BY h.pk ORDER BY {PRIO} DESC) = 1
        """)
        plans.append(("stocks", "h_stocks_d",
                      'INSERT INTO stocks SELECT pk, nsecode, "name", mcap, d_now, v_now, m_now '
                      "FROM h_stocks_d",
                      ("pk",)))
        n_stocks = con.execute("SELECT COUNT(DISTINCT pk) FROM h_stocks_d").fetchone()[0]
        if n_stocks < MIN_STOCKS and not args.allow_small:
            sys.exit(f"ABORT: harvest covers only {n_stocks} stocks (<{MIN_STOCKS}) — truncated "
                     f"list? A full-refresh ingest of a partial harvest would freeze everyone "
                     f"else's history. Re-run the harvester, or pass --allow-small for a "
                     f"deliberate gapfill-only ingest.")

    print(f"\n{'table':<14}{'harvest pks':>12}{'harvest rows':>14}{'db pks':>10}"
          f"{'preserved':>11}{'new':>6}   harvest date range")
    for table, view, _, key in plans:
        hp, hr = con.execute(f"SELECT COUNT(DISTINCT pk), COUNT(*) FROM {view}").fetchone()
        dp = con.execute(f"SELECT COUNT(DISTINCT pk) FROM {table}").fetchone()[0]
        pres = con.execute(f"SELECT COUNT(DISTINCT pk) FROM {table} "
                           f"WHERE pk NOT IN (SELECT pk FROM {view})").fetchone()[0]
        new = con.execute(f"SELECT COUNT(DISTINCT pk) FROM {view} v "
                          f"WHERE pk NOT IN (SELECT pk FROM {table})").fetchone()[0]
        rng = ("", "")
        if table != "stocks":
            rng = con.execute(f'SELECT MIN("date"), MAX("date") FROM {view}').fetchone()
        print(f"{table:<14}{hp:>12}{hr:>14}{dp:>10}{pres:>11}{new:>6}   {rng[0]} .. {rng[1]}")
        # Sub-series coverage. A stock can be "covered" at pk level while the harvest
        # carries only SOME of its series - the exact blind spot that cost 446 dvm series
        # on 2026-09-07. Surfaced here so a partial harvest is visible BEFORE the apply.
        if len(key) > 1:
            kc = ", ".join(key)
            miss = con.execute(f"SELECT COUNT(*) FROM ("
                               f"SELECT DISTINCT {kc} FROM {table} EXCEPT "
                               f"SELECT DISTINCT {kc} FROM {view})").fetchone()[0]
            held = con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {kc} FROM {view})").fetchone()[0]
            note = "kept as-is, NOT deleted" if miss else "full coverage"
            print(f"{'':<14}series: harvest carries {held}, DB has {miss} it omits - {note}")
    print("\npreserved = pks in the DB the harvest does not cover (sub-floor / delisted names) —"
          "\ntheir history is kept untouched; a huge preserved count means a truncated harvest.\n")

    # History-shrink guard: each harvest carries FULL history per stock, so replacing a pk's rows
    # with far fewer than it has is almost always a truncated/partial file, not a correction.
    # (Found by test: a 2-row fixture would have silently replaced BSE's ~6,600-row history.)
    shrinkers = []
    for table, view, _, key in plans:
        if table == "stocks":
            continue
        # Compare at the SAME granularity the apply loop replaces at. For dvm_history that
        # is (pk, score): a pk-level comparison cannot see a stock that kept 2 of 3 series
        # (a ~35% drop, under the 50% bar) — which is exactly how 446 series were lost on
        # 2026-09-07 with the guard reporting nothing.
        cols = ", ".join(key)
        rows = con.execute(f"""
            SELECT {cols}, hr, dr FROM
              (SELECT {cols}, COUNT(*) hr FROM {view} GROUP BY {cols}) h
              JOIN (SELECT {cols}, COUNT(*) dr FROM {table} GROUP BY {cols}) d USING ({cols})
            WHERE hr < 0.5 * dr ORDER BY dr - hr DESC
        """).fetchall()
        shrinkers += [(table, key, r) for r in rows]
    if shrinkers:
        # len(shrinkers) is now the REAL total — the old query carried LIMIT 10, so this line
        # used to print "10" no matter how bad it was (to-do #832).
        print(f"⚠ HISTORY-SHRINK: {len(shrinkers)} series would lose >50% of their stored rows "
              f"(harvest rows << DB rows):")
        for table, key, r in shrinkers[:10]:
            ident = " ".join(f"{k}={v}" for k, v in zip(key, r[:len(key)]))
            hr, dr = r[len(key)], r[len(key) + 1]
            print(f"    {table} {ident}: {dr} rows in DB, only {hr} in harvest")
        if len(shrinkers) > 10:
            print(f"    ... and {len(shrinkers) - 10} more")
        if args.apply and not args.allow_shrink:
            sys.exit("ABORT: refusing to apply a history-shrinking ingest. If this is a real "
                     "upstream correction, re-run with --allow-shrink; otherwise the harvest "
                     "file is partial/truncated — re-pull it.")

    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply (api stopped) to ingest.")
        con.close()
        return

    for table, view, insert_sql, key in plans:
        before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        # Replace only what the harvest actually carries, at `key` granularity. With
        # key=(pk, score) a harvest holding just momentum for a stock leaves that stock's
        # durability and valuation series untouched instead of deleting them.
        match = " AND ".join(f"v.{k} = {table}.{k}" for k in key)
        con.execute("BEGIN")
        con.execute(f"DELETE FROM {table} WHERE EXISTS "
                    f"(SELECT 1 FROM {view} v WHERE {match})")
        con.execute(insert_sql)
        con.execute("COMMIT")
        after, mx = before, None
        after = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if table != "stocks":
            mx = con.execute(f'SELECT MAX("date") FROM {table}').fetchone()[0]
        print(f"applied {table}: rows {before} -> {after}" + (f", max date {mx}" if mx else ""))
    con.close()
    print("\ningest done. NEXT: rebuild_pit_mcap_ca.py, build_membership.py, "
          "docker compose start api, then verify /api/data/status trendlyne.date_max.")


if __name__ == "__main__":
    main()
