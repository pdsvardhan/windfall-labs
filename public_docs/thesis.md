---
public: true
type: thesis
title: Project Thesis — Windfall Labs
order: 1
summary: A private quant cockpit that refuses optimistic backtests for Indian equities.
read_minutes: 3
---

# Windfall Labs — Project Thesis

## Problem
Screener tools like Trendlyne make systematic equity research look easy and profitable — and that is the trap. They cap rebalance frequency, ignore real transaction costs and slippage, never model explicit exits, run on survivorship-biased "today's universe" lists, and leak look-ahead. So a backtest can show a clean edge that evaporates the moment real money is on it. A concrete example that motivated this build: a weekly momentum screen showed +17% gross but churned ~53% per week; the same selection made +17% with weekly loss-cutting versus −17% when simply held a month. The number was real; the way it was measured was a lie.

## The bet
Build one private cockpit where a strategy can only earn trust by surviving honest measurement. Define a strategy once as a declarative config, then run it through a fixed loop: backtest over 10+ years with modelled NSE costs and explicit exits → validate the engine against a known result → prove robustness with walk-forward (in-sample vs out-of-sample) → generate today's exact buy/hold/sell orders → paper-trade it before any capital. Principles are baked in, not optional: realism over optimism, exits are first-class, no look-ahead, no survivorship, liquidity-aware, validate everything, human in the loop.

## Audience
A single quant-minded investor (the author). It is a private, single-user tool — not a product, not a SaaS.

## In scope (v1)
Daily NSE equities; declarative strategies; survivorship-free backtests; walk-forward; live signal generation; a paper-trade log; a Next.js cockpit.

## Out of scope (v1)
Broker order execution (signals-only — the human places every order), intraday / F&O, public internet exposure, multi-user auth, and automated live trading.

## Success criteria
Reproduce a known Trendlyne backtest within tolerance before the engine is trusted; backtest any price strategy over 10+ years with costs, slippage and stops; produce a walk-forward degradation report; one-click today's orders for any saved strategy; and a marked-to-market paper-trade log. Runs are deterministic and tagged by config hash.
