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

  async function duplicate(s: Strategy) {
    const r = await api.saveStrategy(`${s.name}_copy`, s.config);
    router.push(`/strategies/${r.id}/edit`);
  }
  async function remove(id: string) {
    await api.deleteStrategy(id); load();
  }

  return (
    <div>
      <div className="flex items-end justify-between my-7 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Strategies</h1>
          <p className="text-muted text-[14px] mt-1.5">Every recipe you've created and tested. Each is a screen + ranking + sizing + window — and its one result.</p>
        </div>
        <button className="btn btn-acc" onClick={() => router.push("/strategies/new")}>+ New strategy</button>
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
          {rows.map(({ s, b }) => (
            <Card key={s.id} lift className="p-5 flex flex-col">
              <div className="flex items-start justify-between">
                <Link href={`/strategies/${s.id}`} className="font-extrabold text-[16px] hover:underline">{s.name}</Link>
                <span className="text-[11px] font-mono text-faint">{(s.config as any)?.rebalance}</span>
              </div>
              <div className="text-[11.5px] text-faint mt-1 font-mono">
                top {(s.config as any)?.n_holdings} · sort {(s.config as any)?.rank_by} · {(s.config as any)?.data_source === "trendlyne" ? "survivorship-free" : (s.config as any)?.universe?.index}
              </div>
              {b ? (
                <div className="grid grid-cols-3 gap-2 mt-4">
                  <Mini label="CAGR" value={<span className={signClass(b.summary.cagr)}>{pctSigned(b.summary.cagr)}</span>} />
                  <Mini label="Max DD" value={<span className="text-loss">{pctSigned(b.summary.max_drawdown)}</span>} />
                  <Mini label="Sharpe" value={num(b.summary.sharpe)} />
                </div>
              ) : <div className="mt-4 text-[12px] text-faint">Not backtested yet.</div>}
              <div className="flex gap-2 mt-4 pt-3 border-t" style={{ borderColor: "#f0eef6" }}>
                <Link href={`/strategies/${s.id}`} className="btn btn-soft" style={{ padding: "7px 14px", fontSize: 12 }}>Open</Link>
                <Link href={`/strategies/${s.id}/edit`} className="btn btn-ghost" style={{ padding: "7px 14px", fontSize: 12 }}>Edit</Link>
                <button className="btn btn-ghost" style={{ padding: "7px 14px", fontSize: 12 }} onClick={() => duplicate(s)}>Duplicate</button>
                <button className="btn btn-ghost ml-auto" style={{ padding: "7px 12px", fontSize: 12, color: "#c23e74" }} onClick={() => remove(s.id)}>Delete</button>
              </div>
            </Card>
          ))}
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
