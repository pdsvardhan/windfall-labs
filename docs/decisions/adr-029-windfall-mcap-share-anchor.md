# adr-029 — Anchor historical market cap to Trendlyne's own value, not a fragile NP/EPS share estimate

**Status:** accepted · **Date:** 2026-06-24 · **Source:** data audit 2026-06-24, finding F6

## Context
Point-in-time market cap is built as `mcap(t) = adjusted_close(t) × current_shares` (constant-shares identity, adr-026). `current_shares` was derived from `NP_TTM / EPS_TTM` (latest period). That estimate is unstable when EPS is near zero and meaningless for REITs/InvITs and some recent IPOs, which have no conventional EPS. The audit found 36 names diverging >50% from Trendlyne's own current market cap — the worst were **false-exclusions**: PRAJIND ₹6,259cr computed as ₹3cr, BAGMANE REIT ₹34,904cr → ₹62cr, TVSINVIT ₹2,288cr → ₹9cr — large, liquid names wrongly dropped from the survivorship-free universe (and a few, like NAZARA, over-inflated 5×).

## Decision
In `rebuild_pit_mcap_ca.py`, anchor `current_shares = stocks.mcap / last_close` (Trendlyne's own current market cap ÷ latest close) wherever `stocks.mcap` is present; fall back to the NP/EPS estimate only where it is absent. The latest cross-section then matches Trendlyne exactly, and the historical back-projection inherits a clean anchor.

## Consequences
- False-exclusions fixed: PRAJIND/BAGMANE/TVSINVIT/NAZARA current mcap now equals Trendlyne's to the rupee.
- Per name this is pure constant-scaling — it changes a mcap series' LEVEL, never its shape/returns — so it cannot introduce look-ahead (verifier proved ratio stddev = 0 across all days).
- Residual: megacaps with NULL `stocks.mcap` (e.g. ADANIPOWER) stay on NP/EPS and may still be off, but they are far above the ₹500cr floor so universe membership is unaffected.

## Verification
0 names left the universe (no regression); ever-universe 2102 → 2133; PRAJIND/BAGMANE/TVSINVIT/NAZARA ratio to Trendlyne mcap = 1.000.
