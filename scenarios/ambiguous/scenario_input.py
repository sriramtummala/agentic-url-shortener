"""Structured scenario input for the ambiguous 'protect against bad links'
ask.

Two versions of the interpreted requirement exist here on purpose:
NORMALIZED_REQUIREMENT_V1_OVERSCOPED is the first pass (deliberately
overreaching -- a third-party threat-intel dependency and a moderation
workflow nobody asked for), and NORMALIZED_REQUIREMENT_V2_SCOPED is the
reworked interpretation after a human rejected V1 at the requirements
stage's approval gate. See scenarios/ambiguous/step_1_propose_interpretation.py
and step_2_rework_after_rejection.py.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENT_TEXT = (
    "Can we add some kind of protection so we don't end up hosting bad links? "
    "Also maybe let people report broken or shady links."
)

NORMALIZED_REQUIREMENT_V1_OVERSCOPED = {
    "intent": (
        "Prevent malicious or harmful destination URLs from being shortened, and let users report "
        "existing short URLs they believe are unsafe, using automated threat detection plus a "
        "moderation workflow."
    ),
    "explicit_requirements": [
        "Detect and block malicious destination URLs at creation time",
        "Let anyone report an existing short URL as unsafe",
    ],
    "ambiguities": [
        {
            "question": "What does 'bad links' mean -- malicious/phishing, spam, illegal content, or something else?",
            "resolution": (
                "Interpreted broadly as 'unsafe or harmful' and addressed via integration with a "
                "third-party threat-intelligence API for real-time malicious-URL classification at "
                "creation time."
            ),
            "rationale": (
                "A third-party threat feed is the most thorough way to catch malicious URLs across "
                "categories without maintaining our own detection logic."
            ),
        },
        {
            "question": "What should 'some kind of protection' actually do -- block, warn, or flag for review?",
            "resolution": (
                "Block creation outright if the threat-intel API flags the URL, and route user reports "
                "into a moderation queue with an admin dashboard for manual review and takedown."
            ),
            "rationale": "A full review workflow gives moderators the most control over edge cases the automated check might miss.",
        },
    ],
    "assumptions": [
        "A third-party threat-intelligence API is an acceptable new external dependency for this feature.",
        "A moderation queue and admin review workflow are in scope for this pass.",
    ],
    "out_of_scope": [],
}

NORMALIZED_REQUIREMENT_V2_SCOPED = {
    "intent": (
        "Add a lightweight, self-contained safety mechanism: reject known-bad destination domains at "
        "creation time, and let users report an existing short URL so it gets auto-flagged (and blocked "
        "from redirecting) once enough independent reports accumulate -- no third-party dependency, no "
        "moderation-queue workflow."
    ),
    "explicit_requirements": [
        "Reject URL creation if the destination matches a configurable denylist of domains/substrings",
        "Let anyone report an existing short URL as unsafe",
        "Auto-flag (and stop redirecting) a URL once it accumulates enough independent reports",
    ],
    "ambiguities": [
        {
            "question": "What does 'bad links' mean -- malicious/phishing, spam, illegal content, or something else?",
            "resolution": (
                "Scoped down to a static, operator-maintained denylist of known-bad domains/substrings "
                "checked at creation time -- not automated threat classification."
            ),
            "rationale": (
                "REJECTED as originally scoped (see decision log): a third-party threat-intel API "
                "violates this project's own zero-external-dependency decision and is a far bigger "
                "commitment than 'some kind of protection' calls for. A denylist is simple, "
                "self-contained, and directly addresses known-bad destinations."
            ),
        },
        {
            "question": "Should a single report immediately block a link, or require a threshold?",
            "resolution": (
                "Require a configurable threshold (default 3) of reports before auto-flagging and "
                "blocking redirects. No moderator review/unflagging workflow in this pass."
            ),
            "rationale": (
                "A single-report trigger is trivially abusable (report a competitor's or coworker's "
                "legitimate link to take it down). A threshold raises the bar for abuse while still "
                "giving real reports weight. A moderation dashboard is a separate feature nobody asked "
                "for in this ask."
            ),
        },
    ],
    "assumptions": [
        "The denylist is a small, operator-maintained, static list for this prototype (no crowd-sourced or third-party feed).",
        "Flagged links stay flagged permanently in this pass -- no unflag/appeal workflow.",
    ],
    "out_of_scope": [
        "Third-party threat-intelligence integration",
        "Moderation queue / admin review dashboard",
        "Unflagging or appeals process",
    ],
}

DESIGN = {
    "overview": (
        "Two additions to the existing service: (1) a static denylist check on destination_url at "
        "creation time, rejecting known-bad domains/substrings; (2) a report endpoint that increments a "
        "per-URL report counter and auto-flags (blocking redirects) once a configurable threshold is "
        "reached. Both are self-contained -- no third-party services, no moderation UI."
    ),
    "components": [
        {"name": "Denylist", "responsibility": "static, configurable list of disallowed domain "
                                                  "substrings checked at creation time"},
        {"name": "ReportEndpoint", "responsibility": "POST /api/urls/{code}/report; increments "
                                                       "report_count and sets flagged once the "
                                                       "threshold is reached"},
        {"name": "RedirectHandler (updated)", "responsibility": "refuses to redirect a flagged URL "
                                                                  "(403) and never caches a flagged "
                                                                  "code"},
    ],
    "decisions": [
        {
            "decision": "Static, configurable denylist (domain/substring match) rather than automated threat classification",
            "rationale": "Directly implements the approved, scoped-down interpretation -- no external dependency, trivial to reason about and test.",
            "alternatives_considered": "Third-party threat-intel API (rejected during requirements review -- see requirements/spec.md)",
        },
        {
            "decision": "Report-count threshold (default 3) before auto-flagging, rather than single-report blocking",
            "rationale": "Raises the bar against a single malicious report taking down a legitimate link, while still giving real reports weight.",
            "alternatives_considered": "Immediate block on first report (rejected: trivially abusable)",
        },
        {
            "decision": "Flagging invalidates the redirect cache entry for that code",
            "rationale": "The cache is populated from pre-flag state; without invalidation a cached hit would keep redirecting a now-flagged link until the entry aged out on its own.",
            "alternatives_considered": "Checking flagged status on every cache hit too (rejected: defeats the point of the cache -- simpler to invalidate on flag, matching the existing delete-invalidates-cache pattern)",
        },
    ],
    "api_summary": [
        {"method": "POST", "path": "/api/urls/{code}/report",
         "description": "report a short URL; auto-flags it once the report threshold is met"},
    ],
}


def source_files() -> dict:
    paths = [
        "service/app/config.py",
        "service/app/denylist.py",
        "service/app/db.py",
        "service/app/schemas.py",
        "service/app/api/urls.py",
        "service/app/api/redirect.py",
    ]
    return {p: (_REPO_ROOT / p).read_text(encoding="utf-8") for p in paths}


def test_files() -> dict:
    paths = [
        "service/tests/test_denylist.py",
        "service/tests/test_reporting.py",
    ]
    return {p: (_REPO_ROOT / p).read_text(encoding="utf-8") for p in paths}


def doc_files() -> dict:
    changelog = _REPO_ROOT / "CHANGELOG.md"
    return {"CHANGELOG.md": changelog.read_text(encoding="utf-8")}
