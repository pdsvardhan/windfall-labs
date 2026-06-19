# ADR-012 — ASM/GSM surveillance flag as a pre-deploy guardrail

**Status:** accepted · **Date:** 2026-06-19 · **Iteration:** #25

## Context

The methodology's screen tilts toward high-momentum small/mid-caps — exactly the population NSE
puts under surveillance (ASM/GSM) for unusual price/volume or weak fundamentals. Trading into a
surveilled name risks price-band traps, 100% margin, trade-to-trade settlement, and the circuit
behaviour that motivated this guardrail in the first place. The platform had no flag for it.

## Decision

Ingest the NSE ASM (Additional Surveillance Measure, long- and short-term) and GSM (Graded
Surveillance Measure) lists and use them as a **pre-deploy guardrail on live signals**.

- Fetched **in-process by the api** (which owns the windfall.duckdb write lock) — no second DB
  client, no ONE DOOR risk. Stored as a dated snapshot so the lists accrue history going forward.
- Live `/api/signals` output is annotated per name, and a warning is raised when a buy/hold is
  under surveillance. Endpoints `POST /api/surveillance/refresh` + `GET /api/surveillance`; a daily
  cron refreshes the snapshot.

## Consequences

- The guardrail is live and immediately material: on the first refresh (247 surveilled names:
  139 ASM-LT, 57 ASM-ST, 51 GSM), **5 of the 10 current `dvm_monthly` picks were under ASM** —
  the screen really does surface circuit-prone names, and now they're flagged before any deploy.
- It is a *live* guardrail, not yet a backtest filter — we don't have historical ASM/GSM
  membership. Snapshotting forward builds that history so surveilled names can also be excluded in
  historical backtests later.
- Follow-up: the order-prep CSV export (`/api/signals/export`) should carry the flag too (tracked).
