# ADR-007 — Fundamentals via Trendlyne snapshots, point-in-time and snapshot-only

**Status:** accepted · **Date:** 2026-06-19

## Context
The strategy that actually works for the owner is a DVM/fundamental monthly rotation, which the
platform could not express because only price data existed. The owner provided Trendlyne Pro "Data
Downloader" exports — multiple column groups (DVM scores, valuation, quality, shareholding,
quarterly financials), merged on NSE Code, ~1138 screened stocks per snapshot.

A Trendlyne export is a **snapshot**: it is today's fundamentals, not a historical point-in-time
series. Trendlyne does not expose historical DVM/fundamentals in bulk. Using a single snapshot as if
it applied to past dates would be look-ahead bias.

## Decision
- Ingest snapshots into a `fundamentals` table keyed `(ticker, snapshot_date)`, with `reporting_date`
  (the result-announced date) retained. Snapshot date defaults to the latest price bar so live
  signals pick the fundamentals up.
- Expose fundamentals as resolver features: `durability`, `valuation`, `momentum_score`, `pe`,
  `sector_pe`, `pe_to_sector`, `pb`, `roe`, `roa`, `eps_growth`, `piotroski`, `promoter_pledge`,
  `promoter_holding`, `np_qtr_yoy`, `rev_qtr_yoy`, `mcap_cr`, `rs_nifty_1m/3m`, `rs_sector_1m/3m`.
- **Point-in-time read:** at backtest date `t`, a fundamental feature uses the latest snapshot with
  `snapshot_date <= t`; before the first snapshot it is **NaN**, so fundamental filters correctly
  fail (no look-ahead). With one snapshot, fundamental strategies are therefore **live-signals
  strategies** — a historical backtest is gated to empty by design, and the resolver emits a warning
  saying so. As the owner re-exports over time, history accumulates forward and backtests become
  possible.
- `exclude_sectors` added to the universe (substring match) to express "exclude Banking & Finance".
- The tradeable universe for a fundamental strategy is the set of snapshot stocks that also have
  price data; their prices are loaded into a `trendlyne` universe.

## Consequences
- The owner can finally run the DVM screen for **today's orders** (the real goal) on ~1138 stocks.
- Backtesting the DVM strategy historically waits on snapshot accumulation (or a future point-in-time
  fundamentals source) — the platform is explicit about this rather than silently optimistic.
- The full percentile-blend scoring of methodology v2.2 is not replicated in a single rank expression;
  v1 screens on the fundamental filters and ranks by price momentum (`roc125`).
