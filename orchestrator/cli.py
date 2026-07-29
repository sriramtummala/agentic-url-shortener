"""Operator CLI for inspecting orchestration runs and resolving human
approval checkpoints.

This is the human-facing surface for the approval mechanism built in
executor.py/gates.py: list what's waiting on a decision, and decide it.
The actual governance rule (a resolver identity must be human, and a
rejection must carry a rationale) is enforced one layer down in
StateStore.resolve_approval -- this CLI is just the ergonomic front door,
not the enforcement point, so no other caller can bypass the rule by
skipping the CLI.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from orchestrator.state_store import StateStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cmd_runs_list(args, store: StateStore) -> int:
    runs = store.list_runs()
    if not runs:
        print("no runs found")
        return 0
    for r in runs:
        print(f"{r['run_id']}  scenario={r['scenario']}  status={r['status']}  updated={r['updated_at']}")
    return 0


def _cmd_runs_show(args, store: StateStore) -> int:
    run = store.load_run(args.run_id)
    print(f"run {run.run_id}  scenario={run.scenario}  status={run.status.value}")
    for stage_id, state in run.stage_states.items():
        print(
            f"  {stage_id:20s} {state.status.value:16s} attempts={state.attempts} "
            f"rollback_count={state.rollback_count} error={state.error or ''}"
        )
    return 0


def _cmd_approvals_list(args, store: StateStore) -> int:
    pending = store.get_pending_approvals(args.run_id)
    if not pending:
        print("no pending approvals")
        return 0
    for a in pending:
        print(f"{a['id']}  run={a['run_id']}  stage={a['stage_id']}  gate={a['gate_id']}  requested_at={a['requested_at']}")
    return 0


def _cmd_approvals_decide(args, store: StateStore) -> int:
    resolved_by = f"human:{args.by}"
    try:
        store.resolve_approval(args.approval_id, args.status, resolved_by, _now(), comment=args.comment)
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"approval {args.approval_id} marked {args.status} by {resolved_by}")
    print("re-run the scenario/executor for this run_id to pick up the decision")
    return 0


def _cmd_audit(args, store: StateStore) -> int:
    for event in store.get_audit_events(args.run_id):
        print(f"[{event['timestamp']}] {event['level']:5s} {event['message']}")
    return 0


def _cmd_decisions(args, store: StateStore) -> int:
    for d in store.get_decisions(args.run_id, stage_id=args.stage):
        print(f"[{d.timestamp}] {d.stage_id:20s} {d.actor:20s} {d.action:20s} {d.rationale}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Inspect runs and resolve approval checkpoints")
    parser.add_argument("--db", default="orchestrator_state.db", help="path to the run's SQLite state file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_runs = sub.add_parser("runs", help="inspect runs")
    runs_sub = p_runs.add_subparsers(dest="runs_command", required=True)
    runs_sub.add_parser("list", help="list all runs").set_defaults(func=_cmd_runs_list)
    p_show = runs_sub.add_parser("show", help="show one run's stage states")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=_cmd_runs_show)

    p_approvals = sub.add_parser("approvals", help="manage human approval checkpoints")
    approvals_sub = p_approvals.add_subparsers(dest="approvals_command", required=True)
    p_list = approvals_sub.add_parser("list", help="list pending approvals")
    p_list.add_argument("--run", dest="run_id", default=None)
    p_list.set_defaults(func=_cmd_approvals_list)
    p_decide = approvals_sub.add_parser("decide", help="approve or reject a pending approval")
    p_decide.add_argument("approval_id")
    p_decide.add_argument("--by", required=True, help="name of the human making the decision")
    p_decide.add_argument("--status", required=True, choices=["approved", "rejected"])
    p_decide.add_argument("--comment", default=None, help="rationale (required when rejecting)")
    p_decide.set_defaults(func=_cmd_approvals_decide)

    p_audit = sub.add_parser("audit", help="print the audit log for a run")
    p_audit.add_argument("run_id")
    p_audit.set_defaults(func=_cmd_audit)

    p_decisions = sub.add_parser("decisions", help="print decision lineage for a run")
    p_decisions.add_argument("run_id")
    p_decisions.add_argument("--stage", default=None)
    p_decisions.set_defaults(func=_cmd_decisions)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = StateStore(args.db)
    try:
        return args.func(args, store) or 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
