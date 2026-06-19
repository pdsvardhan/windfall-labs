# ADR-009 — Multi-factor blend ranking + per-strategy data-readiness

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #22 (engine fidelity)

## Context

Reference screener tools (Trendlyne) rank a screen by a *blend* of factors and rebalance at
weekly/monthly/**quarterly** cadence. Our engine could only sort by a single expression and had
no quarterly option, so the platform's "DVM" ranking did not match the actual methodology. At the
same time, fundamental factors come from point-in-time snapshots (one so far), so some strategies
are genuinely backtestable on history and some are live-only — and nothing in the engine made that
distinction explicit, which is precisely how a backtest can masquerade as validated when the data
isn't there.

## Decision

Two engine capabilities, designed to be honest by construction:

1. **Multi-factor percentile-blend ranking.** A strategy can rank by a `rank_blend` — a weighted
   set of factors. At each rebalance the engine percentile-ranks each factor *across that day's
   eligible names*, then weight-blends (higher = better). It is **blank-tolerant**: when a factor
   is NaN for a name (e.g. a fundamental before its snapshot) it is dropped and the remaining
   weights renormalize. So a price-only blend backtests over full history, and a blend that
   includes fundamentals automatically uses the full recipe live and gains backtest history as
   snapshots accumulate. The blend is computed in the resolver and flows through the existing
   `rank_score` panel — the simulator is unchanged. Quarterly rebalance and a max-weight-per-stock
   cap were added alongside, completing parity with the reference tool's controls.

2. **Per-strategy data-readiness.** Every strategy reports a verdict before it runs:
   *fully-backtestable* (price-only), *price-backtestable* (fundamentals only in the blend, which
   is blank-tolerant), or *live-only* (a fundamental appears in a hard filter, so a historical
   backtest holds nothing). The verdict is exposed at `POST /api/strategies/readiness` and attached
   to every backtest result.

## Consequences

- The engine now covers every Trendlyne backtest control (frequency incl. quarterly, blended
  ranking, max-weight) **and** the things Trendlyne lacks (modelled costs, explicit exits, no
  look-ahead, ADTV cap, regime overlay, walk-forward).
- A backtest can no longer quietly pretend to be validated when the data isn't there — the
  readiness verdict states it plainly. `dvm_monthly` is correctly labelled *live-only* (its
  durability filter is fundamental); the new price-only `momentum_blend` is *fully-backtestable*
  and trades over the full 11.5-year history.
- Ranking weights live in each strategy's config, not the engine — different strategies blend
  differently. Covered by 10 new tests (ordering preservation, blank-tolerance, quarterly,
  max-weight, the three readiness verdicts, end-to-end).
