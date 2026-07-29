# Normalized Requirement

## Raw ask

> Can we add some kind of protection so we don't end up hosting bad links? Also maybe let people report broken or shady links.

## Interpreted intent

Add a lightweight, self-contained safety mechanism: reject known-bad destination domains at creation time, and let users report an existing short URL so it gets auto-flagged (and blocked from redirecting) once enough independent reports accumulate -- no third-party dependency, no moderation-queue workflow.

## Explicit requirements

- Reject URL creation if the destination matches a configurable denylist of domains/substrings
- Let anyone report an existing short URL as unsafe
- Auto-flag (and stop redirecting) a URL once it accumulates enough independent reports

## Ambiguities identified and resolved

- **Q:** What does 'bad links' mean -- malicious/phishing, spam, illegal content, or something else?
  **Resolution:** Scoped down to a static, operator-maintained denylist of known-bad domains/substrings checked at creation time -- not automated threat classification.
  **Rationale:** REJECTED as originally scoped (see decision log): a third-party threat-intel API violates this project's own zero-external-dependency decision and is a far bigger commitment than 'some kind of protection' calls for. A denylist is simple, self-contained, and directly addresses known-bad destinations.
- **Q:** Should a single report immediately block a link, or require a threshold?
  **Resolution:** Require a configurable threshold (default 3) of reports before auto-flagging and blocking redirects. No moderator review/unflagging workflow in this pass.
  **Rationale:** A single-report trigger is trivially abusable (report a competitor's or coworker's legitimate link to take it down). A threshold raises the bar for abuse while still giving real reports weight. A moderation dashboard is a separate feature nobody asked for in this ask.

## Assumptions

- The denylist is a small, operator-maintained, static list for this prototype (no crowd-sourced or third-party feed).
- Flagged links stay flagged permanently in this pass -- no unflag/appeal workflow.

## Out of scope

- Third-party threat-intelligence integration
- Moderation queue / admin review dashboard
- Unflagging or appeals process
