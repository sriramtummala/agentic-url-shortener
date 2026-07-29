"""Step 1: insert the implementation and test stages into the live
greenfield run now that the core API code (service/app) and its test suite
(service/tests) exist, and execute them.

The insert_stage calls are attributed to actor="agent:engineering" -- this
is an agent-side judgment call ("this code is ready to apply"), not a human
sign-off, so it deliberately does not use the "human:" actor prefix that
StateStore.resolve_approval enforces for real approval-gate decisions.

Idempotent: re-running this after the stages already exist just re-runs the
executor (insert_stage is skipped, not repeated).

Usage: python -m scenarios.greenfield.step_1_add_core_implementation
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

CODE_GATES = [
    GateSpec(id="secret-scan", type=GateType.POLICY, description="scan for hardcoded secrets",
             config={"rule": "secret_scan"}),
    GateSpec(id="dangerous-code-scan", type=GateType.POLICY, description="block dangerous constructs",
             config={"rule": "no_dangerous_code"}),
    GateSpec(id="pii-scan", type=GateType.POLICY, description="scan for PII-shaped values",
             config={"rule": "pii_scan"}),
]


def apply() -> None:
    store = StateStore(STATE_DB)
    try:
        replanner = Replanner(store)
        graph = store.load_graph(RUN_ID)

        if "implementation" not in graph.stages:
            replanner.insert_stage(
                RUN_ID,
                StageDefinition(
                    id="implementation", name="Implementation", agent="implementation",
                    depends_on=["design"], produces=["code"], exit_gates=CODE_GATES,
                ),
                before_stage_ids=[],
                reason="core API implementation (create/redirect/metadata/delete) is ready to apply",
                actor=ACTOR,
            )

        graph = store.load_graph(RUN_ID)
        if "test" not in graph.stages:
            replanner.insert_stage(
                RUN_ID,
                StageDefinition(id="test", name="Test", agent="test", depends_on=["design"], produces=["test"]),
                before_stage_ids=[],
                reason="core API test suite is ready to apply",
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

        REPORT_PATH.write_text(render_report_markdown(generate_run_report(store, RUN_ID)), encoding="utf-8")
    finally:
        store.close()


if __name__ == "__main__":
    apply()
