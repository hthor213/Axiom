"""Live sync status computation for registered projects.

Sync status is computed on demand — not stored in DB since it changes
with every push/pull. Called by project_routes when listing or refreshing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class SyncStatus:
    """Live sync status for a project."""
    local_exists: bool
    remote_exists: bool
    ahead: int       # commits ahead of remote
    behind: int      # commits behind remote

    @property
    def icon(self) -> str:
        """Return the sync status icon per spec:022."""
        if not self.local_exists and not self.remote_exists:
            return "✦"
        if not self.local_exists:
            return "☁"
        if not self.remote_exists:
            return "💾"
        if self.ahead > 0 or self.behind > 0:
            return "☁↕"
        return "☁✓"

    @property
    def label(self) -> str:
        """Human-readable sync label."""
        icon = self.icon
        if icon == "✦":
            return "New / empty"
        if icon == "☁":
            return "Cloud only"
        if icon == "💾":
            return "Local only"
        if icon == "☁↕":
            parts = []
            if self.ahead:
                parts.append(f"{self.ahead} ahead")
            if self.behind:
                parts.append(f"{self.behind} behind")
            return "Out of sync — " + ", ".join(parts)
        return "In sync"

    def to_dict(self) -> dict:
        return {
            "local_exists": self.local_exists,
            "remote_exists": self.remote_exists,
            "ahead": self.ahead,
            "behind": self.behind,
            "icon": self.icon,
            "label": self.label,
        }


def _run(args: list, cwd: Optional[str] = None, timeout: int = 10) -> tuple[int, str]:
    """Run a subprocess command. Returns (returncode, stdout)."""
    try:
        r = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip()
    except Exception:
        return -1, ""


def compute_sync_status(
    repo_path: str,
    remote_url: Optional[str],
    fast: bool = False,
) -> SyncStatus:
    """Compute live sync status for a project.

    - local_exists: repo_path is a valid git directory
    - remote_exists: remote_url is set and reachable (git ls-remote)
    - ahead/behind: HEAD vs upstream tracking branch

    fast=True skips all network operations (no git ls-remote, no git fetch).
    remote_exists reflects whether remote_url is configured, not reachability.
    Use fast=True for list views; fast=False (default) for per-project refresh.
    """
    local_exists = _is_git_repo(repo_path)
    ahead = 0
    behind = 0

    if fast:
        remote_exists = bool(remote_url)
    else:
        remote_exists = False
        if remote_url:
            remote_exists = _check_remote_reachable(remote_url)
        if local_exists and remote_exists:
            ahead, behind = _get_ahead_behind(repo_path)

    return SyncStatus(
        local_exists=local_exists,
        remote_exists=remote_exists,
        ahead=ahead,
        behind=behind,
    )


def _is_git_repo(path: str) -> bool:
    """Check if path is a valid git repository."""
    if not path or not os.path.isdir(path):
        return False
    code, _ = _run(["git", "rev-parse", "--git-dir"], cwd=path, timeout=5)
    return code == 0


def _check_remote_reachable(remote_url: str) -> bool:
    """Check if a remote URL is reachable via git ls-remote."""
    code, _ = _run(["git", "ls-remote", "--heads", remote_url], timeout=8)
    return code == 0


def _get_ahead_behind(repo_path: str) -> tuple[int, int]:
    """Get ahead/behind count vs the tracking upstream branch.

    Fetches first to get current remote state.
    Returns (ahead, behind) — both 0 if no tracking branch configured.
    """
    _run(["git", "fetch", "--quiet"], cwd=repo_path, timeout=15)

    code, output = _run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
        cwd=repo_path, timeout=5,
    )
    if code != 0 or not output:
        return 0, 0

    parts = output.split()
    if len(parts) != 2:
        return 0, 0

    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def clone_project(remote_url: str, local_path: str) -> bool:
    """Clone a remote repository to local_path.

    Creates parent directories as needed.
    Returns True on success.
    """
    parent = os.path.dirname(local_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    code, _ = _run(["git", "clone", remote_url, local_path], timeout=120)
    return code == 0


def pull_project(repo_path: str) -> tuple[bool, str]:
    """Run git pull --ff-only on repo_path. Returns (success, output)."""
    code, out = _run(["git", "pull", "--ff-only"], cwd=repo_path, timeout=30)
    return code == 0, out
