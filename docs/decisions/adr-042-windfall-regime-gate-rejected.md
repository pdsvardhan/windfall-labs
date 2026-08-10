# adr-042 — The MA100 regime gate fails its own adoption gate — rejected for the live books by walk-forward

- **Status:** accepted
- **Date:** 2026-08-10
- **Tags:** curated, cat:product
- **Iteration:** iter-147 (item 934)

## Context

adr-041 measured the MA100 binary index-regime gate as the first risk overlay to survive honest
measurement (full-period MaxDD cut 12–24pp at ~0 Sharpe cost) and recorded it as a CANDIDATE
with a pre-declared adoption bar: *the gated configs must pass the same walk-forward gate the
plain strategies passed* (adr-040: 3y IS / 1y OOS rolling folds, grid={}, robust = OOS/IS ≥ 0.5
on Sharpe). iter-147 ran that gate — 16 walk-forwards (4 deployables × plain/gated × sharpe/cagr),
both arms on identical current data. Harness + full report:
`docs/validation/regime_gate_walkforward_iter147.md` (+ raw per-fold outputs alongside).

## Finding — the gate flatters in-sample and degrades out-of-sample, on every strategy

| strategy | plain OOS/IS (sharpe) | gated OOS/IS (sharpe) | gated verdict |
|---|---|---|---|
| DVM_user | 0.86 | **0.36** | **FAIL (likely-curve-fit)** |
| DVM_dm_m_20 | 0.80 | 0.55 | marginal |
| MOM_roc252_m_20 | 0.88 | 0.55 | marginal |
| CMP_valmom_m_20 | 0.94 | 0.55 | marginal |

The gate RAISES in-sample Sharpe and LOWERS out-of-sample Sharpe on all four books — the
overfit signature the walk-forward exists to catch. On the CAGR lens all arms are robust
(0.92–0.97): OOS returns persist; OOS *risk-adjusted* edge does not — the gate's whipsaw
variance shows up out-of-sample in ways the in-sample period didn't charge. Verifier-noted
sensitivity: DVM_user's outright fail includes a truncated final fold (todo #251); excluding it
the ratio is 0.74 vs plain 1.04 — direction unchanged.

## Decision

**The MA100 gate is NOT enabled at the 1 Sep rebalance (or after, under the current bar).**
The paper books stay ungated. The 55–75% full-period drawdown remains the accepted, stated
risk of the deployables — now with three risk-overlay classes measured and rejected
(stops adr-039, own-equity timing adr-033/034, index regime gate here).

The fold-averaging caveat (1y OOS windows rarely contain the crashes a tail hedge exists for)
is recorded in the study and deliberately NOT used to overturn the result — the bar was
declared before running, exactly so results couldn't renegotiate it.

## Consequence

- #103's drawdown-mitigation path via this gate is closed as measured. Remaining levers, each
  requiring a pre-declared design + ADR before any run counts as an adoption gate:
  vol-targeting position sizing (the one class still unmeasured), or a crash-conditional /
  regime-stratified evaluation that prices tail protection explicitly.
- Partial adoption (gating only the three 0.55 books) is an owner option the study records but
  does not recommend — it trades proven 0.80–0.94 robustness for marginal passes.
- adr-041's full-period DD measurement stands as fact; what died is its ride to real money.
