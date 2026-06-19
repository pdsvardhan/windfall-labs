# ADR-006 — Build plan: validate before trusting, walk-forward before approving

**Status:** accepted · **Date:** 2026-06-19

## Context
The platform's value depends entirely on its results being trustworthy. Two failure modes dominate:
a silently-wrong engine, and a curve-fit strategy. Both have bitten this research before.

## Decision
Build and gate in this order:

1. **Data pipeline** — load Nifty 500 daily history into DuckDB (honest coverage reporting).
2. **Indicator library** — vectorized, each indicator unit-tested against a known value.
3. **Strategy config + engine** — declarative config → vectorbt simulation with costs/exits/ADTV.
4. **Validation harness (gate)** — reproduce a known Trendlyne breakout result with costs off;
   buy-and-hold sanity; indicator tests. The engine is **not trusted** until this passes (or the
   deviation is explained).
5. **Walk-forward + optimization (gate)** — no strategy is "approved" for live signals until a
   walk-forward shows acceptable in-sample vs out-of-sample degradation.
6. **Live signals + paper-trade** — generate today's orders; paper-track before any real capital.
7. **Cockpit dashboard** — render all of the above.

Alerts are scaffolded only (delivery deferred per owner). Broker execution, intraday and F&O are
explicit non-goals for v1.

## Consequences
- Slower to "first pretty chart," but the charts mean something.
- The validation and walk-forward steps are gates, not optional polish — a strategy that skips them
  is not eligible for the live-signals path.
