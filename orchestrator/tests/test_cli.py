import pytest

from orchestrator.cli import main
from orchestrator.executor import Executor
from orchestrator.models import GateSpec, GateType, RunState, StageDefinition, TaskGraph
from orchestrator.state_store import StateStore


class _SucceedAgent:
    name = "succeed"

    def run(self, context):
        from orchestrator.agents.base import AgentOutput, AgentResult
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="artifact", relative_path=f"{context.stage_id}.txt", content="ok")],
            rationale="ok",
        )


def _graph_with_approval():
    return TaskGraph(
        id="approval",
        stages={
            "release": StageDefinition(
                id="release", name="Release", agent="succeed",
                high_impact=True,
                entry_gates=[GateSpec(id="release-approval", type=GateType.APPROVAL, description="sign-off")],
            ),
        },
    )


def _setup_run_with_pending_approval(tmp_path):
    db_path = tmp_path / "state.db"
    store = StateStore(db_path)
    graph = _graph_with_approval()
    run_state = RunState.initialize("run-1", graph, scenario="test", now="2026-07-28T00:00:00Z")
    store.create_run(run_state, graph)
    executor = Executor(graph, store, "run-1", {"succeed": _SucceedAgent()}, artifact_root=tmp_path / "artifacts")
    executor.run()
    store.close()
    return db_path


def test_runs_list_and_show(tmp_path, capsys):
    db_path = _setup_run_with_pending_approval(tmp_path)

    rc = main(["--db", str(db_path), "runs", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run-1" in out
    assert "paused_approval" in out

    rc = main(["--db", str(db_path), "runs", "show", "run-1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "release" in out
    assert "blocked_approval" in out


def test_approvals_list_and_decide_approve(tmp_path, capsys):
    db_path = _setup_run_with_pending_approval(tmp_path)

    rc = main(["--db", str(db_path), "approvals", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run-1" in out
    approval_id = out.split()[0]

    rc = main([
        "--db", str(db_path), "approvals", "decide", approval_id,
        "--by", "stummala", "--status", "approved", "--comment", "looks good",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "human:stummala" in out

    store = StateStore(db_path)
    resolved = store.get_approval(approval_id)
    store.close()
    assert resolved["status"] == "approved"
    assert resolved["resolved_by"] == "human:stummala"


def test_approvals_decide_rejection_without_comment_is_rejected_by_cli(tmp_path, capsys):
    db_path = _setup_run_with_pending_approval(tmp_path)
    pending_out = main(["--db", str(db_path), "approvals", "list"])
    approval_id = capsys.readouterr().out.split()[0]

    rc = main([
        "--db", str(db_path), "approvals", "decide", approval_id,
        "--by", "stummala", "--status", "rejected",
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert "rationale" in err

    store = StateStore(db_path)
    still_pending = store.get_pending_approvals("run-1")
    store.close()
    assert len(still_pending) == 1


def test_state_store_rejects_non_human_approver(tmp_path):
    db_path = _setup_run_with_pending_approval(tmp_path)
    store = StateStore(db_path)
    pending = store.get_pending_approvals("run-1")
    with pytest.raises(ValueError, match="human"):
        store.resolve_approval(pending[0]["id"], "approved", "agent:requirements", "2026-07-28T00:00:01Z")
    store.close()


def test_audit_and_decisions_output(tmp_path, capsys):
    db_path = _setup_run_with_pending_approval(tmp_path)

    rc = main(["--db", str(db_path), "audit", "run-1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "release" in out

    rc = main(["--db", str(db_path), "decisions", "run-1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "entry_gate_blocked" in out
