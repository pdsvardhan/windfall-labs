# adr-047 — Forward PE is harvested but not wired as a factor: analyst coverage reaches 19.5% of what the books hold

- **Status:** accepted
- **Date:** 2026-09-08
- **Tags:** curated, cat:product
- **Iteration:** iter-173

## Context

To-do #26 has carried the same hypothesis since June: the valuation score is stuck at a 0.44
correlation ceiling against Trendlyne's own V-score because **1Y forward PE** is missing from our
factor set. The column exists in Trendlyne's Data Downloader menu, so the fix looked like a data
chore — export it, ingest it, rank on it.

It is not exportable. Measured 2026-09-07: every one of **2,235 of 2,235** cells in the
`Forecaster Estimates 1Y forward PE` column reads the literal string `Export NA`, across both
parameter sets and all five market-cap bands. Trendlyne blocks Forecaster fields from export and
says so on the page. To-do #857 was opened to get it another way.

That worked, and more cleanly than expected. The Forecaster page is **server-rendered** — there is
no XHR to intercept — and the entire estimate set ships inside the document as HTML-escaped JSON on
`<div id="consensus-details" data-consensusjson="…">`. The URL wildcards its slug, so `pk` alone
addresses it. A plain credentialed `fetch` is enough: no API token, no headless browser, no
WAF-fragile endpoint. (The bulk route was checked and ruled out: the screener's `try-aio` endpoint
returns a fixed 20 columns and rejects `forwardpe`/`fwdpe`/`pefwd1y`/`epsest1y` in its query DSL,
so it must be one request per stock.)

So the data is now reachable, and `harvesters/trendlyne_harvester_forecaster.js` fetched all of it:
1,910 stocks, 0 errors, 0 rate-limits, 38,321 rows, ingested by `scripts/ingest_forecaster.py`.

## The measurement that changed the decision

Analyst coverage is not a detail here. It is the whole answer.

Of 1,910 stocks in the ₹500cr universe, **725 (38.0%)** have a forward EPS estimate at all:

| Market cap | Stocks with a forward EPS estimate |
|---|---|
| > ₹50,000cr | 98 / 108 — 90.7% |
| ₹10,000–50,000cr | 296 / 388 — 76.3% |
| ₹2,000–10,000cr | 281 / 630 — 44.6% |
| ₹500–2,000cr | **50 / 775 — 6.5%** |

Analysts do not cover small caps. And small caps are what these strategies buy. Of the **77
distinct names the eight live paper books re-entered on 2026-09-08**, only 15 have a forward
estimate — **19.5%**:

| Book | Covered |
|---|---|
| DVM_user | 3 / 10 |
| DVM_dm_m_20 | 4 / 20 |
| MOM_roc252_m_20 | 4 / 20 |
| CMP_valmom_m_20 | 2 / 20 |
| MOM_roc252_m_10 | **0 / 10** |
| DVM_all_w_10 | 2 / 10 |
| DVM_all_m_10 | 2 / 10 |
| BLEND_70_30 | 10 / 40 |

A ranking factor that is null for four names in five cannot rank the book. It would not improve
those strategies; it would **silently shrink their universe** to the large/mid-cap subset that
happens to have coverage — a scope change disguised as a factor addition, and precisely the kind of
invisible narrowing that adr-046 was written to stop.

## Decision

**Harvest and ingest forward estimates; do not wire a `fwd_pe` factor.**

1. The harvester and the merge-only ingest ship. `forecaster_estimates` accumulates snapshots and is
   available for research.
2. No `fwd_pe` factor is registered, and `windfall/data/fundamentals.py`'s existing (empty) `fwd_pe`
   mapping stays unwired. Nothing ranks on this data today.
3. **#26 is not closed by #857, and its premise is now in doubt.** Forward PE cannot be the
   explanation for the 0.44 ceiling on the names we trade, because for those names Trendlyne has no
   forward PE either — whatever their V-score is built from, it is not analyst consensus. The next
   move on #26 is to re-measure the ceiling on the covered subset alone: if valuation-score
   correlation is materially better among the 725 covered names, the hypothesis survives for large
   caps and dies for small ones. If it is not, forward PE was never the missing input.

## Consequences

- The 0.44 ceiling stays unexplained, and that is now an honest open question rather than a to-do
  with a presumed fix attached.
- We hold a growing point-in-time record of analyst expectations. Each row carries both the period
  it forecasts and the date we learned it, so revisions are visible as revisions. This is the only
  forward-looking data in the system, and it becomes more useful with every monthly snapshot —
  today it is one snapshot and cannot support a backtest at all.
- A future factor built on it must declare its coverage the way adr-045 made forward-filled factors
  declare their age. A strategy silently dropping 80% of its candidates is the failure mode to
  design against.
- Target price and analyst counts came along for free in the same fetch and are now available,
  though nothing reads them yet.

## Alternatives rejected

- **Wire `fwd_pe` anyway and let missing values fall through.** Rejected: on `MOM_roc252_m_10` every
  single holding is uncovered, so the factor is not merely sparse but empty. The strategy would keep
  running and quietly stop being the strategy that was walk-forward tested (adr-040).
- **Restrict the affected strategies to the covered universe.** Rejected as a side effect of a data
  change. Narrowing to large/mid caps is a real strategy decision that would need its own
  walk-forward evidence, not a consequence of which names analysts happen to follow.
- **Compute our own forward EPS from trend extrapolation.** Rejected: that is a model wearing a
  data label. adr-019 already removed the homegrown D/V/M for the same reason.
