# Windfall Labs — Code Map (what to read, what to ignore)

The backend `windfall` package is ~7,900 lines. You do **not** need most of it to understand the
system. Read the six "Start here" files; skim the second tier; **ignore** the rest (one-off scripts
and dated validation dumps). The concepts these files implement are in [CONCEPTS.md](CONCEPTS.md).

## ★ START HERE — the six files that *are* the system (~1,900 lines, in this order)

| # | File | Lines | Why |
|---|------|-------|-----|
| 1 | `strategy/schema.py`        | 184 | The `StrategyConfig` contract — what a strategy *is* (filters, rank, exits, rebalance, overlays). Everything else consumes it. Read first. |
| 2 | `strategy/resolve.py`       | 387 | Turns a config into point-in-time panels: `entry_mask`, `rank_score`, adjusted OHLC, ATR, ADTV, sectors. The bridge from JSON to data. |
| 3 | `engine/backtest.py`        | 538 | **The core.** Rebalance-and-hold simulator: selection, next-open fills, daily exits, the NSE cost model, regime/factor-timing overlays. |
| 4 | `signals_live/generate.py`  | 241 | The live "today's orders" path — same resolve, but as-of the last healthy bar + splice. Shows how live differs from backtest. |
| 5 | `walkforward/walkforward.py` |  79 | The approval gate: in-sample optimize → out-of-sample test → roll → degradation. |
| 6 | `paper/book.py`             | 220 | The paper dry-run: commit a signal → position, daily mark-to-market net of costs, close on stop/target. |

## ◐ SECOND TIER — skim for depth on a specific area

- `app/main.py` (665) — the FastAPI HTTP surface; **all** endpoints. Big but mechanical — grep for the
  route you care about (`/api/backtests`, `/api/signals`, `/api/paper/*`).
- `data/trendlyne_store.py` (480) — the primary read-only data layer (adjusted OHLCV, PIT membership,
  fundamentals, DVM). Read the docstring + table list.
- `strategy/safe_eval.py` (89) — the AST sandbox for factor expressions (why it's not `eval`). Small.
- `signals/indicators.py` (107) — vectorized indicators (sma/ema/roc/rsi/atr/adx/adtv…). Pure functions.
- `strategy/readiness.py` (188) — "can this strategy be backtested, and from when?" (live-only vs
  historically-testable — why a DVM strategy holds nothing before its snapshot).
- `engine/rotation.py` (178) — the fund-of-funds rotation overlay across self-timed sleeves + cash.
- `engine/metrics.py` (86) + `engine/results.py` (54) — how performance is scored; the `BacktestResult` shape.
- `data/surveillance.py` (114) — ASM/GSM pre-deploy guardrail.
- `store_meta.py` (186) + `data/store.py` (253) — metadata store (strategies, backtests, paper_positions)
  and the DuckDB connection layer (note the single-writer proxy).

## ✗ IGNORE — history, one-offs, generated dumps (not needed to understand the system)

- **`backend/scripts/*`** — ~20 one-shot data-build/migration scripts (`bhavcopy_ingest`,
  `build_ca_factor`, `rebuild_pit_mcap_ca`, `migrate_f5_delistings`, `fix_iter23_renames_ohlc`…).
  They built the data once; they are not the running system. Open one only to rebuild that artifact.
- **`docs/validation/*`** — parity/robustness **run logs and analysis scripts** (`parity_*`, `gap_*`,
  `postcovid5y_*`, `regime_study_*`). Evidence, not architecture — dated dumps from specific
  investigations. Read a `*_run-*.md` for a finding; ignore the `.py`/`.txt`/`.jsonl`.
- **`data/fetch.py` + the yfinance path** — legacy data source, superseded by Trendlyne.
- **`alerts/rules.py`** — scaffolded; logs only, sends nothing (delivery deferred). Not live.
- **`backend/tests/*` (~2,300 lines)** — useful as executable spec, but 3 fail + 12 skip *by design*
  (stale own-DVM tests from the ADR-019 removal). Red ≠ broken; see `public_docs/validation.md`.
- **`.venv`, `node_modules`, `__pycache__`** — obviously.

## Frontend (Next.js cockpit) — read only if touching UI

App Router, one page per view: `app/page.tsx` (cockpit home), `strategies/` (list/new/[id]/edit),
`signals/`, `paper/`, `leaderboards/`, `reference/`. The engine is the product; the frontend is a
thin read/trigger layer over the API.

## Where the "why" lives — ADRs (`docs/decisions/`)

41 ADRs is a lot. The ones that actually shape the system:

- **Data / universe:** 011 (Bhavcopy survivorship), 014 (Trendlyne primary), 015 (PIT membership),
  018 (survivorship-free engine + ONE-DOOR), 024 (NSE-only).
- **Fundamentals:** 016/028 (result-lag PIT), 019 (remove homegrown DVM), 023 (factor library).
- **Engine / costs:** 020 (NSE cost model), 032 (gross-of-costs parity), 036 (hand-rolled, not vectorbt).
- **Strategy findings:** 035 (70/30 blend deployable), 039 (no stops, by measurement), 040 (walk-forward
  gate passed), 041 (regime gate candidate).
- **Live / paper:** 022 (live splice + cron), 037/038 (paper honesty).

Skim the rest by title only.

## Reading budget

- **15 min** — CONCEPTS.md + the six "Start here" docstrings.
- **1 hour** — the six core files end-to-end.
- **Half a day** — + the second tier + the ADR titles above. That's the whole system.
