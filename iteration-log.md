# Windfall Labs — Iteration Log

## Session 2026-07-17 — Stage 4 iter-23: comprehensive analysis + autonomous todo sweep + validation trilogy

**Stage:** Stage 4 iterate (9 items locked, 9/9 independent-verifier APPROVE — reports 516-521, 533-534 + item 634's)
**Context:** owner asked for a full project analysis/critique plus "complete all todos you can do alone; improve what you see fit" (first Fable-5 session on this project). Analysis delivered in-chat; its top gaps became locked items.

**Fixes (all verified, committed e36ee71..d19c0ac):**
- **#219 (629):** `/api/backtests/batch` now ENFORCES the sim-side grid-key allowlist — resolve-affecting keys (regime_filter.*/rank/universe/window) 400 before the base resolve, naming offenders. 19 tests.
- **#84 (630):** 5 renamed-but-dead names linked in rename_map with bhavcopy ISINs. Verifier root-caused TATAMOTORS `live_in_tl=false`: the 2024/25 demerger split it into TMCV/TMPV (chain gap → todo 246).
- **#88 (631):** 64 inconsistent OHLC rows clamped to 0; index_ohlcv o/h/l/volume VARCHAR→DOUBLE (3,232-5,785 literal 'null' strings per column became real NULLs).
- **#98 (632):** `scripts/batch_client.py` — long runners wait out the 20:25-20:55 IST EOD window, retry conn/5xx, fail 4xx fast. 7 tests.
- **637:** `costs_bps` proven INERT since adr-020 yet still validating — the validation harness had silently run NET against Trendlyne's gross reference, and the old cost test asserted <= on two equal runs (vacuous). Now: deprecation warning on non-default use (run-local, batch-safe), `_check_reproduce` at cost_mult=0, strict tests.
- **636:** honesty drift purged — `/api/data/status` no longer claims survivorship "deferred" (shipped adr-018/030); validation.md refreshed (186/12 tests, live paper run, round-2 overlap 79-91%); iters 16-18 bridge reconstructed in this log (below-dated sessions were never logged).

**Validation trilogy (adr-040 + adr-041):**
- **Walk-forward gate (633):** ALL five deployed strategies robust — OOS/IS Sharpe 0.71-0.94 over 8 rolling 3y/1y folds. Untouched 2007-2016 decade (2008 included, zero design decisions fitted on it): MOM_roc252 22.0% CAGR / 1.03 Sharpe / -30.1% MaxDD at 67% exposure. The adr-006 gate debt on the live paper run is cleared.
- **Blend parity (634):** adr-035's 29.5%/1.27/-42.7 headline REPRODUCES from stored sleeves (30.1%/1.29/-45.3). The twice-flagged iter-20 "non-reproduction" was a holdings mismatch — n=20 sleeves give exactly the 23.1%/1.13 iter-20 saw. Debt closed.
- **Regime study (635):** the index MA100 binary gate is the FIRST risk overlay to survive measurement — DD cut 11.8-24.1pp on all four paper strategies at Sharpe cost -0.10..+0.05 (two strategies IMPROVE), vs stops (all destructive, adr-039) and own-equity timing (halves CAGR, adr-033/034). Cost: 5-8pp CAGR, ~1/3 time in cash. Recorded as CANDIDATE (adr-041) — zero live-config changes (verifier confirmed zero footprint across all 289 stored configs); adoption path = walk-forward the gated configs (todo 249) + owner decision before 1 Aug.

**Session interruption (00:55-01:40 IST):** a parallel session's ext4 deleted-file recovery (extundelete, media/music/telugu) remounted /mnt/storage READ-ONLY mid-build and quiesced containers; a third (portfolio) session bulk-restarted them unaware. Not disk failure (SMART PASSED, fs clean, administrative remount in auth.log). This session verified 6 items read-only during the freeze, coordinated via cross-session message, and resumed on a restore watcher. Lesson: verification is freeze-compatible (pytest -p no:cacheprovider; DuckDB read_only opens fine with the api down).

**Ledger:** claims 157-164, 170-171 + 634's, all reconciled; iter-21's missing rows backfilled (explicitly labelled, report 522) closing #207. Todos closed: 84 88 98 103(rewritten) 182 184 200 207 219. Created: 246 (TATAMOTORS chain), 248 (next-open at 1 Aug), 249 (gated WF + adoption), 250 (rotation endpoint: single-sleeve 400, calmar=0, PLUS a transient NoneType 400 on valid multi-sleeve payloads caught by the 634 verifier), 251 (down-weight truncated WF folds).
**Friction:** ottomate `/lock` 400s on a missing JSON body — send `{}` (tooling). `/api/rotation` single-sleeve weights=[1.0] 400s; also one transient `'NoneType' has no attribute 'empty'` 400 on a valid call that succeeded on retry (todo 250). DuckDB read-only opens print a progress bar that polluted 144KB of captured stdout — pipe through a filter (tooling). A parallel-session fs freeze mid-iteration is survivable: batch Ottomate writes are NVMe-side, verification is read-only (env).
**Next session context:** **#220 HARD DEADLINE unchanged — owner harvest 30-31 Jul.** 1 Aug = first rebalance + first closed trades + the natural adoption point for next-open entries (248) and, if the gated walk-forward passes and the owner signs off, the MA100 gate (249, adr-041). Drawdown blocker (#103) now has a measured mitigation on the table.

## Session 2026-07-16 (2) — Stage 4 iter-22: no-stop decision + batch/quarterly bugfixes + Trendlyne refresh

**Stage:** Stage 4 iterate (decision + 2 verified bugfixes + the manual data refresh)
**What changed:**
- **adr-039 — no stop-loss, by measurement (#99 closed).** Swept the no-stop baseline against trailing-ATR at 2/3/4/5× across all four paper strategies: no-stop wins on Sharpe in 3 of 4, ties the fourth. A 2× trailing stop turns **every** strategy negative (DVM_user CAGR 33.6% → −12.6%); loosening walks monotonically back to no-stop, so the limit of "loosen" is "remove". **#99's premise was false**: all 289 stored configs already had `stop_loss.type=none` — it measured a harness experiment, not the live path (confirmed by provenance: 2× ATR reproduces R2's 14d/32% as 11.1d/33.6%). Fixed-pct stops recorded as available-not-adopted (MOM at −20% trades 2.6pp CAGR for 8pp drawdown). **Drawdown 55–75% is untouched by stops and is now the real blocker on #103** — a regime/position-sizing question.
- **#210 `/api/backtests/batch` silently simulated NO stop (item 615).** It documented `stop_loss.*` as sweepable, but `resolve.py:373` only builds the ATR panel when the BASE config already asks for one; batch resolved once from `base_config`, so a `type=[trailing]` grid left `rs.atr_stop=None` and returned **byte-identical no-stop numbers under a trailing label** — no error, no warning. It nearly produced the exact false conclusion "stops don't matter" (truth: 0.3357 → 0.0631). Fixed by grouping combos on `_resolve_key` (type + atr_period; pct/none collapse) so each panel resolves once; the resolve-once optimisation survives for sim-side grids.
- **The verifier caught the first fix as incomplete (round-1 ITERATE, correctly).** `StopLoss.mult` defaults to None and the schema only rejects non-positive values, so `type=trailing` with no mult VALIDATES and never arms (`and cfg.stop_loss.mult` is falsy) — the symptom still reproduced on the *stored* DVM_user. **My own e2e check had passed only because it gridded `stop_loss.mult=[3.0]` alongside the type, supplying the missing param itself.** Round 2 added `_inert_stop`: an unarmable stop is refused **before** the resolve, returning no summary at all. Verifier round 2 APPROVE, with 3 mutation tests — incl. reinstating the original leak, which killed 3 endpoint tests, proving they pin the old bug.
- **#209 live signals KeyError on quarterly (item 616).** `_STEP` lacked `quarterly` while the schema accepts it — 96 of 289 stored strategies are quarterly. Added `quarterly: 63` (21×3, the codebase's 252-day convention; verifier measured the real NSE calendar at median 62.0 / mean 61.82, same +1.9% error monthly's 21 carries). Tests pin `_STEP` bidirectionally to the schema Literal so the two cannot drift again. Verifier APPROVE first round.
- **Trendlyne refresh MERGED (not replaced).** DVM 06-24 → **2026-07-16** across 2,001 pks; signals `as_of` 06-29 → **07-15**; 1,921 eligible. **A naive replace would have deleted 806,349 rows / 138 megacaps** (RELIANCE, TCS, SBIN, LT…) with no error — the base screener silently caps at ~₹110k. Recovered 95 via the megacap harvester + 5 via a new `trendlyne_harvester_gapfill.js` (the megacap SYMBOLS list is **stale** — CIPLA/ZYDUSLIFE/LUPIN/LODHA were never in it; **BSE cannot be resolved by symbol** and needs by-pk addressing). Merge **preserved 197,547 dvm + 105,477 ohlcv rows** for 43 names that legitimately left the universe (sub-500cr / delisted) — a replace would have reintroduced the survivorship bias adr-030 exists to prevent. `index_ohlcv` deliberately untouched (NSE feed 07-15 is fresher than the harvest's 07-08).
- Tests 127 → **159 passed / 12 skipped** (+32 net new: 15 batch resolve-key, 9 batch endpoint, 8 live-signals step). Iteration 86 integrated; merged `40ec86e`.

**Decisions:** adr-039 — no stop-loss, by measurement (accepted, curated, cat:product).
**Friction:** `/api/backtests/batch` via port **8500 returns a bare 500 on multi-resolve requests** — that is the Next.js proxy timing out, not the API; hit **:8505** directly (env-limitation). Container code is **baked into the image** (only `./backend/data` + `./backend/strategies` are mounted) — `docker compose restart api` does NOT pick up code, needs `up -d --build` (env-limitation). pytest/duckdb live in the **host venv**, not the container, and need `PYTHONPATH=.` (tooling). SSH heredoc mangled a commit message on an apostrophe — SCP the message file instead, per operating rule 6 (tooling). `name` is a DuckDB reserved word; megacap/gapfill stock CSVs have no `mcap` column (probe the header, don't assume) (data-mismatch). The Ottomate lock-gate URL is **https://ottomate.vault7a.xyz/iterations/N** — `localhost:8110` is the *server's* localhost and unreachable from the user's browser; I sent the user there and the lock silently never happened (env-limitation).
**Next session context:** **HARD DEADLINE #220 — re-run `trendlyne_harvester_ohlcv.js` + `trendlyne_harvester_megacap.js` on 30-31 Jul.** `pit_universe` gates membership on a 14-day lookback, `pit_mcap` is bounded by *Trendlyne* ohlcv, and Trendlyne's OHLC **lags its own DVM by ~8 days** (07-08 vs 07-16). Today that is fine; on 1 Aug the 07-08 mcaps fall outside the window, the universe empties, and the rebalance silently ranks on 3-week-old data. Standing alternative that would delete the manual step forever: extend pit_mcap's *live-name* tail with bhavcopy × ca_factor (the method already used for DEAD names) so membership tracks the daily T-1 feed — a real adr-030 fidelity trade, needs an owner decision + ADR. Also open: **#219 (load-bearing per the verifier)** — batch still silently reuses the base resolve for `regime_filter.*` (measured 0.2289 vs 0.2350 direct) and any rank/universe grid key; the docstring now names them unsafe but an API consumer cannot read a docstring — fix is a known-safe grid allowlist + 400. **Drawdown (55–75%) is the honest blocker before real money (#103)**, not stops. Backups: `/mnt/storage/backups/windfall/trendlyne.duckdb.pre-iter22-bak` (703MB, delete once the refresh is trusted).

## Session 2026-07-16 — Stage 4 iter-21: paper-trade read-out + audit-todo sweep

**Stage:** Stage 4 iterate (data-fidelity + reporting-honesty batch)
**What changed:**
- **Paper dry-run read-out (day 9).** Marked through 2026-07-15: +0.84% gross / +0.38% net aggregate on ₹5L vs **Nifty 500 −0.73%** over 2026-07-06→07-15 — early alpha, not beta (4 of 5 beat the market; the laggard still beat Nifty 50). Per strategy gross→net: MOM_roc252 +1943→+1476, DVM_user +1328→+954, BLEND_70_30 +1004→+470, CMP_valmom +282→−196 (flips red net), DVM_dm −366→−782. All positions still open; first rebalance 1 Aug. Book verified clean — only the 5 intended strategies, no stale dvm-monthly (closes #181's purge).
- **#85 automated NSE index feed (the big one).** `index_ohlcv` was **34 days stale** (max 2026-06-12, worse than the 11d logged) because indices only arrived via the manual WAF-gated Trendlyne harvest — blinding the live-signal regime overlay AND making the benchmark uncomputable. NSE's `ind_close_all_DDMMYYYY.csv` archive IS fetchable server-side: new `backend/scripts/index_ingest.py` (name→pk via `index_map`, idempotent delete-then-insert, skips non-trading days), wired into `windfall-eod-refresh.sh` in the same api-stopped exclusive-write window as the Bhavcopy ingest. Backfilled 2026-06-13→07-15 (110 rows, 22 trading days × 5 indices).
- **#94** `tl_opm` remapped `OPM_A` (40/1962 names, negative median — broken export) → `PBDITMargin_A` (1924/1962, +15.9% median).
- **#96** `readiness._TL` now imports `resolve._TL_FEATURES` (single source of truth) — mcap / tl_roic / tl_ps / tl_eyield / tl_int_cover / tl_piotroski / tl_np_growth / tl_rev_growth / pledge / fii / dii no longer mislabelled "will be skipped".
- **#184 (partial)** paper P&L now reported **net** of the modelled NSE delivery costs (`net_pnl` on `/api/paper/scoreboard`, reusing the engine's side-aware rates + flat DP); per-name `stale_mark` flag (caught 3/87 open marks); `_latest_close` bare-except now logs instead of swallowing.
- **#86** engine flags >40% one-day moves + multi-month suspension gaps on names *while held*. **#99 (partial)** same-bar entry-stop guard — a next-open fill can no longer be stopped out on its own entry bar (0-hold whipsaws gone). **#87** benchmark-coverage warning (e.g. Smallcap 250 begins 2019-01-14). **#95** `pe_to_sector` snapshot-only honesty warning. **#97** `/api/backtests` `limit`/`offset` pagination (defaults preserve prior behavior exactly).
- Verification: 139/139 backend tests green; independent verifier **APPROVE** (no high/med defects, no look-ahead, no stubs). Verifier finding #1 acted on — pagination default changed to `limit=None` so the per-strategy list stays uncapped as before.

**Decisions:** adr-038 — data-fidelity & cost-honesty hardening (accepted, curated, cat:reliability).
**Friction:** to-do titles >300 chars 422 again (2nd session running — measure length before POST; `-o /dev/null` hides the body, drop it when debugging) (tooling). `import a.b.c as x` binds the package attribute, so `windfall.strategy.__init__`'s re-exported `resolve` function shadows the module in throwaway check scripts — use `importlib.import_module` (tooling). Host writes to `trendlyne.duckdb`/`windfall.duckdb` need the api stopped (read-only attach still holds the lock) — the bhavcopy stop/start pattern is the answer (env-limitation).
**Next session context:** paper watch continues — the interesting date is **1 Aug** (first monthly rebalance + first closed trades, which is when win-rate/avg-return stop reading 0). **Owner action owed before then: the manual in-browser Trendlyne pull** (membership + fundamentals) — #182/#183; the snapshot-reminder cron fires 1st 09:00. Open engine/research items: #99 trailing-stop redesign (94% of exits are stops); #184 next-open paper entries (deferred — would re-baseline the running book); heavy survivorship backfills #89/#92/#93; #84 rename reconcile; #88 cosmetic OHLC casts; #98 batch-cron guard; #185 process-diagram enrich. Watch: PBDITMargin carries extreme outliers — clip if any hard `tl_opm` threshold filter is used. Still owed from iter-20: adr-035's 70/30 headline (29.5%/1.27) doesn't reproduce from the saved sleeves.

## Session 2026-07-06 — Stage 4 iter-20: live-signals fix + 5-strategy paper dry-run

**Stage:** Stage 4 iterate (bugfix + new capability)
**What changed:**
- Fixed live-signals all-sell bug — `generate_signals` resolves as-of the last bar with a tradeable universe (stale point-in-time membership vs bhavcopy-spliced prices emptied `entry_mask` on the spliced tail).
- Fixed paper mark-to-market — `_latest_close` uses the Trendlyne store (bare tickers + live splice) instead of the dead yfinance `prices` table (P&L was stuck at 0).
- Built `/paper` cockpit page + Nav; daily mark cron (wkdays 20:40); monthly rebalance cron (1st 21:30) + `POST /api/paper/rebalance` + `/api/paper/purge`; `paper/rebalance.py` ROSTER.
- Started a 5-strategy paper dry-run at ₹1L each: DVM_user (owner design: mcap>500 · avg(D,V,M)≥55 · top-10 by DVM percentile-blend), DVM_dm_m_20, BLEND_70_30 (70% MOM_roc252 / 30% LV_atr), MOM_roc252_m_20, CMP_valmom_m_20.
- Independent audit → fixed CRITICAL phantom day-0 P&L (entries now at the latest executable close) + UI cost-honesty (P&L labelled gross-of-costs; deployed capital + cash % surfaced). Re-baselined every book to 2026-07-06 (day-0 P&L = 0).

**Decisions:** adr-037 — live signals + honest paper dry-run (accepted, curated, cat:reliability).
**Friction:** to-do titles >300 chars are rejected silently (curl -f → empty body); the membership/ohlcv staleness is a recurring manual Trendlyne-harvest dependency (data-mismatch).
**Next session context:** watch the `/paper` scoreboard diverge over ~2 weeks. Remaining audit follow-ups (todo #184): net the NSE cost model into paper P&L; enter at next-open to match the backtest; per-name mark-staleness flag. Monthly: do the Trendlyne pull before the rebalance cron fires. adr-035 70/30 headline (29.5%/1.27) does not reproduce from the saved sleeves — a parity pass is owed.

## Bridge — Sessions 2026-06-25/26 (iters 16–18 + the strategy sweep) — reconstructed 2026-07-16

These sessions were never logged at the time (the only gap in the session record; earlier sessions
live in `docs/iteration-log.md`, later ones above). Reconstructed in iter-23 (#636) from
adr-033/034/035/036 and the backtests store — the ADRs carry the full evidence tables.

- **iter-16 (adr-033):** factor-timing (hold the book only while its own equity sits above its
  MA100) built in-engine on a *reference* equity curve with real switching costs + next-open fills.
  The offline PoC's "free" drawdown protection did **not** survive execution: CAGR 38.7% → 18.4%,
  Sharpe 1.26 → 0.83 on the momentum sleeve.
- **iter-17 (adr-034):** weekly bidirectional re-engagement recovers CAGR (23.5%) and Sharpe (1.04)
  but hands the drawdown protection straight back (−49.5%, same as plain). No overlay variant beats
  plain momentum's 1.26 — own-equity factor-timing dropped as the primary risk control.
- **iter-18 (adr-035):** `LV_atr` defensive sleeve built (CAGR 7.6%, corr 0.42 to MOM, asymmetric in
  drawdowns). Trailing-return sleeve rotation rejected (every variant worse than plain momentum on
  Sharpe AND Calmar). A **fixed 70/30 MOM/LV blend** wins: Sharpe 1.27, MaxDD −42.7%, zero tunable
  degrees of freedom — the first deployable candidate.
- **The 289-config strategy sweep** (store timestamps 2026-06-25): DVM dv/dm/all × w/m/q ×
  10/15/20/30 holdings + MOM_roc252 + CMP_valmom variants populated the leaderboard the paper
  dry-run was later picked from.
- **adr-036 (2026-06-30, documentation):** recorded during the Ottomate deep-dive — the engine
  shipped hand-rolled; the adr-004 vectorbt plan was never adopted.

## Session 2026-08-10 — Iteration 147: post-1-Aug-rebalance catch-up

**Stage:** Stage 4 iteration (3 items: gated walk-forward, next-open paper entries, refresh tooling)
**Duration:** ~3.5 hrs
**What changed:**
- adr-041 MA100 regime gate walk-forwarded (adr-040 protocol, 16 runs) — **fails its own adoption
  bar** (overfit signature: IS up / OOS down on all 4 deployables; DVM_user outright FAILs).
  Recorded as adr-042 (rejected). Books stay ungated for the 1 Sep rebalance.
- Paper rebalance entries now fill at the next session's open (`pending` status, filled by the
  daily mark) instead of the rebalance evening's close — matches the backtest's no-look-ahead
  fill assumption (adr-038's deferred switch). New `paper_positions.planned_capital` column +
  migration. 9 new tests, full suite 208 green.
- `backend/scripts/ingest_refresh.py` + `docs/ops/trendlyne-refresh-runbook.md`: the Trendlyne
  refresh merge-ingest (lost with a prior session's scratchpad) is now a repo script with a
  history-shrink guard and a truncation floor, tested against DB copies. Owner run still pending
  (todo #220 — WAF forces in-browser harvesting).
- Paper page copy reconciled to describe next-open fills (doc-reconcile).

**Decisions:** adr-042 (MA100 regime gate rejected — curated, cat:product)
**Friction:** verifier-936 caught a real bug (lazy TEMP VIEW re-evaluated post-DELETE, silently
blanking real market-caps on a no-mcap gapfill ingest) — fixed same session (commit 9066d89),
re-verified. Tag: tooling-bug, caught-by-verifier (the anti-gaslight bedrock doing its job, not
friction to route around).
**Next session context:**
- Owner still owes: run the Trendlyne refresh (todo #220, runbook staged) and acknowledge/ratify
  the adr-042 gate-rejection decision.
- adr-042 flags 2 remaining unmeasured risk levers if drawdown mitigation is revisited:
  vol-targeting position sizing, or a crash-conditional/regime-stratified evaluation design —
  each needs its own pre-declared bar + ADR before counting as an adoption gate.
- Pre-existing anti-gaslight HARD violations (not from this session, unaddressed):
  `cockpit-dashboard` and `strategy-editor` at status=done with no feature_claims row.
- Pre-existing untracked `docs/orientation/` in the repo — not touched this session, unclear
  provenance, worth asking the owner about next time it comes up.

---

## iter-171 — 2026-09-04 — paper-book honesty audit

**Trigger:** owner returned after ~3 weeks away and asked what the paper books had actually done,
which strategies were working, and whether the pipeline was functioning. The first answer given was
a leaderboard of eight books. The owner's follow-up — *"is anything true?"* — was correct to ask: two
independent defects meant most of those numbers were wrong.

**Duration:** ~2.5 hrs
**Iteration:** ottomate 171 · 12 items locked (10 built, 2 observations) · verifier round 1 BLOCK,
round 2 APPROVE

**What was wrong (measured, not inferred):**
- **BE-series marks froze.** Every price path filtered `series='EQ'`, so a holding moving to the
  trade-for-trade segment vanished from the live splice; `mark_to_market` skipped it silently and the
  curve forward-filled its last EQ close. 10 open positions affected, up to 8 weeks. STALLION was
  marked 254.00 from 10-Aug against a real 206.68; BLISSGVS was booked at −3.2% while actually +26.6%.
- **The equity curve was not a portfolio return.** It divided by every rupee ever deployed, so
  recycled capital was counted twice and any rebalancing book was diluted toward zero. DVM_user read
  7.67% where the account had made 11.88% gross / 11.27% net.
- **Three of eight books had never rebalanced.** `ROSTER` held five; MOM_roc252_m_10, DVM_all_w_10 and
  DVM_all_m_10 were seeded 29-Jun and buy-and-hold ever since, while still being marked daily and
  published as live. They are the three the 2026-07-17 protocol rated *survivor* — the only three
  that passed it. The weekly and monthly DVM_all_10 variants reporting identical returns was the tell.
- **Signals have been frozen at 2026-07-22 for six weeks.** Point-in-time membership runs dry after
  that date, so the engine falls back to the last bar with a tradeable book and says so in
  `warnings`. The cron logged 400 truncated characters of the response and nothing read them, so the
  1-Aug and 1-Sep rebalances both re-derived a stale book with no alert.

**Corrected numbers (net of costs, NAV basis, ₹1L book, 29-Jun/6-Jul → 4-Sep):**
DVM_user +11.27% · CMP_valmom_m_20 +3.94% · DVM_all_w/m_10 +3.53% · MOM_roc252_m_10 +4.09% ·
MOM_roc252_m_20 +3.50% · DVM_dm_m_20 +1.77% · BLEND_70_30 +1.65% — against a Nifty 500 that ran
−0.77% to +1.12% over the same windows. Every book beats its benchmark; the ranking changed
materially (BLEND fell from 4th to last, MOM_roc252_m_10 rose from last to near the top).

**What changed:**
- Pricing reads NSE mainboard series (EQ/BE/BZ). Universe gate, ADTV panel and dead-name splice stay
  EQ-only on purpose — widening those re-baselines every published backtest (adr-043).
- NAV equity curve replaces the cost-basis ratio, unitized across notional changes, with a
  net-of-costs series alongside gross and per-book stats for drawdown, cash floor and unpriceable
  holdings.
- `mark_to_market` counts and names what it cannot price. `scoreboard` splits `closed_win_rate` from
  `book_win_rate` — the closed-only figure read 17–33% on books that were all profitable, because a
  rotation book cuts losers and rides winners by design.
- Rebalance is cadence-aware per book (cron moved to daily, the API decides who is due), funds new
  entries from true cash so a book cannot overdraw, and records every run in `paper_rebalance_runs`.
- The three survivors joined the roster, keeping their 29-Jun baskets.
- Signal-run health is returned and the cron alerts on staleness instead of logging a truncated prefix.
- `/api/paper/equity` honours `strategy_id`; `/api/paper/resize` and `/api/paper/void-pending` added.
- Paper page reads the API's NAV numbers instead of recomputing them, surfaces both win rates, real
  idle cash, overdraws and drawdown, and its cohort copy now matches what is on the page.

**Decisions:** adr-043 (mainboard-series pricing — curated, cat:reliability) · adr-044 (batch-splice
holes — **status: open**, curated, cat:reliability)

**Friction / honesty note:** the verifier's round-1 BLOCK was correct and caught a defect this
session introduced *after* its own verification pass: an aborted ₹5L notional step-up left both
notionals in the run log, and the unitization issued units on an increase but never redeemed them on
a decrease — every book read ≈ −79%. The lesson is narrow and worth keeping: **a state change after
the verification invalidates the verification.** Round 2 also caught the regression test for that bug
being decorative (it re-implemented the arithmetic instead of calling the code, and passed with the
bug restored); it now drives `book_equity` and was mutation-checked failing at −0.79924.

**Observations logged, not built:**
- **#1238 — the Trendlyne refresh is the blocking owner action.** Fundamentals stale since 2026-06-18
  (78 days), membership dry after 2026-07-22. Needs a browser session; Trendlyne's WAF blocks
  server-side pulls. Tracked as to-do #220, runbook at `docs/ops/trendlyne-refresh-runbook.md`. Until
  it lands, every rebalance re-derives a July book.
- **#1239 — leaderboards and robustness verdicts are stale.** Generated 2026-07-17 with every window
  ending 2026-06-16. Regenerate after the refresh. Already being confirmed live: DVM_dm_m_20 was
  flagged *"recent 2.5y is weak"* and is the worst real book at +1.77%.

**Next session context:**
- Owner still owes the Trendlyne refresh (#220). It gates the ₹5L notional flip, the leaderboard
  regeneration, and any real read on which strategy to deploy.
- The ₹5L decision is recorded but NOT applied. `BOOK_NOTIONAL` stays ₹1L because raising it without
  a resize leaves a book holding ₹1L of positions against a ₹5L base — DVM_user came out 80% in cash,
  a worse distortion than the 11–26% drag being fixed. Sequence: refresh → confirm a current `as_of`
  → set `BOOK_NOTIONAL = PAPER_TARGET_NOTIONAL` → `POST /api/paper/resize` per book.
- adr-044 is open: the per-symbol splice fix is three lines and probably correct, but it changes
  backtest inputs, so it wants its own measurement plus a re-run of the leaderboards and the parity
  ledger. Worth landing together with adr-043's dead-name question as one deliberate re-baseline.
- Residue from the aborted step-up, deliberately left as an audit trail: two 2026-09-04 rows per book
  in `paper_rebalance_runs` (handled by the same-day collapse) and 34 `voided-by-operator` rows in
  `paper_positions`.
- Still unaddressed from iter-147: `cockpit-dashboard` and `strategy-editor` sit at status=done with
  no feature_claims row (pre-existing anti-gaslight HARD violations).
- `docs/orientation/` (CODE-MAP.md, CONCEPTS.md, dated 22 Jul) is still untracked and of unclear
  provenance — asked about but not resolved.

---

## Session 2026-09-07/08 — iter-172 · data honesty + the full Trendlyne refresh

**Stage:** Stage 4 iteration (#173, items 1245-1249) + owner-directed follow-ups
**Duration:** ~10 hrs · **Commits:** 13 · **Tests:** 290 → 308, 0 skipped · **ADRs:** adr-045, adr-046

### How it started, and what it actually was

The session opened as "regenerate signals on the fresh data" (#844). All 8 paper books came back
`as_of=2026-09-04` with healthy buy/hold/sell splits, and by the project's own acceptance test the
refresh had worked. It had not. **Every one of 140 held/bought positions across the eight books came
from 293 of 2,190 stocks — 14% of the market — and nothing said so.**

That finding drove the rest of the session.

### The two silent-input failures, and what they have in common

**adr-045 — a forward-filled factor now declares its age.** `valuation_ratios` (PE/PEG/PBV) had no
refresh path at all: `ingest_refresh.py` handled three tables, the runbook never named it, and
`trendlyne_harvester_megacap.js` had been emitting its CSV every month into a directory the ingest
then wiped. Frozen at 2026-07-15 for 54 days while `dvm_history` ran to 2026-09-04. Because
`resolve()` ffills the daily panels, `CMP_valmom_m_20` — a live book — ranked half its holdings on
July multiples with a current `as_of`. 48 of 289 saved strategies read those factors.

**adr-046 — universe eligibility falls back to Bhavcopy.** `harvesters/README.md` told the owner
that skipping the ~40-minute OHLCV harvest was normal and "NOT needed for freshness — Bhavcopy
carries prices to today". True of PRICES, false of ELIGIBILITY: the same table feeds
`rebuild_pit_mcap_ca` → `pit_mcap` → `universe_membership`. The owner followed the documentation
exactly and it froze the candidate list.

It only surfaced because the failure needs a PARTIAL refresh. While everything was equally stale the
`ffill(limit=10)` bridge covered the whole universe and signals resolved on an older bar with all
~1,921 names — stale but complete and disclosed. Refreshing 257 megacaps dragged the newest usable
bar from 2026-07-15 to 2026-09-04 and pushed the other ~1,900 outside the bridge. **A partial
refresh was worse than no refresh.** The existing guard asks "is the eligible set EMPTY?"; 293 is
not empty.

The common shape, and the reason both ADRs exist: the project's rails are built around not trusting
a NUMBER. Neither of these was a wrong number. Every figure was internally consistent and every run
passed its own acceptance check. What was missing was a statement about an input's PROVENANCE.

### Built (iteration #173, all verifier-approved)

- **#850** stale-factor disclosure on ffilled daily panels (14d, the pit_universe window)
- **#849** `valuation_ratios` into the ingest, keyed per `(pk, metric)`; then generalised over
  `METRIC_TABLES` so `pnl_quarterly` / `growth_quality` / `ownership` stop being downloaded and
  discarded
- **#250** three `/api/rotation` defects. `calmar` was never a zero — it was never a FIELD; the
  iter-23 harnesses read `s.get("calmar")` and printed `(... or 0)`, so an absent metric rendered as
  a zero one. The "transient NoneType, fine on retry" reproduced as a real race: `lru_cache` guards
  its dict but not the wrapped call, so 12 concurrent first-callers of `_con()` all ran its
  check-then-ATTACH and 11 died
- **#246** transitive rename chains (`TATAMTRDVR > TATAMOTORS > TMPV`), 1 chain in 127 rows
- **#820** per-symbol price splice — and it collapsed adr-044's feared re-baseline: `extend_live` is
  only true when `cfg.end is None`, so a dated backtest never enters that path
- **#251** walk-forward folds under a quarter excluded from the averages
- **#92** `mcap_panel` and `membership_panel` now share `_pit_mcap_wide` — they had the same query
  written twice and adr-046 fixed only one
- **#89** point-in-time share counts via ASOF join. Measured: today's count off by >2x on 18.1% of
  3.79M cells; **5.29% of Rs500cr universe decisions change**, 195,302 out against 4,843 in
- **#851/#852/#853** leg1 promoted + quarterly staleness disclosure + the conftest fix
- **sector_pe / industry_pe / rs_nifty_* / rs_sector_*** computed from panels we hold instead of
  read from a snapshot that covered 79% of the universe. 0 of 289 strategies used them, so nothing
  re-baselined

### The refresh itself

Owner ran DVM + megacap + OHLCV + leg1-lite, plus 10 Data Downloader exports.

| | before | after |
|---|---|---|
| stocks priced to 2026-08-28 | 257 | **1,972** |
| `valuation_ratios` | frozen 2026-07-15 | **live to 2026-09-04** |
| eligible universe | 293 | **1,937** |
| fundamentals snapshot | 81 days stale, 1,138 tickers | **age 0, 2,365 tickers** |

`CMP_valmom_m_20` now returns `as_of=2026-09-07` with **zero stale-factor warnings** — the alarm
built that morning fell silent because the problem was fixed. Bhavcopy fallback dropped from 1,599
names to 49.

### Two things that did NOT work, kept as findings

- **Data Downloader**: caps at 2,000 rows and truncates ALPHABETICALLY at M — RELIANCE, TCS and SBIN
  simply absent. Two stock groups appear to be OR-ed, so "NSE-listed" + a cap band returned the same
  unfiltered list five times. Fix is ONE group per export, run per market-cap band. Forward-PE is
  unobtainable this way: every cell reads the literal `"Export NA"` (#857).
- **#860 pit_shares seeding**: built, measured, ROLLED BACK. 85.6% → 85.9% agreement and it broke
  PRAJIND (6,395 → 3). Three reasons recorded in the script so the next attempt starts there.

### Friction

- *tooling* — SSH heredocs mangled JSON/JS repeatedly (backticks shell-expanded, `$` interpolated,
  reserved words `asof`/`days` in DuckDB). Every non-trivial payload should be written locally and
  SCP'd, which is already operating rule 6; I kept forgetting it.
- *env-limitation* — `windfall.duckdb` is held by the API, so any in-process `resolve()` or
  `fundamentals` read fails with a lock error. Verification has to go through the API or read the
  source files.
- *process* — my first `#89` before/after check was worthless: the price ingest moved 1,715 stocks
  in the same window, so the comparison could not isolate the share-count effect. The trustworthy
  number was the read-only one measured BEFORE any ingest.

### Next session

1. **#819 — the Rs5L flip / simulation from 29 June.** Fully unblocked; every input it waited on is
   current. Owner's intent: re-run the books from 29 June at Rs5L and show it alongside the real
   Rs1L record. `resize` closes all 106 open positions, so force an immediate rebalance or 7 of 8
   books sit in cash until 1 October.
2. **#857 — forward-PE via the browser harvester.** Export route confirmed dead. Find the Forecaster
   endpoint in devtools on a stock page, model on `trendlyne_harvester_megacap.js`.
3. **Tidying** — #854, #858 (point the runbook at leg1-lite), #288, #818, #185, #841/#846.
4. Pre-existing HARD anti-gaslight: `cockpit-dashboard` and `strategy-editor` at `status=done` with
   no `feature_claims` row. Unchanged since iter-147, still unaddressed.
