# Testing Approach, Limitations, and Trade-offs

## Testing approach

**108 tests, 97% line coverage** across `orchestrator/` and `service/app/`
(see `docs/coverage_report.txt` for the full per-file breakdown;
regenerate with `pytest orchestrator/tests service/tests --cov=orchestrator
--cov=service --cov-report=term-missing`).

The suite is layered by what it's actually proving:

- **Orchestrator unit tests** (`orchestrator/tests/`) exercise the engine
  in isolation from the URL shortener entirely -- toy graphs, fake
  deterministic agents (`SucceedAgent`, `FlakyAgent`, `AlwaysFailAgent`,
  `ConcurrentTrackingAgent`, `RecordingAgent`), and a fake injectable
  clock/id generator for deterministic timestamps. This is what proves the
  *orchestration engine itself* is correct, independent of the product
  built with it: real thread-pool concurrency (not simulated), retry/
  fallback/rollback/safe-stop semantics, the approval-gate resume/reject
  flow, guardrail dispatch and fail-closed behavior, dynamic re-planning
  (including graph mutation via `insert_stage`), and the CLI.
- **Service unit tests** cover each reliability primitive in isolation
  (`test_rate_limiter.py`, `test_idempotency.py`, `test_cache.py`) with
  injectable clocks, plus a dedicated concurrency suite
  (`test_concurrency.py`) that spawns real threads against the rate
  limiter/cache/idempotency store and asserts on outcomes that would only
  be wrong under a real race (e.g. a shared rate-limit key never allows
  more than its capacity across 200 concurrent callers).
- **Service integration tests** exercise the FastAPI app through
  `TestClient` end-to-end per feature area (`test_urls_api.py`,
  `test_redirect.py`, `test_analytics.py`, `test_reliability.py`,
  `test_reporting.py`, `test_denylist.py`), plus a full user-journey test
  (`test_lifecycle.py`: create -> metadata -> redirect x5 -> analytics ->
  delete -> verify everything 404s) and an OpenAPI-schema smoke test.
- **Red-green regression tests** for both real bugs found during this
  project (see below) -- each one was written to fail against the
  then-current code first, confirmed to fail, then the fix was applied and
  the test confirmed to pass, rather than writing test-and-fix together and
  trusting they matched.

## Bugs found and fixed during this project

Documenting these because they're evidence the validation was real, not
performative -- each was caught by actually running the suite or by
inspecting real output, not assumed away.

1. **Stale artifact versions leaking to consumers.** `_collect_upstream_artifacts`
   returned every historical version of every artifact path after a stage
   re-executed (e.g. via re-planning), not just the latest. Fixed by
   collapsing to the newest version per path (`_latest_by_path` in
   `executor.py`); regression test in `test_replanning.py`.
2. **Approval-resume leaving the run stuck.** After an approval was
   resolved out-of-band, calling `Executor.run()` again didn't reset the
   leftover `PAUSED_APPROVAL` run status before re-checking layers, so it
   bailed out immediately even though nothing was still blocked. Fixed in
   `executor.py`'s `run()`; caught by `test_high_impact_stage_blocks_on_approval_then_resumes`
   during initial development (Task 2), before it ever reached a real scenario.
3. **Connection leak in the orchestrator test suite.** Several test files
   never closed their `StateStore`'s sqlite3 connection, producing
   `ResourceWarning`s. Fixed with a single autouse fixture in
   `orchestrator/tests/conftest.py` that tracks and closes every
   `StateStore` created during a test, rather than touching every test
   individually. Verified by re-running the suite with
   `-W error::ResourceWarning`.
4. **Idempotent retries consuming rate-limit budget (the brownfield bug).**
   `POST /api/urls` applied rate limiting as a router-level FastAPI
   dependency, which always runs before the endpoint body -- including
   before the idempotency-key cache-hit check. A client safely retrying
   with the documented `Idempotency-Key` pattern could exhaust its own
   rate-limit budget purely from retrying. Reproduced with a failing test
   first (`test_rate_limit_idempotency_interaction.py`), root-caused via a
   real static-analysis scan (`scenarios/brownfield/artifacts/analysis/impact.md`),
   fixed by moving the rate-limit check inline after the idempotency
   short-circuit.
