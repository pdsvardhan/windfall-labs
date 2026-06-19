import type { Trade } from "@/lib/types";
import { num, pct, signClass } from "@/lib/format";

const reasonChip: Record<string, string> = {
  stop: "border-loss/50 text-loss",
  target: "border-gain/50 text-gain",
  time: "border-warn/50 text-warn",
  rebalance: "border-border text-muted",
  end: "border-border text-muted",
};

export function TradesTable({ trades }: { trades: Trade[] }) {
  if (!trades.length) return <div className="text-muted text-sm">No trades.</div>;
  return (
    <div className="card scroll-y" style={{ maxHeight: 460 }}>
      <table className="data">
        <thead>
          <tr>
            <th>Ticker</th><th>Entry</th><th>Exit</th><th>Entry ₹</th><th>Exit ₹</th>
            <th>Return</th><th>R</th><th>Days</th><th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              <td className="text-fg">{t.ticker.replace(".NS", "")}</td>
              <td className="text-muted">{t.entry_date}</td>
              <td className="text-muted">{t.exit_date ?? "open"}</td>
              <td>{num(t.entry)}</td>
              <td>{t.exit !== null ? num(t.exit) : "—"}</td>
              <td className={signClass(t.return_pct)}>{pct(t.return_pct)}</td>
              <td className={signClass(t.r_multiple)}>{t.r_multiple !== null ? num(t.r_multiple) : "—"}</td>
              <td className="text-muted">{t.holding_days}</td>
              <td>
                <span className={`chip ${reasonChip[t.exit_reason] ?? "border-border text-muted"}`}>
                  {t.exit_reason}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
