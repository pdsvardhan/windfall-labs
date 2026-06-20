"use client";

import { useState } from "react";
import type { BacktestResultFull, CostSensitivity, StrategyConfig } from "@/lib/types";
import { api } from "@/lib/api";
import { pct, pctSigned, num, moneyCompact, signClass } from "@/lib/format";
import { survivorsOnly } from "@/lib/catalog";
import { MetricCard, MetricMini, Card, useReveal } from "@/components/ui";
import { EquityChart, DrawdownChart } from "@/components/charts";

const EXIT_TONE: Record<string, string> = {
  target: "good", stop: "bad", time: "warn", delisted: "neutral", rebalance: "neutral", end: "neutral",
};

export function BacktestReport({ res, config }: { res: BacktestResultFull; config?: StrategyConfig }) {
  const s = res.summary;
  const ref = useReveal();
  const sv = config ? survivorsOnly(config) : { survivorsOnly: false, offenders: [] };

  return (
    <div className="space-y-3.5">
      {/* readiness / survivorship honesty banner */}
      {(res.readiness || config) && (
        <Card className="px-4 py-3 flex items-center gap-3" style={{ background: sv.survivorsOnly ? "#fff3da" : "#e6f4ea" }}>
          <span className="text-[12px] font-extrabold px-2.5 py-1 rounded-full"
            style={{ background: sv.survivorsOnly ? "#f6e2b0" : "#cdeacf", color: sv.survivorsOnly ? "#9a6c12" : "#1f7a4d" }}>
            {sv.survivorsOnly ? "SURVIVORS-ONLY" : "SURVIVORSHIP-FREE"}
          </span>
          <span className="text-[12.5px] text-ink/80">
            {sv.survivorsOnly
              ? `Uses Trendlyne-only factors (${sv.offenders.join(", ")}) that delisted names lack — this run excludes dead names.`
              : "Includes delisted names — results aren't survivorship-biased."}
            {res.readiness?.summary ? ` · ${res.readiness.summary}` : ""}
          </span>
        </Card>
      )}

      {/* big metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <MetricCard tone="lime" label="CAGR" delay={0}
          value={<span className={signClass(s.cagr)}>{pctSigned(s.cagr)}</span>}
          sub={s.benchmark_cagr != null ? `benchmark ${pctSigned(s.benchmark_cagr)}` : undefined} />
        <MetricCard tone="sky" label="Total return" delay={60}
          value={pctSigned(s.total_return)} sub={`${res.period.years}y`} />
        <MetricCard tone="pink" label="Max drawdown" delay={120}
          value={<span className="text-loss">{pct(s.max_drawdown)}</span>}
          sub={s.max_dd_dates?.length ? `${s.max_dd_dates[0]} → ${s.max_dd_dates[1]}` : undefined} />
        <MetricCard tone="limeY" label="Sharpe" delay={180}
          value={num(s.sharpe)} sub={`Sortino ${num(s.sortino)}`} />
      </div>

      {/* mini metrics */}
      <div ref={ref} className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <MetricMini label="Volatility" value={pct(s.volatility)} />
        <MetricMini label="Win rate" value={pct(s.win_rate)} />
        <MetricMini label="Profit factor" value={num(s.profit_factor)} />
        <MetricMini label="Turnover" value={<span className="text-warn">{pct(s.annual_turnover, 0)}</span>} />
        <MetricMini label="Active return" value={<span className={signClass(s.active_return)}>{s.active_return == null ? "—" : pctSigned(s.active_return)}</span>} />
        <MetricMini label="Exposure" value={pct(s.exposure, 0)} />
      </div>

      <CostStrip config={config} />

      {/* equity + drawdown */}
      <div className="grid lg:grid-cols-[1.55fr_1fr] gap-3.5">
        <Card className="p-5">
          <div className="flex items-center justify-between mb-1.5">
            <div className="font-extrabold text-[15px]">Equity curve</div>
            <div className="flex gap-3.5 text-[12px] font-semibold">
              <span className="flex items-center gap-1.5 text-ink"><span className="w-3.5 h-0.5 rounded bg-ink" />Strategy</span>
              <span className="flex items-center gap-1.5 text-faint"><span className="w-3.5 h-0.5 rounded" style={{ background: "#c3bdd0" }} />{res.benchmark_curve?.length ? "Benchmark" : ""}</span>
            </div>
          </div>
          <EquityChart strategy={res.equity_curve} benchmark={res.benchmark_curve} />
          <div className="text-[12px] text-faint mt-1.5">₹{moneyCompact(res.equity_curve[0]?.[1])} → {moneyCompact(res.equity_curve.slice(-1)[0]?.[1])}</div>
        </Card>
        <Card className="p-5">
          <div className="font-extrabold text-[15px] mb-1.5">Drawdown</div>
          <DrawdownChart curve={res.drawdown_curve} />
          <div className="text-[12px] text-faint mt-1.5">Deepest: <b className="text-loss">{pct(s.max_drawdown)}</b></div>
        </Card>
      </div>

      {/* warnings */}
      {res.warnings?.length > 0 && (
        <Card className="p-4">
          <div className="text-[12px] font-bold text-muted mb-2">Engine notes</div>
          <ul className="text-[12px] text-muted space-y-1 list-disc pl-4">
            {res.warnings.slice(0, 6).map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </Card>
      )}

      {/* trades */}
      <div>
        <div className="text-[13px] font-extrabold text-muted mb-2.5">Trades · {res.trades.length} total</div>
        <Card className="overflow-hidden">
          <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.1fr 1fr 1fr .8fr .6fr .6fr .9fr", borderColor: "#f0eef6" }}>
            <span>Ticker</span><span>Entry</span><span>Exit</span><span className="text-right">Return</span><span className="text-right">R</span><span className="text-right">Days</span><span className="text-right">Reason</span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 380 }}>
            {res.trades.slice(0, 200).map((t, i) => (
              <div key={i} className="wf-row grid px-5 py-3 text-[13px] items-center tn border-b" style={{ gridTemplateColumns: "1.1fr 1fr 1fr .8fr .6fr .6fr .9fr", borderColor: "#f6f4fb" }}>
                <span className="font-bold">{t.ticker}</span>
                <span className="text-faint">{t.entry_date}</span>
                <span className="text-faint">{t.exit_date ?? "—"}</span>
                <span className={`text-right font-bold ${signClass(t.return_pct)}`}>{pctSigned(t.return_pct)}</span>
                <span className={`text-right ${signClass(t.r_multiple)}`}>{t.r_multiple == null ? "—" : num(t.r_multiple, 1)}</span>
                <span className="text-right text-faint">{t.holding_days}</span>
                <span className="text-right">
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={tonePill(EXIT_TONE[t.exit_reason] || "neutral")}>{t.exit_reason}</span>
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function tonePill(tone: string): React.CSSProperties {
  const m: Record<string, [string, string]> = {
    good: ["#e6f4ea", "#1f7a4d"], bad: ["#fdeaf1", "#c23e74"], warn: ["#fff3da", "#9a6c12"], neutral: ["#eceaf2", "#7a7689"],
  };
  const [bg, color] = m[tone] || m.neutral;
  return { background: bg, color };
}

// collapsible cost-sensitivity strip — re-runs the strategy at 0x/1x/2x costs on demand.
function CostStrip({ config }: { config?: StrategyConfig }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<CostSensitivity | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    if (!config) return;
    setOpen(true);
    if (data || busy) return;
    setBusy(true); setErr(null);
    try { setData(await api.costSensitivity(config)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Card className="px-5 py-3">
      <button className="flex items-center gap-2 text-[13px] font-bold text-ink" onClick={() => (open ? setOpen(false) : load())}>
        <span className="text-faint">{open ? "▾" : "▸"}</span> Cost sensitivity
        <span className="text-[11.5px] text-faint font-medium">— how much do costs eat the edge?</span>
      </button>
      {open && (
        <div className="mt-3">
          {busy && <div className="text-[12px] text-faint">running 0× / 1× / 2× …</div>}
          {err && <div className="text-[12px] text-loss">{err}</div>}
          {data && (
            <div className="grid grid-cols-3 gap-3">
              {data.runs.map((r) => (
                <div key={r.cost_multiplier} className="rounded-xl px-4 py-3" style={{ background: r.cost_multiplier === 1 ? "#eef6dd" : "#f7f5fc" }}>
                  <div className="text-[11.5px] font-bold text-muted">{r.cost_multiplier === 0 ? "0× (frictionless)" : r.cost_multiplier === 1 ? "1× (your costs)" : `${r.cost_multiplier}× (stress)`}</div>
                  <div className="text-[20px] font-extrabold mt-1 tn">{pctSigned(r.summary.cagr ?? 0)}</div>
                  <div className="text-[11px] text-faint">Sharpe {num(r.summary.sharpe ?? 0)} · turn {pct(r.summary.annual_turnover ?? 0, 0)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
