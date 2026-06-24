"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BacktestRow, Strategy } from "@/lib/types";
import { pctSigned, num, dateShort, signClass, moneyCompact } from "@/lib/format";
import { Card, StatCard, Pill } from "@/components/ui";

export default function Home() {
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [bts, setBts] = useState<BacktestRow[]>([]);
  const [through, setThrough] = useState<string | null>(null);
  const [paper, setPaper] = useState<{ pnl: number; open: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [greet, setGreet] = useState("");

  useEffect(() => {
    const hour = new Date().getHours();
    setGreet(hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening");
    Promise.all([api.listStrategies(), api.listBacktests()])
      .then(([s, b]) => { setStrats(s); setBts(b); })
      .catch((e) => setErr(e.message));
    api.dataStatus().then((d) => setThrough(d.trendlyne?.date_max ?? d.coverage?.date_max ?? null)).catch(() => {});
    api.scoreboard().then((rows) => setPaper({
      pnl: rows.reduce((a, r) => a + (r.total_pnl ?? 0), 0),
      open: rows.reduce((a, r) => a + (r.open ?? 0), 0),
    })).catch(() => {});
  }, []);

  // latest backtest per strategy
  const latest = new Map<string, BacktestRow>();
  for (const b of bts) if (b.strategy_id && !latest.has(b.strategy_id)) latest.set(b.strategy_id, b);
  const tested = [...latest.values()];
  const best = tested.slice().sort((a, b) => (b.summary.cagr ?? -9) - (a.summary.cagr ?? -9))[0];
  const avgCagr = tested.length ? tested.reduce((a, b) => a + (b.summary.cagr ?? 0), 0) / tested.length : null;

  return (
    <div>
      <div className="my-7 animate-rise">
        <h1 className="text-[38px] font-extrabold tracking-tight leading-[1.15] pb-1">{greet ? `${greet} — your cockpit` : "Your cockpit"}</h1>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">API error: {err}</span></Card>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 mb-4">
        <StatCard tone="sky" label="Best strategy" value={best ? <span className={signClass(best.summary.cagr)}>{pctSigned(best.summary.cagr)}</span> : "—"} sub={best?.name ?? "none backtested yet"} delay={0} />
        <StatCard tone="lime" label="Avg CAGR" value={avgCagr != null ? <span className={signClass(avgCagr)}>{pctSigned(avgCagr)}</span> : "—"} sub={`across ${tested.length} backtested`} delay={60} />
        <StatCard tone="limeY" label="Data through" value={through ? through.slice(0, 10) : "…"} sub="survivorship-free layer" delay={120} />
        <StatCard tone="lilac" label="Open paper P&L" delay={180}
          value={paper ? <span className={signClass(paper.pnl)}>{moneyCompact(paper.pnl)}</span> : "—"}
          sub={paper ? (paper.open > 0 ? `${paper.open} open position${paper.open === 1 ? "" : "s"}` : "no open positions") : "paper a strategy to track"} />
      </div>

      <div className="grid lg:grid-cols-[1fr_1.5fr] gap-3.5">
        {/* leaderboard */}
        <div>
          <div className="flex items-center gap-2 mb-2.5 h-[22px]">
            <span className="text-[13px] font-extrabold text-muted">Your strategies</span>
            <Pill tone="neutral">{strats.length}</Pill>
          </div>
          {strats.length === 0 ? (
            <Card className="px-4 py-6 text-[13px] text-muted">No strategies yet. <Link href="/strategies/new" className="font-bold" style={{ color: "#6243b8" }}>Create your first →</Link></Card>
          ) : (
            <div className="flex flex-col gap-2.5">
              {strats.slice(0, 6).map((s) => {
                const b = latest.get(s.id);
                return (
                  <Link key={s.id} href={`/strategies/${s.id}`} className="rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9f86ee]">
                    <Card lift className="px-4 py-3.5 flex items-center justify-between">
                      <div>
                        <div className="font-bold text-[14.5px]">{s.name}</div>
                        <div className="text-[11.5px] text-faint mt-0.5">{String((s.config as any)?.rebalance ?? "")} · top {String((s.config as any)?.n_holdings ?? "")}</div>
                      </div>
                      <div className="flex items-center gap-2.5">
                        {b ? <div className="text-right"><div className={`font-extrabold text-[15px] ${signClass(b.summary.cagr)}`}>{pctSigned(b.summary.cagr)}</div><div className="text-[11px] text-faint">Sharpe {num(b.summary.sharpe)}</div></div>
                          : <span className="text-[11px] text-faint">not run yet</span>}
                        <span className="text-faint text-[16px] leading-none">›</span>
                      </div>
                    </Card>
                  </Link>
                );
              })}
              <Link href="/strategies" className="text-[12.5px] font-bold text-center py-1" style={{ color: "#6243b8" }}>View all strategies →</Link>
            </div>
          )}
        </div>

        {/* recent backtests */}
        <div>
          <div className="flex items-center gap-2 mb-2.5 h-[22px]">
            <span className="text-[13px] font-extrabold text-muted">Recent backtests</span>
            <Pill tone="neutral">{bts.length}</Pill>
          </div>
          <Card className="overflow-hidden">
            <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.6fr .9fr .9fr .7fr .8fr 16px", borderColor: "#f0eef6" }}>
              <span>Strategy</span><span className="text-right">CAGR</span><span className="text-right">Max DD</span><span className="text-right">Sharpe</span><span className="text-right">When</span><span />
            </div>
            {bts.length === 0 ? <div className="px-5 py-6 text-[13px] text-faint">None yet.</div> : (
              <div className="scroll-y" style={{ maxHeight: 420 }}>
                {bts.slice(0, 40).map((b) => (
                  <Link key={b.id} href={b.strategy_id ? `/strategies/${b.strategy_id}` : `/`}
                    className="wf-row grid px-5 py-3 text-[13.5px] items-center tn border-b focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#9f86ee]" style={{ gridTemplateColumns: "1.6fr .9fr .9fr .7fr .8fr 16px", borderColor: "#f6f4fb" }}>
                    <span className="font-bold">{b.name}</span>
                    <span className={`text-right font-bold ${signClass(b.summary.cagr)}`}>{pctSigned(b.summary.cagr)}</span>
                    <span className="text-right text-loss">{pctSigned(b.summary.max_drawdown)}</span>
                    <span className="text-right">{num(b.summary.sharpe)}</span>
                    <span className="text-right text-faint">{dateShort(b.created_at)}</span>
                    <span className="text-right text-faint text-[16px] leading-none">›</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
