# adr-043 — Pricing reads NSE mainboard series (EQ/BE/BZ); universe, ADTV and dead-name history stay EQ-only

- **Status:** accepted
- **Date:** 2026-09-04
- **Tags:** curated, cat:reliability
- **Iteration:** iter-171 (item 1228)

## Context

Every price path in the Trendlyne store filtered `series='EQ'`. On 2026-09-04 that was measured to
freeze live paper marks: when a holding moves from EQ (rolling settlement) to **BE** or **BZ** —
the trade-for-trade / surveillance segments — it disappears from the live splice, `mark_to_market`
skips it silently, and `book_equity` forward-fills its last EQ close indefinitely.

Ten open positions were affected, some for eight weeks:

| name | book mark | real close 2026-09-04 | booked | true |
|---|---|---|---|---|
| STALLION | 254.00 (10-Aug) | 206.68 | +34.0% | +9.0% |
| BLISSGVS | 512.95 (08-Jul) | 671.00 | −3.2% | +26.6% |
| MTARTECH | 6826.50 (08-Jul) | 7161.00 | −9.9% | −5.5% |
| HFCL | 226.27 (02-Sep) | 231.44 | +0.6% | +2.9% |

HFCL is the clean proof: EQ through 2 Sep, BE from 3 Sep, mark dead from that day — while
`bhavcopy_prices` carried it priced through 4 Sep the whole time. The data was always there; the
filter dropped it. Reported returns moved by −1.0pp (MOM_roc252_m_20), −0.8pp (BLEND_70_30) and
**+3.6pp** (MOM_roc252_m_10) once corrected.

## Decision

`MAINBOARD_SERIES = ("EQ", "BE", "BZ")` governs **pricing only** — the live splice inside
`adjusted_close_panel` and the new `raw_close_panel`. BE and BZ are the same shares on the same
exchange, still deliverable; only intraday netting differs. A holding under surveillance is exactly
when an honest mark matters most. SME series (SM/ST) stay excluded: a different platform.

**Deliberately NOT widened**, and this is the load-bearing half of the decision:

- `_nse_symbols()` — the investable-universe gate (adr-024). Widening changes which names a strategy
  may *select*.
- `traded_value_panel()` — ADTV / liquidity sizing. Widening changes position sizes.
- the dead-name history splice — widening changes ten years of backtested exits.

Each of those three re-baselines every backtest and leaderboard the project has produced. They are
separable questions, and each deserves its own measurement rather than riding along with a marks fix.

## Consequence

Marks and the live signal path see a name's real price for as long as it trades anywhere on the
mainboard. Backtests, universe membership and liquidity sizing are byte-identical to before this
change — verified: the four paper books with no BE-series holdings reproduce their prior figures
exactly.

## Open — needs its own measurement

1. **Should the investable universe include BE/BZ names?** Buying into trade-for-trade carries
   100% margin and no netting. Arguably a strategy should never *enter* there — but it should
   certainly keep pricing a name that moves there while held.
2. **Should the dead-name splice include BE/BZ?** A delisting usually runs EQ → BE/BZ → gone. Cutting
   at EQ truncates the final decline, which *understates* the loss — optimistic survivorship bias, the
   exact thing the survivorship-free layer exists to remove. This one likely wants fixing, and it
   will move historical results.
3. **Should ADTV count BE/BZ turnover?** It is real turnover, but at a different liquidity character.
