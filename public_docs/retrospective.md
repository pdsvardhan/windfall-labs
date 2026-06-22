---
public: true
type: retrospective
title: Retrospective — Windfall Labs
order: 4
summary: The data layer was the project; the engine was the easy part.
read_minutes: 4
---

# Windfall Labs — Retrospective

## The tradeoff that defined the build
Roughly two-thirds of the recorded decisions (ADR-003, 007, 011, 013, 014, 015, 016, 017) are about **data**, not algorithms. Building an honest backtest turned out to be a data-sourcing problem first: getting survivorship-free prices, point-in-time universe membership, real result-announcement lag, and reconstructed corporate actions — none of which a free screener hands you. The simulator itself is a few hundred lines; the layer that feeds it truth is the actual work.

## Build vs. buy, twice
The engine plan was to lean on **vectorbt** (ADR-004). The shipped engine is hand-rolled. Owning the simulation gave full control over no-look-ahead, cost accounting, and daily exits — and made them testable — but it also means correctness is the author's responsibility, which is precisely where the warmup bug hid. The mirror-image decision went the other way: the homegrown D/V/M scores (ADR-010) were **removed** (ADR-019) once they proved to only approximate Trendlyne's DVM at ~0.44–0.88 rank-correlation while adding a parallel path to maintain. Strategies now use raw survivorship-free fundamentals or Trendlyne's own scores directly. Two opposite calls, same principle: keep only what you can defend.

## Optimism leaks in quietly
The most instructive lessons were near-misses caught in review, not crashes. A cash-holding strategy reported **+8.71% "active return"** simply because the index fell while it sat in cash (ADR-008) — a number that read as alpha and was an artifact of not being invested. Separately, the engine was found running on garbage configs — inverted dates, 0 capital, 0% stops — and silently producing results (ADR-021). And the parity study's two "silent empty book" findings are the same family: the *behavior* (can't trade without data) was defensible, but the *silence* reproduced exactly the gaslighting the platform exists to remove. The recurring learning: in quant tooling, the dangerous failures are the ones that look like answers.

## Honest current state
Stale tests remain (3 failures pointing at the removed own-DVM), scheduled jobs are unfinished, alerts are scaffolded only, and some data limits are accepted rather than solved (NSE-only universe, un-ingested recent IPOs). The deliberate non-goals — signals-only, no live trading, single-user, no public exposure — keep the surface small enough that "validate everything" stays achievable. The bet so far is paid down on engine veracity, not on live results, and the docs say so.
