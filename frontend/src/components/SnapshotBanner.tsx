import type { FundamentalsCoverage } from "@/lib/types";

// Always-on reminder that the Trendlyne fundamentals snapshot needs refreshing. Each missed
// month is DVM-backtest history that can never be recovered, so this surfaces right where the
// owner works (cockpit + data page). Renders nothing while the snapshot is fresh.
export function SnapshotBanner({ cov }: { cov?: FundamentalsCoverage | null }) {
  if (!cov) return null;
  const missing = !cov.latest;
  if (!missing && !cov.stale) return null;

  const detail = missing
    ? "No Trendlyne fundamentals snapshot is loaded yet — DVM and fundamental screens can't run until one is ingested."
    : `Latest snapshot is ${cov.latest_age_days} days old (${cov.latest}). Export a fresh Trendlyne "Data Downloader" file and run the ingest — every missed month is DVM backtest history you can't recover.`;

  return (
    <div className="card border-warn/50 px-4 py-3 text-sm">
      <span className="text-warn font-medium">
        Fundamentals snapshot {missing ? "missing" : "stale"}
      </span>
      <span className="text-muted"> — {detail}</span>
    </div>
  );
}
