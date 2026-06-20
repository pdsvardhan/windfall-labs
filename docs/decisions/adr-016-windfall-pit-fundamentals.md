# ADR-016: Point-in-time fundamentals via result-announcement lag

Status: accepted
Date: 2026-06-20

## Context
Fundamentals are stamped at period-end but announced weeks later; using them on the
period-end date is look-ahead bias. The engine previously applied a blunt fixed 120-day
lag to all fundamentals.

## Decision
Build `result_lag` (pk, period_end, available_from): the real board-meeting/result date
from Trendlyne `result_dates` where available, else `period_end + 45 days` (the SEBI
quarterly-filing deadline) as a conservative fallback. Earnings-derived fundamentals are
readable only on/after `available_from`.

## Consequences
- Matched-lag median is 39 days (p10 22 / p90 55) vs the old blunt 120 — fundamentals
  become usable as soon as they were genuinely public, with no look-ahead.
- Cross-source validation: Trendlyne vs our screener.in scrape agree to 0.09% (owner net
  profit) and 1.57% (revenue) median over 8,070 stock-years; outliers are the known PSU
  gross-vs-net cases (MMTC).
- Share count is public on the corporate-action ex-date, so `pit_mcap` shares are NOT
  lagged — only earnings-derived factors use `result_lag`.
- Script: `backend/scripts/phase3_build.py`. Validation: `backend/scripts/phase3_reconcile.py`.
