# adr-041 — The index MA100 regime gate is the first risk overlay to survive honest measurement — recorded as a candidate, not adopted

- **Status:** accepted
- **Date:** 2026-07-17
- **Tags:** curated, cat:product
- **Iteration:** iter-23 (item 635)

## Context

Every prior attempt at taming the 55–75% drawdowns was measured and rejected: own-equity
factor-timing halves CAGR (adr-033/034), trailing stops turn every strategy negative (adr-039),
fixed-pct stops are cosmetic (adr-039). adr-039 closed with: *"drawdown remains unaddressed and is
the real risk item... a regime-overlay and position-sizing question"* — blocking the real-money
path (#103). The one built-in lever never measured on the deployables was the engine's
**index-based** `regime_filter`: benchmark (NIFTY500) vs its own moving average — a market-level
gate, not the self-referential equity gate adr-033 rejected. iter-23 measured it, full costs,
direct per-variant resolves (the batch endpoint rightly refuses regime grids since #219).
Adoption bar declared before running (single-commit provenance, verifier-confirmed): **MaxDD cut
≥ 10pp at Sharpe cost ≤ 0.10** — at least as strict as the implicit standard stops faced (adr-039
rejected an 8pp cut at 0.02 Sharpe cost as "a drawdown preference, not an improvement"; it never
wrote a numeric bar, so this one is stated explicitly here). Harness: `docs/validation/regime_study_iter23.py` + `regime_study_run-2026-07-17.txt`.

## Finding — MA100 binary (de-risk to cash below the MA) clears the bar on ALL FOUR strategies

| Strategy | off: CAGR/Sharpe/MaxDD | ma100_bin: CAGR/Sharpe/MaxDD | DD cut | Sharpe cost |
|---|---|---|---|---|
| DVM_user | 33.9% / 1.17 / −74.7% | 25.6% / 1.12 / −56.8% | **+18.0pp** | 0.05 |
| DVM_dm_m_20 | 30.5% / 1.23 / −56.4% | 26.3% / **1.33** / −44.5% | **+11.8pp** | **−0.10 (improves)** |
| MOM_roc252_m_20 | 30.9% / 1.16 / −55.0% | 24.5% / **1.20** / −30.9% | **+24.1pp** | **−0.04 (improves)** |
| CMP_valmom_m_20 | 25.1% / 0.99 / −64.5% | 19.3% / 0.98 / −47.0% | **+17.5pp** | 0.01 |

Slower gates confirm the response is structural, not a lucky period: MA150 keeps most of the DD
cut (DVM_dm clears the bar outright, MOM sits exactly on it), MA200-binary cuts DD but pays
0.12–0.25 Sharpe, and MA200-half/scale are gentler on both axes. Monotone in gate speed — the
faster gate exits earlier and re-enters earlier, which is where both the DD cut and the small
whipsaw cost come from. The price is real and stated: **5–8pp CAGR** and exposure ~0.66–0.74
(cash roughly a third of the time).

Why this survives where the others died: stops act per-name on noisy paths and fight the monthly
re-rank (adr-039); own-equity timing reacts to the book's own drawdown after the fact and
re-enters late (adr-033/034); the index gate keys on the market state that momentum-style books
actually inherit their crashes from, trades only at the same monthly/weekly cadence the book
already trades, and costs almost nothing in risk-adjusted terms.

## Decision

**Recorded as an adoption-ready CANDIDATE. No live config changes in this iteration.** Flipping
the paper strategies mid-experiment would re-baseline the running dry-run (the same reason
adr-038 deferred next-open entries), and gate-period choice (100 best of 100/150/200) deserves
one more honesty check before real money follows it.

Adoption path (owner decision):
1. Walk-forward the GATED configs (same 3y/1y protocol as adr-040) — the overlay must pass the
   same gate the plain strategies passed.
2. If robust: enable at the 1 Aug rebalance alongside the next-open switch (todo 248) so the
   paper run's second month measures the gated book cleanly.

## Consequence

- **#103's drawdown blocker now has a measured, affordable mitigation** — the question changed
  from "can drawdown be cut without killing the edge" (yes, measured) to "does the owner accept
  ~6pp CAGR + a third of the time in cash for 12–24pp less drawdown".
- The paper cockpit keeps tracking the ungated books; nothing about the live run changed.
- Follow-up todos: walk-forward the gated configs; owner adoption decision before 1 Aug.