5. **Stale approvals silently carrying forward across re-planning.**
   Approval ids were scoped only to `(run, stage, gate)`, so invalidating a
   stage that had already been approved (e.g. re-syncing greenfield's
   `implementation` stage after Task 12 added test files) would leave the
   *old* approval in place, which the next execution would silently honor
   -- a real change-control violation (approving version N shouldn't
   approve version N+1). Fixed by adding a `StageState.incarnation` counter
   and scoping approval ids to `(run, stage, gate, incarnation)`; regression
   test `test_approval_does_not_carry_forward_across_incarnations`.
6. **Resuming an exit-gate-blocked stage re-ran the agent.** Discovered
   while reviewing the ambiguous scenario's run report (`requirements`
   showed `attempts=2` when only one real execution should have happened).
   An entry-gate block means the agent never ran; an exit-gate block means
   it already ran and produced artifacts -- resuming should re-check the
   gate against that existing output, not re-invoke the agent. For the
   deterministic stand-in this was merely wasteful; for the pluggable
   Claude adapter it would mean a duplicate paid API call every time
   someone checks on approval status. Fixed in `executor.py`
   (`_recheck_blocked_exit_gate`); regression test
   `test_exit_gate_approval_resume_does_not_rerun_agent`.

## Known limitations

- **No schema migration framework.** `service/app/db.py`'s `CREATE TABLE IF
  NOT EXISTS` / column additions only take effect on a freshly created
  database file. A real deployment would need Alembic or equivalent before
  shipping a schema change against a live database.
- **In-process reliability primitives.** The rate limiter, idempotency
  store, and redirect cache all live in process memory. They reset on
  restart and don't coordinate across multiple service instances -- fine
  for this prototype's zero-external-deps decision, not fine for a
  multi-instance production deployment (Redis would be the natural next
  step, as noted in `docs/architecture.md`'s decision table).
- **`Database` opens and closes a sqlite3 connection per call** rather than
  pooling one. Simple and safe under FastAPI's sync-endpoint threadpool at
  this prototype's scale; would need a real connection pool (or an async
  driver) under real load.
- **Static denylist, no moderation workflow.** The ambiguous scenario's
  "protection against bad links" feature is a deliberately scoped-down
  interpretation (see `scenarios/ambiguous/scenario_input.py`): an
  operator-maintained static list and a report-threshold auto-flag, with no
  unflagging/appeals process and no third-party threat intelligence. This
  was an explicit, human-approved scope decision, not an oversight.
- **Deterministic agents replay pre-authored content; they don't perform
  novel synthesis.** By design (see `docs/architecture.md`), the
  "intelligence" in a deterministic run is captured once in
  `scenario_input` and templated into artifacts reproducibly. The
  `ClaudeAgent` adapter is the path for live, novel generation from a
  model, and is unit-tested against a fake `anthropic` module (parsing,
  error handling) but never called against the real API in this repo's
  tests -- that would require network access, a paid key, and would make
  test runs non-deterministic.
- **Safe-stop doesn't preempt an in-flight stage.** It's checked at layer
  boundaries; a stage already dispatched to the thread pool runs to
  completion. This matches how real workflow engines (Step Functions,
  Temporal) behave, but is worth stating plainly as a limitation rather
  than implying true interrupt-anywhere semantics.
- **CLI has no interactive/TUI mode.** `orchestrator/cli.py` is a scriptable
  argparse tool (list/decide approvals, print audit log/decisions/metrics),
  not a dashboard. Sufficient for this exercise's governance demonstration;
  a real operational tool would likely want a web UI over the same
  `StateStore` queries.

## Trade-offs made explicitly, with reasoning

These are all documented at the point of decision (scenario_input files,
architecture.md's decision table, or inline comments) rather than only
here, but are worth restating together:

- **SQLite over Postgres/Redis** for zero external dependencies, at the
  cost of not being representative of a real multi-instance production
  deployment.
- **Deterministic agents by default over always-live LLM calls**, for
  reproducibility and zero cost/network dependency to run or evaluate this
  project, at the cost of the deterministic path not demonstrating novel
  requirement interpretation at runtime (that capability lives in
  `ClaudeAgent`, exercised by unit tests but not run live here).
- **Diff-scoped artifacts for brownfield/ambiguous vs. full-tree snapshots
  for greenfield's initial build** -- consistent with what each stage
  actually did, at the cost of the artifact model being slightly less
  uniform across scenarios (a reader has to know which pattern a given
  scenario uses).
- **A scoped, self-contained "bad link protection" feature over an
  ML/third-party-integrated one** -- the ambiguous scenario's core
  demonstration: this was a real human decision (reject + rework), not a
  pre-scripted outcome, and the rejected interpretation is preserved in the
  decision log rather than deleted.
