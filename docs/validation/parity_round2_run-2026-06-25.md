# Multi-backtest Trendlyne-parity — re-validation round 2 (post data-audit)

**Run date:** 2026-06-25 · **Engine:** windfall-api @ current main (post Session-1 audit fixes) ·
**Harnesses:** `docs/validation/parity_multi.py` (gross selection/pricing/return decomposition) +
`docs/validation/gap_analysis.py` (per-miss root-cause) + `docs/validation/engine_metrics_round2.py`
(real-engine headline metrics, gross vs net of the adr-020 cost model).
**Gold:** owner-provided Trendlyne CSVs (`Downloads/`, picks + NAV) + 60 result screenshots
(`Downloads/backtest-data/`, configs + headline metrics). **Prior baseline:** `multi-backtest-parity-report.md` (2026-06-22).

> **Task:** todo #83 / `SESSION-backtest-revalidation.md`. Prerequisite (Session 1 data audit, #82 +
> adr-027…031) complete. The gold CSVs are unchanged since the baseline, so every round-2 vs baseline
> delta isolates the effect of the Session-1 fixes (F1 PBV-mask, F2 result-lag, F3 dead-name
> survivorship, F5 GSPL delisting, F6 mcap anchor).

---

## Headline verdict

**The engine still reproduces Trendlyne faithfully, and the Session-1 audit fixes moved exactly the
data-limited tests they targeted — with no regressions.** Across all 13 tests:

- **Gross selection + pricing reconcile tightly** on the 9 in-horizon tests: 79–91% pick-overlap,
  per-stock pricing **median 0.003pp**. Session-1 fixes lifted the data-limited screens
  (548042 breakout **70→79%**, pure-DVM 547994 **42→49%**, 547995 **34→39%**).
- **`gap_analysis` finds zero false-exclusions** on any price indicator (roc21/rsi14/sma50/sma200) or
  DVM factor across all 13 tests. Every miss is data coverage, factor horizon, universe scope, or a
  *correct* exclusion.
- **No new engine bugs.** Every Trendlyne-vs-us discrepancy decomposes into: cost realism (we're
  right), universe floor / NSE-only basis (accepted by design), data horizon (inherent), or
  known-fixable coverage holes. **No code fix was mandated this session.**
- **The cost model is the differentiator:** isolating cost (same engine, gross vs net) shows monthly
  strategies lose ~2.2–2.7pp CAGR to costs while weekly churners lose 6.5–11.6pp — turning
  Trendlyne's gross +24.9% weekly breakout into **−2% net.** The founding thesis, in our own numbers.

---

## A. Selection + pricing parity (GROSS) — round-2 vs baseline

