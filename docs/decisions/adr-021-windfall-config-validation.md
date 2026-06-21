# Server-side config validation — reject nonsensical strategies before any backtest or signal

*Status: accepted · 2026-06-21 · iter-31*

An AI QA pass showed the engine silently ran on garbage (inverted dates, 0 capital, 0% stop, negative max-weight, -1 hold days). Decision: validate StrategyConfig in pydantic so EVERY endpoint that builds it (backtest, signals, cost-sensitivity, sweep, readiness) rejects bad input with a clean human message; readiness fails soft with an 'invalid' verdict. No more signals from a broken config.
