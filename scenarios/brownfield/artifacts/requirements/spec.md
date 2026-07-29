# Normalized Requirement

## Raw ask

> Bug report from the integrations team: "We're seeing our short-URL creation calls get 429'd (rate limited) more than we'd expect. We followed your docs and pass an Idempotency-Key on every POST /api/urls so our retry logic is safe, but it seems like the retries themselves are what's triggering the rate limit. Can someone look into this? We don't want to have to build our own client-side throttling on top of what should already be safe retries."

## Interpreted intent

Diagnose and fix why POST /api/urls retries made with a matching Idempotency-Key count against the per-client rate limit, so that safe, documented retry behavior cannot itself trigger 429 responses.

## Explicit requirements

- Retrying a create request with the same Idempotency-Key must not consume additional rate-limit budget
- Genuinely new create requests must still be rate-limited as before (no regression in abuse protection)

## Ambiguities identified and resolved

- **Q:** "Sometimes" -- does this affect every idempotent retry, or only under specific conditions (e.g. only after the limiter is already near capacity)?
  **Resolution:** Confirmed via code reading (see codebase_reasoning artifact) that it affects every idempotent retry unconditionally -- FastAPI's router-level dependency runs before the endpoint body on every request regardless of outcome. "Sometimes" in the report reflects when the reporter's client happened to be near its own capacity, not a conditional bug.
  **Rationale:** Reproduced with a dedicated regression test before making any code change (see service/tests/test_rate_limit_idempotency_interaction.py) rather than assuming scope from the bug report's wording alone.
- **Q:** Should this be fixed by exempting idempotent requests, or by redesigning rate limiting entirely?
  **Resolution:** Scoped fix only: move the rate-limit check to run after the idempotency cache-hit check, so it's skipped on a cache hit and still enforced on genuine new work. No change to the rate limiter's own logic, capacity, or key scheme.
  **Rationale:** The report describes one specific interaction bug, not a complaint about rate limiting's design generally -- a minimal, targeted fix is lower risk and faster to ship than a redesign nobody asked for.

## Assumptions

- The rate limiter's per-IP token-bucket design and default capacity are not in question here.
- No client-visible API contract changes: same endpoint, same headers, same response shapes.

## Out of scope

- Redesigning or replacing the rate limiter
- Applying the same idempotency-before-rate-limit ordering to any other endpoint (none of the other endpoints currently combine both concerns)
