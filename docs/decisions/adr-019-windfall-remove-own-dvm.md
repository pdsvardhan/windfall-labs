# Remove the homegrown D/V/M — use raw fundamentals + Trendlyne DVM directly

*Status: accepted · 2026-06-21 · iter-31*

The homegrown durability_own/valuation_own/momentum_own scores (adr-010) only approximated Trendlyne's DVM (~0.44-0.88 rank-correlation) and added a parallel path to maintain. Decision: remove own-DVM entirely (scores + formula + validation harness + endpoint). Strategies now screen on raw survivorship-free fundamentals (roe/roa/opm/np_qtr_yoy/pe/pb) or Trendlyne's own daily DVM (tl_*). Supersedes adr-010.
