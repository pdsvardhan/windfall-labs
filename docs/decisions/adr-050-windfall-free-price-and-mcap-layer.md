# adr-050 — Prices and market cap from free NSE data: freeze Trendlyne's price history, take membership from NSE's official market cap

- **Status:** proposed (measurement done in iter-200; the switch is a separate, owner-locked iteration)
- **Date:** 2026-10-20
- **Tags:** curated, cat:reliability
- **Iteration:** iter-200 (Ottomate iteration 200, items 1460–1463)

## Context

The monthly Trendlyne refresh is ~1.5 hours of console scripts in the owner's logged-in browser
(`docs/ops/trendlyne-refresh-runbook.md`). Only one part has no free substitute: the DVM scores four
paper books rank on. The rest feeds two things free NSE data can carry:

- **split-adjusted prices** — Trendlyne `ohlcv` (OHLCV + megacap harvesters), spliced onto raw
  Bhavcopy after the last harvested bar (adr-022/044; split/bonus tail adjusted since adr-049);
- **point-in-time market cap → the ₹500cr universe** — `pit_mcap` = adjusted close × a share count
  derived from Trendlyne's NP/EPS (`rebuild_pit_mcap_ca.py`, `pit_shares`).

iter-200 measured both against Trendlyne and against NSE's own numbers. Scripts:
`backend/scripts/free_layer/`; data: `backend/data/free_layer.duckdb`. Every figure below was
reproduced by an independent verifier.

## What was measured

**Corporate actions (item 1460).** NSE's corporate-actions API returns full years back to 2010.
Parsed in full (pre-2018 filings combine events in one subject — "Bonus 1:1 / Face Value Split
From Rs.10/- To Re.1/-" — and are multiplied): 494 splits, 524 bonuses, 60 same-day bonus+split,
1 bonus+demerger, 1 demerger+scheme, 1 consolidation, 106 demergers, 93 schemes, 350 rights issues. Against the
app's 450 share-step-confirmed `ca_events`: 369 within ±3 days, 366 with the same ratio; several
app events NSE does not list are false detections (repeated 1.25 "splits" on BIRLAMONEY and KITEX
are 20% circuit moves). At 736 NSE events inside Trendlyne's history, Trendlyne took the same price
step on **724 (98.2%)**. NSE's list has real gaps (JSWSTEEL 2017, KARURVYSYA and CGCL 2016, HEG
2024, NAZARA, GPIL, HERITGFOOD, AJANTPHARM).

**Prices (item 1461).** Bhavcopy divided by NSE's split/bonus ratios, plus the standard
theoretical-ex-rights (TERP) adjustment for rights priced below market, compared with the factor
Trendlyne applied on every day for 1,700 live names (each name anchored at its last Trendlyne bar):

| Event source | Names fully matching (≥99% of days) | Name-days matching |
|---|---|---|
| NSE splits/bonuses | 93.2% | 95.8% |
| NSE + rights (TERP) | 93.5% | 96.3% |
| NSE + rights, 2016 onward | **95.9%** | **97.9%** |
| app `ca_events` alone | 77.6% | 87.3% |

Adding the app's own events to NSE's makes it worse (their false positives). The rights regex reads
311 of 350 rights subjects (formats like "Prem", "@ Par" are skipped), so rights are slightly
under-credited.

The decisive point is how Trendlyne's history changes: **only by back-adjustment for corporate
actions after the previous harvest** (15–22 names per refresh had their whole history rescaled —
GENESYS by ×0.682 for a rights issue). Since adr-049 the tail adjustment already divides every
earlier bar, Trendlyne's included, for splits and bonuses; adding rights covers the rest. Nothing
else in the history moves, so nothing requires re-downloading it.

**Market cap and the ₹500cr universe (item 1462).** NSE's daily price bundle carries an official
market-cap file (issue size × close for every listed security) from **2024-02-29**. The current
universe was scored against NSE's official ">₹500cr" set at 30 month-ends (Feb 2024 – Jul 2026),
with companies matched by ISIN (renames like ZOMATO→ETERNAL count once) and both sides behind the
strategies' NSE-only gate (company ever traded in series EQ, adr-024). Averages per month-end
(official: ~1,547 names):

