"""Dynamic re-planning: react to upstream artifact/requirement changes.

Two distinct operations live here:

  * invalidate_downstream -- an upstream artifact changed for a reason other
    than "the stage that produced it failed" (e.g. a human edited the
    requirement doc after design was already approved, or a brownfield
    codebase-reasoning pass discovers a dependency the original impact
    analysis missed). Mechanically this looks like Executor.rollback_stage
    (mark stale, cascade downstream) but it is intentionally a separate,
    lighter-weight entry point: it only needs the state store, not a fully
    constructed Executor with an agent registry, which matters because
    replanning is often triggered by something outside the execution loop
    entirely (a human editing a doc, a CLI command).

  * insert_stage -- the stronger form of re-planning: the original graph
    didn't account for some piece of work, so a new stage is spliced into
    the *persisted* graph for a live run, wired to block whichever stages
    should wait on it. It can carry its own gates (including an approval
    gate), so inserted work is still subject to full governance.

Both operations take effect on the next Executor.run() call, because run()
reloads the graph and re-evaluates stage actionability from the state store
at the top of every pass -- re-planning here never needs to reach into a
running Executor instance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from orchestrator.models import DecisionRecord, StageDefinition, StageState, StageStatus, TaskGraph
from orchestrator.state_store import StateStore


def _default_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_id() -> str:
    return uuid.uuid4().hex[:12]


class Replanner:
    def __init__(self, store: StateStore, now_fn=None, id_fn=None):
        self.store = store
        self._now = now_fn or _default_now
        self._new_id = id_fn or _default_id

    def invalidate_downstream(self, run_id: str, changed_stage_id: str, reason: str, actor: str) -> list[str]:
        graph = self.store.load_graph(run_id)
        run_state = self.store.load_run(run_id)

        origin_state = run_state.stage_states[changed_stage_id]
        origin_state.status = StageStatus.STALE
        origin_state.stale = True
        self.store.save_stage_state(run_id, origin_state)
        self._log(run_id, changed_stage_id, actor, "replanned", reason)

        affected = sorted(graph.downstream_of(changed_stage_id))
        for stage_id in affected:
            ds_state = self.store.load_run(run_id).stage_states[stage_id]
            if ds_state.status == StageStatus.PENDING:
                continue
            ds_state.status = StageStatus.STALE
            ds_state.stale = True
            self.store.save_stage_state(run_id, ds_state)
            self._log(
                run_id, stage_id, actor, "marked_stale",
                f"upstream stage '{changed_stage_id}' was replanned: {reason}",
            )

        self.store.update_run_status(run_id, "running", self._now())
        return [changed_stage_id, *affected]

    def insert_stage(
        self, run_id: str, new_stage: StageDefinition, before_stage_ids: list[str],
        reason: str, actor: str,
    ) -> None:
        graph = self.store.load_graph(run_id)
        if new_stage.id in graph.stages:
            raise ValueError(f"stage '{new_stage.id}' already exists in graph '{graph.id}'")
        for before_id in before_stage_ids:
            if before_id not in graph.stages:
                raise ValueError(f"cannot insert before unknown stage '{before_id}'")

        stages = dict(graph.stages)
        stages[new_stage.id] = new_stage
        for before_id in before_stage_ids:
            existing = stages[before_id]
            if new_stage.id not in existing.depends_on:
                stages[before_id] = existing.model_copy(
                    update={"depends_on": [*existing.depends_on, new_stage.id]}
                )
        new_graph = TaskGraph(id=graph.id, version=graph.version + 1, stages=stages)
        self.store.update_graph(run_id, new_graph, self._now())

        run_state = self.store.load_run(run_id)
        new_state = StageState(stage_id=new_stage.id)
        self.store.save_stage_state(run_id, new_state)

        for before_id in before_stage_ids:
            before_state = run_state.stage_states[before_id]
            if before_state.status != StageStatus.PENDING:
                before_state.status = StageStatus.STALE
                before_state.stale = True
                self.store.save_stage_state(run_id, before_state)

        self._log(
            run_id, new_stage.id, actor, "stage_inserted",
            f"{reason} (now required before: {', '.join(before_stage_ids)})",
        )
        self.store.update_run_status(run_id, "running", self._now())

    def _log(self, run_id: str, stage_id: str, actor: str, action: str, rationale: str) -> None:
        decision = DecisionRecord(
            id=self._new_id(), run_id=run_id, stage_id=stage_id, actor=actor,
            action=action, rationale=rationale, timestamp=self._now(),
        )
        self.store.record_decision(decision)
        self.store.append_audit_event(
            run_id, self._now(), "info", f"[{stage_id}] {action}: {rationale}", {"actor": actor}
        )
