# ADR-013 — Historical fundamentals via screener.in, triangulation-validated

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #26

## Context

Our own DVM (adr-010) needs point-in-time *historical* Durability/Valuation inputs, but the only
fundamentals source so far is a single Trendlyne snapshot (adr-007) — today-only, so durability and
valuation are NaN before the snapshot date. To compute our own ROE/ROCE/PB/margin history and to
backtest fundamental screens, we need ~10+ years of annual financials per stock.

screener.in was chosen as the candidate source: free, public company pages, ~12yr annual
P&L / Balance-Sheet / Cash-Flow / Ratios + shareholding, parseable HTML (lxml). Before committing to
scrape ~1,100+ names, we ran a three-way verification (screener × yfinance × Trendlyne gold exports)
on 21 distinct stocks deliberately spanning the edge cases: bank, NBFC, holding company, recent IPO,
micro-cap, MNC-standalone, autos with finance arms, hospital chain, and a large-minority conglomerate.

## Decision

**Source historical fundamentals from screener.in, with a built-in triangulation self-check.**

Evidence (11 gold stocks × ~10yr, screener vs Trendlyne):
- Raw lines — Revenue 99% · Total Assets 98% · Equity 97% · Operating Profit 90% · CFO 86%.
- Computed ROE (from screener equity + owner-NP) 97% — Durability is faithfully reproducible.
- Data yield 90% of DVM-feeding cells trustworthy as-is.
- The failure space **converged** to ~6 classes; adding 9 diverse new names produced **zero** new
  classes — the issue list is bounded, not growing.

Source roles: **screener.in** = ingest source (12yr history); **yfinance** = automated independent
cross-check (reports owner-NP, ~4yr overlap, resolves restatements by 2-of-3 vote); **Trendlyne** =
high-precision gold calibration (manual, only for disputed cells).

Six handling rules baked into the ingester:
1. Symbol→slug via the screener search API + cache — never assume `symbol == slug` (e.g. TATAMOTORS→TMCV after the demerger).
2. Financials (banks/NBFCs) **excluded** from the fundamental-DVM (different statement schema; they keep price/Momentum only).
3. Net Profit → **owner-attributable** (subtract minority interest; screener's headline figure includes it).
4. EPS / per-share metrics → **split-adjusted** series, not raw-per-year.
5. Period keyed on the **actual fiscal period-end date** (handles non-March and FY changes); stub/transition periods dropped.
6. Ratios (ROE/ROCE/PB/D-E) **computed by us** from raw lines, not scraped; a promoter-less company = NA, not an error.

Per-stock self-check at ingest: Layer-1 accounting identities + a yfinance cross-vote. Any stock
breaching tolerance is **quarantined** (flagged, not silently ingested) before it reaches the engine.

## Consequences

- Free, reproducible ~12yr fundamentals history for the universe; unblocks fundamental backtests and
  our own point-in-time Durability/Valuation (adr-010).
- **CFO is the weakest line (~86%)** — it feeds only the low-weight cash-flow-quality signal; flagged low-confidence.
- Micro-caps (<₹500cr) and recent IPOs are noisier / short-history — largely outside the target
  ₹500–50,000cr universe; pre-listing scores correctly NaN (the data-readiness gate handles it).
- screener.in's ToS prohibits scraping; mitigated by polite, rate-limited, cached, personal-use
  automation. If screener access degrades, yfinance + Trendlyne Excel-Connect remain fallbacks.
- The self-check adds per-stock cost but is the anti-gaslight safeguard that turns a 1,100-stock
  scrape from a silent-error liability into a trustworthy, auditable pipeline.
