# adr-049 — Corporate actions come from NSE; splits and bonuses in the live tail are back-adjusted, demergers are not

- **Status:** accepted
- **Date:** 2026-10-20
- **Tags:** curated, cat:reliability
- **Iteration:** iter-199 (Ottomate iteration 199, to-do #952)

## Context

Live names are priced from Trendlyne's split-adjusted `ohlcv` up to its last harvested bar
(2026-08-28 for most) and from **raw** NSE Bhavcopy after it (adr-022's live splice, made
per-symbol by adr-044). A split or bonus whose ex-date lands in that tail reads as a 50–90%
overnight crash — to momentum ranks, to stops, to paper marks, and to the Bhavcopy market-cap
fallback that keeps names eligible (adr-046) — until the next harvest re-adjusts history. Between
28 August and 20 October nine did: AASTHA, BANSALWIRE, BLSE, BUILDPRO, MOLDTECH, MOLDTKPAC, PGIL,
TAALTECH, TCC.

Nothing already in the data layer could tell such a step from a real crash. Trendlyne's
`corporate_actions` export carries dividends, bonuses and rights only, last ex-date 2026-06-24.
Bhavcopy's `prev_close` is adjusted on some events (CCAVENUE's consolidation) and not on others.
`build_ca_factor.py`'s method needs a share-count step from fundamentals that lag by months.

The case that opened the to-do was itself mis-diagnosed: BHAGYANGR's ₹454.55 → ₹41.40 on
8 October was read (in iteration 197 and adr-048) as a split. Volume and trade count *fell* that
day, the exchange did not adjust `prev_close`, and NSE lists the event as a **demerger**.

## Decision

1. **Source.** NSE's `corporates-corporateActions` API (reachable from the server with the
   landing-page cookies, the same pattern as the ASM/GSM fetch) is fetched in-process over a rolling
   window and stored in `nse_corporate_actions` (`windfall/data/corp_actions.py`). Split, bonus and
   consolidation subjects are parsed to a price ratio; demergers and schemes are stored as typed
   events with no ratio. Refreshed daily by the 9:00 surveillance cron.
2. **Convention = Trendlyne's.** Measured on events Trendlyne already covers: splits and bonuses
   are back-adjusted (TEMBO 1:10 → ×0.1, GOODLUCK bonus 2:1 → ×1/3, TRENT bonus 1:2 → ×2/3);
   demergers are not (GUJENERGY, TRIVENI, INOXGREEN unchanged across the ex-date). So
   `adjusted_close_panel` divides every bar before a ratio event's ex-date by its ratio, **only**
   when the ex-date is after that name's last Trendlyne bar. The latest bar stays the raw traded
   price, and the series equals what Trendlyne will publish — nothing moves when it catches up, and
   nothing Trendlyne already adjusted is adjusted twice. The market-cap fallback scales its share
   count from the ex-date the same way.
3. **Paper re-base.** A position that spans a ratio event is put back on one basis at the next
   mark — entry, stop and target divided by the ratio, shares multiplied, cost unchanged — but
   only when the stored entry divided by the adjusted fill-day price confirms the ratio. An entry
   already on the adjusted basis is left alone; any other mismatch is reported, not changed. Every
   re-base is recorded in `paper_ca_rebases`.
4. **Demergers stay a loss, flagged (owner, 2026-10-20).** The parent's drop counts as P&L — the
   same treatment as Trendlyne's series and every backtest — and a holding that spans one carries
   "demerger <date> — new company's shares not counted". Crediting the new company's shares would
   need the scheme ratio from NSE filings and would make paper disagree with every backtest.

## Consequences

- The replay (adr-048) was re-run on the corrected prices with the owner's approval (archive
  `20261020_065005`). One selection moved: Value + Momentum's 1-October rebalance takes TCC (its
  4-September split had read as −80%) instead of KAMDHENU; that book goes from +21.5% to +20.5%.
  The other seven books are identical trade for trade.
- No current paper position spans a split or bonus, so no re-base has fired yet; the path is
  covered by tests and runs at every mark.
- Backtests that end before a name's last Trendlyne bar are unaffected. Live signals and paper are
  the consumers that change.
- BHAGYANGR's −84.7% in the two 12-month Momentum books and the Blend stands, now explained.
- The feed depends on NSE's public API. A failed refresh leaves yesterday's list in place (logged);
  a stale list can only miss an adjustment, never invent one.
