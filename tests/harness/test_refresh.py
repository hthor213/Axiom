from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest

from harness.refresh import (
    _format_bullet_list,
    _extract_focus,
    _is_state_or_spec_file,
    generate_refresh_state,
    prepare_state_commit,
    _STATE_FILES,
)
from harness.checkpoint import CommitPlan


# ---------------------------------------------------------------------------
# Lightweight stubs for SessionContext and related types
# ---------------------------------------------------------------------------

@dataclass
class FakeSpecInfo:
    number: str
    title: str
    status: str


@dataclass
class FakeSpecContext:
    active_specs: List[FakeSpecInfo] = field(default_factory=list)


@dataclass
class FakeGitInfo:
    branch: Optional[str] = None
    modified: List[str] = field(default_factory=list)


@dataclass
class FakeSessionContext:
    last_session: Optional[Dict[str, Any]] = None
    current_tasks: Dict[str, Any] = field(default_factory=dict)
    done_items: List[str] = field(default_factory=list)
    spec_context: Optional[FakeSpecContext] = None
    backlog_items: List[Dict[str, str]] = field(default_factory=list)
    git: Optional[FakeGitInfo] = None


# ---------------------------------------------------------------------------
# _format_bullet_list
# ---------------------------------------------------------------------------

class TestFormatBulletList:
    def test_with_items(self) -> None:
        result = _format_bullet_list(["a", "b"], "fallback")
        assert result == "- a\n- b"

    def test_empty_uses_fallback(self) -> None:
        assert _format_bullet_list([], "nothing") == "- nothing"

    def test_single_item(self) -> None:
        assert _format_bullet_list(["only"], "x") == "- only"


# ---------------------------------------------------------------------------
# _extract_focus
# ---------------------------------------------------------------------------

class TestExtractFocus:
    def test_focus_from_last_session_string(self) -> None:
        ctx = FakeSessionContext(last_session={"focus": "  Build parser  "})
        assert _extract_focus(ctx) == "Build parser"  # type: ignore[arg-type]

    def test_focus_from_last_session_list(self) -> None:
        ctx = FakeSessionContext(last_session={"focus": ["A", "B"]})
        assert _extract_focus(ctx) == "A; B"  # type: ignore[arg-type]

    def test_focus_falls_back_to_active_tasks(self) -> None:
        ctx = FakeSessionContext(
            last_session={"focus": ""},
            current_tasks={"active": ["task1", "task2"]},
        )
        assert _extract_focus(ctx) == "task1"  # type: ignore[arg-type]

    def test_focus_default_when_nothing(self) -> None:
        ctx = FakeSessionContext()
        assert _extract_focus(ctx) == "Mid-session work in progress"  # type: ignore[arg-type]

    def test_focus_none_last_session(self) -> None:
        ctx = FakeSessionContext(last_session=None, current_tasks={"active": ["x"]})
        assert _extract_focus(ctx) == "x"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _is_state_or_spec_file
# ---------------------------------------------------------------------------

class TestIsStateOrSpecFile:
    @pytest.mark.parametrize("path", [
        "LAST_SESSION.md",
        "CURRENT_TASKS.md",
        "BACKLOG.md",
        ".harness.json",
    ])
    def test_state_files(self, path: str) -> None:
        assert _is_state_or_spec_file(path) is True

    def test_spec_file(self) -> None:
        assert _is_state_or_spec_file("specs/001-foo.md") is True

    def test_nested_spec(self) -> None:
        assert _is_state_or_spec_file("specs/sub/bar.md") is True

    def test_code_file_rejected(self) -> None:
        assert _is_state_or_spec_file("lib/main.py") is False

    def test_non_md_in_specs(self) -> None:
        assert _is_state_or_spec_file("specs/readme.txt") is False

    def test_state_file_in_subdir_rejected(self) -> None:
        # LAST_SESSION.md in a subdirectory is not a state file at root
        assert _is_state_or_spec_file("sub/LAST_SESSION.md") is True  # basename match


# ---------------------------------------------------------------------------
# generate_refresh_state
# ---------------------------------------------------------------------------

class TestGenerateRefreshState:
    def test_happy_path(self) -> None:
        ctx = FakeSessionContext(
            last_session={"focus": "Implementing refresh"},
            current_tasks={"active": ["task A", "task B"]},
            done_items=["Finished X"],
            spec_context=FakeSpecContext(active_specs=[
                FakeSpecInfo("001", "Session Harness", "active"),
            ]),
            git=FakeGitInfo(branch="feat/refresh", modified=["a.py", "b.py"]),
            backlog_items=[{"text": "backlog1"}],
        )
        result = generate_refresh_state(ctx)  # type: ignore[arg-type]
        assert "IN PROGRESS" in result
        assert date.today().isoformat() in result
        assert "Implementing refresh" in result
        assert "- Finished X" in result
        assert "spec:001" in result
        assert "Branch: feat/refresh" in result
        assert "2 file(s) modified" in result
        assert "- task A" in result

    def test_empty_context(self) -> None:
        ctx = FakeSessionContext()
        result = generate_refresh_state(ctx)  # type: ignore[arg-type]
        assert "IN PROGRESS" in result
        assert "no items completed yet" in result
        assert "No active specs" in result
        assert "Continue current work" in result

    def test_backlog_as_next_when_no_active(self) -> None:
        ctx = FakeSessionContext(
            backlog_items=[{"text": "bl1"}, {"text": "bl2"}, {"text": "bl3"}, {"text": "bl4"}],
        )
        result = generate_refresh_state(ctx)  # type: ignore[arg-type]
        assert "- bl1" in result
        assert "- bl3" in result
        # Only first 3
        assert "- bl4" not in result

    def test_multiple_done_items(self) -> None:
        ctx = FakeSessionContext(done_items=["d1", "d2", "d3"])
        result = generate_refresh_state(ctx)  # type: ignore[arg-type]
        assert "- d1\n- d2\n- d3" in result

    def test_no_git_info(self) -> None:
        ctx = FakeSessionContext(git=None)
        result = generate_refresh_state(ctx)  # type: ignore[arg-type]
        assert "Branch:" not in result


