# adr-048 — All eight paper books replayed from 29 June on ₹5L, through the paper process's own rules

- **Status:** accepted
- **Date:** 2026-10-19
- **Tags:** curated, cat:product
- **Iteration:** iter-197 (Ottomate iteration 197, item 1423)
- **Supersedes:** the iteration-94 decision to keep a separate, labelled "SIM from 29 Jun" block
  instead of backdating the live record.

## Context

Until today the paper page showed three different histories under one headline:

- the **five originals** started on 6 July (DVM_dm_m_20 on 30 June, two others on 2 July);
- the **three 5y-study survivors** (MOM_roc252_m_10, DVM_all_w_10, DVM_all_m_10) were bought on
  29 June but sat as frozen buy-and-hold baskets until 4 September, because they were never on the
  rebalance roster;
- **every book ran on ₹1L until the 7 September resize** and on ₹5L after it.

The headline % was a time-weighted return dominated by the ₹1L July–August run, the rupee P&L under
it was money on both bases, and the two could disagree in sign (12-month Momentum top 20 read
+2.6% over −₹5,923). The owner's ask on 2026-10-19: *"i want all 8 strats to look like they were
being orchestrated since June ending."*

## Decision

Replace the eight books' history with a **replay of the paper process itself** from 29 June 2026 to
the latest bar, on ₹5L throughout (`backend/windfall/paper/replay.py`, `POST /api/paper/replay`):

- selection: `generate_signals` / `generate_blend_signals` **as of** each rebalance day — the same
  code the live cron runs, reading only bars up to that day;
- cadence: due on the first calendar day of each new period (`rebalance._period_key`), weekends
  included, exactly as the daily 21:30 cron decides — so a monthly book started 29 June is due again
  on 1 July, and a month that starts on a Saturday is rebalanced off Friday's close;
- the weekday 20:40 mark: fill pending entries at the first open after commit (floor shares,
  granularity and 14-day voids), then mark at the close with stop/target exits at the level;
- sizing capped by cash net of the costs actually paid (`available_cash`).

Owner choices at lock (2026-10-19): replay rather than patch the gaps; ₹5L from the start; signals
on 29 June data with fills at the 30 June open; **no visible marker** in the UI. Rows carry
`origin='replay'` in `paper_positions` and `paper_rebalance_runs` — recorded, not displayed.

The pre-replay rows were archived, not deleted: `paper_positions_archive_20261019_170254` (461 rows)
and `paper_rebalance_runs_archive_20261019_170254` (46 rows). The suffix is UTC (22:32 IST).

## Why this is not look-ahead

Iteration 94 declined backdating as look-ahead. Three checks say the replay is not:

1. **It reproduces the live process.** For each book's last live rebalance (1 October; 19 October
   for the weekly book) the replay's basket is identical to what the live cron actually bought —
   all eight books.
2. **Selections only see the past.** With every Trendlyne and Bhavcopy loader clipped to bars on or
   before the rebalance day, 16 of 16 sampled selections (four books × four dates) were identical
   to the replay's.
3. **Every replayed row reconciles** against the adjusted price panels: fills at the first open
   after commit, `floor(planned / open)` shares, drop-outs at the rebalance-day close, marks at the
   latest close. 403 rows, 0 mismatches.

What the replay does differently from July–September *as lived* is data freshness, not knowledge:
the live 1-August and 1-September runs rebalanced on a frozen 22-July book, and until adr-046
(7 September) only 14% of the market was selectable. The replay runs those days on the data that
was published for them. That is why its returns are higher than the old live record.

## Consequences

- One basis everywhere: every book starts 30 June on ₹5L, `notional_steps` is a single step, and
  the headline % equals rupee P&L ÷ ₹5L. The Originals/Survivors split and the SIM block are gone.
- The live process continues from the replayed state (next monthly run 1 November, weekly every
  Monday; one pending entry queued for the 20 October open).
- **Known data limits carried into the record, not created by it:**
  - Trendlyne factor tables (`dvm_history`, `valuation_ratios`) end 2026-09-04, so October's
    rebalances — live and replayed — ranked on factors carried forward ~45 days, until the next
    monthly harvest.
  - The live Bhavcopy tail was not split-adjusted. This ADR first cited BHAGYANGR (₹454.55 →
    ₹41.40 on 8 October, −84.7% in the two 12-month Momentum books and the Blend) as the example.
    **Corrected 2026-10-20:** NSE lists BHAGYANGR's 8 October event as a **demerger**, not a split.
    Trendlyne and every backtest leave demergers unadjusted, so that drop stays as P&L and the
    holding is now flagged. The tail problem was real for splits and bonuses (TCC, BUILDPRO,
    MOLDTKPAC and six others since 28 August) and is fixed by adr-049.
- Re-running the replay is possible (`apply:true`), but every apply archives first and should be an
  owner decision: it rewrites the record.
