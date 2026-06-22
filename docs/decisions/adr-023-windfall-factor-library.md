# ADR-023 — Curated Trendlyne factor library + point-in-time market-cap filter + negative-PE guard

**Status:** accepted · **Date:** 2026-06-22 · iter-32

## Context
A Trendlyne-parity backtest (548012, validated to ±5.5pp) and a filter-catalog audit surfaced three
gaps: (1) the engine exposed only a thin slice of the data already sitting in `trendlyne.duckdb`;
(2) there was **no historical market-cap filter**, so Trendlyne `Market Capitalization` bands could
not be reproduced (only the ₹500cr universe floor existed); (3) `PE_TTM`/`PEG_TTM` are negative for
loss-makers, so a `tl_pe < N` "cheap" filter silently admitted loss-makers and an ascending sort
ranked them first (caveat #7).

## Decision
1. **Negative/extreme-PE guard** — `valuation_panel` masks `PE_TTM`/`PEG_TTM` ≤ 0 → NaN (PBV left
   intact). Loss-makers are no longer "cheap" for filtering or ranking.
2. **Point-in-time, survivorship-free `mcap` feature** — reads `universe_membership.mcap_cr` (live +
   delisted), so `mcap > 1000 / < 50000` bands are reproducible over history, not just at the snapshot.
3. **Curated factor library** (data was already harvested, just unwired) — 13 result-lag-gated
   factors, no look-ahead: `tl_roic, tl_eyield, tl_ps, tl_current_ratio, tl_quick_ratio,
   tl_int_cover, tl_cfo, tl_piotroski, tl_np_growth, tl_rev_growth` (annual/quarterly) +
   `tl_pledge, tl_fii, tl_dii` (shareholding, 2023+). `tl_eyield` rescaled ×100 to a percentage.
   The previously-hidden `tl_opm`/`tl_eps` were added to the catalog; the snapshot-only
   `piotroski`/`promoter_pledge` builder entries were replaced by the result-lagged `tl_*` versions
   (a footgun: snapshot factors silently no-op in historical backtests); `eps_growth` is marked live-only.

## Consequences
- Far richer screening vocabulary that maps cleanly onto Trendlyne's filters; mcap bands now backtest.
- All new fundamentals are point-in-time via the `result_lag` join (independently verifier-confirmed:
  e.g. `tl_roic`/360ONE period-end 2018-03-31 → first visible 2018-05-15). No survivorship or look-ahead.
- `tl_pledge/fii/dii` are NaN before 2023 (shareholding history span) — they fail filters before then.
- Deferred: dividend yield (`DIV_A` units ambiguous), the long tail of ~35 niche `ratios_annual` codes
  (addable in minutes via the same `_RAW_FUND` map). Independent verifier: APPROVE.
