import builtins
import sys
import types

import pytest

from orchestrator.agents.base import AgentContext
from orchestrator.agents.claude_adapter import ClaudeAgent


def _ctx(**overrides):
    base = dict(
        run_id="r1", stage_id="implementation", attempt=1, graph=None, run_state=None,
        upstream_artifacts=[], artifact_root=None, scenario_input={"requirement_text": "build X"},
    )
    base.update(overrides)
    return AgentContext(**base)


def test_ensure_client_raises_clearly_when_anthropic_not_installed(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    with pytest.raises(RuntimeError, match="anthropic"):
        agent._ensure_client()


def test_ensure_client_raises_clearly_without_api_key(monkeypatch):
    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = lambda api_key: object()
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        agent._ensure_client()


def test_parse_files_splits_multiple_file_blocks():
    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    text = (
        "--- FILE: app/main.py ---\n"
        "print('hi')\n"
        "--- FILE: app/util.py ---\n"
        "def f():\n    pass\n"
    )
    outputs = agent._parse_files(text)
    assert [o.relative_path for o in outputs] == ["app/main.py", "app/util.py"]
    assert outputs[0].content == "print('hi')"
    assert outputs[0].kind == "code"


def test_parse_files_returns_empty_when_no_markers_present():
    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    assert agent._parse_files("no markers here") == []


def test_run_end_to_end_with_fake_client(monkeypatch):
    response_text = "--- FILE: app/main.py ---\nprint('generated')\n"

    class FakeMessages:
        def create(self, **kwargs):
            block = types.SimpleNamespace(type="text", text=response_text)
            return types.SimpleNamespace(content=[block])

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    result = agent.run(_ctx())

    assert result.success
    assert result.outputs[0].relative_path == "app/main.py"
    assert "generated" in result.outputs[0].content


def test_run_fails_cleanly_when_response_has_no_file_blocks(monkeypatch):
    class FakeMessages:
        def create(self, **kwargs):
            block = types.SimpleNamespace(type="text", text="I refuse to use the format.")
            return types.SimpleNamespace(content=[block])

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    agent = ClaudeAgent(name="impl_claude", kind="code", system_prompt="write code")
    result = agent.run(_ctx())

    assert result.success is False
    assert "FILE" in result.error
