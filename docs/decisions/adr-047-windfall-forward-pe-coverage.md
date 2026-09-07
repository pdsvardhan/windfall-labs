# adr-047 — Forward PE is harvested but not wired as a factor: coverage collapses below ₹2,000cr, where the books trade

- **Status:** accepted
- **Date:** 2026-09-08
- **Tags:** curated, cat:product
- **Iteration:** iter-173

> **Corrected 2026-09-08, same day, after independent verification.** The first version of this ADR
> reported coverage of **19.5%** on live holdings and claimed the harvest "fetched all of it".
> Both were wrong, in the direction that flattered this decision. The harvest used the base screener,
> which silently drops the top ~100 index names — a defect this repo already documents in
> `harvesters/README.md` and for which `trendlyne_harvester_megacap.js` exists. So RELIANCE,
> HDFCBANK, LT, TITAN, ICICIBANK and ~90 others were never requested, and 12 of the 77 live holdings
> were counted as *uncovered* when they had never been *asked*. The megacap list has since been run
> through the same endpoint and ingested (+4,832 rows). Every number below is the corrected one.
> The decision did not change; the margin behind it did, and one book's picture changed materially.

## Context

To-do #26 has carried the same hypothesis since June: the valuation score is stuck at a 0.44
correlation against Trendlyne's own V-score because **1Y forward PE** is missing from our factor
set. The column exists in Trendlyne's Data Downloader menu, so the fix looked like a data chore.

It is not exportable. Measured 2026-09-07: **2,235 of 2,235** cells in the
`Forecaster Estimates 1Y forward PE` column read the literal string `Export NA`, across both
parameter sets and all five market-cap bands. Trendlyne blocks Forecaster fields from export and
says so on the page. To-do #857 was opened to get it another way.

That worked, and more cleanly than expected. The Forecaster page is **server-rendered** — there is
no XHR to intercept — and the whole estimate set ships inside the document as HTML-escaped JSON on
`<div id="consensus-details" data-consensusjson="…">`. The URL wildcards its slug, so `pk` alone
addresses it. A plain credentialed `fetch` is enough: no API token, no headless browser, no
WAF-fragile endpoint. (The bulk route was checked and ruled out: the screener's `try-aio` returns a
fixed 20 columns and rejects `forwardpe`/`fwdpe`/`pefwd1y`/`epsest1y` in its query DSL.)

`harvesters/trendlyne_harvester_forecaster.js` plus the megacap top-up fetched **2,005 stocks**,
0 errors, 0 rate-limits, **43,153 rows**, ingested insert-only by `scripts/ingest_forecaster.py`.

## The measurement that decided it

**813 of 2,005 probed stocks (40.5%) have a forward EPS estimate.** Banded strictly against the
₹500cr universe (2,009 names by newest `pit_mcap`, of which 51 remain unprobed — 43 of those in the
bottom band):

| Market cap | Covered | Probed | In universe | % of universe |
|---|---|---|---|---|
| > ₹50,000cr | 186 | 202 | 206 | 90.3% |
| ₹10,000–50,000cr | 296 | 388 | 390 | 75.9% |
| ₹2,000–10,000cr | 281 | 630 | 632 | 44.5% |
| ₹500–2,000cr | **50** | 738 | 781 | **6.4%** |

Coverage does not decline gently — it collapses. Below ₹2,000cr it is effectively absent, and that
band is 39% of the universe. This is the structural finding, and it is the one number the megacap
error never touched.

Of the **77 distinct names the eight live books re-entered on 2026-09-08**, 74 resolve to a pk and
all 74 were probed. **27 are covered — 36.5% of probed, 35.1% of all 77:**

| Book | Covered / probed | Notes |
|---|---|---|
| BLEND_70_30 | 20 / 38 — 52.6% | 2 names unresolvable |
| DVM_user | 3 / 10 — 30.0% | |
| DVM_dm_m_20 | 5 / 19 — 26.3% | 1 unresolvable |
| MOM_roc252_m_20 | 4 / 18 — 22.2% | 2 unresolvable |
| DVM_all_w_10 | 2 / 10 — 20.0% | |
| DVM_all_m_10 | 2 / 10 — 20.0% | |
| CMP_valmom_m_20 | 3 / 20 — 15.0% | |
| MOM_roc252_m_10 | **0 / 8 — 0.0%** | 2 unresolvable |

## Decision

**Harvest and ingest forward estimates; do not wire a `fwd_pe` factor.**

1. The harvester and the merge-only ingest ship. `forecaster_estimates` accumulates snapshots and is
   available for research.
2. No `fwd_pe` factor is registered, and the existing (empty) `fwd_pe` mapping in
   `windfall/data/fundamentals.py` stays unwired. Nothing ranks on this data today.
3. **#26 is not closed by #857, and its premise is in doubt.** For the small-cap names these
   strategies buy, Trendlyne has no forward PE either — so whatever its V-score is built from, it is
   not analyst consensus. The next move is to re-measure the ceiling on the 813 covered names alone:
   if valuation-score correlation is materially better there, the hypothesis survives for large caps
   and dies for small ones. If not, forward PE was never the missing input.

The corrected numbers weaken the case but do not overturn it. Six of eight books sit at 0–30%
coverage, and a factor null for three names in four cannot rank them.

**The honest exception is BLEND_70_30 at 52.6%**, which the 19.5% figure had buried. More than half
its book is covered, because it holds the large caps the base screener had been dropping. A
forward-PE factor is *arguable* there — and only there. That is not a reason to wire it globally; it
is a reason for a scoped experiment, which #867 should now cover explicitly.

## Consequences

- The 0.44 ceiling stays unexplained — an honest open question rather than a to-do with a presumed
  fix attached.
- We hold a growing point-in-time record of analyst expectations. Each row carries both the period
  it forecasts and the date we learned it, so revisions read as revisions. Today it is one snapshot
  and cannot support a backtest at all.
- **Any harvest built on the base screener must run the megacap companion**, or it silently omits
  the ~100 largest names. That is now stated in this ADR, the ingest docstring and the README,
  because it was documented in exactly one place and still cost this decision a wrong headline.
- A future factor built on this table must declare its coverage the way adr-045 made forward-filled
  factors declare their age. A strategy silently dropping two names in three is the failure mode to
  design against.
- Target price and analyst counts came along in the same fetch and are available, though unread.

## Alternatives rejected

- **Wire `fwd_pe` anyway and let missing values fall through.** Rejected: on `MOM_roc252_m_10` every
  holding is uncovered, so the factor is not sparse but empty. The strategy would keep running and
  quietly stop being the one that was walk-forward tested (adr-040).
- **Restrict the affected strategies to the covered universe.** Rejected as a side effect of a data
  change. Narrowing to large/mid caps is a real strategy decision needing its own walk-forward
  evidence, not a consequence of which names analysts follow.
- **Compute our own forward EPS by extrapolating trend.** Rejected: that is a model wearing a data
  label. adr-019 removed the homegrown D/V/M for the same reason.
