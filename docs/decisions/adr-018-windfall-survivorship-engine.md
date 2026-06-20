# ADR-018: Survivorship-free backtest engine on the Trendlyne layer

Status: accepted
Date: 2026-06-20
Curated: yes
Category: cat:reliability
Title (showcase): "A survivorship-free backtest engine: dead companies experience their fate"

## Context
The engine ran on current-membership universes and a single fundamentals snapshot (ADR-014 era):
every backtest CAGR was a ceiling because delisted names were absent and historical fundamentals
were live-only. The iter-28 data layer (ADR-017) made the missing pieces available — adjusted
prices for delisted names, point-in-time Rs500cr membership, real result-announcement dates, and
Trendlyne's own daily DVM scores. This decision wires them into the engine.

## Decision
Add a `data_source` strategy option. `data_source="trendlyne"` resolves a strategy against the
survivorship-free layer:
- **Prices:** split/bonus-adjusted OHLCV — Trendlyne `ohlcv` for live names, raw Bhavcopy x the
  iter-28 `ca_factor` for delisted names.
- **Universe:** every name ever above Rs500cr in the window (live + delisted), gated by a
  TIME-VARYING point-in-time membership mask, so a name is eligible only on the dates it actually
  qualified and drops out when it shrinks or delists.
- **Features:** Trendlyne's own daily Durability/Valuation/Momentum (`tl_*`) and valuation multiples
  (point-in-time by construction), plus raw annual fundamentals (`tl_roe/roce/de/opm/eps`) gated by
  `result_lag.available_from` — readable only on/after the real board-meeting/result date (ADR-016).
- **Benchmark:** the real Nifty-500 index series (`index_ohlcv`), not a yfinance proxy.
- **Delisting terminal exit:** a held name that stops trading is force-closed at its last traded
  (adjusted) price — you cannot hold a delisted stock.

The legacy `data_source="windfall"` path is unchanged (default).

## Decision: ca_uncertain names are INCLUDED (amends ADR-017)
ADR-017 excluded `ca_uncertain` delisted names (large unconfirmed corporate-action gap) from
tradeability. Wiring the engine exposed that this was backwards: a large unexplained gap is usually
a real **crash or merger**, not an unconfirmed split, and 87 of the affected names were ever >Rs500cr
— including blow-ups (RCOM Rs52k cr, RELCAPITAL, JETAIRWAYS) and mergers (HDFC Rs592k cr, RANBAXY,
MINDTREE, GRUH). **Excluding them silently removes exactly the failures a survivorship-free engine
exists to capture — an OPTIMISTIC bias.** So ca_uncertain names are now INCLUDED in the universe and
ca_uncertain is surfaced as a per-run data-quality WARNING, never a silent exclusion.

## Consequences
- Verifier-confirmed no look-ahead on every surface: result-lag fundamentals visible only on
  `available_from` (RELIANCE shows the prior-year ROE at period-end, the fresh value only at
  announcement; 0 negative-lag rows), DVM/valuation/membership panels are ffill-only (no bfill), and
  fills stay decide-at-close / execute-next-open.
- Membership ffill is bounded (~2 trading weeks) so delisted names drop out (RCOM: eligible while
  large, 0 eligible days in 2023) rather than appearing perpetually live.
- A real survivorship-free run over 2016-2024 (momentum+DVM blend, regime gate) holds ~1700 names
  in-window incl. delisted; delisting terminal exits fire (e.g. the 2017 SBI-associate-bank mergers).
- Known limitation: names with no screener share history (e.g. DHFL) have no point-in-time mcap and
  cannot be included; this is a coverage gap, separate from ca_uncertain.
- Files: `strategy/{schema,resolve,readiness}.py`, `engine/backtest.py`, `data/trendlyne_store.py`.
  Tests: `tests/test_trendlyne_engine.py` (9). Full suite 111 green.
- Operational note: the API container now opens `trendlyne.duckdb` READ-ONLY (mounted at
  `/app/data`). Offline data-layer rebuilds (build_ca_factor / rebuild_pit_mcap_ca) must stop the API
  first, as with windfall.duckdb — single-writer discipline.
- Unblocks to-do #30 (reproduce a known Trendlyne backtest, success criterion #1) and #31 (swing
  strategy suite), which now run on real survivorship-free history.
