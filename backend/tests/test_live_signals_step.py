"""iter-22 #209: live signals must cover every rebalance cadence the schema accepts.

_STEP is a second, hand-maintained list of the cadences in StrategyConfig.rebalance. It drifted:
`quarterly` was a legal schema value with no _STEP entry, so generate_signals() raised KeyError for
any quarterly strategy going live (96 of 289 stored strategies are quarterly). The backtest engine
handled quarterly fine, so nothing caught it. These pin the two together.
"""
from typing import get_args

import pytest

from windfall.signals_live.generate import _STEP
from windfall.strategy.schema import StrategyConfig


def _schema_cadences() -> set[str]:
    return set(get_args(StrategyConfig.model_fields["rebalance"].annotation))


def test_step_covers_every_schema_cadence():
    missing = _schema_cadences() - set(_STEP)
    assert not missing, (
        f"StrategyConfig.rebalance accepts {sorted(missing)} but _STEP has no entry — "
        f"generate_signals() will KeyError for those strategies")


def test_step_has_no_cadence_the_schema_rejects():
    extra = set(_STEP) - _schema_cadences()
    assert not extra, f"_STEP defines {sorted(extra)}, which StrategyConfig.rebalance will not accept"


@pytest.mark.parametrize("cadence", sorted(get_args(StrategyConfig.model_fields["rebalance"].annotation)))
def test_every_cadence_indexes_step(cadence):
    """The exact lookup generate_signals() performs (`_STEP[cfg.rebalance]`), for every legal value."""
    cfg = StrategyConfig(name="t", rebalance=cadence)
    assert _STEP[cfg.rebalance] >= 1


def test_step_is_monotonic_in_cadence_length():
    order = ["daily", "weekly", "fortnightly", "monthly", "quarterly"]
    steps = [_STEP[c] for c in order if c in _STEP]
    assert steps == sorted(steps), f"_STEP not increasing across {order}: {steps}"
