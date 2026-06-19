# Windfall Labs

A private, web-hosted **quant research & execution platform** for systematic Indian (NSE)
equity strategies. Define a strategy once → backtest it over long history with realistic
costs → prove it isn't curve-fit (walk-forward) → get today's exact orders → paper-trade it
before risking capital.

> v1 is **signals-only** — the platform prepares orders; the human places every one.

## Principles (baked in)

1. **Realism over optimism** — model costs + slippage; report turnover prominently.
2. **Exits are first-class** — stops, targets, trailing, time-exits, not just rebalance rotation.
3. **No look-ahead** — point-in-time data, next-open fills, fundamentals lagged to publish date.
4. **Liquidity-aware** — never "trade" what you couldn't have bought/exited (ADTV filters + caps).
5. **Validate everything** — reproduce a known result before trusting the engine; walk-forward before trusting a strategy.
6. **Human in the loop** — v1 generates orders; the human places them.

## Architecture

A monorepo with a Python quant engine and a Next.js cockpit:

```
backend/    FastAPI + the `windfall` quant engine package (data, signals, strategy, engine,
            walk-forward, live signals, paper-trade). DuckDB store. CLI + HTTP API.
frontend/   Next.js (App Router, TypeScript) cockpit dashboard.
docs/       Architecture decision records (ADRs).
```

See `docs/decisions/` for the why behind the stack, data sourcing, and engine choices.

## Quick start (dev)

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/load_data.py --universe nifty500 --years 12     # load price history
python -m windfall.cli backtest strategies/breakout_validation.json
uvicorn app.main:app --host 0.0.0.0 --port 8503 --reload   # API listens on 8503

# frontend
cd frontend
npm install
npm run dev    # http://localhost:8500
```

## Docker (vault7a)

```bash
docker compose up -d --build      # web on :8500, api on host :8505 (container :8503)
```

## Status

Built through Ottomate Stage 3. v1 modules: data pipeline, indicator library, strategy config,
backtest engine, validation harness, walk-forward + optimization, live signals, paper-trade log,
cockpit dashboard. Alerts scaffolded (delivery deferred). Broker execution, intraday/F&O are
later phases.
