# adr-044 — adjusted_close_panel splices live prices from one batch-wide last bar, leaving holes per symbol

- **Status:** open
- **Date:** 2026-09-04
- **Tags:** curated, cat:reliability
- **Iteration:** iter-171 (found while building item 1229)

## Context

`adjusted_close_panel(symbols, extend_live=True)` extends the Trendlyne series with live Bhavcopy
using a single scalar:

```sql
SELECT MAX(date) FROM ohlcv WHERE pk IN (…every requested symbol…)   -- last_tl
…
WHERE series IN (…) AND date > last_tl                              -- the splice
```

`last_tl` is the maximum Trendlyne date across the **whole batch**. Any symbol whose own history
ends earlier than the batch maximum gets no Bhavcopy rows for the gap between its last bar and
`last_tl` — so its column carries leading NaNs, or vanishes entirely.

Measured 2026-09-04: `SCPL` requested alone returns a full series from 2026-06-29. Requested inside
the 98-name paper batch, its first non-NaN value is 2026-07-09 — eight leading NaNs. `.ffill()`
cannot repair a leading gap, so `book_equity` valued the holding at its **entry price** for its whole
holding period. SCPL was held 6–31 Jul and closed +14.9%; every day in between reported 0.0%, a flat
line that jumped to the truth only on the exit date. The endpoint was right; the path was fiction.

The same mechanism applies to any multi-symbol request — **including backtests**, which is why this
is filed rather than fixed.

## Decision (interim, iter-171)

The paper equity curve fills its own holes: `_with_bhavcopy_fallback` overlays raw Bhavcopy closes
onto NaN cells only, so adjusted prices always win where they exist. Bounded to the paper book's
weeks-long window, where a split or bonus would be visible as a step. Measured impact of the raw/
adjusted mix over the current window: **0.000% divergence** across every overlapping cell of the
seven held names checked.

`last_tl` itself is left alone.

## Why it is not fixed here

Making the splice per-symbol (extend each name from *its own* last Trendlyne bar) is a three-line
change and is almost certainly correct. But it adds price history to any backtest containing a name
whose Trendlyne coverage ends early, which silently changes results the project has already published:
the 2026-07-17 leaderboards, the robustness verdicts, adr-040's walk-forward gate and adr-032/adr-040's
parity ledger. Re-baselining those is a deliberate act with its own verification, not a side effect of
a paper-marks iteration.

## Open questions

1. How many names in the backtest universe actually have Trendlyne coverage ending before the batch
   maximum? Until that is counted, the blast radius is unknown — it may be negligible or systematic.
2. Does the hole bias results in a direction? A name valued at entry cost for part of its holding
   period understates both gains and losses, so it dampens measured volatility and may flatter Sharpe.
3. Should the per-symbol splice land together with the adr-043 dead-name question, as one deliberate
   data-layer re-baseline with a single re-run of the leaderboards and the parity ledger?
