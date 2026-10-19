"""iter-197: paper replay mechanics, net-of-cost unitization, strategy delete cascade, as-of signals,
and the per-thread Trendlyne cursor.

The replay tests drive the PURE simulation core with hand-built price panels, so each paper rule is
pinned on its own: next-open fills, floor-share sizing, drop-out closes at the rebalance close,
stop exits at the stop level, granularity voids, weekend rebalances, and the cash guard.
"""
from __future__ import annotations

import datetime as dt
import threading

import numpy as np
import pandas as pd
import pytest

from windfall import store_meta
from windfall.engine.backtest import DP_FLAT, NSE_BUY_RATE, NSE_SELL_RATE
from windfall.paper import equity, replay

D = dt.date


def _panel(rows: dict[str, list[float]], start: str, periods: int) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=periods)
    return pd.DataFrame(rows, index=idx)


# ── rebalance calendar ───────────────────────────────────────────────────────

def test_monthly_book_started_29_jun_is_due_again_on_1_jul():
    """The daily cron compares periods, not elapsed time — a start on 29 Jun is due on 1 Jul."""
    days = replay.rebalance_days("monthly", D(2026, 6, 29), D(2026, 10, 19))
    assert days == [D(2026, 6, 29), D(2026, 7, 1), D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 1)]


def test_weekly_book_rebalances_on_each_new_iso_week():
    days = replay.rebalance_days("weekly", D(2026, 6, 29), D(2026, 7, 20))
    assert days == [D(2026, 6, 29), D(2026, 7, 6), D(2026, 7, 13), D(2026, 7, 20)]


# ── simulation core ──────────────────────────────────────────────────────────

def _sig(w, stop=None, target=None):
    return {"weight": w, "stop": stop, "target": target}


def test_entry_fills_at_the_next_open_not_the_signal_day():
    # Mon 29 Jun .. Fri 3 Jul
    opens = _panel({"AAA": [100, 101, 102, 103, 104]}, "2026-06-29", 5)
    closes = _panel({"AAA": [100.5, 101.5, 102.5, 103.5, 104.5]}, "2026-06-29", 5)
    b = replay.simulate_book("T", 10_000, "monthly", {D(2026, 6, 29): {"AAA": _sig(1.0)}},
                             opens, closes, D(2026, 6, 29), D(2026, 7, 3))
    (p,) = b.positions
    assert p.status == "open"
    assert p.entry_date == D(2026, 6, 30) and p.entry == 101          # Tuesday's OPEN
    assert p.shares == 99                                            # floor(10000 / 101)
    assert p.last_price == 104.5 and p.last_date == D(2026, 7, 3)


def test_drop_out_closes_at_the_rebalance_close_and_the_new_name_queues():
    opens = _panel({"AAA": [100, 100, 100, 110, 110], "BBB": [50, 50, 50, 50, 52]},
                   "2026-06-29", 5)
    closes = _panel({"AAA": [100, 100, 105, 110, 110], "BBB": [50, 50, 50, 50, 51]},
                    "2026-06-29", 5)
    targets = {D(2026, 6, 29): {"AAA": _sig(1.0)}, D(2026, 7, 1): {"BBB": _sig(1.0)}}
    b = replay.simulate_book("T", 10_000, "monthly", targets, opens, closes,
                             D(2026, 6, 29), D(2026, 7, 3))
    a = next(p for p in b.positions if p.ticker == "AAA")
    bb = next(p for p in b.positions if p.ticker == "BBB")
    assert a.status == "closed" and a.reason == "rebalance"
    assert a.exit == 105 and a.exit_date == D(2026, 7, 1)            # Wednesday's CLOSE
    assert bb.status == "open" and bb.entry_date == D(2026, 7, 2)     # Thursday's OPEN
    # Sized off cash net of costs actually paid: the AAA round trip, not the notional.
    cash = (10_000 - 100 * 100 * (1 + NSE_BUY_RATE)
            + 100 * 105 * (1 - NSE_SELL_RATE) - DP_FLAT)
    assert bb.planned_capital == pytest.approx(min(10_000, cash))
    assert [r["ran_at"] for r in b.runs] == [D(2026, 6, 29), D(2026, 7, 1)]


