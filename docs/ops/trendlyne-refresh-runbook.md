# Trendlyne refresh runbook (monthly, owner-in-browser — factors only since adr-050)

Written iter-147 (2026-08-10), reconstructing the 2026-07-16 iter-22 procedure whose ingest
script lived only in a session scratchpad. The ingest is now a repo script:
`backend/scripts/ingest_refresh.py`.

**Why manual:** every Trendlyne endpoint is WAF-protected — plain curl/Python gets 403 even with
cookies. The harvesters are console scripts that run inside a logged-in browser tab. Nothing
server-side can replace this step.

**What it still feeds (adr-050, iter-204):** the DVM scores and valuation multiples four paper
books rank on — nothing else. **Prices and the Rs500cr universe no longer need a harvest:**
Trendlyne's price history is frozen at its last harvest and every later bar is NSE Bhavcopy
adjusted with NSE's corporate actions; from 2024-02-01 membership is NSE's official market cap,
pulled nightly by the EOD cron (`scripts/nse_mcap_ingest.py`). A late refresh now means stale
*factors* (the iter-202 stale-factor guard holds a factor book rather than rebalancing on them),
not an empty universe.

**When to run:** ideally the last 2–3 days of each month (for the 1st-of-month 21:30 rebalance
cron). A mid-month run is never wasted — live signals degrade daily past ~8 days of staleness.

---

## Phase 1 — browser (logged-in trendlyne.com tab, F12 → Console, paste, Enter)

Scripts live in `Desktop/Projects/Windfall Labs/harvesters/` on the Windows machine (one-offs already applied are in `harvesters/_done/`; see that folder README for cadence). Click **Allow** when
the browser asks about multiple downloads. Run the DVM **and** megacap scripts — the base screener
silently excludes the top ~100 index names, whose DVM and valuation rows come only from the megacap
leg (iter-22: a DVM-only ingest would have deleted 806k rows / 138 megacaps).

| # | Script | Time | Output (Downloads) |
|---|--------|------|--------------------|
| 1 | `trendlyne_dvm_harvester.js` | ~15–20 min | `tl_dvm_history_partNN.csv`, `tl_stocks.csv` |
| 2 | `trendlyne_harvester_megacap.js` | ~10 min | `tl_*_megacap.csv` (covers the index-megacap crack) |
| ~~3~~ | ~~`trendlyne_harvester_ohlcv.js`~~ — **retired (adr-050)**: prices come from NSE | — | — |
| 4 | `trendlyne_harvester_leg1_lite.js` | ~20 min | `tl_valuation_ratios_partNN.csv` (plus `tl_growth_quality_*` when `FETCH_QUARTERLY` is switched on — do that in the month after a results season closes, i.e. once `MAX(date)` in `growth_quality` is a quarter behind the last quarter-end; otherwise `tl_piotroski` / `tl_np_growth` / `tl_rev_growth` freeze for non-megacap names) |
| 4b | `trendlyne_harvester_leg1.js` — the full 25-code version, ~150 min; only if a strategy starts to read `pnl_quarterly` or `ownership` | ~150 min | adds `tl_pnl_quarterly_*`, `tl_ownership_*` |
| 5 | `trendlyne_harvester_gapfill.js` — only if specific names froze | ~2 min | `tl_*_gapfill.csv` |

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
#    - the report must list THREE tables: dvm_history, stocks, valuation_ratios (OHLCV files are
#      ignored on purpose since adr-050 — the megacap leg still emits one). A missing
#      valuation_ratios line means neither leg1 nor the megacap harvester's CSV landed — do NOT proceed to
#      step 5 (which deletes the staging dir), because that is exactly how the table went 54 days
#      stale unnoticed (#849).
#    - "preserved" pks are EXPECTED (names below the Rs500cr floor + delisted stay untouched —
#      that is the survivorship-safety working, ~40–60 names normal)
#    - preserved in the HUNDREDS = truncated harvest -> STOP, re-run the harvester
#    - tl_index_ohlcv.csv listed as "ignoring on purpose" is correct (adr-038 feed is fresher)

# 2. apply (script auto-backs-up trendlyne.duckdb first; needs the api stopped)
docker compose -f ../docker-compose.yml stop api
.venv/bin/python scripts/ingest_refresh.py data/refresh_staging --apply

# 3. (retired, adr-050) rebuild_pit_mcap_ca.py / build_membership.py — they derive pre-2024
#    membership from the frozen close x this month's share count and would rewrite history on every
#    run; both now refuse without --force-after-adr-050.

# 4. restart + verify
docker compose -f ../docker-compose.yml start api
sleep 5 && curl -s http://127.0.0.1:8505/api/data/status | python3 -c \
  "import json,sys; d=json.load(sys.stdin)['trendlyne']; print('date_max', d['date_max'], '- the frozen price harvest; factors are what this refresh moves')"

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

`dvm_history` + `stocks` + `valuation_ratios` (merged per key, never replaced) → the factor ranks.
Prices: frozen Trendlyne `ohlcv` + NSE Bhavcopy adjusted with NSE corporate actions (adr-049/050).
Universe: `universe_membership` (frozen pit_mcap) before 2024-02-01, NSE's official market cap from
it, behind the point-in-time NSE gate (adr-050).
Index prices come from the automated EOD cron (adr-038), never from a harvest.

### `valuation_ratios` — added to the ingest 2026-09-07 (iter-172, to-do #849)

`PE_TTM` / `PEG_TTM` / `PBV_A`, the daily multiples behind the `tl_pe` / `tl_peg` / `tl_pbv`
factors. **This table was not in the ingest until now**, and the omission was invisible: the
megacap harvester (step 2 above) has always emitted `tl_valuation_ratios_megacap.csv`, the ingest
ignored it, and step 5 of Phase 3 deleted it with the rest of the staging dir. It froze at
2026-07-15 while DVM reached 2026-09-04. 48 of 289 saved strategies rank on these factors and one
of them — `CMP_valmom_m_20` — is a live paper book that was ranking half its holdings on
seven-week-old P/Es while reporting a current `as_of`.

- Replaced per **(pk, metric)**, the same shape as `dvm_history`'s (pk, score): a harvest carrying
  only `PE_TTM` cannot delete a stock's `PEG_TTM` and `PBV_A`.
- The monthly megacap leg covers ~99 names. **Full coverage needs
  `trendlyne_harvester_leg1_lite.js` run as well** (row 4 above) — it is the only script that pulls
  valuation ratios for the whole ~1,800-name universe; without it the non-megacap names keep ageing.
- Since iter-172 a stale factor is no longer silent: `resolve()` emits a `stale factor: ...`
  warning on any daily panel carried forward more than 14 days. If you see one after a refresh,
  the corresponding table did not land — check the staging dir before deleting it.