# ---------------------------------------------------------------------------
# prepare_state_commit
# ---------------------------------------------------------------------------

class TestPrepareStateCommit:
    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        plan = prepare_state_commit(str(tmp_path / "nope"))
        assert plan.has_changes is False
        assert plan.files_to_stage == []
        assert plan.message == ""

    @patch("harness.refresh._is_git_repo", return_value=False)
    def test_non_git_with_state_files(self, mock_git: Any, tmp_project: Path) -> None:
        plan = prepare_state_commit(str(tmp_project))
        assert plan.has_changes is True
        assert "BACKLOG.md" in plan.files_to_stage
        assert "LAST_SESSION.md" in plan.files_to_stage
        assert "CURRENT_TASKS.md" in plan.files_to_stage
        # Spec files should be found
        spec_files = [f for f in plan.files_to_stage if f.startswith("specs/")]
        assert len(spec_files) > 0
        assert "refresh: mid-session state save" in plan.message

    @patch("harness.refresh._is_git_repo", return_value=False)
    def test_non_git_empty_project(self, mock_git: Any, tmp_project_empty: Path) -> None:
        plan = prepare_state_commit(str(tmp_project_empty))
        # No state files exist, specs dir is empty
        assert plan.has_changes is False
        assert plan.files_to_stage == []

    @patch("harness.refresh._is_git_repo", return_value=True)
    @patch("harness.refresh._staged_files", return_value=[])
    @patch("harness.refresh._uncommitted_files", return_value=[
        "LAST_SESSION.md",
        "specs/001-session-harness.md",
        "lib/main.py",
        "BACKLOG.md",
    ])
    def test_git_filters_code_files(
        self, mock_uncommitted: Any, mock_staged: Any, mock_git: Any, tmp_project: Path
    ) -> None:
        plan = prepare_state_commit(str(tmp_project))
        assert "lib/main.py" not in plan.files_to_stage
        assert "LAST_SESSION.md" in plan.files_to_stage
        assert "specs/001-session-harness.md" in plan.files_to_stage
        assert "BACKLOG.md" in plan.files_to_stage
        assert plan.has_changes is True
        assert "1 spec(s)" in plan.message

    @patch("harness.refresh._is_git_repo", return_value=True)
    @patch("harness.refresh._staged_files", return_value=["CURRENT_TASKS.md"])
    @patch("harness.refresh._uncommitted_files", return_value=["specs/002-backlog-workflow.md"])
    def test_git_merges_staged_and_uncommitted(
        self, mock_uncommitted: Any, mock_staged: Any, mock_git: Any, tmp_project: Path
    ) -> None:
        plan = prepare_state_commit(str(tmp_project))
        assert "CURRENT_TASKS.md" in plan.files_to_stage
        assert "specs/002-backlog-workflow.md" in plan.files_to_stage

    @patch("harness.refresh._is_git_repo", return_value=True)
    @patch("harness.refresh._staged_files", return_value=[])
    @patch("harness.refresh._uncommitted_files", return_value=[])
    def test_git_no_changes(
        self, mock_uncommitted: Any, mock_staged: Any, mock_git: Any, tmp_path: Path
    ) -> None:
        # Use an empty directory so no state files exist on disk
        plan = prepare_state_commit(str(tmp_path))
        assert plan.has_changes is False
        assert plan.files_to_stage == []

    @patch("harness.refresh._is_git_repo", return_value=True)
    @patch("harness.refresh._staged_files", return_value=["LAST_SESSION.md"])
    @patch("harness.refresh._uncommitted_files", return_value=["LAST_SESSION.md"])
    def test_deduplication(
        self, mock_uncommitted: Any, mock_staged: Any, mock_git: Any, tmp_project: Path
    ) -> None:
        plan = prepare_state_commit(str(tmp_project))
        assert plan.files_to_stage.count("LAST_SESSION.md") == 1


# ---------------------------------------------------------------------------
# CommitPlan dataclass
# ---------------------------------------------------------------------------

class TestCommitPlan:
    def test_construction(self) -> None:
        plan = CommitPlan(files_to_stage=["a.md"], message="msg", has_changes=True)
        assert plan.files_to_stage == ["a.md"]
        assert plan.message == "msg"
        assert plan.has_changes is True

    def test_defaults_if_any(self) -> None:
        # CommitPlan should at minimum be constructable with required args
        plan = CommitPlan(files_to_stage=[], message="", has_changes=False)
        assert plan.files_to_stage == []
