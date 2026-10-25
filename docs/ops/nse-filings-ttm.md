# NSE filings -> point-in-time trailing-twelve-month EPS / P/E (to-do #970, iteration 206)

A free, server-side, no-browser source for the one number the Value + Momentum book ranks on. Research store
only: **nothing here is an engine factor yet** (adr-052 point 3 says how it would become one).

## What it is

- `backend/windfall/data/nse_filings.py` — fetch, parse, store, and the research series (`ttm_eps`,
  `pe_ttm_panel`).
- `backend/data/nse_filings.duckdb` — `filings` (one row per company, quarter and basis; the **earliest**
  broadcast kept, so every figure carries the moment the market could first have known it) and `fetch_log`.
- `backend/data/nse_filings_raw/<SYMBOL>/<period>_<basis>.{xml.gz,json}` — every fetched filing, so a parser
  fix is `python -m windfall.data.nse_filings reparse`, not a 20-hour refetch.
- Sources: NSE's legacy financial-results API (XBRL from 2017–18 to Dec 2024) and the integrated-filing API
  (2025 onward, raw XBRL under `xbrl`). Both use the same tags and contexts (`OneD` = the quarter, `FourD` = the
  fiscal year to date). Banks use a different spelling (`InterestEarned`, `ProfitLossForThePeriod`,
  `BasicEarningsPerShareAfterExtraordinaryItems`); the parser has both.
- Symbol list: `backend/data/nse_filings_symbols.csv` — 2,138 companies ever in the Rs500cr universe since
  2018, with their other tickers in `alts` (NSE answers by the current symbol; a renamed company is found
  through its alias). Built by `scripts/free_pe/nse_symbols.py`.

## The full run (restarted 2026-10-25 14:51 IST, after the verifier's three fixes)

The first run (13:51) was stopped after about 110 companies: the independent verifier found that it dropped every
legacy standalone filing (NSE labels them "Non-Consolidated"), stored twice the real EPS for the 18 filings where a
filer tags discontinued-operations EPS with the continuing figure, and let files that name the wrong year (14 in the first 106 companies, 17 in the first 2,200 files)
overwrite the real quarter. A refused file is not recorded, so each re-run fetches it again (about 1% of filings); the quarter simply stays missing from that company's TTM. All three are fixed (tests in `test_iter206_nse_filings.py`), the table was rebuilt from
the saved raw files with `reparse`, and the buggy copy is in `backend/data/snapshots/`. The pilot numbers below
were measured before the fixes and have not been re-run on the corrected data.

```bash
cd /mnt/storage/websites/windfall-labs/backend
PYTHONPATH=. setsid nohup .venv/bin/python -u -m windfall.data.nse_filings fetch \
  --symbols-file data/nse_filings_symbols.csv --throttle 1.0 > data/nse_filings_fetch.log 2>&1 < /dev/null &
```

- One worker, ~1 s between requests, about 27–37 s per company (the log's running average), ~34 requests each:
  **roughly 16–20 hours from a clean start** (about 70,000 requests; the restarted run is quicker per company while it skips the quarters already stored). Five consecutive errors pause it for 10 minutes and, after
  three pauses, stop it (re-run to resume). It is resumable: companies marked `done` or `empty` are skipped on a re-run, a
  `partial` one only re-tries the quarters it is missing. A reboot stops it; re-run the same command.
- **Progress:** `tail data/nse_filings_fetch.log` (a line every 10 companies). The DuckDB file is locked by the
  running fetch, so `status` and queries wait until it ends. Do not copy the file while it runs.
- **When it ends** (the log's last line is the `status` dict):
  1. `.venv/bin/python -m windfall.data.nse_filings status` — expect `done` for most companies; `partial` and
     `empty` are listed in `fetch_log.detail`.
  2. `WINDFALL_DATA_DIR=$PWD/data WINDFALL_DB=<copy of windfall.duckdb> PYTHONPATH=. .venv/bin/python
     scripts/free_pe/nse_ttm_validate.py` — the agreement table against `tl_pe` and the annual `pe`.
  3. Re-run the equal-terms backtest with the NSE series (not wired into `pe_backtests.py` yet — it needs a
     `nse_pe` feature in `resolve.py`, which is the engine change adr-052 point 3 asks for in its own ADR).
- **Refresh later:** the same command re-run each quarter (after results season) adds only the new quarters.

## Pilot result (37 companies, 951 filings, before the full run)

`nse_ttm_validate.py` on banks (HDFCBANK, KOTAKBANK, SBIN, YESBANK, IDFCFIRSTB), NBFCs, large caps and small caps
(KAMDHENU, TBZ, VENUSREM): across 2,148 company-months the NSE-filings P/E divided by Trendlyne's has a median
of 1.00, 87% within ±15% and 92% within ±30%; rank correlation with Trendlyne 0.91–0.99 by year and 0.83–0.98
with the annual P/E. Every filing carried EPS, profit and share capital (0 nulls in 951). The largest disagreement
was IDFCFIRSTB (a 2018 merger changes its share base); EXICOM has three months of history.

## Limits found

- **Standalone-only companies** (most small caps) have their standalone filings fetched since the 14:51 run;
  before it they had only the 2025+ integrated ones. A company that switches basis has no TTM across the switch.
- **TTM starts around March 2019, not 2018.** It needs four consecutive quarters on one basis and the first XBRL
  quarter is March 2018; 2018 months are empty and 2019 fills in as quarters accumulate.
- **Filings before mid-2022 declare no `OneD`/`FourD` context**; the quarter's dates are read from the
  dimensional contexts (or, failing that, the listing row). Found by the pilot: 17 of 33 TCS filings failed until
  this was handled.
- A few filings come back empty from NSE's archive (HCLTECH March 2019) and cannot be recovered; the quarter is
  left out and the TTM windows containing it are skipped.
- Half-yearly reporters (`period_months = 6`) are stored but not used in the TTM; a company whose basis changes
  (standalone to consolidated) has no TTM across the change.
- EPS is restated into today's share units with `corp_actions.share_events` for splits/bonuses after the
  broadcast date; an event NSE did not list (see adr-050) leaves a ratio error for that company.
- Revisions: only the earliest broadcast of a quarter is kept. A later restatement is ignored, which is the
  point-in-time choice, but it means a quarter's figure can differ from what the company reports today.
- The same raw files carry paid-up capital and face value (`paid_up / face_value` = shares outstanding), which
  is what to-do #876 (point-in-time share counts) needs; they are stored, not yet used.
