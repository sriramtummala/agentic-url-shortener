# Changelog

## Unreleased

### Added
- `POST /api/urls/{code}/report`: report a short URL as unsafe, broken, or shady. Once a URL
  accumulates enough independent reports (default threshold: 3, `URL_SHORTENER_REPORT_THRESHOLD`),
  it is auto-flagged and redirects are blocked (`403`) until further notice. Flagging also evicts the
  URL from the redirect cache so the block takes effect immediately.
- URL creation now rejects destinations matching an operator-maintained denylist of domains/substrings
  (`URL_SHORTENER_DENYLIST_DOMAINS`), returning `422`.

## 2026-07-29

### Fixed
- `POST /api/urls`: requests retried with a matching `Idempotency-Key` no longer consume rate-limit
  budget. Previously the rate limiter ran unconditionally before the idempotency cache-hit check, so a
  client's own safe retries could exhaust its rate-limit capacity and get `429`'d purely from retrying.
  Fresh (non-retried) requests are still rate-limited as before.
