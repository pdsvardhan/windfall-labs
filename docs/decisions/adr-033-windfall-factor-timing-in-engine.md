# adr-033 — Factor-timing built in-engine on a reference equity curve, and the offline PoC's "free" drawdown protection does not survive real costs

- **Status:** accepted
- **Date:** 2026-06-26
- **Tags:** curated, cat:reliability
- **Iteration:** iter-16 (Phase A, task 1 of the roadmap-to-real-money)

## Context

An offline proof-of-concept had suggested that "factor-timing" — holding a strategy's book only while
its own equity is above its N-day moving average (MA100 the sweet spot) — would roughly halve max
drawdown, add +0.3–0.5 Sharpe, and cost almost nothing in CAGR, mostly turning the 2024–26 factor
winter positive. That PoC was computed on **stored equity curves with no transaction costs and no
execution lag**, and was explicitly flagged as optimistic. Phase A task 1 was to build it into the
engine with real switching costs and next-open fills, then walk-forward it.

## Decision 1 — Time on a *reference* equity curve, not the gated equity

The gate times on the strategy's **reference equity** — the same strategy run with factor-timing
**off** (regime/costs/everything else unchanged) — not on the realized (gated) equity.

Timing on the gated equity is self-referential: de-risking changes the very curve that drives the
next decision, producing non-monotonic, hard-to-reason behaviour (an early test showed enabling the
weekly check *raised* aggregate exposure). It also would not match what the PoC measured. The
reference curve is look-ahead-free and truncation-invariant (the gate reads it only at `t − lag_days`),
mirrors the existing `RegimeFilter` (which reads the benchmark), and is live-tractable because the
signals engine produces the book daily even while standing in cash. Defensive moves route through the
normal rebalance open/close machinery, so real sell + DP + re-buy costs and next-open fills apply.

## Decision 2 — Finding: the PoC's benefit does NOT survive real execution

Validated in-engine on the survivorship-free Trendlyne layer, 6M/12M momentum sleeve
(`roc252`, monthly, n=10, ADTV floor), 2016-06 → 2026-06:

| | Plain | + binary MA100 cash overlay |
|---|---|---|
| CAGR | 38.7% | **18.4%** |
| Sharpe | 1.26 | **0.83** |
| MaxDD | −49.5% | −46.3% |
| Exposure | 98% | 60% |

(Result holds at ₹1L and ₹10L, so it is not a flat-DP-fee artifact.) The binary MA100 cash overlay at
**monthly** cadence cuts ~15–20pp of CAGR and lowers Sharpe for only a few points of drawdown relief —
the opposite of the PoC's "near-free, +0.5 Sharpe, half the drawdown."

Root cause: the PoC assumed frictionless flips and fast re-engagement. In-engine, exposure sits at
~60% and the gate only re-enters at the **monthly** rebalance, so it stands in cash through the sharp
recoveries that cluster right after momentum bottoms — which is where momentum makes its money. A
market-direction-style overlay applied at the holdings cadence is too slow to add value here.

Walk-forward of `factor_timing.ma_period` ∈ {50,100,150,200} (4y IS / 2y OOS) returns verdict
**robust** (OOS/IS ≈ 0.69) but the best lookback drifts (50 in early windows → 100 later) and the two
most recent OOS windows are flat/negative — consistent with the ongoing factor winter. So the overlay
is not curve-fit, but it is also not the free lunch the PoC implied.

## Consequence

- Factor-timing (`FactorTiming`), the weekly de-risk check (`check_weekly`), and a fund-of-funds
  `rotation` module (`POST /api/rotation`) are now first-class, look-ahead-safe engine features.
- The "deploy MOM_roc252 + MA100" front-runner from the strategy-search phase is **demoted**: the
  MA100 self-timing does not earn its CAGR cost at monthly cadence. Do **not** ship it as-is.
- Open question for a follow-up iteration: faster **re-engagement** (evaluate the gate for entry as
  well as exit on a weekly cadence, or a scale-mode overlay), and a genuinely complementary
  (value/defensive) sleeve so rotation has uncorrelated material to rotate between. Rotation across
  two correlated momentum sleeves already improved drawdown (−34.8% vs −46/−49% standalone), but real
  rotation value needs uncorrelated sleeves.

## Anti-gaslight note

This ADR records a result that **refutes** a prior internal claim. The whole point of building the
PoC in-engine was to find exactly this — the offline number was optimistic, and the realistic engine
says so.
