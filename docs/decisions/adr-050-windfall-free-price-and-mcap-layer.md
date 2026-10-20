# adr-050 — Prices and market cap from free NSE data: freeze Trendlyne's price history, take membership from NSE's official market cap

- **Status:** accepted — shipped in iter-204 (Ottomate iteration 204, master 7b47b40, 2026-10-20) after
  the owner approved the side-by-side re-baseline; measured in iter-200.
- **Date:** 2026-10-20
- **Tags:** curated, cat:reliability
- **Iteration:** iter-200 (Ottomate iteration 200, items 1460–1463)

## Context

The monthly Trendlyne refresh is ~1.5 hours of console scripts in the owner's logged-in browser
(`docs/ops/trendlyne-refresh-runbook.md`). Only one part has no free substitute: the DVM scores four
paper books rank on. The rest feeds two things free NSE data can carry:

- **split-adjusted prices** — Trendlyne `ohlcv` (OHLCV + megacap harvesters), spliced onto raw
  Bhavcopy after the last harvested bar (adr-022/044; split/bonus tail adjusted since adr-049);
- **point-in-time market cap → the ₹500cr universe** — `pit_mcap` = adjusted close × a current share
  count anchored on Trendlyne's market-cap snapshot (`stocks.mcap` ÷ last close, adr-029), with
  NP/EPS-derived shares (`pit_shares`) as the fallback (`rebuild_pit_mcap_ca.py`).

Every figure below is printed by a script in `backend/scripts/free_layer/` reading
`backend/data/free_layer.duckdb`.

## What was measured

**Corporate actions (item 1460, `backfill_ca.py`).** NSE's corporate-actions API returns full years
back to 2010. Parsed in full (pre-2018 filings combine events in one subject — "Bonus 1:1 / Face
Value Split From Rs.10/- To Re.1/-" — and are multiplied): 494 splits, 524 bonuses, 60 same-day
bonus+split, 1 bonus+demerger, 1 demerger+scheme, 1 consolidation, 106 demergers, 93 schemes, 350
rights issues. Against the app's 450 share-step-confirmed `ca_events`: 369 within ±3 days, 366 with
the same ratio; several app events NSE does not list are false detections (repeated 1.25 "splits" on
BIRLAMONEY and KITEX are 20% circuit moves). At 736 NSE events inside Trendlyne's history, Trendlyne
took the same price step on **724 (98.2%)**. NSE's list has real gaps (JSWSTEEL 2017, KARURVYSYA and
CGCL 2016, HEG 2024, NAZARA, GPIL, HERITGFOOD, AJANTPHARM).

**Prices (item 1461, `compare_prices.py`, `history_rescale.py`).** Bhavcopy divided by NSE's
split/bonus ratios, plus the standard theoretical-ex-rights (TERP) adjustment for rights priced below
market, compared with the factor Trendlyne applied on every day for 1,700 live names (each name
anchored at its last Trendlyne bar):

| Event source | Names fully matching (≥99% of days) | Name-days matching |
|---|---|---|
| NSE splits/bonuses | 93.2% | 95.8% |
| NSE + rights (TERP) | 93.5% | 96.3% |
| NSE + rights, 2016 onward | **95.9%** | **97.9%** |
| app `ca_events` alone | 77.6% | 87.3% |

Adding the app's own events to NSE's makes it worse (their false positives). The rights regex reads
311 of 350 rights subjects (formats like "Prem", "@ Par" are skipped), so rights are slightly
under-credited.

How Trendlyne's history changes between harvests: against the 2026-06-12 snapshot, 15 of 1,731
names had their whole history rescaled by one constant factor — 14 with an NSE split, bonus or
rights issue in between (GENESYS ×0.682 for a rights issue), one unexplained (VMARCIND ×0.167);
against the 2026-07-08 snapshot, 9 of 1,756, all 9 explained. ("Explained" means the name has an NSE
event between the two harvests; the factors were spot-checked against the ratios — MWL ×0.1 split,
GOODLUCK ×0.333 bonus 2:1 — not matched one by one.) Since adr-049 the tail adjustment already divides
every earlier bar, Trendlyne's included, for splits and bonuses; adding rights covers the rest.
Beyond that, two names per comparison moved by a non-constant amount (TEMBO, SAHANA — also a split
and a bonus); nothing else changed, so nothing requires re-downloading the history.

**Market cap and the ₹500cr universe (item 1462, `explain_membership.py`).** NSE's daily price
bundle carries an official market-cap file (issue size × close for every listed security) from
**2024-02-01** (the bundles for 31 Jan 2024, Dec 2023 and Jun 2023 carry none). The current universe was scored against NSE's official set at 30 month-ends
(Feb 2024 – Jul 2026). Companies are matched by ISIN (renames like ZOMATO→ETERNAL count once); the
official side counts a company that day only if it trades in a mainboard series (EQ, BE, BZ) above
₹500cr; the current side sits behind the strategies' NSE-only gate (company ever traded in EQ,
adr-024). Averages per month-end (official ≈1,539):

