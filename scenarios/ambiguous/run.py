"""Shared paths and scenario-input builder for the ambiguous scenario.

Not meant to be run directly -- see step_1_propose_interpretation.py and
step_2_rework_after_rejection.py, which both import from here.
"""

from __future__ import annotations

from pathlib import Path

from scenarios.ambiguous import scenario_input as si

SCENARIO_DIR = Path(__file__).parent
STATE_DB = SCENARIO_DIR / "run_state" / "state.db"
ARTIFACT_ROOT = SCENARIO_DIR / "artifacts"
REPORT_PATH = SCENARIO_DIR / "report.md"
RUN_ID = "ambiguous-run-1"


def build_scenario_input(requirement_version: str) -> dict:
    normalized = {
        "v1": si.NORMALIZED_REQUIREMENT_V1_OVERSCOPED,
        "v2": si.NORMALIZED_REQUIREMENT_V2_SCOPED,
    }[requirement_version]
    return {
        "requirement_text": si.REQUIREMENT_TEXT,
        "normalized_requirement": normalized,
        "design": si.DESIGN,
        "source_files": si.source_files(),
        "test_files": si.test_files(),
        "doc_files": si.doc_files(),
    }
