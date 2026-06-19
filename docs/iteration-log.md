# Windfall Labs — Iteration Log

## Session 2026-06-19 — review remediation + data-sourcing phase

**Stage:** Stage 4 (iterate) — five iterations + three data-source spikes
**What changed (all verifier-APPROVED, integrated, mirrored):**
- **iter-21 (P0):** dropped DUMMYALCAR.NS; suppressed `active_return` on 0-trade/~0-exposure runs (the "+8.71% on 0 trades" trap); added `backend/scripts/data_audit.py`; cockpit snapshot-staleness banner + monthly host cron.
- **iter-22 (engine fidelity):** quarterly rebalance; multi-factor percentile-blend ranker (`rank_blend`, blank-tolerant); max-weight-per-stock cap; per-strategy data-readiness verdict. Covers every Trendlyne backtest control + more.
- **iter-23 (own DVM):** `windfall/scores/own_dvm.py` reproducible Durability/Valuation/Momentum + validation harness vs Trendlyne snapshot (Spearman: Momentum 0.835, Durability 0.546, Valuation 0.211).
- **iter-24 (Bhavcopy):** `backend/scripts/bhavcopy_ingest.py` — NSE Bhavcopy → standalone `data/bhavcopy.duckdb` (survivorship-free, ISIN-keyed, UDiFF+legacy, ONE-DOOR-safe).
- **iter-25 (surveillance):** `windfall/data/surveillance.py` — NSE ASM/GSM flags, in-process ingest, annotates live signals + warns (5/10 dvm_monthly picks flagged ASM on first run). Daily 9am cron.

**Data-source spikes:** Bhavcopy ✅ (built), ASM/GSM ✅ (built), EODHD ❌ (free key = no India/no fundamentals; paid+quality-doubtful), screener.in ✅ (12yr annual financials, free, parseable; our ratios verified — RELIANCE ROE 9.6%, D/E 0.44).

**Decisions:** ADR-008..012 (curated). Build our own reproducible DVM; survivorship via Bhavcopy in a standalone store; ASM/GSM as a pre-deploy guardrail; historical fundamentals via screener.in.

**Tests:** 34 → 60 passing.

**Left running:** Bhavcopy full backfill (2010→2026) detached on the server (`/tmp/bhavcopy_backfill.log`); resumable.

**Next session pick-up:**
1. After Bhavcopy backfill completes: corporate-action adjustment → point-in-time index membership → **wire survivorship data into the engine** (the big trust unlock).
2. Build `screener_fundamentals.py` (per-company fetch+parse → point-in-time financials → compute own Durability/Valuation history → validate vs Trendlyne snapshot on the ~1,138 overlap stocks). Lag annual ~3mo post-fiscal-year (no look-ahead). lxml already in venv.
3. Then user's sequence: detailed data verification → replicate 1-2 Trendlyne backtests in-engine & compare.

**Known pre-existing:** anti-gaslight "unclaimed-done" on cockpit-dashboard (+1) — original Stage-3 features marked done before ledger writes existed; not from this session.

## Session 2026-06-19 (cont.) — iter-26: screener.in historical fundamentals

