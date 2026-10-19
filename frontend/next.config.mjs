/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // A backtest takes ~40-60s; the default 30s proxy timeout made the UI report a 500 for runs that actually succeeded and saved.
  experimental: { proxyTimeout: 900_000 },
  // Single-origin: the browser calls /api/* on this host; Next proxies to the API container
  // internally. This makes the cockpit work both on the LAN and through the Cloudflare tunnel
  // (Authentik SSO) without a hardcoded LAN IP, and avoids cross-origin entirely.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://api:8503/api/:path*" },
      { source: "/health", destination: "http://api:8503/health" },
    ];
  },
};
export default nextConfig;
