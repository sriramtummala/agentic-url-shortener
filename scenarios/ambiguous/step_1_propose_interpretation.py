"""Step 1: create the run and propose the first (deliberately over-scoped)
interpretation of the ambiguous ask. The `requirements` stage is
high_impact=True with an APPROVAL exit gate, so this cannot reach design/
implementation without a human sign-off on the interpretation itself.

Expected outcome: run pauses at PAUSED_APPROVAL on the requirements stage.
A human then decides via orchestrator.cli whether to approve or reject.

Usage: python -m scenarios.ambiguous.step_1_propose_interpretation
"""

from __future__ import annotations

from datetime import datetime, timezone

from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.guardrails import PolicyGuardrailEngine
from orchestrator.models import RunState
from orchestrator.observability import generate_run_report, render_report_markdown
from orchestrator.state_store import StateStore
from scenarios.ambiguous.graph import build_graph
from scenarios.ambiguous.run import ARTIFACT_ROOT, REPORT_PATH, RUN_ID, STATE_DB, build_scenario_input


def apply() -> None:
    graph = build_graph()
    store = StateStore(STATE_DB)
    try:
        try:
            store.load_run(RUN_ID)
        except KeyError:
            run_state = RunState.initialize(
                RUN_ID, graph, scenario="ambiguous", now=datetime.now(timezone.utc).isoformat()
            )
            store.create_run(run_state, graph)

        executor = Executor(
            graph, store, RUN_ID, build_deterministic_agent_registry(),
            artifact_root=ARTIFACT_ROOT, guardrail_engine=PolicyGuardrailEngine(ARTIFACT_ROOT),
            scenario_input=build_scenario_input("v1"),
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
