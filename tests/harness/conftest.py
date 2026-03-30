"""Shared pytest fixtures for harness tests.

Provides temporary project directories with realistic sample specs,
BACKLOG.md, CURRENT_TASKS.md, and LAST_SESSION.md files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

import pytest


@dataclass
class SampleSpec:
    """Definition of a sample spec file to generate."""
    number: str
    slug: str
    title: str
    status: str
    done_when_items: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        """Return the spec filename, e.g. '001-vision.md'."""
        return f"{self.number}-{self.slug}.md"

    def render(self) -> str:
        """Render the spec as markdown content."""
        lines = [
            f"# {self.title}",
            "",
            f"**Status:** {self.status}",
            "",
            "## Overview",
            "",
            f"This is the overview for {self.title}.",
            "",
            "## Done When",
            "",
        ]
        for item in self.done_when_items:
            lines.append(f"- [ ] {item}")
        lines.append("")
        return "\n".join(lines)


DEFAULT_SPECS = [
    SampleSpec(
        number="000",
        slug="vision",
        title="Project Vision",
        status="active",
        done_when_items=[
            "`README.md` file exists",
            "`specs/` mentions framework goals",
            "All stakeholders agree on direction",
        ],
    ),
    SampleSpec(
        number="001",
        slug="session-harness",
        title="Session Harness",
        status="active",
        done_when_items=[
            "`lib/python/harness/state.py` exists",
            "`lib/python/harness/parser.py` contains extract_done_when",
            "pytest tests pass for harness modules",
            "spec:000 status is active",
        ],
    ),
    SampleSpec(
        number="002",
        slug="backlog-workflow",
        title="Backlog Workflow",
        status="draft",
        done_when_items=[
            "`BACKLOG.md` file exists",
            "Backlog items are triaged weekly",
        ],
    ),
    SampleSpec(
        number="003",
        slug="validation-tiers",
        title="Validation Tiers",
        status="done",
        done_when_items=[
            "`lib/python/harness/gates.py` exists",
            "Gate evaluator returns structured results",
        ],
    ),
]

SAMPLE_BACKLOG = """\
# BACKLOG

## Priorities
- Implement checkpoint automation
- Add LLM judgment integration
- Write end-to-end session tests

## Icebox
- Explore multi-project support
- Dashboard UI for spec status
"""

SAMPLE_CURRENT_TASKS = """\
# Current Tasks

## Active
- Finish spec:001 Done When automation
- Write conftest fixtures for harness tests

## Completed
- Set up project directory structure
- Create initial parser module
"""

SAMPLE_LAST_SESSION = """\
# Last Session

## Date
{date}

## Focus
Implementing session harness core modules.

## Completed
- Built parser.py with extract_done_when
- Created state.py with phase transitions
- Defined gate checks in gates.py

## Next
- Write shared test fixtures
- Add spec_check integration tests
"""


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def sample_specs() -> list[SampleSpec]:
    """Return the default list of SampleSpec definitions."""
    return list(DEFAULT_SPECS)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a realistic temporary project directory.

    Structure:
        tmp_path/
            specs/
                000-vision.md
                001-session-harness.md
                002-backlog-workflow.md
                003-validation-tiers.md
            lib/python/harness/
                state.py       (empty placeholder)
                parser.py      (empty placeholder)
                gates.py       (empty placeholder)
            BACKLOG.md
            CURRENT_TASKS.md
            LAST_SESSION.md
            README.md
    """
    # Write spec files
    specs_dir = tmp_path / "specs"
    for spec in DEFAULT_SPECS:
        _write_file(specs_dir / spec.filename, spec.render())

    # Write harness placeholder files so file_exists checks can pass
    harness_dir = tmp_path / "lib" / "python" / "harness"
    for module_name in ("state.py", "parser.py", "gates.py"):
        _write_file(harness_dir / module_name, f'"""{module_name} placeholder."""\n')

    # Write session markdown files
    from datetime import date
    today = date.today().isoformat()

    _write_file(tmp_path / "BACKLOG.md", SAMPLE_BACKLOG)
    _write_file(tmp_path / "CURRENT_TASKS.md", SAMPLE_CURRENT_TASKS)
    _write_file(tmp_path / "LAST_SESSION.md", SAMPLE_LAST_SESSION.format(date=today))
    _write_file(tmp_path / "README.md", "# Sample Project\n\nA test project for harness fixtures.\n")

    return tmp_path


@pytest.fixture
def tmp_project_minimal(tmp_path: Path) -> Path:
    """Create a minimal project with only one active spec and no extra files."""
    spec = DEFAULT_SPECS[0]
    _write_file(tmp_path / "specs" / spec.filename, spec.render())
    _write_file(tmp_path / "README.md", "# Minimal\n")
    return tmp_path


@pytest.fixture
def tmp_project_empty(tmp_path: Path) -> Path:
    """Create an empty project directory — no specs, no markdown files."""
    (tmp_path / "specs").mkdir()
    return tmp_path


@pytest.fixture
def harness_state_file(tmp_project: Path) -> Path:
    """Write a .harness.json in the tmp_project with WORKING phase."""
    state_data = {
        "phase": "working",
        "started_at": "2025-01-01T00:00:00+00:00",
        "branch": "feat/session-harness",
        "active_specs": ["001"],
        "focus": "Session harness implementation",
        "gates_passed": {"activation": True},
        "artifacts": [],
        "last_transition": "2025-01-01T00:05:00+00:00",
    }
    state_path = tmp_project / ".harness.json"
    state_path.write_text(json.dumps(state_data, indent=2) + "\n", encoding="utf-8")
    return state_path
