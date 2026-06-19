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
