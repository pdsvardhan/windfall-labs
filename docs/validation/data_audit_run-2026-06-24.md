# Engine-facing data audit — run 2026-06-24

> Session 1 of the two-session plan (`SESSION-data-audit.md` → `SESSION-backtest-revalidation.md`).
> Method: read-only profiling of `trendlyne.duckdb` (30 tables) + PIT/identity layer while the API stayed
> live (API opens the file `read_only`, so concurrent read is safe). Reusable profiler committed at
> `docs/validation/data_audit_engine.py` (root-cause drills were one-off). Reference snapshot: ohlcv last bar **2026-06-16**.

## Store at a glance
- 30 tables; ~5.47M ohlcv bars (1959 priced pks), 9.67M DVM rows, 10.47M valuation rows, 5.80M universe rows.
- Identity: 1964 stocks (1738 distinct nsecode + 226 blank, **all 226 covered by `recovered_symbols`** — not a gap).
- Dates: prices 2006→2026; DVM/valuation 2016-05→ ; pledge/FII/DII (shareholding) 2023-03→ ; annual fundamentals 2000→.

## Findings & triage
Severity: **mandatory** (correctness / look-ahead) · **necessary** (materially shifts backtests/signals) · **nice** · **not-worth**.

| # | Table(s) | Symptom | Root cause | Fix approach | Effort | Verdict |
|---|---|---|---|---|---|---|
| **F1** | valuation_ratios → resolve | `PBV_A` not masked for ≤0; 158 names ever / **30 currently negative book value**; a `tl_pbv<N` filter ADMITS them and `rank tl_pbv asc` ranks them "cheapest" | `valuation_panel()` masks PE/PEG≤0 but deliberately leaves PBV ("negative book is rare and real", `trendlyne_store.py:345`). Same logic flaw as the fixed negative-PE bug (todo #36) | Mask `PBV_A` ≤0 → NaN (mirror PE/PEG); optional winsorize extreme-high (max seen 592,717 = near-zero book) | LOW | **mandatory** |
| **F2** | result_lag | Unmatched rows (40,890 / 57,012) use a **uniform 45-day** fallback; for **annual** period-ends that is look-ahead (SEBI annual audited filing window = 60d). Result-gated readers (tl_roe/de/opm/roic/cfo/piotroski…) read annual tables | Builder applies one 45d constant when no board date matched; matched lag median 39d, max 100d | Period-aware fallback: annual=60d, quarterly=45d (or research exact); rebuild `result_lag` (also picks up the 11 recent-annual gaps in F8) | LOW-MED | **necessary** |
| **F3** | dead_names / pit_mcap_dead / universe_membership | **81 dead names absent from survivorship-free universe**; 78 had >₹50cr peak turnover. Includes the biggest blowups: **DHFL, Bhushan Steel, Amtek, Binani, Educomp, Reliance Naval, Dewan Housing** | Dead-name mcap path needs `screener.fundamentals_history` with EPS>0; bankrupt names were loss-makers at death and/or screener lacks their pages → no shares → no mcap. `delistings.ever_mcap_cr` is **null** for all of them. No dead-name analogue of the live loss-maker fallback (adr-026) | Seed an mcap anchor for the ~10-15 material dead loss-makers; constant-shares = anchor/price → extend `pit_mcap_dead` + `universe_membership` (reproducibly, in `rebuild_pit_mcap_ca.py`). Full screener backfill for all 78 = follow-up | MED | **necessary** |
| **F5** | ohlcv / delistings | **GSPL** (Gujarat State Petronet, ever ~₹15,100cr) ohlcv ends 2026-05-11, **absent from `delistings` AND `dead_names`** → silent dropout, no terminal-exit flag | GSPL merged/delisted; never added to the dead-name path (todo #81 carried it as a separate item) | Add GSPL to `delistings` (last_date 2026-05-11, last close, ever_mcap) so the held-position terminal exit + warning fire | LOW | **necessary** |
| **F6** | pit_shares / pit_mcap | **36/1849 names diverge >50%** from Trendlyne's own current mcap; worst are **false-exclusions**: PRAJIND ₹6,259cr→₹3cr, BAGMANE REIT ₹34,904cr→₹62cr, TVSINVIT, NXT-INFRA — wrongly dropped from the universe. NAZARA/ELDEHSG computed 5-7× too high | Current shares = NP_TTM/EPS_TTM is unstable near-zero EPS and meaningless for REITs/InvITs and some recent IPOs | Anchor current shares to **`stocks.mcap` (Trendlyne ground-truth) ÷ latest close** where present; keep NP/EPS only where `stocks.mcap` is null. Edit `rebuild_pit_mcap_ca.py` | MED | **necessary** |
| F4 | dead_names / rename_map | 5 renames (SRTRANSFIN→Shriram Finance, NIITTECH→Coforge, PANTALOONR→Future, IIFLWAM→360 ONE, TATAMTRDVR) in `delistings` but **not** `rename_map` → pre-rename history not attached to successor | Rename map incomplete; engine treats them as clean delistings (acceptable exit), only successor-history backfill is lost | Add the 5 to `rename_map` | LOW | nice |
| F7 | ohlcv | 230 one-day moves >40% (worst: Elcid +6.7M%). Investigated: **real** — special call-auctions (Elcid), 3-yr suspension/resumption (Indosolar→WAAREEINDO), distressed relistings. Not splices, no missed CA | Genuine market events; mitigated by mcap/ADTV gates which exclude these penny/illiquid names | Add a backtest daily-return sanity warning + suspension-gap flag (transparency, not correctness) | LOW-MED | nice |
| F8 | result_lag | 133 `ratios_annual` (pk,date) rows have no result_lag (mostly 2026-03-31 = current FY not yet announced; only **11** of 2025-03-31) → those names use prior-year fundamentals (stale, **not** look-ahead) | result_lag not regenerated after latest ingest | Folds into the F2 rebuild | LOW | nice |
| F9 | ohlcv / index_ohlcv | Staleness skew: bhavcopy 2026-06-23, ohlcv **2026-06-16** (7d), index_ohlcv **2026-06-12** (11d), DVM 2026-06-24. Live-signal **regime overlay reads stale index** (prices are covered by `extend_live` from bhavcopy; indices are not) | EOD refresh updated bhavcopy + DVM but not Trendlyne ohlcv/index | Re-run EOD ingest for ohlcv+index; consider extending index regime from a fresher source for live signals | LOW (ops) | nice |
| F10 | index_ohlcv | Nifty Smallcap 250 starts **2019-01-14** only → smallcap benchmark/regime blind pre-2019 | Source history short | Source longer history or document | LOW | nice |
| F11 | ohlcv | 3 `high<low` + 64 OHLC-inconsistency rows, magnitude ~0.001 (float rounding), almost all on one obscure name (pk 2284) | Source rounding | Optional clamp; immaterial to fills | — | not-worth |
| F12 | index_ohlcv | `open/high/low/volume` stored as **VARCHAR** (close/last are DOUBLE) | Ingest typing; engine reads only `close`/`last` (DOUBLE) → no current impact, latent only | Optional cast to DOUBLE | — | not-worth |
| F13 | pit_mcap | `raw_close` null on 33% of rows | Audit-only LEFT JOIN to bhavcopy by symbol; column not used in mcap calc | None | — | not-worth |

## Re-verification of known prior items (spec category 8)
- **CA smoothness (iter-28) holds** — EICHERMOT / BEL / TATASTEEL mcap series are flat across their 10:1 splits (no 10× step).
- **Negative-PE guard (todo #36) holds** — PE/PEG≤0 masked; **PBV is the remaining gap → F1**.
- 127 names <200 bars (200DMA-blind) — expected for recent listings.
- DVM coverage: durability 1836 / valuation 1898 / momentum 1964 pks — Trendlyne's own coverage, not our gap.
- Loss-maker live fallback (adr-026): 19 pks on constant-shares — working; the **dead** analogue is missing → F3.

## Recommended in-session fix set
**Mandatory + necessary:** F1, F2, F3, F5, F6. Each: backup → stop `windfall-api`+`windfall-web` for writes → fix (edit the builder script where canonical) → independent verifier → ADR + Ottomate iteration.
**Follow-up todos (logged, not fixed now):** F4, F7, F8(rolls into F2), F9, F10; full screener backfill for the remaining ~63 non-material dead names.
**Accept / no action:** F11, F12, F13.
