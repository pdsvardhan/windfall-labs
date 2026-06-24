# adr-031 — Detect silently-delisted live names (e.g. GSPL merger) and record a terminal exit

**Status:** accepted · **Date:** 2026-06-24 · **Source:** data audit 2026-06-24, finding F5

## Context
A currently-listed (pk-keyed) name that stops trading — via merger or delisting — never reaches the `dead_names` / Bhavcopy dead-name path (that path is for names with no pk). So it drops out of the data **silently**: no terminal-exit record in `delistings`, uncounted in coverage, no data-quality warning. The audit caught GSPL (Gujarat State Petronet, ever ~₹26,000cr) whose Trendlyne `ohlcv` and NSE Bhavcopy both stop at 2026-05-11 (a real merger exit) while Bhavcopy overall runs to 2026-06-24 — a large name vanishing with no record.

## Decision
Add a "live silent delisting" detector to `build_ca_factor.py` (reproducible on every full rebuild) plus a one-time migration (`migrate_f5_delistings.py`): a pk-keyed name whose **ohlcv last-bar AND Bhavcopy last-bar are BOTH >30 days before their respective global maxima** has genuinely stopped trading (not merely lagged) and is inserted into `delistings`. Requiring BOTH sources to have stopped prevents a Trendlyne-only ingest lag from wrongly terminal-exiting a live stock.

## Consequences
- GSPL now has a terminal-exit record (last_date 2026-05-11, last_close ₹268.4, ever_mcap ₹25,982cr); its held-position exit and coverage count are honest.
- The same migration refreshed `delistings.ever_mcap_cr` for the adr-030 seeded dead names.
- Caveat: the 30-day threshold has margin only while ohlcv ingest stays current (it is 8d behind Bhavcopy today); a large ohlcv staleness regression (F9) could let live names trip it — monitor with the F9 refresh follow-up.

## Verification
Detector independently re-run flags EXACTLY GSPL and 0 genuinely-live names; no duplicate insertion despite running in both the builder and the migration (NOT IN guard).
