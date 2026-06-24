# adr-030 — Put real bankruptcies (DHFL, Bhushan Steel, Kingfisher) back into the survivorship-free universe

**Status:** accepted · **Date:** 2026-06-24 · **Source:** data audit 2026-06-24, finding F3

## Context
The survivorship-free universe includes delisted names only if a market cap can be computed for them. Dead-name shares were derived from screener fundamentals requiring positive EPS — but companies that went bankrupt were loss-makers at death and/or have no screener page, so they produced no shares → no market cap → were ABSENT from the universe. The audit found 81 dead names missing (78 with >₹50cr peak turnover), including the biggest blow-ups a survivorship-free backtest exists to capture: **DHFL, Bhushan Steel, Kingfisher Airlines, Educomp, Binani, Reliance Naval, Monnet Ispat, Future Consumer**. Their absence reintroduces exactly the optimistic survivorship bias the data layer is meant to remove.

## Decision
Seed researched **equity-shares-outstanding** anchors for 9 material dead loss-makers (`dead_share_seed` in `rebuild_pit_mcap_ca.py`), each a pre-NCLT/pre-resolution count from the company's annual report / exchange filings: DHFL & DEWANHOUS 31.4, EDUCOMP 12.0, BINANIIND 3.14, RNAVAL 73.76, MONNETISPA 6.37, BHUSANSTL 22.65, KFA 26.6, FCONSUMER 191.0 (crore shares). Market cap = `raw_bhavcopy_close × ca_factor × seeded_shares`, so each name rides its full decline from peak to delisting.

## Decision boundary (what we deliberately did NOT do)
Names with major share-count changes over their listed life — **3IINFOTECH** (19→161cr via repeated debt-to-equity), **ALOKTEXT** (Re-1 FV, ~1,358cr, revived by RIL), **IVRCLINFRA** (30→78cr), **AMTEKINDIA** (identity ambiguity Castex vs Metalyst) — are NOT seeded: a single constant anchor would be materially wrong for them. They are queued for a time-varying share-series follow-up. Renames-to-live-successors (e.g. NIITTECH→Coforge, SRTRANSFIN→Shriram Finance) and ETFs are correctly out of the dead-equity path.

## Verification
All 9 now in `pit_mcap_dead` + `universe_membership` with plausible caps (DHFL peak ₹21,328cr @ ₹679/sh, Bhushan Steel ₹48,730cr @ ₹2,151/sh, Kingfisher ₹2,351cr @ ₹88/sh); 0 previously-working dead names corrupted; the 4 dilution-heavy names confirmed not seeded.
