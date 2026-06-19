# Windfall Labs — Iteration Log

## Session 2026-06-19 — review remediation + data-sourcing phase

**Stage:** Stage 4 (iterate) — five iterations + three data-source spikes
**What changed (all verifier-APPROVED, integrated, mirrored):**
- **iter-21 (P0):** dropped DUMMYALCAR.NS; suppressed `active_return` on 0-trade/~0-exposure runs (the "+8.71% on 0 trades" trap); added `backend/scripts/data_audit.py`; cockpit snapshot-staleness banner + monthly host cron.
- **iter-22 (engine fidelity):** quarterly rebalance; multi-factor percentile-blend ranker (`rank_blend`, blank-tolerant); max-weight-per-stock cap; per-strategy data-readiness verdict. Covers every Trendlyne backtest control + more.
- **iter-23 (own DVM):** `windfall/scores/own_dvm.py` reproducible Durability/Valuation/Momentum + validation harness vs Trendlyne snapshot (Spearman: Momentum 0.835, Durability 0.546, Valuation 0.211).
- **iter-24 (Bhavcopy):** `backend/scripts/bhavcopy_ingest.py` — NSE Bhavcopy → standalone `data/bhavcopy.duckdb` (survivorship-free, ISIN-keyed, UDiFF+legacy, ONE-DOOR-safe).
- **iter-25 (surveillance):** `windfall/data/surveillance.py` — NSE ASM/GSM flags, in-process ingest, annotates live signals + warns (5/10 dvm_monthly picks flagged ASM on first run). Daily 9am cron.

**Data-source spikes:** Bhavcopy ✅ (built), ASM/GSM ✅ (built), EODHD ❌ (free key = no India/no fundamentals; paid+quality-doubtful), screener.in ✅ (12yr annual financials, free, parseable; our ratios verified — RELIANCE ROE 9.6%, D/E 0.44).

**Decisions:** ADR-008..012 (curated). Build our own reproducible DVM; survivorship via Bhavcopy in a standalone store; ASM/GSM as a pre-deploy guardrail; historical fundamentals via screener.in.

**Tests:** 34 → 60 passing.

**Left running:** Bhavcopy full backfill (2010→2026) detached on the server (`/tmp/bhavcopy_backfill.log`); resumable.

**Next session pick-up:**
1. After Bhavcopy backfill completes: corporate-action adjustment → point-in-time index membership → **wire survivorship data into the engine** (the big trust unlock).
2. Build `screener_fundamentals.py` (per-company fetch+parse → point-in-time financials → compute own Durability/Valuation history → validate vs Trendlyne snapshot on the ~1,138 overlap stocks). Lag annual ~3mo post-fiscal-year (no look-ahead). lxml already in venv.
3. Then user's sequence: detailed data verification → replicate 1-2 Trendlyne backtests in-engine & compare.

**Known pre-existing:** anti-gaslight "unclaimed-done" on cockpit-dashboard (+1) — original Stage-3 features marked done before ledger writes existed; not from this session.

## Session 2026-06-19 (cont.) — iter-26: screener.in historical fundamentals

**Stage:** Stage 4 (iterate) — historical-fundamentals sourcing, validation & ingestion
**What changed (ADR-013, verifier-APPROVED report #202, feature-claim #70 reconciled):**
- **Validated screener.in** as the historical-fundamentals source via a three-way triangulation (screener × yfinance × Trendlyne) over 21 stocks: raw lines 97–99% vs Trendlyne gold, computed ROE 97%, ~6 bounded failure classes that **converged** (+9 diverse stocks added zero new classes). Decision: **GO**.
- **Built `backend/windfall/data/screener_fundamentals.py`** — standalone `data/screener_fundamentals.duckdb`, six handling rules: (1) symbol→slug direct-first with screener search-API fallback + NSE-symbol verify; (2) financials excluded (sector + schema); (3) Net Profit → owner-attributable via yfinance overlap; (4) split-adjusted per-share; (5) period-end-date keying; (6) ratios computed from raw lines. Self-check (Layer-1 identity + soft yfinance cross-vote) → high/low/quarantined/excluded.
- **Ran the full nifty500: 402 tickers, 4,159 rows, 2005–2026** (368 high · 32 low/review · 2 quarantined; 92 financials excluded; 1 failed). Batch-1 deep verify vs yfinance = 40/40 clean (assets 100%, rev 99%, cfo 98%); across all 402, assets agreed ~99.5%.
- **Key finding:** yfinance is **unreliable for Indian revenue** (INFY ≈ ₹1,928 Cr vs screener's correct ₹162,990 Cr, ~85× off) — so the yfinance cross-vote was demoted to a **soft review flag**; screener is the more reliable source. Hard quarantine now only from the NSE-symbol mapping guard + Layer-1 identity.

**Decisions:** ADR-013 (screener.in historical fundamentals, triangulation-validated, cat:reliability). Financials excluded from the fundamental-DVM (user decision).

**Open bugs/items:** VAML ZeroDivisionError (1 stock); IDEA (Vodafone Idea) screener slug unresolved (search resolves to IdeaForge → MAP-MISMATCH-quarantined); ABB short consolidated history (4p).

**Next session pick-up:**
1. Fix the 3 open items (VAML divide-by-zero, IDEA slug, ABB short history).
2. Run the wider **trendlyne universe (1,138)** — needs a ONE-DOOR-safe symbol export (not via opening windfall.duckdb).
3. **Wire `fundamentals_history` into the engine** (point-in-time, ~3mo fiscal lag) → own Durability/Valuation over history.
4. Then the user's sequence: detailed data verification → replicate 1–2 Trendlyne backtests in-engine & compare.

**Commits:** 318a18c (ingester + ADR-013), f0174da (direct-first + 3 batch fixes), a9f9693 (soft yfinance cross-vote).
