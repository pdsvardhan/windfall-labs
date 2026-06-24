# adr-026 — Loss-maker share-count fallback: bring profitless IPOs into the universe

- **Status:** accepted
- **Date:** 2026-06-24
- **Tags:** curated, cat:reliability
- **Iteration:** iter-12 (Stage 4) · resolves todo #73 (PARITY-4) coverage gap

## Context

The point-in-time market cap (`pit_mcap`) that gates the backtest universe is built from
`mcap(t) = adjusted_close(t) × current_shares`. The **current share count** was derived only from
fundamentals as `shares = net_profit / EPS` (latest `NP_TTM/EPS_TTM`, else `NP_A/EPS_A`), and that
derivation **requires `EPS > 0`**.

Consequence: every **loss-making** company produced *no* share count, so it got **no `pit_mcap`
row** and was **absent from `universe_membership` entirely** — invisible to every backtest,
regardless of strategy. A gap analysis (`docs/validation/gap_analysis.py`, run 2026-06-23) traced the
dominant Trendlyne-parity miss (47–75% of misses) to `NOT_IN_UNIVERSE`, and the root cause for the
live names was exactly this.

This was not a handful of obscure stocks. The 19 affected names (OHLCV present, `pit_mcap` empty)
included major recent IPOs and profitless growth names:

| Symbol | Snapshot mcap (₹ cr) |
|---|---|
| MEESHO | 79,808 |
| SWIGGY | 70,126 |
| ATHERENERG | 37,228 |
| PWL | 35,513 |
| OLAELEC | 19,555 |
| AEQUS | 14,898 |
| FIRSTCRY | 11,264 |
| … (incl. MTNL, UNITECH) | … |

A momentum/market-cap strategy that Trendlyne runs against the full market *would* pick these; we
could never reproduce that because they did not exist in our universe.

## Decision

Add a **fallback share-count source** for any name that has no EPS-derived shares:

```
shares_cr = stocks.mcap (current snapshot) / latest adjusted close
```

This reuses the **exact identity** the pipeline already relies on
(`mcap = adjusted_close × current_shares`); it only changes where `current_shares` comes from when
EPS is unusable. Profitable names are untouched (the fallback fires only when the EPS path produced
nothing). The fix lives in the canonical builder `scripts/rebuild_pit_mcap_ca.py` so every future
rebuild reproduces it.

The NSE-only gate (adr-024) still applies: of the 19, BSE-only / InvIT names (RIIT, CITIUSINVT,
ANZEN) remain correctly excluded; ~14 NSE-EQ names become eligible.

## Consequences

- **Positive:** profitless IPOs/growth names now enter the universe with a real, point-in-time mcap;
  Trendlyne-parity coverage improves on momentum and mcap-banded strategies.
- **Limitation (documented, second-order):** like the existing EPS path, `current_shares` is held
  constant back through history, so share issuance/buyback over time is not separately modelled.
  Immaterial vs. the all-or-nothing exclusion this fixes, and vs. the mcap membership threshold.
- **Honest non-fix:** the numeric-token gold rows (14060423 / 17160453 / 542012) are *not* resolved
  by this change — they have no symbol/ISIN in any of our stores and need a Trendlyne source-side
  lookup or are accepted as gold-source noise (iter-12 Item 3).

## Application

Applied surgically to the 19 affected **live** pks (insert into `pit_shares`, `pit_mcap`,
`universe_membership`) rather than via a full recompute, because `trendlyne.duckdb` predates the
latest `bhavcopy.duckdb` and a full rebuild would have shifted dead-name mcaps beyond this change's
intended scope. The surgical insert uses the identical formula as the edited canonical builder, so a
future full rebuild reproduces the same state.