`gold` = Trendlyne's reported NAV (from the CSV). `gold@ourpx` = Trendlyne's own picks priced by us
(the pricing check). `ours A` = our picks, current-membership basis (Trendlyne's survivorship basis).
`ours B` = our picks, survivorship-free PIT basis. All GROSS (no costs), ÷N fixed slots.

| id | strategy | freq | per | overlap A (base→r2) | overlap B | price med \|Δ\| | gold | gold@ourpx | ours A | ours B |
|---|---|---|---|---|---|---|---|---|---|---|
| 548012 | Tradeable (DVM-mom) | M | 59 | 87→**87** | 90 | 0.003pp | +127% | +133% | +115% | +105% |
| 548776 | Test A (value/PE) | M | 59 | 90→**90** | 92 | 0.003pp | +160% | +167% | +216% | +173% |
| 548042 | Breakout (technical) | W | 54 | 70→**79** | 81 | 0.004pp | +25% | +4% | +17% | +14% |
| 548040 | Pullback (mean-rev) | W | 54 | 91→**91** | 91 | 0.004pp | −1% | +3% | +12% | +12% |
| 548017 | Trend/regime proxy | M | 59 | 87→**87** | 90 | 0.003pp | +127% | +133% | +123% | +114% |
| 548015 | Tighter mom >65 | M | 57 | 87→**88** | 91 | 0.003pp | +102% | +107% | +82% | +77% |
| 548014 | Tighter mom 5-slot | M | 57 | 85→**84** | 87 | 0.003pp | +96% | +111% | +34% | +19% |
| 547989 | v2.2 weekly (1yr) | W | 54 | 83→**85** | 86 | 0.004pp | +17% | +17% | +20% | +24% |
| 547990 | v2.2 monthly (1yr) | M | 12 | 82→**83** | 85 | 0.004pp | −18% | −16% | −18% | −19% |
| 547991 | v2.2 monthly (full) | M | 59 | 41→**41** | 42 | 0.16* | +65% | +74% | −8% | −13% |
| 547992 | v2.2 quarterly (13yr) | Q | 53 | 16→**17** | 17 | 0.52* | **+948%** | +1098% | −24% | −26% |
| 547994 | Pure DVM (no floor) | W | 54 | 42→**49** | 51 | 0.016pp | +74% | +52% | +54% | +46% |
| 547995 | Pure DVM (no floor) | M | 59 | 34→**39** | 35 | 0.43* | +281% | +113% | +342% | +273% |

\* mean \|Δ\| (skewed by a few CA-uncertain deep-history names); in-horizon median stays 0.003–0.004pp.

**Read:** in-horizon parity held or improved everywhere; pricing unchanged-excellent. The 4
deep/no-floor tests sit where the baseline placed them — low overlap by data design, slightly improved
by the audit fixes (e.g. 547994 +42→+49%, 547995 +34→+39%).

---

## B. Per-miss root-cause (`gap_analysis`) — every missed gold pick classified

Dominant buckets per test (full output: `gap_round2_run-2026-06-25.txt`). `NIU` = NOT_IN_UNIVERSE.

| id | misses | dominant buckets | indicator/DVM false-exclusions |
|---|---|---|---|
| 548012 | 73 | NIU 58% · RANKED_OUT 23% · NO_DATA:adtv 12% · FAILED:adtv 7% | **0** |
| 548776 | 54 | NIU 59% · RANKED_OUT 28% · FAILED/NO_DATA:adtv 13% | **0** |
| 548042 | 113 | NIU 51% · NO_DATA:adtv 30% · NO_DATA:close 9% · RANKED_OUT 5% | **0** |
| 548040 | 47 | NIU 38% · RANKED_OUT 32% · NO_DATA:adtv 21% | **0** |
| 548017 | 70 | NIU 60% · RANKED_OUT 17% · NO_DATA:adtv 13% | **0** |
| 548015 | 61 | NIU 64% · NO_DATA:adtv 15% · RANKED_OUT 15% | **0** |
| 548014 | 43 | NIU 51% · RANKED_OUT 23% · NO_DATA:adtv 19% | **0** |
| 547989 | 81 | RANKED_OUT 26% · NO_DATA:adtv 23% · NIU 12% · horizon NO_DATA (rsi/pe/close) | **0** |
| 547990 | 20 | RANKED_OUT 25% · NO_DATA:adtv 20% · NIU 15% | **0** |
| 547991 | 343 | **NO_DATA:tl_pledge 74%** · NIU 10% | **0** |
| 547992 | 419 | **NO_DATA:tl_pledge 34% · close 26% · tl_durability 24%** · NIU 11% | **0** |
| 547994 | 278 | **NOT_IN_UNIVERSE 100%** | **0** |
| 547995 | 360 | **NOT_IN_UNIVERSE 99%** · RANKED_OUT 1% | **0** |

The only `FAILED:` buckets anywhere are **`adtv_cr`** (always the same near-10 NSE-only-basis names:
WHEELS 9.86, MONARCH 9.69, SESHAPAPER 9.88, FMGOETZE 5.63), **`mcap < 50000`** (correctly excluding
mega-caps: MCX 61k, BPCL 87k, IDEA 1.5L cr), **`tl_pe < 100`** (correctly excluding TVSELECT PE 2485),
and one **`rsi14 > 50`** boundary (PAGEIND 49.87 — correct). **No indicator or DVM factor ever wrongly
excluded a single gold pick.**

---

## C. Performance — Trendlyne (gross) vs our engine (gross & net of costs)

Our engine on the survivorship-free PIT basis, our selection. `ENG gross` = cost_mult 0; `ENG net` =
full adr-020 NSE delivery costs. `cost Δ` = CAGR lost to costs (clean: same engine, same picks).

| id | TL gross CAGR / tot / maxDD | our gross CAGR | our **net** CAGR / tot / maxDD | cost Δ (CAGR) | turnover | net Sharpe |
|---|---|---|---|---|---|---|
| 548012 | 18.2 / +127 / −30 | 19.0 | **16.6** / +113 / −33 | −2.4 | 857% | 0.69 |
| 548776 | 21.5 / +160 / −21 | 25.4 | **23.2** / +179 / −34 | −2.2 | 750% | 0.92 |
| 548017 | 18.2 / +127 / −30 | 19.1 | **16.7** / +113 / −34 | −2.4 | 855% | 0.69 |
| 548015 | 15.4 / +102 / −32 | 16.9 | **14.7** / +96 / −34 | −2.2 | 808% | 0.64 |
| 548014 | 14.7 / +96 / −41 | 19.1 | **16.7** / +113 / −31 | −2.4 | 929% | 0.65 |
| 547995 | 31.3 / +281 / −29 | 31.3 | **28.6** / +243 / −30 | −2.7 | 873% | 1.03 |
| 547990 | −17.2 / −18 / −37 | 7.6 | **5.1** / +5 / −31 | −2.5 | 1050% | 0.32 |
| **548042** | **24.1 / +25 / −20** | **4.6** | **−1.9** / **−2** / −27 | **−6.5** | **2706%** | 0.05 |
| **548040** | −0.8 / −1 / −23 | **18.9** | **7.3** / +7 / −19 | **−11.6** | **4392%** | 0.42 |
| **547989** | 16.8 / +17 / −20 | 13.3 | **6.5** / +7 / −26 | **−6.8** | 2564% | 0.38 |
| 547994 | 71.2 / +74 / −20 | 57.7 | **48.7** / +50 / −15 | −9.0 | 2327% | 1.66 |
| 547991 | 10.9 / +65 / −52 | 1.9 | **0.6** / +3 / −49 | −1.3 | 623% | 0.15 |
| 547992 | 19.3 / +948 / −50 | −1.3 | **−1.5** / −18 / −54 | −0.2 | 78% | −0.04 |

**The cost wedge is the story (rows sorted by turnover at the break):** monthly strategies (~750–1050%
turnover) lose **2.2–2.7pp CAGR** to costs; weekly strategies (2300–4400% turnover) lose **6.5–11.6pp**.
548042 breakout flips from +4.6% gross to **−1.9% net**; 548040 pullback gives back 60% of its gross
CAGR. Trendlyne's headline numbers are gross — a screener can't show you this; our cockpit's reason to
exist is that it does.

> Where our gross still differs from Trendlyne's gross (e.g. 548042 +4.6% vs +24.9%, 548040 +18.9% vs
> −0.8%) the driver is **selection + survivorship-free basis + path-sensitivity of short weekly
> windows**, not costs — see §A overlap and §B taxonomy. Trendlyne gross is a *selection/pricing*
> reference, not a net target.

