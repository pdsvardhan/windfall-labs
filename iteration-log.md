# Windfall Labs — Iteration Log

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