| Disagreement | Per month | Cause |
|---|---|---|
| admitted, NSE puts it ≤₹500cr | 12.9 | share-count / price error |
| missed, ours ≤₹500cr | 2.4 | share-count / price error |
| admitted before the company's first NSE bar | **94.6** | the NSE gate is not point-in-time |
| admitted, no NSE trade in the prior 90 days | 15.0 | the gate ignores dormant NSE listings |
| admitted, never in a later file / missing that day | 0.4 / 1.9 | delisted / suspended |
| official, the company is in no universe row at any date | **48.6** | not in Trendlyne's stock list (a rare few, e.g. VAML, are listed but never got a universe row) |
| official, rows end shortly before the date | 2.6 | harvest-end window (bridged in the engine by the Bhavcopy fallback, adr-046) |
| official, rows exist but not within 60 days | 1.9 | interior gap |

- **Share counts are not the problem:** share-count/price errors are **1.0%** of the official set.
  (Today's NP/EPS share counts sit within 10% of NSE's for 90.7% of 1,767 names, but those are only
  the fallback; the 1.0% is the evidence for `pit_mcap` itself.)
- **The NSE gate looks ahead.** "Ever traded EQ" admits a company before it listed on NSE (many
  BSE-only names joined NSE in 2024–26: ACGL, AKCAPIT, ASHIKA…) and keeps BSE companies whose NSE
  line went idle (GOODYEAR, KENNAMET, KOVAI…). It needs "has traded on NSE, recently" — first bar on
  or before the date, and a trade within ~90 days. Independent of market cap; exists before 2024 too.
- **Survivorship gap in the stock list.** 157 companies were officially above ₹500cr at some
  2024–26 month-end yet never appear in `universe_membership`; 149 are still listed, and **142 of
  them are under ₹500cr today** (median ₹302cr). Trendlyne's stock list evidently reflects today's
  larger companies, so companies that qualified and later shrank are missing from backtests in the
  months they qualified. That should bias backtests upward — inferred from the excluded companies
  having shrunk, not measured — very likely before 2024 as well, and it is not fixed by changing
  where market cap comes from.
- REITs and InvITs sit in `universe_membership` but never reach a strategy (no EQ series); no paper
  position — current or archived, 213 tickers — ever held one.
- Paper exposure: **4 of 389** paper buys were in names NSE's official figure put under ₹500cr at the
  prior month-end (all DVM-all-three weekly, ₹428–470cr; `paper_exposure.py`). This window (Jul–Oct
  2026, after the adr-048 replay) is when share counts are freshest, so it does not carry over to
  backtests.

Not measured: anything before Feb 2024 — NSE's daily bundle carries no market-cap file earlier. Share
counts drift (413 of 2,096 names, 19.7%, moved more than 10% in 2.5 years net of splits and
bonuses — `compare_mcap.py`), and `pit_mcap` holds today's count constant back through history, so its
pre-2024 accuracy is unknown.

Also found: `corp_actions.parse` returns only the split part of a combined subject and drops the
bonus. No row in the live window is affected (current NSE filings list the two separately).

## Proposed decision (for the owner to lock as its own iteration)

1. **Freeze Trendlyne's price history at its last harvest; stop the OHLCV and megacap harvests.**
   Extend from Bhavcopy adjusted from NSE's list (live since adr-049), add rights (TERP) to that
   adjustment, fix `parse` for combined subjects.
