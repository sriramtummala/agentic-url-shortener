"""Runner for the brownfield scenario. Unlike greenfield's run.py, the
whole graph exists from the start (see graph.py) -- this is a scoped,
already-understood fix, not an exploratory build, so there's no
insert_stage growth here.

Usage: python -m scenarios.brownfield.run
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.guardrails import PolicyGuardrailEngine
from orchestrator.models import RunState
from orchestrator.observability import generate_run_report, render_report_markdown
from orchestrator.state_store import StateStore
from scenarios.brownfield import scenario_input as si
from scenarios.brownfield.graph import build_graph

SCENARIO_DIR = Path(__file__).parent
STATE_DB = SCENARIO_DIR / "run_state" / "state.db"
ARTIFACT_ROOT = SCENARIO_DIR / "artifacts"
REPORT_PATH = SCENARIO_DIR / "report.md"
RUN_ID = "brownfield-run-1"


def build_scenario_input() -> dict:
    scenario_input = {
        "requirement_text": si.REQUIREMENT_TEXT,
        "normalized_requirement": si.NORMALIZED_REQUIREMENT,
        "design": si.DESIGN,
        "source_files": si.source_files(),
        "test_files": si.test_files(),
        "doc_files": si.doc_files(),
    }
    scenario_input.update(si.codebase_reasoning_input())
    return scenario_input


def get_or_create_run(store: StateStore, graph) -> None:
    try:
        store.load_run(RUN_ID)
    except KeyError:
        run_state = RunState.initialize(
            RUN_ID, graph, scenario="brownfield", now=datetime.now(timezone.utc).isoformat()
        )
        store.create_run(run_state, graph)


def run() -> None:
    graph = build_graph()
    store = StateStore(STATE_DB)
    try:
        get_or_create_run(store, graph)
        executor = Executor(
            graph, store, RUN_ID, build_deterministic_agent_registry(),
            artifact_root=ARTIFACT_ROOT,
            guardrail_engine=PolicyGuardrailEngine(ARTIFACT_ROOT),
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

        report = generate_run_report(store, RUN_ID)
        REPORT_PATH.write_text(render_report_markdown(report), encoding="utf-8")
        print(f"wrote {REPORT_PATH}")
    finally:
        store.close()


if __name__ == "__main__":
    run()
