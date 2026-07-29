"""Runner for the greenfield scenario: creates/resumes the run, executes it,
and writes a markdown audit report. Safe to re-invoke -- it resumes the
existing run_id rather than starting over, which is how Tasks 9-11 pick the
run back up after inserting new stages and expanding scenario_input.

Usage (from repo root, with the venv active):
    python -m scenarios.greenfield.run
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
from scenarios.greenfield import scenario_input as si
from scenarios.greenfield.graph import build_graph

SCENARIO_DIR = Path(__file__).parent
STATE_DB = SCENARIO_DIR / "run_state" / "state.db"
ARTIFACT_ROOT = SCENARIO_DIR / "artifacts"
REPORT_PATH = SCENARIO_DIR / "report.md"
RUN_ID = "greenfield-run-1"


def build_scenario_input() -> dict:
    scenario_input = {
        "requirement_text": si.REQUIREMENT_TEXT,
        "normalized_requirement": si.NORMALIZED_REQUIREMENT,
        "design": si.DESIGN,
    }
    for optional_key in ("SOURCE_FILES", "TEST_FILES", "DOC_FILES"):
        if hasattr(si, optional_key):
            scenario_input[optional_key.lower()] = getattr(si, optional_key)
    return scenario_input


def get_or_create_run(store: StateStore, graph) -> None:
    try:
        store.load_run(RUN_ID)
    except KeyError:
        run_state = RunState.initialize(
            RUN_ID, graph, scenario="greenfield", now=datetime.now(timezone.utc).isoformat()
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

        report = generate_run_report(store, RUN_ID)
        REPORT_PATH.write_text(render_report_markdown(report), encoding="utf-8")
        print(f"wrote {REPORT_PATH}")
    finally:
        store.close()


if __name__ == "__main__":
    run()
