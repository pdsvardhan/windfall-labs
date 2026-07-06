# adr-037 — Live signals + paper trading made real: last-healthy-bar resolution, Trendlyne-based marking, and a 5-strategy paper dry-run

- **Status:** accepted
- **Date:** 2026-07-06
- **Tags:** curated, cat:reliability
- **Iteration:** iter-20

## Context

Starting the real-money path meant paper-trading candidate strategies live. Three things were broken
or missing, discovered on 2026-07-06:

1. **Live signals returned an all-SELL book for every strategy.** Root cause: the data layer is
   stale (`universe_membership` to 2026-06-24, `ohlcv` to 2026-06-16) while live prices splice
   forward (bhavcopy, adr-022) to the last trading day. `resolve()` gates eligibility on point-in-time
   membership with `fillna(False)`, so on the spliced tail `entry_mask` is empty — today's book
   resolves to nothing and the prior holdings all emit as "sell". Measured: entry_mask True=1701 on
   2026-06-25, **0** on 2026-07-02/03, with prices and rank scores fine.
2. **Paper mark-to-market never priced Trendlyne positions.** `_latest_close` queried the legacy
   yfinance `prices` table (`.NS` tickers), but strategies use the Trendlyne store (bare tickers),
   so P&L stayed 0.
3. **No paper-tracking surface and no automation** — the paper book lived only in the API.

## Decision

- **Live signals resolve as-of the last bar with a tradeable universe.** `generate_signals` walks
  `last_i` back while `entry_mask.iloc[last_i]` is empty, and warns when it backs off the true latest
  bar. Orders reflect a real book instead of an all-sell artifact; staleness stays visible.
- **Paper marking uses the engine's price series.** `_latest_close` now reads
  `adjusted_close_panel(..., extend_live=True)` (bare tickers + bhavcopy splice) — the same series the
  signals/backtests use, so entry and mark share one basis — with the legacy table as fallback.
- **A `/paper` cockpit page + a monthly rebalance job.** The page shows the 5-strategy scoreboard,
  per-position P&L, and an EOD-freshness banner. Crons: `windfall-paper-mark` (weeknights 20:40,
  after the EOD refresh) marks the book; `windfall-paper-rebalance` (1st of month) syncs each
  strategy's positions to its current top-N. `POST /api/paper/rebalance` and `/api/paper/purge`
  back these.

## Consequence

- The **5-strategy paper dry-run** is live (₹1L notional each): DVM_user, DVM_dm_m_20, BLEND_70_30,
  MOM_roc252_m_20, CMP_valmom_m_20 — entries as-of the last healthy bar (2026-06-29).
- **The one remaining manual step is the monthly Trendlyne data pull** (WAF-gated, in-browser).
  Until it is refreshed, rebalances run on the last-held data — the signals already warn about this.
- The blend at ₹1L is under-invested (~60%): 15 of 40 names round to 0 shares — a real small-account
  granularity effect, not a bug. A faithful blend needs ~₹5L or fewer names.
- The adr-035 70/30 headline (29.5% / 1.27 / −42.7%) does **not** trivially reproduce from the saved
  MOM_roc252/LV_atr sleeves today — live rotation gives 22.9–28.4% CAGR / Sharpe 1.09–1.24 depending
  on holdings. Flagged for a later parity pass; does not affect the paper dry-run.

## Anti-gaslight note

Both bugs were caught by refusing to trust a green-looking pipeline: the all-sell book and the
₹0 P&L were investigated to root cause (entry_mask counts, price-store mismatch) rather than
worked around. The fixes were verified end-to-end (real buys returned; 92 positions marked to the
current close) before being called done.
