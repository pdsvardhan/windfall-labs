# adr-050 — Prices and market cap from free NSE data: freeze Trendlyne's price history, take membership from NSE's official market cap

- **Status:** proposed (measurement done in iter-200; the switch is a separate, owner-locked iteration)
- **Date:** 2026-10-20
- **Tags:** curated, cat:reliability
- **Iteration:** iter-200 (Ottomate iteration 200, items 1460–1463)

## Context

The monthly Trendlyne refresh is ~1.5 hours of console scripts in the owner's logged-in browser
(`docs/ops/trendlyne-refresh-runbook.md`). Only one part of it has no free substitute: the DVM
scores four paper books rank on. The rest feeds two things that free NSE data can carry:

- **split-adjusted prices** — Trendlyne `ohlcv` (OHLCV + megacap harvesters), spliced onto raw
  Bhavcopy after the last harvested bar (adr-022/044; split/bonus tail adjusted since adr-049);
- **point-in-time market cap → the ₹500cr universe** — `pit_mcap` = adjusted close × a share count
  derived from Trendlyne's NP/EPS (`rebuild_pit_mcap_ca.py`, `pit_shares`).

iter-200 measured both against Trendlyne and against NSE's own numbers. Scripts:
`backend/scripts/free_layer/`; data: `backend/data/free_layer.duckdb`.

## What was measured

**Corporate actions (item 1460).** NSE's corporate-actions API returns full years back to 2010:
521 splits, 524 bonuses, 33 same-day bonus+split, 1 consolidation, 107 demergers, 93 schemes, 350
rights issues. Against the app's 450 share-step-confirmed `ca_events`: 369 on the same date, 363
with the same ratio — and several app events NSE does not list are false detections (repeated
1.25 "splits" on BIRLAMONEY and KITEX are 20% circuit moves). NSE's list has real gaps too
(JSWSTEEL 2017, KARURVYSYA and CGCL 2016, HEG 2024, NAZARA, GPIL, HERITGFOOD, AJANTPHARM).

**Prices (item 1461).** Bhavcopy divided by NSE's split/bonus ratios plus the standard
theoretical-ex-rights (TERP) adjustment for rights issues priced below market, compared with the
factor Trendlyne applied on every day for 1,700 live names:

| Event source | Names fully matching (≥99% of days) | Name-days matching |
|---|---|---|
| NSE splits/bonuses | 93.2% | 95.8% |
| NSE + rights (TERP) | 93.5% | 96.3% |
| NSE + rights, 2016 onward | **95.9%** | **97.9%** |
| app `ca_events` alone | 77.6% | 87.3% |

Adding the app's own events to NSE's makes it *worse* (their false positives). The residual is
NSE's missing events and a few names whose Trendlyne factor drifts for other reasons.

The decisive observation is not the match rate: **Trendlyne's price history is static.** A
harvested bar never changes. Nothing requires re-downloading it monthly; only the newest stretch
goes stale, and since adr-049 that stretch is already Bhavcopy adjusted from NSE's list.

**Market cap and the ₹500cr universe (item 1462).** NSE's daily price bundle carries an official
market-cap file (issue size × close for every security) from **2024-02-29**. Scored against NSE's
official ">₹500cr" set at 30 month-ends (Feb 2024 – Jul 2026), with the strategies' own NSE-only
gate (symbol ever traded in series EQ, adr-024) applied to every set:

| Universe | Wrongly admitted / month | Missed / month | Errors |
|---|---|---|---|
| current (Trendlyne-derived shares) | 61–177 | 0–7 | **10.5%** |
| free (that month's NSE share count) | 0 | 9–68 | **2.7%** |
| share count frozen at Feb 2024 | 0–4 | 67 → 417 | 14.3% |

- The free method's misses are names Trendlyne carries **no price for at all** (AKCAPIT, ARIHANT,
  ASHIKA…, invisible to the engine today too), plus a basis mix-up in the measurement itself
  (a split-adjusted close × a pre-split share count — TEMBO, MWL). NSE's own market-cap figure
  avoids both.
- Holding a share count constant goes wrong fast — ~20% of names changed share count by more
  than 10% in 2.5 years, net of splits and bonuses — so a frozen count is no rule for the past.
- REITs and InvITs sit in `universe_membership` but never reach a strategy (no EQ series); no
  paper position, current or archived (213 tickers), has ever held one.
- Paper exposure to the current method's looser universe is small: **4 of 389** paper buys were
  in names NSE's official figure put under ₹500cr at the time (all DVM-all-three weekly,
  ₹428–470cr).

Also found: `corp_actions.parse` reads only the first event of a combined subject ("Bonus 1:1 /
Face Value Split From Rs.10/- To Re.1/-"). No row in the live window is affected — current NSE
filings list the two separately — but a backfill would be.

## Proposed decision (for the owner to lock as its own iteration)

1. **Freeze Trendlyne's price history at its last harvest and stop the OHLCV and megacap
   harvests.** The tail beyond it is Bhavcopy adjusted from NSE's list (live since adr-049), now
   also adjusted for rights issues (TERP), with `parse` fixed for combined subjects.
2. **Gap detector.** An overnight move in a held or selectable name that snaps to a canonical
   split/bonus ratio with no NSE event is alerted (same webhook as the paper crons), never
   auto-adjusted — NSE's list misses a few percent of events.
3. **Membership from NSE's official market cap from 2024-02-29 onward.** Pull the daily MCAP file
   with the nightly Bhavcopy refresh; keep the existing `pit_mcap` for earlier dates — that history
   is static too, and it beats every free alternative measured for those years.
4. **Re-baseline.** Backtest windows before Feb 2024 are unchanged. From Feb 2024 the universe
   sheds the 61–177 names per month the current share counts let in wrongly; leaderboards and the
   8 paper strategies' backtests are re-run and reported side by side before anything else moves.

## Consequences

- The monthly chore shrinks to the DVM-score script (weekly, ~20 min) plus the valuation pull
  while Value + Momentum ranks on Trendlyne's P/E (a separate study tests a free P/E).
- The ₹500cr gate becomes exact from Feb 2024, stops depending on derived share counts, and stops
  drifting between harvests.
- Names Trendlyne never priced (~65 above ₹500cr) stay invisible unless a later step prices them
  from Bhavcopy too.
- New moving parts: a daily MCAP pull and the gap detector — both NSE-public, both alerting on
  failure the way the corporate-actions refresh does.
