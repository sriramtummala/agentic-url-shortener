"""The executor: walks a TaskGraph layer by layer, running stages through
their assigned agent under bounded retries/fallback, evaluating entry/exit
gates (policy + human approval), propagating failures downstream, and
supporting explicit rollback and safe-stop.

Execution model
----------------
`run()` advances a single pass over the graph as far as it can go and then
returns -- it never blocks waiting on a human. Stages are grouped into
topological layers (orchestrator.models.TaskGraph.topological_layers); every
stage in a layer has all of its dependencies resolved in a prior layer, so
all stages within a layer are safe to execute concurrently (a real
ThreadPoolExecutor, not a simulated one) and act as a synchronization
barrier for whatever depends on them.

If any stage in a layer ends up BLOCKED_APPROVAL, the whole run is marked
PAUSED_APPROVAL and `run()` returns immediately -- re-invoking `run()` later
(after a human resolves the approval via the state store) picks up exactly
where it left off, because stage status is the source of truth, not
in-memory state.

Failure handling has three distinct, intentionally different mechanisms:
  * retry       -- bounded re-attempts of the *same* stage (RetryPolicy)
  * fallback    -- one extra attempt with a different agent after retries
                   are exhausted
  * rollback    -- an explicit, human/replanning-triggered action that
                   invalidates a *previously passed* stage and everything
                   downstream of it, marking them stale for re-execution
An unrecoverable failure (retries + fallback exhausted, or an entry/exit
gate outright rejects) marks the stage FAILED and propagates SKIPPED to
every downstream stage -- that branch is dead until a human intervenes.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from orchestrator.agents.base import Agent, AgentContext, AgentOutput, AgentResult
from orchestrator.gates import ApprovalGateHandler, GateRunner, GuardrailEngine, PermissiveGuardrailEngine
from orchestrator.models import (
    ArtifactRef,
    DecisionRecord,
    RunState,
    RunStatus,
    StageDefinition,
    StageState,
    StageStatus,
    TERMINAL_STAGE_STATUSES,
    TaskGraph,
)
from orchestrator.state_store import StateStore

_ERROR_ACTIONS = {
    "attempt_failed",
    "stage_failed",
    "stage_skipped",
    "exit_gate_failed",
    "entry_gate_rejected",
}


def _default_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_id() -> str:
    return uuid.uuid4().hex[:12]


class Executor:
    def __init__(
        self,
        graph: TaskGraph,
        store: StateStore,
        run_id: str,
        agents: dict[str, Agent],
        artifact_root: str | Path,
        guardrail_engine: Optional[GuardrailEngine] = None,
        scenario_input: Optional[dict] = None,
        max_workers: int = 4,
        now_fn=None,
        id_fn=None,
    ):
        self.graph = graph
        self.store = store
        self.run_id = run_id
        self.agents = agents
        self.artifact_root = Path(artifact_root)
        self.scenario_input = scenario_input or {}
        self.max_workers = max_workers
        self._now = now_fn or _default_now
        self._new_id = id_fn or _default_id
        self.approval_handler = ApprovalGateHandler(store, self._new_id, self._now)
        self.gate_runner = GateRunner(guardrail_engine or PermissiveGuardrailEngine(), self.approval_handler)

    # -- public entry points ------------------------------------------------

    def run(self) -> RunState:
        # Reload rather than trust the graph passed at construction time:
        # dynamic re-planning (orchestrator.replanning) mutates the
        # persisted graph between calls, and this is the one place that
        # change becomes visible without having to build a new Executor.
        self.graph = self.store.load_graph(self.run_id)
        run_state = self.store.load_run(self.run_id)
        if run_state.status == RunStatus.PAUSED_SAFE_STOP:
            # Safe-stop is sticky: it stays halted across calls until an
            # operator explicitly clears it via resume_from_safe_stop().
            return run_state
        if run_state.status == RunStatus.PAUSED_APPROVAL:
            # Unlike safe-stop, an approval pause is *not* sticky -- calling
            # run() again is itself the resume signal, and each still-blocked
            # gate will simply re-pause the run when its layer is reached.
            self.store.update_run_status(self.run_id, RunStatus.RUNNING.value, self._now())

        for layer in self.graph.topological_layers():
            current = self.store.load_run(self.run_id)
            if current.status == RunStatus.PAUSED_SAFE_STOP:
                return current
            run_state = self._process_layer(layer)
            if run_state.status in (RunStatus.PAUSED_APPROVAL, RunStatus.PAUSED_SAFE_STOP):
                return run_state
        return self._finalize()

    def request_safe_stop(self, reason: str, actor: str = "operator") -> None:
        self.store.update_run_status(self.run_id, RunStatus.PAUSED_SAFE_STOP.value, self._now())
        self.store.append_audit_event(
            self.run_id, self._now(), "warn", f"safe-stop requested by {actor}: {reason}"
        )

    def resume_from_safe_stop(self, actor: str = "operator") -> None:
        self.store.update_run_status(self.run_id, RunStatus.RUNNING.value, self._now())
        self.store.append_audit_event(self.run_id, self._now(), "info", f"safe-stop cleared by {actor}")

    def rollback_stage(self, stage_id: str, reason: str, actor: str = "operator") -> None:
        """Undo a stage that previously passed, and mark it plus everything
        downstream of it stale so the next `run()` call re-executes them."""
        now = self._now()
        run_state = self.store.load_run(self.run_id)
        stage_state = run_state.stage_states[stage_id]
        stage_state.status = StageStatus.ROLLED_BACK
        stage_state.rollback_count += 1
        stage_state.stale = True
        stage_state.ended_at = now
        self.store.save_stage_state(self.run_id, stage_state)
        self._log_decision(stage_id, actor=actor, action="rolled_back", rationale=reason)

        for downstream_id in sorted(self.graph.downstream_of(stage_id)):
            ds_state = self.store.load_run(self.run_id).stage_states[downstream_id]
            if ds_state.status == StageStatus.PENDING:
                continue
            ds_state.status = StageStatus.STALE
            ds_state.stale = True
            self.store.save_stage_state(self.run_id, ds_state)
            self._log_decision(
                downstream_id, actor=actor, action="marked_stale",
                rationale=f"upstream stage '{stage_id}' was rolled back",
            )

        if self.store.load_run(self.run_id).status != RunStatus.RUNNING:
            self.store.update_run_status(self.run_id, RunStatus.RUNNING.value, now)

    # -- layer processing ----------------------------------------------------

    def _process_layer(self, layer: list[str]) -> RunState:
        run_state = self.store.load_run(self.run_id)
        runnable = []
        for stage_id in layer:
            state = run_state.stage_states[stage_id]
            if not self._is_actionable(state):
                continue
            stage = self.graph.stages[stage_id]
            blocker = self._first_blocking_dependency(stage, run_state)
            if blocker:
                self._skip_stage(stage_id, reason=f"upstream stage '{blocker}' did not succeed")
            else:
                runnable.append(stage_id)

        if runnable:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(runnable))) as pool:
                futures = [pool.submit(self._execute_stage, sid) for sid in runnable]
                for future in futures:
                    future.result()

        run_state = self.store.load_run(self.run_id)
        if any(run_state.stage_states[sid].status == StageStatus.BLOCKED_APPROVAL for sid in layer):
            self.store.update_run_status(self.run_id, RunStatus.PAUSED_APPROVAL.value, self._now())
            self.store.append_audit_event(
                self.run_id, self._now(), "info", "run paused: one or more stages awaiting approval"
            )
            run_state = self.store.load_run(self.run_id)
        return run_state

    def _is_actionable(self, state: StageState) -> bool:
        return (
            state.status in (StageStatus.PENDING, StageStatus.BLOCKED_APPROVAL, StageStatus.STALE)
            or state.stale
        )

    def _first_blocking_dependency(self, stage: StageDefinition, run_state: RunState) -> Optional[str]:
        for dep in stage.depends_on:
            dep_state = run_state.stage_states[dep]
            if dep_state.status in (StageStatus.FAILED, StageStatus.SKIPPED):
                return dep
            if dep_state.status == StageStatus.ROLLED_BACK and not dep_state.stale:
                return dep
        return None

    # -- single stage execution ----------------------------------------------

    def _execute_stage(self, stage_id: str) -> None:
        stage = self.graph.stages[stage_id]

        entry_result = self.gate_runner.evaluate(self.run_id, stage, stage.entry_gates, "entry")
        if entry_result.blocked:
            self._update_stage(stage_id, status=StageStatus.BLOCKED_APPROVAL)
            self._log_decision(
                stage_id, actor=f"gate:{entry_result.gate_id}",
                action="entry_gate_blocked", rationale=entry_result.reason,
            )
            return
        if not entry_result.passed:
            self._log_decision(
                stage_id, actor=f"gate:{entry_result.gate_id}",
                action="entry_gate_rejected", rationale=entry_result.reason,
            )
            self._fail_stage_and_propagate(stage_id, error=entry_result.reason)
            return

        stage_state = self.store.load_run(self.run_id).stage_states[stage_id]
        attempts_used = 0 if stage_state.stale else stage_state.attempts
        max_attempts = max(1, stage.retry_policy.max_attempts)
        agent_name = stage.agent
        used_fallback = False

        while True:
            attempts_used += 1
            self._begin_attempt(stage_id, attempts_used, agent_name)

            agent = self.agents.get(agent_name)
            if agent is None:
                result = AgentResult(success=False, error=f"no agent registered for '{agent_name}'")
            else:
                context = AgentContext(
                    run_id=self.run_id,
                    stage_id=stage_id,
                    attempt=attempts_used,
                    graph=self.graph,
                    run_state=self.store.load_run(self.run_id),
                    upstream_artifacts=self._collect_upstream_artifacts(stage),
                    artifact_root=self.artifact_root,
                    scenario_input=self.scenario_input,
                )
                try:
                    result = agent.run(context)
                except Exception as exc:  # an agent bug must not crash the whole run
                    result = AgentResult(success=False, error=f"agent raised: {exc!r}")

            failure_reason = None
            if result.success:
                artifacts = self._persist_artifacts(stage_id, result.outputs)
                exit_result = self.gate_runner.evaluate(
                    self.run_id, stage, stage.exit_gates, "exit", artifacts
                )
                if exit_result.blocked:
                    self._update_stage(stage_id, status=StageStatus.BLOCKED_APPROVAL)
                    self._log_decision(
                        stage_id, actor=f"gate:{exit_result.gate_id}",
                        action="exit_gate_blocked", rationale=exit_result.reason,
                    )
                    return
                if exit_result.passed:
                    self._pass_stage(stage_id, result.rationale)
                    return
                failure_reason = exit_result.reason
                self._log_decision(
                    stage_id, actor=f"gate:{exit_result.gate_id}",
                    action="exit_gate_failed", rationale=failure_reason,
                )
            else:
                failure_reason = result.error or "agent failed"
                self._log_decision(
                    stage_id, actor=f"agent:{agent_name}",
                    action="attempt_failed", rationale=failure_reason,
                )

            if attempts_used < max_attempts:
                self._update_stage(
                    stage_id, status=StageStatus.RETRYING, attempts=attempts_used, error=failure_reason
                )
                if stage.retry_policy.backoff_seconds:
                    time.sleep(stage.retry_policy.backoff_seconds)
                continue

            if stage.retry_policy.fallback_agent and not used_fallback:
                used_fallback = True
                agent_name = stage.retry_policy.fallback_agent
                self._log_decision(
                    stage_id, actor="executor", action="fallback_invoked",
                    rationale=f"switching to fallback agent '{agent_name}' after {attempts_used} failed attempt(s)",
                )
                continue

            self._fail_stage_and_propagate(stage_id, error=failure_reason, attempts=attempts_used)
            return

    # -- stage state transitions ---------------------------------------------

    def _update_stage(self, stage_id: str, **fields) -> StageState:
        run_state = self.store.load_run(self.run_id)
        stage_state = run_state.stage_states[stage_id]
        for key, value in fields.items():
            setattr(stage_state, key, value)
        self.store.save_stage_state(self.run_id, stage_state)
        return stage_state

    def _begin_attempt(self, stage_id: str, attempt: int, agent_name: str) -> None:
        fields = {
            "status": StageStatus.RUNNING if attempt == 1 else StageStatus.RETRYING,
            "attempts": attempt,
            "error": None,
            "stale": False,
        }
        if attempt == 1:
            fields["started_at"] = self._now()
        self._update_stage(stage_id, **fields)
        self._log_decision(
            stage_id, actor=f"agent:{agent_name}", action="attempt_started",
            rationale=f"attempt {attempt} using agent '{agent_name}'",
        )

    def _pass_stage(self, stage_id: str, rationale: str) -> None:
        self._update_stage(stage_id, status=StageStatus.PASSED, ended_at=self._now(), error=None)
        agent_name = self.graph.stages[stage_id].agent
        self._log_decision(
            stage_id, actor=f"agent:{agent_name}", action="stage_passed",
            rationale=rationale or "stage completed successfully",
        )

    def _fail_stage_and_propagate(self, stage_id: str, error: str, attempts: Optional[int] = None) -> None:
        fields = {"status": StageStatus.FAILED, "ended_at": self._now(), "error": error}
        if attempts is not None:
            fields["attempts"] = attempts
        self._update_stage(stage_id, **fields)
        self._log_decision(stage_id, actor="executor", action="stage_failed", rationale=error or "stage failed")

        run_state = self.store.load_run(self.run_id)
        for downstream_id in sorted(self.graph.downstream_of(stage_id)):
            ds_state = run_state.stage_states[downstream_id]
            if ds_state.status in TERMINAL_STAGE_STATUSES:
                continue
            self._skip_stage(downstream_id, reason=f"upstream stage '{stage_id}' failed")

    def _skip_stage(self, stage_id: str, reason: str) -> None:
        self._update_stage(stage_id, status=StageStatus.SKIPPED, ended_at=self._now(), error=reason)
        self._log_decision(stage_id, actor="executor", action="stage_skipped", rationale=reason)

    def _log_decision(
        self, stage_id: str, actor: str, action: str, rationale: str,
        input_artifact_ids: Optional[list[str]] = None,
        output_artifact_ids: Optional[list[str]] = None,
    ) -> None:
        decision = DecisionRecord(
            id=self._new_id(),
            run_id=self.run_id,
            stage_id=stage_id,
            actor=actor,
            action=action,
            rationale=rationale,
            input_artifact_ids=input_artifact_ids or [],
            output_artifact_ids=output_artifact_ids or [],
            timestamp=self._now(),
        )
        self.store.record_decision(decision)
        stage_state = self.store.load_run(self.run_id).stage_states[stage_id]
        stage_state.decision_ids.append(decision.id)
        self.store.save_stage_state(self.run_id, stage_state)
        level = "error" if action in _ERROR_ACTIONS else "info"
        self.store.append_audit_event(
            self.run_id, self._now(), level, f"[{stage_id}] {action}: {rationale}", {"actor": actor}
        )

    # -- artifacts -------------------------------------------------------------

    def _collect_upstream_artifacts(self, stage: StageDefinition) -> list[ArtifactRef]:
        artifacts: list[ArtifactRef] = []
        for dep in stage.depends_on:
            artifacts.extend(self.store.get_artifacts(self.run_id, stage_id=dep))
        return artifacts

    def _persist_artifacts(self, stage_id: str, outputs: list[AgentOutput]) -> list[ArtifactRef]:
        existing = self.store.get_artifacts(self.run_id, stage_id=stage_id)
        refs: list[ArtifactRef] = []
        for output in outputs:
            version = 1 + sum(1 for a in existing if a.path == output.relative_path)
            content_hash = hashlib.sha256(output.content.encode("utf-8")).hexdigest()
            full_path = self.artifact_root / output.relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(output.content, encoding="utf-8")
            ref = ArtifactRef(
                id=self._new_id(),
                kind=output.kind,
                path=output.relative_path,
                produced_by_stage=stage_id,
                version=version,
                content_hash=content_hash,
                created_at=self._now(),
            )
            self.store.record_artifact_for_run(self.run_id, ref)
            refs.append(ref)
            existing.append(ref)

        if refs:
            stage_state = self.store.load_run(self.run_id).stage_states[stage_id]
            stage_state.artifact_ids.extend(r.id for r in refs)
            self.store.save_stage_state(self.run_id, stage_state)
        return refs

    # -- finalization ----------------------------------------------------------

    def _finalize(self) -> RunState:
        run_state = self.store.load_run(self.run_id)
        statuses = {s.status for s in run_state.stage_states.values()}
        if StageStatus.FAILED in statuses:
            final = RunStatus.FAILED
        elif statuses <= {StageStatus.PASSED, StageStatus.SKIPPED}:
            final = RunStatus.COMPLETED
        else:
            final = RunStatus.RUNNING
        self.store.update_run_status(self.run_id, final.value, self._now())
        self.store.append_audit_event(self.run_id, self._now(), "info", f"run finalized: {final.value}")
        return self.store.load_run(self.run_id)