2. **Gap detector.** An overnight move that snaps to a canonical split/bonus ratio with no NSE event
   is alerted (the paper crons' webhook), never auto-adjusted — NSE misses a few percent of events.
3. **Membership from NSE's official market cap from 2024-02-01**, pulled daily with the Bhavcopy
   refresh. Requirements: companies mapped to engine symbols by ISIN through Bhavcopy (the MCAP file
   carries no ISIN; renames), `recovered_symbols` honoured, mainboard series counted. Before
   then keep the existing `pit_mcap` (static; NSE's quarterly shareholding filings are the
   candidate if pre-2024 accuracy is ever measured).
4. **Make the NSE gate point-in-time**, for all dates: a company enters only from its first NSE bar
   and only while it has traded on NSE within ~90 days. The largest correction measured; needs no
   Trendlyne data.
5. **Survivorship gap — decide separately.** Closing it means pricing companies Trendlyne never
   listed from Bhavcopy (adjusted with NSE's corporate actions) and giving them engine symbols, for
   all dates — a larger change than this proposal, logged on its own.
6. **Re-baseline.** Before Feb 2024 step 4 changes the universe (step 5 would too, if taken). From
   Feb 2024 the universe drops the not-yet-listed and dormant names and fixes the ~1% share-count
   cases; it gains the never-mapped companies only if step 5 is taken. Leaderboards and the 8 paper
   strategies' backtests are re-run and shown side by side before anything else moves.

## Implementation (iter-204, Ottomate iteration 204)

Built as proposed, steps 1–5, with these choices made in the build:

- **Corporate actions** (`corp_actions.py`): NSE's list backfilled from 2010 (`/api/corporate-actions/backfill`);
  combined subjects multiply (#958); rights issues are typed and priced at P/TERP when the list is
  refreshed, from the last close before the ex-date — only issues stating a price (premium or par),
  fully paid and in equity; one event filed twice (same day, kind and ratio) counts once, while a
  bonus and a split on one day are two events even when their ratios match (seven such pairs since
  2021). The cum-rights price is looked up across every ticker the company has used. A share COUNT
  is scaled by splits/bonuses only (`share_events`), never by a rights P/TERP.
- **Prices** (`trendlyne_store.adjusted_close_panel`): Trendlyne `ohlcv` frozen; names with no
  Trendlyne bars (listings after the freeze, the companies Trendlyne never listed) priced from
  Bhavcopy back-adjusted with NSE's events (`_bhavcopy_adjusted`). Trendlyne-priced names extend
  from Bhavcopy whenever a window runs past their last bar — a live run, or a backtest whose explicit
  end is after the freeze (otherwise every walk-forward OOS window would lose them). Rights reach the
  live tail and the paper re-base through `ratio_events`, the same convention as the backtests.
- **Harvest**: the OHLCV harvester is retired and `ingest_refresh.py` ignores `tl_ohlcv_*.csv`
  unless `--include-ohlcv`. The megacap harvester stays — it carries the DVM and valuation rows of
  the ~100 index names the base screener omits. `rebuild_pit_mcap_ca.py` / `build_membership.py`
  refuse to run without `--force-after-adr-050`: with the close frozen they would rewrite pre-2024
  membership from each month's share count.
- **Gap detector** (`gap_check.py`, `/api/data/gap-check`, the 20:40 mark cron): ratios ≥ 1.5 only
  (a 1:4 bonus is indistinguishable from a 20% circuit move); any NSE event of any kind within three
  sessions explains a move.
- **Market cap** (`scripts/nse_mcap_ingest.py` → `nse_layer.duckdb`, nightly in the EOD window):
  mainboard rows of NSE's MCAP file from 2024-02-01; `ticker_map` groups every mainboard ticker with
  an equity ISIN (INE…, so no ETFs) transitively and names the company by its Trendlyne symbol when
  Trendlyne has one, else its latest NSE ticker. From 2024-02-01 membership, the `mcap` feature and
  the universe candidates read it; the adr-046 Bhavcopy fallback only engages when the pull is behind.
- **NSE gate** (`nse_gate_panel` / `nse_gate_at`): first EQ bar on or before the date AND a mainboard
  (EQ/BE/BZ) trade within 90 days, by company. Bhavcopy starts 2010-01-04, so before it a company
  counts if it was already listed when coverage began (warned). adr-024 amended.
- **Survivorship** (`survivors()`): a company NSE put above the floor on any day from 2024-02-01 whose
  ISIN group has no `universe_membership` row. Before 2024 its market cap is its adjusted close × the
  share count implied by its first MCAP reading (pit_mcap's own method). It has no Trendlyne factor,
  so a rank_blend that uses one leaves it out (`resolve._mask_uncovered`) rather than scoring it on
  the blend's price factors alone; price-only rules can pick it. A company renamed after the frozen
  membership build keeps its rows under the old symbol; `companies.membership_symbol` reads them under
  the new one, so it is never counted twice. Out of scope: companies that delisted before 2024-02-01
  without a Trendlyne row (survivor selection uses post-2024 data, so some pre-2024 bias remains).
- **Known break at the cutover:** the `mcap` feature switches from Trendlyne's pit_mcap to NSE's own
  number on 2024-02-01 and steps where pit_mcap's share count was wrong (IDEA 155,586 → 68,882 cr;
  UJJIVAN 110,608 → 6,667 cr) — a size-ranked rule sees that step.

## Consequences

- The monthly chore shrinks to the DVM-score script (weekly, ~20 min) plus the valuation pull while
  Value + Momentum ranks on Trendlyne's P/E (a separate study tests a free P/E).
- The ₹500cr gate becomes NSE's own number from Feb 2024 and stops drifting between harvests.
- New moving parts: a daily MCAP pull, an ISIN mapping, and the gap detector — all NSE-public, all
  alerting on failure the way the corporate-actions refresh does.
- Known limits of the measurement, negligible to the totals: ISIN grouping joins a few unrelated
  tickers (ETF families, one IBULISL group) and does not link an ISIN change at a rename; the official
  side is not EQ-gated like ours (~1 company-month per month — rights-entitlement tickers, SWANDEF,
  VHLTD).
