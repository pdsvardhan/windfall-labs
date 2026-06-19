# ADR-010 — Build our own reproducible D/V/M, validated against Trendlyne

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #23

## Context

The platform's strategies lean on Durability/Valuation/Momentum scores. Trendlyne's DVM is
proprietary and only one current snapshot is held, so DVM strategies are live-only and not
backtestable. Sourcing Trendlyne's *historical* DVM is either paid (Excel Connect) or impractical
to extract by hand, and either way it would leave the core scores a black box we don't own.

## Decision

Compute our **own** Durability / Valuation / Momentum scores from data we hold, with a transparent
formula, and **validate against Trendlyne's snapshot** to verify and tune — rather than license
Trendlyne's history.

- Each score is a cross-sectional percentile blend scaled 0-100 (higher = better), with weights
  that are explicit, tunable knobs (`scores/own_dvm.py`).
- **Momentum** is 100% price-derived (3/6/12-month returns, RSI, relative strength) → **fully
  backtestable over the entire price history today**.
- **Durability** (ROE, ROA, Piotroski, operating margin, profit growth, low pledge) and
  **Valuation** (cheapness vs peers/sector, loss-makers excluded) derive from fundamentals →
  point-in-time, snapshot-gated, and the data-readiness gate flags strategies that depend on them.
- A validation harness rank-correlates (Spearman) our scores against Trendlyne's on the snapshot.

## Consequences

- The scores are **reproducible, transparent, and owned** — no vendor lock-in, consistent with the
  platform's "deterministic, reproducible runs" principle.
- First-pass validation (2026-06-18 snapshot): **Momentum 0.835** (effectively tracks Trendlyne and
  is backtestable now), **Durability 0.546** (a workable proxy — improves once Debt/Equity and ROCE
  are added to the export), **Valuation 0.211** (weak by design — Trendlyne's valuation is "vs
  5–10-year history" + EV/EBITDA, which needs historical fundamentals). The correlations are the
  tuning signal; weights are tuned against multiple snapshots over time to avoid overfitting one.
- Durability/Valuation become historically backtestable once point-in-time fundamentals are sourced
  (or accrue forward via monthly snapshots); Momentum already is.
