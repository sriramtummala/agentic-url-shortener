# Normalized Requirement

## Raw ask

> We need a URL shortener service. Users should be able to submit a long URL and get back a short one that redirects to the original when visited. We also want to see how many times each short link gets used. It needs to be reliable — we don't want it going down or being slow, and obviously it shouldn't let people abuse it. Let's get a first version out in a few days.

## Interpreted intent

Provide a self-service HTTP API that converts long URLs into short, shareable codes which redirect to the original destination, with basic usage analytics and production-grade reliability safeguards (rate limiting, idempotency, health checks), suitable for a first internal release.

## Explicit requirements

- Accept a long URL and return a short code/URL
- Visiting the short URL redirects the caller to the original long URL
- Track how many times each short URL has been used
- The service must be reliable (available, fast) under normal load
- The service must not be easily abused (protect against excessive/malicious use)

## Ambiguities identified and resolved

- **Q:** How long / what format should the short code be?
  **Resolution:** 7-character base62 code (0-9, a-z, A-Z), generated randomly with a collision check.
  **Rationale:** ~3.5 trillion possible codes at 7 characters is enough for a first release without needing a longer code, and base62 keeps the resulting URL compact and URL-safe.
- **Q:** What does 'see how many times it's used' mean exactly -- unique visitors, raw hits, a time-series breakdown?
  **Resolution:** Track a raw click count plus a per-day time series and last-accessed timestamp. Unique-visitor dedup and referrer/geo breakdown are out of scope.
  **Rationale:** Raw counts plus daily buckets covers the stated need ('how many times') without requiring visitor identification, which would raise its own data-handling questions QT would need to sign off on separately.
- **Q:** What does 'reliable' mean in measurable terms (uptime target, latency budget)?
  **Resolution:** No formal SLA for the prototype; the implementation targets a fast in-process cache on the redirect hot-path and exposes a health check so a real SLA can be set once there's traffic to measure against.
  **Rationale:** The ask gives no target number, and inventing one wouldn't be defensible. Optimizing the hot path and exposing health/observability is the honest response to 'reliable' without a stated number.
- **Q:** What counts as 'abuse' and how should it be limited?
  **Resolution:** Per-client-IP rate limiting on URL creation, with a generous default limit.
  **Rationale:** Creation is the expensive, abusable operation (a write plus code generation); redirects are cheap reads and rate-limiting them would hurt legitimate traffic more than it would stop abuse.
- **Q:** Should short URLs expire, be deletable, or support custom aliases?
  **Resolution:** Support an optional expiration timestamp and deletion by the creator (via an opaque owner token returned at creation). Custom aliases are deferred.
  **Rationale:** Expiration and deletion are common, low-cost, high-value asks that fit the same data model. Custom aliases add a namespace-collision/moderation surface the ask didn't request and that's reasonable to defer.
- **Q:** Is authentication/authorization required?
  **Resolution:** No user accounts for v1 -- anyone can create a short URL, but deleting one requires the opaque owner token returned at creation time.
  **Rationale:** The ask never mentions accounts. An owner-token model gives basic self-service control without building a full auth system nobody asked for yet.

## Assumptions

- Single-instance/single-region deployment is acceptable for this prototype (no multi-region replication).
- SQLite is an acceptable persistence store for a first release; the data-access layer stays thin enough to swap in Postgres later without an API change.
- 'A first version in a few days' means iterative delivery -- core create/redirect first, analytics next, reliability hardening last -- not all three simultaneously.

## Out of scope

- Custom/vanity short codes
- User accounts and authentication
- Multi-region / high-availability deployment
- Detailed visitor analytics (geo, device, referrer, unique-visitor dedup)
