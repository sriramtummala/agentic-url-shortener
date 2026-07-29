"""Deterministic stand-in agents: one per SDLC stage.

These agents do not perform novel synthesis at runtime. They deterministically
format already-decided content -- the actual requirement interpretation,
design decisions, and source code, supplied via AgentContext.scenario_input
-- into artifacts. Two agents do real computation instead of templating:
CodebaseReasoningAgent actually scans the on-disk codebase for impacted
files, and ReleaseReadinessAgent actually inspects which artifact kinds are
present upstream rather than being told.

This is a deliberate, documented trade-off for a reproducible prototype: the
engineering judgment (what the requirement means, how to decompose it, what
the code should be) is captured once as scenario_input and replayed
deterministically, rather than re-derived on every run. Swap in
orchestrator.agents.claude_adapter.ClaudeAgent for any stage where that
judgment should instead be made live by a model.

scenario_input keys each agent expects are documented on the agent itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from orchestrator.agents.base import AgentContext, AgentOutput, AgentResult


class RequirementsAgent:
    """Expects scenario_input['normalized_requirement'] = {
        'intent': str, 'explicit_requirements': [str], 'assumptions': [str],
        'out_of_scope': [str],
        'ambiguities': [{'question': str, 'resolution': str, 'rationale': str}],
    } and optionally scenario_input['requirement_text'] (the raw ask)."""

    name = "requirements_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        req = context.scenario_input.get("normalized_requirement")
        if not req:
            return AgentResult(success=False, error="scenario_input['normalized_requirement'] is required")
        raw = context.scenario_input.get("requirement_text", "")

        lines = [
            "# Normalized Requirement",
            "",
            "## Raw ask",
            "",
            f"> {raw}" if raw else "_(no raw ask text supplied)_",
            "",
            "## Interpreted intent",
            "",
            req.get("intent", ""),
            "",
            "## Explicit requirements",
            "",
        ]
        lines += [f"- {r}" for r in req.get("explicit_requirements", [])]
        lines += ["", "## Ambiguities identified and resolved", ""]
        for a in req.get("ambiguities", []):
            lines.append(f"- **Q:** {a['question']}")
            lines.append(f"  **Resolution:** {a['resolution']}")
            lines.append(f"  **Rationale:** {a['rationale']}")
        lines += ["", "## Assumptions", ""]
        lines += [f"- {a}" for a in req.get("assumptions", [])]
        lines += ["", "## Out of scope", ""]
        lines += [f"- {o}" for o in req.get("out_of_scope", [])]
        content = "\n".join(lines) + "\n"

        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="spec", relative_path="requirements/spec.md", content=content)],
            rationale=(
                f"normalized {len(req.get('explicit_requirements', []))} requirement(s), resolved "
                f"{len(req.get('ambiguities', []))} ambiguity/ambiguities"
            ),
        )


class DesignAgent:
    """Expects scenario_input['design'] = {
        'overview': str, 'components': [{'name': str, 'responsibility': str}],
        'decisions': [{'decision': str, 'rationale': str, 'alternatives_considered': str}],
        'api_summary': [{'method': str, 'path': str, 'description': str}],
    }."""

    name = "design_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        design = context.scenario_input.get("design")
        if not design:
            return AgentResult(success=False, error="scenario_input['design'] is required")

        upstream_specs = context.upstream_by_kind("spec")
        lineage_note = (
            f"Builds on upstream requirement artifact(s): {', '.join(a.path for a in upstream_specs)}"
            if upstream_specs else "No upstream requirement artifact found."
        )

        lines = [
            "# Architecture & Design",
            "",
            lineage_note,
            "",
            "## Overview",
            "",
            design.get("overview", ""),
            "",
            "## Components",
            "",
        ]
        lines += [f"- **{c['name']}** — {c['responsibility']}" for c in design.get("components", [])]
        lines += ["", "## Key decisions", ""]
        for d in design.get("decisions", []):
            lines.append(f"### {d['decision']}")
            lines.append(f"- Rationale: {d['rationale']}")
            if d.get("alternatives_considered"):
                lines.append(f"- Alternatives considered: {d['alternatives_considered']}")
            lines.append("")
        lines += ["## API summary", "", "| Method | Path | Description |", "|---|---|---|"]
        lines += [f"| {a['method']} | {a['path']} | {a['description']} |" for a in design.get("api_summary", [])]
        content = "\n".join(lines) + "\n"

        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="design", relative_path="design/architecture.md", content=content)],
            rationale=(
                f"documented {len(design.get('components', []))} component(s) and "
                f"{len(design.get('decisions', []))} decision(s)"
            ),
        )


class ImplementationAgent:
    """Expects scenario_input['source_files'] = {relative_path: content}."""

    name = "implementation_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        source_files = context.scenario_input.get("source_files")
        if not source_files:
            return AgentResult(success=False, error="scenario_input['source_files'] is required")
        outputs = [AgentOutput(kind="code", relative_path=p, content=c) for p, c in source_files.items()]
        return AgentResult(
            success=True, outputs=outputs,
            rationale=f"applied {len(outputs)} source file(s): {', '.join(source_files.keys())}",
        )


class TestAgent:
    """Expects scenario_input['test_files'] = {relative_path: content}."""

    name = "test_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        test_files = context.scenario_input.get("test_files")
        if not test_files:
            return AgentResult(success=False, error="scenario_input['test_files'] is required")
        outputs = [AgentOutput(kind="test", relative_path=p, content=c) for p, c in test_files.items()]
        return AgentResult(success=True, outputs=outputs, rationale=f"authored {len(outputs)} test file(s)")


class DocumentationAgent:
    """Expects scenario_input['doc_files'] = {relative_path: content}."""

    name = "documentation_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        doc_files = context.scenario_input.get("doc_files")
        if not doc_files:
            return AgentResult(success=False, error="scenario_input['doc_files'] is required")
        outputs = [AgentOutput(kind="doc", relative_path=p, content=c) for p, c in doc_files.items()]
        return AgentResult(success=True, outputs=outputs, rationale=f"produced {len(outputs)} documentation file(s)")


class ReleaseReadinessAgent:
    """Needs no scenario_input: genuinely inspects which artifact kinds are
    present among upstream artifacts and fails the stage if any required
    kind is missing."""

    name = "release_readiness_deterministic"
    REQUIRED_KINDS = ("code", "test", "doc")

    def run(self, context: AgentContext) -> AgentResult:
        present_kinds = {a.kind for a in context.upstream_artifacts}
        missing = [k for k in self.REQUIRED_KINDS if k not in present_kinds]

        lines = ["# Release Readiness Checklist", ""]
        lines += [f"- [{'x' if k not in missing else ' '}] {k} artifact present" for k in self.REQUIRED_KINDS]
        lines += ["", f"Upstream artifacts considered: {len(context.upstream_artifacts)}"]
        if missing:
            lines += ["", f"**Not ready**: missing {missing}"]

        if missing:
            return AgentResult(success=False, error=f"release readiness check failed: missing {missing}")
        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="release_report", relative_path="release/readiness.md",
                                  content="\n".join(lines) + "\n")],
            rationale="all required artifact kinds present: " + ", ".join(self.REQUIRED_KINDS),
        )


class CodebaseReasoningAgent:
    """Real static analysis, not templating: scans the on-disk codebase
    under scenario_input['scan_root'] for files referencing any of
    scenario_input['change_keywords'], to identify impacted modules for a
    brownfield change. scenario_input['change_summary'] is included in the
    artifact for readability."""

    name = "codebase_reasoning_deterministic"

    def run(self, context: AgentContext) -> AgentResult:
        scan_root = context.scenario_input.get("scan_root")
        keywords = context.scenario_input.get("change_keywords")
        if not scan_root or not keywords:
            return AgentResult(success=False, error="scenario_input requires 'scan_root' and 'change_keywords'")

        root = Path(scan_root)
        pattern = re.compile("|".join(re.escape(k) for k in keywords))
        impacted = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                impacted.append(str(path.relative_to(root)).replace("\\", "/"))

        change_summary = context.scenario_input.get("change_summary", "")
        lines = [
            "# Codebase Impact Analysis",
            "",
            f"Change: {change_summary}",
            f"Searched for keyword(s): {', '.join(keywords)}",
            "",
            "## Impacted files",
            "",
        ]
        lines += [f"- {f}" for f in impacted] or ["_(no matching files found)_"]
        content = "\n".join(lines) + "\n"

        return AgentResult(
            success=True,
            outputs=[AgentOutput(kind="impact_analysis", relative_path="analysis/impact.md", content=content)],
            rationale=f"found {len(impacted)} impacted file(s) via keyword scan of {scan_root}",
        )
