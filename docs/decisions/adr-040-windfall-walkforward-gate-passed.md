# adr-040 — The five deployed strategies pass the walk-forward gate, and the adr-035 blend headline reproduces (iter-20's discrepancy was a holdings mismatch)

- **Status:** accepted
- **Date:** 2026-07-17
- **Tags:** curated, cat:reliability
- **Iteration:** iter-23 (items 633 + 634)

## Context

adr-006 and the locked must_have say **"no strategy is approved for live signals until a
walk-forward shows acceptable in-sample vs out-of-sample degradation"** — yet the five strategies
paper-trading since 2026-07-06 went live without one. Separately, iter-20 and iter-21 both flagged
that adr-035's 70/30 headline (29.5% CAGR / 1.27 Sharpe / −42.7% MaxDD) "does not reproduce from
the saved sleeves" (observed 22.9–28.4% / 1.09–1.24) — an unreproducible deployable headline, the
exact Trendlyne sin this platform exists to kill. Both debts are settled here, on the current
(post-audit, post-refresh) data layer. Harnesses + raw outputs:
`docs/validation/walkforward_iter23.py` / `blend_parity_iter23.py` / `*_run-2026-07-17.txt`.

## Decision 1 — every deployed strategy passes the gate (rolling 3y IS / 1y OOS, metric Sharpe)

| Strategy | folds | IS avg | OOS avg | OOS/IS | verdict |
|---|---|---|---|---|---|
| DVM_user | 8 | 0.952 | 0.818 | **0.86** | robust |
| DVM_dm_m_20 | 8 | 1.116 | 0.889 | **0.80** | robust |
| MOM_roc252_m_20 | 8 | 1.217 | 1.068 | **0.88** | robust |
| CMP_valmom_m_20 | 8 | 0.970 | 0.916 | **0.94** | robust |
| LV_atr_m_10 (blend sleeve) | 8 | 0.488 | 0.391 | **0.80** | robust |
| MOM_roc252 gridded n∈{10,15,20,25} | 8 | 1.385 | 0.981 | **0.71** | robust |

All six clear the ≥0.5 OOS/IS bar by a wide margin; the locked configs' edges persist
out-of-sample across eight rolling folds. The gridded run (0.71 vs 0.88 fixed) shows mild
holdings-choice overfit — fitting n in-sample buys IS Sharpe that partially evaporates OOS,
which is why the deployed configs keep n FIXED.

**Untouched-decade evidence:** MOM_roc252 (m, n=10) run over 2007-01-01→2016-06-10 — a decade no
design decision ever touched, containing the 2008 crash — earns **CAGR 22.0% / Sharpe 1.03 /
MaxDD −30.1%** at 67% exposure on the survivorship-free layer (972 names ever >₹500cr in-window;
76 ca_uncertain flagged). The momentum edge is not a 2016–2026 bull-decade artifact.

## Decision 2 — the adr-035 headline reproduces; iter-20 compared the wrong sleeves

Re-run from the SAVED sleeves on today's data layer (rotation endpoint, ₹10L, monthly):

| Run | CAGR | Sharpe | MaxDD | adr-035 said |
|---|---|---|---|---|
| 70/30 MOM_m_10 + LV_m_10 (stored) | **30.1%** | **1.29** | −45.3% | 29.5% / 1.27 / −42.7% |
| 60/40 stored | 26.6% | 1.27 | −43.3% | 26.4% / 1.27 / −40.4% |
| 70/30 with **n=20** sleeves | 23.1% | 1.13 | −48.2% | — |
| 70/30 with ad-hoc atr14 LV (as adr-035's text describes) | 30.4% | 1.30 | −44.2% | — |
| MOM_m_10 solo (direct) | 40.7% | 1.31 | −51.0% | 38.7% / 1.26 / −49.5% |
| LV_m_10 solo (direct) | 5.6% | 0.53 | −35.3% | 7.6% / 0.68 / −29.7% |

The headline reproduces to within 0.6pp CAGR / 0.02 Sharpe. **The iter-20 "non-reproduction"
(22.9–28.4% / 1.09–1.24) is exactly what n=20 sleeves produce** — iter-20 rotated the wrong
holdings variant. Residual deltas vs the ADR (−45.3 vs −42.7 DD; LV sleeve softer) are the
audit-corrected data layer (F1–F6 + the merged refresh), all in the honest direction. The stored
atr20-vs-ADR-text-atr14 discrepancy is immaterial (30.1 vs 30.4).

## Consequence

- The adr-006 gate debt on the live paper run is **cleared** — with evidence, not assertion.
- adr-035's headline is confirmed current; the twice-carried parity debt closes.
- Two rotation-endpoint nits found: single-sleeve `weights:[1.0]` returns 400 (harness fell back
  to direct backtests), and rotation summaries return `calmar` as 0 — filed as a todo.
