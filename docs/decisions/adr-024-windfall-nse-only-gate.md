# ADR-024 — Hard NSE-only universe gate

**Status:** accepted · **Date:** 2026-06-22 · iter-33 · **amended by adr-050 (iter-204, 2026-10-20)**

> **Amendment (adr-050).** "Ever traded EQ" turned out to be a look-ahead: measured against NSE's
> official market cap it admitted ~95 companies per month-end before their first NSE bar and ~15 whose
> NSE line had gone idle. The gate is now **point-in-time and by company** (every ticker sharing an
> ISIN): a company counts on day d only if its first EQ bar is on or before d and it traded on the NSE
> mainboard (EQ/BE/BZ) within 90 days before d (`trendlyne_store.nse_gate_panel` / `nse_gate_at`).
> `_nse_symbols()` remains as the ever-EQ ticker set for diagnostics.

## Context
We target NSE-only strategies. But the investable universe (`universe_membership`) is gated purely on
**Trendlyne point-in-time market cap > floor** — with no exchange check. Trendlyne also scores AND
prices **BSE-only names** (on BSE closes via its `ohlcv`). An audit found **239 / 2,099 eligible names
(11.4%) have no NSE-traded presence** (zero NSE Bhavcopy turnover) yet were fully priced and therefore
*selectable* in a backtest — on BSE closes. They were only excluded by a strategy's own liquidity
filter (`adtv_cr > N`, which they fail with zero NSE turnover) or by ADTV position-sizing. So "NSE-only"
held by **user discipline, not by construction** — a silent footgun for any strategy without a
liquidity gate (it could hold a BSE-only name on BSE prices).

## Decision
Add `_nse_symbols()` (cached set of Bhavcopy `series='EQ'` tickers = real NSE-traded presence) and gate
the three universe primitives — `pit_universe`, `membership_panel`, `universe_over_window` — to it.
A name is eligible **iff it has NSE-traded presence.** NSE-only is now guaranteed by construction,
independent of any filter.

## Consequences
- BSE-only / non-NSE names can never be selected (verified: `universe_over_window` 0 non-NSE remaining;
  ACGL/ARTSON/ADCINDIA/ALPEXSOLAR excluded; RELIANCE/TCS retained). Universe ~1,860 NSE names.
- Drops only names we have **no NSE price/turnover** for anyway — i.e. names not realistically
  NSE-tradeable in our data. No loss of genuinely-tradeable coverage.
- Their Trendlyne factor rows remain in the DB (harmless, just never eligible); no data purge needed.
- Tests: `tests/test_iter33_nse_gate.py` (3). Orthogonal to the iter-32 factor library (all 6 still green).
