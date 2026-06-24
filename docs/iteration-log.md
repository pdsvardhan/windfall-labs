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
- **iter momentum (no change — confirmed optimal):** measure-first (single-input, lstsq ceiling, 5 reweights, train/test) showed the current 5-input blend (0.835) beats every variant; dist-from-200DMA is the best single signal (0.868) but has only ~220-name coverage (strict 200-day window) and is redundant. No reweight beat 0.835 on held-out data → left unchanged (changing it = curve-fit). To-do #27 (done, logged).
- **iter valuation-dvm-v1.1 (commit cd4a503, verifier-APPROVED):** held-out fit gave `pe_to_sector` a NEGATIVE weight; dropped it, reweighted {peg .45, pe .30, pb .25}. **Valuation 0.407 → 0.445** — the **data ceiling** (~0.44). The historical-multiple percentile (Trendlyne's documented 5-10yr method) was reconstructed (price × screener EPS) and TESTED: single-input rho only ~0.12, makes the blend worse — it's a time-series signal orthogonal to cross-sectional cheapness. Lifting valuation further needs NEW data: forward-PE (export column EMPTY), EV/EBITDA, dividend yield → to-do #26.
- **DVM scoreboard now (deployed):** momentum **0.835** · durability **0.875** · valuation **0.445**. Durability & momentum at data ceilings; valuation data-capped ~0.44.

**Pick-up:** (#26) re-export Trendlyne with forward-PE/div-yield/EV-EBITDA to lift valuation; then the Trendlyne-parity DVM backtest end-to-end (all 3 factors now history-backed). Method to reuse: measure-first lstsq-ceiling + train/test before any reweight.

## Session 2026-06-20 (cont.) — iter-28 + iter-29 + iter-16 (survivorship-free engine → live cockpit)

**Stage:** Stage 4 — two verifier-APPROVED data/engine iterations (merged) + a full UI rebuild (on branch).

- **iter-28 (ADR-017, merge e10605c, verifier APPROVE 3/3):** derived a corporate-action (split/bonus) master from canonical price gaps CONFIRMED by share-count steps (precision 0.95 vs Trendlyne adjusted/raw GT) — Bhavcopy `prev_close` is NOT CA-adjusted, so price-gap+share-step is the method, no NSE feed. Tables `ca_events`/`ca_factor`/`delistings`. Fixed a real ~10× pit_mcap bug (not the "transient" ADR-015 assumed — Trendlyne reflects splits in EPS on a different date than the price ex-date) via `mcap = adjusted_close × current_shares`; now ~90% within 15% of Trendlyne mcap. `trendlyne_store.py` read primitives; `test_ca_factor.py` (16).
- **iter-29 (ADR-018 — amends ADR-017, merge 1805ebf, verifier APPROVE 3/3, NO look-ahead):** `data_source="trendlyne"` wires the survivorship-free layer into resolve()+backtest — adjusted OHLCV (live+delisted), time-varying PIT ₹500cr membership mask, Trendlyne daily DVM/valuation features + result-lag raw fundamentals (no look-ahead), real Nifty-500 benchmark, delisting terminal-exit. **ca_uncertain blow-ups/mergers now INCLUDED** (excluding them was optimistic survivorship bias), surfaced as a warning. Tests 102→111. Deployed live.
- **iter-16 (commit 34d3134, branch `iter-16-ui-pastel`, deployed, PENDING user visual sign-off + merge):** full from-scratch Next.js cockpit rebuild in the "Pastel Pop" design system, wired to live API. Pages: Home (redesigned command center), Strategies library (recipe+result cards), guided Strategy builder (manual filter chips + live JSON + readiness verdict + auto survivorship status + Explore-variations sweep), Strategy result (metrics/cost-sensitivity/equity/drawdown/trades), Live signals, Reference. Strategy = recipe + one result; survivorship-free default with auto survivors-only on Trendlyne-DVM factors. Paper/walk-forward deferred; A/B dropped. Tracker: `docs/UI-REBUILD.md`.

**Data reality (survivorship):** ~175 delisted names (Bhavcopy, 166 ever >₹500cr) carry the whole survivorship correction — adjusted prices + screener fundamentals, but NO Trendlyne DVM (0/175); all 1,924 Trendlyne names are current survivors.

**To-dos:** #28, #29 done. #16 pending (branch deployed, awaiting visual sign-off → verifier → merge).

**Next session pick-up:**
1. User verifies live cockpit (http://192.168.1.10:8500) → run verifier, merge iter-16 → master, mark #16 done.
2. #30 — reproduce a known Trendlyne backtest on the survivorship-free layer (success criterion #1).
3. #31 — swing strategy suite on the survivorship-free engine.

## Session 2026-06-23 — multi-backtest parity validation + engine/data fixes + CI green

**Stage:** Stage 4 — cross-style Trendlyne-parity validation, then 5 engine/data fixes + 3 CI/test fixes.

**Parity validation (to-do #66, done):** ran all 13 downloaded Trendlyne backtests through a new
parametrised harness (`docs/validation/parity_multi.py`) + a per-miss root-cause classifier
(`gap_analysis.py`). Report: `docs/validation/multi-backtest-parity-report.md`. Result: engine
reproduces Trendlyne across DVM / value / technical / mean-reversion / v2.2 — **70–91% selection
overlap, median 0.003pp pricing, 0% indicator false-exclusions** (the indicators + DVM factors are
verified correct). The gap to Trendlyne is data coverage/freshness, not logic. **Process note:** a first
pass bucketed misses into assumed categories; user pushed back; the classifier overturned the
"roc21/rsi14 definition mismatch" hypothesis (it was wrong) and surfaced the membership-staleness bug.

**Fixes shipped + deployed (master):**
- **#68 warmup** (`engine/backtest.py`, db94e18): pad cfg.start by the longest rolling window before
  resolve, trade from the requested start. Was: sma200 strategies had a silently empty ~9-month early
  book. Verified (28→124 trades on a short sma200 window; pad-0 byte-identical; 19 engine tests).
- **#75 empty-book warning** (2c3a6bf): backtest warns "N/M rebalances had NO eligible names" when a
  filter's factor has no data in-window (e.g. v2.2-quarterly-2013 is cash ~10/13yr).
- **#76 + #72** (pit_mcap rebuild): `pit_mcap` was stale at 2026-05-13 for ~50 non-delisted names
  (prices fresh to 06-12). Re-ran `rebuild_pit_mcap_ca.py` (API stopped, DB backed up). STLTECH
  (₹20k cr, missed 16×) + DEEDEV recovered; 548042 misses 162→128, NOT_IN_UNIVERSE 121→73,
  NO_DATA:mcap 32→3.
- **#74 adtv_cr** (resolved, no change): screen filter = `AvgTradedValueCr > 10` (value ₹cr = our
  adtv_cr). Calibrated our window vs 705 v2.2 gold picks — 20d already = 96% agreement (15d peak 97%,
  30d worse 92%). Residual ~4% is NSE-only-vs-Consolidated bias, accepted (NSE-only universe).

**CI fixes (suite now 113 passed / 0 skipped / 0 failed):**
- **#38** (2e1888b): repointed stale readiness tests off removed factors durability_own/valuation_own
  (adr-019) to roe/pe; dropped removed costs_bps assertions (cost output simplified iter-30/31).
- **#48** (a8d4063): conftest now points read-only WINDFALL_TRENDLYNE_DB/BHAVCOPY_DB at the real DBs
  when present, so the iter32/33/34 integration tests run instead of skipping (12 ex-no-ops now green).
- **#32:** deleted 7 junk strategies (EdgeTest, Test Strategy Alpha, 5× *_copy). Left `sas` +
  `momentum_survivorship_free` (real configs, not *_copy).

**Open follow-ups filed as to-dos:** **#73** (un-ingested IPOs OLAELEC + numeric-token/ISIN gold rows →
needs in-browser harvest; harvester half-built next session) · standing offer to cron the pit_mcap
rebuild so membership staleness can't silently recur.

**Next session pick-up:**
1. **#73** — finish the targeted browser harvester (model on `trendlyne_harvester_ohlcv.js` + dvm + leg1)
   for OLAELEC + the numeric-token/ISIN names; user runs it, returns CSVs, ingest (ohlcv + dvm + shares).
2. Decide whether to cron `rebuild_pit_mcap_ca.py` (membership freshness).
3. DB backup `backend/data/trendlyne.duckdb.bak-20260623-parity` retained as rollback — delete after #73.

## Session 2026-06-24 — engine data fixes + UI handoff port + validation planning

**Stage:** Stage 4 (iterations 12–14) + next-session planning
**What changed:**
- **iter-12 (#73 · adr-026) — loss-maker universe coverage.** Root cause: `pit_shares` derived shares = NP/EPS (requires EPS>0), so every loss-making name produced no share count → no `pit_mcap` → absent from `universe_membership` entirely. 19 names affected incl. SWIGGY (~₹70k cr), MEESHO (~₹80k cr), OLAELEC, ATHERENERG, FIRSTCRY, MTNL, UNITECH. Fix: fallback `shares = stocks.mcap / latest_close` for EPS-less pks, in canonical `rebuild_pit_mcap_ca.py` + surgical apply. +19 universe symbols (2101→2120). Numeric-token gold rows confirmed unresolvable internally; KRN/ALPEXSOLAR/DEEDEV confirmed already-covered (stale 06-23 gap run). Verifier APPROVE.
- **iter-13 (#81 · PARITY-5) — sub-floor NSE coverage.** Ingested 13 historically-liquid NSE names that sit below the ₹500cr Trendlyne harvest floor (GSPL, MIRZAINT, UGARSUGAR, SHANKARA, ORIENTBELL, KESORAMIND, 3IINFOLTD, HCL-INSYS, VINYLINDIA, SAKUMA, OMAXAUTO, APCL, RAMAPHO) via a targeted in-browser harvester (`trendlyne_harvester_parity5.js`, owner-run). Loaded ohlcv/dvm/pnl/etc; built pit_shares(EPS)/pit_mcap/membership (live path). +13 symbols (2120→2133). GSPL resolved fine (not delisted). NSE-only rule reaffirmed (adr-024): BSE-only names + numeric tokens deliberately dropped. Verifier APPROVE.
- **iter-14 (#39) — UI handoff port.** Implemented owner `CHANGES_HANDOFF.md`: Part A (20 review fixes) + Part B (owner changes). New shared primitives (Menu/Modal/ConfirmDialog), chart axes+gridlines+year-axis, darkened faint token, Single/Composite ranking (rank_blend — engine already supported), consolidated labeled config grid, Re-run split-button → Explore-variations modal, mobile nav, slim inline readiness (C-1), Export-CSV skipped (C-5). `next build` green; rebuilt + deployed `windfall-web`. Verifier APPROVE.

**Decisions:** adr-026 (loss-maker share-count fallback). NSE-only universe rule reaffirmed.

**Tracker:** closed #73, #81; deleted #18 (post-v1 roadmap — owner no longer tracking); created #82 (Session 1: engine-facing data audit + fix) and #83 (Session 2: backtest re-validation vs Trendlyne), both with detailed specs in `docs/validation/SESSION-*.md`.

**Next session pick-up:**
1. **#82 / Session 1** — engine-facing data audit + fix (no prereqs). Spec: `docs/validation/SESSION-data-audit.md`.
2. **#83 / Session 2** — backtest re-validation vs Trendlyne; owner first fills `C:\Users\pdsva\Downloads\backtest-data` with Trendlyne CSVs + per-test screenshots. Spec: `docs/validation/SESSION-backtest-revalidation.md`.
3. Pre-existing anti-gaslight note (not this session): 2 SO1 features at status=done lack `feature_claims` (cockpit-dashboard +1) — reconciliation gap from original Stage 3.

## Session 2026-06-24 (evening) — Session 1: engine-facing data audit + fix (#82)

**Stage:** Stage 4 (iteration #15) — owner-requested dedicated data-audit session
**What changed:** read-only audit of `trendlyne.duckdb` (30 tables) + PIT/identity layer (profiler committed at `docs/validation/data_audit_engine.py`; report `docs/validation/data_audit_run-2026-06-24.md`). 13 findings triaged; owner locked 5 fixes, all independently verifier-APPROVED:

- **F1 (adr-027) — PBV ≤ 0 guard.** `valuation_panel` masked PE/PEG ≤ 0 but left PBV; 30 names currently have negative book value that a `tl_pbv < N` filter admitted / an ascending P/B rank ranked "cheapest". Now masked, mirroring PE/PEG. `trendlyne_store.py`.
- **F2 (adr-028) — result_lag look-ahead.** Unmatched fallback was a flat 45d; annual audited results need 60d (SEBI LODR Reg 33), so unmatched annual fundamentals were visible ~15d early. Now period-aware: annual 60d / quarterly 45d. `phase3_build.py`. After rebuild: 12,184 annual=60d, 29,076 qtr=45d, 0 negative lag.
- **F3 (adr-030) — dead-bankruptcy survivorship.** 81 dead names (78 >₹50cr peak turnover) absent from the survivorship-free universe because bankrupt loss-makers had no positive-EPS screener page → no shares → no mcap. Seeded researched share anchors for 9 material deaths (DHFL, Bhushan Steel, Kingfisher, Educomp, Binani, Reliance Naval, Monnet, Future Consumer, Dewan). Now ride peak→delisting (DHFL ₹21,328cr→524cr, Bhushan ₹48,730cr→615cr). `rebuild_pit_mcap_ca.py`. Dilution-heavy 4 (3i/Alok/IVRCL/Amtek) deferred → todo 89.
- **F5 (adr-031) — silent delistings.** A live (pk-keyed) name that stops in BOTH Trendlyne ohlcv AND Bhavcopy >30d before the latest bar has genuinely delisted (not lagged) but had no terminal-exit record. Detector added to `build_ca_factor.py` + one-time `migrate_f5_delistings.py`. GSPL (Gujarat State Petronet, merged 2026-05, ever ₹26k cr) registered; detector flags only GSPL.
- **F6 (adr-029) — pit_mcap share anchor.** Current shares = NP/EPS was unstable near-zero EPS and meaningless for REITs/InvITs, wrongly EXCLUDING large names (PRAJIND ₹6,259cr→₹3cr, BAGMANE REIT ₹34,904cr→₹62cr, TVSINVIT) and over-inflating others (NAZARA 5×). Now anchored to `stocks.mcap / last_close` where present; NP/EPS fallback only where Trendlyne mcap is null. `rebuild_pit_mcap_ca.py`. Pure constant-scaling per name (verifier proved ratio stddev 0 → no look-ahead).

**Data rebuilt** (DuckDB, gitignored): result_lag, pit_mcap, pit_mcap_dead, universe_membership, delistings. Verified vs pre-fix backup `trendlyne.duckdb.bak-audit-20260624-201855`: ever-universe **2102→2133 (+31)**, **0 names wrongly dropped**, pit_mcap==ohlcv rows, 0 null/negative mcap.

**Decisions:** adr-027, adr-028, adr-029, adr-030, adr-031 (all curated). **Tracker:** closed #82; iteration #15 integrated; created follow-ups #84–89 (F4 renames, F7 return-sanity, F9 staleness refresh, F10 smallcap benchmark, F11/F12 cosmetic, F3 dilution-heavy dead names).

**Commits:** 281f1a5 (code+data), 820fbb4 (ADRs+mirror), 37ac1b6 (profiler) — pushed to Gitea.

**Next session pick-up:**
1. **#83 / Session 2** — backtest re-validation vs Trendlyne. NOW UNBLOCKED; F3/F6 shifted universe membership, so backtests WILL change — re-run against the corrected universe. Owner first fills `C:\Users\pdsva\Downloads\backtest-data` with Trendlyne CSVs + screenshots. Spec: `docs/validation/SESSION-backtest-revalidation.md`.
2. Audit follow-ups #84–89 (all non-blocking).
3. Pre-existing anti-gaslight (not this session): `unclaimed-done` on 2 SO1 features (cockpit-dashboard, strategy-editor) lacking feature_claims; `stale-verification` SOFT on 7 engine features — reconciliation gaps from original Stage 3, unaffected by this data session.
