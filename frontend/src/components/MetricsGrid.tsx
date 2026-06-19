import type { Summary } from "@/lib/types";
import { num, pct } from "@/lib/format";
import { StatCard } from "./StatCard";

export function MetricsGrid({ s }: { s: Summary }) {
  const tone = (x: number): "gain" | "loss" | "default" =>
    x > 0 ? "gain" : x < 0 ? "loss" : "default";
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <StatCard label="CAGR" value={pct(s.cagr)} tone={tone(s.cagr)}
        sub={`bench ${pct(s.benchmark_cagr)}`} />
      <StatCard label="Total Return" value={pct(s.total_return)} tone={tone(s.total_return)} />
      <StatCard label="Max Drawdown" value={pct(s.max_drawdown)} tone="loss"
        sub={s.max_dd_dates?.join(" → ")} />
      <StatCard label="Sharpe" value={num(s.sharpe)} sub={`sortino ${num(s.sortino)}`} />
      <StatCard label="Volatility" value={pct(s.volatility)} tone="muted" />
      <StatCard label="Win Rate" value={pct(s.win_rate)}
        sub={`${s.n_trades} trades`} />
      <StatCard label="Profit Factor" value={num(s.profit_factor)}
        sub={`avg win ${pct(s.avg_win)} / loss ${pct(s.avg_loss)}`} />
      <StatCard label="Annual Turnover" value={`${num(s.annual_turnover * 100, 0)}%`} tone="warn"
        sub={`avg hold ${num(s.avg_holding_days, 0)}d`} />
      <StatCard label="Active Return" value={pct(s.active_return)} tone={tone(s.active_return)}
        sub="vs benchmark" />
      <StatCard label="Exposure" value={pct(s.exposure)} tone="muted" />
    </div>
  );
}
