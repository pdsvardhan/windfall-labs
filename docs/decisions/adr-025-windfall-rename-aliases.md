# ADR-025 — ISIN-based ticker-rename/alias resolution

**Status:** accepted · **Date:** 2026-06-22 · iter-34

## Context
A deep Test-A parity reconciliation found a systematic bug: when a company changes its NSE ticker
(e.g. Nava Bharat Ventures **NBVENTURES → NAVA** in 2022), Bhavcopy keeps the pre-rename history under
the **old** ticker. Our **symbol-keyed** Bhavcopy lookups searched only the current ticker, so renamed
names had **no turnover and no Bhavcopy price** in their pre-rename window. Consequences:
- The **ADTV/liquidity filter** wrongly failed them (NAVA, PE 4.3 and passing every score filter, was
  dropped in 2021 because we saw zero turnover for "NAVA" — its volume was under "NBVENTURES").
- **pit_mcap / membership** started only at the rename date (NAVA looked eligible only from 2022).
- The old `rename_map` (122 entries) was both **incomplete** and **never wired** into these lookups.
Scope: **417 companies** have ≥2 tickers over their life.

## Decision
Resolve renames via **ISIN** (the stable company id), accumulating across the multiple ISINs a name
may carry after a face-value change (NAVA has INE725A01022 *and* INE725A01030):
- `trendlyne_store._ticker_aliases()` — symbol → all tickers ever sharing its ISIN(s).
- `traded_value_panel` and `adjusted_close_panel` (dead-name path) expand each requested symbol to its
  aliases and relabel old-ticker rows back to the current symbol.
- `build_pit_mcap.py` joins Bhavcopy via **ISIN** (not the current symbol), so pit-mcap/membership
  cover the full pre-rename history (NAVA mcap now spans 2011→, was 2022-only).

## Consequences
- Renamed names get correct pre-rename turnover, price, and membership (NAVA's 2021 ADTV = ₹16.2cr →
  now passes the liquidity filter and is selectable). Test-A pick-overlap 88% → 90%.
- Validated: 0 ISINs map to >1 Trendlyne pk (no over-merge); +53k recovered bhavcopy rows (modest).
- **Survivors-only limit (Fix-3, documented):** names that *merged/delisted during the window*
  (IDFC, JSL Hisar, Ujjivan, Tata Steel BSL, GSPL) are absent from the Trendlyne FACTOR layer (current
  listings only), so a `tl_`-factor screen cannot select them — Trendlyne can. This is irreducible
  without delisted-name factor history (which Trendlyne does not serve). The survivorship-free PRICE
  layer covers their prices for price/screener-fundamental screens, not for `tl_`-factor screens.
- **ca_uncertain (Fix-2):** names with an unconfirmable corporate action (e.g. GVKPIL, a ₹4 penny
  stock) are excluded from the parity comparison — neither side's price is trustworthy.
