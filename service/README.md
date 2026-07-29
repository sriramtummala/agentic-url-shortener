# URL Shortener Service

A small FastAPI service that converts long URLs into short, shareable codes,
redirects visitors to the original destination, tracks basic usage
analytics, and includes first-release reliability safeguards (rate
limiting, idempotent creation, a redirect cache, and a health check).

See `docs/architecture.md` (repo root) for the design rationale behind these
choices, and `scenarios/greenfield/scenario_input.py` for how the original
ask was interpreted.

## Setup

Requires Python 3.11+. From the repo root:

```
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
```

Run the service:

```
uvicorn service.app.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`, with interactive docs
at `http://127.0.0.1:8000/docs` (FastAPI's auto-generated OpenAPI UI).

Run the test suite:

```
pytest service/tests
```

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `URL_SHORTENER_DB` | `url_shortener.db` | Path to the SQLite database file |
| `URL_SHORTENER_RATE_LIMIT_CAPACITY` | `20` | Token-bucket burst capacity for URL creation, per client IP |
| `URL_SHORTENER_RATE_LIMIT_REFILL_PER_SECOND` | `0.5` | Token-bucket refill rate |
| `URL_SHORTENER_IDEMPOTENCY_TTL_SECONDS` | `300` | How long an `Idempotency-Key` is remembered |
| `URL_SHORTENER_REDIRECT_CACHE_SIZE` | `1024` | Max entries in the in-process redirect cache |
| `URL_SHORTENER_DENYLIST_DOMAINS` | `malware-example.test,phishing-example.test` | Comma-separated list of destination-domain/substring matches rejected at creation time |
| `URL_SHORTENER_REPORT_THRESHOLD` | `3` | Number of reports before a short URL is auto-flagged and blocked from redirecting |

## API Reference

### `POST /api/urls` -- create a short URL

Request body:
```json
{"destination_url": "https://example.com/some/long/path", "expires_at": "2027-01-01T00:00:00Z"}
```
`expires_at` is optional and must be in the future. An optional
`Idempotency-Key` header makes retries of this request safe -- a repeated
request with the same key returns the original result instead of minting a
second short code, and does not consume rate-limit budget. Returns `422` if
`destination_url` matches the configured denylist.

Response (`201 Created`):
```json
{
  "code": "aZ3kQ7x",
  "destination_url": "https://example.com/some/long/path",
  "owner_token": "3xU8...redacted...",
  "created_at": "2026-07-29T00:00:00+00:00",
  "expires_at": "2027-01-01T00:00:00+00:00"
}
```
`owner_token` is only ever returned here -- save it if you'll need to
delete the URL later. Rate-limited (`429 Too Many Requests`) per client IP.

### `GET /{code}` -- redirect

Redirects (`302 Found`) to the original URL and records a click. Returns
`404` if the code doesn't exist, `410 Gone` if it has expired, `403` if it
has been flagged (see the report endpoint below).

### `GET /api/urls/{code}` -- metadata

Returns the short URL's destination, creation time, expiry, and
moderation state (`report_count`, `flagged`), without redirecting or
counting as a click. `404`/`410` as above.

### `POST /api/urls/{code}/report` -- report a short URL

No request body. Increments the URL's report count; once it reaches
`URL_SHORTENER_REPORT_THRESHOLD` (default 3), the URL is auto-flagged and
subsequent redirects return `403` until further notice. There is currently
no unflagging/appeals endpoint. Response:
```json
{"code": "aZ3kQ7x", "report_count": 3, "flagged": true}
```

### `GET /api/urls/{code}/analytics` -- usage analytics

```json
{
  "code": "aZ3kQ7x",
  "click_count": 42,
  "last_accessed_at": "2026-07-29T12:00:00+00:00",
  "daily_clicks": [{"day": "2026-07-28", "count": 30}, {"day": "2026-07-29", "count": 12}]
}
```

### `DELETE /api/urls/{code}` -- delete

Requires an `X-Owner-Token` header matching the token returned at creation.
`403` if it doesn't match, `404` if the code doesn't exist. Also purges the
URL from the redirect cache and cascades deletion of its click history.

### `GET /health` -- health check

Returns `{"status": "ok"}` if the database is reachable, `503` otherwise.

## Known limitations

See `docs/testing_and_tradeoffs.md` (repo root) for the full list --
notably: no schema migration framework (adding columns/tables only affects
freshly created databases); the rate limiter/idempotency store/redirect
cache are in-process, so they reset on restart and don't coordinate across
multiple instances; and the denylist is a small static list with no
moderation/appeals workflow for flagged links (see
`scenarios/ambiguous/scenario_input.py` for why that scope was chosen).
