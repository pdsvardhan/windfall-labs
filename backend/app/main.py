"""FastAPI app — thin HTTP over the windfall engine.

Sync (`def`) handlers run in the threadpool so a long backtest never blocks the event loop.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from windfall import store_meta
from windfall.data import fundamentals as fund
from windfall.data import store
from windfall.jsonsafe import clean
from windfall.data.pipeline import incremental_update
from windfall.engine.backtest import run_backtest
from windfall.paper import commit_signal, list_positions, mark_to_market, scoreboard
from windfall.scripts_validation import run_validation
from windfall.signals_live import generate_signals
from windfall.signals_live.generate import signals_to_csv
from windfall.strategy.schema import StrategyConfig
from windfall.walkforward import sweep, walk_forward

app = FastAPI(title="Windfall Labs API", version="0.1.0")

# Lock CORS to the cockpit origin(s) so an arbitrary browser tab can't POST to this API.
# Override with WINDFALL_CORS_ORIGINS (comma-separated) if the cockpit moves.
_DEFAULT_ORIGINS = "http://192.168.1.10:8500,http://localhost:8500,http://127.0.0.1:8500"
_ALLOWED_ORIGINS = [o.strip() for o in
                    os.environ.get("WINDFALL_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ── request models ───────────────────────────────────────────────────────────
class StrategyIn(BaseModel):
    name: str
    config: dict
    id: str | None = None


class BacktestIn(BaseModel):
    config: dict
    strategy_id: str | None = None
    save: bool = True


class SweepIn(BaseModel):
    config: dict
    grid: dict = {}
    metric: str = "sharpe"


class WalkForwardIn(SweepIn):
    is_years: float = 3.0
    oos_years: float = 1.0


class SignalsIn(BaseModel):
    config: dict
    strategy_id: str | None = None
    save: bool = False


class CommitIn(BaseModel):
    strategy_id: str | None = None
    signal: dict
    capital_per_position: float = 15000.0


# ── health & data ────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "windfall-api"}


@app.get("/api/coverage")
def coverage():
    return store.coverage_summary()


@app.get("/api/data/status")
def data_status():
    cov = store.coverage_summary()
    fcov = fund.coverage()
    return {"coverage": cov, "n_universe": len(store.universe_tickers("niftytotalmarket")),
            "fundamentals": fcov, "feasibility": _feasibility(cov, fcov)}


@app.get("/api/fundamentals/status")
def fundamentals_status():
    return {"coverage": fund.coverage(), "snapshots": fund.snapshots(), "fields": fund.NUMERIC_FIELDS}


@app.post("/api/data/refresh")
def data_refresh(index: str = "nifty500"):
    return incremental_update(index)


def _feasibility(cov: dict, fcov: dict | None = None) -> list[dict]:
    have = (cov.get("n_tickers") or 0) > 0
    fcov = fcov or {}
    n_fund = fcov.get("tickers") or 0
    n_snap = fcov.get("snapshots") or 0
    return [
        {"need": "Daily adjusted OHLCV (~12yr)", "source": "yfinance",
         "status": "available" if have else "not-loaded",
         "detail": f"{cov.get('n_tickers',0)} tickers, {cov.get('date_min')}..{cov.get('date_max')}"},
        {"need": "Fundamentals + DVM scores (reporting-dated)", "source": "Trendlyne Pro",
         "status": "snapshot" if n_fund else "deferred",
         "detail": (f"{n_fund} stocks, {n_snap} snapshot(s), latest {fcov.get('latest')} — "
                    f"powers live DVM signals; backtest history builds as snapshots accumulate")
                   if n_fund else "DVM/fundamental strategies wait until this is sourced"},
        {"need": "Survivorship-free (delisted) history", "source": "NSE Bhavcopy",
         "status": "deferred", "detail": "v1 uses current membership; Bhavcopy is a later phase"},
        {"need": "Corporate actions", "source": "yfinance/NSE", "status": "partial",
         "detail": "adjusted prices used; explicit action log is a later phase"},
        {"need": "Point-in-time index membership", "source": "NSE", "status": "deferred",
         "detail": "current membership only in v1"},
    ]


# ── strategies ───────────────────────────────────────────────────────────────
@app.get("/api/strategies")
def strategies_list():
    return store_meta.list_strategies()


@app.post("/api/strategies")
def strategies_create(body: StrategyIn):
    StrategyConfig(**body.config)  # validate
    sid = store_meta.save_strategy(body.name, body.config, body.id)
    return store_meta.get_strategy(sid)


@app.get("/api/strategies/{sid}")
def strategies_get(sid: str):
    s = store_meta.get_strategy(sid)
    if not s:
        raise HTTPException(404, "strategy not found")
    return s


@app.delete("/api/strategies/{sid}")
def strategies_delete(sid: str):
    store_meta.delete_strategy(sid)
    return {"deleted": sid}


# ── backtests ────────────────────────────────────────────────────────────────
@app.post("/api/backtests")
def backtests_run(body: BacktestIn):
    try:
        res = run_backtest(body.config)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"backtest failed: {exc}")
    d = clean(res.model_dump())
    if body.save:
        d["backtest_id"] = store_meta.save_backtest(d, body.strategy_id)
    return d


@app.get("/api/backtests")
def backtests_list(strategy_id: str | None = None):
    return store_meta.list_backtests(strategy_id)


@app.get("/api/backtests/{bid}")
def backtests_get(bid: str):
    d = store_meta.get_backtest(bid)
    if not d:
        raise HTTPException(404, "backtest not found")
    return clean(d)


# ── sweep / walk-forward ─────────────────────────────────────────────────────
@app.post("/api/sweep")
def sweep_run(body: SweepIn):
    return clean(sweep(body.config, body.grid, metric=body.metric))


@app.post("/api/walkforward")
def walkforward_run(body: WalkForwardIn):
    return clean(walk_forward(body.config, body.grid, metric=body.metric,
                              is_years=body.is_years, oos_years=body.oos_years))


# ── signals ──────────────────────────────────────────────────────────────────
@app.post("/api/signals")
def signals_run(body: SignalsIn):
    out = clean(generate_signals(body.config))
    if body.save:
        out["signal_run_id"] = store_meta.save_signal_run(
            body.strategy_id, out.get("as_of"), out.get("signals", []))
    return out


@app.post("/api/signals/export")
def signals_export(body: SignalsIn):
    out = generate_signals(body.config)
    csv_text = signals_to_csv(out)
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="signals_{out.get("as_of")}.csv"'})


@app.get("/api/signals/runs")
def signals_runs():
    return store_meta.list_signal_runs()


@app.get("/api/signals/runs/{rid}")
def signals_run_get(rid: str):
    r = store_meta.get_signal_run(rid)
    if not r:
        raise HTTPException(404, "signal run not found")
    return r


# ── paper trades ─────────────────────────────────────────────────────────────
@app.post("/api/paper/commit")
def paper_commit(body: CommitIn):
    try:
        pid = commit_signal(body.strategy_id, body.signal, body.capital_per_position)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"position_id": pid}


@app.post("/api/paper/mark")
def paper_mark():
    return clean({"mark": mark_to_market(), "scoreboard": scoreboard()})


@app.get("/api/paper/positions")
def paper_positions(strategy_id: str | None = None, status: str | None = None):
    return clean(list_positions(strategy_id, status))


@app.get("/api/paper/scoreboard")
def paper_scoreboard():
    return clean(scoreboard())


# ── validation ───────────────────────────────────────────────────────────────
@app.get("/api/validate")
def validate():
    return run_validation()
