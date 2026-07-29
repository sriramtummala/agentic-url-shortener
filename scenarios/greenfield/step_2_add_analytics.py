"""Step 2: analytics (click tracking, per-day series, GET
/api/urls/{code}/analytics) has been added to service/app. The
implementation and test stages already passed once in step 1 -- this is a
genuine "upstream input changed" case, not a fresh run, so it goes through
Replanner.invalidate_downstream rather than insert_stage: the stages are
marked stale and re-execute, re-applying the now-expanded code/tests.

scenario_input.source_files()/test_files() re-read service/app and
service/tests off disk on every call, so nothing else needs updating here --
re-running the executor after invalidation picks up the new files
automatically.

Usage: python -m scenarios.greenfield.step_2_add_analytics
"""

from __future__ import annotations

from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.guardrails import PolicyGuardrailEngine
from orchestrator.observability import generate_run_report, render_report_markdown
from orchestrator.replanning import Replanner
from orchestrator.state_store import StateStore
from scenarios.greenfield.run import ARTIFACT_ROOT, REPORT_PATH, RUN_ID, STATE_DB, build_scenario_input

ACTOR = "agent:engineering"


def apply() -> None:
    store = StateStore(STATE_DB)
    try:
        replanner = Replanner(store)
        replanner.invalidate_downstream(
            RUN_ID, "implementation",
            reason="analytics added: click tracking, per-day series, GET /api/urls/{code}/analytics",
            actor=ACTOR,
        )
        replanner.invalidate_downstream(
            RUN_ID, "test", reason="test suite expanded to cover analytics", actor=ACTOR,
        )

        executor = Executor(
            store.load_graph(RUN_ID), store, RUN_ID, build_deterministic_agent_registry(),
            artifact_root=ARTIFACT_ROOT, guardrail_engine=PolicyGuardrailEngine(ARTIFACT_ROOT),
            scenario_input=build_scenario_input(),
        )
        final = executor.run()

        print(f"run status: {final.status.value}")
        for stage_id, state in final.stage_states.items():
            print(f"  {stage_id:24s} {state.status.value:16s} attempts={state.attempts} error={state.error or ''}")

        REPORT_PATH.write_text(render_report_markdown(generate_run_report(store, RUN_ID)), encoding="utf-8")
    finally:
        store.close()


if __name__ == "__main__":
    apply()
