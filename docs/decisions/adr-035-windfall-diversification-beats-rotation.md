# adr-035 — Diversification beats rotation: a fixed 70/30 momentum/low-vol blend is the first deployable candidate

- **Status:** accepted
- **Date:** 2026-06-26
- **Tags:** curated, cat:reliability
- **Iteration:** iter-18 (continues the Phase A pivot from adr-034)

## Context

adr-034 dropped per-sleeve factor-timing and pointed Phase A at the user's other idea: run 2-3
strategies + cash and "rotate to whichever is working, cash when none are." iter-18 built a
complementary defensive sleeve and tested that rotation honestly.

**Low-vol sleeve (`LV_atr`, rank by `atr14/close` ascending, same universe):** CAGR 7.6%, Sharpe 0.68,
MaxDD −29.7%, vol 12% — a genuine defensive sleeve. Daily-return correlation with MOM_roc252 is **0.42**
(moderate), but asymmetric: in the 2018 momentum drawdown LV fell −6% while MOM fell −26%.

## Decision 1 — Trailing-return rotation does NOT work; it underperforms plain momentum

Ranking sleeves by trailing return and rotating the book to the leaders (lookback 63–126d, monthly)
**whipsaws** — it is itself a momentum bet on sleeves, buying whichever just ran up and getting caught
in the reversal:

| Variant | CAGR | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|
| plain MOM_roc252 (bar) | 38.7% | **1.26** | −49.5% | **0.78** |
| rotation top_k=1 lb=63 | 22.0% | 0.97 | −59.4% | 0.37 |
| rotation top_k=all lb=126 | 16.2% | 0.91 | −46.2% | 0.35 |

Every rotation variant is worse than plain momentum on Sharpe AND Calmar, several with *worse*
drawdown. A cash-overlay version looked good only at lookback 189 while 126/252 were far worse — a
curve-fit smell. **Trailing-return sleeve rotation is rejected.**

## Decision 2 — A fixed static blend DOES work; 70/30 is the deployable candidate

Holding a *fixed* MOM/LV allocation (no chasing), rebalanced monthly, validated in-engine with real
costs (turnover ~0.1x — the sleeves drift together, so inter-sleeve rebalancing barely trades):

| Allocation | CAGR | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|
| 100% MOM (bar) | 38.7% | 1.26 | −49.5% | 0.78 |
| **70/30 MOM/LV** | **29.5%** | **1.27** | **−42.7%** | 0.69 |
| 60/40 MOM/LV | 26.4% | 1.27 | −40.4% | 0.65 |

Adding 30% low-vol **raises** Sharpe (1.26 → 1.27) while cutting MaxDD ~7pp — diversification, not
timing. It is **robust** (split-half: Sharpe 1.25 / 1.29; DD −42.7% / −30.4% vs pure −49.5% / −38.8%
in H1/H2) and has **zero tunable degrees of freedom** (a fixed weight, nothing to overfit). It holds
at the real ₹1L deployment scale (Sharpe 1.25 = plain, MaxDD −43.4% vs plain −50.1%).

## Consequence

- **The Phase A deliverable is a fixed-weight static blend, NOT rotation.** Rotation (trailing-return)
  stays in the engine but is off the deploy path; the rotation module gained a `weights` fixed-blend
  mode so the 70/30 blend is a first-class, cost-accurate, deployable artifact (`POST /api/rotation`
  with `weights:[0.7,0.3]`).
- Plain momentum still has the highest CAGR (38.7%) and Calmar (0.78); the blend trades ~9pp CAGR for
  a materially gentler, more *holdable* drawdown at the same risk efficiency — the right trade for real
  retail money.
- **Next:** wire the 70/30 blend into live "today's orders" (the signals path) so it is deployable;
  consider whether a third uncorrelated sleeve (value/quality) widens the frontier; then the dry-run.

## Anti-gaslight note

The user's stated instinct ("rotate to what's working + cash") was tested honestly and found *worse*
than a plain static blend. The recorded result follows the evidence, not the original hypothesis.
