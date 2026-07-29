# Architecture & Design

Builds on upstream requirement artifact(s): requirements/spec.md

## Overview

Root cause: POST /api/urls declared `dependencies=[Depends(enforce_rate_limit)]` at the route level, which FastAPI evaluates before the endpoint body runs, unconditionally -- including on requests that would have short-circuited via the Idempotency-Key cache. Fix: remove the router-level dependency and call enforce_rate_limit(request) manually inside the handler, after the idempotency cache-hit check, so it only runs for requests that are actually about to do new work.

## Components

- **ShortenAPI.create_url** — reordered so idempotency short-circuit is checked before rate limiting is enforced

## Key decisions

### Call enforce_rate_limit(request) manually inside create_url instead of as a router-level dependency
- Rationale: Router-level dependencies always run before the handler body, with no way to conditionally skip them after the fact; moving the call inline is the smallest change that fixes the ordering.
- Alternatives considered: Rate-limiting by (IP, idempotency key) pair so retries hit a separate always-available bucket (rejected: adds a second limiter dimension and its own capacity-planning question for a problem that's fully solved by correct ordering alone)

## API summary

| Method | Path | Description |
|---|---|---|