def test_stop_exits_at_the_stop_level_on_the_first_close_below_it():
    opens = _panel({"AAA": [100, 100, 99, 95, 90]}, "2026-06-29", 5)
    closes = _panel({"AAA": [100, 99, 96, 93, 91]}, "2026-06-29", 5)
    b = replay.simulate_book("T", 10_000, "monthly", {D(2026, 6, 29): {"AAA": _sig(1.0, stop=94)}},
                             opens, closes, D(2026, 6, 29), D(2026, 7, 3))
    (p,) = b.positions
    assert p.status == "closed" and p.reason == "stop"
    assert p.exit == 94 and p.exit_date == D(2026, 7, 2)
    assert p.return_pct == pytest.approx(94 / 100 - 1)


def test_a_slice_below_one_share_is_voided():
    opens = _panel({"BIG": [50_000, 50_000, 50_000]}, "2026-06-29", 3)
    closes = opens.copy()
    b = replay.simulate_book("T", 10_000, "monthly", {D(2026, 6, 29): {"BIG": _sig(1.0)}},
                             opens, closes, D(2026, 6, 29), D(2026, 7, 1))
    assert b.positions[0].status == "void" and b.positions[0].reason == "unfillable-granularity"


def test_a_saturday_rebalance_uses_fridays_close_and_fills_mondays_open():
    """1 Aug 2026 is a Saturday: the daily cron rebalances that night off Friday's bar."""
    opens = _panel({"AAA": [100] * 6, "BBB": [20, 20, 20, 20, 20, 21]}, "2026-07-27", 6)
    closes = _panel({"AAA": [100, 100, 100, 100, 99, 99], "BBB": [20] * 6}, "2026-07-27", 6)
    targets = {D(2026, 7, 27): {"AAA": _sig(1.0)}, D(2026, 8, 1): {"BBB": _sig(1.0)}}
    b = replay.simulate_book("T", 10_000, "monthly", targets, opens, closes,
                             D(2026, 7, 27), D(2026, 8, 3))
    a = next(p for p in b.positions if p.ticker == "AAA")
    bb = next(p for p in b.positions if p.ticker == "BBB")
    assert a.exit_date == D(2026, 7, 31) and a.exit == 99            # Friday close
    assert bb.entry_date == D(2026, 8, 3) and bb.entry == 21          # Monday open


def test_kept_names_are_not_retraded():
    opens = _panel({"AAA": [100, 100, 100, 100, 100]}, "2026-06-29", 5)
    closes = opens.copy()
    targets = {D(2026, 6, 29): {"AAA": _sig(1.0)}, D(2026, 7, 1): {"AAA": _sig(1.0)}}
    b = replay.simulate_book("T", 10_000, "monthly", targets, opens, closes,
                             D(2026, 6, 29), D(2026, 7, 3))
    assert len(b.positions) == 1 and b.positions[0].status == "open"
    assert b.runs[1]["closed"] == 0 and b.runs[1]["opened"] == 0


# ── net-of-cost unitization (item 1418) ──────────────────────────────────────

DATES = ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"]


