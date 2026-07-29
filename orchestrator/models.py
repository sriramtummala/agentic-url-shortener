"""Core data model for the agentic SDLC orchestration engine.

This module defines the *static* graph (what stages exist, how they depend on
each other, and what gates guard them) and the *dynamic* run state (what
actually happened during one execution of that graph: statuses, retries,
artifacts, decisions, approvals). The two are kept separate on purpose --
the same TaskGraph can be executed many times (once per scenario/run) and
each execution gets its own RunState with a full audit trail.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class GateType(str, Enum):
    POLICY = "policy"              # automated guardrail check (security/compliance/change-control)
    APPROVAL = "approval"          # blocking human checkpoint
    AUTOMATED_CHECK = "automated_check"  # e.g. tests must pass, lint must pass


class StageStatus(str, Enum):
    PENDING = "pending"                  # deps not yet satisfied
    READY = "ready"                       # deps satisfied, not yet started
    BLOCKED_APPROVAL = "blocked_approval"  # waiting on a human decision
    RUNNING = "running"
    RETRYING = "retrying"
    PASSED = "passed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"
    STALE = "stale"                       # was PASSED, invalidated by upstream re-plan


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED_APPROVAL = "paused_approval"
    PAUSED_SAFE_STOP = "paused_safe_stop"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# Terminal statuses for a stage in the current pass -- the executor stops
# trying to advance a stage further once it lands in one of these.
TERMINAL_STAGE_STATUSES = {
    StageStatus.PASSED,
    StageStatus.FAILED,
    StageStatus.ROLLED_BACK,
    StageStatus.SKIPPED,
}


# --------------------------------------------------------------------------
# Static graph definition
# --------------------------------------------------------------------------

class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    fallback_agent: Optional[str] = None
    """If set, this agent is invoked instead of the primary agent once
    max_attempts is exhausted, giving the stage one last chance before it is
    marked FAILED and rollback is triggered."""


class GateSpec(BaseModel):
    id: str
    type: GateType
    description: str
    config: dict = Field(default_factory=dict)


class StageDefinition(BaseModel):
    id: str
    name: str
    agent: str
    """Key identifying which agent adapter executes this stage (see
    orchestrator.agents)."""
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: Optional[str] = None
    """Stages sharing a parallel_group are expected to run concurrently and
    are joined by a synchronization barrier before any stage that depends on
    the group is allowed to start."""
    entry_gates: list[GateSpec] = Field(default_factory=list)
    exit_gates: list[GateSpec] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    high_impact: bool = False
    """High-impact stages must carry at least one APPROVAL gate (validated
    at graph-build time) -- this is the mechanism that enforces 'human
    approval checkpoints for high-impact actions' structurally rather than
    by convention."""
    consumes: list[str] = Field(default_factory=list)
    """Artifact kinds this stage reads from upstream stages."""
    produces: list[str] = Field(default_factory=list)
    """Artifact kinds this stage is expected to emit on success."""

    @model_validator(mode="after")
    def _high_impact_requires_approval(self) -> "StageDefinition":
        if self.high_impact:
            has_approval = any(g.type == GateType.APPROVAL for g in self.entry_gates)
            if not has_approval:
                raise ValueError(
                    f"stage '{self.id}' is marked high_impact but has no "
                    "APPROVAL entry gate"
                )
        return self


class TaskGraph(BaseModel):
    id: str
    version: int = 1
    stages: dict[str, StageDefinition]

    @model_validator(mode="after")
    def _validate_graph(self) -> "TaskGraph":
        for stage_id, stage in self.stages.items():
            if stage_id != stage.id:
                raise ValueError(
                    f"graph key '{stage_id}' does not match stage.id '{stage.id}'"
                )
            for dep in stage.depends_on:
                if dep not in self.stages:
                    raise ValueError(
                        f"stage '{stage_id}' depends on unknown stage '{dep}'"
                    )
        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {sid: WHITE for sid in self.stages}

        def visit(sid: str, path: list[str]) -> None:
            color[sid] = GRAY
            for dep in self.stages[sid].depends_on:
                if color[dep] == GRAY:
                    cycle = " -> ".join(path + [dep])
                    raise ValueError(f"dependency cycle detected: {cycle}")
                if color[dep] == WHITE:
                    visit(dep, path + [dep])
            color[sid] = BLACK

        for sid in self.stages:
            if color[sid] == WHITE:
                visit(sid, [sid])

    def topological_layers(self) -> list[list[str]]:
        """Group stage ids into layers where every stage in layer N depends
        only on stages in layers < N. Stages within a layer have no
        dependency relationship to each other and are the executor's
        candidates for concurrent execution."""
        remaining = dict(self.stages)
        done: set[str] = set()
        layers: list[list[str]] = []
        while remaining:
            layer = [
                sid
                for sid, stage in remaining.items()
                if all(dep in done for dep in stage.depends_on)
            ]
            if not layer:
                # _assert_acyclic already guards against this, but keep a
                # defensive check in case the graph is mutated post-validation.
                raise ValueError("unable to make progress; cycle or missing dependency")
            layers.append(sorted(layer))
            for sid in layer:
                done.add(sid)
                del remaining[sid]
        return layers

    def downstream_of(self, stage_id: str) -> set[str]:
        """All stages transitively depending on stage_id (used by dynamic
        re-planning to know what to invalidate)."""
        result: set[str] = set()
        changed = True
        while changed:
            changed = False
            for sid, stage in self.stages.items():
                if sid in result:
                    continue
                if stage_id in stage.depends_on or (result & set(stage.depends_on)):
                    result.add(sid)
                    changed = True
        return result


# --------------------------------------------------------------------------
# Dynamic run state
# --------------------------------------------------------------------------

class ArtifactRef(BaseModel):
    id: str
    kind: str
    path: str
    produced_by_stage: str
    version: int
    content_hash: str
    created_at: str


class DecisionRecord(BaseModel):
    """A single lineage entry: who did what, why, based on which inputs,
    producing which outputs. This is the backbone of 'decision lineage' --
    every stage attempt, gate evaluation, retry, rollback, and human approval
    is captured as one of these, in order, forming a replayable trail."""

    id: str
    run_id: str
    stage_id: str
    actor: str
    """e.g. 'agent:implementation', 'human:stummala', 'gate:policy:secrets-scan'"""
    action: str
    """e.g. 'stage_started', 'stage_passed', 'gate_failed', 'approved',
    'retry_scheduled', 'rolled_back', 'replanned'"""
    rationale: str
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    timestamp: str


class StageState(BaseModel):
    stage_id: str
    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    rollback_count: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error: Optional[str] = None
    artifact_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    stale: bool = False


class RunState(BaseModel):
    run_id: str
    graph_id: str
    scenario: str
    status: RunStatus = RunStatus.RUNNING
    stage_states: dict[str, StageState]
    created_at: str
    updated_at: str

    @classmethod
    def initialize(cls, run_id: str, graph: TaskGraph, scenario: str, now: str) -> "RunState":
        return cls(
            run_id=run_id,
            graph_id=graph.id,
            scenario=scenario,
            stage_states={
                sid: StageState(stage_id=sid) for sid in graph.stages
            },
            created_at=now,
            updated_at=now,
        )
