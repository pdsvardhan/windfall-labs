# ADR-008 — Suppress "active return" when a strategy holds cash

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #21 (P0 review remediation)

## Context

A June-2026 review caught a reporting trap: the `dvm_monthly` strategy showed
**active return +8.71%** while making **zero trades**. It hadn't beaten anything — it
sat entirely in cash during a window when the index *fell* ~8.7%, and "your CAGR (0%)
minus the benchmark's (−8.7%)" mechanically produced a positive number. Anyone glancing
at the metric could conclude the screen beat the market by ~9%. It did not.

This is exactly the class of optimism the platform exists to refuse: a number that reads
as alpha but is an artifact of *not being invested*.

## Decision

Active return is only reported when the strategy actually took exposure. When a backtest
makes **0 trades** or holds **< 1% average exposure**, `active_return` is set to `null`
and carries an explicit reason (`active_return_note`: "no exposure (held cash) — not
comparable to benchmark"). The cockpit renders it as "not comparable" rather than a
green outperformance figure. `benchmark_cagr` is still shown — the index's own return is
a fact; the *comparison* is what's withheld.

## Consequences

- A do-nothing run can no longer masquerade as a winner. The suppression is covered by
  two regression tests (`test_active_return_suppressed_when_no_exposure`,
  `test_active_return_reported_when_invested`).
- The normal path is unchanged: an invested strategy (e.g. `momentum_regime`, 55%
  exposure) still reports its true active return (+0.73%/yr).
- `Summary.active_return` is now `Optional[float]`; the API contract, TypeScript types,
  and UI were updated to treat `null` as "not applicable".

Part of a broader stance — realism over optimism, honest metrics — alongside no
look-ahead, modelled costs, and survivorship caveats.
