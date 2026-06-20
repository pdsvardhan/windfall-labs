"use client";

// Lightweight hand-rolled SVG charts — no chart lib, matching the Pastel Pop line aesthetic.

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

export function EquityChart({ strategy, benchmark, height = 220 }:
  { strategy: [string, number][]; benchmark?: [string, number][]; height?: number }) {
  const W = 560, H = 200;
  const sv = strategy.map((d) => d[1]);
  if (!sv.length) return <div className="text-faint text-sm">No equity data.</div>;
  // normalize both series onto the same scale (combined min/max)
  const bvRaw = (benchmark || []).map((d) => d[1]);
  // rebase benchmark to strategy's starting capital so the lines are comparable
  let bv: number[] = [];
  if (bvRaw.length) {
    const b0 = bvRaw[0] || 1; const s0 = sv[0] || 1;
    bv = bvRaw.map((x) => (x / b0) * s0);
  }
  const all = [...sv, ...bv];
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  // build with shared scale
  const scaled = (vals: number[]) =>
    vals.map((v, i) => {
      const x = (i / (vals.length - 1 || 1)) * (W - 16) + 8;
      const y = H - 8 - ((v - lo) / span) * (H - 16);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  const sPts = scaled(sv);
  const bPts = bv.length ? scaled(bv) : "";
  const last = sPts.split(" ").slice(-1)[0]?.split(",") || ["0", "0"];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none">
      <defs>
        <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#b9d24a" stopOpacity=".38" />
          <stop offset="1" stopColor="#b9d24a" stopOpacity="0" />
        </linearGradient>
      </defs>
      {sPts && <polygon points={`${sPts} ${W - 8},${H} 8,${H}`} fill="url(#eqfill)" />}
      {bPts && <polyline points={bPts} fill="none" stroke="#c3bdd0" strokeWidth={2.5} strokeDasharray="5 5" />}
      <polyline points={sPts} fill="none" stroke="#16151c" strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={5} fill="#16151c" />
    </svg>
  );
}

export function DrawdownChart({ curve, height = 200 }: { curve: [string, number][]; height?: number }) {
  const W = 560, H = 180;
  const vals = curve.map((d) => d[1]); // negative fractions
  if (!vals.length) return <div className="text-faint text-sm">No drawdown data.</div>;
  const lo = Math.min(...vals, 0); // most negative
  const span = Math.abs(lo) || 1;
  const P = vals.map((v, i) => {
    const x = (i / (vals.length - 1 || 1)) * (W - 16) + 8;
    const y = 8 + (Math.abs(v) / span) * (H - 16); // 0 at top, deepest at bottom
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none">
      <line x1="8" y1="8" x2={W - 8} y2="8" stroke="#e3dff0" strokeWidth={1.5} />
      <polygon points={`8,8 ${P} ${W - 8},8`} fill="rgba(232,81,138,.16)" />
      <polyline points={P} fill="none" stroke="#e0518a" strokeWidth={2.5} strokeLinejoin="round" />
    </svg>
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
