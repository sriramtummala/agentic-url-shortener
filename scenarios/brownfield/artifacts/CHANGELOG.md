# Changelog

## Unreleased

### Fixed
- `POST /api/urls`: requests retried with a matching `Idempotency-Key` no longer consume rate-limit budget. Previously the rate limiter ran unconditionally before the idempotency cache-hit check, so a client's own safe retries could exhaust its rate-limit capacity and get `429`'d purely from retrying. Fresh (non-retried) requests are still rate-limited as before.
