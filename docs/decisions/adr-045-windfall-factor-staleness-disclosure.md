# adr-045 — A forward-filled factor must disclose its age; and every table the engine reads needs a refresh path

- **Status:** accepted
- **Date:** 2026-09-07
- **Tags:** curated, cat:reliability
- **Iteration:** iter-172 (items 1245, 1246)

## Context

On 2026-09-07, a routine task — regenerate live signals on the freshly refreshed data (#844) — came
back clean. All eight paper books returned `as_of=2026-09-04`, each with a healthy buy/hold/sell
split. By the project's own acceptance test, the refresh had worked.

It had not, for one book.

`dvm_history` was current to 2026-09-04. `valuation_ratios` — `PE_TTM` / `PEG_TTM` / `PBV_A`, the
daily multiples behind the `tl_pe` / `tl_peg` / `tl_pbv` factors — had stopped at **2026-07-15**, 54
days earlier. `CMP_valmom_m_20` ranks on `tl_pe` at half weight. It is a live paper book. It had
been selecting holdings on seven-week-old price-to-earnings ratios, and reporting a current `as_of`
while doing it.

Two independent defects made that possible, and neither is exotic:

**1. The ingest never covered the table.** `ingest_refresh.py` merged `dvm_history`, `ohlcv` and
`stocks`. The monthly runbook never named `valuation_ratios` in any of its four phases. Meanwhile
`trendlyne_harvester_megacap.js` — an *active*, documented monthly step — had been writing
`tl_valuation_ratios_megacap.csv` into the staging directory every month, where the ingest ignored
it and Phase 3 step 5 (`rm data/refresh_staging/*.csv`) deleted it. The data was being downloaded
and thrown away on a schedule. `harvesters/README.md` documented the gap accurately, but filed it
under shares-outstanding and characterised the impact as degrading "gently".

**2. The engine forward-filled it silently.** `resolve()` ffills the daily `tl_*` panels onto the
price index. That is correct behaviour — a daily series should carry its last published value across
a holiday or a missed scrape. But the ffill is indistinguishable, from the outside, between a table
refreshed yesterday and a table abandoned in July: both come back fully populated to the last bar.
Nothing in `warnings[]` mentioned it, and `warnings[]` is where this project puts its honesty.

The combination is worse than either half. The gap was invisible *because* the ffill was silent, and
the ffill was harmless-looking *because* nobody knew the gap existed. 48 of 289 saved strategies read
these factors.

## Decision

**A forward-filled daily factor discloses its age.** `_ffill_daily_tl` measures the distance from a
panel's newest real observation to the newest price bar and appends a warning past 14 days — the
same window `pit_universe` already gates membership on, so "stale" means what it already meant here.
The ffill itself is unchanged and asserted byte-identical to the prior expression: this adds a
disclosure, it does not alter a single ranking, selection or `as_of`.

**Every table the engine reads gets a refresh path, or an explicit note saying it has none.**
`valuation_ratios` now merges through `ingest_refresh.py` keyed per `(pk, metric)` — the same
per-series shape as the `(pk, score)` fix of 2026-09-06, so a partial harvest cannot delete the
metrics it omits. The runbook names it, and its dry-run step now says the report must list four
tables, with a missing line meaning **stop before step 5 wipes the staging directory**.

## Consequences

- `CMP_valmom_m_20` will emit a stale-factor warning until the next harvest lands. That is the fix
  working, not a new failure.
- Coverage is megacap-only (~99 names) until `_done/trendlyne_harvester_leg1.js` is promoted back
  into the monthly set (#851). The warning will now say so, per name, instead of the gap sitting
  silent for another 54 days.
- The threshold is panel-wide, not per-symbol. A table that stopped being refreshed moves every
  column together, which is the failure this catches. Individually stale names inside a current
  table (#845) are a noisier problem and deliberately out of scope.
- `_TL_LAGGED` and `_TL_SHARE` panels ffill unbounded inside `trendlyne_store.py` and are **not**
  covered (#852). A flat 14-day threshold would be wrong for quarterly result-lag-gated data; they
  need a cadence-aware one. The residual risk is real and now recorded rather than assumed away.

## The generalisation worth keeping

The project's rails are built around not trusting a *number*: no look-ahead, costs on every fill,
walk-forward before approval, validate against a known result. This incident was not a wrong number.
Every number was internally consistent, and the signal run passed its own acceptance check. What was
missing was a statement about the *provenance* of an input — how old it was.

So: **an unwired table does not announce itself, and a forward-fill is an assertion about freshness
that nobody checked.** Where the engine carries a value forward, it says how far. Where a harvester
emits a file the ingest does not read, that is a staleness bug waiting for a consumer, not a
harmless extra file.
