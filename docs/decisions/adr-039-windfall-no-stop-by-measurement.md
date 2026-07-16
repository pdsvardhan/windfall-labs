# adr-039 — No stop-loss, by measurement (iter-22)

**Status:** accepted · **Date:** 2026-07-16

## Context

Open item #99 ("harness R2") recorded that a trailing-ATR stop whipsaws the monthly rotation: 94% of
exits were stops, 14-day average holds, 32% win rate. It was carried for weeks as a blocker on the
real-money path, on the understanding that the live book was being shaken out by its own stop.

Two checks reframed it:

1. **No saved strategy uses a stop.** All 289 configs in the store have `stop_loss.type = "none"`,
   including every strategy in the paper dry-run (DVM_user, DVM_dm_m_20, MOM_roc252_m_20,
   CMP_valmom_m_20, and the BLEND_70_30 composite). Several carry a vestigial
   `mult: 2.5, atr_period: 14` under a `none` type — inert config that never fires. #99 measured a
   harness experiment, not the live path. Nothing was being whipsawed.
2. **The question was therefore inverted:** not "how do we fix the stop" but "should a stop exist at
   all?" That is measurable, so it was measured rather than argued.

## Decision

**Run with no stop-loss.** The monthly re-rank is the only exit. #99 is closed as answered.

A stop sweep over all four paper strategies (identical resolve, stop varied sim-side only) is
unambiguous — the no-stop baseline wins on Sharpe in 3 of 4 and ties in the fourth, and trailing stops
are actively destructive at every width tested:

| DVM_user (monthly, n=10) | CAGR | MaxDD | Sharpe | Win | Hold |
|---|---|---|---|---|---|
| no-stop (current) | **33.6%** | −74.7% | **1.16** | 51.7% | 51.9d |
| trailing 2× ATR | −12.6% | −77.8% | −0.93 | 33.6% | 11.1d |
| trailing 3× ATR | 6.3% | −63.8% | 0.41 | 39.4% | 22.8d |
| trailing 4× ATR | 17.0% | −65.1% | 0.78 | 44.8% | 32.5d |
| trailing 5× ATR | 22.7% | −70.7% | 0.94 | 47.8% | 40.0d |

The shape repeated across all four strategies: a 2× trailing stop turns every one of them **negative**,
and loosening the stop walks monotonically back toward the no-stop result. The limit of "loosen the
stop" is "remove the stop" — so there is no trailing configuration worth adopting, including the wide
catastrophic variant considered at the outset.

This also closes out #99's provenance: at 2× ATR, DVM_user reproduces 11.1-day holds and a 33.6% win
rate against R2's recorded 14 days and 32%. Same experiment, now explained.

**Fixed-percentage stops** (`type: pct`, fired from entry, no ratchet) are roughly free but roughly
pointless: DVM_user at −25% returns CAGR 32.6% / Sharpe 1.16, statistically indistinguishable from
no-stop. The single defensible cell is MOM_roc252_m_20 at −20%, which trades 2.6pp of CAGR and 0.02 of
Sharpe for 8pp of max drawdown (−54.4% → −46.4%). Recorded as available, not adopted: it is a
drawdown *preference*, not an improvement.

## Consequence

- No config change. The status quo was already correct; what changed is that it is now correct *on
  evidence* rather than by accident, and #99 stops blocking the deploy path (#103).
- The ATR/trailing machinery stays in the engine (`backtest.py` `check_exit`, `_stop_target`) — it is
  exercised by tests and by the harness, and remains available to any future strategy designed around
  it. What is rejected is bolting it onto a rank-driven rotation whose edge needs time to play out.
- Vestigial `mult`/`atr_period` under `type: none` in ~288 stored configs are left as-is (inert), but
  they are a documented foot-gun: they read as "there is a 2.5× stop here" to anyone skimming.
- **Drawdown remains unaddressed and is the real risk item.** All four strategies draw down 55–75%,
  and the best stop configuration still leaves −44%. Stops are not the lever. That is a regime-overlay
  and position-sizing question, and it is now the open question standing between the paper run and
  real capital — see #103.
- Sweep harness: `scratchpad/stop_sweep.py` (resolve-once batch, `save=False`).

## Note on method

The first sweep returned "trailing 3× ATR = byte-identical to no-stop," whose natural reading is
"stops make no difference" — the opposite of the truth (CAGR 33.6% → 6.3%). The cause was a silent
defect in `/api/backtests/batch` (#210): it resolves once from `base_config`, and `resolve.py:373`
only builds the ATR panel when the base config *already* asks for a trailing stop, so a
`stop_loss.type` grid off a no-stop base simulates no stop at all and labels the result as though it
applied. The endpoint documents `stop_loss.*` as sweepable (`main.py:76`); it is not. Caught only
because byte-identical summaries across a varied parameter are implausible. Variants here were
therefore resolved *from* a trailing base, with only `stop_loss.mult` gridded (genuinely sim-side).
