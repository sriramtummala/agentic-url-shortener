import threading
import time

from orchestrator.agents.base import AgentContext, AgentOutput, AgentResult
from orchestrator.executor import Executor
from orchestrator.models import (
    GateSpec,
    GateType,
    RetryPolicy,
    RunState,
    RunStatus,
    StageDefinition,
    StageStatus,
    TaskGraph,
)
from orchestrator.state_store import StateStore


class _Clock:
    def __init__(self):
        self.n = 0

    def now(self) -> str:
        self.n += 1
        return f"2026-07-28T00:{self.n:04d}Z"


class _Ids:
    def __init__(self, prefix="id"):
        self.prefix = prefix
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"{self.prefix}-{self.n}"


class SucceedAgent:
    name = "succeed"

    def __init__(self):
        self.calls = []

    def run(self, context: AgentContext) -> AgentResult:
        self.calls.append(context.attempt)
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt",
                                  content=f"ok from {context.stage_id}")],
            rationale=f"{context.stage_id} produced output",
        )


class FlakyAgent:
    name = "flaky"

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def run(self, context: AgentContext) -> AgentResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            return AgentResult(success=False, error=f"transient failure #{self.calls}")
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="recovered")],
            rationale="recovered after retries",
        )


class AlwaysFailAgent:
    name = "fail"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(success=False, error="permanent failure")


class ConcurrentTrackingAgent:
    """Records the peak number of simultaneously-active invocations, so
    tests can assert real concurrency happened rather than just trusting
    the layering logic."""

    name = "tracker"

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, context: AgentContext) -> AgentResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="done")],
            rationale="done",
        )


def _new_executor(graph, agents, tmp_path, scenario="test", guardrail_engine=None, max_workers=4):
    store = StateStore(tmp_path / "state.db")
    clock = _Clock()
    ids = _Ids()
    run_state = RunState.initialize(ids.new_id(), graph, scenario=scenario, now=clock.now())
    store.create_run(run_state, graph)
    executor = Executor(
        graph, store, run_state.run_id, agents,
        artifact_root=tmp_path / "artifacts",
        guardrail_engine=guardrail_engine,
        max_workers=max_workers,
        now_fn=clock.now,
        id_fn=ids.new_id,
    )
    return executor, store, run_state.run_id


def _linear_graph(agent_name="succeed"):
    return TaskGraph(
        id="linear",
        stages={
            "requirements": StageDefinition(id="requirements", name="Requirements", agent=agent_name),
            "design": StageDefinition(id="design", name="Design", agent=agent_name, depends_on=["requirements"]),
            "impl": StageDefinition(id="impl", name="Implementation", agent=agent_name, depends_on=["design"]),
        },
    )


def test_sequential_run_completes_and_persists_artifacts(tmp_path):
    agent = SucceedAgent()
    executor, store, run_id = _new_executor(_linear_graph(), {"succeed": agent}, tmp_path)

    final = executor.run()

    assert final.status == RunStatus.COMPLETED
    for stage_id in ("requirements", "design", "impl"):
        assert final.stage_states[stage_id].status == StageStatus.PASSED
    artifacts = store.get_artifacts(run_id)
    assert {a.produced_by_stage for a in artifacts} == {"requirements", "design", "impl"}
    for a in artifacts:
        path = executor.artifact_root / a.path
        assert path.exists()


def test_independent_stages_run_concurrently(tmp_path):
    tracker = ConcurrentTrackingAgent()
    graph = TaskGraph(
        id="fanout",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="tracker"),
            "impl_a": StageDefinition(id="impl_a", name="A", agent="tracker", depends_on=["design"]),
            "impl_b": StageDefinition(id="impl_b", name="B", agent="tracker", depends_on=["design"]),
            "release": StageDefinition(id="release", name="Release", agent="tracker", depends_on=["impl_a", "impl_b"]),
        },
    )
    executor, store, run_id = _new_executor(graph, {"tracker": tracker}, tmp_path)

    final = executor.run()

    assert final.status == RunStatus.COMPLETED
    assert tracker.max_active >= 2  # impl_a and impl_b actually overlapped


def test_retry_then_success(tmp_path):
    flaky = FlakyAgent(fail_times=2)
    graph = TaskGraph(
        id="retry",
        stages={
            "impl": StageDefinition(
                id="impl", name="Impl", agent="flaky",
                retry_policy=RetryPolicy(max_attempts=3),
            ),
        },
    )
    executor, store, run_id = _new_executor(graph, {"flaky": flaky}, tmp_path)

    final = executor.run()

    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["impl"].status == StageStatus.PASSED
    assert final.stage_states["impl"].attempts == 3
    actions = [d.action for d in store.get_decisions(run_id, "impl")]
    assert actions.count("attempt_failed") == 2
    assert "stage_passed" in actions


def test_retries_exhausted_fails_and_skips_downstream(tmp_path):
    graph = TaskGraph(
        id="fail",
        stages={
            "impl": StageDefinition(id="impl", name="Impl", agent="fail", retry_policy=RetryPolicy(max_attempts=2)),
            "release": StageDefinition(id="release", name="Release", agent="succeed", depends_on=["impl"]),
        },
    )
    executor, store, run_id = _new_executor(
        graph, {"fail": AlwaysFailAgent(), "succeed": SucceedAgent()}, tmp_path
    )

    final = executor.run()

    assert final.status == RunStatus.FAILED
    assert final.stage_states["impl"].status == StageStatus.FAILED
    assert final.stage_states["impl"].attempts == 2
    assert final.stage_states["release"].status == StageStatus.SKIPPED


