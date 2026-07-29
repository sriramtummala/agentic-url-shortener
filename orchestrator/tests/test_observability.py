from orchestrator.agents.base import AgentContext, AgentOutput, AgentResult
from orchestrator.executor import Executor
from orchestrator.models import RetryPolicy, RunState, StageDefinition, TaskGraph
from orchestrator.observability import (
    end_to_end_latency,
    generate_run_report,
    mean_time_to_recovery,
    render_report_markdown,
    retry_stats,
    rollback_stats,
    success_rate,
)
from orchestrator.state_store import StateStore


class _Clock:
    def __init__(self):
        self.n = 0

    def now(self) -> str:
        self.n += 1
        return f"2026-07-28T00:{self.n // 60:02d}:{self.n % 60:02d}Z"


class _Ids:
    def __init__(self):
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"id-{self.n}"


class FlakyAgent:
    name = "flaky"

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def run(self, context: AgentContext) -> AgentResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            return AgentResult(success=False, error=f"transient #{self.calls}")
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path="impl.txt", content="ok")],
            rationale="recovered",
        )


class AlwaysFailAgent:
    name = "fail"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(success=False, error="permanent failure")


class SucceedAgent:
    name = "succeed"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="ok")],
            rationale="ok",
        )


def _new_executor(graph, agents, tmp_path):
    store = StateStore(tmp_path / "state.db")
    clock = _Clock()
    ids = _Ids()
    run_state = RunState.initialize("run-1", graph, scenario="test", now=clock.now())
    store.create_run(run_state, graph)
    executor = Executor(
        graph, store, "run-1", agents, artifact_root=tmp_path / "artifacts",
        now_fn=clock.now, id_fn=ids.new_id,
    )
    return executor, store


def test_retry_metrics_and_mttr(tmp_path):
    flaky = FlakyAgent(fail_times=2)
    graph = TaskGraph(
        id="g", stages={"impl": StageDefinition(id="impl", name="Impl", agent="flaky",
                                                   retry_policy=RetryPolicy(max_attempts=3))},
    )
    executor, store = _new_executor(graph, {"flaky": flaky}, tmp_path)
    executor.run()
    run_state = store.load_run("run-1")

    stats = retry_stats(run_state)
    assert stats["total_retries"] == 2
    assert stats["stages_with_retries"] == 1

    decisions = store.get_decisions("run-1")
    mttr = mean_time_to_recovery(decisions)
    assert mttr is not None
    assert mttr > 0

    assert success_rate(run_state) == 1.0
    assert end_to_end_latency(run_state) >= 0


def test_success_rate_counts_failed_and_skipped_as_terminal(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "impl": StageDefinition(id="impl", name="Impl", agent="fail"),
            "release": StageDefinition(id="release", name="Release", agent="succeed", depends_on=["impl"]),
        },
    )
    executor, store = _new_executor(graph, {"fail": AlwaysFailAgent(), "succeed": SucceedAgent()}, tmp_path)
    executor.run()
    run_state = store.load_run("run-1")

    assert success_rate(run_state) == 0.0


def test_rollback_metrics(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="succeed"),
            "impl": StageDefinition(id="impl", name="Impl", agent="succeed", depends_on=["design"]),
        },
    )
    executor, store = _new_executor(graph, {"succeed": SucceedAgent()}, tmp_path)
    executor.run()
    executor.rollback_stage("design", reason="spec changed")
    executor.run()
    run_state = store.load_run("run-1")

    stats = rollback_stats(run_state)
    assert stats["total_rollbacks"] == 1
    assert stats["rollbacks_by_stage"] == {"design": 1}


def test_generate_run_report_and_markdown_rendering(tmp_path):
    flaky = FlakyAgent(fail_times=1)
    graph = TaskGraph(
        id="g",
        stages={
            "design": StageDefinition(id="design", name="Design", agent="succeed"),
            "impl": StageDefinition(id="impl", name="Impl", agent="flaky", depends_on=["design"],
                                     retry_policy=RetryPolicy(max_attempts=2)),
        },
    )
    executor, store = _new_executor(graph, {"succeed": SucceedAgent(), "flaky": flaky}, tmp_path)
    executor.run()

    report = generate_run_report(store, "run-1")
    assert report["status"] == "completed"
    assert report["success_rate"] == 1.0
    assert report["retry"]["total_retries"] == 1
    assert "design" in report["stages"]
    assert "impl" in report["stages"]

    markdown = render_report_markdown(report)
    assert "# Run Report: run-1" in markdown
    assert "| design |" in markdown
    assert "| impl |" in markdown
