"""Step 2: after a human rejects the V1 (over-scoped) interpretation, rework
it into the scoped-down V2 interpretation and resubmit it through the same
requirements approval gate as a fresh incarnation.

Usage: python -m scenarios.ambiguous.step_2_rework_after_rejection
"""

from __future__ import annotations

from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.guardrails import PolicyGuardrailEngine
from orchestrator.observability import generate_run_report, render_report_markdown
from orchestrator.replanning import Replanner
from orchestrator.state_store import StateStore
from scenarios.ambiguous.graph import build_graph
from scenarios.ambiguous.run import ARTIFACT_ROOT, REPORT_PATH, RUN_ID, STATE_DB, build_scenario_input

ACTOR = "agent:engineering"


def apply() -> None:
    store = StateStore(STATE_DB)
    try:
        replanner = Replanner(store)
        replanner.invalidate_downstream(
            RUN_ID, "requirements",
            reason="V1 interpretation was rejected (third-party dependency + moderation workflow "
                   "overreach); reworked to a scoped denylist + report-threshold interpretation",
            actor=ACTOR,
        )

        executor = Executor(
            build_graph(), store, RUN_ID, build_deterministic_agent_registry(),
            artifact_root=ARTIFACT_ROOT, guardrail_engine=PolicyGuardrailEngine(ARTIFACT_ROOT),
            scenario_input=build_scenario_input("v2"),
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
