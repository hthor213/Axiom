"""Tests for harness/project.py — structure detection, scaffolding, migration."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from harness.project import (
    ProjectStructure,
    detect_structure,
    ensure_workflow_files,
    migrate_legacy,
    scaffold,
    _slugify,
    _split_legacy_sections,
    _safe_listdir,
)


# ---------------------------------------------------------------------------
# ProjectStructure dataclass defaults
# ---------------------------------------------------------------------------

class TestProjectStructureDefaults:
    """Verify dataclass field defaults."""

    def test_all_false_by_default(self) -> None:
        """All boolean fields should default to False."""
        ps = ProjectStructure()
        assert ps.has_specs_dir is False
        assert ps.has_legacy_spec is False
        assert ps.has_backlog is False
        assert ps.has_current_tasks is False
        assert ps.has_last_session is False
        assert ps.has_done is False
        assert ps.has_claude_md is False

    def test_project_type_defaults_to_unknown(self) -> None:
        ps = ProjectStructure()
        assert ps.project_type == "unknown"


# ---------------------------------------------------------------------------
# detect_structure
# ---------------------------------------------------------------------------

class TestDetectStructure:
    """Tests for detect_structure()."""

    def test_full_harness_project(self, tmp_project: Path) -> None:
        """A fully-scaffolded project is detected as 'harness'."""
        result = detect_structure(str(tmp_project))
        assert result.has_specs_dir is True
        assert result.has_backlog is True
        assert result.has_current_tasks is True
        assert result.has_last_session is True
        assert result.project_type == "harness"

    def test_legacy_project(self, tmp_path: Path) -> None:
        """A project with SPEC.md but no specs/ is 'legacy'."""
        (tmp_path / "SPEC.md").write_text("# Legacy Spec\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Hi\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        result = detect_structure(str(tmp_path))
        assert result.has_legacy_spec is True
        assert result.has_specs_dir is False
        assert result.project_type == "legacy"

    def test_fresh_project_empty(self, tmp_path: Path) -> None:
        """An empty directory is detected as 'fresh'."""
        result = detect_structure(str(tmp_path))
        assert result.project_type == "fresh"

    def test_fresh_project_one_file(self, tmp_path: Path) -> None:
        """A directory with <=2 files and no specs/ is 'fresh'."""
        (tmp_path / "README.md").write_text("# New\n", encoding="utf-8")
        result = detect_structure(str(tmp_path))
        assert result.project_type == "fresh"

    def test_unknown_project(self, tmp_path: Path) -> None:
        """A directory with many files but no recognizable structure."""
        for i in range(5):
            (tmp_path / f"file{i}.txt").write_text("data\n", encoding="utf-8")
        result = detect_structure(str(tmp_path))
        assert result.project_type == "unknown"

    def test_specs_dir_without_numbered_files(self, tmp_project_empty: Path) -> None:
        """specs/ exists but has no NNN-*.md files — still 'harness' (has specs dir)."""
        result = detect_structure(str(tmp_project_empty))
        assert result.has_specs_dir is True
        # specs dir exists but empty — _infer_project_type falls through to harness
        assert result.project_type == "harness"

    def test_detects_claude_md(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
        result = detect_structure(str(tmp_path))
        assert result.has_claude_md is True

    def test_detects_done(self, tmp_path: Path) -> None:
        (tmp_path / "DONE.md").write_text("# Done\n", encoding="utf-8")
        result = detect_structure(str(tmp_path))
        assert result.has_done is True


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------

class TestScaffold:
    """Tests for scaffold()."""

    def test_creates_all_files_in_empty_dir(self, tmp_path: Path) -> None:
        """Scaffolding an empty directory creates all expected files."""
        created = scaffold(str(tmp_path), "TestProject")
        assert "BACKLOG.md" in created
        assert "CURRENT_TASKS.md" in created
        assert "LAST_SESSION.md" in created
        assert "DONE.md" in created
        assert "CLAUDE.md" in created
        assert os.path.join("specs", "000-vision.md") in created
        assert os.path.join("specs", "README.md") in created
        # Verify files actually exist
        assert (tmp_path / "specs" / "000-vision.md").is_file()
        assert (tmp_path / "CLAUDE.md").is_file()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Existing files are preserved during scaffolding."""
        (tmp_path / "BACKLOG.md").write_text("# My Backlog\n", encoding="utf-8")
        created = scaffold(str(tmp_path), "TestProject")
        assert "BACKLOG.md" not in created
        assert (tmp_path / "BACKLOG.md").read_text(encoding="utf-8") == "# My Backlog\n"

    def test_project_name_in_templates(self, tmp_path: Path) -> None:
        """Project name appears in generated content."""
        scaffold(str(tmp_path), "AwesomeApp")
        vision = (tmp_path / "specs" / "000-vision.md").read_text(encoding="utf-8")
        assert "AwesomeApp" in vision
        claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "AwesomeApp" in claude

    def test_last_session_has_today_date(self, tmp_path: Path) -> None:
        scaffold(str(tmp_path), "P")
        content = (tmp_path / "LAST_SESSION.md").read_text(encoding="utf-8")
        assert date.today().isoformat() in content


# ---------------------------------------------------------------------------
# migrate_legacy
# ---------------------------------------------------------------------------

