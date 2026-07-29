# Architecture & Design

Builds on upstream requirement artifact(s): requirements/spec.md

## Overview

A FastAPI service backed by SQLite, exposing a small REST API to create and resolve short URLs. An in-process LRU cache sits in front of the redirect path for low-latency hot lookups. Per-IP rate limiting guards the create endpoint, an idempotency-key store makes create safely retryable, and a health endpoint reports DB connectivity. Analytics are recorded inline on each redirect (one cheap write) and served via a read endpoint.

## Components

- **ShortenAPI** — POST /api/urls (create) and GET /api/urls/{code} (metadata); validates input and applies rate limiting
- **RedirectHandler** — GET /{code}; resolves the short code cache-first, issues an HTTP redirect, and records a click
- **AnalyticsService** — aggregates and serves click counts and a per-day time series for a short URL
- **CodeGenerator** — generates collision-checked base62 short codes
- **RateLimiter** — in-memory token-bucket limiter keyed by client IP, applied to the create endpoint
- **IdempotencyStore** — tracks recently-seen Idempotency-Key values so retried creates return the original result instead of a duplicate short code
- **Cache** — in-process LRU cache mapping code -> destination + expiry, invalidated on delete/expiry
- **HealthCheck** — GET /health verifies DB connectivity

## Key decisions

### Use FastAPI + Pydantic for the API layer
- Rationale: Automatic OpenAPI schema generation directly satisfies the API/schema-definition deliverable, and it's the stack already standardized on for this project.
- Alternatives considered: Flask (no built-in schema validation/OpenAPI); Django (too heavyweight for this scope)

### Use SQLite for persistence
- Rationale: Zero external services required to run the prototype end-to-end, matching this project's infra-footprint decision.
- Alternatives considered: Postgres+Docker (adds a hard dependency evaluators must install); in-memory only (doesn't survive a restart, not representative of a real reliability story)

### 7-character random base62 code with a uniqueness check and bounded retry on collision
- Rationale: Collision probability is negligible at this code-space size for a first release; bounded retry keeps creation latency predictable.
- Alternatives considered: Sequential/incrementing IDs encoded to base62 (rejected: predictable and enumerable -- any visitor could guess adjacent codes and scrape other users' links)

### In-process LRU cache in front of redirect lookups
- Rationale: The redirect path is the hottest, most latency-sensitive path (every click hits it); caching keeps it fast without an external cache dependency.
- Alternatives considered: Redis (violates the zero-external-deps decision for this prototype; the natural next step if this goes to real production traffic)

### Per-IP token-bucket rate limiting on URL creation only
- Rationale: Matches the resolved ambiguity that creation, not redirection, is the operation worth protecting.
- Alternatives considered: A global rate limit (would throttle legitimate multi-tenant usage unfairly)

### Idempotency-Key header support on create
- Rationale: Network retries on a write endpoint are routine; without this, a client retrying a timed-out create would mint a second short URL for the same input.
- Alternatives considered: No idempotency support (rejected: pushes the correctness burden onto every caller)

### Owner token (opaque secret returned at creation) required for delete
- Rationale: Gives basic self-service control without building full authentication, matching the resolved ambiguity on auth.
- Alternatives considered: No protection on delete (anyone could delete anyone's link); full user accounts (out of scope per requirement)

## API summary

| Method | Path | Description |
|---|---|---|
| POST | /api/urls | create a short URL from a long URL (optional expires_at, Idempotency-Key) |
| GET | /{code} | redirect to the original URL, recording a click |
| GET | /api/urls/{code} | fetch metadata without redirecting |
| DELETE | /api/urls/{code} | delete a short URL (requires owner token) |
| GET | /api/urls/{code}/analytics | click count + per-day time series |
| GET | /health | service health check |
