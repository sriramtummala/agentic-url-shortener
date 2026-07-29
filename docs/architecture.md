# Architecture Overview

This document covers: the components, the orchestration model, control
flow through one execution pass, and the key design decisions with their
rationale. It assumes you've skimmed the root `README.md` for how to run
things.

## Two layers, one dependency direction

```
scenarios/  --uses-->  orchestrator/  (generic engine)
    |
    +--produces/evolves-->  service/  (the actual product)
```

`orchestrator/` has zero knowledge of URL shorteners. Every scenario
(`scenarios/greenfield`, `scenarios/brownfield`, `scenarios/ambiguous`)
supplies: a `TaskGraph` (which stages exist, how they depend on each other,
what gates guard them), a `scenario_input` dict (the engineering judgment
-- interpreted requirements, design decisions, actual source code -- that
stage agents format into artifacts), and an agent registry. This
separation is what makes the orchestrator itself the reusable, evaluable
artifact, independent of the fact that this particular exercise is a URL
shortener.

## Orchestrator components

| Module | Responsibility |
|---|---|
| `models.py` | The static graph (`TaskGraph`, `StageDefinition`, `GateSpec`) and dynamic run state (`RunState`, `StageState`, `ArtifactRef`, `DecisionRecord`). Validates the graph is acyclic and computes topological layers -- the unit of parallel execution. |
| `state_store.py` | SQLite-backed persistence for everything: run/stage state, decision lineage, artifacts, a free-form audit log, and the human-approval queue. One connection per `StateStore`, guarded by a lock since stages within a layer run on separate threads. |
| `executor.py` | Walks the graph layer by layer. Runs all stages in a layer concurrently (`ThreadPoolExecutor`), applies entry/exit gates, bounded retries with backoff, a one-shot fallback agent, propagates unrecoverable failure to everything downstream (`SKIPPED`), and supports explicit rollback and a sticky safe-stop. |
| `gates.py` | The gate *mechanism*: `GateRunner` dispatches each `GateSpec` to either the pluggable `GuardrailEngine` (POLICY/AUTOMATED_CHECK) or `ApprovalGateHandler` (APPROVAL, always -- policy engines never see approval gates). |
| `guardrails.py` | Concrete POLICY rules: secret scanning, a dangerous-construct blocklist (`eval`, `os.system`, `shell=True`, ...), a PII/PCI-shaped-value scanner, and a required-artifacts completeness check. Fails *closed*: an unregistered rule name fails the gate rather than passing it. |
| `replanning.py` | Dynamic re-planning: `invalidate_downstream` (upstream input changed outside normal failure/retry -- mark stale, cascade) and `insert_stage` (splice a brand-new stage into a *live* run's persisted graph, with its own gates). |
| `observability.py` | Reliability metrics (success rate, retry/rollback frequency, MTTR, end-to-end latency) computed purely from persisted state, plus a markdown report renderer. |
| `cli.py` | The human-facing surface: list/decide approvals, inspect runs, print the decision-lineage and audit log, print metrics/reports. |
| `agents/` | `base.py` defines the `Agent` protocol. `deterministic.py` has one stand-in agent per SDLC stage (see "Deterministic vs. live agents" below). `claude_adapter.py` is the pluggable real-LLM path. `registry.py` wires stage names to deterministic agents. |

## The orchestration model

**Explicit dependency graph with entry/exit gates.** A `TaskGraph` is a
dict of `StageDefinition`s, each declaring `depends_on` (direct
dependencies only -- artifact collection is scoped to direct deps, not
transitive ones, so a stage must declare everything it actually consumes),
`entry_gates` and `exit_gates` (lists of `GateSpec`, each POLICY,
AUTOMATED_CHECK, or APPROVAL), and a `retry_policy`.

**Sequential and parallel paths with synchronization.**
`TaskGraph.topological_layers()` groups stages into layers where every
stage in layer N depends only on stages in layers < N. The executor
processes layers in order and runs every stage within a layer concurrently
-- this is real thread-pool concurrency
(`test_independent_stages_run_concurrently` proves overlap via a shared
counter, not just that the layering logic looks right on paper). A layer
boundary is therefore also the synchronization barrier: nothing in layer
N+1 starts until every stage in layer N has resolved.

**Human approval checkpoints for high-impact actions.** Any
`StageDefinition` with `high_impact=True` must carry an `APPROVAL` gate on
either its entry or exit gates -- enforced by a pydantic validator at
construction time, not by convention. Two distinct placements are used
across the three scenarios:
- **Entry-gate approval** (greenfield, brownfield `release_readiness`):
  approve *before* the stage runs -- a release action shouldn't happen at
  all without sign-off.
- **Exit-gate approval** (ambiguous `requirements`): approve the stage's
  *output* -- the agent proposes an interpretation, and nothing downstream
  can consume it until a human signs off. Resuming a stage blocked on an
  exit gate re-checks the gate against the artifacts it already produced;
  it does **not** re-run the agent (a real bug found and fixed during this
  project -- see `docs/testing_and_tradeoffs.md`).

Approval identity is structurally enforced, not just conventionally: `resolve_approval` in
`state_store.py` rejects any resolver whose actor string doesn't start with
`human:`, and rejections must carry a rationale comment. An agent cannot
self-approve a high-impact action through this code path.

**Bounded retries, fallback, rollback, safe-stop** are four deliberately
distinct controls:
- *Retry*: bounded re-attempts of the same stage (`RetryPolicy.max_attempts`, with backoff).
- *Fallback*: one extra attempt with a different agent after retries are exhausted.
- *Rollback* (`Executor.rollback_stage`): an explicit, human/replanning-triggered
  action that invalidates a *previously passed* stage and everything downstream,
  marking them stale for re-execution.
- *Safe-stop* (`Executor.request_safe_stop` / `resume_from_safe_stop`): a
  sticky, run-level halt checked at every layer boundary. It does not
  preempt an in-flight stage (a real limitation, documented, and consistent
  with how real workflow engines like Step Functions/Temporal behave --
  they cancel at safe points, not mid-instruction).

An unrecoverable failure (retries + fallback exhausted, or an entry/exit
gate outright rejects) marks the stage `FAILED` and propagates `SKIPPED` to
everything downstream -- that branch is dead until a human intervenes via
rollback or re-planning.

**Dynamic re-planning while maintaining governance.** Two operations, both
recorded as decisions with full rationale and both taking effect on the
*next* `Executor.run()` call (the executor reloads the graph from the store
at the top of every pass specifically so this works without reconstructing
it):
- `invalidate_downstream`: upstream input changed for a reason other than
  "the stage failed" (a human edited a doc, a rejected interpretation gets
  reworked). Marks the stage and its transitive downstream stale.
- `insert_stage`: the original plan didn't account for some piece of work
  (a brownfield impact analysis reveals an extra dependency). Splices a new
  stage into the *persisted* graph, wired to block whichever stages should
  wait on it -- and the inserted stage can carry its own gates, including
  approval, so re-planned work is still fully governed.

Crucially, **approvals don't silently carry forward across re-planning**.
Every stage tracks an `incarnation` counter, bumped whenever it's rolled
back or invalidated. The approval id is scoped to
`(run, stage, gate, incarnation)`, so a human's sign-off on incarnation 0
of a stage's output is never read as approving a materially different
incarnation 1 later. This was a real gap found and fixed mid-project (see
`docs/testing_and_tradeoffs.md`) after the greenfield scenario's
`implementation`/`test` stages were re-synced post-approval and the release
gate would otherwise have silently stayed "approved."

**Policy guardrails for security, compliance, and change control.**
`PolicyGuardrailEngine` dispatches each POLICY/AUTOMATED_CHECK `GateSpec` to
a named rule (`config={"rule": "secret_scan"}`, etc.) and fails closed on
an unregistered rule name -- a misconfigured guardrail must never silently
become a no-op. The PII scanner is a direct, deliberate nod to QuikTrip's
own data-handling policy (no PII/PCI/PHI in tooling inputs): it blocks
SSN-shaped and card-number-shaped literals from ever landing in a generated
artifact.

**Audit-grade observability and traceability.** Every stage attempt, gate
evaluation, retry, rollback, and human decision is a `DecisionRecord`
(actor, action, rationale, timestamp, linked artifact ids) plus a
free-form audit event. `observability.py` computes success rate,
retry/rollback frequency, MTTR (mean gap between a failure-ish decision and
the subsequent `stage_passed`), and end-to-end latency purely by reading
this trail back -- the executor doesn't need to know observability exists.

## Control flow through one `Executor.run()` pass

```
run()
 |- if run status == PAUSED_SAFE_STOP: return immediately (sticky, needs explicit resume)
 |- if run status == PAUSED_APPROVAL: reset to RUNNING (calling run() again IS the resume signal)
 |- reload graph from the state store (picks up any re-planning since the last call)
 |- for each topological layer:
     |- check safe-stop again (a stage's own agent may have requested it)
     |- for each actionable stage in the layer (PENDING / STALE / BLOCKED_APPROVAL):
     |   |- skip immediately if a direct dependency FAILED/SKIPPED (propagate)
     |   |- otherwise dispatch to a thread pool -- all stages in the layer run concurrently
     |       |- if resuming a stage blocked on an EXIT gate: re-check the gate against
     |       |   existing artifacts, don't re-run the agent
     |       |- else: evaluate entry gates -> run agent (retry/fallback loop) -> evaluate exit gates
     |- if any stage in the layer ended BLOCKED_APPROVAL: pause the whole run, return
 |- once every layer is processed: finalize (COMPLETED if everything PASSED/SKIPPED, else FAILED)
```

## Key design decisions

| Decision | Rationale | Alternative considered |
|---|---|---|
| Python + FastAPI + Pydantic for the service | Automatic OpenAPI generation satisfies the API/schema deliverable directly; matches the orchestrator's own stack | Flask (no built-in schema validation); Node/Express (would split the stack across two languages for no benefit here) |
| SQLite for both the orchestrator's state store and the service's persistence | Zero external services required to run the whole prototype end-to-end -- a deliberate, explicit trade-off (see setup-decision record early in this project) | Postgres/Redis via Docker (more production-realistic, but adds a hard dependency for anyone evaluating this) |
| Deterministic stand-in agents by default, Claude API as an explicit opt-in | Reproducible, no API key/network/cost required to run or evaluate the whole project; the *engineering judgment* (interpreted requirements, design decisions, actual code) is captured once as reviewable `scenario_input` data and replayed deterministically | Always calling a live LLM (non-reproducible runs, cost/latency/network dependency for every evaluator run) |
| Artifacts are diff-scoped for brownfield/ambiguous, full-tree for greenfield's initial build | A brownfield/ambiguous change is a diff against an existing codebase; snapshotting the whole tree would misattribute unrelated files to a scoped change | Always snapshotting the full tree (simpler code, but dishonest about what a stage actually did) |
| Approval id scoped to `(stage, gate, incarnation)` | Prevents a stale approval from silently carrying forward across re-planning (a real bug found and fixed) | A fixed `(stage, gate)` id (simpler, but exactly the bug) |
| `insert_stage`/`invalidate_downstream` require only a `StateStore`, not a full `Executor` | Re-planning is often triggered by something outside the execution loop entirely (a human editing a doc, a CLI command) -- it shouldn't need an agent registry to do that | Making replanning a method on `Executor` only |

## Where this stops short of "production"

See `docs/testing_and_tradeoffs.md` for the full list. The short version:
no schema migration framework, in-process-only reliability primitives (rate
limiter/idempotency/cache reset on restart and don't coordinate across
instances), a static denylist instead of real threat intelligence, and the
Claude adapter's live-generation path is untested against a real API key in
this repo's CI (by design -- see that document for why).
