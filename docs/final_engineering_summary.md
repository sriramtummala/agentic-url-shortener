# Final Engineering Summary

## Plan and rationale

The task decomposed into two tracks, executed in order: **Phase 1** built
the orchestration engine itself (7 tasks: graph/state model, executor,
approval checkpoints, policy guardrails, observability, dynamic
re-planning, agent adapters) as a fully domain-agnostic system, validated
by its own unit tests before any URL-shortener code existed. **Phase 2**
used that engine to actually build the service (5 tasks: requirements/
design, core APIs, analytics, reliability, docs/release), deliberately
re-using the re-planning machinery (`invalidate_downstream`) to grow the
implementation across tasks rather than writing the whole service in one
shot. **Phases 3-5** then ran the three required scenarios (brownfield,
ambiguous) and produced this documentation set.

Every logical task in this plan was implemented behind an explicit
checkpoint -- the user approved starting each one before it began, and (for
this exercise) also stood in as the human reviewer for every governance
decision the system itself required (release approvals, an interpretation
rejection, a rework approval). That dual role -- directing the plan *and*
exercising the approval gates -- is the actual "controlled autonomy"
principle in action: the agent proposed and executed; the human decided
what shipped.

## Artifacts produced

- **Orchestration engine**: `orchestrator/` -- 14 modules, 108 tests, 97%
  coverage (shared with the service; see `docs/coverage_report.txt`).
- **URL shortener service**: `service/app/` -- FastAPI app with 6 endpoints
  (create, redirect, metadata, delete, analytics, report), backed by
  SQLite, with rate limiting, idempotency, a redirect cache, health check,
  and a static denylist/report-flagging safety mechanism. Full reference in
  `service/README.md`.
- **Three scenario runs**, each with real, committed, run-produced
  artifacts (not hand-written after the fact) under `scenarios/<name>/artifacts/`
  and a markdown audit report at `scenarios/<name>/report.md`:
  - **Greenfield**: 6 stages, 40 decisions, 48 audit events, 100% success
    rate, 0 retries, 0 rollbacks. Built incrementally across 4 re-plan
    cycles as features were added.
  - **Brownfield**: 7 stages (adds `codebase_reasoning`), 15 decisions, 17
    audit events, 100% success rate. Fixed a real bug found by inspection,
    reproduced with a failing test first.
  - **Ambiguous**: 6 stages, 18 decisions, 22 audit events, 100% success
    rate, 1 retry (the requirements stage's second incarnation after
    rework -- not a failure retry, a governed rework). Includes a genuine
    reject-then-approve cycle on the interpretation itself.
- **Documentation**: this file, `docs/architecture.md`,
  `docs/testing_and_tradeoffs.md`, `docs/coverage_report.txt`,
  `service/README.md`, `CHANGELOG.md`, plus this project's root `README.md`.

## Risks, trade-offs, and validation

Covered in full in `docs/testing_and_tradeoffs.md`; the highlights:

- **Validation was empirical, not assumed.** Six real bugs were found and
  fixed during this project (listed with root cause and fix in
  `docs/testing_and_tradeoffs.md`), three of them by actually running the
  three scenarios end-to-end and inspecting the resulting state/artifacts
  rather than trusting the code once it was written. The brownfield bug
  specifically was reproduced with a failing test *before* any fix was
  written.
- **Every release decision in this project was a real approval-gate
  resolution**, not a scripted stand-in: greenfield's release, brownfield's
  release, and the ambiguous scenario's interpretation (rejected once,
  reworked, approved) and release. Rejections required a rationale by
  construction (`StateStore.resolve_approval` raises otherwise), and
  approvals require a `human:`-prefixed actor by construction -- an agent
  cannot self-approve through this code path.
- **Key trade-off**: deterministic stand-in agents by default (reproducible,
  zero-cost, zero-network) vs. live LLM generation (the pluggable
  `ClaudeAgent`, unit-tested but not exercised against a real API key in
  this repo). This means the deterministic runs replay engineering
  judgment captured in `scenario_input`, rather than deriving it fresh each
  run -- an explicit, stated limitation, not a hidden one.
- **Key trade-off**: SQLite and in-process reliability primitives
  everywhere, for a zero-external-dependency prototype, at the cost of not
  being representative of a multi-instance production deployment.

## Assumptions

- Single-instance/single-region deployment is acceptable for this
  prototype (stated explicitly in the greenfield requirements spec).
- SQLite is an acceptable persistence store for a first release, with the
  data-access layer kept thin enough to swap in Postgres later without an
  API change.
- No user authentication system exists yet; owner-token-based control (a
  secret returned once at creation) is sufficient self-service protection
  for delete, matching what the original ask actually requested.
- The three scenarios' bugs/features (rate-limit/idempotency interaction,
  bad-link protection) are the intended shape of "brownfield" and
  "ambiguous" for this exercise -- reasonable, realistic choices given the
  existing codebase, but choices nonetheless, documented at the point they
  were made (see each scenario's `scenario_input.py`).

## Limitations

See `docs/testing_and_tradeoffs.md` for the complete list. In one sentence
each: no schema migration framework; in-process-only rate limiter/
idempotency/cache (no cross-instance coordination); per-call (not pooled)
SQLite connections; a static denylist with no moderation/appeals workflow
(an explicit, approved scope decision); deterministic agents replay rather
than synthesize; safe-stop is checkpoint-boundary, not mid-instruction
preemption; and the operator CLI is scriptable, not a dashboard.

## What a QuikTrip reviewer should do next

This is a prototype built for an evaluation exercise, not a production
deployment decision -- the choices above (SQLite, in-process primitives, a
static denylist) were made for that context and should be revisited before
any real production use. A QT engineer should:
1. Run the test suite and the three scenarios themselves (`README.md` has
   exact commands) to verify these claims rather than taking this document
   at face value.
2. Decide whether the deterministic-agent default or the live-Claude-API
   path is the right fit for any real adoption of this orchestration
   pattern -- that's a cost/reproducibility trade-off a human should own.
3. Treat every "Approved" decision recorded in this session's scenario
   runs as what it is: a review performed inside this exercise, not a
   substitute for whatever QT's actual change-management process requires
   before real deployment.
