# ADR-002 — Architecture: monorepo with an importable quant engine, CLI and HTTP API

**Status:** accepted · **Date:** 2026-06-19

## Context
The same engine must be drivable three ways: by an assistant writing `config.json` files (CLI/batch),
by scheduled cron jobs (nightly data + signals), and by the cockpit UI (HTTP). Duplicating logic
across these would drift.

## Decision
One monorepo, one engine, three thin entry points:

```
backend/windfall/      the engine package — pure functions over data:
  data/      fetch (yfinance + fallback), DuckDB store, universe, ADTV
  signals/   vectorized indicator library
  strategy/  declarative config schema (pydantic) + resolver
  engine/    vectorbt simulation, metrics, results serialization
  walkforward/  parameter sweep + rolling walk-forward
  signals_live/ today's buy/hold/sell generation
  paper/     paper-trade book (mark-to-market)
  alerts/    rule engine (logs only in v1)
backend/app/           FastAPI routers — thin HTTP over the engine
backend/scripts/       load_data, run_validation, nightly  (CLI/cron)
frontend/              Next.js cockpit
```

The canonical contract is `run_backtest(config: StrategyConfig) -> BacktestResult`. CLI, API and
cron all call it. Results and strategies are persisted in DuckDB and addressable by id.

## Consequences
- Engine has **no** web or UI dependencies — testable in isolation, runnable headless.
- Adding a feature = add an engine function + (optionally) a router + a UI view; the seam is JSON.
