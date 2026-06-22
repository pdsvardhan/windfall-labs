# Multi-backtest Trendlyne-parity report — cross-style engine veracity

**Run date:** 2026-06-22 · **Engine:** windfall-api @ current main · **Harness:** `_spike/parity_multi.py`
(parametrised; supersedes the hardcoded `parity.py`/`deep_testA.py`). Source plan:
`docs/validation/multi-backtest-parity-plan.md`.

## Fixes applied 2026-06-23 (post-report)

| item | what shipped | evidence |
|---|---|---|
| **#68** warmup | `run_backtest` warms long indicators before the requested start (mirrors signals_live) | sma200 short-window: empty 9mo → trades from start; pad-0 byte-identical; 19 engine tests pass. Deployed (`db94e18`). |
| **#75** empty-book | backtest warns when a rebalance has zero eligible names (factor-horizon cash) | v2.2-quarterly-2013 warns "41/53 rebalances had NO eligible names". Deployed (`2c3a6bf`). |
| **#76** membership | re-ran `rebuild_pit_mcap_ca.py` — `pit_mcap` was stale at 2026-05-13 for ~50 non-delisted names (prices fresh to 06-12) | STLTECH (₹20k cr, missed 16×) + DEEDEV back in `pit_universe`; 548042 misses 162→128, NOT_IN_UNIVERSE 121→73 |
| **#72** mcap holes | same rebuild filled the `pit_mcap` date holes | 548042 `NO_DATA:mcap` 32→3; 548040 10→1 |

**#74** `adtv_cr` — **resolved, no change needed.** The screen filter is `AvgTradedValueCr > 10` (value in
₹cr — matches our `adtv_cr` type). Calibrated our window against 705 v2.2 gold picks (all passed >10):
our 20-day gives 96% agreement, peak 97% at 15d, and longer windows are *worse* (30d 92%, 126d 78%) —
so Trendlyne's window is short (~2–4 weeks) and ours already matches. The residual ~4% is the NSE-only-
vs-Consolidated(NSE+BSE) bias, accepted (user: NSE-only universe, no BSE feed). Verified, not assumed.

**Still open** (needs external input): **#73** un-ingested recent IPOs (`OLAELEC`=0 rows) + numeric-token
gold rows — needs an in-browser Trendlyne harvest.
Backup before the rebuild: `backend/data/trendlyne.duckdb.bak-20260623-parity`.

