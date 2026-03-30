"""Git operations helpers for the HTH AI Dev Framework.

Provides utilities for querying git repository state including
current branch detection and uncommitted file listing.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional


class GitNotFoundError(RuntimeError):
    """Raised when the git executable cannot be found."""


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process.

    Args:
        args: Git subcommand and arguments.
        cwd: Working directory for the git command.

    Returns:
        The CompletedProcess instance from subprocess.run.

    Raises:
        GitNotFoundError: If the git executable cannot be found or the
            working directory does not exist.
    """
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError(
            f"git executable not found or working directory does not exist: {cwd}"
        ) from exc


def _current_branch(repo_path: str) -> str:
    """Get the current git branch name.

    Args:
        repo_path: Path to the git repository.

    Returns:
        The current branch name, or empty string if in detached HEAD state.
    """
    result = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_path)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _uncommitted_files(repo_path: str) -> List[str]:
    """List files with uncommitted changes (staged or unstaged).

    Uses NUL-delimited porcelain output to correctly handle paths
    with spaces, quotes, and renames.

    Args:
        repo_path: Path to the git repository.

    Returns:
        A list of file paths (relative to repo root) with uncommitted changes.
    """
    result = _run_git(["status", "--porcelain", "-z"], cwd=repo_path)
    if result.returncode != 0:
        return []
    files: List[str] = []
    entries = result.stdout.split('\0')
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) < 3:
            i += 1
            continue
        status = entry[:2]
        path = entry[3:]
        # Renames (R or C status) have a second path as the next NUL-delimited field
        if status[0] in ('R', 'C'):
            i += 1
            # The destination (new name) is `path`, source is entries[i]
            # We report the new name
        files.append(path)
        i += 1
    return files


def _init_repo(path: str) -> None:
    """Initialize a new git repository.

    Args:
        path: Directory in which to initialize the repo.

    Raises:
        RuntimeError: If git init fails.
    """
    result = _run_git(["init"], cwd=path)
    if result.returncode != 0:
        raise RuntimeError(f"git init failed: {result.stderr.strip()}")


def _add_and_commit(repo_path: str, message: str) -> None:
    """Stage all changes and commit.

    Args:
        repo_path: Path to the git repository.
        message: Commit message.

    Raises:
        RuntimeError: If git add or git commit fails.
    """
    result = _run_git(["add", "."], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"git add failed: {result.stderr.strip()}")
    result = _run_git(["commit", "-m", message, "--allow-empty"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")


def _has_uncommitted_changes(repo_path: str) -> bool:
    """Check whether the repo has any uncommitted changes.

    Args:
        repo_path: Path to the git repository.

    Returns:
        True if there are staged or unstaged changes.

    Raises:
        RuntimeError: If git status fails (e.g. not a git repository).
    """
    result = _run_git(["status", "--porcelain"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"git status failed (is this a git repository?): {result.stderr.strip()}"
        )
    return bool(result.stdout.strip())


def _is_git_repo(path: str) -> bool:
    """Check if path is inside a git repository.

    Args:
        path: Directory to check.

    Returns:
        True if the directory is within a git work tree.
    """
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _latest_commit_sha(repo_path: str, short: bool = False) -> str:
    """Get the SHA of the latest commit.

    Args:
        repo_path: Path to the git repository.
        short: If True, return abbreviated SHA.

    Returns:
        The commit SHA string, or empty string on failure.
    """
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    result = _run_git(args, cwd=repo_path)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _create_branch(repo_path: str, branch_name: str) -> bool:
    """Create a new branch.

    Args:
        repo_path: Path to the git repository.
        branch_name: Name for the new branch.

    Returns:
        True if the branch was created successfully.
    """
    result = _run_git(["branch", "--", branch_name], cwd=repo_path)
    return result.returncode == 0


def _checkout(repo_path: str, ref: str) -> bool:
    """Checkout a branch or ref.

    Args:
        repo_path: Path to the git repository.
        ref: Branch name or commit ref to checkout.

    Returns:
        True if checkout succeeded.
    """
    result = _run_git(["checkout", "--", ref], cwd=repo_path)
    return result.returncode == 0


def _list_branches(repo_path: str) -> List[str]:
    """List all local branches.

    Args:
        repo_path: Path to the git repository.

    Returns:
        List of branch names.
    """
    result = _run_git(["branch", "--list", "--format=%(refname:short)"], cwd=repo_path)
    if result.returncode != 0:
        return []
    return [b.strip() for b in result.stdout.splitlines() if b.strip()]
