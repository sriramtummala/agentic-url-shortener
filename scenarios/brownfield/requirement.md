# Raw ask (brownfield)

> Bug report from the integrations team:
>
> "We're seeing our short-URL creation calls get 429'd (rate limited) more
> than we'd expect. We followed your docs and pass an Idempotency-Key on
> every POST /api/urls so our retry logic is safe, but it seems like the
> retries themselves are what's triggering the rate limit. Can someone look
> into this? We don't want to have to build our own client-side throttling
> on top of what should already be safe retries."

This is the unedited bug report fed into the `requirements` stage as
`scenario_input["requirement_text"]`. Unlike the greenfield ask, this
targets the *existing* service (built in the greenfield scenario) -- the
work here is diagnosis and a scoped fix, not new feature design, which is
why this scenario's graph looks different (see graph.py): it adds a
`codebase_reasoning` stage and skips upfront architecture work in favor of
investigating the actual code first.
