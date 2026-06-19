# Windfall Labs — Handover / Next-Session Brief

*Last updated: 2026-06-19. Read this first; you should not need to re-explain the project from scratch.*

## What this is
A private quant research & execution cockpit for Indian (NSE) equities. Define a strategy →
backtest with realistic costs/exits/no-look-ahead → walk-forward → live signals → paper-trade.
**Signals-only** (the human places every order). Owner trades **swing** (2 weeks–3 months); intraday/
F&O/long-term are later phases. Built through Ottomate (project slug `windfall-labs`).

## Where everything lives
- **Cockpit (web):** http://192.168.1.10:8500 (LAN) · **https://windfall-labs.vault7a.xyz** (remote, Authentik SSO)
- **API:** internal only now — the frontend proxies `/api/*` to the api container (single-origin). Host port 8505 still maps to the api container for direct/debug use.
- **Repo:** Gitea `pdsv/windfall-labs` (master) · on disk `/mnt/storage/websites/windfall-labs`
- **Server:** `ssh pdsv@192.168.1.10` · containers `windfall-web` (:8500), `windfall-api` (:8505→8503)
- **Ottomate tracker:** project `windfall-labs` (SO1, ADRs 001–007, verification reports, to-dos)

## How to run / operate
- **Stack:** `cd /mnt/storage/websites/windfall-labs && docker compose up -d --build`
- **Tests:** `cd backend && . .venv/bin/activate && python -m pytest -q` (34 pass)
- **CLI:** `python -m windfall.cli {coverage|backtest <cfg>|signals <cfg>|walk-forward <cfg> --grid g.json|validate|paper-mark}`
- **Load prices:** `python scripts/load_data.py --universe niftytotalmarket --years 12 [--skip-existing]`
- **Ingest fundamentals:** `python scripts/ingest_fundamentals.py f1.xlsx f2.xlsx f3.xlsx`
- ⚠️ **DuckDB is single-writer.** Host CLI jobs that WRITE the DB (load/ingest/seed) conflict with the
  running api container. Pattern: `docker stop windfall-api` → run the job → `docker compose up -d --build`.
  pytest is safe anytime (uses a temp DB). Read-only host queries while api is up will error — read via the API.

## Current data state (2026-06-20)
- **Prices:** 1,505 NSE tickers, daily adjusted OHLCV, 2014-06 → **2026-06-18** (last close). DuckDB at `backend/data/windfall.duckdb`.
- **Fundamentals (Trendlyne snapshot):** 1 snapshot dated **2026-06-18**, 1,138 stocks (DVM scores, PE/sector-PE, PB, EPS growth, ROE, Piotroski, promoter pledge/holding, qtr growth, relative strength).
- **Fundamentals (screener.in history):** point-in-time annual 2006→2026 in `backend/data/screener_fundamentals.duckdb`. **633 names** from the niftytotalmarket run (552 high / 80 low / 1 quarantined; 121 financials excluded; 0 failed). NOTE: niftytotalmarket and the Trendlyne-1138 universe overlap only on **287**, so the usable **Trendlyne ∩ screener = 238**. A scrape of the **674 genuine-company gap** (`data/genuine_674.csv`, classified in `data/missing_screener.csv`) ran 2026-06-20 to widen this toward ~900.
- **Universes:** `nifty500` (504), `niftytotalmarket` (~754), `trendlyne` (the 1138 fundamentals stocks), `allnse` (full EQUITY_L, load on demand).
- **DVM validation vs Trendlyne (snapshot 2026-06-18, Spearman):** momentum **0.835**, durability **0.546**, valuation **0.407** (v1: PEG + blend-bug fix, commit 28dc401). Valuation v2 (historical-multiple percentile) and a durability ROCE/D-E add are the next correlation lifts.
- **Refresh cadence (agreed):** prices nightly after close; fundamentals monthly re-export (each export = a new point-in-time snapshot → builds backtest history forward). Corporate-action logs: skip (adjusted prices suffice). Point-in-time index membership: only as part of survivorship work.

## What's built (done)
Data pipeline · vectorized indicators · declarative strategy schema (safe AST evaluator, no `eval`) ·
backtest engine (next-open fills/no-look-ahead, costs+slippage+turnover, stops/targets/trailing/time,
ADTV sizing, sector cap, **regime filter**, **invest_fully**) · validation harness · walk-forward +
sweep · live signals (+CSV, freshness, regime state, no-stop warning) · paper-trade book ·
**fundamentals/DVM point-in-time** · cockpit dashboard · Authentik-gated remote access.

**Saved strategies:** `momentum-regime` (CAGR 11.6% / maxDD −28% / Sharpe 0.71 — the good one),
`dvm-monthly` (live DVM screen — 10 picks today; backtest is flat by design, snapshot-only),
`momentum-v22`, `breakout-val` (the "junk" baselines the platform correctly flags).

## What's pending (build next — priority order)
1. **Full percentile-blend DVM ranker** — make `dvm_monthly` faithful to methodology v2.2 (percentile-rank
   each factor within survivors, weighted blend), instead of single-factor `roc125`. Needs a new ranking
   primitive in the engine (cross-sectional percentile at each rebalance).
2. **Survivorship-free history** — NSE Bhavcopy ingestion + point-in-time index membership. Removes the
   optimistic bias; until then every backtest CAGR is a ceiling.
3. **Fundamentals history** — auto-save each monthly Trendlyne export as a dated snapshot + a scheduled
   reminder; over time enables real fundamental *backtests* (not just live screens).
4. **Scheduled auto-refresh (nightly)** — add an API-triggered refresh endpoint that runs in the uvicorn
   process (avoids the single-writer DB conflict) + a cron that curls it after close. Wire `scripts/nightly.py`.
5. **Trendlyne parity (small):** quarterly rebalance · multi-key ranking (rank by A, tie-break B) ·
   **max-weight-per-stock cap**.
6. **Comparison/insight views:** cost-sensitivity (re-run at 0/1×/2× costs) · A/B strategy comparison.
7. **Filter-parity review:** the owner is running this repo + the prior chat through a second AI agent to
   diff our filters against Trendlyne's. Ingest that critique; any missing field is a one-line add to the
   `_MAP` in `backend/windfall/data/fundamentals.py` (it's already in the export files).
8. **Later phases:** alerts delivery (Telegram/email) · broker order-prep (Kite) — staged, manual-confirm,
   never auto-fire · intraday/F&O (needs intraday data + a live feed).

## Known limitations (be honest about these)
- **Fundamentals are a single snapshot** → DVM strategies are *live-signals* only; historical fundamental
  backtests are gated to NaN before 2026-06-18 by design (no look-ahead). Fixed by item #3 over time.
- **Survivorship:** current-membership universes only (item #2).
- **DVM rank** is single-factor momentum, not the full percentile blend (item #1).
- **No app login** — protected only by Authentik SSO at the edge (ADR-005/007). Don't remove the SSO gate.

## How to start next session
1. `/ottomate windfall-labs` — loads state + surfaces the open to-dos (mirrors of the list above).
2. Feed in the second AI agent's filter-parity critique.
3. Pick from the pending list (owner wants 1–5 built; 1 and 2 are the highest-leverage).
