export function StatCard({
  label, value, sub, tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "gain" | "loss" | "muted" | "warn";
}) {
  const toneClass =
    tone === "gain" ? "text-gain"
    : tone === "loss" ? "text-loss"
    : tone === "muted" ? "text-muted"
    : tone === "warn" ? "text-warn"
    : "text-fg";
  return (
    <div className="card px-4 py-3">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-semibold mono mt-1 ${toneClass}`}>{value}</div>
      {sub && <div className="text-xs text-muted mt-0.5 mono">{sub}</div>}
    </div>
  );
}
