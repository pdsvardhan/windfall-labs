# adr-036 — Engine shipped hand-rolled; the vectorbt plan (adr-004) was not adopted

- **Status:** accepted
- **Date:** 2026-06-30
- **Supersedes:** adr-004 (Backtest core: vectorbt over a hand-rolled simulator)
- **Tags:** curated, cat:system, engine

## Context

adr-004 (2026-06-19) chose to build the backtest core *on top of* `vectorbt`'s
portfolio primitives, and adr-001 listed `vectorbt` in the stack. In practice that
plan was never adopted. The shipped engine in `backend/windfall/engine/backtest.py`
is a **from-scratch deterministic rebalance-and-hold simulator**: a pure
NumPy/pandas bar-by-bar event loop with daily explicit exits and a hand-coded NSE
cost model. `vectorbt` appears only in `requirements-optional.txt` and is imported
by **no runtime, CLI, test, or validation code** (`grep -r vectorbt` over the
package returns zero hits). The public docs already state this plainly
(`public_docs/technical-deep-dive.md`, `retrospective.md`); the ADRs did not, which
this decision corrects.

This was reconstructed during the 2026-06-30 Ottomate deep-dive reconciliation —
the implementation diverged from adr-004 without an ADR ever recording it (the
post-SO1-lock backfill gap).

## Decision

Record the as-built reality: the backtest core is a hand-rolled deterministic
simulator, and `vectorbt` is **not a dependency**. adr-004 is marked superseded by
this decision. The `rebalance-and-hold + daily explicit exits` semantics adr-004
specified still stand; only the vectorbt substrate was dropped.

Why hand-rolled won in practice:
- Full control over no-look-ahead (decision at close of `t`, fill at `t+1` open),
  intra-period stop/target/trailing/time exits, ADTV-capped sizing, and an exact
  side-aware NSE delivery cost model (adr-020) — all easier to make byte-for-byte
  deterministic and `config_hash`-taggable than bending vectorbt to fit.
- One fewer heavy dependency in a single-user tool.

## Consequences

- `vectorbt` stays in `requirements-optional.txt` only as an optional, currently
  unused cross-check substrate; it can be removed entirely later.
- Anyone reading adr-004/adr-001 must follow the supersession pointer to here.
- Aligns the decision record with the (already-honest) public docs and the tracker.

## Notes

Source: `backend/windfall/engine/backtest.py`, `requirements-optional.txt`,
`public_docs/technical-deep-dive.md`, `public_docs/retrospective.md`.
