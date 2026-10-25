# Free P/E vs Trendlyne's on equal terms (iteration 206, 2026-10-25)

Follow-up to `free-pe-2026-10-20.md` (to-do #969). Measurement only; the one change the iteration made to a
paper book is recorded in adr-052. Scripts: `backend/scripts/free_pe/` (`missing_names.py`, `pe_backtests.py`
with `EXCLUDE_FIN=1`); results: `data/free_pe.duckdb` table `pe_backtests_equal`. Not investment advice.

## What was unequal in iteration 201, and what changed

1. **Coverage.** The screener.in store held 1,474 companies, so the free P/E saw about half the universe. The
   825 non-bank companies that were ever in the Rs500cr universe and missing from it were fetched (same
   ingester, same self-check and yfinance cross-vote). Result: 490 high-confidence, 306 low-confidence, 15
   quarantined, 10 excluded as financials, 4 failed. The store now holds 2,295 companies (was 1,474).
   Non-bank universe coverage at four dates, free `pe` vs `tl_pe`:

   | date | non-bank universe | free `pe` | `tl_pe` |
   |---|---|---|---|
   | 2018-12 | 822 | 689 | 672 |
   | 2021-12 | 1,029 | 824 | 824 |
   | 2024-12 | 1,395 | 1,230 | 1,164 |
   | 2026-08 | 1,594 | 1,450 | 1,429 |

   The free P/E now sees as many non-bank companies as Trendlyne's does.
2. **Banks and NBFCs** (which the free P/E can never see) are excluded from every arm by sector label. The match
   is the substrings `bank` and `financ` on Trendlyne's sector label, which covers the whole "BANKING AND FINANCE"
   sector — insurers, brokers and asset managers too, so the exclusion is wider than "banks and NBFCs". Companies
   with no sector label (287 of 2,249 ever in the universe, among them dead banks such as ALBK and ANDHRABANK) are
   not excluded in any arm.
3. **Repeatability** (#967). Two sources of run-to-run difference were fixed, and every cell below was run
   twice: the two runs are identical to the decimal (range 0.0 in all 12 cells).

## Results

`CMP_valmom_m_20` (P/E ascending + 6-month momentum, top 20, monthly, same costs), banks/NBFCs out of every
arm. CAGR / Sharpe / max drawdown:

| window | as configured (no P/E needed) | Trendlyne P/E required | free P/E required | momentum only |
|---|---|---|---|---|
| 10 years 2016–26 | 23.0% / 0.93 / −65.4% | 15.0% / 0.66 / −72.4% | **18.2% / 0.79 / −73.1%** | 29.5% / 1.10 / −52.5% |
| post-COVID 5y | 16.3% / 0.72 / −35.8% | 16.1% / 0.70 / −34.6% | **16.6% / 0.75 / −36.9%** | 19.4% / 0.80 / −37.0% |
| pre-COVID 5y | 30.3% / 1.14 / −65.4% | 15.1% / 0.66 / −72.4% | **17.4% / 0.75 / −73.1%** | 38.5% / 1.34 / −53.1% |

Overlap of holdings with the momentum-only book, same rebalance days: as configured 14% / 9% / 20% (10y /
post / pre); Trendlyne P/E required 8% / 7% / 9%; free P/E required 6% / 5% / 7%. The two P/E-required books
share 34% / 32% / 37% of their holdings with each other (printed by `pe_backtests.py` in its run log; not stored
in the result table).

## What it shows

- **The iteration-201 headline reversed.** There the free P/E (required) made 23.5% / 22.2% / 22.4% and beat the
  as-configured book after COVID (22.2% vs 17.1%) and the momentum-only book (18.3%). On equal terms it makes
  18.2% / 16.6% / 17.4% and trails momentum-only in all three windows; the as-configured book is ahead of it over
  ten years and pre-COVID. Most of the earlier lead came from the unequal comparison (half the universe, banks
  on one side) and the repeatability bug (#967), not from the free P/E.
- **The free P/E is at least as good as Trendlyne's on equal terms.** It leads by 3.2 / 0.5 / 2.3 CAGR points
  (10y / post-COVID / pre-COVID) with a better Sharpe in all three windows, and a slightly worse maximum drawdown (−73.1% vs −72.4%, −36.9% vs
  −34.6%, −73.1% vs −72.4%). The iteration-201 gap (5.1 / 2.7 /
  6.0) was partly the coverage difference; between a fifth and two-thirds of it survives the fix. The
  post-COVID gap (0.5 points) is small. Each cell is one path (two identical runs of the same data, not two
  independent samples) and no significance test was run, so read it as "no worse", not "better"; the free P/E also
  uses restated EPS (see the caveats).
- **Requiring a P/E costs return in the early years and nothing since 2021.** Against the as-configured book,
  requiring Trendlyne's P/E gives up 8.0 points over ten years and 15.2 points before COVID, and 0.2 points
  after. The as-configured book's extra return is the 2020–21 stretch, as iteration 201 found.
- **The as-configured book is not a copy of the momentum book.** Its holdings overlap the momentum-only book by
  only 9–20%, so it is not momentum under another name. What it holds that a value book should not is companies with no positive P/E — loss-makers and recent
  listings — chosen on momentum alone.
- **Momentum alone still beats every value variant over ten years and pre-COVID**, and is ahead after COVID.
  Value + Momentum as a pair has not earned its slot on return; it is there for diversification and as the
  value sleeve the other books lack.

## Caveats that remain

- The free P/E uses screener.in's figures as restated today (EPS rebased for later splits; about 5 real
  restatements per 40 companies), which leaks later information into the past. Trendlyne's P/E has no such
  leak but exists only for companies it still lists. Neither bias is measured here.
- It is an annual P/E: EPS is known 120 days after the fiscal year ends, so up to 16 months stale. The
  trailing-twelve-month series from NSE filings (to-do #970, `docs/ops/nse-filings-ttm.md`) removes this.
- Low-confidence rows (306 of the 825 new companies, 620 in the whole store) are used as the store's own rules
  allow; they were not separated out in the backtest.
