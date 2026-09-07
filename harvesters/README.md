# Trendlyne harvesters

Every Trendlyne endpoint is WAF-protected — plain curl/Python gets 403 even with cookies. These
are console scripts that run **inside a logged-in trendlyne.com tab** (F12 → Console → paste →
Enter). Nothing server-side can replace them. Files land in `~/Downloads`; click **Allow** when
Chrome asks about multiple downloads.

Full procedure (staging, ingest, rebuild, verify) lives on the server at
`docs/ops/trendlyne-refresh-runbook.md` in the windfall-labs repo.

---

## A normal refresh — run these, in this order

| Order | Script | Cadence | Time |
|---|---|---|---|
| 0 | `trendlyne_preflight.js` | every time | 15 sec |
| 1 | `trendlyne_dvm_harvester.js` | **weekly** | ~20 min |
| 2 | `trendlyne_harvester_megacap.js` | monthly | ~10 min |
| 3 | `trendlyne_harvester_ohlcv.js` | **monthly** | ~35–45 min |
| 4 | `trendlyne_harvester_leg1.js` | **monthly** | ~25 min |

**3 and 4 were added 2026-09-07 (adr-046, to-do #851).** This table used to list only the first
three and describe the OHLCV pull as optional. That is how the eligible universe silently collapsed
to 293 of 2,190 stocks: `ohlcv` also feeds `pit_mcap` → `universe_membership`, so skipping it
freezes *which stocks can be picked*, not just their price history. leg1 is here because it is the
only script that refreshes `valuation_ratios` (the `tl_pe` / `tl_peg` / `tl_pbv` factors) for the
whole universe rather than the ~99 megacaps — it had been parked in `_done/` while a live paper
book ranked half its holdings on P/Es frozen since July.

As of 2026-09-07 `ingest_refresh.py` reads every table leg1 produces — `valuation_ratios`,
`pnl_quarterly`, `growth_quality`, `ownership` — each replaced per `(pk, metric)`. Before that it
read three tables and Phase 3 step 5 deleted the rest of the download.

**0. Preflight.** Answers one question before you spend 30 minutes: does this session actually
return DVM data? Prints `GREEN - go` or `RED - stop`. It exists because on 2026-09-05 the
subscription had lapsed and the harvest came back with prices and fundamentals but empty
`d/v/m` — 30 minutes for nothing.

**1. DVM harvester.** The one that matters. D/V/M score history — what every DVM/factor strategy
ranks on. The only thing that genuinely goes stale and cannot be automated.

**2. Megacap.** The base screener silently drops the top ~100 index names (measured 2026-09-07:
99 names, **94 of which the base list misses**). Without it a refresh deletes megacaps.

**Why weekly is only ~20 minutes:** `pit_mcap` and `universe_membership` are built from
**Bhavcopy**, not Trendlyne OHLCV (`rebuild_pit_mcap_ca.py:106`, `build_pit_mcap.py:40`). Bhavcopy
is free and already automated. So script 1 alone keeps the factors current.

### Situational — not part of a normal refresh

| Script | When |
|---|---|
| `trendlyne_harvester_ohlcv.js` (~40 min) | **Run it monthly.** It extends Trendlyne's **native price history**, and that table is also what feeds `rebuild_pit_mcap_ca.py` -> `pit_mcap` -> `universe_membership` — i.e. which stocks are **eligible to be picked at all**. This row used to say it was "NOT needed for freshness" because Bhavcopy carries prices and `adjusted_close_panel` splices them on. That was true of PRICES and false of ELIGIBILITY, and on 2026-09-07 it cost the live books their universe: a partial harvest left 293 of 2,190 stocks selectable and every paper book picked from that slice (adr-046). Skipping it is now *survivable* — eligibility falls back to Bhavcopy and says so in `warnings[]` — but the fallback uses unadjusted closes, so run it monthly to keep membership split-adjusted. |
| `trendlyne_harvester_gapfill.js` (~2–5 min) | When the ingest dry-run names specific stocks as missing or shrinking. **Its `SYMBOLS` list is scratch — repointed per incident, never a stable list.** Check it targets the names you actually mean before running. |
| `trendlyne_harvester_forecaster.js` (~25-35 min) | **Analyst consensus estimates — forward EPS and target price (#857, for #26).** Not yet part of the monthly loop; read the coverage note below before spending 30 minutes on it. Output goes to `tl_forecaster_estimates_partNN.csv` (`pk,metric,period_end,as_of,value`) plus `tl_forecaster_coverage_partNN.csv`. **There is no ingest leg for it yet** — the CSVs land in Downloads and wait. |

### Forecaster estimates — how it is reached, and why coverage limits it

`FUNDAMENTALS-EXPORT-COLUMNS.md` #6 asks for `Forecaster Estimates 1Y forward PE`. It cannot be
exported: measured 2026-09-07, all **2,235 of 2,235** cells read the literal string `Export NA`,
across both parameter sets and all five market-cap bands. Trendlyne blocks Forecaster fields from
the Data Downloader and says so on the page.

The page itself is **server-rendered**, so there is no XHR to intercept — watch the network tab on a
consensus page and you get static assets and `getLivePrice`, nothing else. The whole estimate set
ships inside the document, HTML-escaped, on one attribute:

```
<div id="consensus-details" data-consensusjson="{ ... }">
```

so a plain credentialed `fetch` is enough. The slug wildcards, meaning **pk alone addresses it**:

```
https://trendlyne.com/equity/consensus-estimates/<pk>/x/x/
```

`RANGE_ESTIMATES.<METRIC>.ANNUAL[]` carries `ACTUAL / AVG / HIGH / LOW / MEDIAN /
NUMBER_OF_ANALYSTS`, with `periodtype` ("FY27") and `qtr_end_date` ("2027-03-31"). Twelve metrics
are available; the harvester takes EPS and TARGET_PRICE, and the parser is generic — add a key to
`METRICS` and it is harvested.

**RUN THE MEGACAP COMPANION, or you silently omit the ~100 largest names.** This harvester takes
its stock list from the base screener, and the base screener drops the top ~100 index names — the
same defect `trendlyne_harvester_megacap.js` exists to fix. On the first run (2026-09-08) that
omitted RELIANCE, HDFCBANK, LT, TITAN, ICICIBANK and ~90 others, and because they were never
*requested* there was no error to notice: 0 errors, 0 429s, and a coverage table that read ~19%
where the truth was ~36%. Feed the megacap symbol list through the same endpoint and re-ingest with
`--allow-small`, which exists for exactly this top-up.

**Coverage is the catch, and it decides whether #26 is even answerable.** Full harvest 2026-09-08,
2,005 stocks probed, banded strictly against the ₹500cr universe:

| Market cap | Covered / probed / in universe | % of universe |
|---|---|---|
| > ₹50,000cr | 186 / 202 / 206 | 90.3% |
| ₹10,000–50,000cr | 296 / 388 / 390 | 75.9% |
| ₹2,000–10,000cr | 281 / 630 / 632 | 44.5% |
| ₹500–2,000cr | 50 / 738 / 781 | **6.4%** |
| overall | 813 / 2,005 | 40.5% |

Coverage does not decline gently, it collapses: below ₹2,000cr it is effectively absent, and that
band is 39% of the universe. Of the 77 names the live books held on 2026-09-08, 27 are covered
(36.5% of the 74 that resolve to a pk); `MOM_roc252_m_10` is 0 of 8. An uncovered stock is not an
error — it returns HTTP 200 with an empty `RANGE_ESTIMATES` and a ~75KB page against ~600KB for a
covered one, and the harvester records it as a miss in the coverage CSV so a thin harvest is
measured rather than inferred. See adr-047.

**When the ingest is written it must MERGE, never replace per `(pk, metric)`.** This endpoint returns
only *today's* estimates — there is no history, and estimates revise. Every row therefore carries both
the period it forecasts (`period_end`) and the date we learned it (`as_of`); history builds forward as
snapshots accumulate. A wholesale replace would delete every prior snapshot on the first run, which is
the same silent data loss fixed on 2026-09-07 in `0b0ecce`.

### Fundamentals snapshot

Not a script — Trendlyne → **Data Downloader** → `.xlsx`. The exact 24 columns the ingest reads
are in `FUNDAMENTALS-EXPORT-COLUMNS.md`. Roughly quarterly; a cron nags past 35 days.

---

## Gotchas that each cost a bug once

- **Run 1 AND 2 together on a refresh.** A DVM-only ingest would have deleted 806k rows and 138
  megacaps (iter-22).
- **If the DVM harvester reports fewer than ~1,800 stocks, the screener list truncated** — re-run
  it, do not ingest. A healthy run reads ~1,899 (2026-09-07: 1,901).
- **Watch the progress line.** `parts` climbing = working, expect 4–5 files at ~48MB. `errs`
  climbing with `parts` stuck at 0 = the DVM endpoint is refusing — stop, don't burn 20 minutes.
  That is what a lapsed subscription looks like.
- **A harvester reporting `NO PK` for a name** — say which one, don't assume it's absent. Names
  the symbol search can't resolve (e.g. "BSE", pk 52884) must be addressed as `{sym, pk}`.
- **The megacap `SYMBOLS` list is hardcoded and drifts.** Jul 2026 it was missing
  CIPLA/ZYDUSLIFE/LUPIN/LODHA; Sep 2026 it was missing MARICO/SBICARD. When the ingest dry-run
  shows a big live name under "preserved" or "shrinking", that's this.

---

## Fixed 2026-09-07 — the silent partial-harvest bug

**Symptom:** gapfill felt like it was needed on *every* refresh.

**It was never a Trendlyne coverage problem.** Both harvesters discarded their own failures:

- `trendlyne_dvm_harvester.js` — `hist()` gave up after 3 retries at CONC=6, did `errs++`, and
  dropped that `(pk, param)` with no record of which one.
- `trendlyne_harvester_megacap.js` — worse: `if (d && d.length) { push }` with **no else**. A
  failed param wasn't pushed, counted, or reported.

Each stock is three separate fetches (`d`, `v`, `m`). Losing one or two left the stock **looking
populated while carrying a third of its history**. Because `ingest_refresh.py` replaces a covered
pk's rows wholesale, those partials would have *deleted* real history — its shrink guard caught
it. Measured on the 2026-09-07 refresh: 24 stocks with zero rows, **62 more with 1-of-3 params**,
including GODREJCP, VOLTAS, MOTHERSON, JSWENERGY, ATGL, MAZDOCK, BLUEDART.

**Fix:** both scripts now track every failed `(pk, param)` and run a **recovery sweep** at CONC=1
with patient backoff before writing anything. Whatever still fails is written to
`tl_dvm_misses.csv` / `tl_dvm_misses_megacap.csv` and named in the panel — visible, not a number
in `errs`. Proof it was only ever a retry problem: all 24 zero-row names were present in the
screener the whole time, and 23 of 24 returned full history on a gentle retry.

Tracked as to-do #831; the companion reporting bug in `ingest_refresh.py` (shrink guard says
"10 pks" no matter how many there are — `LIMIT 10` counted as the total) is #832.

**Consequence:** gapfill should now be rare — reach for it when the megacap list has drifted, not
every month.

---

## `_done/` — one-offs whose output is already in the database

Kept because they are the **only way to rebuild most of those tables**: `ingest_refresh.py` handles
`dvm_history`, `ohlcv`, `stocks` and — since 2026-09-07 — `valuation_ratios`. The *other*
fundamentals CSVs these produce (`growth_quality`, `pnl_quarterly`, `ownership`,
`shareholding_summary`, …) still have no monthly ingest path; only the original bulk loader
`load_trendlyne.py` reads them. Don't delete them.

**`valuation_ratios` is the cautionary tale (iter-172, to-do #849).** It sat in that "no ingest
path" list for months while `trendlyne_harvester_megacap.js` — an *active* monthly step — kept
emitting `tl_valuation_ratios_megacap.csv` into the staging dir, which the ingest ignored and
Phase 3 step 5 then deleted. The table froze at 2026-07-15 while `dvm_history` ran to 2026-09-04,
and because `resolve()` forward-fills the daily factor panels, 48 of 289 saved strategies (one a
LIVE paper book) kept ranking on July multiples with nothing in `warnings[]` to say so. The lesson
generalises to every row still in this table: **an unwired table does not announce itself.** If a
harvester emits a CSV the ingest does not read, that is a silent staleness bug waiting for a
consumer, not a harmless extra file.

Megacap coverage only, for now: the monthly leg carries ~99 names. `leg1` is what covers the full
~1,800, and promoting it back into the monthly set is the remaining half of #849.

| Script | What it built |
|---|---|
| `trendlyne_harvester_leg1.js` | daily valuation ratios + quarterly P&L / growth / ownership |
| `trendlyne_harvester_leg1_5.js` | corporate actions, result dates, shareholding |
| `trendlyne_harvester_leg2.js` | full annual statements (11 yrs) |
| `trendlyne_harvester_recover.js` | ~226 stocks with a blank NSE symbol in the screener |
| `trendlyne_harvester_completeness.js` | SREEL, RKSWAMY (≥₹500cr but absent) |
| `trendlyne_harvester_parity5.js` | 13 historically-liquid names below the ₹500cr floor |

`_done/_superseded/` holds `trendlyne_harvester_megacap_fill.js` — a re-pull of 6 files Chrome's
download throttle blocked in Jun 2026, obsolete since the megacap script started spacing its
downloads.

**Known gap (unwired, not by design):** because those fundamentals CSVs have no refresh path,
**shares outstanding** — which `pit_mcap` derives as NP/EPS from `pnl_quarterly` — is updated only
by a manual reload. Shares move slowly, so this degrades gently rather than breaking.
