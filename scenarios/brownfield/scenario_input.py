"""Structured scenario input for the brownfield rate-limit/idempotency fix.

Unlike the greenfield scenario_input (which snapshots the *entire*
service/app and service/tests trees as each stage's output), this one
snapshots only the changed/added files -- a brownfield change is a diff
against an existing codebase, not a resubmission of the whole thing, and
the artifacts here should read that way.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

CHANGED_SOURCE_FILE = _REPO_ROOT / "service" / "app" / "api" / "urls.py"
NEW_TEST_FILE = _REPO_ROOT / "service" / "tests" / "test_rate_limit_idempotency_interaction.py"


def source_files() -> dict:
    return {"service/app/api/urls.py": CHANGED_SOURCE_FILE.read_text(encoding="utf-8")}


def test_files() -> dict:
    return {
        "service/tests/test_rate_limit_idempotency_interaction.py": NEW_TEST_FILE.read_text(encoding="utf-8"),
    }


def doc_files() -> dict:
    return {"CHANGELOG.md": CHANGELOG_ENTRY}


def codebase_reasoning_input() -> dict:
    return {
        "scan_root": str(_REPO_ROOT / "service" / "app"),
        "change_keywords": ["enforce_rate_limit", "Idempotency-Key", "idempotency_key"],
        "change_summary": (
            "Investigate why POST /api/urls retries with a matching Idempotency-Key are "
            "being rate-limited, to find every file involved in the interaction between "
            "rate limiting and idempotency."
        ),
    }


CHANGELOG_ENTRY = (
    "# Changelog\n\n"
    "## Unreleased\n\n"
    "### Fixed\n"
    "- `POST /api/urls`: requests retried with a matching `Idempotency-Key` no "
    "longer consume rate-limit budget. Previously the rate limiter ran "
    "unconditionally before the idempotency cache-hit check, so a client's own "
    "safe retries could exhaust its rate-limit capacity and get `429`'d purely "
    "from retrying. Fresh (non-retried) requests are still rate-limited as before.\n"
)

REQUIREMENT_TEXT = (
    "Bug report from the integrations team: \"We're seeing our short-URL "
    "creation calls get 429'd (rate limited) more than we'd expect. We followed "
    "your docs and pass an Idempotency-Key on every POST /api/urls so our retry "
    "logic is safe, but it seems like the retries themselves are what's "
    "triggering the rate limit. Can someone look into this? We don't want to "
    "have to build our own client-side throttling on top of what should already "
    "be safe retries.\""
)

NORMALIZED_REQUIREMENT = {
    "intent": (
        "Diagnose and fix why POST /api/urls retries made with a matching "
        "Idempotency-Key count against the per-client rate limit, so that safe, "
        "documented retry behavior cannot itself trigger 429 responses."
    ),
    "explicit_requirements": [
        "Retrying a create request with the same Idempotency-Key must not consume additional rate-limit budget",
        "Genuinely new create requests must still be rate-limited as before (no regression in abuse protection)",
    ],
    "ambiguities": [
        {
            "question": (
                "\"Sometimes\" -- does this affect every idempotent retry, or only under specific "
                "conditions (e.g. only after the limiter is already near capacity)?"
            ),
            "resolution": (
                "Confirmed via code reading (see codebase_reasoning artifact) that it affects every "
                "idempotent retry unconditionally -- FastAPI's router-level dependency runs before the "
                "endpoint body on every request regardless of outcome. \"Sometimes\" in the report "
                "reflects when the reporter's client happened to be near its own capacity, not a "
                "conditional bug."
            ),
            "rationale": (
                "Reproduced with a dedicated regression test before making any code change (see "
                "service/tests/test_rate_limit_idempotency_interaction.py) rather than assuming scope "
                "from the bug report's wording alone."
            ),
        },
        {
            "question": "Should this be fixed by exempting idempotent requests, or by redesigning rate limiting entirely?",
            "resolution": (
                "Scoped fix only: move the rate-limit check to run after the idempotency cache-hit "
                "check, so it's skipped on a cache hit and still enforced on genuine new work. No "
                "change to the rate limiter's own logic, capacity, or key scheme."
            ),
            "rationale": (
                "The report describes one specific interaction bug, not a complaint about rate "
                "limiting's design generally -- a minimal, targeted fix is lower risk and faster to "
                "ship than a redesign nobody asked for."
            ),
        },
    ],
    "assumptions": [
        "The rate limiter's per-IP token-bucket design and default capacity are not in question here.",
        "No client-visible API contract changes: same endpoint, same headers, same response shapes.",
    ],
    "out_of_scope": [
        "Redesigning or replacing the rate limiter",
        "Applying the same idempotency-before-rate-limit ordering to any other endpoint (none of the "
        "other endpoints currently combine both concerns)",
    ],
}

DESIGN = {
    "overview": (
        "Root cause: POST /api/urls declared `dependencies=[Depends(enforce_rate_limit)]` at the route "
        "level, which FastAPI evaluates before the endpoint body runs, unconditionally -- including on "
        "requests that would have short-circuited via the Idempotency-Key cache. Fix: remove the "
        "router-level dependency and call enforce_rate_limit(request) manually inside the handler, "
        "after the idempotency cache-hit check, so it only runs for requests that are actually about "
        "to do new work."
    ),
    "components": [
        {"name": "ShortenAPI.create_url", "responsibility": "reordered so idempotency short-circuit is "
                                                              "checked before rate limiting is enforced"},
    ],
    "decisions": [
        {
            "decision": "Call enforce_rate_limit(request) manually inside create_url instead of as a "
                        "router-level dependency",
            "rationale": "Router-level dependencies always run before the handler body, with no way to "
                         "conditionally skip them after the fact; moving the call inline is the "
                         "smallest change that fixes the ordering.",
            "alternatives_considered": "Rate-limiting by (IP, idempotency key) pair so retries hit a "
                                        "separate always-available bucket (rejected: adds a second "
                                        "limiter dimension and its own capacity-planning question for "
                                        "a problem that's fully solved by correct ordering alone)",
        },
    ],
    "api_summary": [],
}
