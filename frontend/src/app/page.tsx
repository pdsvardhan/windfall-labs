"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BacktestRow, Strategy } from "@/lib/types";
import { pctSigned, num, dateShort, signClass } from "@/lib/format";
import { Card, StatCard, CountUp } from "@/components/ui";
import { Sparkline } from "@/components/charts";

export default function Home() {
  const router = useRouter();
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [bts, setBts] = useState<BacktestRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listStrategies(), api.listBacktests()])
      .then(([s, b]) => { setStrats(s); setBts(b); })
      .catch((e) => setErr(e.message));
  }, []);

  // latest backtest per strategy
  const latest = new Map<string, BacktestRow>();
  for (const b of bts) if (b.strategy_id && !latest.has(b.strategy_id)) latest.set(b.strategy_id, b);
  const tested = [...latest.values()];
  const best = tested.slice().sort((a, b) => (b.summary.cagr ?? -9) - (a.summary.cagr ?? -9))[0];
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div>
      <div className="my-7 animate-rise">
        <h1 className="text-[38px] font-extrabold tracking-tight leading-none">{greet} — your cockpit</h1>
        <p className="text-muted text-[15px] mt-2">Define a screen, backtest it survivorship-free with real costs, then act on today's signals. You place every order.</p>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">API error: {err}</span></Card>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 mb-4">
        <StatCard tone="limeY" label="Strategies" value={<CountUp to={strats.length} />} sub="in your library" delay={0} />
        <StatCard tone="lime" label="Backtested" value={<CountUp to={tested.length} />} sub="with results" delay={60} />
        <StatCard tone="sky" label="Best CAGR" value={best ? pctSigned(best.summary.cagr) : "—"} sub={best?.name} delay={120} />
        <Link href="/strategies/new" className="wf-card wf-card-lift animate-pop flex flex-col justify-between" style={{ background: "linear-gradient(140deg,#7c5cd6,#6243b8)", padding: "20px 22px", animationDelay: "180ms" }}>
          <div className="text-[13px] font-semibold" style={{ color: "#ddd6f5" }}>Create</div>
          <div className="text-[26px] font-extrabold mt-1" style={{ color: "#e9f57a" }}>+ New strategy →</div>
        </Link>
      </div>

      <div className="grid lg:grid-cols-[1fr_1.5fr] gap-3.5">
        {/* leaderboard */}
        <div>
          <div className="text-[13px] font-extrabold text-muted mb-2.5">Your strategies</div>
          {strats.length === 0 ? (
            <Card className="px-4 py-6 text-[13px] text-muted">No strategies yet. <Link href="/strategies/new" className="font-bold" style={{ color: "#6243b8" }}>Create your first →</Link></Card>
          ) : (
            <div className="flex flex-col gap-2.5">
              {strats.slice(0, 6).map((s) => {
                const b = latest.get(s.id);
                return (
                  <Card key={s.id} lift className="px-4 py-3.5 flex items-center justify-between cursor-pointer" onClick={() => router.push(`/strategies/${s.id}`)}>
                    <div>
                      <div className="font-bold text-[14.5px]">{s.name}</div>
                      <div className="text-[11.5px] text-faint mt-0.5">{String((s.config as any)?.rebalance ?? "")} · top {String((s.config as any)?.n_holdings ?? "")}</div>
                    </div>
                    {b ? <div className="text-right"><div className={`font-extrabold text-[15px] ${signClass(b.summary.cagr)}`}>{pctSigned(b.summary.cagr)}</div><div className="text-[11px] text-faint">Sharpe {num(b.summary.sharpe)}</div></div>
                      : <span className="text-[11px] text-faint">not run yet</span>}
                  </Card>
                );
              })}
              <Link href="/strategies" className="text-[12.5px] font-bold text-center py-1" style={{ color: "#6243b8" }}>View all strategies →</Link>
            </div>
          )}
        </div>

        {/* recent backtests */}
        <div>
          <div className="text-[13px] font-extrabold text-muted mb-2.5">Recent backtests</div>
          <Card className="overflow-hidden">
            <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.6fr .9fr .9fr .7fr .8fr", borderColor: "#f0eef6" }}>
              <span>Strategy</span><span className="text-right">CAGR</span><span className="text-right">Max DD</span><span className="text-right">Sharpe</span><span className="text-right">When</span>
            </div>
            {bts.length === 0 ? <div className="px-5 py-6 text-[13px] text-faint">None yet.</div> : (
              <div className="scroll-y" style={{ maxHeight: 420 }}>
                {bts.slice(0, 40).map((b) => (
                  <div key={b.id} className="wf-row grid px-5 py-3 text-[13.5px] items-center tn border-b cursor-pointer" style={{ gridTemplateColumns: "1.6fr .9fr .9fr .7fr .8fr", borderColor: "#f6f4fb" }}
                    onClick={() => router.push(b.strategy_id ? `/strategies/${b.strategy_id}` : `/`)}>
                    <span className="font-bold">{b.name}</span>
                    <span className={`text-right font-bold ${signClass(b.summary.cagr)}`}>{pctSigned(b.summary.cagr)}</span>
                    <span className="text-right text-loss">{pctSigned(b.summary.max_drawdown)}</span>
                    <span className="text-right">{num(b.summary.sharpe)}</span>
                    <span className="text-right text-faint">{dateShort(b.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
