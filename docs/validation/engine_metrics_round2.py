#!/usr/bin/env python3
"""Round-2 engine headline metrics — run each parity TEST_TABLE config through the REAL
engine (run_backtest: survivorship-free PIT basis, adr-020 cost model applied) to produce
the PERFORMANCE layer of the Session-2 parity revalidation. This complements parity_multi.py
(which compares GROSS selection/pricing vs Trendlyne); here we report what OUR platform
actually shows for each strategy, WITH costs, for comparison to Trendlyne's reported metrics.

Windows are taken from the owner's Trendlyne result screenshots (the CSV/screenshot gold).
Floor is injected as an `mcap > <floor>` entry filter when the config has no explicit mcap
filter, mirroring the parity harness's universe floor. max_weight = 1/nhold (equal-weight,
fully invested across the held slots — matches Trendlyne's fixed-slot book).

Output (one machine-readable line per test):
  ENG|<tid>|cagr=..|tot=..|maxdd=..|sharpe=..|turn=..|ntr=..|win=..|benchcagr=..|ddwin=..
"""
import importlib.util, sys
from windfall.strategy.schema import StrategyConfig
from windfall.engine.backtest import run_backtest

COST_MULT = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
TAG = f"ENG{int(round(COST_MULT*100))}"  # ENG100 = net (full costs); ENG0 = gross (costless)

spec = importlib.util.spec_from_file_location(
    "pm", "/mnt/storage/websites/windfall-labs/docs/validation/parity_multi.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

# windows from owner Trendlyne screenshots (start, end)
WINDOWS = {
    "548012": ("2021-07-15", "2026-06-12"), "548776": ("2021-07-15", "2026-06-12"),
    "548042": ("2025-06-01", "2026-06-12"), "548040": ("2025-06-01", "2026-06-12"),
    "548017": ("2021-07-15", "2026-06-12"), "548015": ("2021-07-15", "2026-06-12"),
    "548014": ("2021-07-15", "2026-06-12"), "547990": ("2025-06-01", "2026-06-12"),
    "547989": ("2025-06-01", "2026-06-12"), "547991": ("2021-07-31", "2026-06-12"),
    "547992": ("2013-03-01", "2026-06-12"), "547994": ("2025-06-01", "2026-06-12"),
    "547995": ("2021-07-15", "2026-06-12"),
}

for tid, (start, end) in WINDOWS.items():
    t = pm.TEST_TABLE[tid]
    entry = list(t["entry"])
    if not any(f.replace(" ", "").startswith("mcap>") for f in entry):
        entry = [f"mcap > {t['floor']:.0f}"] + entry
    try:
        cfg = StrategyConfig(
            name=tid, data_source="trendlyne", entry_filters=entry,
            rank_by=t["rank_by"], rank_order=t["rank_order"], n_holdings=t["nhold"],
            weighting="equal", max_weight_per_stock=round(1.0 / t["nhold"], 4),
            max_position_adtv_pct=1e9, rebalance=t["freq"], entry_fill="close",
            start=start, end=end, benchmark="NIFTY500")
        s = run_backtest(cfg, cost_mult=COST_MULT).summary
        ddwin = "-".join(s.max_dd_dates) if s.max_dd_dates else ""
        print(f"{TAG}|{tid}|cagr={s.cagr*100:.1f}|tot={s.total_return*100:.1f}|"
              f"maxdd={s.max_drawdown*100:.1f}|sharpe={s.sharpe}|turn={s.annual_turnover*100:.0f}|"
              f"ntr={s.n_trades}|win={s.win_rate*100:.0f}|benchcagr={s.benchmark_cagr*100:.1f}|"
              f"ddwin={ddwin}", flush=True)
    except Exception as e:
        import traceback
        print(f"{TAG}|{tid}|FAILED|{e}", flush=True)
        traceback.print_exc()
