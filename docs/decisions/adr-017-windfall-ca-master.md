# ADR-017: Derived corporate-action master + split-correct point-in-time market caps

Status: accepted
Date: 2026-06-20
Curated: yes
Category: cat:reliability
Title (showcase): "Reconstructing stock splits from price + share-count, with no corporate-action feed"

## Context
Survivorship-free backtests must trade delisted names, but those exist only as RAW NSE Bhavcopy
prices — a held dead name through a split would show a phantom overnight crash (a false stop-out =
optimistic bias). No reliable corporate-action feed exists for delisted names, and NSE Bhavcopy's
`prev_close` is NOT split-adjusted (verified on IRCTC's 1:5). Separately, the existing `pit_mcap`
(raw price x NP/EPS shares) was found to be ~10x WRONG for months around splits — not the
"~1-quarter boundary transient" ADR-015 assumed. Root cause: Trendlyne reflects a split in EPS on
an INCONSISTENT date across names — EICHERMOT's 10:1 stepped at the 2020-06-30 period-end (raw EPS)
while BEL's 2017 10:1 was back-adjusted (its 2016 EPS already shows post-split shares) — so pairing
those mis-timed shares with the raw price inflated mcap by the split factor. This corrupts the
survivorship universe the engine (iter-29) depends on.

## Decision
Derive a corporate-action master from data already on disk (user-approved over fetching NSE's
WAF-gated archive): a CA is the rare event that gaps the PRICE and steps the SHARE COUNT by the
same canonical factor (a crash gaps price only; an issuance steps shares only; a dividend does
neither). Detector = canonical overnight Bhavcopy price gap CONFIRMED by a share-count step
(Trendlyne NP/EPS, Trendlyne book-value shares, or screener NP/EPS for dead names) within +/-1yr.
Tables in `trendlyne.duckdb`: `ca_events`, `ca_factor` (back-adjustment), `delistings` (terminal-
exit registry + `ca_uncertain` flag).

Replace the broken pit_mcap formula with the exact identity **mcap(t) = adjusted_close(t) x
current_shares**: live names use Trendlyne's ground-truth adjusted `ohlcv`; dead names use raw
Bhavcopy x `ca_factor.adj_factor`. This is split/bonus-correct by construction and needs no
per-name guess about Trendlyne's EPS-adjustment convention.

## Consequences
- Validated: detector precision **0.95** vs Trendlyne adjusted/raw ground truth (live names);
  latest pit_mcap agrees with Trendlyne's reported mcap for ~90% of names within 15%; the four
  reference 10:1 splits (EICHERMOT/BEL/BAJFINANCE/TATASTEEL) are now smooth (max 2.0x MoM step).
- Honest-over-optimistic: detection recall is ~0.51, so dead names with an unconfirmable large gap
  are flagged `ca_uncertain` (135 of 250) and EXCLUDED from tradeability rather than mis-adjusted.
  Live names are unaffected by recall misses — they price off Trendlyne's adjusted ohlcv (IRCTC's
  undetected 1:5 is still split-clean).
- Known limitation (documented, second-order): `current_shares` is held constant back through
  history, so genuine share issuance/buyback over time is not separately modeled — immaterial vs
  the Rs500cr membership threshold and vs the 10x CA error it replaces.
- No look-ahead: back-adjustment is piecewise-constant per segment and scales the whole series by a
  constant, leaking no future information into returns (verifier-confirmed, 0/359 violations).
- Scripts: `backend/scripts/{build_ca_factor,rebuild_pit_mcap_ca}.py`. Read API:
  `backend/windfall/data/trendlyne_store.py`. Tests: `backend/tests/test_ca_factor.py` (16).
- Amends ADR-015: the pit_mcap CA effect was a systematic ~10x error on split names (incl.
  megacaps), not a bounded boundary transient.
