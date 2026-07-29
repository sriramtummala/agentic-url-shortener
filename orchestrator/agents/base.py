"""Agent adapter interface.

An "agent" is whatever executes a single stage's work: it receives the
upstream context (artifacts produced by dependency stages, the scenario's
input, and which attempt this is) and returns either a set of produced
artifacts or a failure. The executor does not care whether an agent is a
deterministic stand-in (see orchestrator.agents.deterministic) or a real LLM
call (see orchestrator.agents.claude_adapter) -- both implement this same
Protocol, which is what makes the agent layer pluggable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.models import ArtifactRef, RunState, TaskGraph


@dataclass
class AgentContext:
    run_id: str
    stage_id: str
    attempt: int
    graph: TaskGraph
    run_state: RunState
    upstream_artifacts: list[ArtifactRef]
    scenario_input: dict
    """Free-form scenario configuration (e.g. path to the raw requirement
    text, prior scenario's final artifact set for brownfield/ambiguous
    runs). Agents interpret the keys they care about."""


@dataclass
class AgentOutput:
    kind: str
    """Artifact kind, e.g. 'spec', 'design', 'code', 'test', 'doc'."""
    relative_path: str
    """Path relative to the run's artifact directory."""
    content: str


@dataclass
class AgentResult:
    success: bool
    outputs: list[AgentOutput] = field(default_factory=list)
    rationale: str = ""
    error: str | None = None


class Agent(Protocol):
    name: str

    def run(self, context: AgentContext) -> AgentResult: ...
