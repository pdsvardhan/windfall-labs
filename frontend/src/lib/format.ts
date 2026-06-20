export const pct = (x: number | null | undefined, dp = 2): string =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(dp)}%`;

// signed percent, e.g. +24.6%
export const pctSigned = (x: number | null | undefined, dp = 1): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const v = x * 100;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(dp)}%`;
};

export const num = (x: number | null | undefined, dp = 2): string =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : x.toFixed(dp);

export const money = (x: number | null | undefined): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return "₹" + x.toLocaleString("en-IN", { maximumFractionDigits: 0 });
};

// Indian-format compact for large rupee figures (lakh/crore).
export const moneyCompact = (x: number | null | undefined): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const abs = Math.abs(x);
  if (abs >= 1e7) return `₹${(x / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(x / 1e5).toFixed(2)} L`;
  return money(x);
};

export const signClass = (x: number | null | undefined): string =>
  x === null || x === undefined || Number.isNaN(x)
    ? "text-ink"
    : x > 0
      ? "text-gain"
      : x < 0
        ? "text-loss"
        : "text-muted";

export const dateShort = (s: string | null | undefined): string =>
  !s ? "—" : new Date(s).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