def test_fallback_agent_recovers_after_retries_exhausted(tmp_path):
    graph = TaskGraph(
        id="fallback",
        stages={
            "impl": StageDefinition(
                id="impl", name="Impl", agent="fail",
                retry_policy=RetryPolicy(max_attempts=2, fallback_agent="succeed"),
            ),
        },
    )
    executor, store, run_id = _new_executor(
        graph, {"fail": AlwaysFailAgent(), "succeed": SucceedAgent()}, tmp_path
    )

    final = executor.run()

    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["impl"].status == StageStatus.PASSED
    actions = [d.action for d in store.get_decisions(run_id, "impl")]
    assert "fallback_invoked" in actions


def test_high_impact_stage_blocks_on_approval_then_resumes(tmp_path):
    graph = TaskGraph(
        id="approval",
        stages={
            "impl": StageDefinition(id="impl", name="Impl", agent="succeed"),
            "release": StageDefinition(
                id="release", name="Release", agent="succeed", depends_on=["impl"],
                high_impact=True,
                entry_gates=[GateSpec(id="release-approval", type=GateType.APPROVAL, description="sign-off")],
            ),
        },
    )
    executor, store, run_id = _new_executor(graph, {"succeed": SucceedAgent()}, tmp_path)

    paused = executor.run()
    assert paused.status == RunStatus.PAUSED_APPROVAL
    assert paused.stage_states["release"].status == StageStatus.BLOCKED_APPROVAL
    pending = store.get_pending_approvals(run_id)
    assert len(pending) == 1

    store.resolve_approval(pending[0]["id"], "approved", "human:reviewer", "2026-07-28T00:9999Z", comment="looks good")
    final = executor.run()

    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["release"].status == StageStatus.PASSED


def test_high_impact_stage_rejected_fails_and_does_not_run(tmp_path):
    graph = TaskGraph(
        id="rejection",
        stages={
            "release": StageDefinition(
                id="release", name="Release", agent="succeed",
                high_impact=True,
                entry_gates=[GateSpec(id="release-approval", type=GateType.APPROVAL, description="sign-off")],
            ),
        },
    )
    agent = SucceedAgent()
    executor, store, run_id = _new_executor(graph, {"succeed": agent}, tmp_path)

    executor.run()
    pending = store.get_pending_approvals(run_id)
    store.resolve_approval(pending[0]["id"], "rejected", "human:reviewer", "2026-07-28T00:9999Z", comment="not ready")
    final = executor.run()

    assert final.status == RunStatus.FAILED
    assert final.stage_states["release"].status == StageStatus.FAILED
    assert agent.calls == []  # agent never actually invoked


def test_safe_stop_before_run_prevents_any_execution(tmp_path):
    graph = _linear_graph()
    agent = SucceedAgent()
    executor, store, run_id = _new_executor(graph, {"succeed": agent}, tmp_path)

    executor.request_safe_stop("precautionary halt")
    final = executor.run()

    assert final.status == RunStatus.PAUSED_SAFE_STOP
    assert all(s.status == StageStatus.PENDING for s in final.stage_states.values())
    assert agent.calls == []


def test_safe_stop_triggered_mid_run_halts_before_next_layer(tmp_path):
    graph = _linear_graph()
    store_holder = {}

    class HaltingAgent:
        name = "halting"

        def run(self, context: AgentContext) -> AgentResult:
            if context.stage_id == "requirements":
                store_holder["executor"].request_safe_stop("stop after requirements")
            return AgentResult(
                success=True,
                outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="ok")],
                rationale="ok",
            )

    executor, store, run_id = _new_executor(graph, {"succeed": HaltingAgent()}, tmp_path)
    store_holder["executor"] = executor

    final = executor.run()

    assert final.status == RunStatus.PAUSED_SAFE_STOP
    assert final.stage_states["requirements"].status == StageStatus.PASSED
    assert final.stage_states["design"].status == StageStatus.PENDING
    assert final.stage_states["impl"].status == StageStatus.PENDING


def test_rollback_marks_downstream_stale_and_reexecutes(tmp_path):
    graph = _linear_graph()
    agent = SucceedAgent()
    executor, store, run_id = _new_executor(graph, {"succeed": agent}, tmp_path)

    first = executor.run()
    assert first.status == RunStatus.COMPLETED

    executor.rollback_stage("design", reason="requirement changed after design was approved")

    mid = store.load_run(run_id)
    assert mid.stage_states["design"].status == StageStatus.ROLLED_BACK
    assert mid.stage_states["design"].stale is True
    assert mid.stage_states["impl"].status == StageStatus.STALE
    assert mid.stage_states["requirements"].status == StageStatus.PASSED  # untouched, upstream of rollback

    final = executor.run()
    assert final.status == RunStatus.COMPLETED
    assert final.stage_states["design"].status == StageStatus.PASSED
    assert final.stage_states["design"].rollback_count == 1
    assert final.stage_states["impl"].status == StageStatus.PASSED

    decisions = store.get_decisions(run_id, "design")
    assert "rolled_back" in [d.action for d in decisions]
    impl_decisions = [d.action for d in store.get_decisions(run_id, "impl")]
    assert "marked_stale" in impl_decisions
