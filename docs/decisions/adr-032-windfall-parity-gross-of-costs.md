# adr-032 — Trendlyne parity is gross-of-costs; net divergence on high-turnover is by design

- **Status:** accepted
- **Date:** 2026-06-25
- **Tags:** curated · cat:reliability
- **Context:** Session 2 backtest re-validation (`docs/validation/parity_round2_run-2026-06-25.md`), 13 Trendlyne backtests re-run on the post-audit data layer.

## Context

We re-validated 13 owner-run Trendlyne backtests (DVM, value, pure-technical, mean-reversion,
and the 10-filter v2.2 compound screen) against our engine. Two things had to be reconciled:
how closely we reproduce Trendlyne, and *why* our headline returns differ where they do.

## What we found

**Trendlyne's reported returns are gross — there is no cost or slippage in them.** This is not
assumed: our engine, pricing Trendlyne's *own* per-period picks (`gold@ourpx`), reproduces
Trendlyne's reported NAV to a **median 0.003pp** per stock-period with no systematic wedge
(e.g. 547989: our gold@ourpx 117.4 vs Trendlyne 117.4, exact). If Trendlyne deducted costs,
that reconciliation would carry a turnover-proportional gap. It does not.

Our engine, by contrast, deducts the full NSE delivery cost model (adr-020: side-aware
brokerage + STT + flat DP, no slippage) on every entry and exit. The consequence is
turnover-dependent:

| strategy class | turnover (ann.) | Trendlyne gross | our net | cost effect |
|---|---|---|---|---|
| monthly DVM (548012/15/17) | ~850% | +15–18% CAGR | +15–17% CAGR | immaterial |
| **weekly breakout (548042)** | **2706%** | **+24.9% total** | **−2.0% total** | **decisive** |
| weekly v2.2 (547989) | 2564% | +17.4% | +6.6% | large |

## Decision

1. **Parity is validated on GROSS selection + pricing**, which reconcile tightly (70–91% pick
   overlap on in-horizon tests; 0.003pp pricing). Trendlyne's gross numbers are a *selection/pricing*
   reference, **not a net-return target to match.**
2. **Net-of-cost divergence on high-turnover strategies is the intended, correct behavior** of a
   cost-realistic engine — and is the platform's core value proposition. A weekly screen that looks
   excellent gross on a screener can be flat-to-negative once realistic costs hit 2500%+ turnover;
   surfacing that *before* capital is risked is the entire reason this tool exists.
3. We will **not** "fix" the engine to chase Trendlyne's gross headline numbers, and future
   re-validations should compare net-of-cost results only against gross Trendlyne with this wedge in
   mind.

## Consequences

- Backtest and live-signal reporting always shows costs + turnover alongside returns (already true).
- The re-validation report records, per test, Trendlyne gross → our gross → our net so the cost wedge
  is explicit and attributable.
- Related: adr-020 (cost model), adr-008 (reporting honesty), adr-015 (PIT ≥₹500cr universe — the
  *other* deliberate divergence from Trendlyne's no-floor microcap screens).
