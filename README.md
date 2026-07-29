# Agentic Software Engineering System -- URL Shortener

A working prototype of an agentic SDLC orchestration system, demonstrated
by using it to build, evolve, and fix a URL shortener service across three
scenarios: **greenfield** (build from scratch), **brownfield** (fix a real
bug in the existing service), and **ambiguous** (a vague ask that requires
interpretation, gets challenged, and gets reworked).

This is a two-layer project:

- **`orchestrator/`** -- the agentic orchestration engine: a dependency
  graph of SDLC stages with entry/exit gates, bounded retries/fallback,
  explicit rollback and re-planning, human approval checkpoints, policy
  guardrails, and audit-grade observability. This is the "critical
  differentiator" piece and is entirely domain-agnostic -- nothing in it
  knows what a URL shortener is.
- **`service/`** -- the actual URL shortener API (FastAPI + SQLite),
  produced by running scenarios through the orchestrator.

See `docs/architecture.md` for how the pieces fit together and why, and
`docs/final_engineering_summary.md` for the full plan/rationale/risk
write-up expected of this exercise.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e ".[dev]"
```

Optional extra, only needed if you want the orchestrator's agents to call
the real Claude API instead of the deterministic stand-ins (see
`docs/architecture.md` for what that means):

```bash
pip install -e ".[claude]"
export ANTHROPIC_API_KEY=...  # required at call time, not at install time
```

### Run the tests

```bash
pytest orchestrator/tests service/tests
# with coverage:
pytest orchestrator/tests service/tests --cov=orchestrator --cov=service --cov-report=term-missing
```

108 tests, 97% line coverage on application code. See
`docs/testing_and_tradeoffs.md` for the testing approach and
`docs/coverage_report.txt` for the full per-file breakdown.

### Run the actual URL shortener service

```bash
uvicorn service.app.main:app --reload
```

API at `http://127.0.0.1:8000`, interactive docs at
`http://127.0.0.1:8000/docs`. Full API reference in `service/README.md`.

## Running the three scenarios

Each scenario is a small, runnable Python module under `scenarios/`. Every
run is persisted to its own SQLite state file
(`scenarios/<name>/run_state/state.db`, gitignored -- regenerate by
re-running the scripts below) and produces real, committed artifacts under
`scenarios/<name>/artifacts/` plus a markdown audit report at
`scenarios/<name>/report.md`.

### Greenfield -- build the service from scratch

Demonstrates non-linear, incrementally-grown orchestration: the graph
starts with just `requirements` -> `design`, and stages get *inserted* into
the live run as each slice of work (core APIs, then analytics, then
reliability hardening, then docs/release) becomes ready.

```bash
python -m scenarios.greenfield.run                              # requirements + design
python -m scenarios.greenfield.step_09_add_core_implementation   # + implementation, test
python -m scenarios.greenfield.step_10_add_analytics             # re-plan: analytics added
python -m scenarios.greenfield.step_11_add_reliability           # re-plan: reliability added
python -m scenarios.greenfield.step_13_add_docs_and_release_gate # + documentation, release gate
```

The last step pauses at `PAUSED_APPROVAL` on `release_readiness` (a
`high_impact` stage with an approval gate). Resolve it:

```bash
python -m orchestrator.cli --db scenarios/greenfield/run_state/state.db approvals list --run greenfield-run-1
python -m orchestrator.cli --db scenarios/greenfield/run_state/state.db approvals decide <approval_id> \
    --by <your-name> --status approved --comment "..."
python -m scenarios.greenfield.run   # resume
```

### Brownfield -- fix a real bug in the existing service

Demonstrates codebase reasoning: a `codebase_reasoning` stage does a real
static-analysis scan of `service/app/` to identify impacted files for a bug
report, before any fix is designed. The whole graph is built upfront here
(a scoped, understood fix), in contrast to greenfield's incremental growth.

```bash
python -m scenarios.brownfield.run
```

Pauses at `release_readiness`'s approval gate; resolve the same way as
above (`--db scenarios/brownfield/run_state/state.db`, run id
`brownfield-run-1`), then re-run `python -m scenarios.brownfield.run`.

### Ambiguous -- an interpretation gets challenged and reworked

Demonstrates governance applied to *understanding* the ask, not just to
release: the `requirements` stage itself is `high_impact` with an approval
gate on its *output* (an exit gate, not an entry gate). The first proposed
interpretation is deliberately over-scoped; a human can reject it, at which
point it's reworked and resubmitted as a fresh incarnation.

```bash
python -m scenarios.ambiguous.step_1_propose_interpretation
# review scenarios/ambiguous/artifacts/requirements/spec.md, then:
python -m orchestrator.cli --db scenarios/ambiguous/run_state/state.db approvals decide <approval_id> \
    --by <your-name> --status rejected --comment "..."   # rejection requires a rationale
python -m scenarios.ambiguous.step_2_rework_after_rejection
# review the reworked spec, then approve it and the later release gate:
python -m orchestrator.cli --db scenarios/ambiguous/run_state/state.db approvals decide <approval_id> \
    --by <your-name> --status approved --comment "..."
python -m scenarios.ambiguous.step_3_resume
# ... approve release_readiness the same way, then step_3_resume again
```

## Inspecting a run

```bash
python -m orchestrator.cli --db <scenario>/run_state/state.db runs show <run_id>
python -m orchestrator.cli --db <scenario>/run_state/state.db decisions <run_id>   # full decision lineage
python -m orchestrator.cli --db <scenario>/run_state/state.db audit <run_id>       # audit event log
python -m orchestrator.cli --db <scenario>/run_state/state.db metrics <run_id>     # reliability metrics
python -m orchestrator.cli --db <scenario>/run_state/state.db report <run_id>      # render the markdown report
```

## Repository layout

```
orchestrator/           the agentic orchestration engine (domain-agnostic)
  models.py              TaskGraph / StageDefinition / RunState / gates -- the static + dynamic data model
  executor.py             walks the graph: retries, fallback, rollback, safe-stop, parallel execution
  gates.py + guardrails.py   entry/exit gate mechanism + concrete policy rules (secrets/PII/dangerous-code scans)
  replanning.py           dynamic re-planning: invalidate downstream work, insert new stages mid-run
  observability.py        reliability metrics + audit-grade run reports
  cli.py                  operator CLI: approvals, audit log, decisions, metrics
  agents/                 deterministic stand-in agents + optional Claude API adapter
  tests/                  108 tests total across orchestrator + service

service/                 the URL shortener product itself
  app/                    FastAPI app: create/redirect/metadata/delete, analytics, rate limiting,
                          idempotency, redirect cache, health check, denylist + report-flagging
  tests/                  unit, integration, concurrency, lifecycle, OpenAPI-schema tests
  README.md               full API reference + setup for the service specifically

scenarios/               the three required scenarios, each with real committed artifacts
  greenfield/ brownfield/ ambiguous/

docs/                    architecture, testing/trade-offs, final engineering summary, coverage snapshot
CHANGELOG.md             real changelog, updated by the brownfield and ambiguous scenarios
```
