# ADR-011 — Survivorship-free prices via NSE Bhavcopy, in a standalone store

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #24

## Context

The engine's prices come from yfinance, which only carries *currently-listed* names. Every
backtest therefore picks from survivors — stocks that delisted, merged, or blew up over the period
are simply absent — which inflates returns (the review showed this can erase a strategy's whole
edge). Even Trendlyne's backtest is survivorship-biased ("current constituents applied throughout").
NSE's daily **Bhavcopy** lists every stock that traded each day, including names later delisted, so
its archives are a survivorship-complete price source — and it's free.

## Decision

Ingest NSE Bhavcopy into a **standalone `data/bhavcopy.duckdb`**, separate from the engine's
`windfall.duckdb`.

- **Separate DB is deliberate (ONE DOOR, adr-018):** the api container holds the single-writer lock
  on windfall.duckdb; a host backfill writing the same file would risk WAL corruption. bhavcopy.duckdb
  is untouched by the container, so a multi-hour backfill runs while the cockpit stays up.
- Handles both NSE formats (UDiFF from 2024-07-08, legacy before), is **ISIN-keyed** so symbol
  renames across history stay linked, filters to equity series, is holiday-aware, rate-limited, and
  resumable.
- Prices are stored **raw (unadjusted)**. Corporate-action adjustment, point-in-time index
  membership, and wiring this into the engine are deliberate *later* steps — this iteration is data
  collection only.

## Consequences

- We now have a survivorship-complete raw price store including delisted names — the foundation for
  trustworthy backtests, and a basis to be *more* rigorous than Trendlyne.
- It also repairs an existing data gap: the 599 last-bar NULL closes were yfinance's incomplete final
  fetch; Bhavcopy supplies those closes exactly.
- The data is not yet in the backtest path — until corporate-action adjustment + point-in-time
  membership land, every yfinance-based CAGR remains an optimistic ceiling, as before.
- Validated on ingest: universe grows 1,748 (Jan 2020) → 3,107 (May 2026); prices match yfinance
  within rounding (RELIANCE volume within 0.007%).
