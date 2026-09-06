# Trendlyne Data Downloader — exact columns to export

The runbook said "same column-groups as last time", which is not actionable 80 days later.
These are the **25 headers the ingest actually matches**, read from
`backend/windfall/data/fundamentals.py:_MAP` (exact-name match, first occurrence).

Tick these in the Data Downloader. Anything else you export is ignored — harmless, just noise.
Anything on this list you *miss* silently becomes NaN for that snapshot.

| # | Trendlyne column header (exact) | Lands in |
|---|---|---|
| 1 | Trendlyne Durability Score | `durability` |
| 2 | Trendlyne Valuation Score | `valuation` |
| 3 | Trendlyne Momentum Score | `momentum_score` |
| 4 | Normalized Momentum Score | `norm_momentum` |
| 5 | PE TTM Price to Earnings | `pe` |
| 6 | Forecaster Estimates 1Y forward PE | `fwd_pe` |
| 7 | Sector PE TTM | `sector_pe` |
| 8 | Industry PE TTM | `industry_pe` |
| 9 | Price to Book Value Adjusted | `pb` |
| 10 | Basic EPS TTM | `eps_ttm` |
| 11 | EPS TTM Growth % | `eps_growth` |
| 12 | ROE Annual % | `roe` |
| 13 | RoA Annual % | `roa` |
| 14 | Piotroski Score | `piotroski` |
| 15 | Market Capitalization | `mcap_cr` |
| 16 | Promoter holding latest % | `promoter_holding` |
| 17 | Promoter holding pledge percentage % Qtr | `promoter_pledge` |
| 18 | Relative returns vs Nifty50 month% | `rs_nifty_1m` |
| 19 | Relative returns vs Nifty50 quarter% | `rs_nifty_3m` |
| 20 | Relative returns vs Sector month% | `rs_sector_1m` |
| 21 | Relative returns vs Sector quarter% | `rs_sector_3m` |
| 22 | Net Profit Qtr Growth YoY % | `np_qtr_yoy` |
| 23 | Revenue Growth Qtr YoY % | `rev_qtr_yoy` |
| 24 | Operating Profit Margin Qtr % | `opm` |

Plus the join key, always present in an export: **NSE Code**.

## Notes

- **#6 `Forecaster Estimates 1Y forward PE` is the one to-do #26 asked for** — the valuation DVM
  is stuck at a 0.44 correlation ceiling because forward-PE was missing from the old export.
  Do not skip it.
- Export in whatever column-group splits the downloader gives you — the ingest merges multiple
  `.xlsx` files on NSE Code, so 3 files or 6 files both work.
- Universe: same `mcapq > 500` screener filter as the harvesters, so the snapshot covers the
  names the engine actually trades.
- The snapshot date is the **export date**, passed as `--snapshot YYYY-MM-DD`. Snapshots
  accumulate; history builds forward. Nothing is overwritten.
