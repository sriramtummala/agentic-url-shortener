"""Structured scenario input for the greenfield URL-shortener build.

NORMALIZED_REQUIREMENT and DESIGN are the actual engineering-judgment
artifacts for this scenario -- the interpretation of the raw ask and the
architecture decisions made in response to it. The requirements/design
deterministic agents just format these into artifacts; the judgment calls
live here, in plain reviewable data, so they can be read/edited/argued with
independently of the orchestration mechanics.

SOURCE_FILES / TEST_FILES read the real, living code under service/app and
service/tests off disk rather than duplicating it here -- the orchestrator
artifact is a faithful snapshot of the actual repo code, not a second copy
that could drift from it. Their contents grow as later steps (see
step_1_add_core_implementation.py, step_2_add_analytics.py,
step_3_add_reliability.py) add files under those directories; DOC_FILES is
added in step_4_add_docs_and_release_gate.py.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE_APP_ROOT = _REPO_ROOT / "service" / "app"
_SERVICE_TESTS_ROOT = _REPO_ROOT / "service" / "tests"


def _read_tree(root: Path) -> dict:
    """Read every .py file under root into {"service/<...>": content},
    keyed relative to the repo's service/ directory so artifact paths mirror
    the real file layout."""
    files = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_REPO_ROOT / "service")
        files[f"service/{rel.as_posix()}"] = path.read_text(encoding="utf-8")
    return files


def source_files() -> dict:
    return _read_tree(_SERVICE_APP_ROOT)


def test_files() -> dict:
    return _read_tree(_SERVICE_TESTS_ROOT)


def doc_files() -> dict:
    readme = _REPO_ROOT / "service" / "README.md"
    return {"service/README.md": readme.read_text(encoding="utf-8")}


REQUIREMENT_TEXT = (
    "We need a URL shortener service. Users should be able to submit a long URL "
    "and get back a short one that redirects to the original when visited. We "
    "also want to see how many times each short link gets used. It needs to be "
    "reliable — we don't want it going down or being slow, and obviously it "
    "shouldn't let people abuse it. Let's get a first version out in a few days."
)

NORMALIZED_REQUIREMENT = {
    "intent": (
        "Provide a self-service HTTP API that converts long URLs into short, "
        "shareable codes which redirect to the original destination, with basic "
        "usage analytics and production-grade reliability safeguards (rate "
        "limiting, idempotency, health checks), suitable for a first internal "
        "release."
    ),
    "explicit_requirements": [
        "Accept a long URL and return a short code/URL",
        "Visiting the short URL redirects the caller to the original long URL",
        "Track how many times each short URL has been used",
        "The service must be reliable (available, fast) under normal load",
        "The service must not be easily abused (protect against excessive/malicious use)",
    ],
    "ambiguities": [
        {
            "question": "How long / what format should the short code be?",
            "resolution": "7-character base62 code (0-9, a-z, A-Z), generated randomly with a collision check.",
            "rationale": (
                "~3.5 trillion possible codes at 7 characters is enough for a first release "
                "without needing a longer code, and base62 keeps the resulting URL compact and URL-safe."
            ),
        },
        {
            "question": (
                "What does 'see how many times it's used' mean exactly -- unique visitors, "
                "raw hits, a time-series breakdown?"
            ),
            "resolution": (
                "Track a raw click count plus a per-day time series and last-accessed timestamp. "
                "Unique-visitor dedup and referrer/geo breakdown are out of scope."
            ),
            "rationale": (
                "Raw counts plus daily buckets covers the stated need ('how many times') without "
                "requiring visitor identification, which would raise its own data-handling questions "
                "that would need separate sign-off."
            ),
        },
        {
            "question": "What does 'reliable' mean in measurable terms (uptime target, latency budget)?",
            "resolution": (
                "No formal SLA for the prototype; the implementation targets a fast in-process cache "
                "on the redirect hot-path and exposes a health check so a real SLA can be set once "
                "there's traffic to measure against."
            ),
            "rationale": (
                "The ask gives no target number, and inventing one wouldn't be defensible. Optimizing "
                "the hot path and exposing health/observability is the honest response to 'reliable' "
                "without a stated number."
            ),
        },
        {
            "question": "What counts as 'abuse' and how should it be limited?",
            "resolution": "Per-client-IP rate limiting on URL creation, with a generous default limit.",
            "rationale": (
                "Creation is the expensive, abusable operation (a write plus code generation); "
                "redirects are cheap reads and rate-limiting them would hurt legitimate traffic more "
                "than it would stop abuse."
            ),
        },
        {
            "question": "Should short URLs expire, be deletable, or support custom aliases?",
            "resolution": (
                "Support an optional expiration timestamp and deletion by the creator (via an opaque "
                "owner token returned at creation). Custom aliases are deferred."
            ),
            "rationale": (
                "Expiration and deletion are common, low-cost, high-value asks that fit the same data "
                "model. Custom aliases add a namespace-collision/moderation surface the ask didn't "
                "request and that's reasonable to defer."
            ),
        },
        {
            "question": "Is authentication/authorization required?",
            "resolution": (
                "No user accounts for v1 -- anyone can create a short URL, but deleting one requires "
                "the opaque owner token returned at creation time."
            ),
            "rationale": (
                "The ask never mentions accounts. An owner-token model gives basic self-service "
                "control without building a full auth system nobody asked for yet."
            ),
        },
    ],
    "assumptions": [
        "Single-instance/single-region deployment is acceptable for this prototype (no multi-region replication).",
        "SQLite is an acceptable persistence store for a first release; the data-access layer stays thin "
        "enough to swap in Postgres later without an API change.",
        "'A first version in a few days' means iterative delivery -- core create/redirect first, "
        "analytics next, reliability hardening last -- not all three simultaneously.",
    ],
    "out_of_scope": [
        "Custom/vanity short codes",
        "User accounts and authentication",
        "Multi-region / high-availability deployment",
        "Detailed visitor analytics (geo, device, referrer, unique-visitor dedup)",
    ],
}

DESIGN = {
    "overview": (
        "A FastAPI service backed by SQLite, exposing a small REST API to create and resolve short "
        "URLs. An in-process LRU cache sits in front of the redirect path for low-latency hot lookups. "
        "Per-IP rate limiting guards the create endpoint, an idempotency-key store makes create safely "
        "retryable, and a health endpoint reports DB connectivity. Analytics are recorded inline on "
        "each redirect (one cheap write) and served via a read endpoint."
    ),
    "components": [
        {"name": "ShortenAPI", "responsibility": "POST /api/urls (create) and GET /api/urls/{code} (metadata); "
                                                  "validates input and applies rate limiting"},
        {"name": "RedirectHandler", "responsibility": "GET /{code}; resolves the short code cache-first, issues "
                                                       "an HTTP redirect, and records a click"},
        {"name": "AnalyticsService", "responsibility": "aggregates and serves click counts and a per-day "
                                                        "time series for a short URL"},
        {"name": "CodeGenerator", "responsibility": "generates collision-checked base62 short codes"},
        {"name": "RateLimiter", "responsibility": "in-memory token-bucket limiter keyed by client IP, applied "
                                                   "to the create endpoint"},
        {"name": "IdempotencyStore", "responsibility": "tracks recently-seen Idempotency-Key values so "
                                                        "retried creates return the original result instead "
                                                        "of a duplicate short code"},
        {"name": "Cache", "responsibility": "in-process LRU cache mapping code -> destination + expiry, "
                                             "invalidated on delete/expiry"},
        {"name": "HealthCheck", "responsibility": "GET /health verifies DB connectivity"},
    ],
    "decisions": [
        {
            "decision": "Use FastAPI + Pydantic for the API layer",
            "rationale": "Automatic OpenAPI schema generation directly satisfies the API/schema-definition "
                         "deliverable, and it's the stack already standardized on for this project.",
            "alternatives_considered": "Flask (no built-in schema validation/OpenAPI); Django (too heavyweight "
                                        "for this scope)",
        },
        {
            "decision": "Use SQLite for persistence",
            "rationale": "Zero external services required to run the prototype end-to-end, matching this "
                         "project's infra-footprint decision.",
            "alternatives_considered": "Postgres+Docker (adds a hard dependency evaluators must install); "
                                        "in-memory only (doesn't survive a restart, not representative of a "
                                        "real reliability story)",
        },
        {
            "decision": "7-character random base62 code with a uniqueness check and bounded retry on collision",
            "rationale": "Collision probability is negligible at this code-space size for a first release; "
                         "bounded retry keeps creation latency predictable.",
            "alternatives_considered": "Sequential/incrementing IDs encoded to base62 (rejected: predictable "
                                        "and enumerable -- any visitor could guess adjacent codes and scrape "
                                        "other users' links)",
        },
        {
            "decision": "In-process LRU cache in front of redirect lookups",
            "rationale": "The redirect path is the hottest, most latency-sensitive path (every click hits "
                         "it); caching keeps it fast without an external cache dependency.",
            "alternatives_considered": "Redis (violates the zero-external-deps decision for this prototype; "
                                        "the natural next step if this goes to real production traffic)",
        },
        {
            "decision": "Per-IP token-bucket rate limiting on URL creation only",
            "rationale": "Matches the resolved ambiguity that creation, not redirection, is the operation "
                         "worth protecting.",
            "alternatives_considered": "A global rate limit (would throttle legitimate multi-tenant usage "
                                        "unfairly)",
        },
        {
            "decision": "Idempotency-Key header support on create",
            "rationale": "Network retries on a write endpoint are routine; without this, a client retrying "
                         "a timed-out create would mint a second short URL for the same input.",
            "alternatives_considered": "No idempotency support (rejected: pushes the correctness burden onto "
                                        "every caller)",
        },
        {
            "decision": "Owner token (opaque secret returned at creation) required for delete",
            "rationale": "Gives basic self-service control without building full authentication, matching "
                         "the resolved ambiguity on auth.",
            "alternatives_considered": "No protection on delete (anyone could delete anyone's link); full "
                                        "user accounts (out of scope per requirement)",
        },
    ],
    "api_summary": [
        {"method": "POST", "path": "/api/urls", "description": "create a short URL from a long URL "
                                                                 "(optional expires_at, Idempotency-Key)"},
        {"method": "GET", "path": "/{code}", "description": "redirect to the original URL, recording a click"},
        {"method": "GET", "path": "/api/urls/{code}", "description": "fetch metadata without redirecting"},
        {"method": "DELETE", "path": "/api/urls/{code}", "description": "delete a short URL (requires owner token)"},
        {"method": "GET", "path": "/api/urls/{code}/analytics", "description": "click count + per-day time series"},
        {"method": "GET", "path": "/health", "description": "service health check"},
    ],
}
