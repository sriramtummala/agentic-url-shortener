"""Reliability metrics and audit-grade run reports.

Everything here is derived purely from what the executor already persisted
(stage_states + decisions + audit_events) -- observability is a read-side
concern layered on top of the state store, not something the executor needs
to know about while it runs.

MTTR is computed from the decision-lineage timeline: for each stage that hit
at least one failure-ish event (a failed attempt, a rejected/failed gate, or
an explicit rollback) before eventually passing, the "recovery time" is the
gap between the last such event and the subsequent stage_passed decision.
MTTR is the mean of those gaps. A run with no failures has no recoveries to
measure, so MTTR is reported as None rather than a misleading 0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from orchestrator.models import DecisionRecord, RunState, StageStatus
from orchestrator.state_store import StateStore

_FAILURE_ACTIONS = {"attempt_failed", "exit_gate_failed", "entry_gate_rejected", "stage_failed", "rolled_back"}
_TERMINAL_FOR_SUCCESS_RATE = {StageStatus.PASSED, StageStatus.FAILED, StageStatus.SKIPPED}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def stage_durations(run_state: RunState) -> dict[str, Optional[float]]:
    """Wall-clock seconds spent per stage (started_at -> ended_at). None for
    stages that haven't finished (or never started)."""
    out: dict[str, Optional[float]] = {}
    for stage_id, state in run_state.stage_states.items():
        if state.started_at and state.ended_at:
            out[stage_id] = (_parse(state.ended_at) - _parse(state.started_at)).total_seconds()
        else:
            out[stage_id] = None
    return out


def end_to_end_latency(run_state: RunState) -> float:
    return (_parse(run_state.updated_at) - _parse(run_state.created_at)).total_seconds()


def success_rate(run_state: RunState) -> Optional[float]:
    """Fraction of stages that reached a terminal outcome and passed. None
    if no stage has reached a terminal outcome yet (run just started)."""
    terminal = [s for s in run_state.stage_states.values() if s.status in _TERMINAL_FOR_SUCCESS_RATE]
    if not terminal:
        return None
    passed = sum(1 for s in terminal if s.status == StageStatus.PASSED)
    return passed / len(terminal)


def retry_stats(run_state: RunState) -> dict:
    retried = {sid: s.attempts - 1 for sid, s in run_state.stage_states.items() if s.attempts > 1}
    return {
        "stages_with_retries": len(retried),
        "total_retries": sum(retried.values()),
        "retries_by_stage": retried,
    }


def rollback_stats(run_state: RunState) -> dict:
    rolled_back = {sid: s.rollback_count for sid, s in run_state.stage_states.items() if s.rollback_count > 0}
    return {
        "stages_rolled_back": len(rolled_back),
        "total_rollbacks": sum(rolled_back.values()),
        "rollbacks_by_stage": rolled_back,
    }


def mean_time_to_recovery(decisions: list[DecisionRecord]) -> Optional[float]:
    by_stage: dict[str, list[DecisionRecord]] = {}
    for d in decisions:
        by_stage.setdefault(d.stage_id, []).append(d)

    recoveries: list[float] = []
    for stage_decisions in by_stage.values():
        stage_decisions = sorted(stage_decisions, key=lambda d: d.timestamp)
        last_failure: Optional[DecisionRecord] = None
        for d in stage_decisions:
            if d.action in _FAILURE_ACTIONS:
                last_failure = d
            elif d.action == "stage_passed" and last_failure is not None:
                recoveries.append((_parse(d.timestamp) - _parse(last_failure.timestamp)).total_seconds())
                last_failure = None
    if not recoveries:
        return None
    return sum(recoveries) / len(recoveries)


def generate_run_report(store: StateStore, run_id: str) -> dict:
    run_state = store.load_run(run_id)
    decisions = store.get_decisions(run_id)
    audit_events = store.get_audit_events(run_id)

    stages = {}
    for stage_id, state in run_state.stage_states.items():
        stages[stage_id] = {
            "status": state.status.value,
            "attempts": state.attempts,
            "rollback_count": state.rollback_count,
            "duration_seconds": stage_durations(run_state)[stage_id],
            "error": state.error,
        }

    return {
        "run_id": run_state.run_id,
        "scenario": run_state.scenario,
        "status": run_state.status.value,
        "created_at": run_state.created_at,
        "updated_at": run_state.updated_at,
        "end_to_end_latency_seconds": end_to_end_latency(run_state),
        "success_rate": success_rate(run_state),
        "retry": retry_stats(run_state),
        "rollback": rollback_stats(run_state),
        "mean_time_to_recovery_seconds": mean_time_to_recovery(decisions),
        "stages": stages,
        "decision_count": len(decisions),
        "audit_event_count": len(audit_events),
    }


def render_report_markdown(report: dict) -> str:
    lines = [
        f"# Run Report: {report['run_id']}",
        "",
        f"- Scenario: `{report['scenario']}`",
        f"- Status: **{report['status']}**",
        f"- Created: {report['created_at']}",
        f"- Updated: {report['updated_at']}",
        f"- End-to-end latency: {report['end_to_end_latency_seconds']:.3f}s",
        f"- Success rate: {_fmt_pct(report['success_rate'])}",
        f"- Retries: {report['retry']['total_retries']} across {report['retry']['stages_with_retries']} stage(s)",
        f"- Rollbacks: {report['rollback']['total_rollbacks']} across {report['rollback']['stages_rolled_back']} stage(s)",
        f"- MTTR: {_fmt_seconds(report['mean_time_to_recovery_seconds'])}",
        f"- Decisions recorded: {report['decision_count']}",
        f"- Audit events recorded: {report['audit_event_count']}",
        "",
        "## Stages",
        "",
        "| Stage | Status | Attempts | Rollbacks | Duration (s) | Error |",
        "|---|---|---|---|---|---|",
    ]
    for stage_id, s in report["stages"].items():
        duration = f"{s['duration_seconds']:.3f}" if s["duration_seconds"] is not None else "-"
        error = (s["error"] or "").replace("|", "\\|")
        lines.append(f"| {stage_id} | {s['status']} | {s['attempts']} | {s['rollback_count']} | {duration} | {error} |")
    lines.append("")
    return "\n".join(lines)


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _fmt_seconds(value: Optional[float]) -> str:
    return "n/a (no recoveries observed)" if value is None else f"{value:.3f}s"
