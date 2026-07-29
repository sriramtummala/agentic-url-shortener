"""Task 13 step: insert the documentation and release-readiness stages now
that the feature set (core APIs, analytics, reliability) and service/README
are all in place.

release_readiness is high_impact=True with an APPROVAL entry gate -- it is
NOT auto-approved here. Running this script will normally end with the run
PAUSED_APPROVAL; a human decides whether to approve or reject it separately
via orchestrator.cli (see scenarios/greenfield/report.md and the printed
pending-approval id for what to run next).

Usage: python -m scenarios.greenfield.step_13_add_docs_and_release_gate
"""

from __future__ import annotations

from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.guardrails import PolicyGuardrailEngine
from orchestrator.models import GateSpec, GateType, StageDefinition
from orchestrator.observability import generate_run_report, render_report_markdown
from orchestrator.replanning import Replanner
from orchestrator.state_store import StateStore
from scenarios.greenfield.run import ARTIFACT_ROOT, REPORT_PATH, RUN_ID, STATE_DB, build_scenario_input

ACTOR = "agent:engineering"


def apply() -> None:
    store = StateStore(STATE_DB)
    try:
        replanner = Replanner(store)
        graph = store.load_graph(RUN_ID)

        if "documentation" not in graph.stages:
            replanner.insert_stage(
                RUN_ID,
                StageDefinition(
                    id="documentation", name="Documentation", agent="documentation",
                    depends_on=["design"], produces=["doc"],
                ),
                before_stage_ids=[],
                reason="service/README.md is ready to apply",
                actor=ACTOR,
            )

        graph = store.load_graph(RUN_ID)
        if "release_readiness" not in graph.stages:
            replanner.insert_stage(
                RUN_ID,
                StageDefinition(
                    id="release_readiness", name="Release Readiness", agent="release_readiness",
                    depends_on=["implementation", "test", "documentation"],
                    high_impact=True,
                    entry_gates=[
                        GateSpec(id="release-approval", type=GateType.APPROVAL,
                                 description="human sign-off required before release"),
                    ],
                ),
                before_stage_ids=[],
                reason="full feature set (core APIs, analytics, reliability) and docs are complete; "
                       "ready for release-readiness review",
                actor=ACTOR,
            )

        executor = Executor(
            store.load_graph(RUN_ID), store, RUN_ID, build_deterministic_agent_registry(),
            artifact_root=ARTIFACT_ROOT, guardrail_engine=PolicyGuardrailEngine(ARTIFACT_ROOT),
            scenario_input=build_scenario_input(),
        )
        final = executor.run()

        print(f"run status: {final.status.value}")
        for stage_id, state in final.stage_states.items():
            print(f"  {stage_id:24s} {state.status.value:16s} error={state.error or ''}")

        pending = store.get_pending_approvals(RUN_ID)
        if pending:
            print("\npending approval(s):")
            for p in pending:
                print(f"  id={p['id']} stage={p['stage_id']} gate={p['gate_id']} requested_at={p['requested_at']}")

        REPORT_PATH.write_text(render_report_markdown(generate_run_report(store, RUN_ID)), encoding="utf-8")
    finally:
        store.close()


if __name__ == "__main__":
    apply()
