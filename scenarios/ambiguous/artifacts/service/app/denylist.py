"""Static, operator-maintained denylist check for destination URLs.

Deliberately simple (substring match against a configurable list) per the
scoped-down interpretation of "protection against bad links" -- see
scenarios/ambiguous/scenario_input.py for why automated threat
classification via a third-party API was rejected in favor of this.
"""


def is_denylisted(destination_url: str, denylist_domains: list[str]) -> bool:
    lowered = destination_url.lower()
    return any(domain in lowered for domain in denylist_domains if domain)