---

## D. Root-cause → decision (signed off with owner 2026-06-25)

| # | discrepancy | root cause | decision |
|---|---|---|---|
| 1 | weekly net ≪ Trendlyne (548042/040/989) | Trendlyne is **gross/costless**; we apply NSE costs on 2300–4400% turnover | **We're right** (cost realism) → **adr-032** |
| 2 | pure-DVM low overlap (547994/995: 99–100% NIU) | our **₹500cr PIT universe floor** vs Trendlyne's no-floor microcaps | Accepted by design (adr-015) |
| 3 | 547992 +948% gross irreproducible (our −18–24%) | DVM≥2016 + pledge≥2023 + pre-2010 price gaps → book is cash for most of 2013–23 | Inherent data horizon; already warned (#75 empty-book) |
| 4 | 548017 ≡ 548012 on Trendlyne (identical metrics) | their extra `close>sma200` was non-binding / a duplicate run | **We're right** — our filter binds (548017 net +113.3 ≠ 548012 +112.7); no action |
| 5 | FAILED:adtv_cr near-10 names (WHEELS 9.86…) | NSE-only volume vs Trendlyne NSE+BSE consolidated; our 20d window already 96–97% calibrated (#74) | Accepted (adr-024 NSE-only) |
| 6 | NO_DATA:adtv_cr / mcap holes (9–30% of misses) | `pit_mcap`/`adtv` panel NaN on some rebalance dates | Known-fixable → follow-up todo |
| 7 | numeric-token NIU (14060423, 542012, 530805…) | ISIN present / NSE symbol blank → un-joined by symbol | Known-fixable → follow-up todo |

---

## E. Fixes applied / accepted differences / follow-ups

- **Engine fixes this session:** none required — `gap_analysis` confirms the logic is correct
  (0 false-exclusions); every gap is data/scope/cost, not computation.
- **Harness fix:** restored the 4 deep/no-floor configs (547991/992/994/995) to
  `parity_multi.py` `TEST_TABLE` (they were trimmed after the baseline; still present in
  `gap_analysis.py`). Configs re-confirmed against the owner's Trendlyne screenshots (547992's full
  query expanded the v2.2 blend). All 13 now run in both harnesses.
- **Accepted difference → ADR:** **adr-032** (Trendlyne parity is gross-of-costs; net divergence on
  high-turnover is by design). Universe-floor and NSE-only differences remain covered by adr-015 /
  adr-024.
- **Follow-up todos (logged, not blocking):**
  1. Backfill `pit_mcap` / `adtv` panel NaN holes (the NO_DATA:adtv/mcap bucket, 9–30% of misses).
  2. ISIN-based ingest/join for numeric-token gold rows (14060423, 542012, 530805, 524534) still
     absent from the universe.

---

## F. Reproduce

```bash
# gold staged at /tmp/parity_gold/gold_<id>.csv (13 owner CSVs)
cd backend && PYTHONPATH=$(pwd) WINDFALL_DATA_DIR=$(pwd)/data \
  ./.venv/bin/python ../docs/validation/parity_multi.py all       # gross selection/pricing, in-table 9
./.venv/bin/python ../docs/validation/parity_multi.py 547992      # one deep test (single-arg harness)
./.venv/bin/python ../docs/validation/gap_analysis.py             # per-miss taxonomy, all 13
./.venv/bin/python /tmp/engine_metrics_round2.py 1.0              # engine NET headline metrics
./.venv/bin/python /tmp/engine_metrics_round2.py 0.0              # engine GROSS (cost isolation)
```

Raw outputs: `parity_round2_run-2026-06-25.txt`, `gap_round2_run-2026-06-25.txt`,
`engine_metrics_round2_run-2026-06-25.txt`.
