# ADR-003 — Data sourcing: yfinance first, Bhavcopy for survivorship-free history, behind a Phase-0 gate

**Status:** accepted · **Date:** 2026-06-19

## Context
The PRD makes **Phase 0 — data feasibility audit** a hard gate: prove each dataset is actually
obtainable before building on it. The owner approved loading "easily-available data we can source
ourselves" for the first build. A bare request to Yahoo Finance from the server already returned
**HTTP 429 (rate-limited)**, so the fetcher must be resilient, not naive.

## Decision
- **Primary (v1):** `yfinance` for adjusted + raw daily OHLCV of the Nifty 500 universe (`*.NS`),
  with a hardened fetcher: browser-like headers, exponential backoff on 429/5xx, small paced
  batches, and **aggressive local caching in DuckDB** (download once, reuse forever).
- **Fallback:** if yfinance is broadly blocked, a secondary adapter (stooq) fills daily OHLCV so a
  build is never fully blocked on one source.
- **Survivorship-free history (later phase):** NSE **Bhavcopy** archives, which retain delisted
  tickers — required before any result is trusted for delisting-sensitive strategies. v1 uses the
  current Nifty 500 membership and is explicitly **not** survivorship-free yet; this is recorded as
  an open risk and surfaced on the Data Status page.
- **Fundamentals / point-in-time index membership:** deferred — DVM/fundamental strategies wait
  until that data is sourced (Trendlyne Pro export or a one-time paid dataset).

## Consequences
- v1 backtests are honest about their universe limitation (current-membership, not point-in-time).
- The data layer reports **actual coverage** (tickers loaded, date span, gaps) rather than assuming
  completeness — anti-gaslight rule: report what was really fetched.
