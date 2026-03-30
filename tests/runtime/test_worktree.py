"""Tests for git worktree management."""

from __future__ import annotations

import os
import subprocess
import pytest

from lib.python.runtime.worktree import (
    create_worktree,
    cleanup_worktree,
    list_worktrees,
    get_worktree_diff,
    commit_in_worktree,
    Worktree,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, capture_output=True)

    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--no-verify"],
        cwd=repo, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    return repo


@pytest.fixture
def worktree_dir(tmp_path):
    """Temporary directory for worktrees."""
    d = tmp_path / "worktrees"
    d.mkdir()
    return d


class TestCreateWorktree:

    def test_creates_worktree(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        assert os.path.isdir(wt.path)
        assert wt.branch == "auto/spec-014-task-1"
        assert wt.task_id == 1
        assert wt.spec_number == "014"

    def test_worktree_has_files(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        assert os.path.isfile(os.path.join(wt.path, "README.md"))

    def test_worktree_is_on_branch(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path, capture_output=True, text=True,
        )
        assert result.stdout.strip() == "auto/spec-014-task-1"

    def test_recreates_if_exists(self, git_repo, worktree_dir):
        """If the worktree path already exists, cleanup and recreate."""
        wt1 = create_worktree(str(git_repo), task_id=1, spec_number="014",
                               worktree_dir=str(worktree_dir))
        # Clean up the worktree but leave the branch
        cleanup_worktree(str(git_repo), wt1.path)
        # Recreate
        wt2 = create_worktree(str(git_repo), task_id=1, spec_number="014",
                               worktree_dir=str(worktree_dir))
        assert os.path.isdir(wt2.path)


class TestCleanupWorktree:

    def test_cleanup(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        assert os.path.isdir(wt.path)
        cleanup_worktree(str(git_repo), wt.path)
        assert not os.path.isdir(wt.path)


class TestListWorktrees:

    def test_list_includes_main_and_created(self, git_repo, worktree_dir):
        create_worktree(str(git_repo), task_id=1, spec_number="014",
                         worktree_dir=str(worktree_dir))
        wts = list_worktrees(str(git_repo))
        assert len(wts) >= 2  # main + created


class TestCommitInWorktree:

    def test_commit(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))

        # Create a file
        new_file = os.path.join(wt.path, "test.py")
        with open(new_file, "w") as f:
            f.write("# test\n")

        sha = commit_in_worktree(wt.path, "test commit")
        assert sha is not None
        assert len(sha) == 40  # full SHA

    def test_commit_no_changes(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        # No changes to commit
        sha = commit_in_worktree(wt.path, "empty commit")
        # Should return None since there's nothing to commit
        assert sha is None


class TestGetWorktreeDiff:

    def test_diff_with_changes(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        new_file = os.path.join(wt.path, "new.py")
        with open(new_file, "w") as f:
            f.write("print('hello')\n")
        commit_in_worktree(wt.path, "add new file")

        diff = get_worktree_diff(wt.path, "main")
        assert "new.py" in diff

    def test_diff_no_changes(self, git_repo, worktree_dir):
        wt = create_worktree(str(git_repo), task_id=1, spec_number="014",
                              worktree_dir=str(worktree_dir))
        diff = get_worktree_diff(wt.path, "main")
        assert diff == ""
