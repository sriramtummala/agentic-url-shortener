import tempfile
from pathlib import Path

import pytest

from orchestrator.models import (
    ArtifactRef,
    DecisionRecord,
    GateSpec,
    GateType,
    RetryPolicy,
    RunState,
    StageDefinition,
    StageStatus,
    TaskGraph,
)
from orchestrator.state_store import StateStore


def _toy_graph() -> TaskGraph:
    return TaskGraph(
        id="toy",
        stages={
            "requirements": StageDefinition(
                id="requirements", name="Requirements", agent="requirements"
            ),
            "design": StageDefinition(
                id="design", name="Design", agent="design", depends_on=["requirements"]
            ),
            "impl_api": StageDefinition(
                id="impl_api",
                name="Implement API",
                agent="implementation",
                depends_on=["design"],
                parallel_group="implementation",
            ),
            "impl_docs": StageDefinition(
                id="impl_docs",
                name="Draft docs",
                agent="documentation",
                depends_on=["design"],
                parallel_group="implementation",
            ),
            "release": StageDefinition(
                id="release",
                name="Release readiness",
                agent="release",
                depends_on=["impl_api", "impl_docs"],
                high_impact=True,
                entry_gates=[
                    GateSpec(id="release-approval", type=GateType.APPROVAL, description="human sign-off")
                ],
            ),
        },
    )


def test_graph_validates_and_layers():
    graph = _toy_graph()
    layers = graph.topological_layers()
    assert layers[0] == ["requirements"]
    assert layers[1] == ["design"]
    assert set(layers[2]) == {"impl_api", "impl_docs"}
    assert layers[3] == ["release"]


def test_cycle_detection_raises():
    with pytest.raises(ValueError, match="cycle"):
        TaskGraph(
            id="bad",
            stages={
                "a": StageDefinition(id="a", name="A", agent="x", depends_on=["b"]),
                "b": StageDefinition(id="b", name="B", agent="x", depends_on=["a"]),
            },
        )


def test_high_impact_requires_approval_gate():
    with pytest.raises(ValueError, match="high_impact"):
        StageDefinition(id="risky", name="Risky", agent="x", high_impact=True)


def test_downstream_of():
    graph = _toy_graph()
    assert graph.downstream_of("design") == {"impl_api", "impl_docs", "release"}
    assert graph.downstream_of("impl_api") == {"release"}


def test_state_store_roundtrip():
    graph = _toy_graph()
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(Path(tmp) / "state.db")
        run = RunState.initialize("run-1", graph, scenario="greenfield", now="2026-07-28T00:00:00Z")
        store.create_run(run, graph)

        loaded_graph = store.load_graph("run-1")
        assert loaded_graph.id == "toy"

        loaded_run = store.load_run("run-1")
        assert loaded_run.stage_states["requirements"].status == StageStatus.PENDING

        stage_state = loaded_run.stage_states["requirements"]
        stage_state.status = StageStatus.PASSED
        stage_state.attempts = 1
        store.save_stage_state("run-1", stage_state)

        reloaded = store.load_run("run-1")
        assert reloaded.stage_states["requirements"].status == StageStatus.PASSED

        decision = DecisionRecord(
            id="dec-1",
            run_id="run-1",
            stage_id="requirements",
            actor="agent:requirements",
            action="stage_passed",
            rationale="normalized requirement into spec",
            timestamp="2026-07-28T00:00:01Z",
        )
        store.record_decision(decision)
        assert len(store.get_decisions("run-1")) == 1
        assert len(store.get_decisions("run-1", stage_id="requirements")) == 1
        assert len(store.get_decisions("run-1", stage_id="design")) == 0

        artifact = ArtifactRef(
            id="art-1",
            kind="spec",
            path="scenarios/greenfield/artifacts/spec.md",
            produced_by_stage="requirements",
            version=1,
            content_hash="deadbeef",
            created_at="2026-07-28T00:00:01Z",
        )
        store.record_artifact_for_run("run-1", artifact)
        assert len(store.get_artifacts("run-1")) == 1

        store.append_audit_event("run-1", "2026-07-28T00:00:02Z", "info", "stage passed", {"stage": "requirements"})
        events = store.get_audit_events("run-1")
        assert events[0]["message"] == "stage passed"
        assert events[0]["data"]["stage"] == "requirements"

        store.request_approval("appr-1", "run-1", "release", "release-approval", "2026-07-28T00:00:03Z")
        pending = store.get_pending_approvals("run-1")
        assert len(pending) == 1
        store.resolve_approval("appr-1", "approved", "human:stummala", "2026-07-28T00:00:04Z", comment="looks good")
        assert store.get_pending_approvals("run-1") == []
        assert store.get_approval("appr-1")["status"] == "approved"

        store.close()
