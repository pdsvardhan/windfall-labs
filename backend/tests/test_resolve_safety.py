"""Security regression: the strategy expression evaluator must not allow code execution."""
import numpy as np
import pandas as pd
import pytest

from windfall.strategy.resolve import resolve
from windfall.strategy.safe_eval import SafeEvalError, feature_names, safe_eval


def _ns():
    df = pd.DataFrame(np.arange(20, dtype=float).reshape(10, 2), columns=["AAA.NS", "BBB.NS"])
    return {"close": df, "sma50": df - 1, "rsi14": df}


def test_safe_eval_allows_comparison_and_arithmetic():
    ns = _ns()
    out = safe_eval("close > sma50", ns)
    assert bool(out.values.all())  # close is always sma50+1 here
    out2 = safe_eval("50 < rsi14", ns)  # chained/scalar compare works
    assert out2.shape == ns["close"].shape


def test_safe_eval_rejects_attribute_access_the_rce_vector():
    ns = _ns()
    payload = "close.__class__.__init__.__globals__['__builtins__']['__import__']('os')"
    with pytest.raises(SafeEvalError):
        safe_eval(payload, ns)


def test_safe_eval_rejects_calls_subscripts_and_and_or():
    ns = _ns()
    for bad in ["__import__('os')", "close[0]", "close > 1 and sma50 > 1", "open('x')"]:
        with pytest.raises(SafeEvalError):
            safe_eval(bad, ns)


def test_safe_eval_rejects_unknown_names():
    with pytest.raises(SafeEvalError):
        safe_eval("mystery_token > 1", _ns())


def test_feature_names_extracts_identifiers():
    assert set(feature_names("close > sma50")) == {"close", "sma50"}


def test_resolve_skips_malicious_filter_without_executing(seeded_db):
    from windfall.strategy.schema import StrategyConfig
    payload = "close.__class__.__init__.__globals__['__builtins__']['__import__']('os').getpid() > 0"
    cfg = StrategyConfig(name="evil", entry_filters=[payload], rank_by="roc21",
                         start="2018-06-01", end="2020-12-31")
    rs = resolve(cfg)
    # The malicious filter is rejected (recorded as a warning) and never executed.
    assert any("rejected expression" in w for w in rs.warnings)