class TestMigrateLegacy:
    """Tests for migrate_legacy()."""

    def test_no_spec_md_returns_empty(self, tmp_path: Path) -> None:
        """No SPEC.md means nothing to migrate."""
        assert migrate_legacy(str(tmp_path)) == []

    def test_simple_migration(self, tmp_path: Path) -> None:
        """SPEC.md without numbered sections becomes 000-vision.md."""
        (tmp_path / "SPEC.md").write_text("# My Project\nSome content.\n", encoding="utf-8")
        changes = migrate_legacy(str(tmp_path))
        assert os.path.join("specs", "000-vision.md") in changes
        assert os.path.join("specs", "README.md") in changes
        assert "SPEC.md.bak" in changes
        assert (tmp_path / "specs" / "000-vision.md").is_file()
        assert (tmp_path / "SPEC.md.bak").is_file()
        assert not (tmp_path / "SPEC.md").exists()

    def test_numbered_sections_split(self, tmp_path: Path) -> None:
        """SPEC.md with numbered H2 sections is split into separate files."""
        content = (
            "# Project\n\n"
            "## 001 - Session Harness\nHarness details.\n\n"
            "## 002 - Backlog Workflow\nBacklog details.\n"
        )
        (tmp_path / "SPEC.md").write_text(content, encoding="utf-8")
        changes = migrate_legacy(str(tmp_path))
        assert os.path.join("specs", "001-session-harness.md") in changes
        assert os.path.join("specs", "002-backlog-workflow.md") in changes
        # Preamble content ("# Project") is captured as 000-vision.md
        assert os.path.join("specs", "000-vision.md") in changes

    def test_does_not_overwrite_existing_spec(self, tmp_path: Path) -> None:
        """Existing spec files in specs/ are not overwritten."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "000-vision.md").write_text("# Existing\n", encoding="utf-8")
        (tmp_path / "SPEC.md").write_text("# Incoming\n", encoding="utf-8")
        changes = migrate_legacy(str(tmp_path))
        assert os.path.join("specs", "000-vision.md") not in changes
        assert (specs_dir / "000-vision.md").read_text(encoding="utf-8") == "# Existing\n"

    def test_backup_already_exists(self, tmp_path: Path) -> None:
        """If SPEC.md.bak already exists, SPEC.md is deleted instead."""
        (tmp_path / "SPEC.md").write_text("# Dup\n", encoding="utf-8")
        (tmp_path / "SPEC.md.bak").write_text("# Old Backup\n", encoding="utf-8")
        changes = migrate_legacy(str(tmp_path))
        assert "SPEC.md.bak" not in changes
        assert not (tmp_path / "SPEC.md").exists()
        assert (tmp_path / "SPEC.md.bak").read_text(encoding="utf-8") == "# Old Backup\n"


# ---------------------------------------------------------------------------
# ensure_workflow_files
# ---------------------------------------------------------------------------

class TestEnsureWorkflowFiles:
    """Tests for ensure_workflow_files()."""

    def test_creates_missing_workflow_files(self, tmp_path: Path) -> None:
        created = ensure_workflow_files(str(tmp_path))
        assert set(created) == {"BACKLOG.md", "CURRENT_TASKS.md", "LAST_SESSION.md", "DONE.md"}
        for f in created:
            assert (tmp_path / f).is_file()

    def test_skips_existing_files(self, tmp_project: Path) -> None:
        """A fully-populated project needs no new workflow files."""
        # tmp_project already has BACKLOG.md, CURRENT_TASKS.md, LAST_SESSION.md
        # but may not have DONE.md — create it to ensure all present
        (tmp_project / "DONE.md").write_text("# Done\n", encoding="utf-8")
        created = ensure_workflow_files(str(tmp_project))
        assert created == []

    def test_does_not_create_specs_or_claude(self, tmp_path: Path) -> None:
        """ensure_workflow_files should NOT create specs/ or CLAUDE.md."""
        ensure_workflow_files(str(tmp_path))
        assert not (tmp_path / "specs").exists()
        assert not (tmp_path / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestSlugify:
    """Tests for _slugify()."""

    def test_basic_title(self) -> None:
        assert _slugify("Session Harness") == "session-harness"

    def test_special_characters(self) -> None:
        assert _slugify("What's Next? (v2)") == "whats-next-v2"

    def test_multiple_spaces_and_dashes(self) -> None:
        assert _slugify("  too   many---dashes  ") == "too-many-dashes"

    def test_empty_string(self) -> None:
        assert _slugify("") == "untitled"

    def test_only_punctuation(self) -> None:
        assert _slugify("!!!") == "untitled"


class TestSafeListdir:
    """Tests for _safe_listdir()."""

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        result = _safe_listdir(tmp_path / "does_not_exist")
        assert result == []

    def test_returns_sorted_listing(self, tmp_path: Path) -> None:
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        result = _safe_listdir(tmp_path)
        assert result == ["a.txt", "b.txt"]


class TestSplitLegacySections:
    """Tests for _split_legacy_sections()."""

    def test_no_sections_returns_empty(self) -> None:
        assert _split_legacy_sections("# Just a title\nNo sections.\n") == []

    def test_single_section_returns_empty(self) -> None:
        """A single numbered H2 is not enough to split."""
        assert _split_legacy_sections("## 001 - Only One\nContent.\n") == []

    def test_two_sections_splits(self) -> None:
        content = "## 001 - First\nA.\n\n## 002 - Second\nB.\n"
        sections = _split_legacy_sections(content)
        assert len(sections) == 2
        assert sections[0][0] == "001"
        assert sections[0][1] == "first"
        assert sections[1][0] == "002"
        assert sections[1][1] == "second"
