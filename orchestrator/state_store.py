"""SQLite-backed persistence for orchestration run state.

Everything the executor needs to be resumable and auditable lives here:
the graph snapshot used for a run, per-stage state, the decision-lineage
trail, produced artifacts, a free-form audit event log, and the human
approval queue. Using SQLite (rather than a JSONL file) gives us
transactional writes and queryability (e.g. "all pending approvals across
runs") for free, with zero external services required to run the prototype.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from orchestrator.models import (
    ArtifactRef,
    DecisionRecord,
    RunState,
    StageState,
    TaskGraph,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_states (
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (run_id, stage_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    comment TEXT
);
"""


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- runs -------------------------------------------------------------

    def create_run(self, run_state: RunState, graph: TaskGraph) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO runs (run_id, graph_id, graph_json, scenario,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_state.run_id,
                    graph.id,
                    graph.model_dump_json(),
                    run_state.scenario,
                    run_state.status.value,
                    run_state.created_at,
                    run_state.updated_at,
                ),
            )
            for stage_state in run_state.stage_states.values():
                self._save_stage_state_nolock(run_state.run_id, stage_state)

    def update_run_status(self, run_id: str, status: str, updated_at: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, updated_at, run_id),
            )

    def load_graph(self, run_id: str) -> TaskGraph:
        row = self._conn.execute(
            "SELECT graph_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such run: {run_id}")
        return TaskGraph.model_validate_json(row["graph_json"])

    def load_run(self, run_id: str) -> RunState:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such run: {run_id}")
        stage_rows = self._conn.execute(
            "SELECT stage_id, state_json FROM stage_states WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        stage_states = {
            r["stage_id"]: StageState.model_validate_json(r["state_json"])
            for r in stage_rows
        }
        return RunState(
            run_id=row["run_id"],
            graph_id=row["graph_id"],
            scenario=row["scenario"],
            status=row["status"],
            stage_states=stage_states,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_runs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT run_id, graph_id, scenario, status, created_at, updated_at "
            "FROM runs ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- stage state --------------------------------------------------------

    def _save_stage_state_nolock(self, run_id: str, stage_state: StageState) -> None:
        self._conn.execute(
            """INSERT INTO stage_states (run_id, stage_id, state_json)
               VALUES (?, ?, ?)
               ON CONFLICT(run_id, stage_id) DO UPDATE SET state_json = excluded.state_json""",
            (run_id, stage_state.stage_id, stage_state.model_dump_json()),
        )

    def save_stage_state(self, run_id: str, stage_state: StageState) -> None:
        with self._conn:
            self._save_stage_state_nolock(run_id, stage_state)

    # -- decisions (lineage) ------------------------------------------------

    def record_decision(self, decision: DecisionRecord) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO decisions (id, run_id, stage_id, timestamp, record_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    decision.id,
                    decision.run_id,
                    decision.stage_id,
                    decision.timestamp,
                    decision.model_dump_json(),
                ),
            )

    def get_decisions(self, run_id: str, stage_id: Optional[str] = None) -> list[DecisionRecord]:
        if stage_id:
            rows = self._conn.execute(
                "SELECT record_json FROM decisions WHERE run_id = ? AND stage_id = ? "
                "ORDER BY timestamp",
                (run_id, stage_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT record_json FROM decisions WHERE run_id = ? ORDER BY timestamp",
                (run_id,),
            ).fetchall()
        return [DecisionRecord.model_validate_json(r["record_json"]) for r in rows]

    # -- artifacts ------------------------------------------------------------

    def record_artifact_for_run(self, run_id: str, artifact: ArtifactRef) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO artifacts (id, run_id, stage_id, record_json)
                   VALUES (?, ?, ?, ?)""",
                (artifact.id, run_id, artifact.produced_by_stage, artifact.model_dump_json()),
            )

    def get_artifacts(self, run_id: str, stage_id: Optional[str] = None) -> list[ArtifactRef]:
        if stage_id:
            rows = self._conn.execute(
                "SELECT record_json FROM artifacts WHERE run_id = ? AND stage_id = ?",
                (run_id, stage_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT record_json FROM artifacts WHERE run_id = ?", (run_id,)
            ).fetchall()
        return [ArtifactRef.model_validate_json(r["record_json"]) for r in rows]

    # -- audit log ------------------------------------------------------------

    def append_audit_event(
        self, run_id: str, timestamp: str, level: str, message: str, data: Optional[dict] = None
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO audit_events (run_id, timestamp, level, message, data_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, timestamp, level, message, json.dumps(data) if data else None),
            )

    def get_audit_events(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT seq, timestamp, level, message, data_json FROM audit_events "
            "WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d.pop("data_json")) if d.get("data_json") else None
            out.append(d)
        return out

    # -- approvals ------------------------------------------------------------

    def request_approval(
        self, approval_id: str, run_id: str, stage_id: str, gate_id: str, requested_at: str
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO approvals (id, run_id, stage_id, gate_id, status, requested_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (approval_id, run_id, stage_id, gate_id, requested_at),
            )

    def resolve_approval(
        self,
        approval_id: str,
        status: str,
        resolved_by: str,
        resolved_at: str,
        comment: Optional[str] = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """UPDATE approvals SET status = ?, resolved_by = ?, resolved_at = ?,
                   comment = ? WHERE id = ?""",
                (status, resolved_by, resolved_at, comment, approval_id),
            )

    def get_pending_approvals(self, run_id: Optional[str] = None) -> list[dict]:
        if run_id:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE status = 'pending'"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_approval(self, approval_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return dict(row) if row else None
