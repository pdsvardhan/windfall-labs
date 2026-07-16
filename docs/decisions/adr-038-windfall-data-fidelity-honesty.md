# adr-038 — Data-fidelity & cost-honesty hardening (iter-21)

**Status:** accepted · **Date:** 2026-07-16

## Context

Ten days into the honest 5-strategy paper dry-run (adr-037), an audit-todo sweep surfaced a cluster of
data-fidelity and reporting-honesty gaps that could quietly mislead the run toward or away from real
capital — exactly the failure mode this platform exists to prevent ("realism over optimism, validate
everything").

## Decision

Ship a batch of correctness + honesty fixes, each verified against intent by an independent verifier
(APPROVE) with 139/139 tests green:

- **Automated NSE index feed.** `index_ohlcv` was 34 days stale because indices only arrived via the
  manual, WAF-gated Trendlyne harvest — which blinds the live-signal *regime overlay* (index vs its MA)
  and the backtest benchmark. NSE's daily index-close archive **is** fetchable server-side, so
  `scripts/index_ingest.py` now splices it in nightly (same api-stopped exclusive-write window as the
  Bhavcopy EOD ingest). The regime overlay and benchmark stay current with no manual step.
- **Corrected operating-margin factor.** `tl_opm` resolved to `OPM_A`, a broken export column present
  for only 40 of 1962 names with a negative median. Remapped to `PBDITMargin_A` (1924/1962, +15.9%
  median) — the standard EBITDA-margin proxy.
- **Net-of-cost paper P&L.** The paper scoreboard now reports P&L **net** of the modelled NSE delivery
  costs (the same side-aware rates + flat DP the backtest deducts, adr-020), not just gross — so the
  small-capital cost drag is visible. At ₹1L per strategy it is material: costs give back roughly half
  the gross P&L, and one strategy flips from +₹282 gross to −₹196 net.
- **Held-name transparency.** The engine now flags >40% one-day moves and multi-month price gaps on
  names *while held* — usually real (special auctions, suspensions) but never left silent.
- **Same-bar entry-stop fix.** A next-open fill could be stopped out on its own entry bar (0-hold
  whipsaw); the first exit check is now the following bar.
- **Honest readiness + benchmark coverage.** Readiness no longer mislabels computed Trendlyne factors as
  "will be skipped" (single source of truth imported from `resolve`); backtests warn when the benchmark
  index history begins after the window start (e.g. Nifty Smallcap 250 starts 2019-01-14); `pe_to_sector`
  warns that it is snapshot-only.
- **Backtest-list pagination** (`limit`/`offset`) so leaderboards page past the newest 200.

## Consequence

The paper dry-run can now be read honestly against a live benchmark: over its first 9 days the book is
**+0.84% gross / +0.38% net while Nifty 500 fell −0.73%** — early, small-sample, but genuine alpha, not
beta. Deferred with reason: paper entries stay at the executable close (matching backtest next-open would
re-baseline the running experiment); the trailing-stop *redesign* and the heavy survivorship data
backfills remain open todos.
