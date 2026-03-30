"""Git operations via subprocess.

Provides dataclasses and functions for inspecting and manipulating git
repositories using subprocess calls. All operations are safe — they return
sensible defaults when git is unavailable or the directory is not a repo.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class GitStatus:
    """Snapshot of a git repository's current status."""

    branch: str = ""
    base_branch: str = ""
    has_remote: bool = False
    uncommitted: List[str] = field(default_factory=list)
    staged: List[str] = field(default_factory=list)
    recent_commits: List[str] = field(default_factory=list)
    is_clean: bool = True


@dataclass
class BranchInfo:
    """Information about the current branch and its relationship to remotes."""

    current: str = ""
    base: str = ""
    tracks_remote: bool = False
    remote_name: str = ""


def _run_git(
    root: str,
    args: List[str],
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given root directory.

    Args:
        root: Working directory for the git command.
        args: Arguments to pass after 'git'.
        timeout: Maximum seconds to wait for the command.

    Returns:
        The CompletedProcess result. On any error, returns a synthetic
        CompletedProcess with returncode=-1 and empty stdout/stderr.
    """
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return subprocess.CompletedProcess(
            args=["git"] + args,
            returncode=-1,
            stdout="",
            stderr="",
        )


def _is_git_repo(root: str) -> bool:
    """Check whether root is the root of a git repository.

    Args:
        root: Directory path to check.

    Returns:
        True if the directory is the root of a git repo, False otherwise.
    """
    result = _run_git(root, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return False
    try:
        toplevel = Path(result.stdout.strip()).resolve()
        target = Path(root).resolve()
        return toplevel == target
    except (OSError, ValueError):
        return False


def _current_branch(root: str) -> str:
    """Return the name of the current branch, or empty string.

    Args:
        root: Repository root directory.

    Returns:
        Branch name string, or '' if detached or not a repo.
    """
    result = _run_git(root, ["branch", "--show-current"])
    if result.returncode == 0:
        branch = result.stdout.strip()
        # "HEAD" is returned by rev-parse --abbrev-ref in detached state;
        # branch --show-current returns "" but guard against either.
        if branch == "HEAD":
            return ""
        return branch
    return ""


def _detect_base_branch(root: str) -> str:
    """Heuristically detect the base branch (main or master).

    Args:
        root: Repository root directory.

    Returns:
        'main', 'master', or '' if neither exists.
    """
    for candidate in ("main", "master"):
        result = _run_git(root, ["rev-parse", "--verify", candidate])
        if result.returncode == 0:
            return candidate
    return ""


def _has_remote(root: str) -> bool:
    """Check whether the repository has any configured remotes.

    Args:
        root: Repository root directory.

    Returns:
        True if at least one remote is configured.
    """
    result = _run_git(root, ["remote"])
    return result.returncode == 0 and result.stdout.strip() != ""


def _uncommitted_files(root: str) -> List[str]:
    """List files with uncommitted changes (modified, untracked).

    Args:
        root: Repository root directory.

    Returns:
        List of file paths with uncommitted changes.
    """
    result = _run_git(root, ["status", "--porcelain", "-z", "-uall"])
    if result.returncode != 0:
        return []
    files: List[str] = []
    output = result.stdout
    # -z output: entries are NUL-terminated. Each entry starts with XY status
    # then a space, then the path. Renames have a second NUL-terminated path.
    entries = output.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) < 4:
            i += 1
            continue
        x_status = entry[0]
        y_status = entry[1]
        filepath = entry[3:].strip()
        # Strip surrounding quotes that git adds for paths with special chars
        if filepath.startswith('"') and filepath.endswith('"'):
            filepath = filepath[1:-1]
        # Renames (R) and copies (C) have an additional path entry
        if x_status in ("R", "C"):
            # The next entry is the original path; we want the new path
            i += 1  # skip the source path
        # Uncommitted = anything modified in working tree or untracked
        if y_status != " " or x_status == "?":
            if filepath not in files:
                files.append(filepath)
        i += 1
    return files


def _staged_files(root: str) -> List[str]:
    """List files that are staged for commit.

    Args:
        root: Repository root directory.

    Returns:
        List of staged file paths.
    """
    result = _run_git(root, ["diff", "--cached", "--name-only", "-z"])
    if result.returncode != 0:
        return []
    # -z output is NUL-separated; split and filter empty strings
    return [f for f in result.stdout.split("\0") if f]


def _recent_commits(root: str, count: int = 5) -> List[str]:
    """Return the most recent commit messages (one-line format).

    Args:
        root: Repository root directory.
        count: Maximum number of commits to retrieve.

    Returns:
        List of commit message strings, most recent first.
    """
    result = _run_git(root, ["log", f"--max-count={count}", "--oneline"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]


def _tracking_info(root: str, branch: str) -> tuple[bool, str]:
    """Get remote tracking info for a branch.

    Args:
        root: Repository root directory.
        branch: Branch name to check.

    Returns:
        Tuple of (tracks_remote, remote_name).
    """
    if not branch:
        return False, ""
    result = _run_git(
        root,
        ["config", f"branch.{branch}.remote"],
    )
    if result.returncode == 0 and result.stdout.strip():
        return True, result.stdout.strip()
    return False, ""


def gather_status(root: str) -> GitStatus:
    """Gather comprehensive git status for a repository.

    Collects branch info, remote status, uncommitted/staged files,
    recent commits, and overall cleanliness. Returns sensible defaults
    if the directory is not a git repository.

    Args:
        root: Path to the repository root directory.

    Returns:
        A GitStatus dataclass with all fields populated.
    """
    if not os.path.isdir(root):
        return GitStatus()

    if not _is_git_repo(root):
        return GitStatus()

    branch = _current_branch(root)
    base_branch = _detect_base_branch(root)
    has_rem = _has_remote(root)
    uncommitted = _uncommitted_files(root)
    staged = _staged_files(root)
    commits = _recent_commits(root)

    # Clean means no uncommitted changes and no staged changes
    is_clean = len(uncommitted) == 0 and len(staged) == 0

    return GitStatus(
        branch=branch,
        base_branch=base_branch,
        has_remote=has_rem,
        uncommitted=uncommitted,
        staged=staged,
        recent_commits=commits,
        is_clean=is_clean,
    )


def detect_branches(root: str) -> BranchInfo:
    """Detect branch information for the repository.

    Identifies the current branch, base branch, and remote tracking
    configuration. Returns empty BranchInfo if not a git repo.

    Args:
        root: Path to the repository root directory.

    Returns:
        A BranchInfo dataclass with branch details.
    """
    if not os.path.isdir(root):
        return BranchInfo()

    if not _is_git_repo(root):
        return BranchInfo()

    current = _current_branch(root)
    base = _detect_base_branch(root)
    tracks_remote, remote_name = _tracking_info(root, current)

    return BranchInfo(
        current=current,
        base=base,
        tracks_remote=tracks_remote,
        remote_name=remote_name,
    )


def stage_files(root: str, files: List[str]) -> bool:
    """Stage specific files for commit.

    Args:
        root: Path to the repository root directory.
        files: List of file paths (relative to root) to stage.

    Returns:
        True if git add succeeded for all batches, False otherwise.
    """
    if not files:
        return False

    if not os.path.isdir(root):
        return False

    if not _is_git_repo(root):
        return False

    # Batch files to avoid exceeding ARG_MAX
    batch_size = 100
    for i in range(0, len(files), batch_size):
        batch = files[i : i + batch_size]
        result = _run_git(root, ["add", "--"] + batch)
        if result.returncode != 0:
            return False
    return True


def create_commit(root: str, message: str) -> bool:
    """Create a git commit with the given message.

    Only commits if there are staged changes. Uses --no-verify to skip
    hooks for programmatic commits.

    Args:
        root: Path to the repository root directory.
        message: Commit message string.

    Returns:
        True if the commit was created successfully, False otherwise.
    """
    if not message:
        return False

    if not os.path.isdir(root):
        return False

    if not _is_git_repo(root):
        return False

    # Check that there are staged changes to commit
    staged = _staged_files(root)
    if not staged:
        return False

    result = _run_git(root, ["commit", "--no-verify", "-m", message])
    return result.returncode == 0
