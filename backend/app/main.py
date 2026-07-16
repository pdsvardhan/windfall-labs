"""FastAPI app — thin HTTP over the windfall engine.

Sync (`def`) handlers run in the threadpool so a long backtest never blocks the event loop.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from windfall import store_meta
from windfall.data import fundamentals as fund
from windfall.data import store
from windfall.data import surveillance
from windfall.data import trendlyne_store as ts
from windfall.jsonsafe import clean
from windfall.data.pipeline import incremental_update
from windfall.engine.backtest import run_backtest, resolve_with_warmup
from windfall.engine.rotation import run_rotation
from windfall.paper import (
    commit_signal, delete_positions, list_positions, mark_to_market, rebalance_paper, scoreboard,
)
from windfall.scripts_validation import run_validation
from windfall.signals_live import generate_blend_signals, generate_signals
from windfall.signals_live.generate import signals_to_csv
from windfall.strategy.readiness import data_readiness
from windfall.strategy.schema import StrategyConfig
from windfall.walkforward import sweep, walk_forward

def _cfg_error(exc: Exception) -> str:
    """Flatten a pydantic ValidationError to a short human message (else the raw error)."""
    if isinstance(exc, ValidationError):
        return "; ".join(e.get("msg", "").replace("Value error, ", "") for e in exc.errors()) or str(exc)
    return str(exc)


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


class BatchIn(BaseModel):
    # Resolve per distinct stop-panel combo, simulate the whole grid off each.
    # Grid keys are ENFORCED against _SAFE_GRID_KEYS/_SAFE_GRID_PREFIXES (verified pure-sim-side;
    # they share one ResolvedStrategy, ~10x faster than N independent backtests).
    # `stop_loss.type` + `stop_loss.atr_period` are handled: they decide whether resolve() builds
    # the ATR panel, so combos are grouped by `_resolve_key` and each group resolves once.
    # Anything else — rank_by / rank_blend / universe.* / entry_filters / start / end / benchmark /
    # data_source / regime_filter.* (its MA warmup pad is sized at resolve from
    # regime_filter.enabled: gridding it on measured ~0.229 CAGR where a direct resolve gives
    # ~0.235, iter-22) — changes what resolve() produces and is refused with 400 (#219): the
    # resolve-once optimisation would silently reuse the base's panels and label the results as
    # varied. Use separate /api/backtests calls for those.
    base_config: dict
    grid: dict = {}            # e.g. {"n_holdings":[10,20], "rebalance":["monthly","quarterly"]}
    name_template: str = ""    # e.g. "MOM_roc126_{rebalance}_{n_holdings}"; falls back to base name
    save: bool = True


class WalkForwardIn(SweepIn):
    is_years: float = 3.0
    oos_years: float = 1.0


class CostSensitivityIn(BaseModel):
    config: dict
    multipliers: list[float] = [0.0, 1.0, 2.0]


class CompareIn(BaseModel):
    config_a: dict
    config_b: dict


class RotationIn(BaseModel):
    # Fund-of-funds rotation across self-timed sleeves + cash (the user's 2-3-strategies plan).
    sleeves: list[dict]                 # each is a full StrategyConfig (ideally with factor_timing)
    rebalance: str = "monthly"
    lookback_days: int = 63             # trailing-return window used to rank sleeves (~3 months)
    top_k: int | None = None           # max sleeves held at once (None = all that clear the floor)
    momentum_floor: float = 0.0        # a sleeve must beat this trailing return to be "working"
    switch_cost_bps: float = 20.0      # conservative fund-level switch cost on reallocation
    capital: float = 1_000_000.0
    benchmark: str = "NIFTY500"
    name: str = "rotation"
    weights: list[float] | None = None  # fixed-weight static blend (e.g. [0.7,0.3]); None = rotate


class SignalsIn(BaseModel):
    config: dict
    strategy_id: str | None = None
    save: bool = False


class BlendSignalsIn(BaseModel):
    # Live today's-orders for a fixed-weight blend (the adr-035 70/30 deployable candidate).
    sleeves: list[dict]                 # each a full StrategyConfig
    weights: list[float]               # one per sleeve, e.g. [0.7, 0.3]
    name: str = "blend"
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
            "fundamentals": fcov, "feasibility": _feasibility(cov, fcov),
            # The survivorship-free Trendlyne layer is what backtests actually use; surface its real
            # counts so the Reference page stops reporting the legacy yfinance store (755/1505).
            "trendlyne": ts.coverage() if ts.available() else {"available": False}}


@app.get("/api/fundamentals/status")
def fundamentals_status():
    return {"coverage": fund.coverage(), "snapshots": fund.snapshots(), "fields": fund.NUMERIC_FIELDS}


@app.post("/api/data/refresh")
def data_refresh(index: str = "nifty500"):
    return incremental_update(index)


@app.post("/api/surveillance/refresh")
def surveillance_refresh():
    """Fetch the current NSE ASM/GSM lists and store a dated snapshot (in-process — ONE DOOR safe)."""
    try:
        rows = surveillance.fetch_asm_gsm()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"NSE surveillance fetch failed: {exc}")
    return surveillance.ingest(rows)


@app.get("/api/surveillance")
def surveillance_list():
    return surveillance.latest_flags()


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


@app.post("/api/strategies/readiness")
def strategies_readiness(body: BacktestIn):
    """Tell the owner whether a strategy can be backtested (and from when) before they run it.
    On an invalid config, fail soft with an 'invalid' verdict the builder can render inline."""
    try:
        return data_readiness(body.config)
    except ValidationError as exc:
        return {"verdict": "invalid", "backtestable_from": None,
                "summary": "Fix before running — " + _cfg_error(exc),
                "unknown_features": [], "features": []}


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
        raise HTTPException(400, f"backtest failed: {_cfg_error(exc)}")
    d = clean(res.model_dump())
    d["readiness"] = data_readiness(body.config)  # so the UI can flag live-only / partial runs
    if body.save:
        d["backtest_id"] = store_meta.save_backtest(d, body.strategy_id)
    return d


# Grid keys verified to be read only by the SIMULATION (backtest.py: "n_holdings / rebalance /
# regime / exits / costs all live in the simulation") — with the regime exception below. Everything
# resolve() or _warmup_calendar_days() reads from config is excluded: data_source, start/end,
# benchmark, universe.*, entry_filters, rank_by/rank_blend, and regime_filter.* (the regime
# MULTIPLIER is sim-side, but its MA warmup pad is sized at resolve from regime_filter.enabled +
# ma_period, so a regime grid off a non-regime base runs with a cold MA — measured 0.2289 vs
# 0.2350 CAGR, iter-22). stop_loss./take_profit. are prefix-allowed: TakeProfit is pct/r_multiple
# (no panel), and stop_loss.type/atr_period get their own resolve via _resolve_key grouping.
_SAFE_GRID_KEYS = {"n_holdings", "rebalance", "weighting", "rank_order", "invest_fully",
                   "capital", "entry_fill", "max_hold_days", "max_position_adtv_pct", "sector_cap"}
_SAFE_GRID_PREFIXES = ("stop_loss.", "take_profit.")


def _unsafe_grid_keys(keys) -> list[str]:
    return sorted(k for k in keys
                  if k not in _SAFE_GRID_KEYS
                  and not any(k.startswith(p) for p in _SAFE_GRID_PREFIXES))


def _resolve_key(cfg: dict) -> tuple:
    """The config values that change what resolve() BUILDS, as opposed to what the sim reads.

    resolve() constructs the ATR stop panel only when the config handed to it already asks for an
    atr/trailing stop, and sizes it by atr_period. Two configs differing in either therefore need
    their own ResolvedStrategy; everything else in a batch grid is sim-side and can share one.
    `pct` and `none` need no panel, so they collapse to the same key.
    """
    sl = cfg.get("stop_loss") or {}
    needs_atr = sl.get("type") in ("atr", "trailing")
    return (sl.get("type") if needs_atr else "no-atr-panel",
            sl.get("atr_period") if needs_atr else None)


def _inert_stop(cfg: dict) -> str | None:
    """Why this config's stop can never fire, or None if it can.

    StopLoss.mult and .value both default to None and the schema only rejects non-positive values,
    so `{"type": "trailing"}` with no mult VALIDATES and then silently never arms — _stop_target
    and check_exit both gate on `and cfg.stop_loss.mult` / `and sl.value`, and None is falsy. A grid
    that asks for such a stop cannot be honoured, and returning the no-stop numbers under a stop
    label is precisely the defect this endpoint had (iter-22 #210). Callers get an error instead.

    `type: none` is NOT inert-by-mistake — it honestly says "no stop" and honestly returns no stop.
    """
    sl = cfg.get("stop_loss") or {}
    t = sl.get("type", "none")
    if t == "pct" and not sl.get("value"):
        return "stop_loss.type is 'pct' but stop_loss.value is unset"
    if t in ("atr", "trailing") and not sl.get("mult"):
        return f"stop_loss.type is '{t}' but stop_loss.mult is unset"
    return None


@app.post("/api/backtests/batch")
def backtests_batch(body: BatchIn):
    """Simulate a strategy grid, resolving once per distinct stop-panel combo.

    Sim-side grid params share a single ResolvedStrategy (~10x faster than N independent backtests,
    byte-identical). `stop_loss.type` / `stop_loss.atr_period` decide whether resolve() builds the
    ATR panel at all, so combos are grouped by `_resolve_key` and each group resolves once. Sharing
    the base `rs` across those silently simulated the BASE config's stop — a trailing sweep off a
    no-stop base returned no-stop numbers under a trailing label (iter-22 #210).

    Grid keys outside the verified sim-side allowlist are refused with 400 (#219): an API consumer
    cannot read a docstring, and a grid on e.g. rank_by or regime_filter.enabled would silently
    reuse the base's panels and label the results as though the parameter had varied.
    """
    import copy as _copy
    import itertools as _it
    # Refuse resolve-affecting grid keys BEFORE paying for the base resolve (#219).
    if bad := _unsafe_grid_keys(body.grid.keys()):
        raise HTTPException(400, (
            f"grid key(s) {bad} change what resolve() builds (or are unverified for batch), so the "
            f"batch resolve-once optimisation would silently reuse the base config's panels and "
            f"label the results as varied (#219). Safe grid keys: "
            f"{sorted(_SAFE_GRID_KEYS)} + prefixes {list(_SAFE_GRID_PREFIXES)}. "
            f"Run resolve-affecting parameters as separate /api/backtests calls."))
    try:
        base = StrategyConfig(**body.base_config).model_dump()
    except ValidationError as exc:
        raise HTTPException(400, f"invalid base_config: {_cfg_error(exc)}")
    try:
        base_rs = resolve_with_warmup(StrategyConfig(**base))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"resolve failed: {_cfg_error(exc)}")
    rs_cache = {_resolve_key(base): base_rs}

    keys = list(body.grid.keys())
    combos = ([dict(zip(keys, c)) for c in _it.product(*[body.grid[k] for k in keys])]
              if keys else [{}])

    def apply(over: dict) -> dict:
        cfg = _copy.deepcopy(base)
        for path, val in over.items():           # dotted-path overrides, e.g. "stop_loss.mult"
            node = cfg
            parts = path.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = val
        return cfg

    results = []
    for over in combos:
        cfg = apply(over)
        name = body.name_template.format(**over) if body.name_template else cfg.get("name")
        if name:
            cfg["name"] = name
        # Refuse a stop that cannot arm BEFORE paying for its resolve: returning no-stop numbers
        # under a stop label is the defect, and a silent one is worse than a loud failure.
        if (why := _inert_stop(cfg)) and any(k.startswith("stop_loss.") for k in over):
            results.append({"name": name, "overrides": over,
                            "error": f"grid asks for a stop that can never fire: {why} — set it on "
                                     f"base_config or in the grid. Refusing to return no-stop "
                                     f"numbers under a stop label."})
            continue
        rkey = _resolve_key(cfg)
        if rkey not in rs_cache:                 # this combo needs a panel the base never built
            try:
                rs_cache[rkey] = resolve_with_warmup(StrategyConfig(**cfg))
            except Exception as exc:  # noqa: BLE001
                results.append({"name": name, "overrides": over,
                                "error": f"resolve failed: {_cfg_error(exc)}"})
                continue
        try:
            res = run_backtest(cfg, rs=rs_cache[rkey])
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "overrides": over, "error": _cfg_error(exc)})
            continue
        d = clean(res.model_dump())
        warns = list(d.get("warnings", []))
        # type='none' is honest — it says no stop and returns no stop — but sweeping stop_loss.*
        # around it still yields N identical rows under N labels. Say so.
        if (any(k.startswith("stop_loss.") for k in over)
                and (cfg.get("stop_loss") or {}).get("type", "none") == "none"):
            warns.append("stop_loss.* varied in the grid but stop_loss.type is 'none' — no stop was "
                         "simulated for this combo; set stop_loss.type to pct/atr/trailing.")
        if body.save and name:
            store_meta.save_strategy(name, cfg, name)
            d["backtest_id"] = store_meta.save_backtest(d, name)
        results.append({"name": name, "overrides": over,
                        "summary": d.get("summary"), "warnings": warns})
    return clean({"n": len(results), "n_resolves": len(rs_cache), "results": results})


@app.get("/api/backtests")
def backtests_list(strategy_id: str | None = None, limit: int | None = None, offset: int = 0):
    # limit omitted → prior behavior (global capped at 200, per-strategy uncapped); limit=0 → no cap;
    # limit>0 with offset → pagination (audit #97).
    return store_meta.list_backtests(strategy_id, limit=limit, offset=offset)


@app.get("/api/backtests/{bid}")
def backtests_get(bid: str):
    d = store_meta.get_backtest(bid)
    if not d:
        raise HTTPException(404, "backtest not found")
    return clean(d)


# Summary metrics where the modelled costs + turnover actually show up (Build-Spec rail #1).
_COST_METRICS = ("cagr", "total_return", "sharpe", "sortino", "max_drawdown",
                 "annual_turnover", "n_trades", "exposure", "active_return")


@app.post("/api/backtests/cost-sensitivity")
def backtests_cost_sensitivity(body: CostSensitivityIn):
    """Run one strategy at several cost multipliers (default 0x/1x/2x) so realism-vs-optimism is
    explicit: how much net CAGR / Sharpe / return the modelled costs + turnover give back."""
    try:
        base = StrategyConfig(**body.config)  # validate
    except ValidationError as exc:
        raise HTTPException(400, f"invalid config: {_cfg_error(exc)}")
    runs = []
    for m in body.multipliers:
        try:
            res = run_backtest(body.config, cost_mult=m)  # engine scales the NSE delivery costs
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"cost-sensitivity run (x{m}) failed: {_cfg_error(exc)}")
        s = res.summary.model_dump()
        runs.append({"cost_multiplier": m, "summary": {k: s.get(k) for k in _COST_METRICS}})
    return clean({"name": base.name, "multipliers": body.multipliers, "runs": runs})


@app.post("/api/backtests/compare")
def backtests_compare(body: CompareIn):
    """A/B two strategy configs over their windows: side-by-side summary metrics + equity curves."""
    def one(cfg: dict) -> dict:
        d = run_backtest(cfg).model_dump()
        return {k: d[k] for k in ("name", "period", "summary", "equity_curve",
                                  "benchmark_curve", "warnings")}
    try:
        return clean({"a": one(body.config_a), "b": one(body.config_b)})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"compare failed: {exc}")


# ── sweep / walk-forward ─────────────────────────────────────────────────────
@app.post("/api/sweep")
def sweep_run(body: SweepIn):
    try:
        return clean(sweep(body.config, body.grid, metric=body.metric))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"sweep failed: {_cfg_error(exc)}")


@app.post("/api/walkforward")
def walkforward_run(body: WalkForwardIn):
    try:
        return clean(walk_forward(body.config, body.grid, metric=body.metric,
                                  is_years=body.is_years, oos_years=body.oos_years))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"walk-forward failed: {_cfg_error(exc)}")


@app.post("/api/rotation")
def rotation_run(body: RotationIn):
    """Backtest the user's multi-sleeve plan. Trailing-return rotation (rotate to whichever sleeve is
    working, cash when none are) by default; pass `weights` for a FIXED-WEIGHT static blend (e.g.
    [0.7,0.3] = 70/30, rebalanced monthly with real switch costs — the adr-035 deployable candidate)."""
    try:
        return clean(run_rotation(
            body.sleeves, rebalance=body.rebalance, lookback_days=body.lookback_days,
            top_k=body.top_k, momentum_floor=body.momentum_floor,
            switch_cost_bps=body.switch_cost_bps, capital=body.capital,
            benchmark=body.benchmark, name=body.name, weights=body.weights))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"rotation failed: {_cfg_error(exc)}")


# ── signals ──────────────────────────────────────────────────────────────────
@app.post("/api/signals")
def signals_run(body: SignalsIn):
    try:
        out = surveillance.annotate_signals(clean(generate_signals(body.config)))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"signals failed: {_cfg_error(exc)}")
    if body.save:
        out["signal_run_id"] = store_meta.save_signal_run(
            body.strategy_id, out.get("as_of"), out.get("signals", []))
    return out


@app.post("/api/signals/export")
def signals_export(body: SignalsIn):
    # Annotate with ASM/GSM surveillance flags first (same as /api/signals) so the exported
    # order-prep CSV carries the flag — a buy into a surveilled name must be visible on the sheet.
    out = surveillance.annotate_signals(generate_signals(body.config))
    csv_text = signals_to_csv(out)
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="signals_{out.get("as_of")}.csv"'})


@app.post("/api/signals/blend")
def signals_blend(body: BlendSignalsIn):
    """Today's combined orders for a fixed-weight blend (adr-035 70/30 MOM/LV): one buy/hold/sell
    sheet across the sleeves, with sleeve provenance + ASM/GSM surveillance flags."""
    try:
        out = surveillance.annotate_signals(
            clean(generate_blend_signals(body.sleeves, body.weights, name=body.name)))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"blend signals failed: {_cfg_error(exc)}")
    if body.save:
        out["signal_run_id"] = store_meta.save_signal_run(
            body.name, out.get("as_of"), out.get("signals", []))
    return out


@app.post("/api/signals/blend/export")
def signals_blend_export(body: BlendSignalsIn):
    out = surveillance.annotate_signals(generate_blend_signals(body.sleeves, body.weights, name=body.name))
    csv_text = signals_to_csv(out)
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="signals_blend_{out.get("as_of")}.csv"'})


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


@app.post("/api/paper/rebalance")
def paper_rebalance():
    """Monthly rebalance: sync every tracked paper strategy to its current target book."""
    return clean(rebalance_paper())


class PurgeIn(BaseModel):
    strategy_id: str


@app.post("/api/paper/purge")
def paper_purge(body: PurgeIn):
    """Hard-delete every paper position for a strategy_id (e.g. a stale test book)."""
    return {"deleted": delete_positions(body.strategy_id)}


# ── validation ───────────────────────────────────────────────────────────────
@app.get("/api/validate")
def validate():
    return run_validation()
