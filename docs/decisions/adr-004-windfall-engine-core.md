# ADR-004 — Backtest core: vectorbt over a hand-rolled simulator

**Status:** accepted · **Date:** 2026-06-19

## Context
A home-built simulator is easy to get subtly wrong (fills, cost accounting, corporate actions).
The Build-Spec recommends not building the simulation core from scratch.

## Decision
Use **`vectorbt`** for the portfolio simulation core (vectorized, native stop/target support,
rich metrics), and own the layers around it: data ingestion, the declarative strategy layer,
sizing/ADTV caps, and the reporting/IO wrapper.

We implement a **rebalance-and-hold simulator** on top of vectorbt's portfolio primitives:
at each rebalance date we compute signals from data up to that date only, rank, take the top-N,
size within ADTV caps, enter at next-bar open net of costs, and check stops/targets/trailing/
time-exits daily between rebalances.

`backtrader` remains the documented escape hatch for strategies that need fully event-driven,
path-dependent exit logic that doesn't vectorize cleanly.

## Consequences
- Fewer simulation bugs; fast enough to sweep many variants for walk-forward.
- Our own thin simulation wrapper is the part we must test hardest (no-look-ahead, costs, exits).
- Determinism is our responsibility: fixed sort orders, seeded tie-breaks, config-hash tagging.
