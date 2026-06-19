# ADR-005 — No authentication in v1: private, single-user, tunnel-gated

**Status:** accepted · **Date:** 2026-06-19

## Context
The platform is a personal cockpit for a single owner, hosted on vault7a. The owner explicitly
does not want a login in v1. Every page is `anonymous` in the spec.

## Decision
- **No application auth** in v1 (`auth.strategy = none`). Access is restricted at the network edge:
  the app is bound to the home LAN / behind the existing Cloudflare tunnel, never publicly exposed.
- Policy: `exposure = intranet-only`, `access_control = anonymous-ok`, `data_sensitivity = financial`.
- Secrets (future broker keys, any data-vendor tokens) live in env / a secrets store, never in code,
  and are not needed for the signals-only v1.

## Consequences
- Zero auth friction for the owner; matches the threat model (no public exposure, single user).
- **If** the app is ever exposed publicly, or multi-user is added, this ADR must be superseded and
  a real auth strategy added before that change ships (the 3→deploy gate requires auth if any page
  becomes non-anonymous).

## Amendment 2026-06-19 — exposed at the edge behind Authentik SSO
The cockpit is now reachable at **https://windfall-labs.vault7a.xyz** via the vault7a Cloudflare
tunnel, routed through **Authentik SSO** (embedded proxy outpost → upstream `http://192.168.1.10:8500`),
matching the owner's other personal apps (ottomate, cointrail, leaploop). The app still has **no
in-app login** — access control is enforced at the edge by Authentik (an unauthenticated request
redirects to the Authentik login flow). This is consistent with the original "tunnel-gated, never
unauthenticated-public" intent: it is *not* public-anonymous; it is SSO-gated. The frontend was
reworked to **single-origin** (browser calls `/api/*` on the cockpit host; Next.js proxies to the API
container) so it works through the tunnel with no hardcoded LAN address and no cross-origin. Do not
remove the Authentik gate or route the hostname directly to `:8500`.
