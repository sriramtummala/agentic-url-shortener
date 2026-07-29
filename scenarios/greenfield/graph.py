"""TaskGraph definition for the greenfield 'build a URL shortener' scenario.

Starts deliberately small: just requirements and design. The
implementation/test/documentation/release-readiness stages are added later
via orchestrator.replanning.Replanner.insert_stage as each slice of real
engineering work (core APIs, then analytics, then reliability hardening)
becomes ready, rather than being declared up front and left dangling with
no scenario_input to run against. See scenarios/greenfield/run.py.
"""

from __future__ import annotations

from orchestrator.models import StageDefinition, TaskGraph


def build_graph() -> TaskGraph:
    return TaskGraph(
        id="greenfield-url-shortener",
        stages={
            "requirements": StageDefinition(
                id="requirements", name="Requirements", agent="requirements", produces=["spec"],
            ),
            "design": StageDefinition(
                id="design", name="Design", agent="design", depends_on=["requirements"], produces=["design"],
            ),
        },
    )
