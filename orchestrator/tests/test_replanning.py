import pytest

from orchestrator.agents.base import AgentContext, AgentOutput, AgentResult
from orchestrator.executor import Executor
from orchestrator.models import GateSpec, GateType, RunState, RunStatus, StageDefinition, StageStatus, TaskGraph
from orchestrator.replanning import Replanner
from orchestrator.state_store import StateStore


class SucceedAgent:
    name = "succeed"

    def __init__(self):
        self.calls = []

    def run(self, context: AgentContext) -> AgentResult:
        self.calls.append(context.stage_id)
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="ok")],
            rationale=f"{context.stage_id} done",
        )


def _linear_graph():
    return TaskGraph(
        id="linear",
        stages={
            "requirements": StageDefinition(id="requirements", name="Requirements", agent="succeed"),
            "design": StageDefinition(id="design", name="Design", agent="succeed", depends_on=["requirements"]),
            "impl": StageDefinition(id="impl", name="Impl", agent="succeed", depends_on=["design"]),
        },
    )


def _setup(tmp_path, graph):
    store = StateStore(tmp_path / "state.db")
    run_state = RunState.initialize("run-1", graph, scenario="test", now="2026-07-28T00:00:00Z")
    store.create_run(run_state, graph)
    agent = SucceedAgent()
    executor = Executor(graph, store, "run-1", {"succeed": agent}, artifact_root=tmp_path / "artifacts")
    return store, executor, agent


def test_invalidate_downstream_marks_stale_and_reexecutes(tmp_path):
    graph = _linear_graph()
    store, executor, agent = _setup(tmp_path, graph)
    first = executor.run()
    assert first.status == RunStatus.COMPLETED

    replanner = Replanner(store)
    affected = replanner.invalidate_downstream(
        "run-1", "design", reason="requirement text changed after design was drafted", actor="human:stummala"
    )
    assert set(affected) == {"design", "impl"}

    mid = store.load_run("run-1")
    assert mid.stage_states["design"].status == StageStatus.STALE
    assert mid.stage_states["impl"].status == StageStatus.STALE
    assert mid.stage_states["requirements"].status == StageStatus.PASSED  # untouched

    final = executor.run()
    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["design"].status == StageStatus.PASSED
    assert final.stage_states["impl"].status == StageStatus.PASSED

    decisions = store.get_decisions("run-1", "design")
    assert "replanned" in [d.action for d in decisions]


def test_insert_stage_blocks_dependent_and_runs_in_order(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="succeed"),
            "release": StageDefinition(id="release", name="Release", agent="succeed", depends_on=["design"]),
        },
    )
    store, executor, agent = _setup(tmp_path, graph)
    first = executor.run()
    assert first.status == RunStatus.COMPLETED
    assert first.stage_states["release"].status == StageStatus.PASSED

    replanner = Replanner(store)
    new_stage = StageDefinition(
        id="extra_review", name="Extra Review", agent="succeed", depends_on=["design"],
    )
    replanner.insert_stage(
        "run-1", new_stage, before_stage_ids=["release"],
        reason="brownfield impact analysis found an additional affected module",
        actor="agent:codebase_reasoning",
    )

    mid = store.load_run("run-1")
    assert mid.stage_states["release"].status == StageStatus.STALE
    assert "extra_review" in mid.stage_states

    reloaded_graph = store.load_graph("run-1")
    assert "extra_review" in reloaded_graph.stages
    assert "extra_review" in reloaded_graph.stages["release"].depends_on

    agent.calls.clear()
    final = executor.run()
    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["extra_review"].status == StageStatus.PASSED
    assert final.stage_states["release"].status == StageStatus.PASSED
    assert agent.calls.index("extra_review") < agent.calls.index("release")


def test_inserted_stage_can_carry_approval_gate(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="succeed"),
            "release": StageDefinition(id="release", name="Release", agent="succeed", depends_on=["design"]),
        },
    )
    store, executor, agent = _setup(tmp_path, graph)
    executor.run()

    replanner = Replanner(store)
    new_stage = StageDefinition(
        id="security_review", name="Security Review", agent="succeed", depends_on=["design"],
        high_impact=True,
        entry_gates=[GateSpec(id="sec-approval", type=GateType.APPROVAL, description="security sign-off")],
    )
    replanner.insert_stage(
        "run-1", new_stage, before_stage_ids=["release"],
        reason="new security-sensitive dependency discovered", actor="agent:codebase_reasoning",
    )

    paused = executor.run()
    assert paused.status == RunStatus.PAUSED_APPROVAL
    assert paused.stage_states["security_review"].status == StageStatus.BLOCKED_APPROVAL
    assert paused.stage_states["release"].status != StageStatus.PASSED

    pending = store.get_pending_approvals("run-1")
    assert len(pending) == 1
    store.resolve_approval(pending[0]["id"], "approved", "human:stummala", "2026-07-28T00:00:01Z", comment="reviewed")

    final = executor.run()
    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["security_review"].status == StageStatus.PASSED
    assert final.stage_states["release"].status == StageStatus.PASSED


class RecordingAgent:
    name = "recording"

    def __init__(self):
        self.seen_upstream = []

    def run(self, context: AgentContext) -> AgentResult:
        self.seen_upstream.append(list(context.upstream_artifacts))
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="ok")],
            rationale="ok",
        )


def test_upstream_artifacts_only_include_latest_version_after_replan(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="succeed"),
            "impl": StageDefinition(id="impl", name="Impl", agent="recording", depends_on=["design"]),
        },
    )
    store = StateStore(tmp_path / "state.db")
    run_state = RunState.initialize("run-1", graph, scenario="test", now="2026-07-28T00:00:00Z")
    store.create_run(run_state, graph)
    recorder = RecordingAgent()
    executor = Executor(
        graph, store, "run-1", {"succeed": SucceedAgent(), "recording": recorder},
        artifact_root=tmp_path / "artifacts",
    )

    executor.run()
    assert len(recorder.seen_upstream[0]) == 1
    assert recorder.seen_upstream[0][0].version == 1

    replanner = Replanner(store)
    replanner.invalidate_downstream("run-1", "design", reason="design changed", actor="human:stummala")
    executor.run()

    assert len(recorder.seen_upstream) == 2
    latest_call_artifacts = recorder.seen_upstream[1]
    assert len(latest_call_artifacts) == 1  # not two -- the stale v1 must not linger alongside v2
    assert latest_call_artifacts[0].version == 2


def test_insert_stage_rejects_unknown_before_id_and_duplicate_id(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={"design": StageDefinition(id="design", name="Design", agent="succeed")},
    )
    store, executor, agent = _setup(tmp_path, graph)
    executor.run()
    replanner = Replanner(store)

    with pytest.raises(ValueError, match="unknown stage"):
        replanner.insert_stage(
            "run-1", StageDefinition(id="new", name="New", agent="succeed"),
            before_stage_ids=["does_not_exist"], reason="x", actor="human:stummala",
        )

    with pytest.raises(ValueError, match="already exists"):
        replanner.insert_stage(
            "run-1", StageDefinition(id="design", name="Design2", agent="succeed"),
            before_stage_ids=[], reason="x", actor="human:stummala",
        )
