"""Strategy config contract: round-trip, deterministic hash, example loads & resolves."""
import json
from pathlib import Path

from windfall.strategy import StrategyConfig, config_hash, resolve


def test_round_trip_lossless():
    cfg = StrategyConfig(name="t", n_holdings=12, entry_filters=["close > sma50"])
    again = StrategyConfig(**json.loads(cfg.model_dump_json()))
    assert again.model_dump() == cfg.model_dump()


def test_hash_is_deterministic_and_sensitive():
    a = StrategyConfig(name="a", n_holdings=10)
    b = StrategyConfig(name="a", n_holdings=10)
    c = StrategyConfig(name="a", n_holdings=11)
    assert config_hash(a) == config_hash(b)
    assert config_hash(a) != config_hash(c)


def test_example_breakout_config_loads_and_resolves():
    path = Path(__file__).resolve().parents[1] / "strategies" / "breakout_validation.json"
    cfg = StrategyConfig(**json.loads(path.read_text()))
    rs = resolve(cfg)
    # Resolution produces aligned, same-shaped panels over the seeded synthetic universe.
    assert rs.entry_mask.shape == rs.rank_score.shape
    assert rs.entry_mask.shape[1] == len(rs.tickers)
    assert rs.close_adj.shape[0] > 0
