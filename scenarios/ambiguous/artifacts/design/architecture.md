# Architecture & Design

Builds on upstream requirement artifact(s): requirements/spec.md

## Overview

Two additions to the existing service: (1) a static denylist check on destination_url at creation time, rejecting known-bad domains/substrings; (2) a report endpoint that increments a per-URL report counter and auto-flags (blocking redirects) once a configurable threshold is reached. Both are self-contained -- no third-party services, no moderation UI.

## Components

- **Denylist** — static, configurable list of disallowed domain substrings checked at creation time
- **ReportEndpoint** — POST /api/urls/{code}/report; increments report_count and sets flagged once the threshold is reached
- **RedirectHandler (updated)** — refuses to redirect a flagged URL (403) and never caches a flagged code

## Key decisions

### Static, configurable denylist (domain/substring match) rather than automated threat classification
- Rationale: Directly implements the approved, scoped-down interpretation -- no external dependency, trivial to reason about and test.
- Alternatives considered: Third-party threat-intel API (rejected during requirements review -- see requirements/spec.md)

### Report-count threshold (default 3) before auto-flagging, rather than single-report blocking
- Rationale: Raises the bar against a single malicious report taking down a legitimate link, while still giving real reports weight.
- Alternatives considered: Immediate block on first report (rejected: trivially abusable)

### Flagging invalidates the redirect cache entry for that code
- Rationale: The cache is populated from pre-flag state; without invalidation a cached hit would keep redirecting a now-flagged link until the entry aged out on its own.
- Alternatives considered: Checking flagged status on every cache hit too (rejected: defeats the point of the cache -- simpler to invalidate on flag, matching the existing delete-invalidates-cache pattern)

## API summary

| Method | Path | Description |
|---|---|---|
| POST | /api/urls/{code}/report | report a short URL; auto-flags it once the report threshold is met |
