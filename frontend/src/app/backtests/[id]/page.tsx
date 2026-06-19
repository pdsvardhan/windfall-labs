"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { BacktestResult } from "@/lib/types";
import { pct } from "@/lib/format";
import { LineChart } from "@/components/LineChart";
import { MetricsGrid } from "@/components/MetricsGrid";
import { TradesTable } from "@/components/TradesTable";

export default function BacktestPage() {
  const { id } = useParams() as { id: string };
  const [r, setR] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.getBacktest(id).then(setR).catch((e) => setErr(e.message)); }, [id]);

  if (err) return <div className="card border-loss/50 px-4 py-3 text-loss">Error: {err}</div>;
  if (!r) return <div className="text-muted">Loading…</div>;

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{r.name}</h1>
        <p className="text-muted text-sm mono">
          {r.period.start} → {r.period.end} · {r.period.years}y · hash {r.config_hash}
        </p>
      </div>

      {r.warnings?.length > 0 && (
        <div className="card border-warn/40 px-4 py-2 text-sm text-warn">
          {r.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}

      <MetricsGrid s={r.summary} />

      <section>
        <h2 className="text-lg font-medium mb-2">Equity curve</h2>
        <div className="card p-3">
          <LineChart
            series={[
              { name: r.name, color: "#2EA043", points: r.equity_curve },
              ...(r.benchmark_curve?.length
                ? [{ name: "benchmark", color: "#8B949E", points: r.benchmark_curve }]
                : []),
            ]}
            yFormat={(v) => `₹${(v / 1e5).toFixed(1)}L`}
          />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium mb-2">Drawdown</h2>
        <div className="card p-3">
          <LineChart
            series={[{ name: "drawdown", color: "#F85149", points: r.drawdown_curve, fill: true }]}
            yFormat={(v) => pct(v, 0)} zeroLine
            height={200}
          />
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium mb-2">Trades ({r.trades.length})</h2>
        <TradesTable trades={r.trades} />
      </section>
    </div>
  );
}
