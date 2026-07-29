"""Optional pluggable agent: generates artifact content via the real Claude
API instead of replaying pre-authored content (see agents/deterministic.py
for that default path).

Requires the `anthropic` package (the project's `claude` extra) and
ANTHROPIC_API_KEY to be set. Both are checked at first use and raise
immediately with an actionable message -- a misconfigured environment must
fail loudly, not silently fall back to a different agent behind the
caller's back.
"""

from __future__ import annotations

import os
import re

from orchestrator.agents.base import AgentContext, AgentOutput, AgentResult

_FILE_MARKER = re.compile(r"^---\s*FILE:\s*(?P<path>\S+)\s*---\s*$", re.MULTILINE)

DEFAULT_MODEL = "claude-sonnet-5"

_FILE_FORMAT_INSTRUCTIONS = (
    "Produce your output using exactly this format for every file you write, "
    "with no other text before, between, or after the file blocks:\n\n"
    "--- FILE: relative/path ---\n<file content>\n"
)


class ClaudeAgent:
    """Wraps a single Claude API call for one SDLC stage. `kind` is the
    artifact kind stamped on every file this stage produces -- one call
    represents one stage, so one kind per agent instance."""

    def __init__(self, name: str, kind: str, system_prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 4096):
        self.name = name
        self.kind = kind
        self.system_prompt = system_prompt
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "ClaudeAgent requires the 'anthropic' package: pip install -e '.[claude]'"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ClaudeAgent requires the ANTHROPIC_API_KEY environment variable to be set")
        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _build_user_message(self, context: AgentContext) -> str:
        parts = [f"Scenario input:\n{context.scenario_input}", ""]
        if context.upstream_artifacts:
            parts.append("Upstream artifacts:")
            for artifact in context.upstream_artifacts:
                parts.append(f"--- {artifact.kind}: {artifact.path} ---")
                parts.append(context.read_artifact(artifact))
            parts.append("")
        parts.append(_FILE_FORMAT_INSTRUCTIONS)
        return "\n".join(parts)

    def run(self, context: AgentContext) -> AgentResult:
        client = self._ensure_client()
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": self._build_user_message(context)}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
        outputs = self._parse_files(text)
        if not outputs:
            return AgentResult(success=False, error="Claude response contained no '--- FILE: ... ---' blocks")
        return AgentResult(success=True, outputs=outputs, rationale=f"generated {len(outputs)} file(s) via {self.model}")

    def _parse_files(self, text: str) -> list[AgentOutput]:
        matches = list(_FILE_MARKER.finditer(text))
        outputs = []
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip("\n")
            outputs.append(AgentOutput(kind=self.kind, relative_path=match.group("path"), content=content))
        return outputs
