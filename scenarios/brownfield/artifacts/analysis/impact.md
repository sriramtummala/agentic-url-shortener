# Codebase Impact Analysis

Change: Investigate why POST /api/urls retries with a matching Idempotency-Key are being rate-limited, to find every file involved in the interaction between rate limiting and idempotency.
Searched for keyword(s): enforce_rate_limit, Idempotency-Key, idempotency_key

## Impacted files

- api/urls.py
- dependencies.py
- idempotency.py
