# Windfall Labs — Iteration Log

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