| Disagreement | Per month | Cause |
|---|---|---|
| admitted, NSE puts it ≤₹500cr | 12.9 | share count / price error |
| missed, ours ≤₹500cr | 2.5 | share count / price error |
| admitted before the company had any NSE bar | **87** | the NSE gate is not point-in-time |
| admitted while absent from NSE's file | 17.3 | suspended / delisted / merged |
| official >₹500cr, no row in our universe | **53.6** | harvest coverage (CIPLA, ZYDUSLIFE, BSE in some months) |

- **Share counts are not the problem:** share-count/price errors are **~1%** of the official set.
  Today's NP/EPS share counts sit within 10% of NSE's for 90.7% of 1,767 names.
- **Look-ahead in the NSE gate.** "Ever traded EQ" admits a company before it listed on NSE (many
  BSE-only names joined NSE in 2024–26: ACGL, AKCAPIT, ASHIKA…). This is independent of where
  market cap comes from and exists before 2024 too.
- **Coverage.** The current layer misses ~54 official >₹500cr equity names a month — names the
  harvest did not return (the megacap list is hand-maintained and drifts).
- REITs and InvITs sit in `universe_membership` but never reach a strategy (no EQ series); no
  paper position — current or archived, 213 tickers — ever held one.
- Paper exposure: **4 of 389** paper buys were in names NSE's official figure put under ₹500cr at
  the prior month-end (all DVM-all-three weekly, ₹428–470cr). This window (Jul–Oct 2026, after the
  adr-048 replay) is when share counts are freshest, so it does not carry over to backtests.

Not measured: anything before 2024-02-29 — NSE publishes no daily market-cap file earlier. Share
counts do drift (19.7% of names moved more than 10% in 2.5 years, net of splits and bonuses), and
the existing `pit_mcap` holds today's count constant back through history, so its pre-2024 accuracy
is unknown.

Also found: `corp_actions.parse` returns only the split part of a combined subject and drops the
bonus. No row in the live window is affected (current NSE filings list the two separately).

## Proposed decision (for the owner to lock as its own iteration)

1. **Freeze Trendlyne's price history at its last harvest; stop the OHLCV and megacap harvests.**
   Extend from Bhavcopy adjusted from NSE's list (live since adr-049) and add rights (TERP) to that
   adjustment; fix `parse` for combined subjects.
2. **Gap detector.** An overnight move that snaps to a canonical split/bonus ratio with no NSE event
   is alerted (the paper crons' webhook), never auto-adjusted — NSE misses a few percent of events.
3. **Membership from NSE's official market cap from 2024-02-29**, pulled daily with the Bhavcopy
   refresh, with these requirements: companies mapped to engine symbols by ISIN through Bhavcopy
   (the MCAP file carries no ISIN; renames), `recovered_symbols` honoured, every series counted.
   Before 2024-02-29 keep the existing `pit_mcap` (static; no better source was measured — NSE's
   quarterly shareholding filings are the candidate if pre-2024 accuracy ever matters).
4. **Make the NSE gate point-in-time** (a company enters only from its first NSE bar), for all
   dates. This is the largest correction in the measurement and needs no Trendlyne data.
5. **Re-baseline.** Before Feb 2024 only step 4 changes anything. From Feb 2024 the universe drops
   the not-yet-listed and absent names, gains the uncovered ones, and fixes the ~1% share-count
   cases. Leaderboards and the 8 paper strategies' backtests are re-run and shown side by side
   before anything else moves.

## Consequences

- The monthly chore shrinks to the DVM-score script (weekly, ~20 min) plus the valuation pull while
  Value + Momentum ranks on Trendlyne's P/E (a separate study tests a free P/E).
- The ₹500cr gate becomes NSE's own number from Feb 2024 and stops drifting between harvests.
- New moving parts: a daily MCAP pull, an ISIN mapping, and the gap detector — all NSE-public, all
  alerting on failure the way the corporate-actions refresh does.
