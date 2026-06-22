"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BacktestRow, Strategy } from "@/lib/types";
import { pctSigned, num, signClass } from "@/lib/format";
import { Card } from "@/components/ui";

export default function StrategiesPage() {
  const router = useRouter();
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [bts, setBts] = useState<BacktestRow[]>([]);
  const [sort, setSort] = useState<"cagr" | "sharpe" | "name">("cagr");
  const [err, setErr] = useState<string | null>(null);
  const [peek, setPeek] = useState<string | null>(null);
  const [running, setRunning] = useState<Set<string>>(new Set());

  function load() {
    Promise.all([api.listStrategies(), api.listBacktests()])
      .then(([s, b]) => { setStrats(s); setBts(b); }).catch((e) => setErr(e.message));
  }
  useEffect(load, []);

  const latest = new Map<string, BacktestRow>();
  for (const b of bts) if (b.strategy_id && !latest.has(b.strategy_id)) latest.set(b.strategy_id, b);

  const rows = strats.map((s) => ({ s, b: latest.get(s.id) }));
  rows.sort((a, b) => {
    if (sort === "name") return a.s.name.localeCompare(b.s.name);
    const av = a.b?.summary[sort] ?? -99, bv = b.b?.summary[sort] ?? -99;
    return bv - av;
  });

  // Duplicate now seeds the builder and opens /new prefilled (no silent auto-create entry).
  function duplicate(s: Strategy) {
    sessionStorage.setItem("wf_seed", JSON.stringify({ name: `${s.name}_copy`, config: s.config }));
    router.push("/strategies/new");
  }
  async function runOne(s: Strategy) {
    setRunning((r) => new Set(r).add(s.id));
    try { await api.runBacktest(s.config, s.id, true); load(); }
    catch (e) { setErr(`backtest failed: ${(e as Error).message}`); }
    finally { setRunning((r) => { const n = new Set(r); n.delete(s.id); return n; }); }
  }
  async function remove(id: string) { await api.deleteStrategy(id); load(); }

  return (
    <div>
      <div className="my-7 animate-rise">
        <h1 className="text-[34px] font-extrabold tracking-tight">Strategies</h1>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}

      <div className="flex items-center gap-2 mb-3 text-[12px] font-bold text-muted">
        Sort:
        {(["cagr", "sharpe", "name"] as const).map((k) => (
          <button key={k} className="wf-seg" data-active={sort === k ? "1" : "0"} style={{ flex: "none", padding: "5px 12px" }} onClick={() => setSort(k)}>{k.toUpperCase()}</button>
        ))}
      </div>

      {strats.length === 0 ? (
        <Card className="px-5 py-10 text-center">
          <div className="text-[15px] font-bold">No strategies yet</div>
          <p className="text-muted text-[13px] mt-1.5 mb-4">Create your first screen and backtest it.</p>
          <button className="btn btn-acc mx-auto" onClick={() => router.push("/strategies/new")}>+ New strategy</button>
        </Card>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3.5">
          {rows.map(({ s, b }) => {
            const c = s.config as any;
            return (
              <Card key={s.id} lift className="p-5 flex flex-col">
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/strategies/${s.id}`} className="font-extrabold text-[16px] hover:underline">{s.name}</Link>
                  <button onClick={() => setPeek(peek === s.id ? null : s.id)} title="View config" className="text-faint hover:text-ink text-[14px] leading-none">{peek === s.id ? "✕" : "⊙ config"}</button>
                </div>
                <div className="text-[11.5px] text-faint mt-1 font-mono">
                  {c?.rebalance} · top {c?.n_holdings} · sort {c?.rank_by || "—"} · {c?.data_source === "trendlyne" ? "survivorship-free" : c?.universe?.index}
                </div>
                <div className="text-[11px] text-faint mt-0.5 font-mono">{c?.start} → {c?.end || "today"}</div>

                {peek === s.id && <ConfigPeek c={c} />}

                {b ? (
                  <>
                    <div className="grid grid-cols-3 gap-2 mt-4">
                      <Mini label="CAGR" value={<span className={signClass(b.summary.cagr)}>{pctSigned(b.summary.cagr)}</span>} />
                      <Mini label="Max DD" value={<span className="text-loss">{pctSigned(b.summary.max_drawdown)}</span>} />
                      <Mini label="Sharpe" value={num(b.summary.sharpe)} />
                    </div>
                    <div className="text-[11px] text-faint mt-2">
                      vs benchmark {pctSigned(b.summary.benchmark_cagr)} · {b.summary.n_trades} trades
                    </div>
                  </>
                ) : (
                  <div className="mt-4 flex items-center gap-2.5">
                    <span className="text-[12px] text-faint">Not backtested yet.</span>
                    <button className="btn btn-acc" style={{ padding: "5px 12px", fontSize: 12 }} disabled={running.has(s.id)} onClick={() => runOne(s)}>{running.has(s.id) ? "running…" : "Run backtest"}</button>
                  </div>
                )}
                <div className="flex gap-2 mt-4 pt-3 border-t" style={{ borderColor: "#f0eef6" }}>
                  <Link href={`/strategies/${s.id}`} className="btn btn-soft" style={{ padding: "7px 14px", fontSize: 12 }}>Open</Link>
                  <Link href={`/strategies/${s.id}/edit`} className="btn btn-ghost" style={{ padding: "7px 14px", fontSize: 12 }}>Edit</Link>
                  <button className="btn btn-ghost" style={{ padding: "7px 14px", fontSize: 12 }} onClick={() => duplicate(s)}>Duplicate</button>
                  <button className="btn btn-ghost ml-auto" style={{ padding: "7px 12px", fontSize: 12, color: "#c23e74" }} onClick={() => remove(s.id)}>Delete</button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Mini({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl px-2.5 py-2" style={{ background: "#f7f5fc" }}>
      <div className="text-[10.5px] text-faint font-semibold">{label}</div>
      <div className="text-[15px] font-extrabold mt-0.5 tn">{value}</div>
    </div>
  );
}

// Inline config peek — the "view query/config" the owner asked for (mirrors Trendlyne's "Query used").
function ConfigPeek({ c }: { c: any }) {
  const line = (k: string, v: React.ReactNode) => (
    <div className="flex gap-2"><span className="text-faint w-[88px] shrink-0">{k}</span><span className="font-mono text-ink/80 break-words">{v}</span></div>
  );
  const filters = (c?.universe?.filters ?? []) as string[];
  const entries = (c?.entry_filters ?? []) as string[];
  return (
    <div className="mt-3 rounded-xl p-3 text-[11.5px] space-y-1" style={{ background: "#f7f5fc" }}>
      {line("Screener", filters.length ? filters.join("  ·  ") : "all names")}
      {line("Entry", entries.length ? entries.join("  ·  ") : "—")}
      {line("Rank", `${c?.rank_by || "—"} ${c?.rank_order === "asc" ? "↑" : "↓"}`)}
      {line("Sizing", `top ${c?.n_holdings} · ${c?.weighting}${c?.max_weight_per_stock ? ` · max ${c.max_weight_per_stock}` : ""}`)}
      {line("Exits", `stop ${c?.stop_loss?.type ?? "none"} · tp ${c?.take_profit?.type ?? "none"}${c?.regime_filter?.enabled ? " · regime on" : ""}`)}
      {line("Costs", `${c?.costs_bps?.brokerage}+${c?.costs_bps?.stt}+${c?.costs_bps?.slippage} bps`)}
      {line("Window", `${c?.start} → ${c?.end || "today"} · ${c?.rebalance} · vs ${c?.benchmark}`)}
    </div>
  );
}