def test_net_return_is_not_diluted_by_a_later_contribution(monkeypatch):
    """Era 1 on Rs1L makes +Rs1,000 gross and pays real costs; Rs4L arrives on day 2 and sits idle.

    The whole-history net return must equal era 1's net return on Rs1L. Before the fix the step-up
    issued net units at the GROSS price, so era 1's costs were spread over ~5x the units and the net
    return read too high — on the live books by 0.4-0.7 pts.
    """
    positions = [{
        "id": "p1", "strategy_id": "TNET", "ticker": "AAA", "status": "closed",
        "entry_date": DATES[0], "entry": 100.0, "shares": 100.0,
        "exit": 110.0, "exit_date": DATES[1], "last_price": 110.0, "last_date": DATES[1],
    }]
    panel = pd.DataFrame({"AAA": [100.0, 110.0, 110.0, 110.0, 110.0]}, index=pd.to_datetime(DATES))
    monkeypatch.setattr(equity, "list_positions", lambda *a, **k: positions)
    monkeypatch.setattr(equity.ts, "adjusted_close_panel", lambda *a, **k: panel)
    monkeypatch.setattr(equity, "_with_bhavcopy_fallback", lambda p, t, s: p)
    monkeypatch.setattr(equity.ts, "benchmark_series",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no benchmark")))
    monkeypatch.setattr(equity, "_notional_steps",
                        lambda sid, since: [(DATES[0], 100_000.0), (DATES[2], 500_000.0)])
    st = equity.book_equity()["books"]["TNET"]["stats"]
    costs = 10_000 * NSE_BUY_RATE + 11_000 * NSE_SELL_RATE + DP_FLAT
    assert st["gross_return"] == pytest.approx(1_000 / 100_000, abs=1e-6)
    assert st["net_return"] == pytest.approx((1_000 - costs) / 100_000, abs=1e-6)


# ── strategy delete cascade (item 1422) ──────────────────────────────────────

def test_deleting_a_strategy_deletes_its_backtests_and_only_its_own():
    keep = store_meta.save_strategy("keep-197", {"name": "keep"})
    gone = store_meta.save_strategy("gone-197", {"name": "gone"})
    store_meta.save_backtest({"name": "a", "summary": {}}, gone)
    store_meta.save_backtest({"name": "b", "summary": {}}, gone)
    store_meta.save_backtest({"name": "c", "summary": {}}, keep)
    assert store_meta.delete_strategy(gone) == 2
    assert store_meta.get_strategy(gone) is None
    assert store_meta.list_backtests(gone) == []
    assert len(store_meta.list_backtests(keep)) == 1
    store_meta.delete_strategy(keep)


# ── as-of signals ────────────────────────────────────────────────────────────

def test_generate_signals_as_of_reads_the_selection_from_that_bar():
    """The replay asks generate_signals for a past day; the book must come from that bar."""
    from windfall.signals_live.generate import generate_signals
    from windfall.strategy.resolve import ResolvedStrategy
    from windfall.strategy.schema import StrategyConfig

    n = 80
    idx = pd.bdate_range("2026-03-02", periods=n)
    px = pd.DataFrame({"AAA": np.linspace(100, 120, n), "BBB": np.linspace(100, 120, n)}, index=idx)
    rank = pd.DataFrame({"AAA": np.where(np.arange(n) < 70, 2.0, 1.0),
                         "BBB": np.where(np.arange(n) < 70, 1.0, 2.0)}, index=idx)
    cfg = StrategyConfig(name="asof", rank_by="roc21", n_holdings=1)
    rs = ResolvedStrategy(
        config=cfg, tickers=["AAA", "BBB"], entry_mask=px.notna(), rank_score=rank,
        open_adj=px, close_adj=px, high_adj=px * 1.01, low_adj=px * 0.99, atr_stop=None,
        ret_vol=px * 0, adtv_value=px * 1e9, sectors={}, benchmark=px["AAA"])
    on_65 = idx[65].date()
    assert [s["ticker"] for s in generate_signals(cfg, rs=rs)["signals"]
            if s["action"] != "sell"] == ["BBB"]
    past = generate_signals(cfg, as_of=on_65, rs=rs)
    assert past["as_of"] == str(on_65)
    assert [s["ticker"] for s in past["signals"] if s["action"] != "sell"] == ["AAA"]


# ── per-thread Trendlyne cursor (item 1420) ──────────────────────────────────

def test_concurrent_panels_do_not_clobber_each_other():
    """Eight threads reading price panels at once — the shape of the paper page's parallel loads.

    On one shared DuckDB connection a thread's pending result could be replaced by another
    thread's execute, and `.fetchdf()` came back None (the intermittent equity 500).
    """
    ts = pytest.importorskip("windfall.data.trendlyne_store")
    if not ts.available():
        pytest.skip("trendlyne.duckdb not present in this environment")
    syms = ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    shapes: list[tuple] = []

    def worker():
        barrier.wait()
        try:
            p = ts.adjusted_close_panel(syms, start="2026-08-01", extend_live=True)
            shapes.append(tuple(sorted(p.columns)))
        except BaseException as exc:  # noqa: BLE001 — collect, assert in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"{len(errors)} of {n} concurrent panel reads failed: {errors[0]!r}"
    assert len(set(shapes)) == 1 and len(shapes) == n
