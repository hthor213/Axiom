import os
import subprocess
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from lib.python.harness.git_ops import (
    GitStatus,
    BranchInfo,
    _run_git,
    _is_git_repo,
    _current_branch,
    _detect_base_branch,
    _has_remote,
    _uncommitted_files,
    _staged_files,
    _recent_commits,
    _tracking_info,
    gather_status,
    detect_branches,
    stage_files,
    create_commit,
)


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestDataclassDefaults:
    def test_git_status_defaults(self) -> None:
        s = GitStatus()
        assert s.branch == ""
        assert s.base_branch == ""
        assert s.has_remote is False
        assert s.uncommitted == []
        assert s.staged == []
        assert s.recent_commits == []
        assert s.is_clean is True

    def test_branch_info_defaults(self) -> None:
        b = BranchInfo()
        assert b.current == ""
        assert b.base == ""
        assert b.tracks_remote is False
        assert b.remote_name == ""

    def test_git_status_mutable_defaults_independent(self) -> None:
        """Each instance should get its own list."""
        a = GitStatus()
        b = GitStatus()
        a.uncommitted.append("foo.py")
        assert b.uncommitted == []


# ---------------------------------------------------------------------------
# Helper to make a real git repo in tmp_path
# ---------------------------------------------------------------------------

def _init_repo(path: Path, *, with_commit: bool = True) -> None:
    """Initialise a git repo, optionally with an initial commit on 'main'."""
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path),
                    capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                    cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                    cwd=str(path), capture_output=True, check=True)
    if with_commit:
        (path / "README.md").write_text("# hi\n")
        subprocess.run(["git", "add", "."], cwd=str(path),
                        capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init", "--no-verify"],
                        cwd=str(path), capture_output=True, check=True)


# ---------------------------------------------------------------------------
# _run_git
# ---------------------------------------------------------------------------

