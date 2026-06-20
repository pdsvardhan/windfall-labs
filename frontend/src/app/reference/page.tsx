"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DataStatus } from "@/lib/types";
import { ALL_FACTORS, FREQUENCIES, INDEXES } from "@/lib/catalog";
import { Card, StatCard, SectionTitle } from "@/components/ui";

export default function ReferencePage() {
  const [data, setData] = useState<DataStatus | null>(null);
  useEffect(() => { api.dataStatus().then(setData).catch(() => {}); }, []);

  // group factors by their catalog group
  const groups: Record<string, typeof ALL_FACTORS> = {};
  for (const f of ALL_FACTORS) (groups[f.group] ||= []).push(f);

  // Prefer the survivorship-free Trendlyne layer (what backtests actually run on) over the legacy store.
  const tl = data?.trendlyne?.available ? data.trendlyne : null;
  const cov = data?.coverage;
  return (
    <div>
      <div className="mt-6 mb-4 animate-rise">
        <h1 className="text-[34px] font-extrabold tracking-tight">Reference</h1>
        <p className="text-muted text-[14px] mt-1.5">Everything you can screen, rank and backtest on — the variables, the universes, the frequencies, and what data we hold.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 mb-5">
        <StatCard tone="lime" label="Investable now" value={tl?.universe_now ?? data?.n_universe ?? "…"} sub={`names > ₹${tl?.floor_cr ?? 500}cr today`} />
        <StatCard tone="pink" label="Ever in universe" value={tl?.universe_ever ?? "…"} sub={`incl. ${tl?.delisted ?? 0} delisted (survivorship-free)`} />
        <StatCard tone="limeY" label="Price tickers" value={tl?.price_tickers ?? cov?.n_tickers ?? "…"} sub="split/bonus-adjusted OHLCV" />
        <StatCard tone="sky" label="Data through" value={tl?.date_max?.slice(0, 10) ?? cov?.date_max?.slice(0, 10) ?? "…"} sub={`from ${tl?.date_min?.slice(0, 4) ?? cov?.date_min?.slice(0, 4) ?? "…"}`} />
      </div>

      <div className="grid lg:grid-cols-[1.4fr_1fr] gap-3.5">
        {/* variables */}
        <Card className="p-5">
          <SectionTitle dot="#b9d24a">Variables you can screen &amp; rank on</SectionTitle>
          <p className="text-[12px] text-muted mb-3">Use these in filters (e.g. <span className="font-mono">close &gt; sma200</span>) and as the sort variable. <span className="font-bold">⚠ = no data for delisted names</span> — selecting one makes a run survivors-only.</p>
          <div className="space-y-4">
            {Object.entries(groups).map(([g, fs]) => (
              <div key={g}>
                <div className="text-[12px] font-extrabold text-muted mb-1.5">{g}</div>
                <div className="flex flex-wrap gap-1.5">
                  {fs.map((f) => (
                    <span key={f.token} className="font-mono text-[11.5px] px-2 py-1 rounded-lg" style={{ background: f.survivorsOnly ? "#fff3da" : "#f1ecfb", color: f.survivorsOnly ? "#9a6c12" : "#5b4a9e" }} title={f.label}>
                      {f.token}{f.survivorsOnly ? " ⚠" : ""}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-3.5">
          <Card className="p-5">
            <SectionTitle dot="#a9c9f2">Universes</SectionTitle>
            <p className="text-[12px] text-muted mb-2.5">The starting pool a strategy screens from. <span className="font-mono">trendlyne</span> is the default — survivorship-free (includes delisted names).</p>
            <div className="space-y-2">
              {INDEXES.map((i) => <div key={i.value} className="text-[13px]"><span className="font-mono font-bold">{i.value}</span> — <span className="text-muted">{i.label}</span></div>)}
            </div>
          </Card>
          <Card className="p-5">
            <SectionTitle dot="#f5e049">Rebalance frequencies</SectionTitle>
            <div className="flex flex-wrap gap-1.5">
              {FREQUENCIES.map((f) => <span key={f} className="font-mono text-[12px] px-2.5 py-1 rounded-lg" style={{ background: "#f1ecfb", color: "#5b4a9e" }}>{f}</span>)}
            </div>
          </Card>
          <Card className="p-5">
            <SectionTitle dot="#c4b6f7">Data &amp; honesty</SectionTitle>
            <ul className="text-[12.5px] text-muted space-y-2 list-disc pl-4">
              <li><b className="text-ink">Survivorship-free by default</b> — backtests include delisted companies so results aren't optimistic.</li>
              <li>Costs (brokerage + STT + slippage) and turnover are modelled on every trade.</li>
              <li>No look-ahead: decisions at close, fills at next open; fundamentals readable only after their announcement date.</li>
              <li>Trendlyne DVM (⚠ factors) exists for survivors only — a screen using them is survivors-only.</li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
