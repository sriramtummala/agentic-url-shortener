"""Gate evaluation: policy guardrails, automated checks, and human approval.

A stage's entry_gates run before its agent is invoked; exit_gates run after
the agent succeeds, against the artifacts it produced. Any gate can put a
stage into one of three outcomes: passed, blocked (waiting on something
external -- currently only human approval), or failed.

This module wires the *mechanism* (how gates are evaluated and how approval
requests are tracked in the state store). The actual policy rules enforced
by POLICY/AUTOMATED_CHECK gates live in orchestrator.guardrails -- here we
default to a permissive engine so the executor is fully functional before
that piece exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from orchestrator.models import ArtifactRef, GateSpec, GateType, StageDefinition
from orchestrator.state_store import StateStore


@dataclass
class GateContext:
    run_id: str
    stage: StageDefinition
    phase: str  # "entry" | "exit"
    artifacts: list[ArtifactRef]


@dataclass
class GateResult:
    gate_id: str
    passed: bool
    blocked: bool
    reason: str


class GuardrailEngine(ABC):
    """Evaluates POLICY and AUTOMATED_CHECK gates. Never handles APPROVAL
    gates -- those are always routed to ApprovalGateHandler regardless of
    which engine is plugged in, since approval requires a human, not a
    policy check."""

    @abstractmethod
    def check(self, gate: GateSpec, ctx: GateContext) -> GateResult: ...


class PermissiveGuardrailEngine(GuardrailEngine):
    """Placeholder engine: every policy/automated-check gate passes. Used
    until a real guardrail engine (secret scanning, license checks, schema
    contract checks, etc.) is plugged in."""

    def check(self, gate: GateSpec, ctx: GateContext) -> GateResult:
        return GateResult(gate_id=gate.id, passed=True, blocked=False, reason="no policy engine configured")


class ApprovalGateHandler:
    """Tracks human approval checkpoints via the state store's approvals
    table. The first time a stage hits an APPROVAL gate, a pending request
    is created and the stage blocks. Subsequent evaluations (e.g. after the
    executor is re-invoked following a human decision) read the same
    request back.

    The approval id is scoped to (stage, gate, incarnation) rather than just
    (stage, gate): if the stage is later rolled back or re-planned (its
    incarnation bumps), it gets a brand new pending approval instead of
    silently inheriting the previous incarnation's decision. A human
    approving one version of a stage's output must not be read as approving
    a materially different re-execution of it later."""

    def __init__(self, store: StateStore, id_fn, now_fn):
        self.store = store
        self._id_fn = id_fn
        self._now_fn = now_fn

    def evaluate(self, run_id: str, stage: StageDefinition, gate: GateSpec, incarnation: int) -> GateResult:
        approval_id = f"{run_id}:{stage.id}:{gate.id}:{incarnation}"
        existing = self.store.get_approval(approval_id)
        if existing is None:
            self.store.request_approval(approval_id, run_id, stage.id, gate.id, self._now_fn())
            return GateResult(
                gate_id=gate.id, passed=False, blocked=True,
                reason=f"awaiting human approval ({gate.description})",
            )
        if existing["status"] == "pending":
            return GateResult(
                gate_id=gate.id, passed=False, blocked=True,
                reason=f"awaiting human approval ({gate.description})",
            )
        if existing["status"] == "approved":
            return GateResult(
                gate_id=gate.id, passed=True, blocked=False,
                reason=f"approved by {existing['resolved_by']}: {existing['comment'] or ''}".strip(),
            )
        return GateResult(
            gate_id=gate.id, passed=False, blocked=False,
            reason=f"rejected by {existing['resolved_by']}: {existing['comment'] or ''}".strip(),
        )


class GateRunner:
    def __init__(self, guardrail_engine: GuardrailEngine, approval_handler: ApprovalGateHandler):
        self.guardrail_engine = guardrail_engine
        self.approval_handler = approval_handler

    def evaluate(
        self, run_id: str, stage: StageDefinition, gates: list[GateSpec], phase: str,
        incarnation: int, artifacts: list[ArtifactRef] | None = None,
    ) -> GateResult:
        if not gates:
            return GateResult(gate_id="-", passed=True, blocked=False, reason="no gates defined")
        ctx = GateContext(run_id=run_id, stage=stage, phase=phase, artifacts=artifacts or [])
        for gate in gates:
            if gate.type == GateType.APPROVAL:
                result = self.approval_handler.evaluate(run_id, stage, gate, incarnation)
            else:
                result = self.guardrail_engine.check(gate, ctx)
            if result.blocked:
                return result
            if not result.passed:
                return result
        return GateResult(gate_id=gates[-1].id, passed=True, blocked=False, reason="all gates passed")
