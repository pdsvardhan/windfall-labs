"use client";

import { useMemo, useState } from "react";

export interface Series {
  name: string;
  color: string;
  points: [string, number][];
  fill?: boolean;
}

interface Props {
  series: Series[];
  height?: number;
  yFormat?: (v: number) => string;
  zeroLine?: boolean;
}

export function LineChart({ series, height = 280, yFormat = (v) => v.toFixed(0), zeroLine }: Props) {
  const W = 1000;
  const H = height;
  const pad = { l: 64, r: 16, t: 12, b: 28 };

  const { paths, yMin, yMax, xFirst, xLast } = useMemo(() => {
    const all = series.flatMap((s) => s.points.map((p) => p[1])).filter((v) => Number.isFinite(v));
    let lo = Math.min(...all, zeroLine ? 0 : Infinity);
    let hi = Math.max(...all, zeroLine ? 0 : -Infinity);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1; }
    if (lo === hi) { hi = lo + 1; }
    const span = hi - lo;
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    const x = (i: number, n: number) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
    const y = (v: number) => pad.t + innerH - ((v - lo) / span) * innerH;

    const paths = series.map((s) => {
      const n = s.points.length;
      const line = s.points
        .map((p, i) => `${i === 0 ? "M" : "L"}${x(i, n).toFixed(1)},${y(p[1]).toFixed(1)}`)
        .join(" ");
      const area = s.fill && n > 0
        ? `${line} L${x(n - 1, n).toFixed(1)},${y(zeroLine ? 0 : lo).toFixed(1)} L${x(0, n).toFixed(1)},${y(zeroLine ? 0 : lo).toFixed(1)} Z`
        : null;
      return { ...s, line, area };
    });

    const first = series[0]?.points[0]?.[0] ?? "";
    const last = series[0]?.points[series[0].points.length - 1]?.[0] ?? "";
    return { paths, yMin: lo, yMax: hi, xFirst: first, xLast: last };
  }, [series, H, zeroLine]);

  const [hover, setHover] = useState(false);
  const yTicks = [yMax, (yMax + yMin) / 2, yMin];

  return (
    <div className="w-full" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
        {yTicks.map((t, i) => {
          const yy = pad.t + (H - pad.t - pad.b) * (i / (yTicks.length - 1));
          return (
            <g key={i}>
              <line x1={pad.l} x2={W - pad.r} y1={yy} y2={yy} stroke="#1F2630" strokeWidth={1} />
              <text x={pad.l - 8} y={yy + 4} textAnchor="end" fontSize={12} fill="#8B949E" className="mono">
                {yFormat(t)}
              </text>
            </g>
          );
        })}
        {paths.map((p) => (
          <g key={p.name}>
            {p.area && <path d={p.area} fill={p.color} opacity={0.12} />}
            <path d={p.line} fill="none" stroke={p.color} strokeWidth={1.6} opacity={hover ? 1 : 0.9} />
          </g>
        ))}
        <text x={pad.l} y={H - 8} fontSize={11} fill="#8B949E" className="mono">{xFirst}</text>
        <text x={W - pad.r} y={H - 8} textAnchor="end" fontSize={11} fill="#8B949E" className="mono">{xLast}</text>
      </svg>
      <div className="flex gap-4 mt-1 px-2">
        {series.map((s) => (
          <span key={s.name} className="text-xs text-muted flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}
