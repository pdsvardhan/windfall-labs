---
public: true
type: technical-deep-dive
title: Technical Deep-Dive — Windfall Labs
order: 2
summary: A hand-rolled survivorship-free simulator, DuckDB columnar data, and a point-in-time data layer.
read_minutes: 4
---

# Windfall Labs — Technical Deep-Dive

## Stack
A monorepo: a Python **FastAPI** backend wrapping an importable `windfall` quant-engine package, and a **Next.js 14** (App Router, TypeScript, Tailwind) cockpit. Data lives in **DuckDB** columnar stores — downloaded once, reused across runs with no re-fetch. The engine is reachable as both a CLI and a thin HTTP API; sync handlers run in the threadpool so a long backtest never blocks the event loop, and CORS is locked to the cockpit origin.

## How it works
A strategy is a declarative `StrategyConfig` (pydantic): universe, entry filters, rank expression or multi-factor blend, exits, sizing, rebalance frequency. The engine resolves it into aligned price/feature panels, then simulates: at each rebalance, decisions use only data up to that close, fills happen at the **next bar's open**, and between rebalances stops / targets / trailing / time-exits are checked daily. Costs are deducted on every entry and exit; turnover is always reported.

## Interesting decisions

**1. Hand-rolled simulator, not vectorbt (ADR-004 era, since diverged).** The plan was to build on vectorbt. In practice the engine is a from-scratch deterministic rebalance-and-hold simulator (`engine/backtest.py`); vectorbt is not a dependency. This put no-look-ahead, cost accounting, and exit logic fully under test — at the cost of owning correctness, the part that bit hardest (see the retrospective).

**2. Survivorship-free engine (ADR-018).** Backtests run against a point-in-time universe of every name ever above ₹500cr — live *and* delisted. A time-varying membership mask makes a name eligible only on dates it actually qualified; a delisted holding is force-closed at its last traded adjusted price. Blow-ups (RCOM, RELCAPITAL, JETAIRWAYS) and mergers (HDFC, RANBAXY) are deliberately *included* — excluding them is exactly the optimistic bias the platform exists to refuse.

**3. Accurate NSE cost model (ADR-020).** The real Zerodha-class delivery schedule: side-aware fees (~11.9 bps buy / ~10.4 bps sell from STT, stamp, exchange, SEBI, GST) plus a **flat ₹15.93 DP per sell**. The flat fee makes returns capital-dependent — small accounts bleed — which is intentional realism. Slippage is dropped as a fee and instead stressed via a 0×/1×/2× cost-sensitivity card.

**4. Honest reporting (ADR-008, ADR-021).** Active return is suppressed (`null`) when a strategy held cash — a do-nothing run can't masquerade as alpha. Server-side config validation rejects nonsensical strategies (inverted dates, 0 capital, 0% stop) before any backtest or signal runs.
