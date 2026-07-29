"""Builds the {agent_name: Agent} registry an Executor needs, wiring
StageDefinition.agent names to concrete deterministic implementations.

There's no equivalent "build me a Claude registry" helper: each ClaudeAgent
needs a stage-specific system prompt, so scenario runners that want live
generation for a given stage construct that one ClaudeAgent explicitly
(agents/claude_adapter.py) rather than getting one from a generic factory.
"""

from __future__ import annotations

from orchestrator.agents.deterministic import (
    CodebaseReasoningAgent,
    DesignAgent,
    DocumentationAgent,
    ImplementationAgent,
    ReleaseReadinessAgent,
    RequirementsAgent,
    TestAgent,
)


def build_deterministic_agent_registry() -> dict:
    return {
        "requirements": RequirementsAgent(),
        "design": DesignAgent(),
        "implementation": ImplementationAgent(),
        "test": TestAgent(),
        "documentation": DocumentationAgent(),
        "release_readiness": ReleaseReadinessAgent(),
        "codebase_reasoning": CodebaseReasoningAgent(),
    }
