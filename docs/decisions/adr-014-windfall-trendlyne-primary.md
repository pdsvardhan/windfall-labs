# ADR-014: Trendlyne full-history as the primary data layer

Status: accepted
Date: 2026-06-20

## Context
The engine originally ran on yfinance prices + a single Trendlyne DVM snapshot + a
reconstructed "own DVM" validated against that snapshot (adr-010). A full in-browser
harvest of Trendlyne's `all-param-history` (WAF-gated, so collected in a logged-in
browser) then delivered the real history: daily DVM scores, PE/PEG/PBV, full annual
(2000+) and quarterly (2016+) statements, ownership, corporate actions, result dates,
and adjusted OHLCV — ~24.4M rows across 20 tables.

## Decision
Adopt Trendlyne full history as the **primary** price + fundamentals + DVM source,
loaded into a standalone, read-only `trendlyne.duckdb` (ONE-DOOR safe; never opens
windfall.duckdb). The reconstructed own-DVM (adr-010) is demoted to an optional
transparency/extension tool — we now hold Trendlyne's actual scores, so matching them by
reconstruction is no longer the critical path. The screener.in scrape (adr-013) becomes
an independent cross-check.

## Consequences
- Trendlyne adjusted OHLCV validated as canonical price vs official NSE Bhavcopy:
  99.44% of 3.63M stock-days agree within 0.5pp; every >10pp divergence is a corporate
  action. Trendlyne adjusts for splits AND bonuses (its own corp-actions table lists only
  bonuses/rights, but the prices are fully adjusted).
- Universe-completeness bug (found + fixed): the harvest initially excluded the top-100
  megacaps (RELIANCE/TCS/HDFCBANK…) because the screener *session* universe was
  "Others | Listed on NSE", which drops index constituents. Fixed by pulling the 100 by
  symbol->pk directly; universe 1,849 -> 1,949.
- Supersedes to-do #26 (lift own-DVM valuation) and #13 (accumulate monthly snapshots).
- Loaders: `backend/scripts/load_trendlyne.py`, `backend/scripts/load_v2.py`.
- Gotcha: the megacap merge mixed quoted/unquoted names -> DuckDB strict CSV parser
  fails; load with `strict_mode=false`.
