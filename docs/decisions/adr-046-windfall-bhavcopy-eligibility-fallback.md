# adr-046 — Universe eligibility falls back to Bhavcopy, so the system stays operational between manual harvests

- **Status:** accepted
- **Date:** 2026-09-07
- **Tags:** curated, cat:reliability
- **Iteration:** iter-172

## Context

Windfall has two price sources with opposite operational characteristics. NSE Bhavcopy arrives on a
server cron every weekday evening and needs nobody. Trendlyne's split-adjusted history is WAF-gated
and arrives only when the owner runs a ~40-minute script in a logged-in browser.

`harvesters/README.md` told the owner, correctly, that skipping the Trendlyne price harvest was
normal:

> *"NOT needed for freshness — Bhavcopy carries prices to today and `adjusted_close_panel` splices
> it on. Skipping it is normal."*

That is true of **prices**. It is false of **eligibility**, and nobody noticed the difference. The
Trendlyne `ohlcv` table also feeds `rebuild_pit_mcap_ca.py` → `pit_mcap` → `universe_membership`,
which decides *which stocks may be picked at all*. That chain has no Bhavcopy fallback. So the
documented-as-safe action silently froze the candidate list.

It stayed invisible while everything was equally stale. Measured 2026-09-07, after a harvest that
refreshed D/V/M for everyone but prices for only the megacap leg:

| | before the harvest | after |
|---|---|---|
| most stocks' last price bar | 2026-07-08 | 2026-07-08 (unchanged) |
| megacap stocks' last price bar | 2026-07-08 | 2026-08-28 |
| newest bar with any eligible name | 2026-07-15 | 2026-09-04 |
| names eligible on that bar | ~1,921 | **293** |

`membership_panel` bridges gaps with `ffill(limit=10)` — about two trading weeks. Before, the
newest usable bar sat five trading days after everyone's last reading, so the bridge covered the
whole universe. Refreshing 257 names dragged the newest bar forward two months and pushed the other
~1,900 outside it. **A partial refresh was worse than no refresh.**

Consequences were live, not theoretical: all 140 held-or-bought positions across eight paper books
came from the 293 survivors, and not one from the other 1,897. Nothing warned, because the existing
protection asks *"is the eligible set empty?"* — and 293 is not empty. The guard is all-or-nothing;
the failure was partial.

## Decision

`membership_panel` falls back to Bhavcopy — close × the same share count the primary path used —
where the primary panel has no value. Three properties keep it honest, each pinned by a test:

1. **NaN cells only.** A real Trendlyne-derived reading always wins. Any date that already had data
   is untouched.
2. **Only past a symbol's own last real reading.** Interior historical holes are left alone; they
   are a separate question with its own measurement (to-do #92).
3. **Only where Bhavcopy actually priced that symbol that day.** A delisted name has no such rows,
   so it still drops out of the universe rather than looking perpetually eligible — the invariant
   the original docstring existed to protect.

Measured blast radius: the earliest date the fallback touches anything is **2026-06-29**, and
**zero cells before 2026** are affected. Every published backtest, walk-forward fold and parity
result is unchanged by construction, not by assertion. Eligible names on the last bar go from
**293 → 1,724** of 2,190.

The fallback announces itself in `warnings[]` — *"1,599 of 2,190 names … priced from Bhavcopy
instead … run the Trendlyne OHLCV harvest"* — because a silent rescue would recreate the original
sin in a friendlier form.

## Consequences

- The manual harvest is now a **quality** step, not an **availability** step. Skipping it costs
  split-adjustment fidelity on recent bars, not the ability to pick stocks.
- Recent-bar market caps for filled names use raw Bhavcopy closes. Over a window this short a split
  would show as an obvious step, and the ₹500cr floor is far from most names' cap, so a borderline
  misclassification is unlikely — but it is a real, bounded approximation, disclosed in the warning.
- The all-or-nothing guard in `generate_signals` is still all-or-nothing. It should complain when
  the eligible set *collapses* relative to its recent norm, not only when it hits zero. Filed
  separately; this ADR removes the cause, not the blind spot.
- `harvesters/README.md` is corrected. The claim was not wrong so much as **over-generalised from
  one subsystem to all of them**, which is the kind of error that reads as authoritative.

## The lesson, stated plainly

A fallback for the *data* is not a fallback for the *decisions derived from that data*. Bhavcopy
had covered prices for months, and everyone — the docs, the code, and this assistant — reasoned
"prices are fine, therefore we are fine." Eligibility was one join away and had no fallback at all.
Where a manual step gates an automated system, the automated system should degrade, not stop.
