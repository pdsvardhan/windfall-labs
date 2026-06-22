# Multi-backtest Trendlyne-parity validation — NEXT SESSION work plan

**Goal:** run all ~10 replicable Trendlyne backtests through our engine and deep-dive each like Test A
(548776) — per-stock pricing reconciliation, name-by-name selection overlap, return decomposition,
thin-period cash drag, and a consolidated, severity-tagged issues list. All gold CSVs are already
downloaded (no fresh Trendlyne run needed).

## Where things are
- **Gold CSVs:** `back test examples/Backtest Excecution Detail-<id>.csv` (13 of them, archived). The
  harness scp's them to the server `/tmp/parity_gold/gold_<id>.csv` at run time.
- **Harness (in `_spike/`, copy to server `/tmp/` + `docker cp` into `windfall-api`):**
  - `parity.py <gold.csv> <freq> <floor>` — Phase A (current-membership, matches Trendlyne) + Phase B
    (survivorship-free). Decomposes: gold-picks@our-prices (PRICING) vs our-picks (SELECTION) vs gold
    NAV. Already has: asof pricing, ÷NHOLD fixed-slot cash, ca_uncertain exclusion, rename canon.
    **NOTE: its `cfg` is hardcoded — edit `entry_filters`/`rank_by`/`rank_order` per test (see table).**
  - `parity_price.py <gold.csv>` — per-stock our-price vs Trendlyne-CSV-price reconciliation (the
    authoritative pricing check; Test A = 0.04pp/stock).
  - `deep_testA.py` — name-by-name selection + per-period decomposition (template; re-point per test).
- Run in container: `docker exec -e PYTHONPATH=/app windfall-api python /tmp/parity.py ...`
  (pytest is NOT in the prod image — `pip install -q pytest` transiently if needed).

## Harness improvement to do FIRST
Parametrise `parity.py` to take the per-test config (filters, rank, order, freq, floor, nhold) instead
of the hardcoded `cfg` — drive it from the table below so all ~10 run in a loop.

## The backtests (screener → our config)

| id | name | our entry_filters | rank_by / order | freq | floor | window | verdict |
|---|---|---|---|---|---|---|---|
| 548012 | Tradeable (DVM-mom) | tl_durability>55, tl_valuation>50, tl_momentum>60, adtv_cr>10 | tl_momentum / desc | M | 1000 | 2021-07→26-06 | ✅ DONE (+5.5pp) |
| 548776 | Test A (value/PE) | +tl_pe>0 (same 4) | tl_pe / asc | M | 1000 | 2021-07→26-06 | ✅ DONE (overlap 90%) |
| **548042** | Short-term breakout | mcap>1000, adtv_cr>10, close>sma50, close>sma200, roc21>10, rsi14>60 | roc21 / desc | **W** | 1000 | 2025-06→26-06 | ✅ run — PURE TECHNICAL (new family) |
| **548040** | Pullback in uptrend | mcap>1000, adtv_cr>10, tl_durability>50, close>sma200, rsi14>40, rsi14<55 | tl_momentum / desc | **W** | 1000 | 2025-06→26-06 | ✅ run — technical mean-reversion |
| 548017 | Trend/regime proxy | tl_durability>55, tl_valuation>50, tl_momentum>60, adtv_cr>10, mcap>1000, close>sma200 | tl_momentum / desc | M | 1000 | 2021-07→26-06 | ✅ run |
| 548015 | Tighter momentum | tl_durability>55, tl_valuation>50, tl_momentum>65, adtv_cr>10, mcap>1000 | tl_momentum / desc | M | 1000 | 2021-07→26-06 | ✅ run |
| 548014 | Tighter momentum (20%) | (same as 548015) | tl_momentum / desc | M | 1000 | 2021-07→26-06 | ✅ run — **NHOLD=5** (20% max weight) |
| 547990 | Windfall v2.2 (monthly) | mcap>500, mcap<50000, tl_durability>50, rsi14>50, close>sma50, close>sma200, tl_pledge<20, adtv_cr>10, tl_pe<100, tl_momentum>60 | tl_momentum / desc | M | 500 | **2025-06→26-06** | ✅ run — full (pledge data exists post-2023) |
| 547989 | Windfall v2.2 (weekly) | (same v2.2) | tl_momentum / desc | W | 500 | 2025-06→26-06 | ✅ run — full |
| 547991 | Windfall v2.2 (monthly) | (same v2.2) | tl_momentum / desc | M | 500 | 2021-07→26-06 | ⚠️ PARTIAL — tl_pledge NaN pre-2023 |
| 547992 | Windfall v2.2 (quarterly) | (same v2.2) | tl_momentum / desc | Q | 500 | 2013→26-06 | ⚠️ PARTIAL — DVM only ≥2016, pledge ≥2023 |
| 547994/95 | DVM clones | tl_durability>55, tl_valuation>50, tl_momentum>60 | tl_momentum / desc | W/M | none | various | ❌ microcap coverage gap (~50% picks absent) |

## Per-test deliverable (mirror the Test A deep-dive)
1. Phase A pick-overlap %, avg stocks/period, turnover.
2. PRICING: `parity_price.py` per-stock mean|Δ| (target ≈0.04pp); flag CA/delisting outliers by name.
3. SELECTION: name-by-name — Trendlyne-only vs ours-only (frequency); classify each as
   merged/delisted-absent (survivors-only), microcap-absent, rename (should be fixed now), or
   marginal-boundary swap.
4. Return decomposition: gold NAV vs gold-picks@our-prices (pricing) vs our-picks (selection); the
   thin-period cash drag (÷NHOLD vs ÷n).
5. Verdict + issues.

## Expected issues to watch (from Test A + 548012 deep-dives)
- **Survivors-only:** merged/delisted-in-window names (IDFC, JSLHISAR, UJJIVAN, TATASTLBSL, GSPL)
  absent from the tl_ factor layer → unavoidable selection misses on DVM/fundamental screens.
- **Microcap coverage:** the no-floor DVM clones pick sub-₹500cr names we don't carry (~50% miss) — avoid.
- **Pledge horizon:** tl_pledge (shareholding) only from 2023 → v2.2 pre-2023 windows break that filter.
- **DVM horizon:** dvm_history only from 2016-06 → pre-2016 backtests (547992/quarterly) unreplicable early.
- **ca_uncertain:** GVKPIL-type penny stocks excluded from parity (unconfirmable CA).
- **Technical mapping:** Trendlyne "Day RSI"=RSI(14), "Day ROC21"=ROC(21), "Day SMA50/200"=sma50/200,
  "Current Price > X" = `close > X`. CONFIRM these map exactly (548042/548040 are the test of this).
- **548014 weighting:** 20% max weight = 5 effective slots → set NHOLD=5 in the harness for that one.
- **Traffic-lights (547861/62):** screener had NO sort shown — confirm Trendlyne's default ranking
  before replicating (not downloaded; skip unless clarified).
- **rename fix (iter-34/adr-025):** renamed names (NAVA←NBVENTURES) should now match — verify overlap
  improved vs the pre-fix baseline on the momentum screens.

## Output
A consolidated table (per test: overlap %, pricing Δ, headline our-vs-Trendlyne, top issues) + one
ranked issues list across all tests. This is the engine's full cross-style veracity report.
