# adr-051 — A paper book that ranks on Trendlyne scores holds, rather than trades, when those scores are over 7 days old

- **Status:** accepted
- **Date:** 2026-10-20
- **Tags:** curated, cat:reliability
- **Iteration:** iter-202 (Ottomate iteration 202, to-dos #953, #954)

## Context

Trendlyne's D/V/M scores and its P/E, PEG and P/B history reach the server only through a
browser harvest the owner runs (the endpoints are WAF-protected). When nobody runs it, the
factor tables freeze while prices keep moving. adr-045 made that visible — a signal carries a
`stale factor:` warning past 14 days — but nothing acted on it. The 1-Aug and 1-Sep 2026
rebalances ranked on a 22-July book, and by 20 October the scores were 46 days old (last
published 2026-09-04) with five of the eight paper books ranking on them — the four DVM books
and Value + Momentum (P/E). A book
that rebalances on scores that old is not running the strategy it names, and its record says it
is.

## Decision

1. **Hold, then alert (owner, 2026-10-20).** On a due rebalance, a book whose ranking, blend or
   filters use a Trendlyne factor is held when the newest published data for that factor family
   (D/V/M → `dvm_history`; P/E, PEG, P/B → `valuation_ratios`) is more than **7 days** older than
   the rebalance day. Held means: no signals, no orders, and no run recorded — the book stays due
   and rebalances on the first night fresh data lands. Price-only books are unaffected. A blend
   inherits its sleeves' families.
2. **A table that cannot be dated counts as stale.** Missing data never reads as fresh.
3. **Visible in three places.** `data_health` in the rebalance response lists held books with the
   factor date and age; the 21:30 cron alerts on any held book; the paper page shows one warning
   line and a "holding — scores Nd old" tag on each held book (`GET /api/paper/data-health`).
4. **One explicit override.** `allow_stale=true` on the rebalance call. `force` still overrides
   only the cadence, never the data check.

7 days, not adr-045's 14: a weekly harvest is the intended cadence, so a book should never be
more than one missed harvest behind.

## Consequences

- Paper records now mean "the strategy on current data, or not at all". A held month is a gap in
  trading, not a trade on old data; the positions already held keep being marked daily.
- The monthly harvest (#953) is now load-bearing in a visible way: miss a week and the cockpit
  and the alert say which books are waiting.
- The override exists so the owner can choose to trade on old scores knowingly; nothing in the
  crons passes it.
- Freshness is measured per table (newest date anywhere in it), not per stock. A harvest that
  refreshes only some names — the ~99-name megacap leg alone, or a DVM pull that lost some series
  — makes the table look fresh while most names are old. The monthly harvest therefore runs the
  full-universe DVM and valuation legs; the ingest dry-run's coverage report is where a partial
  harvest shows.
- The alert reaches the owner only through the cron log and the paper page until a push channel
  (`/opt/homeserver/scripts/.windfall-alert.env`) is configured; none is, on this server, for any
  project.
