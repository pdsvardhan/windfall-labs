# adr-027 — Guard negative book value (P/B ≤ 0) so distressed stocks aren't ranked "cheapest"

**Status:** accepted · **Date:** 2026-06-24 · **Source:** data audit 2026-06-24, finding F1

## Context
`valuation_panel` already masked PE_TTM and PEG_TTM ≤ 0 → NaN (a negative P/E is not "cheap"; adr-023's negative-PE guard), but it deliberately left PBV (price-to-book) unmasked on the reasoning "negative book is rare and real." The audit found PBV_A ≤ 0 on ~30 names currently and 158 ever (133,675 daily rows) — accumulated losses wipe out book value and turn P/B negative. A `tl_pbv < N` filter then ADMITS those names, and an ascending "prefer-low P/B" rank ranks them as the absolute cheapest — i.e. a value strategy would preferentially buy companies with negative net worth.

## Decision
Mask `PBV_A ≤ 0 → NaN` in `valuation_panel`, identical to the PE/PEG guard. A `tl_pbv < N` filter now EXCLUDES negative-book names and the ascending rank no longer ranks them cheapest. Masking is per-cell (a name with negative book today but positive book historically keeps its valid history).

## Consequences
- P/B value strategies are no longer silently corrupted by distressed names.
- Extreme-HIGH PBV (near-zero book) is left as-is — it self-protects (ranks last on an ascending rank, excluded by `< N`).
- No data is altered; this is a read-time engine guard (`trendlyne_store.py`).

## Verification
Independent verifier: RELIANCE/TCS keep all positive PBV; MTNL (negative net worth, was admitting at −4.2) is fully masked to NaN; masking is surgical per-cell, not column-wide.
