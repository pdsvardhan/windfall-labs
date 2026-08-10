# adr-041 adoption gate: walk-forward of the MA100-gated configs — iter-147, 2026-08-10

**Verdict up front: DO NOT ADOPT the MA100 gate at the 1 Sep rebalance.** The gated configs do
not pass the walk-forward gate the plain strategies passed — one fails outright, three scrape
the bar while their plain arms sail over it. Full reasoning below; the declared bar is honored
as written, not reinterpreted after the results.

## What ran

adr-041 recorded the MA100 binary index-regime gate as an adoption-ready CANDIDATE (full-period
DD cut 12–24pp at ~0 Sharpe cost) with an explicit adoption path: *"Walk-forward the GATED
configs (same 3y/1y protocol as adr-040) — the overlay must pass the same gate the plain
strategies passed."* This is that run (todo #249, iteration 147 item 934).

- Protocol: `POST /api/walkforward`, 3y IS / 1y OOS rolling folds, `grid={}` (deployed configs
  are locked — the honest question is edge persistence, not parameter fitting), 8 folds each.
- Robustness bar (adr-040): **OOS/IS ≥ 0.5 on Sharpe**.
- Both arms re-run on identical current data (prices to 2026-08-08, Trendlyne factors to
  2026-07-08) rather than comparing against the 2026-07-17 numbers — data had advanced.
- A CAGR-metric pass was run as a second lens (same folds, same configs).
- Harness: `docs/validation/walkforward_gated_iter147.py` →
  `walkforward_gated_run-2026-08-10.txt` (sharpe) / `walkforward_gated_run-2026-08-10_cagr.txt`.

## Results — Sharpe (the declared bar)

| strategy | plain OOS/IS | gated OOS/IS | plain verdict | gated verdict |
|---|---|---|---|---|
| DVM_user | **0.86** (0.952→0.818) | **0.36** (0.995→0.355) | robust | **likely-curve-fit — FAIL** |
| DVM_dm_m_20 | **0.80** (1.116→0.889) | 0.55 (1.232→0.682) | robust | marginal pass |
| MOM_roc252_m_20 | **0.88** (1.217→1.068) | 0.55 (1.377→0.762) | robust | marginal pass |
| CMP_valmom_m_20 | **0.94** (0.971→0.915) | 0.55 (1.020→0.563) | robust | marginal pass |

Note the shape of the failure: **the gate RAISES in-sample Sharpe on every strategy and LOWERS
out-of-sample Sharpe on every strategy.** Looks-better-in-sample + worse-out-of-sample is the
textbook overfit signature the walk-forward gate exists to catch.

## Results — CAGR (second lens)

| strategy | plain OOS/IS | gated OOS/IS |
|---|---|---|
| DVM_user | 0.85 | 0.97 |
| DVM_dm_m_20 | 0.94 | 0.93 |
| MOM_roc252_m_20 | 0.94 | 0.92 |
| CMP_valmom_m_20 | 1.02 | 0.93 |

All eight arms robust on CAGR. Read together with the Sharpe table: **the gated books' OOS
returns persist; their OOS risk-adjusted returns do not.** Out-of-sample, the gate keeps the
return level but adds variance relative to what in-sample suggested — whipsaw timing costs that
the smooth in-sample period didn't charge.

## Honest protocol caveat (recorded, not used to move the bar)

A regime gate's benefit is concentrated in rare crash regimes (2008, 2020). Fold-averaged 1y
OOS windows mostly contain no crash, so the protocol charges the gate its whipsaw cost every
fold and credits its tail protection almost never. The walk-forward is structurally unkind to
tail-protection overlays. This is a real limitation — AND the bar was declared before running
(adr-041), precisely so results couldn't renegotiate it. adr-039 held stops to the same
standard. If tail protection is to be valued properly, that needs a *new, pre-declared*
evaluation design (see paths forward), not a post-hoc reinterpretation of this one.

## Recommendation (owner decision input, todo #249)

1. **Do not enable the gate at the 1 Sep rebalance.** DVM_user-gated outright fails; the other
   three trade 0.80–0.94 proven OOS robustness for 0.55 marginal passes. The paper books stay
   ungated; drawdown remains the accepted, known risk (55–75% full-period).
2. **The full-period DD-cut finding of adr-041 stands** — it measured what it measured. What
   this run adds: that protection does not come with fold-level OOS persistence, so it cannot
   ride to real money under the current gate.
3. Paths forward, each requiring a pre-declared design + ADR before any run is treated as an
   adoption gate:
   - crash-conditional evaluation (e.g. gated vs plain on the untouched 2007–2016 decade
     including 2008, or regime-stratified folds) — values tail protection explicitly;
   - position-sizing overlays (vol-targeting) — the one risk-lever class still unmeasured;
   - accept drawdown and size real-money capital accordingly (the do-nothing option is a
     legitimate owner choice and costs nothing).

## Provenance

- Runs: 16 walk-forwards (4 strategies × 2 arms × 2 metrics), 8 folds each, via the live API
  against the deployed engine (old image — engine code untouched by this iteration's branch).
- Raw per-fold detail in both `.txt` outputs alongside this file.
- Related: adr-039 (stops rejected by measurement), adr-040 (plain WF gate passed),
  adr-041 (gate candidate), adr-033/034 (own-equity timing rejected).
