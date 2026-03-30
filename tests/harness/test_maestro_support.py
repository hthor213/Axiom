"""Tests for lib/python/harness/maestro_support.py"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

from lib.python.harness.maestro_support import (
    FIVE_FILES,
    FiveFileStatus,
    MilestoneValidation,
    TasksValidation,
    WorkTransition,
    _count_milestones_in_text,
    _find_matching_spec,
    _has_heading,
    _next_spec_number,
    _read_text,
    count_active_milestones,
    diagnose_failure_type,
    transition_work_item,
    validate_current_tasks,
    validate_five_files,
    validate_milestone,
)


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclassDefaults:
    def test_five_file_status_defaults(self) -> None:
        s = FiveFileStatus()
        assert s.files == {}
        assert s.all_present is False
        assert s.format_issues == []

    def test_work_transition_defaults(self) -> None:
        t = WorkTransition()
        assert t.item == ""
        assert t.spec_created is False
        assert t.spec_ref is None

    def test_tasks_validation_defaults(self) -> None:
        v = TasksValidation()
        assert v.milestone_count == 0
        assert v.exceeds_limit is False
        assert v.valid is True

    def test_milestone_validation_defaults(self) -> None:
        m = MilestoneValidation()
        assert m.has_clear_scope is False
        assert m.is_independent is True
        assert m.issues == []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestReadText:
    def test_reads_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("world", encoding="utf-8")
        assert _read_text(str(f)) == "world"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        assert _read_text(str(tmp_path / "nope.txt")) is None


class TestHasHeading:
    def test_matches_h1(self) -> None:
        assert _has_heading("# My Title", 1, "My Title") is True

    def test_no_match_wrong_level(self) -> None:
        assert _has_heading("## Sub", 1, "Sub") is False

    def test_case_insensitive(self) -> None:
        assert _has_heading("## Active Tasks", 2, "active") is True


class TestCountMilestonesInText:
    def test_counts_bullets_under_milestone_heading(self) -> None:
        md = "## Active Milestones\n- Alpha\n- Beta\n- Gamma\n"
        assert _count_milestones_in_text(md) == 3

    def test_counts_headings_when_no_bullets(self) -> None:
        md = "## Milestone 1\nSome text\n## Milestone 2\nMore text\n"
        assert _count_milestones_in_text(md) == 2

    def test_zero_when_empty(self) -> None:
        assert _count_milestones_in_text("") == 0

    def test_ignores_non_milestone_headings(self) -> None:
        md = "## Active\n- task\n## Completed\n- done task\n"
        assert _count_milestones_in_text(md) == 0


# ---------------------------------------------------------------------------
# validate_five_files
# ---------------------------------------------------------------------------


class TestValidateFiveFiles:
    def test_all_present(self, tmp_project: Path) -> None:
        status = validate_five_files(str(tmp_project))
        assert status.all_present is True
        for name in FIVE_FILES:
            assert status.files[name] is True

    def test_missing_files(self, tmp_project_empty: Path) -> None:
        status = validate_five_files(str(tmp_project_empty))
        assert status.all_present is False
        assert status.files["README.md"] is False

    def test_empty_readme_flagged(self, tmp_project: Path) -> None:
        (tmp_project / "README.md").write_text("", encoding="utf-8")
        status = validate_five_files(str(tmp_project))
        assert any("README.md is empty" in i for i in status.format_issues)

    def test_backlog_missing_h2(self, tmp_project: Path) -> None:
        (tmp_project / "BACKLOG.md").write_text("# Backlog\nNo sections.\n", encoding="utf-8")
        status = validate_five_files(str(tmp_project))
        assert any("H2 section" in i for i in status.format_issues)

    def test_last_session_missing_date(self, tmp_project: Path) -> None:
        (tmp_project / "LAST_SESSION.md").write_text("# Session\n## Next\nDo stuff\n", encoding="utf-8")
        status = validate_five_files(str(tmp_project))
        assert any("Date" in i for i in status.format_issues)

    def test_specs_empty_dir(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        issues: List[str] = []
        from lib.python.harness.maestro_support import _validate_specs_dir
        issues = _validate_specs_dir(str(tmp_path))
        assert any("no .md files" in i for i in issues)


# ---------------------------------------------------------------------------
# validate_current_tasks
# ---------------------------------------------------------------------------


class TestValidateCurrentTasks:
    def test_valid_file(self, tmp_project: Path) -> None:
        result = validate_current_tasks(str(tmp_project))
        assert result.valid is True
        assert result.exceeds_limit is False

    def test_missing_file(self, tmp_path: Path) -> None:
        result = validate_current_tasks(str(tmp_path))
        assert result.valid is False
        assert any("not found" in i for i in result.format_issues)

    def test_empty_file(self, tmp_project: Path) -> None:
        (tmp_project / "CURRENT_TASKS.md").write_text("", encoding="utf-8")
        result = validate_current_tasks(str(tmp_project))
        assert result.valid is False

    def test_exceeds_milestone_limit(self, tmp_project: Path) -> None:
        md = "# Tasks\n## Active Milestones\n- M1\n- M2\n- M3\n- M4\n## Active\n- t\n## Completed\n- d\n"
        (tmp_project / "CURRENT_TASKS.md").write_text(md, encoding="utf-8")
        result = validate_current_tasks(str(tmp_project))
        assert result.milestone_count == 4
        assert result.exceeds_limit is True


# ---------------------------------------------------------------------------
# validate_milestone
# ---------------------------------------------------------------------------


class TestValidateMilestone:
    def test_good_milestone(self) -> None:
        text = (
            "Implement user authentication module.\n"
            "- [ ] `auth.py` exists and contains login handler\n"
            "- [ ] pytest tests pass with at least 90% coverage\n"
            "Verify by running `pytest tests/auth`."
        )
        result = validate_milestone(text)
        assert result.has_clear_scope is True
        assert result.has_testable_criteria is True
        assert result.has_verification_method is True
        assert result.is_independent is True
        assert result.issues == []

    def test_empty_milestone(self) -> None:
        result = validate_milestone("")
        assert "empty" in result.issues[0].lower()

    def test_detects_dependency(self) -> None:
        text = "Build API layer. Depends on database milestone. Must return 200. Run pytest to check."
        result = validate_milestone(text)
        assert result.is_independent is False

    def test_missing_verification(self) -> None:
        text = "Create the config file.\n- [ ] `config.yaml` exists"
        result = validate_milestone(text)
        assert result.has_verification_method is False

    def test_too_long_scope(self) -> None:
        text = "Implement " + "x" * 500 + ". Must return 200. Run test."
        result = validate_milestone(text)
        assert result.has_clear_scope is False


# ---------------------------------------------------------------------------
# transition_work_item
# ---------------------------------------------------------------------------


class TestTransitionWorkItem:
    def test_backlog_to_active(self, tmp_project: Path) -> None:
        t = transition_work_item(str(tmp_project), "Add login", "backlog", "active")
        assert t.from_file == "BACKLOG.md"
        assert t.to_file == "CURRENT_TASKS.md"
        assert t.spec_created is False

    def test_to_spec_creates_new(self, tmp_project: Path) -> None:
        t = transition_work_item(str(tmp_project), "Brand new feature", "backlog", "spec")
        assert t.to_file == "specs/"
        assert t.spec_created is True
        assert t.spec_ref is not None
        assert int(t.spec_ref) > 3  # 000-003 already exist

    def test_to_spec_finds_existing(self, tmp_project: Path) -> None:
        t = transition_work_item(str(tmp_project), "Session Harness module", "backlog", "spec")
        assert t.spec_ref == "001"
        assert t.spec_created is False

    def test_to_spec_no_specs_dir(self, tmp_path: Path) -> None:
        t = transition_work_item(str(tmp_path), "Something", "backlog", "spec")
        assert t.spec_ref == "001"
        assert t.spec_created is True


# ---------------------------------------------------------------------------
# count_active_milestones
# ---------------------------------------------------------------------------


class TestCountActiveMilestones:
    def test_returns_zero_no_file(self, tmp_path: Path) -> None:
        assert count_active_milestones(str(tmp_path)) == 0

    def test_returns_count(self, tmp_project: Path) -> None:
        md = "# Tasks\n## Milestones\n- M1\n- M2\n"
        (tmp_project / "CURRENT_TASKS.md").write_text(md, encoding="utf-8")
        assert count_active_milestones(str(tmp_project)) == 2


# ---------------------------------------------------------------------------
# diagnose_failure_type
# ---------------------------------------------------------------------------


class TestDiagnoseFailureType:
    @pytest.mark.parametrize("result_text,expected", [
        ("FileNotFoundError: No such file", "missing_file"),
        ("file not found: config.yaml", "missing_file"),
        ("3 failed, 1 passed in pytest run", "test_failure"),
        ("AssertionError in test_login", "test_failure"),
        ("Traceback (most recent call last)", "test_failure"),
        ("blocked by upstream service", "blocked"),
        ("permission denied accessing /root", "blocked"),
        ("connection refused on port 5432", "blocked"),
        ("output does not contain expected key", "wrong_content"),
        ("expected 'foo' but got 'bar'", "wrong_content"),
        ("wrong scope applied to task", "scope_mismatch"),
        ("out of scope changes detected", "scope_mismatch"),
        ("partial implementation done, still need tests", "incomplete"),
        ("work in progress, TODO remaining", "incomplete"),
        ("", "unknown"),
        ("everything looks fine actually", "unknown"),
    ])
    def test_classification(self, result_text: str, expected: str) -> None:
        assert diagnose_failure_type(result_text, "some criteria") == expected

    def test_criteria_hint_file_exists(self) -> None:
        assert diagnose_failure_type("no", "output file exists") == "missing_file"

    def test_criteria_hint_contains(self) -> None:
        assert diagnose_failure_type("fail", "file contains expected key") == "wrong_content"


# ---------------------------------------------------------------------------
# _next_spec_number / _find_matching_spec
# ---------------------------------------------------------------------------


class TestNextSpecNumber:
    def test_increments(self, tmp_project: Path) -> None:
        specs_dir = str(tmp_project / "specs")
        assert _next_spec_number(specs_dir) == "004"

    def test_returns_001_when_empty(self, tmp_path: Path) -> None:
        d = tmp_path / "specs"
        d.mkdir()
        assert _next_spec_number(str(d)) == "001"

    def test_returns_001_when_missing(self, tmp_path: Path) -> None:
        assert _next_spec_number(str(tmp_path / "nope")) == "001"


class TestFindMatchingSpec:
    def test_finds_match(self, tmp_project: Path) -> None:
        result = _find_matching_spec(str(tmp_project / "specs"), "Backlog Workflow system")
        assert result == "002"

    def test_no_match_for_unrelated(self, tmp_project: Path) -> None:
        result = _find_matching_spec(str(tmp_project / "specs"), "Quantum teleportation device")
        assert result is None

    def test_stopwords_only(self, tmp_project: Path) -> None:
        result = _find_matching_spec(str(tmp_project / "specs"), "the a an is")
        assert result is None