class TestRunGit:
    def test_success(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        result = _run_git(str(tmp_path), ["status"])
        assert result.returncode == 0

    def test_returns_synthetic_on_missing_git(self, tmp_path: Path) -> None:
        with patch("lib.python.harness.git_ops.subprocess.run",
                    side_effect=FileNotFoundError):
            result = _run_git(str(tmp_path), ["status"])
        assert result.returncode == -1
        assert result.stdout == ""

    def test_returns_synthetic_on_timeout(self, tmp_path: Path) -> None:
        with patch("lib.python.harness.git_ops.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1)):
            result = _run_git(str(tmp_path), ["status"])
        assert result.returncode == -1

    def test_returns_synthetic_on_oserror(self, tmp_path: Path) -> None:
        with patch("lib.python.harness.git_ops.subprocess.run",
                    side_effect=OSError("boom")):
            result = _run_git(str(tmp_path), ["log"])
        assert result.returncode == -1


# ---------------------------------------------------------------------------
# _is_git_repo
# ---------------------------------------------------------------------------

class TestIsGitRepo:
    def test_true_for_real_repo(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _is_git_repo(str(tmp_path)) is True

    def test_false_for_plain_dir(self, tmp_path: Path) -> None:
        assert _is_git_repo(str(tmp_path)) is False

    def test_false_when_git_missing(self, tmp_path: Path) -> None:
        with patch("lib.python.harness.git_ops._run_git",
                    return_value=subprocess.CompletedProcess(
                        args=[], returncode=-1, stdout="", stderr="")):
            assert _is_git_repo(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _current_branch / _detect_base_branch
# ---------------------------------------------------------------------------

class TestBranchHelpers:
    def test_current_branch_main(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _current_branch(str(tmp_path)) == "main"

    def test_current_branch_empty_for_non_repo(self, tmp_path: Path) -> None:
        assert _current_branch(str(tmp_path)) == ""

    def test_current_branch_returns_empty_for_detached_head(self, tmp_path: Path) -> None:
        """When rev-parse returns 'HEAD' we should get empty string."""
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="HEAD\n", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _current_branch(str(tmp_path)) == ""

    def test_detect_base_branch_main(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _detect_base_branch(str(tmp_path)) == "main"

    def test_detect_base_branch_master(self, tmp_path: Path) -> None:
        """When 'main' doesn't verify but 'master' does, returns 'master'."""
        calls: list[list[str]] = []

        def fake_run(root: str, args: list[str], timeout: int = 10):
            calls.append(args)
            if args == ["rev-parse", "--verify", "main"]:
                return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            if args == ["rev-parse", "--verify", "master"]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="abc\n", stderr="")
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with patch("lib.python.harness.git_ops._run_git", side_effect=fake_run):
            assert _detect_base_branch(str(tmp_path)) == "master"

    def test_detect_base_branch_none(self, tmp_path: Path) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _detect_base_branch(str(tmp_path)) == ""


# ---------------------------------------------------------------------------
# _has_remote
# ---------------------------------------------------------------------------

class TestHasRemote:
    def test_no_remote(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _has_remote(str(tmp_path)) is False

    def test_with_remote(self, tmp_path: Path) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="origin\n", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _has_remote(str(tmp_path)) is True

    def test_empty_stdout(self, tmp_path: Path) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _has_remote(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _uncommitted_files / _staged_files / _recent_commits
# ---------------------------------------------------------------------------

class TestFileListHelpers:
    def test_uncommitted_files_empty_on_clean(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _uncommitted_files(str(tmp_path)) == []

    def test_uncommitted_files_detects_modification(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("changed\n")
        result = _uncommitted_files(str(tmp_path))
        assert "README.md" in result

    def test_uncommitted_files_detects_untracked(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "new.txt").write_text("new\n")
        result = _uncommitted_files(str(tmp_path))
        assert "new.txt" in result

    def test_uncommitted_files_no_duplicates(self, tmp_path: Path) -> None:
        """Porcelain output: a file should appear at most once."""
        _init_repo(tmp_path)
        (tmp_path / "a.txt").write_text("a\n")
        result = _uncommitted_files(str(tmp_path))
        assert len(result) == len(set(result))

    def test_uncommitted_files_handles_quoted_paths(self) -> None:
        porcelain = '?? "path with spaces.txt"\n'
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=porcelain, stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            result = _uncommitted_files("/fake")
        assert "path with spaces.txt" in result

    def test_uncommitted_files_skips_short_lines(self) -> None:
        porcelain = "ab\n"  # len < 4
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=porcelain, stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _uncommitted_files("/fake") == []

    def test_uncommitted_files_error_returns_empty(self) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _uncommitted_files("/fake") == []

    def test_staged_files(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "staged.txt").write_text("content\n")
        subprocess.run(["git", "add", "staged.txt"], cwd=str(tmp_path),
                        capture_output=True, check=True)
        result = _staged_files(str(tmp_path))
        assert "staged.txt" in result

    def test_staged_files_empty(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert _staged_files(str(tmp_path)) == []

    def test_staged_files_error(self) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            assert _staged_files("/fake") == []

    def test_recent_commits(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        commits = _recent_commits(str(tmp_path))
        assert len(commits) == 1
        assert "init" in commits[0]

    def test_recent_commits_empty_no_repo(self, tmp_path: Path) -> None:
        assert _recent_commits(str(tmp_path)) == []

    def test_recent_commits_respects_count(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        for i in range(3):
            (tmp_path / f"f{i}.txt").write_text(f"{i}\n")
            subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}", "--no-verify"],
                            cwd=str(tmp_path), capture_output=True)
        assert len(_recent_commits(str(tmp_path), count=2)) == 2


# ---------------------------------------------------------------------------
# _tracking_info
# ---------------------------------------------------------------------------

class TestTrackingInfo:
    def test_empty_branch(self) -> None:
        assert _tracking_info("/fake", "") == (False, "")

    def test_no_tracking(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        tracks, remote = _tracking_info(str(tmp_path), "main")
        assert tracks is False
        assert remote == ""

    def test_with_tracking(self) -> None:
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="origin\n", stderr="")
        with patch("lib.python.harness.git_ops._run_git", return_value=cp):
            tracks, remote = _tracking_info("/fake", "main")
        assert tracks is True
        assert remote == "origin"


# ---------------------------------------------------------------------------
# gather_status
# ---------------------------------------------------------------------------

class TestGatherStatus:
    def test_non_dir_returns_default(self) -> None:
        status = gather_status("/nonexistent/path/xyz")
        assert status == GitStatus()

    def test_non_repo_returns_default(self, tmp_path: Path) -> None:
        status = gather_status(str(tmp_path))
        assert status == GitStatus()

    def test_clean_repo(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        status = gather_status(str(tmp_path))
        assert status.branch == "main"
        assert status.base_branch == "main"
        assert status.is_clean is True
        assert status.uncommitted == []
        assert status.staged == []
        assert len(status.recent_commits) >= 1

    def test_dirty_repo(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("x\n")
        status = gather_status(str(tmp_path))
        assert status.is_clean is False
        assert "dirty.txt" in status.uncommitted

    def test_staged_changes_not_clean(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "s.txt").write_text("staged\n")
        subprocess.run(["git", "add", "s.txt"], cwd=str(tmp_path), capture_output=True)
        status = gather_status(str(tmp_path))
        assert status.is_clean is False
        assert "s.txt" in status.staged


# ---------------------------------------------------------------------------
# detect_branches
# ---------------------------------------------------------------------------

class TestDetectBranches:
    def test_non_dir(self) -> None:
        assert detect_branches("/no/such/dir") == BranchInfo()

    def test_non_repo(self, tmp_path: Path) -> None:
        assert detect_branches(str(tmp_path)) == BranchInfo()

    def test_real_repo(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        info = detect_branches(str(tmp_path))
        assert info.current == "main"
        assert info.base == "main"
        assert info.tracks_remote is False
        assert info.remote_name == ""


# ---------------------------------------------------------------------------
# stage_files / create_commit
# ---------------------------------------------------------------------------

class TestStageFiles:
    def test_empty_list(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert stage_files(str(tmp_path), []) is False

    def test_non_dir(self) -> None:
        assert stage_files("/no/dir", ["a.txt"]) is False

    def test_non_repo(self, tmp_path: Path) -> None:
        assert stage_files(str(tmp_path), ["a.txt"]) is False

    def test_success(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "new.py").write_text("print(1)\n")
        assert stage_files(str(tmp_path), ["new.py"]) is True
        assert "new.py" in _staged_files(str(tmp_path))


class TestCreateCommit:
    def test_empty_message(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert create_commit(str(tmp_path), "") is False

    def test_non_dir(self) -> None:
        assert create_commit("/no/dir", "msg") is False

    def test_non_repo(self, tmp_path: Path) -> None:
        assert create_commit(str(tmp_path), "msg") is False

    def test_no_staged(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        assert create_commit(str(tmp_path), "nothing staged") is False

    def test_success(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "c.txt").write_text("commit me\n")
        stage_files(str(tmp_path), ["c.txt"])
        assert create_commit(str(tmp_path), "add c.txt") is True
        commits = _recent_commits(str(tmp_path))
        assert any("add c.txt" in c for c in commits)
