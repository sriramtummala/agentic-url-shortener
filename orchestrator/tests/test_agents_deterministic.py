from orchestrator.agents.base import AgentContext
from orchestrator.agents.deterministic import (
    CodebaseReasoningAgent,
    DesignAgent,
    DocumentationAgent,
    ImplementationAgent,
    ReleaseReadinessAgent,
    RequirementsAgent,
    TestAgent,
)
from orchestrator.agents.registry import build_deterministic_agent_registry
from orchestrator.executor import Executor
from orchestrator.models import RunState, StageDefinition, TaskGraph
from orchestrator.state_store import StateStore


def _ctx(scenario_input, upstream_artifacts=None, artifact_root=None, stage_id="s"):
    return AgentContext(
        run_id="r1", stage_id=stage_id, attempt=1, graph=None, run_state=None,
        upstream_artifacts=upstream_artifacts or [], artifact_root=artifact_root,
        scenario_input=scenario_input,
    )


def test_requirements_agent_requires_normalized_requirement():
    result = RequirementsAgent().run(_ctx({}))
    assert result.success is False
    assert "normalized_requirement" in result.error


def test_requirements_agent_renders_ambiguities_and_assumptions():
    scenario_input = {
        "requirement_text": "build a URL shortener",
        "normalized_requirement": {
            "intent": "Provide a service that maps long URLs to short codes.",
            "explicit_requirements": ["Create short URL", "Redirect to original URL"],
            "ambiguities": [
                {"question": "How long should short codes be?", "resolution": "7 base62 characters",
                 "rationale": "balances collision risk and URL length"},
            ],
            "assumptions": ["Single-region deployment for the prototype"],
            "out_of_scope": ["Custom domains"],
        },
    }
    result = RequirementsAgent().run(_ctx(scenario_input))
    assert result.success
    content = result.outputs[0].content
    assert "Create short URL" in content
    assert "How long should short codes be?" in content
    assert "Single-region deployment" in content
    assert "Custom domains" in content
    assert result.outputs[0].kind == "spec"


def test_design_agent_references_upstream_spec():
    from orchestrator.models import ArtifactRef
    upstream = [ArtifactRef(id="a1", kind="spec", path="requirements/spec.md", produced_by_stage="requirements",
                             version=1, content_hash="x", created_at="t")]
    scenario_input = {
        "design": {
            "overview": "A FastAPI service backed by SQLite.",
            "components": [{"name": "ShortenAPI", "responsibility": "create/redirect endpoints"}],
            "decisions": [{"decision": "Use base62 codes", "rationale": "compact, URL-safe",
                           "alternatives_considered": "UUID (rejected: too long)"}],
            "api_summary": [{"method": "POST", "path": "/api/shorten", "description": "create a short URL"}],
        }
    }
    result = DesignAgent().run(_ctx(scenario_input, upstream_artifacts=upstream))
    assert result.success
    content = result.outputs[0].content
    assert "requirements/spec.md" in content
    assert "ShortenAPI" in content
    assert "base62" in content.lower()
    assert result.outputs[0].kind == "design"


def test_implementation_and_test_and_documentation_agents_pass_through_files():
    impl = ImplementationAgent().run(_ctx({"source_files": {"service/main.py": "print('hi')\n"}}))
    assert impl.success and impl.outputs[0].kind == "code"

    tests = TestAgent().run(_ctx({"test_files": {"tests/test_main.py": "def test_x(): assert True\n"}}))
    assert tests.success and tests.outputs[0].kind == "test"

    docs = DocumentationAgent().run(_ctx({"doc_files": {"README.md": "# Service\n"}}))
    assert docs.success and docs.outputs[0].kind == "doc"


def test_release_readiness_agent_fails_when_kind_missing():
    from orchestrator.models import ArtifactRef
    upstream = [
        ArtifactRef(id="a1", kind="code", path="x.py", produced_by_stage="impl", version=1,
                    content_hash="h", created_at="t"),
    ]
    result = ReleaseReadinessAgent().run(_ctx({}, upstream_artifacts=upstream))
    assert result.success is False
    assert "test" in result.error and "doc" in result.error


def test_release_readiness_agent_passes_when_all_kinds_present():
    from orchestrator.models import ArtifactRef
    upstream = [
        ArtifactRef(id="a1", kind="code", path="x.py", produced_by_stage="impl", version=1,
                    content_hash="h", created_at="t"),
        ArtifactRef(id="a2", kind="test", path="t.py", produced_by_stage="test", version=1,
                    content_hash="h", created_at="t"),
        ArtifactRef(id="a3", kind="doc", path="d.md", produced_by_stage="docs", version=1,
                    content_hash="h", created_at="t"),
    ]
    result = ReleaseReadinessAgent().run(_ctx({}, upstream_artifacts=upstream))
    assert result.success is True
    assert result.outputs[0].kind == "release_report"


def test_codebase_reasoning_agent_scans_real_files(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "shorten.py").write_text("def create_short_url(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "unrelated.py").write_text("def noop(): pass\n", encoding="utf-8")

    result = CodebaseReasoningAgent().run(_ctx({
        "scan_root": str(tmp_path),
        "change_keywords": ["create_short_url"],
        "change_summary": "add expiration support to short URL creation",
    }))
    assert result.success
    content = result.outputs[0].content
    assert "pkg/shorten.py" in content
    assert "pkg/unrelated.py" not in content


def test_full_deterministic_lifecycle_end_to_end(tmp_path):
    graph = TaskGraph(
        id="lifecycle",
        stages={
            "requirements": StageDefinition(id="requirements", name="Requirements", agent="requirements"),
            "design": StageDefinition(id="design", name="Design", agent="design", depends_on=["requirements"]),
            "implementation": StageDefinition(id="implementation", name="Impl", agent="implementation",
                                               depends_on=["design"]),
            "test": StageDefinition(id="test", name="Test", agent="test", depends_on=["design"]),
            "documentation": StageDefinition(id="documentation", name="Docs", agent="documentation",
                                              depends_on=["design"]),
            "release_readiness": StageDefinition(id="release_readiness", name="Release", agent="release_readiness",
                                                  depends_on=["implementation", "test", "documentation"]),
        },
    )
    scenario_input = {
        "requirement_text": "build a URL shortener",
        "normalized_requirement": {
            "intent": "map long URLs to short codes",
            "explicit_requirements": ["create", "redirect"],
            "ambiguities": [], "assumptions": [], "out_of_scope": [],
        },
        "design": {"overview": "simple service", "components": [], "decisions": [], "api_summary": []},
        "source_files": {"service/main.py": "print('ok')\n"},
        "test_files": {"tests/test_main.py": "def test_ok(): assert True\n"},
        "doc_files": {"README.md": "# URL Shortener\n"},
    }

    store = StateStore(tmp_path / "state.db")
    run_state = RunState.initialize("run-1", graph, scenario="greenfield", now="2026-07-28T00:00:00Z")
    store.create_run(run_state, graph)
    executor = Executor(
        graph, store, "run-1", build_deterministic_agent_registry(),
        artifact_root=tmp_path / "artifacts", scenario_input=scenario_input,
    )

    final = executor.run()

    from orchestrator.models import RunStatus, StageStatus
    assert final.status == RunStatus.COMPLETED
    for stage_id in graph.stages:
        assert final.stage_states[stage_id].status == StageStatus.PASSED
    artifacts = store.get_artifacts("run-1")
    assert {a.kind for a in artifacts} == {"spec", "design", "code", "test", "doc", "release_report"}
