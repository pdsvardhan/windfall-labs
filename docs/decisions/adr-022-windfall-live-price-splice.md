# Live signals splice the latest Bhavcopy EOD beyond the Trendlyne layer (read-only) + nightly cron

*Status: accepted · 2026-06-21 · iter-31*

The Trendlyne bulk layer is WAF-gated and lags; signals were as old as the last manual pull. Decision: for live signals only (end=None), read-only-splice the freshest NSE Bhavcopy bars past the last Trendlyne date so today's orders use the latest close we hold — no DB write, so adr-018 single-writer is respected; backtests untouched. New EOD is ingested by a nightly host cron (stop api -> bhavcopy ingest -> start api), never a UI button (the API holds bhavcopy read-only).
