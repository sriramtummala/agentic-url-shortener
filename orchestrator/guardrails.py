"""Concrete policy guardrail rules for POLICY/AUTOMATED_CHECK gates.

Each rule is small, independently testable, and reads produced artifact
content straight off disk (via artifact_root + ArtifactRef.path) rather than
requiring the executor to thread file contents through the gate context.

Dispatch is fail-closed by design: a GateSpec names which rule it wants via
`config={"rule": "<rule_id>"}`, and an unknown or missing rule name fails
the gate rather than passing it. A guardrail that silently no-ops on
misconfiguration is worse than no guardrail at all, because it looks like
protection without providing any.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from orchestrator.gates import GateContext, GateResult, GuardrailEngine
from orchestrator.models import GateSpec


class GuardrailRule(ABC):
    id: str

    @abstractmethod
    def evaluate(self, ctx: GateContext, artifact_root: Path) -> GateResult: ...


def _read_all(ctx: GateContext, artifact_root: Path, kind: Optional[str] = None) -> list[tuple[str, str]]:
    """Return (relative_path, content) pairs for artifacts in ctx, optionally
    filtered by kind. Centralized so every rule reads artifacts the same way."""
    out = []
    for artifact in ctx.artifacts:
        if kind is not None and artifact.kind != kind:
            continue
        out.append((artifact.path, (artifact_root / artifact.path).read_text(encoding="utf-8")))
    return out


_SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("hardcoded api key", re.compile(r"api[_-]?key\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.IGNORECASE)),
    (
        "hardcoded password",
        re.compile(r"password\s*=\s*['\"](?!changeme|password|<[^>]+>)[^'\"]{6,}['\"]", re.IGNORECASE),
    ),
]


class SecretScanRule(GuardrailRule):
    id = "secret_scan"

    def evaluate(self, ctx: GateContext, artifact_root: Path) -> GateResult:
        for path, content in _read_all(ctx, artifact_root):
            for label, pattern in _SECRET_PATTERNS:
                if pattern.search(content):
                    return GateResult(gate_id=self.id, passed=False, blocked=False,
                                       reason=f"potential {label} found in {path}")
        return GateResult(gate_id=self.id, passed=True, blocked=False, reason="no secrets detected")


_DANGEROUS_PATTERNS = [
    ("eval(", re.compile(r"\beval\s*\(")),
    ("exec(", re.compile(r"\bexec\s*\(")),
    ("os.system(", re.compile(r"\bos\.system\s*\(")),
    ("subprocess shell=True", re.compile(r"shell\s*=\s*True")),
    ("pickle.loads(", re.compile(r"\bpickle\.loads\s*\(")),
]


class NoDangerousConstructsRule(GuardrailRule):
    """Change-control style guardrail: blocks known-risky constructs from
    ever reaching a produced code artifact, regardless of which agent wrote
    it."""

    id = "no_dangerous_code"

    def evaluate(self, ctx: GateContext, artifact_root: Path) -> GateResult:
        for path, content in _read_all(ctx, artifact_root, kind="code"):
            for label, pattern in _DANGEROUS_PATTERNS:
                if pattern.search(content):
                    return GateResult(gate_id=self.id, passed=False, blocked=False,
                                       reason=f"disallowed construct '{label}' found in {path}")
        return GateResult(gate_id=self.id, passed=True, blocked=False, reason="no disallowed constructs found")


_PII_PATTERNS = [
    ("SSN-like value", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit-card-like value", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]


class PiiScanRule(GuardrailRule):
    """Blocks PII/PCI-shaped literals (SSN-like, card-number-like) from
    landing in generated artifacts -- e.g. an agent embedding a realistic
    sample SSN in a fixture or example payload."""

    id = "pii_scan"

    def evaluate(self, ctx: GateContext, artifact_root: Path) -> GateResult:
        for path, content in _read_all(ctx, artifact_root):
            for label, pattern in _PII_PATTERNS:
                if pattern.search(content):
                    return GateResult(gate_id=self.id, passed=False, blocked=False,
                                       reason=f"potential {label} found in {path}")
        return GateResult(gate_id=self.id, passed=True, blocked=False, reason="no PII-shaped values detected")


class RequiredArtifactsRule(GuardrailRule):
    """Completeness check independent of gate config: confirms a stage
    actually produced every artifact kind it declared via
    StageDefinition.produces."""

    id = "required_artifacts"

    def evaluate(self, ctx: GateContext, artifact_root: Path) -> GateResult:
        produced_kinds = {a.kind for a in ctx.artifacts}
        missing = [k for k in ctx.stage.produces if k not in produced_kinds]
        if missing:
            return GateResult(
                gate_id=self.id, passed=False, blocked=False,
                reason=f"stage declared produces={ctx.stage.produces} but is missing: {missing}",
            )
        return GateResult(gate_id=self.id, passed=True, blocked=False, reason="all declared artifact kinds present")


class PolicyGuardrailEngine(GuardrailEngine):
    def __init__(self, artifact_root: str | Path, rules: Optional[list[GuardrailRule]] = None):
        self.artifact_root = Path(artifact_root)
        rules = rules if rules is not None else [
            SecretScanRule(), NoDangerousConstructsRule(), PiiScanRule(), RequiredArtifactsRule(),
        ]
        self._rules = {rule.id: rule for rule in rules}

    def check(self, gate: GateSpec, ctx: GateContext) -> GateResult:
        rule_id = gate.config.get("rule")
        rule = self._rules.get(rule_id)
        if rule is None:
            return GateResult(
                gate_id=gate.id, passed=False, blocked=False,
                reason=f"no registered policy rule for gate '{gate.id}' (configured rule={rule_id!r}) -- failing closed",
            )
        result = rule.evaluate(ctx, self.artifact_root)
        return GateResult(gate_id=gate.id, passed=result.passed, blocked=result.blocked, reason=result.reason)