**Stage:** Stage 4 (iterate) — historical-fundamentals sourcing, validation & ingestion
**What changed (ADR-013, verifier-APPROVED report #202, feature-claim #70 reconciled):**
- **Validated screener.in** as the historical-fundamentals source via a three-way triangulation (screener × yfinance × Trendlyne) over 21 stocks: raw lines 97–99% vs Trendlyne gold, computed ROE 97%, ~6 bounded failure classes that **converged** (+9 diverse stocks added zero new classes). Decision: **GO**.
- **Built `backend/windfall/data/screener_fundamentals.py`** — standalone `data/screener_fundamentals.duckdb`, six handling rules: (1) symbol→slug direct-first with screener search-API fallback + NSE-symbol verify; (2) financials excluded (sector + schema); (3) Net Profit → owner-attributable via yfinance overlap; (4) split-adjusted per-share; (5) period-end-date keying; (6) ratios computed from raw lines. Self-check (Layer-1 identity + soft yfinance cross-vote) → high/low/quarantined/excluded.
- **Ran the full nifty500: 402 tickers, 4,159 rows, 2005–2026** (368 high · 32 low/review · 2 quarantined; 92 financials excluded; 1 failed). Batch-1 deep verify vs yfinance = 40/40 clean (assets 100%, rev 99%, cfo 98%); across all 402, assets agreed ~99.5%.
- **Key finding:** yfinance is **unreliable for Indian revenue** (INFY ≈ ₹1,928 Cr vs screener's correct ₹162,990 Cr, ~85× off) — so the yfinance cross-vote was demoted to a **soft review flag**; screener is the more reliable source. Hard quarantine now only from the NSE-symbol mapping guard + Layer-1 identity.

**Decisions:** ADR-013 (screener.in historical fundamentals, triangulation-validated, cat:reliability). Financials excluded from the fundamental-DVM (user decision).

**Open bugs/items:** VAML ZeroDivisionError (1 stock); IDEA (Vodafone Idea) screener slug unresolved (search resolves to IdeaForge → MAP-MISMATCH-quarantined); ABB short consolidated history (4p).

**Next session pick-up:**
1. Fix the 3 open items (VAML divide-by-zero, IDEA slug, ABB short history).
2. Run the wider **trendlyne universe (1,138)** — needs a ONE-DOOR-safe symbol export (not via opening windfall.duckdb).
3. **Wire `fundamentals_history` into the engine** (point-in-time, ~3mo fiscal lag) → own Durability/Valuation over history.
4. Then the user's sequence: detailed data verification → replicate 1–2 Trendlyne backtests in-engine & compare.

**Commits:** 318a18c (ingester + ADR-013), f0174da (direct-first + 3 batch fixes), a9f9693 (soft yfinance cross-vote).

## Session 2026-06-19 (cont.) — iters 6/7/8/C: bug fixes, wider scrape, D/V/M history

**Stage:** Stage 4 (iterate) — 4 verifier-APPROVED iterations + the wider-universe scrape
**What changed:**
- **iter-6 (#20, merge 26ca933, APPROVE 3/3):** fixed 3 screener-ingester bug classes — ROCE crash on zero/negative capital employed (VAML); poisoned slug_map IDEA->IDEAFORGE + 7 corrupt rows (direct-symbol-first resolution + cleanup); sparse consolidated kept over richer standalone (ABB) + DELETE-all-bases on re-ingest. `tests/test_screener_fundamentals.py`.
- **#21a wider scrape:** ran niftytotalmarket (754) WITH cross-check -> 552 high / 80 low / 1 quarantined / 121 financials excluded / **0 failed** (the iter-6 fixes held). Store 403 -> **633 tickers, 6,648 rows, 2006-2026**.
- **iter-7 (#19 + #16, merge 16dd4a2, APPROVE 3/3):** signals/export CSV now carries the ASM/GSM flag; new `/api/backtests/cost-sensitivity` (0x/1x/2x) + `/api/backtests/compare` (A/B). `tests/test_insight_endpoints.py`. (#16 cockpit UI views deferred.)
- **iter-8 (#21b, merge bcb9b69, APPROVE 2/2, NO look-ahead):** wired screener `fundamentals_history` into the engine for Durability — `fund.screener_history_panel` (read-only cross-DB, conf in {high,low}, roe/opm/roa/np_qtr_yoy, **keyed on period_end+120d**); `resolve.feat()` `snapshot.combine_first(history)`; readiness honesty (durability no longer live-only). `tests/test_durability_history.py`.
- **iter-C (#23, merge 83d02e2, APPROVE, NO look-ahead):** wired historical PE/PB into `valuation_own` — PE = close/eps_lagged, PB = PE*ROE/100 (guards); `pe_to_sector` stays snapshot-only. `tests/test_valuation_history.py`.

**Result: the D/V/M-history trio is COMPLETE** — Momentum (price), Durability (iter-8), Valuation (iter-C) all backtest over real history (2006-2026, 633 names) with verifier-confirmed no-look-ahead. Tests 60 -> 83.

**Decisions:** no new ADRs (bug fixes + additive features + documented modeling choices: 120d publication lag; PB = PE*ROE identity).

**To-dos:** #20/#21/#22/#23 done; #16 retitled (backend done, UI remains). Open: #16(UI)/#14/#13/#17/#12/#18.

**Next session pick-up:**
1. **Run a Trendlyne-parity DVM backtest end-to-end** (now possible — all 3 factors history-backed) + detailed data verification, then replicate 1-2 Trendlyne results in-engine & compare. (User's stated phase goal — now unblocked.)
2. #16 cockpit UI views (cost-sensitivity + A/B panels -> the new endpoints).
3. Ops: #14 nightly auto-refresh cron, #13 monthly snapshot auto-save.

**Commits:** d92d53f/26ca933 (iter-6), 27dc074/16dd4a2 (iter-7), b97ed6a/bcb9b69 (iter-8), 826d3f5/83d02e2 (iter-C).

## Session 2026-06-20 — data audit + valuation DVM v1 + 674-name screener scrape

**Stage:** Stage 4 (iterate) — data-quality audit (user-requested), one verifier-APPROVED code iteration, one data-source scrape.

**Data audit (read-only, requested: "how much screener data, is it correct, are the DVM right?"):**
- **Screener coverage reconciled.** The run targeted **niftytotalmarket (754)** — complete: 633 ingested (552 high / 80 low / 1 quarantined), 121 financials excluded by ADR-013, **0 failed**. The "1138 vs 633" is apples-to-oranges: Trendlyne(1138) ∩ niftytotalmarket = only **287**; **Trendlyne ∩ screener = 238** (the usable set for fundamental backtests). The 900 Trendlyne names without screener history = 89 financial + 137 fund/ETF/other + **674 genuine companies** (668 outside the run target, 6 inside). Exact list dumped to `backend/data/missing_screener.csv`.
- **Data correctness.** Fresh yfinance cross-check on 8 large-caps: revenue agrees <2% on all clean names (RELIANCE 0.1%, TCS 0.0%, HINDUNILVR 1.1%, MARUTI 1.6%, SUNPHARMA 0.4%); TITAN 14% correctly flagged `low`; NESTLE filled where yfinance has no data. Caveat: net-profit agreement is partly circular (ingester adopts yfinance owner-NP on overlap) — revenue is the independent signal. Confidence tiering is the systematic guard.

**iter (valuation-dvm-v1, commit 28dc401, verifier-APPROVED, no look-ahead):** Trendlyne valuation is growth-adjusted + benchmarked vs a stock's own 5–10yr multiple history (per Trendlyne's own methodology, user-supplied). v1: added **PEG** (P/E ÷ EPS-growth%, the strongest single predictor ρ≈0.67) as the leading valuation component; **fixed a latent blend bug** (PB / PE-to-sector were negated without a >0 guard, so negative ratios scored as "cheapest"); reweighted peg .40 / pe_to_sector .25 / pe .20 / pb .15; wired PEG into the live engine with snapshot-only gating. **Valuation Spearman 0.211 → 0.407** (durability 0.546 / momentum 0.835 unchanged). +2 regression tests; 83 → 85 pass. Deliberately did NOT crank weights to chase the snapshot number (curve-fit risk) — the remaining gap is the historical-multiple-percentile component (v2).

**In flight:** detached screener scrape of the **674 genuine-company gap** (`data/genuine_674.csv`, cross-check on) → lifts the live-DVM ∩ history overlap from 238 toward ~900, unlocking valuation v2 + fundamental backtests on a wide universe.

**Next session pick-up:**
1. **Valuation v2:** historical-multiple percentile (current PE/PB vs the stock's own screener history) — Trendlyne's core valuation ingredient; now feasible across the wider overlap from the 674 scrape.
2. **Durability gap:** Trendlyne durability uses **ROCE + D/E**; ours uses ROA/Piotroski/OPM. Add ROCE + D/E (screener history already computes both) to lift durability ρ above 0.55.
3. Run a Trendlyne-parity DVM backtest end-to-end + replicate 1–2 Trendlyne results in-engine & compare (user's stated phase goal).

### 2026-06-20 (cont.) — scrape complete, data validated, durability v2

- **674-gap scrape complete:** 660 ingested / 9 quarantined / 3 financial / 2 failed. Screener store **633 → 1,305** names. **Trendlyne ∩ screener = 238 → 898** (~98% of eligible operating companies; remaining 240 = 130 ETFs/funds + 89 financials + 21 edge-cases). The fundamental-backtest universe is now effectively complete.
- **Universe clarified:** NSE ~2,375 listed (EQUITY_L); we hold prices for 1,505 (liquid set). BSE out of scope (illiquid, NSE-keyed sources).
- **Data correctness (independent):** screener-COMPUTED ROE vs Trendlyne-REPORTED ROE on the 898 overlap = **Spearman 0.90, 94% within ±5pp** (OPM 0.87, wider by the annual-vs-quarterly definition). The wild ROE outliers are unstable ratios (near-zero equity), not parse errors. Conclusion: **screener data is sound; remaining DVM gaps are formula, not data.** (Note: the earlier net-profit-vs-yfinance "match" is non-independent — the ingester adopts yfinance owner-NP on overlap; revenue is the independent yfinance check and agrees <2% on clean large-caps.)
- **iter durability-dvm-v2 (commit 65d75aa, verifier-APPROVED):** a held-out least-squares fit showed Trendlyne durability is **Piotroski-DOMINATED** (Piotroski ~3× any other input; ceiling ~0.88). Reweighted `durability_own` to {piotroski .45, pledge .18, eps_growth .15, roa .12, opm .05, np_qtr_yoy .05}; ROE dropped from blend (collinear) but kept as a param. **Durability 0.546 → 0.875** (valuation/momentum unchanged). Measured finding: **ROCE/D-E HURT the snapshot match** (cross-source noise vs Trendlyne's own-data target) — kept out of the live blend; ROCE-for-history is an opt-in ~0.03-match-cost follow-up (user chose "max live-match").
- **DVM scoreboard now:** momentum **0.835** · durability **0.875** · valuation **0.407**.

**Pick-up:** valuation v2 (historical-multiple percentile — same measure-first lstsq-ceiling method); momentum tweak (add distance-from-200DMA / 52w-high); then the Trendlyne-parity backtest.
