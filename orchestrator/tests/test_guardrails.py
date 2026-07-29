from orchestrator.agents.base import AgentOutput, AgentResult
from orchestrator.executor import Executor
from orchestrator.gates import GateContext
from orchestrator.guardrails import (
    NoDangerousConstructsRule,
    PiiScanRule,
    PolicyGuardrailEngine,
    RequiredArtifactsRule,
    SecretScanRule,
)
from orchestrator.models import (
    ArtifactRef,
    GateSpec,
    GateType,
    RunState,
    StageDefinition,
    StageStatus,
    TaskGraph,
)
from orchestrator.state_store import StateStore


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return name


def _artifact(path, kind="code"):
    return ArtifactRef(
        id="a1", kind=kind, path=path, produced_by_stage="s", version=1,
        content_hash="x", created_at="2026-07-28T00:00:00Z",
    )


def _ctx(artifacts, stage=None):
    stage = stage or StageDefinition(id="s", name="S", agent="a")
    return GateContext(run_id="r1", stage=stage, phase="exit", artifacts=artifacts)


def test_secret_scan_flags_aws_key(tmp_path):
    path = _write(tmp_path, "config.py", "AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'")
    result = SecretScanRule().evaluate(_ctx([_artifact(path)]), tmp_path)
    assert result.passed is False
    assert "AWS access key" in result.reason


def test_secret_scan_passes_clean_content(tmp_path):
    path = _write(tmp_path, "config.py", "DEBUG = True\n")
    result = SecretScanRule().evaluate(_ctx([_artifact(path)]), tmp_path)
    assert result.passed is True


def test_secret_scan_ignores_placeholder_password(tmp_path):
    path = _write(tmp_path, "config.py", "password = 'changeme'\n")
    result = SecretScanRule().evaluate(_ctx([_artifact(path)]), tmp_path)
    assert result.passed is True


def test_no_dangerous_constructs_flags_eval(tmp_path):
    path = _write(tmp_path, "handler.py", "def f(x):\n    return eval(x)\n")
    result = NoDangerousConstructsRule().evaluate(_ctx([_artifact(path, kind="code")]), tmp_path)
    assert result.passed is False
    assert "eval(" in result.reason


def test_no_dangerous_constructs_ignores_non_code_artifacts(tmp_path):
    path = _write(tmp_path, "notes.md", "call eval(x) in your shell\n")
    result = NoDangerousConstructsRule().evaluate(_ctx([_artifact(path, kind="doc")]), tmp_path)
    assert result.passed is True


def test_pii_scan_flags_ssn_like_value(tmp_path):
    path = _write(tmp_path, "fixture.json", '{"ssn": "123-45-6789"}')
    result = PiiScanRule().evaluate(_ctx([_artifact(path, kind="test")]), tmp_path)
    assert result.passed is False
    assert "SSN" in result.reason


def test_required_artifacts_rule_flags_missing_kind(tmp_path):
    stage = StageDefinition(id="s", name="S", agent="a", produces=["code", "test"])
    path = _write(tmp_path, "impl.py", "print('ok')\n")
    result = RequiredArtifactsRule().evaluate(_ctx([_artifact(path, kind="code")], stage=stage), tmp_path)
    assert result.passed is False
    assert "test" in result.reason


def test_unregistered_rule_fails_closed(tmp_path):
    engine = PolicyGuardrailEngine(tmp_path, rules=[])
    gate = GateSpec(id="mystery", type=GateType.POLICY, description="?", config={"rule": "does_not_exist"})
    result = engine.check(gate, _ctx([]))
    assert result.passed is False
    assert "failing closed" in result.reason


def test_executor_blocks_stage_on_secret_and_permissive_engine_would_pass(tmp_path):
    graph = TaskGraph(
        id="g",
        stages={
            "impl": StageDefinition(
                id="impl", name="Impl", agent="leaky",
                exit_gates=[GateSpec(id="secret-check", type=GateType.POLICY, description="scan for secrets",
                                      config={"rule": "secret_scan"})],
            ),
        },
    )

    class LeakyAgent:
        name = "leaky"

        def run(self, context):
            return AgentResult(
                success=True,
                outputs=[AgentOutput(kind="code", relative_path="impl.py",
                                      content="AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n")],
                rationale="implemented",
            )

    def _run(engine):
        store = StateStore(tmp_path / f"state_{engine.__class__.__name__}.db")
        run_state = RunState.initialize("run-1", graph, scenario="test", now="2026-07-28T00:00:00Z")
        store.create_run(run_state, graph)
        executor = Executor(
            graph, store, "run-1", {"leaky": LeakyAgent()},
            artifact_root=tmp_path / f"artifacts_{engine.__class__.__name__}",
            guardrail_engine=engine,
        )
        final = executor.run()
        store.close()
        return final

    blocked = _run(PolicyGuardrailEngine(tmp_path / "artifacts_PolicyGuardrailEngine"))
    assert blocked.stage_states["impl"].status == StageStatus.FAILED
    assert "AWS access key" in (blocked.stage_states["impl"].error or "")
