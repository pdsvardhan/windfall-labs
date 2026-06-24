# SESSION — Backtest re-validation vs Trendlyne (parity round 2)

> Owner-requested dedicated session. **Prerequisite:** the data-audit session ([`SESSION-data-audit.md`](SESSION-data-audit.md)) is complete and its fixes have landed.
> Decisions locked with owner 2026-06-24:
> **Gold source** = owner downloads all Trendlyne backtest **CSVs + per-test result screenshots** into `C:\Users\pdsva\Downloads\backtest-data` (filled before this session starts; the prior `/tmp/parity_gold` fixtures were cleared).
> **Acceptance** = NO hard threshold. The goal is to **identify every difference, root-cause it, then brainstorm per root cause whether WE are right or TRENDLYNE is right**, and fix only genuine bugs on our side. Prior baseline (70–91% pick-overlap, ~0.003pp pricing) is the reference for improved/regressed.

## Goal
Re-run the same backtests we previously validated against Trendlyne, compare to Trendlyne's own results, and for **every** discrepancy: quantify it, find the root cause (web-research Trendlyne's methodology where unknown), jointly decide right/wrong, and fix only real engine/data bugs. Record accepted methodology differences as ADRs so they are never re-chased.

## Gold reference (owner-provided)
At session start, inventory `C:\Users\pdsva\Downloads\backtest-data`:
- Parse each test's **config** (filters, rank, rebalance, dates, mcap floor, n-hold), **picks per rebalance period**, and **headline metrics** (CAGR, total return, max DD, Sharpe, turnover, etc.) from the CSVs.
- Use the screenshots to cross-check fields not present in the CSVs and to confirm each test's exact definition.
- The owner's files are the **source of truth** for what each test was — reconcile our stored `TEST_TABLE` against them, don't assume.

## The backtests
The cross-style parity set already encoded in `docs/validation/parity_multi.py` / `gap_analysis.py` (`TEST_TABLE`): **548012, 548776, 548042, 548040, 548017, 548015, 548014, 547990, 547989, 547991, 547992, 547994, 547995** — covering durability/valuation/momentum blends, mcap + technical (sma/roc/rsi) screens, and pledge/PE-filtered styles, across monthly/weekly/quarterly rebalances. Confirm this set matches the owner's downloaded tests; add/drop to match.

## Method
1. **Map** each Trendlyne test → our `StrategyConfig` (reuse/extend the existing `TEST_TABLE`).
2. **Run** each through the engine using the existing parity harness (`parity_multi.py`) on the **post-audit** data.
3. **Compare** at two levels:
   - **Selection:** pick-overlap per rebalance period; per-miss classification via the `gap_analysis.py` taxonomy — `NOT_IN_UNIVERSE` / `NO_DATA:<feat>` / `FAILED:<filter>` / `RANKED_OUT`.
   - **Performance:** headline metric deltas (CAGR, total return, max DD, Sharpe, turnover) vs the Trendlyne CSV numbers.
4. **Root-cause every discrepancy.** Candidate causes to test explicitly: data coverage gap (post-audit should be smaller); factor-definition difference (how Trendlyne computes D/V/M, PE/PEG, etc.); CA / point-in-time timing; cost model (our fixed NSE delivery vs theirs); mcap floor / universe construction; rebalance-date alignment; **total-return vs price-return** benchmark; rounding/winsorization. Web-research Trendlyne's methodology where unknown.
5. **Decide per root cause (with owner):** are WE right or is TRENDLYNE right? Fix genuine engine/data bugs on our side (backup → lock-in → verifier, same discipline as the audit session). Record each **accepted difference as an ADR** (recruiter-readable, `curated`) so it is documented, not re-investigated.
6. **Report:** `docs/validation/parity_round2_run-<date>.md` — per-test overlap %, metric deltas, the root-cause table, the right/wrong decisions, fixes applied, and the accepted-difference ADRs. Compare overlap/pricing vs the prior baseline.

## Acceptance / done when
- Every material discrepancy has a documented root cause and an explicit "we're right / Trendlyne's right" decision.
- Genuine bugs fixed + verifier-APPROVED; accepted differences captured as ADRs.
- Round-2 parity report written and compared to the prior run.

## Anti-gaslight
Surface misses honestly (never hide a non-overlap); verify root causes, don't assume; fixes via lock-in + independent verifier; accepted Trendlyne-vs-us differences become ADRs so the next session doesn't re-chase them.
