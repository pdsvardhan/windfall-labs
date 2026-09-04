# Windfall Labs — Concepts (read this first)

Orientation for anyone (human or AI) who needs to understand **what this system is and why**,
without reading ~7,900 lines of engine code. For the file-by-file reading guide, see
[CODE-MAP.md](CODE-MAP.md).

## What it is (one paragraph)

A private, single-user quant research + execution platform for systematic **NSE (Indian) equity
swing strategies**. You declare a strategy as JSON → backtest it over ~10 years with real costs and
explicit exits → prove it isn't curve-fit with walk-forward → generate today's exact buy/hold/sell
orders → paper-trade it live with zero risk before any real money. **v1 is signals-only**: it
prepares orders; a human places every one.

## The core loop

```
strategy config (JSON)
  → resolve        signals / filters / ranks, point-in-time      (strategy/resolve.py)
  → backtest       rebalance-and-hold sim, costs, daily exits     (engine/backtest.py)
  → validate       reproduce a known Trendlyne result             (scripts_validation.py)
  → walk-forward   in-sample optimize → out-of-sample test        (walkforward/walkforward.py)
  → live signals   today's exact orders (entry/stop/target/size)  (signals_live/generate.py)
  → paper trade    honest live dry-run, marked daily              (paper/book.py)
  → [human places the orders]
```

## The six principles (baked in, not aspirational)

1. **Realism over optimism** — costs + turnover reported on every run.
2. **Exits are first-class** — stop / target / trailing / time, checked every day.
3. **No look-ahead** — next-open fills, point-in-time data, fundamentals lagged to publish date.
4. **Liquidity-aware** — ADTV filters + ADTV-capped position sizing.
5. **Validate everything** — reproduce before trusting; walk-forward before approving.
6. **Human in the loop** — v1 generates, the human executes.

## The concepts that make this different

These are the non-obvious ideas. Understand these eleven and you understand the system.

**1. Survivorship-free universe.** Most backtests use *today's* index members, silently excluding the
companies that went bankrupt — which inflates returns. Here the universe is every NSE name ever
>₹500cr in-window, **live + delisted** (DHFL, Bhushan Steel, Kingfisher are in it), with
**point-in-time membership** (eligible only on dates it actually was a member). Dead companies
experience their fate. → `data/trendlyne_store.py`; ADR-011/015/018/030.

**2. Point-in-time everything (no look-ahead).** Prices fill at the **next open**, never the same-bar
close. Fundamentals are valid only **on/after their real result-announcement date** (60-day annual /
45-day quarterly lag) — you never rank on a number the market hadn't seen. Market cap is
reconstructed point-in-time. → ADR-016/028/029.

**3. The data layers (and why some is manual).**
- **Trendlyne** (primary): full-history split/bonus-adjusted OHLCV + fundamentals + DVM scores in a
  standalone **read-only** `trendlyne.duckdb`. WAF-gated → a **manual in-browser harvest**, not an
  API. This is the system's main data fragility. → `data/trendlyne_store.py`; ADR-014.
- **NSE Bhavcopy** (nightly cron): survivorship-free EOD + the **live-price splice** beyond the
  Trendlyne layer. → `scripts/bhavcopy_ingest.py`; ADR-022.
- **screener.in**: historical fundamentals, triangulation-validated. → `data/screener_fundamentals.py`; ADR-013.
- **yfinance**: legacy path, mostly superseded. → `data/fetch.py`.

**4. Declarative strategy config.** A strategy is JSON: universe filters, a rank expression (or a
percentile blend of factors), n_holdings, rebalance cadence, weighting, exits, regime overlay.
Factor expressions (`roc252`, `tl_durability`, `mcap > 500`…) run through a **real AST sandbox**, not
`eval`. → `strategy/schema.py` (the contract), `strategy/resolve.py` (config→signals),
`strategy/safe_eval.py` (the sandbox).

**5. The engine is hand-rolled (not vectorbt).** A from-scratch deterministic **rebalance-and-hold**
simulator: rebalance on cadence, hold between, check exits **every day**, fill at next open, charge
the real NSE delivery cost model (side-aware fees + flat DP; no slippage for delivery by design),
optional regime / factor-timing overlay. ADR-004 planned vectorbt; never adopted (ADR-036). →
`engine/backtest.py`. **If you read one file, read this.**

**6. Validation & parity.** Before trusting the engine, it must **reproduce a known Trendlyne
backtest**. Parity is measured **gross-of-costs** (Trendlyne is costless; our net diverges on
high-turnover strategies by design). → `scripts_validation.py`, `docs/validation/`; ADR-032.

**7. Walk-forward is the approval gate.** A single backtest is easy to curve-fit. Walk-forward
optimizes in-sample, tests out-of-sample, rolls forward, reports degradation. **No strategy is
"approved" until it clears walk-forward** (OOS/IS ratio; a 2007–16 decade incl. the 2008 crash). →
`walkforward/walkforward.py`; ADR-040. This is *the* number to trust — short-window backtests flip
conclusions (a strategy can look like the worst book over one window and the best over another).

**8. Live signals ≠ backtest.** Live signals resolve **as of the last healthy bar** (spliced Bhavcopy
EOD), producing today's exact orders with entry/stop/target/size, ASM/GSM surveillance flags, and
next-open intent. → `signals_live/generate.py`; ADR-022/037.

**9. Paper trading is an *honest* live dry-run.** Several strategy "books" (currently 8) at ~₹1L each,
entered live, marked daily by cron, **net-of-costs**. The zero-risk proof before real capital.
Honesty rules: entries at the latest executable close (no phantom day-0 P&L); a `stale_mark` flag
when a name's price didn't refresh; a **SIM series that reconstructs backfilled runs is labelled
"NOT the live record."** Backfilled/backdated positions stay auditable via `entry_date` vs
`created_at`. → `paper/book.py`, `paper/equity.py`, `paper/rebalance.py`; ADR-037/038.

**10. DVM factors.** Trendlyne's **Durability / Valuation / Momentum** scores are used *directly* (a
homegrown reproduction was built, then removed — ADR-019 — because the source is cleaner), plus a
curated library of ~35 Trendlyne fundamental factors. → `data/fundamentals.py`; ADR-019/023.

**11. Cost & reporting honesty.** Every result reports costs, turnover, net P&L. Active-return (alpha)
is **suppressed when a strategy holds cash** — annualizing a 3-week active return produces garbage.
→ `engine/metrics.py`; ADR-008/020.

## One hard runtime reality

`windfall.duckdb` is opened by the API as a **single persistent writer** — no second process can open
it (even read-only) while the API is up; all writes go through the API process. The separate
`trendlyne.duckdb` is read-only (ONE-DOOR safe, ADR-018). Data refresh, paper marking, and monthly
rebalance run on the **`pdsv` crontab** (EOD 20:30, paper-mark 20:40, monthly rebalance) — nothing is
event-driven.
