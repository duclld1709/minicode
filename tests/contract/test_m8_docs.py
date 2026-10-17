"""M8: the project is documented, CI-ready, and the README's numbers are real.

These are cheap guards against docs rotting: if the eval results change, the README
table must change with them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.m8

ROOT = Path(__file__).parents[2]
LEARNING = ROOT / "docs" / "learning"
NOTE_SECTIONS = ["## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."]


def test_readme_has_the_sections_a_reviewer_looks_for() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in [
        "## Features",
        "## Quick start",
        "## Architecture",
        "## Design decisions",
        "## Eval results",
        "## Limitations",
        "## Roadmap",
    ]:
        assert heading in readme, heading
    assert "```mermaid" in readme
    assert "docs/demo.tape" in readme


def test_readme_eval_table_matches_saved_results() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    results = sorted((ROOT / "evals" / "results").glob("*.json"))
    assert results, "no eval results saved"
    for path in results:
        summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
        assert f"{summary['passed']}/{summary['tasks']}" in readme
        assert f"${summary['cost']:.3f}" in readme, f"cost of {path.name} not in README"


@pytest.mark.parametrize("milestone", range(9))
def test_every_milestone_has_a_complete_learning_note(milestone: int) -> None:
    [note] = LEARNING.glob(f"m{milestone}-*.md")
    text = note.read_text(encoding="utf-8")
    for section in NOTE_SECTIONS:
        assert section in text, f"{note.name} is missing section {section}"


def test_interview_questions() -> None:
    text = (LEARNING / "interview-questions.md").read_text(encoding="utf-8")
    questions = re.findall(r"^\*\*\d+\. ", text, flags=re.MULTILINE)
    assert len(questions) >= 25
    assert text.count("→") >= 25  # every question points to code


def test_ci_runs_lint_types_and_offline_tests() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    steps = " ".join(str(step.get("run", "")) for step in workflow["jobs"]["checks"]["steps"])
    for command in ["ruff check", "ruff format --check", "mypy src", "pytest"]:
        assert command in steps
    assert "--run-live" not in steps  # CI must never spend money


def test_architecture_doc_exists() -> None:
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "```mermaid" in text
    assert "Safety model" in text
