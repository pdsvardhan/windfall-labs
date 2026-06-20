"use client";

// Lightweight hand-rolled SVG charts — no chart lib, matching the Pastel Pop line aesthetic.
// Equity + drawdown are interactive: hover to scrub a crosshair, dot and tooltip across the curve.

import { useRef, useState } from "react";
import { moneyCompact, pct } from "@/lib/format";

function pts(values: number[], w: number, h: number, pad = 4): string {
  if (values.length === 0) return "";
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const n = values.length;
  return values
    .map((v, i) => {
      const x = (i / (n - 1 || 1)) * (w - pad * 2) + pad;
      const y = h - pad - ((v - lo) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function Sparkline({ values, color = "#1f7a4d", width = 84, height = 28 }:
  { values: number[]; color?: string; width?: number; height?: number }) {
  if (!values?.length) return <svg width={width} height={height} />;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={pts(values, width, height)} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// shared hover: maps cursor x → nearest data index over the wrapper's width.
function useHover(n: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [i, setI] = useState<number | null>(null);
  const onMove = (e: React.MouseEvent) => {
    const el = ref.current; if (!el || n < 2) return;
    const r = el.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setI(Math.round(f * (n - 1)));
  };
  return { ref, i, onMove, onLeave: () => setI(null) };
}

const W = 560, H = 200, PAD = 8;
const fx = (i: number, len: number) => (i / (len - 1 || 1)) * (W - 2 * PAD) + PAD;   // viewBox x
const leftPct = (i: number, len: number) => (fx(i, len) / W) * 100;                   // overlay left %

export function EquityChart({ strategy, benchmark, height = 220 }:
  { strategy: [string, number][]; benchmark?: [string, number][]; height?: number }) {
  const sv = strategy.map((d) => d[1]);
  const hv = useHover(sv.length);
  if (!sv.length) return <div className="text-faint text-sm">No equity data.</div>;
  // rebase benchmark to the strategy's starting capital so the two lines are comparable
  const bvRaw = (benchmark || []).map((d) => d[1]);
  let bv: number[] = [];
  if (bvRaw.length) { const b0 = bvRaw[0] || 1, s0 = sv[0] || 1; bv = bvRaw.map((x) => (x / b0) * s0); }
  const all = [...sv, ...bv]; const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const fy = (v: number) => H - PAD - ((v - lo) / span) * (H - 2 * PAD);
  const path = (vals: number[]) => vals.map((v, i) => `${fx(i, vals.length).toFixed(1)},${fy(v).toFixed(1)}`).join(" ");
  const sPts = path(sv), bPts = bv.length ? path(bv) : "";
  const i = hv.i;
  const chg = (vals: number[], k: number) => { const c = vals[0] ? vals[k] / vals[0] - 1 : 0; return `${c >= 0 ? "+" : "−"}${Math.abs(c * 100).toFixed(1)}%`; };

  return (
    <div className="wf-chartwrap" ref={hv.ref} onMouseMove={hv.onMove} onMouseLeave={hv.onLeave} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none">
        <defs>
          <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#b9d24a" stopOpacity=".38" />
            <stop offset="1" stopColor="#b9d24a" stopOpacity="0" />
          </linearGradient>
        </defs>
        {sPts && <polygon points={`${sPts} ${W - PAD},${H} ${PAD},${H}`} fill="url(#eqfill)" />}
        {bPts && <polyline points={bPts} fill="none" stroke="#c3bdd0" strokeWidth={2} strokeDasharray="5 5" vectorEffect="non-scaling-stroke" />}
        <polyline points={sPts} fill="none" stroke="#16151c" strokeWidth={2.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
        {i != null && <line x1={fx(i, sv.length)} y1={PAD} x2={fx(i, sv.length)} y2={H} stroke="#9f86ee" strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
      </svg>
      {/* round markers + tooltip as HTML overlay (immune to the non-uniform SVG scaling) */}
      {(() => { const k = i ?? sv.length - 1; return (
        <span style={{ position: "absolute", left: `${leftPct(k, sv.length)}%`, top: `${(fy(sv[k]) / H) * height}px`, width: 9, height: 9, borderRadius: "50%", background: "#16151c", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
      ); })()}
      {i != null && bv.length > 0 && (
        <span style={{ position: "absolute", left: `${leftPct(i, bv.length)}%`, top: `${(fy(bv[i]) / H) * height}px`, width: 8, height: 8, borderRadius: "50%", background: "#c3bdd0", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
      )}
      {i != null && (
        <div className="wf-tip" style={{ left: `${leftPct(i, sv.length)}%`, top: `${(fy(sv[i]) / H) * height}px` }}>
          <div className="d">{strategy[i][0]}</div>
          <div>Strategy <b>₹{moneyCompact(sv[i]).replace("₹", "")}</b> <span className="d">{chg(sv, i)}</span></div>
          {bv.length > 0 && <div>Benchmark <b>₹{moneyCompact(bv[i]).replace("₹", "")}</b> <span className="d">{chg(bv, i)}</span></div>}
        </div>
      )}
    </div>
  );
}

export function DrawdownChart({ curve, height = 200 }: { curve: [string, number][]; height?: number }) {
  const Hd = 180;
  const vals = curve.map((d) => d[1]); // negative fractions
  const hv = useHover(vals.length);
  if (!vals.length) return <div className="text-faint text-sm">No drawdown data.</div>;
  const lo = Math.min(...vals, 0);
  const span = Math.abs(lo) || 1;
  const fy = (v: number) => PAD + (Math.abs(v) / span) * (Hd - 2 * PAD); // 0 at top, deepest at bottom
  const P = vals.map((v, k) => `${fx(k, vals.length).toFixed(1)},${fy(v).toFixed(1)}`).join(" ");
  const i = hv.i;
  return (
    <div className="wf-chartwrap" ref={hv.ref} onMouseMove={hv.onMove} onMouseLeave={hv.onLeave} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${Hd}`} width="100%" height={height} preserveAspectRatio="none">
        <line x1={PAD} y1={PAD} x2={W - PAD} y2={PAD} stroke="#e3dff0" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        <polygon points={`${PAD},${PAD} ${P} ${W - PAD},${PAD}`} fill="rgba(232,81,138,.16)" />
        <polyline points={P} fill="none" stroke="#e0518a" strokeWidth={2.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {i != null && <line x1={fx(i, vals.length)} y1={PAD} x2={fx(i, vals.length)} y2={Hd} stroke="#9f86ee" strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
      </svg>
      {i != null && (
        <>
          <span style={{ position: "absolute", left: `${leftPct(i, vals.length)}%`, top: `${(fy(vals[i]) / Hd) * height}px`, width: 9, height: 9, borderRadius: "50%", background: "#e0518a", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
          <div className="wf-tip" style={{ left: `${leftPct(i, vals.length)}%`, top: `${(fy(vals[i]) / Hd) * height}px` }}>
            <div className="d">{curve[i][0]}</div>
            <div>Drawdown <b className="text-loss">{pct(vals[i])}</b></div>
          </div>
        </>
      )}
    </div>
  );
}

export function Gauge({ pct, label, sub, size = 88, color = "#16151c" }:
  { pct: number; label: string; sub?: string; size?: number; color?: string }) {
  const r = 52, c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(1, pct)));
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" style={{ flex: "none" }}>
      <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(22,21,28,.16)" strokeWidth="12" />
      <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 60 60)" />
      <text x="60" y="58" textAnchor="middle" fontSize="21" fontWeight="800" fill="#16151c">{label}</text>
      {sub && <text x="60" y="76" textAnchor="middle" fontSize="11" fill="#5b6b1f">{sub}</text>}
    </svg>
  );
}
