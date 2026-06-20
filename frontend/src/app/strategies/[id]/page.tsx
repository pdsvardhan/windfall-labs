"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BacktestResultFull, Strategy, StrategyConfig } from "@/lib/types";
import { Card } from "@/components/ui";
import { BacktestReport } from "@/components/BacktestReport";

export default function StrategyResult() {
  const id = String(useParams().id);
  const router = useRouter();
  const [s, setS] = useState<Strategy | null>(null);
  const [res, setRes] = useState<BacktestResultFull | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.getStrategy(id).then(setS).catch((e) => setErr(e.message));
    api.listBacktests(id).then((rows) => {
      if (rows[0]) api.getBacktest(rows[0].id).then((r) => setRes(r as BacktestResultFull)).catch(() => {});
    }).catch(() => {});
  }, [id]);

  async function run() {
    if (!s) return;
    setBusy(true); setErr(null);
    try { setRes(await api.runBacktest(s.config, id, true)); }
    catch (e) { setErr(`backtest failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }
  async function remove() { await api.deleteStrategy(id); router.push("/strategies"); }

  if (err && !s) return <div className="mt-8 text-loss text-sm">{err}</div>;
  if (!s) return <div className="mt-8 text-muted text-sm">Loading…</div>;
  const cfg = s.config as unknown as StrategyConfig;

  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <div className="flex items-center gap-3">
            <Link href="/strategies" className="wf-card wf-card-lift flex items-center justify-center" style={{ width: 38, height: 38, borderRadius: "50%", fontSize: 17 }}>←</Link>
            <span className="text-[13px] text-faint font-bold uppercase tracking-wide">Strategy result</span>
            {res && <span className="text-[11px] font-extrabold px-2.5 py-1 rounded-full" style={{ background: "#b9d24a", color: "#3a4512" }}>BACKTESTED</span>}
          </div>
          <h1 className="text-[34px] font-extrabold tracking-tight mt-2">{s.name}</h1>
          {res && <p className="text-faint text-[13px] mt-1 font-mono">{res.period.start} → {res.period.end} · {res.period.years}y · {cfg.rebalance} · top {cfg.n_holdings} · sort {cfg.rank_by} {cfg.rank_order === "desc" ? "↓" : "↑"}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn btn-soft" disabled={busy} onClick={run}>{busy ? "running…" : res ? "↻ Re-run" : "Run backtest"}</button>
          <Link href={`/strategies/${id}/edit`} className="btn btn-soft">Edit config</Link>
          <Link href={`/signals?strategy=${id}`} className="btn btn-ink">Use for signals →</Link>
          <button className="btn btn-ghost" style={{ color: "#c23e74" }} onClick={remove}>Delete</button>
        </div>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}

      {res ? (
        <BacktestReport res={res} config={cfg} />
      ) : (
        <Card className="px-5 py-10 text-center">
          <div className="text-[15px] font-bold">No result yet</div>
          <p className="text-muted text-[13px] mt-1.5 mb-4">Run the backtest to produce this strategy's result.</p>
          <button className="btn btn-acc mx-auto" disabled={busy} onClick={run}>{busy ? "running…" : "Run backtest →"}</button>
        </Card>
      )}
    </div>
  );
}
