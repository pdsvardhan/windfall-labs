"""iter-22 #210, endpoint level: POST /api/backtests/batch must never return no-stop numbers
under a stop label.

The unit tests in test_batch_resolve_key.py pin _resolve_key/_inert_stop in isolation. They were
9/9 green while the ENDPOINT was still wrong for the canonical stored config — the iter-22 verifier
caught exactly that gap. These drive the handler itself.

resolve/run_backtest are stubbed: this asserts the endpoint's DISPATCH logic (how many resolves,
what config reaches the sim, what is refused), not the engine's numbers. The fake sim mirrors the
real arming gate (`and cfg.stop_loss.mult`), so an unarmed stop shows up here the same way it did
in production: as the no-stop number.

The handler is called directly rather than through fastapi's TestClient — TestClient needs httpx,
which is not a runtime dep, and the HTTP hop adds nothing: the dispatch logic under test is all in
backtests_batch itself.
"""
import pytest

import app.main as main
from app.main import BatchIn, backtests_batch


class _FakeRS:
    def __init__(self, cfg):
        sl = cfg.get("stop_loss") or {}
        self.has_atr_panel = sl.get("type") in ("atr", "trailing")


class _FakeRes:
    """Reports 0.06 when a stop genuinely armed, 0.34 (the no-stop number) when it did not."""

    def __init__(self, cfg, rs):
        sl = cfg.get("stop_loss") or {}
        armed = bool(
            (sl.get("type") in ("atr", "trailing") and sl.get("mult") and rs.has_atr_panel)
            or (sl.get("type") == "pct" and sl.get("value"))
        )
        self._d = {"summary": {"cagr": 0.06 if armed else 0.34, "stop_armed": armed},
                   "warnings": []}

    def model_dump(self):
        return self._d


class _Recorder:
    """Captures every config that reached resolve / the sim, so the dispatch can be asserted."""

    def __init__(self):
        self.resolved, self.simmed = [], []


@pytest.fixture
def client(monkeypatch):
    rec = _Recorder()

    def fake_resolve(cfg):
        d = cfg.model_dump() if hasattr(cfg, "model_dump") else cfg
        rec.resolved.append(d)
        return _FakeRS(d)

    def fake_run(cfg, rs=None):
        rec.simmed.append(cfg)
        return _FakeRes(cfg, rs)

    monkeypatch.setattr(main, "resolve_with_warmup", fake_resolve)
    monkeypatch.setattr(main, "run_backtest", fake_run)
    return rec


def _post(client, grid, stop=None):
    base = {"name": "t", "start": "2020-01-01", "stop_loss": stop or {"type": "none"}}
    return backtests_batch(BatchIn(base_config=base, grid=grid, save=False))


def _by_type(body):
    return {r["overrides"]["stop_loss.type"]: r for r in body["results"]}


# ── the regression the verifier caught ────────────────────────────────────────────────────────
def test_endpoint_refuses_unarmable_trailing(client):
    """#210's exact symptom: stored configs are {"type": "none"} with NO mult key, so a trailing
    grid off one silently returned the no-stop number under a trailing label."""
    body = _post(client, {"stop_loss.type": ["trailing"]})          # base has no mult
    res = body["results"][0]
    assert "error" in res, f"expected refusal, got {res.get('summary')}"
    assert "can never fire" in res["error"]
    assert "summary" not in res                                      # no numbers to misread


def test_endpoint_refuses_unarmable_pct(client):
    body = _post(client, {"stop_loss.type": ["pct"]})                # base has no value
    assert "error" in body["results"][0]


def test_refusal_costs_no_resolve(client):
    """An unarmable combo must be rejected before paying for its ATR panel."""
    _post(client, {"stop_loss.type": ["trailing"]})
    assert all((c.get("stop_loss") or {}).get("type") != "trailing" for c in client.resolved)


def test_armed_trailing_grid_actually_simulates_the_stop(client):
    body = _post(client, {"stop_loss.type": ["none", "trailing"], "stop_loss.mult": [3.0]})
    rows = _by_type(body)
    assert rows["trailing"]["summary"]["stop_armed"] is True
    assert rows["none"]["summary"]["stop_armed"] is False
    assert rows["trailing"]["summary"]["cagr"] != rows["none"]["summary"]["cagr"], \
        "trailing returned the no-stop number — #210 has regressed"


def test_armed_trailing_gets_its_own_resolve_with_a_panel(client):
    _post(client, {"stop_loss.type": ["none", "trailing"], "stop_loss.mult": [3.0]})
    assert any((c.get("stop_loss") or {}).get("type") == "trailing" for c in client.resolved), \
        "no resolve ever saw a trailing config — the ATR panel was never built"


def test_n_resolves_reports_two_for_a_type_sweep(client):
    body = _post(client, {"stop_loss.type": ["none", "trailing"], "stop_loss.mult": [3.0]})
    assert body["n_resolves"] == 2


def test_sim_side_sweep_still_resolves_once(client):
    """The optimisation must survive: width-only off an armed trailing base is one resolve."""
    body = _post(client, {"stop_loss.mult": [2.0, 3.0, 4.0]},
                 stop={"type": "trailing", "mult": 2.0, "atr_period": 14})
    assert body["n_resolves"] == 1
    assert len(body["results"]) == 3
    assert all(r["summary"]["stop_armed"] for r in body["results"])


def test_type_none_is_warned_not_refused(client):
    """'none' is honest — it must still run, but a stop_loss.* sweep around it yields identical
    rows under different labels, so it must say so."""
    body = _post(client, {"stop_loss.mult": [2.0, 3.0]})
    assert all("error" not in r for r in body["results"])
    assert all(any("stop_loss.type is 'none'" in w for w in r["warnings"])
               for r in body["results"])


def test_no_grid_request_is_untouched(client):
    body = _post(client, {})
    assert body["n"] == 1 and body["n_resolves"] == 1
    assert "error" not in body["results"][0]