**What this is:** all 9 replicable Trendlyne backtests run through our engine at Trendlyne's exact
rebalance dates, decomposed into PRICING (do our adjusted prices reproduce Trendlyne's returns?) and
SELECTION (does our filter+rank pick the same names?). Phase A freezes the universe to current
membership (matches Trendlyne's survivorship basis); Phase B re-runs survivorship-free (PIT).

---

## Headline verdict

**The engine reproduces Trendlyne across every style tested — DVM, value, pure-technical,
mean-reversion, and the full 10-filter v2.2 compound screen — WHEN the strategy's required data exists
over the window.** On the 9 in-horizon tests, after fixing one harness bug (warmup, below), selection
overlap is **70–91%** and per-stock pricing reconciles to a **median 0.003pp** (96–100% of
stock-periods within 0.5pp). The 4 out-of-horizon / no-floor tests (547991/992/994/995) drop to
16–42% overlap — but for documented data-availability reasons (factor horizon, microcap coverage), not
engine logic. Net: **two confirmed engine-transparency findings (both "silent empty book" family),
three unverified leads still owed, and a set of now-quantified inherent data limits.**

### The one material finding this session: warmup, not the engine

The harness warmed rolling features only **120 calendar days** before each gold window. `sma200` needs
**200 trading days** (~280 calendar). On every screen filtering `close > sma200`, the engine was
**starved of eligible names in the early periods** (literally zero picks for the first ~3 rebalances),
which collapsed measured overlap. The DVM screens were unaffected (their `tl_*` factors are
point-in-time, not rolling), which is exactly why only the technical/v2.2 screens looked broken.

Fixing the warmup to 420 calendar days:

| screen | overlap before | overlap after |
|---|---|---|
| 548042 breakout (sma50+sma200) | 39% | **70%** |
| 548040 pullback (sma200) | 50% | **91%** |
| 547990 v2.2 monthly (sma50+sma200) | 42% | **82%** |
| 547989 v2.2 weekly (sma50+sma200) | 46% | **83%** |

> 🔴 **CONFIRMED production bug (not just the harness):** the same starvation exists in `run_backtest`.
> - `signals_live/generate.py:46` **pads correctly** — `warmup_start = today − 820d`, then
>   `cfg.model_copy(update={"start": min(cfg.start, warmup_start)})` before `resolve()`. Live signals are fine.
> - `engine/backtest.py:105` **does NOT pad** — it calls `resolve(cfg)` with the user's raw `cfg.start`,
>   then `entry_mask.fillna(False)` makes every unwarmed `sma200` row ineligible.
>
> **Impact:** a user backtesting any long-MA strategy (`close > sma200`, `roc125`, regime overlay) over a
> recent window gets a **silently empty/thin book for the first ~200 trading days (~9 months)** — early
> exposure and returns understated, and a long-MA strategy can look artificially defensive (parked in
> cash) at the start. This is a correctness bug that distorts every short-window backtest with a long
> indicator. Filed as a Stage-4 engine iteration (todo added) — fix mirrors the signals path: pad
> `cfg.start` by the longest indicator window (≥250 trading days) before `resolve()`, then trim the
> result back to the user's requested `start` for reporting.

### Second finding: silent empty book on missing-factor horizon (same family)

The 4 out-of-horizon tests exposed a sibling of the warmup bug. When a **filter** references a
point-in-time factor that has **no data in a period** (`tl_pledge` before 2023, `tl_durability/
valuation/momentum` before our 2016 DVM history), `resolve()` produces NaN → `entry_mask.fillna(False)`
→ **every name excluded → empty book → silent cash**, with no warning. On 547992 this empties the book
for ~10 of 13 years; the user just sees a flat/cash early curve and a −32% result against a +948% gold,
with nothing telling them *why*.

> 🟠 **Engine transparency follow-up (todo filed):** when a filter's referenced factor is entirely
> absent for a rebalance period — or when the book is empty/near-empty for N consecutive early periods —
> the backtest should emit a WARNING (e.g. "`tl_pledge` has no data before 2023-01; book is cash for 7
> periods"). This is correctness-adjacent: the *behavior* (can't assert a filter without its data) is
> defensible, but the *silence* reproduces the gaslighting pattern this whole system exists to remove.
> Distinct from I-warmup (rolling-feature NaN) but the same fix surface — both are "silent starvation."

---

## Per-test results (final: 420d warmup + ca_uncertain parked as cash)

Returns are total return over the window; `gold@ourpx` = Trendlyne's own picks priced by us
(the pricing check); `ours` = our picks priced by us (adds the selection effect).

| id | strategy | style / freq | per | overlap A / B | price median \|Δ\| | gold | gold@ourpx | ours (A) | ours (B) |
|---|---|---|---|---|---|---|---|---|---|
| 548012 | Tradeable | DVM+mom / M | 59 | 87% / 90% | 0.003pp | +127% | +112% | +110% | +118% |
| 548776 | Test A | DVM+value(PE) / M | 59 | 90% / 92% | 0.003pp | +160% | +180% | +220% | +212% |
| 548017 | Trend/regime | DVM+sma200 / M | 59 | 87% / 90% | 0.003pp | +127% | +112% | +133% | +124% |
| 548015 | Tighter mom>65 | DVM+mom / M | 57 | 87% / 90% | 0.003pp | +102% | +88% | +84% | +80% |
| 548014 | Tighter mom 20% | DVM+mom, 5 slots / M | 57 | 85% / 88% | 0.003pp | +96% | +110% | +19% | +26% |
| 548042 | Breakout | pure technical / W | 54 | 70% / 79% | 0.003pp | +25% | +4% | −2% | +14% |
| 548040 | Pullback | technical mean-rev / W | 54 | 91% / 92% | 0.002pp | −1% | +3% | +12% | +11% |
| 547990 | v2.2 monthly | 10-filter compound / M | 12 | 82% / 85% | 0.002pp | −18% | −15% | −22% | −19% |
| 547989 | v2.2 weekly | 10-filter compound / W | 54 | 83% / 86% | 0.003pp | +17% | +20% | +8% | +15% |

### Out-of-horizon / no-floor tests (run for completeness, low overlap by data design)

| id | strategy | window | overlap A | unpriceable | gold | ours (A) | why low |
|---|---|---|---|---|---|---|---|
| 547991 | v2.2 monthly | 2021–26 | 41% | 21 | +65% | −15% | `tl_pledge<20` NaN pre-2023 → empty book ~2021-23 |
| 547992 | v2.2 quarterly | **2013–26** | 16% | 11 | **+948%** | −32% | DVM NaN pre-2016 + pledge pre-2023 → empty book ~2013-23; **the +948% origin run is NOT reproducible by our engine** |
| 547994 | DVM clone weekly | 2025–26 | 42% | 72 | +74% | +31% | no mcap floor → 72 sub-₹500cr names we don't carry |
| 547995 | DVM clone monthly | 2021–26 | 34% | **217** | +281% | +254% | no floor → 217 unpriceable microcaps; the large-caps we DO carry track gold (NAV close) but names differ |

**Methodology check (passed on every test):** `gold @ Trendlyne-prices` (compounded `Avg Change %`
row) equals Trendlyne's reported NAV exactly — confirming Trendlyne's NAV is a fixed-slot
(÷N-holdings, empty slots = cash), equal-weight, compounded-rebalanced book, which is what our engine
models (`invest_fully=False`).

---

## Selection gap — VERIFIED root cause (per-miss classifier, `gap_analysis.py`)

> **Correction of an earlier draft.** A first pass bucketed selection misses into assumed categories
> ("survivors-only / microcap / boundary") *without verifying each name*. That was inference dressed as
> finding. `gap_analysis.py` now classifies every (period, missed gold-pick) from our own data, using
> `entry_mask` as the truth for eligibility and recomputing each filter feature only to EXPLAIN a
> rejection. Results below replace the assumptions — and they change the conclusion.

For every name Trendlyne picked that we did not, across all 13 tests:

| cause | share of misses | fixable | what it is |
|---|---|---|---|
| **NOT_IN_UNIVERSE** | 37–75% | partly | name absent from our resolved tickers — decomposes 3 ways (below) |
| **NO_DATA: mcap / adtv** | 4–29% | **yes** | we carry the prices, but `mcap`/`adtv` panel is NaN that date → filter drops it |
| **RANKED_OUT** | 0–25% | no | eligible, ranked just outside top-N — irreducible boundary churn |
| **FAILED: adtv_cr** | 1–10% | **yes** | our liquidity calc reads low vs Trendlyne at the threshold |
| **FAILED: indicators** | **0%** | — | `roc21`/`rsi14`/`sma50/200`/`tl_durability/valuation/momentum` **never wrongly excluded a single pick** |

**Headline: the price-derived indicators and DVM factors are verified correct — zero false-exclusions
across 13 tests.** Any earlier suspicion about `roc21`/`rsi14` definitions (548042's 70%) is disproven:
548042's misses are 75% NOT_IN_UNIVERSE + 20% NO_DATA:mcap, **0% indicator failures**.

### NOT_IN_UNIVERSE decomposes into three very different things

1. **Membership-snapshot staleness — FIXABLE, the biggest lever, probable production bug.**
   `pit_universe(latest)` requires a name to be present on the *exact* max membership date (2026-06-22).
   **57 names that last updated mid-May — including STLTECH (₹20,440 cr large-cap, missed 16× in 548042)
   and DEEDEV (₹3,299 cr) — are silently dropped from the "current" universe.** They are NOT delisted;
   the membership feed just didn't refresh them. If live signals use the same `pit_universe(latest)`,
   those 57 current names are missing from the tradeable universe in production too. → **todo PARITY-1.**
2. **Genuinely un-ingested names — FIXABLE coverage.** OLAELEC = **0 rows** (Ola Electric, IPO Aug-2024,
   never ingested); other 2024-25 listings (KRN, ALPEXSOLAR); and numeric-token gold rows
   (`14060423`/`17160453`/`542012` — ISIN present, NSE symbol blank → un-joinable by symbol). →
   **todos PARITY-4 (ingest IPOs + ISIN-join).**
3. **True survivors — INHERENT.** IDFC, UJJIVAN, JSLHISAR, TATASTLBSL, GSPL, GVKPIL — merged/delisted,
   genuinely un-pickable from current membership. The only inherent bucket.

### The other verified, fixable levers
- **NO_DATA: mcap / adtv (4–29%)** — names we price but whose `pit_mcap`/`adtv` panel is NaN that date,
  so `mcap>X` / `adtv>X` drops them. Backfill `pit_mcap`. → **todo PARITY-2.**
- **FAILED: adtv_cr (1–10%)** — the *only* recurring threshold failure, always just under 10 and on the
  same names (WHEELS 9.86, MONARCH 9.69, SESHAPAPER 9.88) with one real outlier (FMGOETZE **5.63**, a
  44% gap — not rounding). Our `adtv_cr` = 20-day rolling mean traded-value / 1e7; align window/method
  to Trendlyne's ADTV. → **todo PARITY-3.**

### Still genuinely inherent / irreducible
- **Survivors** (above) and **RANKED_OUT** boundary churn (worse at weekly: 547989 90 swaps vs 547990
  21, and at `nhold=5`/548014 where each swap is 20% of the book).
- **`ca_uncertain` CA mismatch** (GVKPIL; new candidates over deep history: BSOFT 2016, VERTOZ 2023,
  DHANI 2018, TATAMETALI 2016) — parked as cash, bounded.
- **v2.2 13-year quarterly (+948%) is not reproducible by our engine** — needs DVM≥2016 + pledge≥2023;
  pre-data periods are cash (todo for the *silent* version of this: I-horizon).

---

## Conclusion

**Within its data horizon the engine reproduces Trendlyne faithfully, and its computation is sound — the
indicators, DVM factors, ranking, and pricing all check out (0% indicator false-exclusions; 0.003pp
median pricing).** The gap to Trendlyne is almost entirely **data coverage / freshness**, and most of it
is fixable:

| lever | impact | todo |
|---|---|---|
| Universe membership staleness (57 current names incl. STLTECH) | **high** | PARITY-1 |
| `pit_mcap`/`adtv` NaN holes (4–29% of misses) | med | PARITY-2 |
| `adtv_cr` calc alignment | med | PARITY-3 |
| Ingest recent IPOs + ISIN-join numeric tokens | med | PARITY-4 |
| `run_backtest` long-indicator warmup | **bug** | #68 |
| Silent empty-book on missing-factor horizon | transparency | I-horizon |

Inherent and not closable: true survivors (merged/delisted), `ca_uncertain` CA names, and the
pre-DVM/pre-pledge history of deep-backtest strategies. **Indicator/ranking logic needs no change.**

---

## Reproduce

```bash
# stage 13 gold CSVs -> /tmp/parity_gold/gold_<id>.csv ; harnesses -> container
docker exec -e PYTHONPATH=/app windfall-api python /tmp/parity_multi.py all      # 5-section recon, all 13
docker exec -e PYTHONPATH=/app windfall-api python /tmp/gap_analysis.py          # per-miss root-cause, all 13
docker exec -e PYTHONPATH=/app windfall-api python /tmp/gap_analysis.py 548042   # one test
```
Per-test config lives in `TEST_TABLE` (shared by both harnesses). `parity_multi.py` = pricing/return
decomposition; `gap_analysis.py` = verified per-miss selection root cause. Raw outputs:
`parity_all_run-2026-06-22.txt`, `gap_all.txt`.
