"""Git worktree management for autonomous tasks.

Each task runs in its own worktree with an isolated branch.
This prevents agents from interfering with each other's work.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Worktree:
    """Represents a git worktree for a task."""
    path: str
    branch: str
    base_branch: str
    base_commit: str  # SHA of the commit the branch was created from
    task_id: int
    spec_number: str


WORKTREE_DIR = "/tmp/hth-worktrees"


def _run_git(cwd: str, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command. Returns CompletedProcess."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(
            args=["git"] + args,
            returncode=-1,
            stdout="",
            stderr=str(e),
        )


def create_worktree(
    repo_root: str,
    task_id: int,
    spec_number: str,
    base_branch: str = "main",
    worktree_dir: Optional[str] = None,
) -> Worktree:
    """Create a git worktree for a task.

    Args:
        repo_root: Path to the main repository.
        task_id: Database task ID.
        spec_number: Spec number (e.g., "014").
        base_branch: Branch to base the worktree on.
        worktree_dir: Directory to create worktrees in.

    Returns:
        Worktree dataclass with path and branch info.

    Raises:
        RuntimeError: If worktree creation fails.
    """
    wt_dir = worktree_dir or WORKTREE_DIR
    os.makedirs(wt_dir, exist_ok=True)

    branch_name = f"auto/spec-{spec_number}-task-{task_id}"
    worktree_path = os.path.join(wt_dir, f"spec-{spec_number}-task-{task_id}")

    # Clean up if the worktree path already exists
    if os.path.exists(worktree_path):
        cleanup_worktree(repo_root, worktree_path)

    # Resolve base branch — fall back to HEAD if the named branch doesn't exist locally
    resolved_base = base_branch
    check_base = _run_git(repo_root, ["rev-parse", "--verify", base_branch])
    if check_base.returncode != 0:
        # base_branch doesn't exist locally — use current HEAD
        head_result = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
        if head_result.returncode == 0 and head_result.stdout.strip():
            resolved_base = head_result.stdout.strip()
        else:
            resolved_base = "HEAD"

    # Create the branch from base
    result = _run_git(repo_root, ["branch", branch_name, resolved_base])
    if result.returncode != 0:
        # Branch might already exist — try to use it
        check = _run_git(repo_root, ["rev-parse", "--verify", branch_name])
        if check.returncode != 0:
            raise RuntimeError(
                f"Failed to create branch {branch_name}: {result.stderr}"
            )

    # Record the base commit SHA before creating the worktree
    base_sha_result = _run_git(repo_root, ["rev-parse", resolved_base])
    base_commit = base_sha_result.stdout.strip() if base_sha_result.returncode == 0 else ""

    # Create the worktree
    result = _run_git(repo_root, ["worktree", "add", worktree_path, branch_name])
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create worktree at {worktree_path}: {result.stderr}"
        )

    return Worktree(
        path=worktree_path,
        branch=branch_name,
        base_branch=base_branch,
        base_commit=base_commit,
        task_id=task_id,
        spec_number=spec_number,
    )


def cleanup_worktree(repo_root: str, worktree_path: str) -> bool:
    """Remove a git worktree.

    Args:
        repo_root: Path to the main repository.
        worktree_path: Path to the worktree to remove.

    Returns:
        True if cleanup succeeded.
    """
    result = _run_git(repo_root, ["worktree", "remove", "--force", worktree_path])
    if result.returncode != 0:
        # Try manual cleanup
        import shutil
        if os.path.exists(worktree_path):
            shutil.rmtree(worktree_path, ignore_errors=True)
        # Prune worktree references
        _run_git(repo_root, ["worktree", "prune"])
    return True


def list_worktrees(repo_root: str) -> list[dict]:
    """List all active worktrees.

    Returns list of dicts with 'path', 'branch', 'head' keys.
    """
    result = _run_git(repo_root, ["worktree", "list", "--porcelain"])
    if result.returncode != 0:
        return []

    worktrees = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True

    if current:
        worktrees.append(current)

    return worktrees


def get_worktree_diff(worktree_path: str, base_branch: str = "main",
                      base_commit: str = "") -> str:
    """Get the diff between the worktree branch and its base.

    Uses base_commit SHA if provided (most reliable), otherwise
    falls back to base_branch name.
    """
    base_ref = base_commit or base_branch
    result = _run_git(
        worktree_path,
        ["diff", f"{base_ref}...HEAD", "--stat"],
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def get_worktree_full_diff(worktree_path: str, base_branch: str = "main",
                           base_commit: str = "") -> str:
    """Get the full diff between the worktree branch and its base."""
    base_ref = base_commit or base_branch
    result = _run_git(
        worktree_path,
        ["diff", f"{base_ref}...HEAD"],
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def commit_in_worktree(
    worktree_path: str,
    message: str,
    files: Optional[list[str]] = None,
) -> Optional[str]:
    """Stage and commit changes in a worktree.

    Args:
        worktree_path: Path to the worktree.
        message: Commit message.
        files: Specific files to stage, or None for all changes.

    Returns:
        Commit SHA, or None if commit failed.
    """
    if files:
        result = _run_git(worktree_path, ["add", "--"] + files)
    else:
        result = _run_git(worktree_path, ["add", "-A"])
    if result.returncode != 0:
        return None

    result = _run_git(worktree_path, ["commit", "--no-verify", "-m", message])
    if result.returncode != 0:
        return None

    # Get the commit SHA
    result = _run_git(worktree_path, ["rev-parse", "HEAD"])
    sha = result.stdout.strip() if result.returncode == 0 else None

    # Push the branch to origin so code is never orphaned on MacStudio
    if sha:
        branch_result = _run_git(worktree_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        if branch_result.returncode == 0:
            branch = branch_result.stdout.strip()
            _run_git(worktree_path, ["push", "origin", branch])  # Best effort

    return sha
    return None
