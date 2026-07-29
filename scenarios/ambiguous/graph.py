"""TaskGraph for the ambiguous 'protect against bad links' scenario.

The differentiator versus greenfield/brownfield: the `requirements` stage
itself is high_impact=True with an APPROVAL *exit* gate -- governance
applied to locking in an interpretation of a vague ask, not just to
release. Everything downstream is unreachable until a human signs off on
the normalized requirement.
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
        id="ambiguous-bad-link-protection",
        stages={
            "requirements": StageDefinition(
                id="requirements", name="Requirements", agent="requirements", produces=["spec"],
                high_impact=True,
                exit_gates=[
                    GateSpec(id="interpretation-approval", type=GateType.APPROVAL,
                             description="human sign-off on the normalized interpretation before any "
                                         "design/implementation work begins"),
                ],
            ),
            "design": StageDefinition(
                id="design", name="Design", agent="design", depends_on=["requirements"], produces=["design"],
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
