# Raw ask (ambiguous)

> Can we add some kind of protection so we don't end up hosting bad links?
> Also maybe let people report broken or shady links.

This ask is vague on both axes that matter: what "bad links" means (the
threat model) and what "protection" should actually do (the mechanism).
This scenario deliberately shows a *contested* interpretation: the first
pass over-scopes it (see `scenario_input.NORMALIZED_REQUIREMENT_V1_OVERSCOPED`),
gets rejected at a human approval checkpoint on the requirements stage
itself (not just at release), and gets reworked into a scoped, defensible
interpretation (`NORMALIZED_REQUIREMENT_V2_SCOPED`) before any design or
implementation work happens against it.
