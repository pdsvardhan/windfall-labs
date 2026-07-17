# Post-COVID 5y study + robustness protocol — run 2026-07-17

Chat-driven study (tracker iteration 94, item 651 will formalize display). Owner question:
"pre-COVID and COVID noise may not be relevant to current Indian markets — rank everything
on the last five years, then check the winners are real and not noise."

## Method

- Window: 2021-07-01 → 2026-06-16, benchmark NIFTY500 (+11.2% CAGR, Sharpe 0.81, MaxDD −18.8%).
- Pass 1 (`postcovid5y_slice.py`): all 198 stored sweep runs re-scored by slicing stored
  equity curves to the window. Warm-start + pre-audit data layer — ranking-grade only.
- Pass 2 (`postcovid5y_gapfill.py`): 91 configs with no stored runs (MOM/TRD/MR families)
  run fresh (cold start, save=False, today's data layer) + 6 cold-start validation re-runs
  of slice winners. Validation delta: fresh runs come in 4–8pp CAGR BELOW warm slices —
  treat slice absolutes as flattered; ranks broadly stable.
- Pass 3 (`postcovid5y_robustness.py`, user-approved full protocol): 11 family-diverse
  finalists × {5y, H1 2021-23, H2 2024-26, pre-COVID 2016-07→2021-07} all fresh, plus
  MA100/MA150 binary regime overlays on top 6. Persistence = 10 half-year segments vs
  benchmark. NOTE: configs have no tunable params, so walk-forward reduces to persistence
  analysis. The `correction` field in the robustness JSONL is buggy (mis-detects the
  Dec-24 episode) — ignore it; use maxdd + maxdd_dates + segment table instead.

## Verdicts (fresh numbers)

- SURVIVORS: DVM_all_w_10 (5y 36.2%/1.19/−33%, pre 43.2%/1.37, 8/10 halves beat bench,
  zero losing half-years), MOM_roc252_m_10 (38.9%/1.29, pre 41.9%/1.30, 8/10),
  DVM_all_m_10 (32.0%/1.11, pre 32.2%/1.13, 6/10).
- REGIME BETS (post-COVID only, fading): SZ_small_m_15 (H1 50.1% → H2 13.1%, pre 6.1%),
  SZ_small_m_20, VAL_ownpe_q_30 (pre 9.8%).
- NOISE/SUSPECT: VAL_ownpe_w_10 (H2 2.2%), TRD_golden_m_10 (lone 38% vs family median 14%).
- INCUMBENT FLAG: DVM_dm_m_20 H2 only 4.3% — consistent with last place on live paper book.
- Regime gate ON THIS WINDOW: hurts everything (~14pp CAGR for nothing — no bear market
  in-window) EXCEPT SZ_small_m_15 (Sharpe 1.29 → 1.68). Reconcile with adr-041: the gate
  is crash insurance; 5y windows without crashes cannot price it. Feeds todo 249, not a
  contradiction of it.
- MOM_relstr ≡ MOM_roc252 (identical rankings → identical results); deduped to roc252.

## Files

- `postcovid5y_slice.py` / `postcovid5y_slice_run-2026-07-17.json` — pass 1 harness + rows
- `postcovid5y_gapfill.py` / `postcovid5y_gapfill_run-2026-07-17.jsonl` — pass 2
- `postcovid5y_merge.py` / `postcovid5y_combined_run-2026-07-17.json` — combined ranking
- `postcovid5y_robustness.py` / `postcovid5y_robustness_run-2026-07-17.jsonl` — pass 3
- `postcovid5y_report.py` — verdict-table renderer

Owner decisions taken on the back of this study (iteration 94): simulated Jun-29 paper
series (live books untouched — backdating declined as look-ahead), and 3 survivor paper
books starting now as a separate cohort.
