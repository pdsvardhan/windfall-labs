# SESSION — Engine-facing data audit + fix

> Owner-requested dedicated session. Decisions locked with owner 2026-06-24:
> **(1) Audit then fix inline** (fix necessary/mandatory in-session; flag nice-to-haves).
> **(2) Scope = engine-facing only** (skip raw bhavcopy/screener internals unless they feed a bug).
> Pairs with the follow-up session [`SESSION-backtest-revalidation.md`](SESSION-backtest-revalidation.md), which runs only AFTER this one's fixes land.

## Goal
Systematically audit every dataset the backtest/signal **engine consumes**, find every kind of issue, root-cause each (web-research domain conventions where needed), decide whether a fix is **mandatory / necessary / nice-to-have / not worth it**, and **fix the mandatory + necessary ones in this session** — safely and reproducibly.

## Scope — engine-facing only
Primary store `backend/data/trendlyne.duckdb` (30 tables). Audit the tables the engine actually reads + the derived/identity layer:

- **Prices/scores (daily):** `ohlcv`, `dvm_history`, `valuation_ratios`, `index_ohlcv`.
- **Fundamentals:** `pnl_quarterly`, `pnl_annual`, `balance_sheet`, `cashflow`, `ratios_annual`, `growth_quality`, `ownership`, `shareholding_summary`, `financials_other`, `result_dates`.
- **Derived / point-in-time layer:** `pit_shares`, `pit_mcap`, `pit_mcap_dead`, `ca_factor`, `universe_membership`.
- **Identity / universe:** `stocks` (pk↔nsecode↔mcap), `recovered_symbols`, `rename_map`, `dead_names`, `delistings`, `sector_map`, `index_map`, plus `backend/data/universe/*.csv` where they feed resolution.
- **Out of scope** unless a finding traces into them: raw `bhavcopy.duckdb`, `screener_fundamentals.duckdb` internals.

## Issue categories to check (per table)
1. **Coverage / completeness** — missing names, short/late-start histories, NULL-heavy columns, pk↔symbol gaps, date holes.
2. **Correctness** — out-of-range values (negative/zero prices, extreme PE/EPS, mcap spikes), CA-adjustment step errors (split/bonus), unit inconsistencies.
3. **Point-in-time integrity** — look-ahead: fundamentals usable only after the result-date lag (documented ~120d / ~3mo via `result_dates`); restatement overwrites; any future-dated rows in historical series.
4. **Survivorship** — dead/delisted names present with price + shares + mcap; rename chains complete; no silent dropouts.
5. **Identity / join integrity** — duplicate pks, symbol collisions, ISIN mismatches, `rename_map` gaps, numeric-token/blank-symbol rows.
6. **Cross-store consistency** — `ohlcv` vs `pit_mcap` date alignment; `dvm_history` latest vs `stocks` current scores; pnl-derived shares vs sane share counts.
7. **Staleness** — last-date per table; mismatched currency of sources (e.g. trendlyne `ohlcv` vs bhavcopy last date, like GSPL ending 2026-05-11).
8. **Re-verify known prior items** — iter-12 loss-maker constant-shares fallback (adr-026) edge cases; the EICHERMOT/BEL CA-timing rebuild assumptions (`rebuild_pit_mcap_ca.py`); 200DMA/dist-high coverage gap; valuation-factor ceiling; negative-PE guard.

## Method
1. **Profile read-only first.** Open `trendlyne.duckdb` with `read_only=True`. Extend the existing `backend/scripts/data_audit.py` to emit per-table: row count, date range, NULL %, distinct pk, numeric min/max + outlier flags, and the category-specific checks above.
2. **Root-cause each finding.** Don't assume — web-research where domain knowledge is needed (NSE corporate-action conventions, Trendlyne factor definitions, accounting period/availability conventions).
3. **Triage.** Severity = mandatory (breaks correctness / look-ahead) / necessary (materially shifts backtests or signals) / nice-to-have / not-worth-it. Each finding gets: table · symptom · root cause · fix approach · effort · verdict.
4. **Write the report:** `docs/validation/data_audit_run-<date>.md`.
5. **Fix mandatory + necessary in-session, safely:**
   - `cp` backup `trendlyne.duckdb` first.
   - **Stop `windfall-api` + `windfall-web` during any write** (DuckDB single-writer); restart after.
   - **Lock-in gate (AskUserQuestion) before any non-trivial or destructive fix**; dispatch the **independent verifier** sub-agent after each fix; for canonical rebuilds, edit the builder script (e.g. `rebuild_pit_mcap_ca.py`) so the fix is reproducible by a future full rebuild.
   - Record each material fix as an **ADR** (`adr-NNN-...`) and an Ottomate iteration.
6. **Anti-gaslight:** nothing changed silently; every fix = backup + verifier + recorded decision; surface "not worth fixing" items with the reason.

## Done when
- `data_audit_run-<date>.md` exists with the full finding list + verdicts.
- All mandatory + necessary issues fixed and verifier-APPROVED; nice-to-haves logged as follow-up todos.
- Data declared ready → unblocks the backtest-revalidation session.
