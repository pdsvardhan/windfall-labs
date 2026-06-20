# Cockpit UI rebuild — "Pastel Pop" (iter-16)

Full from-scratch rebuild of the Next.js cockpit in the Pastel Pop design system, wired to the
live FastAPI backend. Live at **http://192.168.1.10:8500**. Branch `iter-16-ui-pastel`.

## Design system (foundation)
- `tailwind.config.ts` — Pastel Pop palette (lavender bg, ink, lime/pink/sky/lilac/grape pastels, lime accent), Plus Jakarta Sans + JetBrains Mono, float/rise/pop animations.
- `src/app/globals.css` — card / button / input / chip / switch / segmented / range / nav / json-highlight classes.
- `src/app/layout.tsx` — gradient canvas + floating blobs + rounded dark nav.
- `src/components/` — `Nav`, `ui` (Card, StatCard, MetricCard/Mini, Switch, Segmented, Slider, Field, Pill, CountUp), `charts` (Sparkline, EquityChart, DrawdownChart, Gauge), `JsonView`, `BacktestReport`, `StrategyBuilder`.
- `src/lib/catalog.ts` — the variable catalog (drives builder pickers + Reference) and the **survivorship classifier**.

## Pages (all wired to live data) — verify each
| Page | Route | What to check |
|---|---|---|
| Home / Cockpit | `/` | Greeting, stat cards (strategies / backtested / best CAGR / new-strategy CTA), your-strategies leaderboard, recent-backtests table (click → strategy). Coverage cards removed per your note. |
| Strategies library | `/strategies` | Card per strategy (recipe summary + CAGR/MaxDD/Sharpe), sort by CAGR/Sharpe/name, actions: Open / Edit / Duplicate / Delete. |
| New strategy | `/strategies/new` | Guided builder: screener filter chips (indicator+op+value, with raw escape), entry filters, sort-by + max/min, sizing (holdings/weighting/max-wt/sector cap), exits, regime, costs, rebalance, dates. Live JSON mirror. Readiness verdict. **Survivorship status chip auto-flips** when a Trendlyne-DVM (⚠) factor is picked. Run backtest + **Explore variations** (sweep → ranked → save winner). |
| Edit strategy | `/strategies/[id]/edit` | Same builder, pre-loaded. |
| Strategy result | `/strategies/[id]` | = the backtest report: survivorship/readiness banner, 4 big + 6 mini metrics, collapsible cost-sensitivity (0×/1×/2×), equity + drawdown charts, trades table. Actions: Re-run / Edit / Use for signals / Delete. |
| Live signals | `/signals` | Pick a strategy → Run on latest data → BUY/HOLD/SELL table (entry zone, stop, target, RSI, weight, surveillance flag), regime badge, CSV export. |
| Reference | `/reference` | Coverage cards + all screen/rank variables grouped (⚠ = no delisted data), universes, frequencies, honesty notes. (replaces Data status) |

## Key behaviours
- **Survivorship-free is the default** (`data_source: "trendlyne"`). The builder shows it as a status
  chip; it **auto-flips to "survivors-only" (disabled)** when a factor with no delisted-name data
  (Trendlyne DVM/valuation/snapshot fundamentals — flagged ⚠) is referenced. No manual toggle.
- **Strategy = recipe + one result** — the strategy detail page *is* its report; variations via Duplicate.
- **Explore variations** = parameter sweep (`/api/sweep`): set value ranges, auto-run, rank, save winners.
- **Cost-sensitivity** = collapsible diagnostic on the result (gap between 0× and 1× = fragility).

## Deferred (by decision, explained earlier)
- **Paper trades** — forward real-time tracker; needs calendar time, not in the core loop yet.
- **Walk-forward** — robustness/curve-fit standard; add later as a "check robustness" action.
- **A/B compare** — dropped (not needed).
- Own-DVM validation stays backend-only.

## Notes
- No new npm deps (fonts via `next/font/google`, charts hand-rolled SVG).
- Seeded example: `momentum_survivorship_free` (survivorship-free, 2017-2023) so there's a live result to inspect.
