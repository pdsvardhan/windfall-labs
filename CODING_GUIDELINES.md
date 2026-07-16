# Coding Guidelines — Windfall Labs

These are the rails for any code (human or assistant) added to this repo. They exist because
backtesting code that looks right and is silently wrong loses real money.

## Non-negotiables (the anti-gaslight rails)

1. **No look-ahead, ever.** At any decision date `t`, use only data with timestamp ≤ `t`.
   Signals computed on bar `t` fill at bar `t+1` open. Fundamentals are lagged to their actual
   publish date. Any function that could leak future data must have a test proving it doesn't.
2. **Costs + slippage on every fill.** No backtest result is reported without costs applied and
   **annual turnover** shown alongside it. A "costless" run is only ever a validation aid, and is
   labelled as such.
3. **Exits are explicit.** Stop-loss / take-profit / trailing / time-exit are first-class and
   checked daily, not emergent from rebalance rotation.
4. **Liquidity realism.** Universe is ADTV-filtered; position size is capped vs ADTV.
5. **Determinism.** Same config + same data ⇒ byte-identical results. Every result is tagged with
   a `config_hash`. No wall-clock, no unseeded randomness in the engine path.
6. **Validate before trust.** The engine must reproduce a known reference (see
   `scripts/run_validation.py`) before any result is believed.

## Python (backend)

- Python 3.12, type hints on public functions. `pydantic` v2 models for all external contracts
  (strategy config, results). The strategy config schema in `windfall/strategy/schema.py` is a
  **stable contract** — additive changes only; never silently rename a field.
- Data is a tidy long DataFrame (`date, ticker, open, high, low, close, volume, ...`) or a wide
  panel keyed `(date) x (ticker)`; indicators are vectorized over the panel — avoid per-ticker
  Python loops in hot paths.
- DuckDB is the store. One `.duckdb` file under `data/`. Read once, reuse; never re-fetch cached
  history. All schema in `windfall/data/store.py`.
- Engine I/O is JSON. `run_backtest(config) -> results` is the contract; the CLI and the API are
  thin wrappers over it.
- Tests with `pytest`. Every indicator has a unit test against a known value. The no-look-ahead
  and costs rails each have a dedicated test. Run `pytest` green before claiming a feature done.
- Format with `ruff`/`black` defaults; keep imports tidy.
- **Long-running host-side scripts** (sweeps, research harnesses, anything alive >5 min) call the
  API via `scripts/batch_client.py` (`post_json`/`get_json`), never raw urllib/requests: the
  weekday EOD cron (20:30 IST) stops and rebuilds the api container for its exclusive DuckDB
  write window (adr-022), and a bare POST dies mid-run with connection refused (#98). The helper
  waits out the 20:25–20:55 window and retries through the bounce; 4xx still fail fast.

## TypeScript (frontend)

- Next.js App Router + TypeScript strict. Server components for data fetching where possible.
- All API types live in `src/lib/types.ts` and mirror the backend pydantic models.
- Tailwind for styling; theme tokens (palette/fonts) match the Ottomate UI master plan. Numbers
  and tables use the mono font; gains green, losses red.
- No business/quant logic in the frontend — it renders what the engine returns.

## Money & safety

- **Signals-only in v1.** No code path places a broker order. The execution phase is separate,
  paper-proven, manual-confirm, and guard-railed.
- Secrets in env, never in code or git. `.env.example` documents required vars.
- Results, paper-trades and strategies are user data — back them up with the DuckDB file.

## Definition of done (per feature)

- Acceptance criteria in the Ottomate tracker are all satisfied.
- Tests covering the feature pass.
- For engine features: a no-look-ahead consideration is documented or tested.
- The independent verifier sub-agent has APPROVED against the locked manifest + diff.
