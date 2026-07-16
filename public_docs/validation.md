---
public: true
type: validation
title: Validation — Windfall Labs
order: 3
summary: What is actually built, tested, and reconciled against Trendlyne — including the bugs it caught.
read_minutes: 4
---

# Windfall Labs — Validation

## What is built
All v1 engine modules are implemented: data pipeline (DuckDB), indicator/signal library, declarative strategy config, the backtest engine, validation harness, walk-forward + parameter sweep, live signal generation, paper-trade book, a FastAPI engine API, and the Next.js cockpit (home, strategy editor, backtest/walk-forward reports, signals, paper, data status). Scheduled jobs run nightly in production: the EOD Bhavcopy + NSE index-close ingest (20:30 IST weekdays), the paper mark-to-market (20:40), a monthly paper rebalance, and a daily surveillance refresh. Alerts remain scaffolded with delivery deferred.

## Test suite
The backend suite runs **green** — 181 passed / 12 skipped as of 2026-07-16 (the 12 skips are integration tests that only run against the production DuckDB stores). An earlier version of this page reported 3 honest-debt failures against removed ADR-019 factors; those were repointed on 2026-06-23 and the suite has been kept at zero failures since. No-look-ahead is covered by dedicated tests (`test_engine_no_lookahead.py`), as are costs (including a pin that the deprecated `costs_bps` field is inert and the real NSE cost schedule is what charges), stops, regime, schema, batch-grid safety, and the survivorship-free engine (`test_trendlyne_engine.py`).

## Engine reconciliation (the real proof)
The headline validation is a multi-backtest parity study (`docs/validation/multi-backtest-parity-report.md`), run twice: 2026-06-22/23, and again 2026-06-25 after a 13-finding data audit. All replicable Trendlyne backtests are re-run through the engine at Trendlyne's exact rebalance dates, decomposed into a **pricing** check (do our adjusted prices reproduce their returns?) and a **selection** check (do our filters/ranks pick the same names?). On the in-horizon tests spanning DVM, value, pure-technical, mean-reversion, and the full 10-filter compound screen, selection overlap is **70–91%**, per-stock pricing reconciles to a **median 0.003pp** difference, and round 2 confirmed **zero indicator/DVM false-exclusions** — every residual miss is a data-coverage or universe-scope difference, not engine logic. The same study quantified the cost wedge on identical picks: monthly strategies give back 2.2–2.7pp CAGR to modelled NSE delivery costs, weekly churners 6.5–11.6pp — the founding thesis, measured.

## What the validation actually caught
The study earned its keep by finding real defects, not by rubber-stamping. (1) A production warmup bug: `run_backtest` did not pad long rolling indicators before the requested start, so short-window backtests of `sma200`-class strategies ran a silently thin book for ~200 trading days; overlap on affected screens jumped from ~39–50% to 70–91% after the fix. (2) Filters referencing a point-in-time factor with no data produced an empty book with no warning — now surfaced explicitly. (3) In iter-22 the batch endpoint was caught returning no-stop numbers under a stop label (a resolve-reuse defect); it now refuses grids it cannot honour, and the refusal is pinned by tests.

## Honest limits
Out-of-horizon tests drop to 16–42% overlap for documented data reasons (factor history, microcap coverage), and the +948% origin run on one is explicitly **not reproducible** by this engine. The universe is NSE-only (no BSE feed), names below the ₹500cr point-in-time floor are out of scope, and the monthly Trendlyne fundamentals harvest remains a manual, browser-gated step.

## Live paper run (in progress, not yet evidence)
Five strategies have been paper-trading live since 2026-07-06 at ₹1L notional each, marked nightly net of modelled NSE delivery costs against a live Nifty 500 benchmark. Through day 9 the book was +0.84% gross / +0.38% net vs the index at −0.73% — the right direction, but with **zero closed trades** (first rebalance 2026-08-01) it is a sample of one market fortnight and is treated as such. No flow is marked tested in the tracker, there are no real users, and no real capital has been deployed. Everything above the paper run is engine-level correctness, not a performance claim.
