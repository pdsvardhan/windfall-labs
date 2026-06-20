# ADR-015: Survivorship-free point-in-time universe membership

Status: accepted
Date: 2026-06-20

## Context
The investable-universe filter is "NSE-listed + market cap > Rs500 Cr". Applied with
today's membership it is survivorship-biased: look-ahead in selection (using today's
size for a past date) and dead companies are absent entirely.

## Decision
Build a point-in-time market-cap series and a survivorship-free membership table.
- `mcap(t) = raw_close(t) x shares(t)`, where `shares = NP/EPS`. EPS_TTM/EPS_A are RAW
  (not split/bonus-adjusted — verified: the ratio doubles at each split/bonus), so they
  must be paired with **raw Bhavcopy price**, never Trendlyne's adjusted close (which
  would collapse historical mcap by the split factor). Tables: `pit_shares`, `pit_mcap`.
- Dead/delisted names: classified via Bhavcopy **ISIN continuity** (renames where the
  ISIN still trades vs truly-dead where it stops). Renames -> `rename_map` (already covered
  under the successor symbol). Truly-dead fundamentals scraped from screener.in (serves
  delisted pages; 169/256 = 66% yield) -> `pit_mcap_dead`.
- Capstone `universe_membership` (live + dead), symbol-keyed; eligible = `mcap_cr > 500`.

## Consequences
- Survivorship quantified: in 2016, 77 of 563 eligible names (14%) later died — now
  included so backtests experience their fate. Validated PIT-mcap vs current mcap: 3%
  median error (fine for a 500cr threshold).
- Usable window 2016-2026 (pre-2016 per-share EPS is sparse; matches the DVM start).
- Known limitation: ~1-quarter mcap transient around a stock's bonus/split (quarterly
  shares vs ex-date price); affects only names sitting at the Rs500cr boundary with a CA
  in-window; megacaps unaffected. Full fix needs the NSE split master (tracked to-do #28).
- Scripts: `backend/scripts/{build_pit_mcap,gen_dead_list,extend_pit_mcap_dead,build_membership}.py`.
