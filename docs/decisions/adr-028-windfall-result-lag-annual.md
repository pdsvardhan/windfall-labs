# adr-028 — Point-in-time fundamentals: 60-day annual / 45-day quarterly result lag

**Status:** accepted · **Date:** 2026-06-24 · **Source:** data audit 2026-06-24, finding F2

## Context
`result_lag` makes period-end fundamentals readable only from their real announcement date (`available_from`), so a backtest never sees a result before it was public (no look-ahead — the platform's #1 principle). When no real board-meeting date is matched in `result_dates` (72% of rows — mostly older periods), the builder fell back to a flat `period_end + 45 days`. 45 days is the SEBI LODR deadline for UNAUDITED quarterly results, but AUDITED ANNUAL results have a 60-day deadline and empirically land at a median of 48 days (p90 59d). So a flat 45-day fallback made unmatched annual fundamentals (which feed tl_roe, tl_roce, tl_de, tl_opm, tl_roic, tl_cfo, tl_piotroski, …) visible ~15 days too early — a mild but real look-ahead.

## Decision
Make the fallback period-type-aware in `phase3_build.py`: a period-end that appears in `pnl_annual` (a fiscal-year-end) gets **+60 days**; a pure quarterly period-end gets **+45 days**. Real matched board dates are unchanged.

## Consequences
- Closes the annual look-ahead window; aligns with SEBI LODR Reg 33.
- Empirically 60d covers ~99% of real annual announcements, so it is conservative, not overly tight.
- Rebuild also refreshed coverage of the most recent annuals (incidental F8 fix).

## Verification
After rebuild: every unmatched annual row lag = 60 (12,184 rows), every unmatched quarterly = 45 (29,076); matched rows still use real dates; zero negative lag.
