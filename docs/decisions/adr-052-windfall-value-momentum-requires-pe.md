# adr-052 — The Value + Momentum paper book only buys companies with a positive P/E

- **Status:** accepted — shipped in iter-206 (Ottomate iteration 206, 2026-10-25); the owner delegated the call
  ("968 - you decide")
- **Date:** 2026-10-25
- **Tags:** curated, cat:product
- **Iteration:** iter-206 (Ottomate iteration 206, to-dos #968, #969, #956)

## Context

`CMP_valmom_m_20` ranks on `tl_pe` (ascending) plus 6-month momentum. The rank blend re-weights a missing factor
away, so a company with no P/E was ranked on momentum alone and could be bought. Measured in iteration 201 and
again on equal terms in iteration 206 (`docs/validation/free-pe-equal-terms-2026-10-25.md`): over ten years that
was 367 entries, about half loss-makers and four in ten companies that later delisted; since COVID about two-thirds
of the entries were loss-makers (ATHERENERG and BLUSPRING were held in the paper book on 2026-10-25).

Performance, banks/NBFCs out of every arm, repeats identical (CAGR): as configured 23.0% / 16.3% / 30.3%
(10 years / post-COVID / pre-COVID); Trendlyne P/E required 15.0% / 16.1% / 15.1%; free P/E required 18.2% /
16.6% / 17.4%. Since 2021 requiring a P/E costs nothing (16.3% vs 16.1%); the as-configured book's extra return
is the 2020–21 stretch. The as-configured book is not a momentum duplicate (9–20% holdings overlap with the
momentum-only book).

## Decision

1. **Require a positive P/E.** `CMP_valmom_m_20` gets the entry filter `tl_pe > 0`. A book called Value +
   Momentum buys companies it can value. The previous config is kept in
   `docs/validation/CMP_valmom_m_20.config-before-iter206.json`.
2. **Keep Trendlyne's P/E as the live source for now.** On equal terms the free (screener.in) P/E was at least as
   good (+3.2 / +0.5 / +2.3 CAGR points, better Sharpe). But it is an annual P/E, up to 16 months stale, and the
   store refreshes only May–September; changing the source of a live book on a backtest alone, and in the same
   step as the filter, would change two things at once.
3. **The follow-up that would swap the source** is the free trailing-twelve-month P/E from NSE filings
   (to-do #970, `docs/ops/nse-filings-ttm.md`): current, point in time, includes delisted companies, no
   restatement leak. When its data has landed: re-run the equal-terms test with it, run a walk-forward, and
   decide the swap in its own ADR.
4. **Not changed:** the engine-wide behaviour (a blend ranks a company with no value for one factor on the
   others). Every other roster book ranks on price or DVM scores and is unaffected. `_mask_uncovered` still
   masks only Trendlyne factors.

## Consequences

- The next monthly rebalance (1 Nov 2026) sells ATHERENERG and BLUSPRING, which have no positive P/E, and buys
  IDEA and TNPETRO instead of RBA; KAMDHENU stays. Seven other holdings that the as-configured book was also
  about to rotate out of still rotate out. Preview from `POST /api/signals` on 2026-10-23 data.
- The ten-year backtest of this book reads 15.0% (was 23.0% with the old config, 25.3% before banks were
  excluded and runs were made repeatable). It is the honest number for what the book now does.
- The paper-book card's rule line now says "positive P/E required". The card title/rules are still hardcoded
  per strategy id (#956 stays open: the roster cards do not yet derive from `GET /api/strategies`).
- Reversible: restore the saved config from the JSON above.
