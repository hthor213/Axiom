from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import List

import pytest

from harness.checkpoint import (
    BacklogDiff,
    CommitPlan,
    InvariantResult,
    _is_artifact,
    _rmtree_simple,
    check_automatable_invariants,
    cleanup_artifacts,
    generate_session_summary,
    prepare_commit,
    update_backlog,
)
from harness.session import SessionContext


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_invariant_result_fields(self) -> None:
        r = InvariantResult(invariant="x exists", status="pass", check_type="file_exists", evidence="found")
        assert r.invariant == "x exists"
        assert r.status == "pass"
        assert r.check_type == "file_exists"
        assert r.evidence == "found"

    def test_backlog_diff_defaults(self) -> None:
        d = BacklogDiff()
        assert d.moved_to_done == []
        assert d.new_items == []
        assert d.reprioritized == []

    def test_commit_plan_defaults(self) -> None:
        p = CommitPlan()
        assert p.files_to_stage == []
        assert p.message == ""
        assert p.has_changes is False


# ---------------------------------------------------------------------------
# _is_artifact
# ---------------------------------------------------------------------------

class TestIsArtifact:
    @pytest.mark.parametrize("name", [
        "screenshot-001.png", "file.tmp", "file.bak", "file.swp",
        "module.pyc", ".DS_Store", "Thumbs.db", "~$document.docx",
        "patch.orig", "__pycache__",
    ])
    def test_recognized_artifacts(self, name: str) -> None:
        assert _is_artifact(name) is True

    @pytest.mark.parametrize("name", [
        "README.md", "main.py", "data.json", "Makefile",
    ])
    def test_non_artifacts(self, name: str) -> None:
        assert _is_artifact(name) is False


# ---------------------------------------------------------------------------
# cleanup_artifacts
# ---------------------------------------------------------------------------

class TestCleanupArtifacts:
    def test_removes_artifacts(self, tmp_path: Path) -> None:
        (tmp_path / "screenshot-1.png").write_text("img")
        (tmp_path / ".DS_Store").write_text("x")
        (tmp_path / "keep.md").write_text("keep")
        removed = cleanup_artifacts(str(tmp_path))
        assert "screenshot-1.png" in removed
        assert ".DS_Store" in removed
        assert "keep.md" not in removed
        assert (tmp_path / "keep.md").exists()

    def test_removes_pycache_dir(self, tmp_path: Path) -> None:
        pc = tmp_path / "__pycache__"
        pc.mkdir()
        (pc / "mod.cpython-312.pyc").write_text("bytecode")
        removed = cleanup_artifacts(str(tmp_path))
        assert "__pycache__" in removed
        assert not pc.exists()

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        assert cleanup_artifacts(str(tmp_path / "nope")) == []

    def test_empty_dir(self, tmp_project_empty: Path) -> None:
        removed = cleanup_artifacts(str(tmp_project_empty))
        assert removed == []


# ---------------------------------------------------------------------------
# _rmtree_simple
# ---------------------------------------------------------------------------

class TestRmtreeSimple:
    def test_removes_nested(self, tmp_path: Path) -> None:
        d = tmp_path / "a" / "b"
        d.mkdir(parents=True)
        (d / "f.txt").write_text("x")
        _rmtree_simple(tmp_path / "a")
        assert not (tmp_path / "a").exists()

    def test_noop_on_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hi")
        _rmtree_simple(f)  # should do nothing
        assert f.exists()


# ---------------------------------------------------------------------------
# update_backlog
# ---------------------------------------------------------------------------

class TestUpdateBacklog:
    def test_removes_completed_and_adds_new(self, tmp_project: Path) -> None:
        diff = update_backlog(
            str(tmp_project),
            completed=["Implement checkpoint automation"],
            new_items=["Add telemetry hooks"],
        )
        assert "Implement checkpoint automation" in diff.moved_to_done
        assert "Add telemetry hooks" in diff.new_items
        content = (tmp_project / "BACKLOG.md").read_text()
        assert "Implement checkpoint automation" not in content
        assert "Add telemetry hooks" in content

    def test_no_backlog_creates_one(self, tmp_path: Path) -> None:
        diff = update_backlog(str(tmp_path), completed=[], new_items=["New task"])
        assert diff.new_items == ["New task"]
        assert (tmp_path / "BACKLOG.md").exists()
        assert "New task" in (tmp_path / "BACKLOG.md").read_text()

    def test_no_changes(self, tmp_project: Path) -> None:
        diff = update_backlog(str(tmp_project), completed=[], new_items=[])
        assert diff.moved_to_done == []
        assert diff.new_items == []

    def test_completed_not_present_is_harmless(self, tmp_project: Path) -> None:
        diff = update_backlog(str(tmp_project), completed=["Nonexistent item"], new_items=[])
        assert diff.moved_to_done == []


