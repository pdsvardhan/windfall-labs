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
