# Trendlyne refresh runbook (monthly, owner-in-browser)

Written iter-147 (2026-08-10), reconstructing the 2026-07-16 iter-22 procedure whose ingest
script lived only in a session scratchpad. The ingest is now a repo script:
`backend/scripts/ingest_refresh.py`.

**Why manual:** every Trendlyne endpoint is WAF-protected — plain curl/Python gets 403 even with
cookies. The harvesters are console scripts that run inside a logged-in browser tab. Nothing
server-side can replace this step.

**Why it matters:** `pit_universe` gates membership on a **14-day lookback**, and Trendlyne's
own OHLC endpoint **lags its DVM by ~8 days**. If a pull doesn't land within 14 days of a
monthly rebalance, the universe empties and signals silently resolve on the last healthy bar
(weeks-old factors). The 1 Aug 2026 rebalance ran on 8 Jul factors for exactly this reason.

**When to run:** ideally the last 2–3 days of each month (for the 1st-of-month 21:30 rebalance
cron). A mid-month run is never wasted — live signals degrade daily past ~8 days of staleness.

---

## Phase 1 — browser (logged-in trendlyne.com tab, F12 → Console, paste, Enter)

Scripts live in `Desktop/Projects/Windfall Labs/harvesters/` on the Windows machine (one-offs already applied are in `harvesters/_done/`; see that folder README for cadence). Click **Allow** when
the browser asks about multiple downloads. Run all three — **a refresh takes three scripts, not
one** (iter-22: DVM-only ingest would have deleted 806k rows / 138 megacaps — the base screener
silently excludes the top ~100 index names).

| # | Script | Time | Output (Downloads) |
|---|--------|------|--------------------|
| 1 | `trendlyne_dvm_harvester.js` | ~15–20 min | `tl_dvm_history_partNN.csv`, `tl_stocks.csv` |
| 2 | `trendlyne_harvester_megacap.js` | ~10 min | `tl_*_megacap.csv` (covers the index-megacap crack) |
| 3 | `trendlyne_harvester_ohlcv.js` | ~35–45 min | `tl_ohlcv_partNN.csv`, `tl_index_ohlcv.csv`, `tl_index_map.csv` |
| 4 | `trendlyne_harvester_gapfill.js` — only if specific names froze | ~2 min | `tl_*_gapfill.csv` |

Gotchas (all cost a bug once):
- The megacap `SYMBOLS` list is **hardcoded and drifts** — 2026-07-16 it was missing
  CIPLA/ZYDUSLIFE/LUPIN/LODHA. If the ingest dry-run later shows a big live name in
  "preserved" that shouldn't be there, add it to `trendlyne_harvester_gapfill.js` (supports
  `{sym, pk}` entries; "BSE" must be pk 52884 — the symbol search can't resolve it) and re-run.
- A harvester reporting `NO PK` for a name: tell Claude which one — don't assume it's absent.
- If the DVM harvester reports fewer than ~1,800 stocks, the screener list truncated — re-run
  it; don't ingest.

## Phase 2 — stage + ship to the server

```bash
# on the Windows machine (Git Bash) — stage this month's files only, then ship
mkdir -p ~/Downloads/tl_refresh && mv ~/Downloads/tl_*.csv ~/Downloads/tl_refresh/
scp -q ~/Downloads/tl_refresh/*.csv pdsv@192.168.1.10:/mnt/storage/websites/windfall-labs/backend/data/refresh_staging/
```

## Phase 3 — server ingest (avoid 20:25–20:45 IST weekdays — the EOD cron restarts the api)

```bash
ssh pdsv@192.168.1.10
cd /mnt/storage/websites/windfall-labs/backend

# 1. DRY RUN — read the report before writing anything
.venv/bin/python scripts/ingest_refresh.py data/refresh_staging

#    Read it like this:
#    - "preserved" pks are EXPECTED (names below the Rs500cr floor + delisted stay untouched —
#      that is the survivorship-safety working, ~40–60 names normal)
#    - preserved in the HUNDREDS = truncated harvest -> STOP, re-run the harvester
#    - tl_index_ohlcv.csv listed as "ignoring on purpose" is correct (adr-038 feed is fresher)

# 2. apply (script auto-backs-up trendlyne.duckdb first; needs the api stopped)
docker compose -f ../docker-compose.yml stop api
.venv/bin/python scripts/ingest_refresh.py data/refresh_staging --apply

# 3. rebuild the point-in-time layers that hang off the refreshed tables
.venv/bin/python scripts/rebuild_pit_mcap_ca.py
.venv/bin/python scripts/build_membership.py

# 4. restart + verify
docker compose -f ../docker-compose.yml start api
sleep 5 && curl -s http://127.0.0.1:8505/api/data/status | python3 -c \
  "import json,sys; d=json.load(sys.stdin)['trendlyne']; print('date_max', d['date_max'], '- expect within ~8-10 days of today')"

# 5. clean the staging dir so next month starts empty
rm data/refresh_staging/*.csv
```

## Phase 4 — fundamentals snapshot (separate export, ~quarterly-fresh is enough, 35d reminder)

The DVM/OHLCV harvest does NOT refresh the fundamentals snapshot table (53 days stale as of
2026-08-10; the 1st-of-month 9:00 reminder cron nags when >35d).

1. Trendlyne → **Data Downloader** → export the usual column-group `.xlsx` files
   (same groups as last time; forward-PE, dividend yield, EV/EBITDA columns included — #26).
2. Ship + ingest (snapshot date = the export date):

```bash
scp -q ~/Downloads/<the-xlsx-files> pdsv@192.168.1.10:/tmp/
ssh pdsv@192.168.1.10 'cd /mnt/storage/websites/windfall-labs/backend && \
  .venv/bin/python scripts/ingest_fundamentals.py /tmp/*.xlsx --snapshot YYYY-MM-DD'
```

## What this feeds

`dvm_history` + `ohlcv` + `stocks` (merged per-pk, never replaced) → `rebuild_pit_mcap_ca.py`
→ `pit_mcap` → `build_membership.py` → `universe_membership` → live signals + backtests.
Index prices come from the automated EOD cron (adr-038), never from a harvest.
