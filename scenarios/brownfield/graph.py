"""TaskGraph for the brownfield rate-limit/idempotency bug fix.

Unlike greenfield's incrementally-grown graph, this one is built upfront in
one shot: it's a scoped, already-understood fix (diagnose -> fix -> test),
not an exploratory build. It also uses a stage type greenfield never
needed -- codebase_reasoning -- which does real static analysis over the
existing codebase rather than templating from pre-decided content, matching
the 'Codebase Reasoning (Brownfield)' requirement directly.
"""

from __future__ import annotations

from orchestrator.models import GateSpec, GateType, StageDefinition, TaskGraph

CODE_GATES = [
    GateSpec(id="secret-scan", type=GateType.POLICY, description="scan for hardcoded secrets",
             config={"rule": "secret_scan"}),
    GateSpec(id="dangerous-code-scan", type=GateType.POLICY, description="block dangerous constructs",
             config={"rule": "no_dangerous_code"}),
    GateSpec(id="pii-scan", type=GateType.POLICY, description="scan for PII-shaped values",
             config={"rule": "pii_scan"}),
]


def build_graph() -> TaskGraph:
    return TaskGraph(
        id="brownfield-rate-limit-idempotency-fix",
        stages={
            "requirements": StageDefinition(
                id="requirements", name="Requirements", agent="requirements", produces=["spec"],
            ),
            "codebase_reasoning": StageDefinition(
                id="codebase_reasoning", name="Codebase Impact Analysis", agent="codebase_reasoning",
                depends_on=["requirements"], produces=["impact_analysis"],
            ),
            "design": StageDefinition(
                id="design", name="Design", agent="design",
                depends_on=["requirements", "codebase_reasoning"], produces=["design"],
            ),
            "implementation": StageDefinition(
                id="implementation", name="Implementation", agent="implementation",
                depends_on=["design"], produces=["code"], exit_gates=CODE_GATES,
            ),
            "test": StageDefinition(
                id="test", name="Test", agent="test", depends_on=["design"], produces=["test"],
            ),
            "documentation": StageDefinition(
                id="documentation", name="Documentation", agent="documentation",
                depends_on=["design"], produces=["doc"],
            ),
            "release_readiness": StageDefinition(
                id="release_readiness", name="Release Readiness", agent="release_readiness",
                depends_on=["implementation", "test", "documentation"],
                high_impact=True,
                entry_gates=[
                    GateSpec(id="release-approval", type=GateType.APPROVAL,
                             description="human sign-off required before release"),
                ],
            ),
        },
    )
