# ADR-001 — Stack: FastAPI + Next.js + DuckDB for a private quant cockpit

**Status:** accepted · **Date:** 2026-06-19

## Context
Windfall Labs is a private, single-user platform whose hardest work is in Python: the quant
engine relies on `pandas`/`numpy` and a columnar store. The PRD floated Streamlit/Dash

<!-- Amendment 2026-06-30: this Context originally listed `vectorbt` in the stack. The
shipped engine is hand-rolled and does NOT depend on vectorbt — see ADR-004's amendment
and ADR-036. -->

as the fastest path, but the owner explicitly asked for "the best stack, no shortcuts — this will
be a huge product with lots of features later."

## Decision
- **Backend / engine:** Python 3.12 + **FastAPI**. The quant engine is an importable package
  (`windfall`) with a thin CLI and a thin HTTP API over the same `run_backtest(config) -> results`
  contract.
- **Store:** **DuckDB** (single embedded file) for price history, strategies, results and paper
  trades — fast columnar reads, SQL, zero server to operate.
- **Frontend:** **Next.js (App Router) + TypeScript + Tailwind** — a real, componentized cockpit
  that scales to many features, not a notebook UI.
- **Deploy:** two Docker containers on vault7a — `web` (Next.js, :8500) and `api` (FastAPI,
  host **:8505** → container :8503; host 8503 was already taken by another project).

## Consequences
- Two languages/containers instead of one Streamlit process — more moving parts, but a clean
  separation: the engine is reusable headless (CLI/cron/API) and the UI can grow independently.
- The strategy-config and results JSON contracts become the stable seam between engine and UI.
