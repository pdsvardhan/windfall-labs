# adr-034 — Faster re-engagement tested: own-equity factor-timing still does not beat plain momentum, so it is dropped as the primary risk control

- **Status:** accepted
- **Date:** 2026-06-26
- **Tags:** curated, cat:reliability
- **Iteration:** iter-17 (resolves the open question in adr-033)

## Context

adr-033 found that the MA100 self-timing overlay, built in-engine with real costs, *hurt* the momentum
sleeve, and left an open question: was that just because the overlay re-engaged only at the monthly
rebalance and so missed the sharp recoveries right after momentum bottoms? iter-17 added an opt-in
**bidirectional weekly re-engagement** (`factor_timing.reengage_weekly`): on a weekly check the
overlay can now re-enter the most recent monthly selection when it flips back on, not just de-risk.

## Decision — the experiment's verdict

Re-tested MOM_roc252 (monthly, n=10, survivorship-free, ADTV floor, 2016-06 → 2026-06, ₹10L):

| Variant | CAGR | Sharpe | MaxDD | Exposure |
|---|---|---|---|---|
| **Plain (no overlay)** | **38.7%** | **1.26** | −49.5% | 98% |
| MA100 monthly (iter-16) | 18.4% | 0.83 | −46.3% | 60% |
| MA100 weekly de-risk only | 18.3% | 0.89 | **−38.0%** | 56% |
| MA100 weekly **re-engage** (iter-17) | 23.5% | 1.04 | −49.5% | 65% |

Re-engagement works exactly as designed — it recovers CAGR (18.4% → 23.5%) and Sharpe (0.83 → 1.04)
by catching the recoveries the monthly version slept through. **But it hands the drawdown protection
straight back** (−49.5%, identical to plain): re-entering fast means you are also back in for the next
leg down. The trade-off is fundamental: you can have lower drawdown (de-risk-only, −38%) *or* more of
the return back (re-engage), **never both**, and **no overlay variant beats plain momentum's Sharpe of
1.26.** Faster re-engagement fixed the *mechanism* but did not change the *conclusion*.

## Consequence

- **Own-equity factor-timing is dropped as the primary per-sleeve risk control.** It does not earn its
  CAGR cost on momentum at any cadence tested. Do not deploy MOM_roc252 + MA100.
- The feature stays in the engine — it is a validated, honest, look-ahead-safe tool (and may matter for
  a genuinely trending/defensive sleeve), but it is off the critical path to deployment.
- **Phase A pivots to the other lever:** rotation across genuinely *uncorrelated* sleeves + cash, where
  "cash when none are working" is the drawdown control instead of per-sleeve self-timing. Next: add a
  complementary value/defensive sleeve (low-vol `LV_atr` is the existing drawdown champ: ~−25% DD; or a
  dividend-yield / true-low-beta sleeve from Bucket B) so rotation has uncorrelated material — rotating
  two correlated momentum sleeves already cut DD to −34.8%, but real rotation value needs uncorrelated
  return streams. Then walk-forward the rotation and cost-stress it at ₹1L.

## Anti-gaslight note

Two iterations (16, 17) were spent disproving an attractive internal idea (the MA100 PoC). That is the
system working: the offline number was optimistic, the realistic engine said so, and the "obvious fix"
(faster re-engagement) was tested and also did not rescue it. Plain momentum + rotation-level cash is
the honest path, not a per-sleeve equity-timing overlay.
