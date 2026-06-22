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
All v1 engine modules are implemented: data pipeline (DuckDB), indicator/signal library, declarative strategy config, the backtest engine, validation harness, walk-forward + parameter sweep, live signal generation, paper-trade log, a FastAPI engine API, and the Next.js cockpit (home, strategy editor, backtest/walk-forward reports, signals, paper, data status). Scheduled jobs are in progress; alerts are scaffolded with delivery deferred.

## Test suite
The backend has **~110 tests across 21 files**. A current run reports **98 passed, 12 skipped, and 3 failing**. The failures are honest debt, not hidden breakage: they assert readiness for the homegrown `durability_own`/`valuation_own` scores that were deliberately removed in ADR-019 (plus one cost-sensitivity monotonicity check), so the tests are stale relative to the current design. No-look-ahead is covered by dedicated tests (`test_engine_no_lookahead.py`), as are costs, regime, schema, and the survivorship-free engine (`test_trendlyne_engine.py`).

## Engine reconciliation (the real proof)
The headline validation is a multi-backtest parity study (`docs/validation/multi-backtest-parity-report.md`, run 2026-06-22/23): all replicable Trendlyne backtests are re-run through the engine at Trendlyne's exact rebalance dates, decomposed into a **pricing** check (do our adjusted prices reproduce their returns?) and a **selection** check (do our filters/ranks pick the same names?). On the 9 in-horizon tests spanning DVM, value, pure-technical, mean-reversion, and the full 10-filter compound screen, selection overlap is **70–91%** and per-stock pricing reconciles to a **median 0.003pp** difference (96–100% of stock-periods within 0.5pp).

## What the validation actually caught
The study earned its keep by finding two real "silent empty book" defects, not by rubber-stamping. (1) A production warmup bug: `run_backtest` did not pad long rolling indicators before the requested start, so any short-window backtest of an `sma200`/`roc125`/regime strategy ran a silently thin book for the first ~200 trading days. Fixed to mirror the live-signals path; overlap on affected screens jumped from ~39–50% to 70–91%. (2) Filters referencing a point-in-time factor with no data in a period produced an empty book with no warning — a transparency follow-up is filed.

## Honest limits
4 out-of-horizon tests drop to 16–42% overlap for documented data reasons (factor history, microcap coverage), and the +948% origin run on one is explicitly **not reproducible** by this engine. The universe is NSE-only (no BSE feed), and names with no point-in-time market-cap history cannot be included.

## Not yet proven
No flow is marked tested in the tracker; there are no real users, no live paper-trading track record, and no live trading. Everything above is engine-level correctness, not a performance claim.
