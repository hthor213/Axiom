"""Project sync status — live git state computation.

Computes whether a project's local clone exists, whether the remote is
reachable, and whether local is ahead/behind the remote tracking branch.

This is intentionally NOT stored in the database; it's recomputed on demand
since it changes with every push/pull.

Sync status icons (matches spec:022):
  ☁✓  cloud_synced   — remote + local, in sync
  ☁↕  cloud_drift    — remote + local, ahead or behind
  ☁   cloud_only     — remote URL known, no local clone
  💾   local_only     — local exists, no remote
  ✦   new            — just created, no commits
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class SyncStatus:
    """Live sync state for a project."""
    local_exists: bool = False
    remote_exists: bool = False
    ahead: int = 0       # commits local has that remote doesn't
    behind: int = 0      # commits remote has that local doesn't
    icon: str = "✦"      # ☁✓ | ☁↕ | ☁ | 💾 | ✦
    label: str = "new"   # human-readable label
    error: Optional[str] = None


def compute_sync_status(repo_path: str, remote_url: Optional[str]) -> SyncStatus:
    """Compute live sync status for a project.

    Args:
        repo_path: Absolute path to the local git repo (may not exist).
        remote_url: Remote URL (may be None for local-only projects).

    Returns:
        SyncStatus with icon/label/ahead/behind populated.
    """
    local_exists = _is_git_repo(repo_path)
    remote_exists = False
    ahead = behind = 0
    error = None

    if not local_exists:
        if remote_url:
            remote_exists = _check_remote_reachable(remote_url)
            if remote_exists:
                return SyncStatus(
                    local_exists=False, remote_exists=True,
                    icon="☁", label="cloud_only",
                )
        return SyncStatus(icon="✦", label="new")

    # Local exists — check commits
    if not _has_commits(repo_path):
        return SyncStatus(local_exists=True, icon="✦", label="new")

    # Check remote
    if remote_url:
        remote_exists = _check_remote_reachable(remote_url)

    if not remote_url or not remote_exists:
        return SyncStatus(
            local_exists=True, remote_exists=False,
            icon="💾", label="local_only",
        )

    # Both exist — check ahead/behind
    try:
        ahead, behind, err = _get_ahead_behind(repo_path)
        if err:
            error = err
    except Exception as e:
        error = str(e)

    if ahead == 0 and behind == 0:
        return SyncStatus(
            local_exists=True, remote_exists=True,
            ahead=0, behind=0,
            icon="☁✓", label="cloud_synced",
        )

    return SyncStatus(
        local_exists=True, remote_exists=True,
        ahead=ahead, behind=behind,
        icon="☁↕", label="cloud_drift",
        error=error,
    )


# ---- Internal helpers ----

def _is_git_repo(path: str) -> bool:
    """Return True if path is a git repository."""
    if not os.path.isdir(path):
        return False
    git_dir = os.path.join(path, ".git")
    return os.path.exists(git_dir)


def _has_commits(repo_path: str) -> bool:
    """Return True if the repo has at least one commit."""
    result = _run_git(repo_path, ["rev-parse", "HEAD"])
    return result.returncode == 0


def _check_remote_reachable(remote_url: str) -> bool:
    """Check if the remote URL is reachable via git ls-remote."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", remote_url],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_ahead_behind(repo_path: str) -> tuple[int, int, Optional[str]]:
    """Return (ahead, behind, error) vs the upstream tracking branch."""
    # Fetch to get current remote state (quiet, no fail if offline)
    _run_git(repo_path, ["fetch", "--quiet"], timeout=15)

    result = _run_git(
        repo_path,
        ["rev-list", "--left-right", "--count", "HEAD...@{u}"],
    )
    if result.returncode != 0:
        return 0, 0, result.stderr.strip() or "no upstream"

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0, f"unexpected output: {result.stdout!r}"

    return int(parts[0]), int(parts[1]), None


def _run_git(cwd: str, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:
        return subprocess.CompletedProcess(["git"] + args, -1, "", str(e))