# ---------------------------------------------------------------------------
# check_automatable_invariants
# ---------------------------------------------------------------------------

class TestCheckAutomatableInvariants:
    def test_file_exists_pass(self, tmp_project: Path) -> None:
        results = check_automatable_invariants(
            str(tmp_project),
            ["`README.md` file exists"],
        )
        assert len(results) == 1
        assert results[0].status == "pass"
        assert results[0].check_type == "file_exists"

    def test_file_exists_fail(self, tmp_project: Path) -> None:
        results = check_automatable_invariants(
            str(tmp_project),
            ["`nonexistent.txt` file exists"],
        )
        assert len(results) == 1
        assert results[0].status == "fail"

    def test_judgment_skipped(self, tmp_project: Path) -> None:
        results = check_automatable_invariants(
            str(tmp_project),
            ["All stakeholders agree on direction"],
        )
        assert len(results) == 1
        assert results[0].status == "skip"
        assert results[0].check_type == "judgment"

    def test_multiple_invariants(self, tmp_project: Path) -> None:
        results = check_automatable_invariants(
            str(tmp_project),
            ["`README.md` file exists", "Team is happy"],
        )
        assert len(results) == 2
        assert results[0].status == "pass"
        assert results[1].status == "skip"

    def test_empty_list(self, tmp_project: Path) -> None:
        assert check_automatable_invariants(str(tmp_project), []) == []


# ---------------------------------------------------------------------------
# generate_session_summary
# ---------------------------------------------------------------------------

class TestGenerateSessionSummary:
    def test_basic_summary(self, tmp_project: Path) -> None:
        ctx = SessionContext(
            last_session={"focus": "Build parser"},
            current_tasks={"active": ["Task A"], "completed": []},
            backlog_items=[],
        )
        md = generate_session_summary(ctx, accomplishments=["Did X", "Did Y"])
        assert date.today().isoformat() in md
        assert "Build parser" in md
        assert "- Did X" in md
        assert "- Did Y" in md

    def test_no_accomplishments(self, tmp_project: Path) -> None:
        ctx = SessionContext(
            last_session={},
            current_tasks={"active": []},
            backlog_items=[],
        )
        md = generate_session_summary(ctx, accomplishments=[])
        assert "No accomplishments recorded" in md

    def test_focus_falls_back_to_active_task(self, tmp_project: Path) -> None:
        ctx = SessionContext(
            last_session={"focus": ""},
            current_tasks={"active": ["Fallback task"]},
            backlog_items=[],
        )
        md = generate_session_summary(ctx, accomplishments=["a"])
        assert "Fallback task" in md

    def test_focus_falls_back_to_default(self, tmp_project: Path) -> None:
        ctx = SessionContext(
            last_session={},
            current_tasks={"active": []},
            backlog_items=[],
        )
        md = generate_session_summary(ctx, accomplishments=[])
        assert "Session work" in md


# ---------------------------------------------------------------------------
# prepare_commit (non-git)
# ---------------------------------------------------------------------------

class TestPrepareCommit:
    def test_non_git_project(self, tmp_project: Path) -> None:
        plan = prepare_commit(str(tmp_project), message_prefix="end")
        assert plan.has_changes is True
        assert "BACKLOG.md" in plan.files_to_stage
        assert plan.message.startswith("end:")
        assert date.today().isoformat() in plan.message

    def test_nonexistent_root(self, tmp_path: Path) -> None:
        plan = prepare_commit(str(tmp_path / "missing"))
        assert plan.has_changes is False
        assert plan.files_to_stage == []

    def test_default_prefix(self, tmp_project: Path) -> None:
        plan = prepare_commit(str(tmp_project))
        assert plan.message.startswith("checkpoint:")

    def test_includes_spec_files(self, tmp_project: Path) -> None:
        plan = prepare_commit(str(tmp_project))
        spec_files = [f for f in plan.files_to_stage if f.startswith("specs/")]
        assert len(spec_files) > 0
