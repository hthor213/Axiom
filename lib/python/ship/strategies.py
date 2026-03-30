"""Ship strategies — PR creation and direct merge logic.

Provides functions for creating a PR via `gh pr create` or
performing a direct fast-forward merge to the base branch.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyResult:
    """Result of executing a ship strategy."""

    ok: bool
    detail: str = ""
    pr_url: str = ""
    merge_sha: str = ""


def _run(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a subprocess command safely."""
    try:
        return subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=args, returncode=-1,
                                           stdout="", stderr="Timed out")
    except (FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(args=args, returncode=-1,
                                           stdout="", stderr=str(e))


def detect_base_branch(root: str) -> str:
    """Detect base branch: SHIP_BASE_BRANCH env -> main -> master -> empty."""
    env_branch = os.environ.get("SHIP_BASE_BRANCH", "")
    if env_branch:
        return env_branch
    for candidate in ("main", "master"):
        result = _run(["git", "rev-parse", "--verify", candidate], cwd=root)
        if result.returncode == 0:
            return candidate
    return ""


def fetch_and_merge_base(root: str, base: str) -> StrategyResult:
    """Fetch origin and merge base branch into current branch."""
    fetch = _run(["git", "fetch", "origin", base], cwd=root)
    if fetch.returncode != 0:
        return StrategyResult(ok=False,
                              detail=f"Fetch failed: {fetch.stderr.strip()}")

    merge = _run(["git", "merge", f"origin/{base}"], cwd=root)
    if merge.returncode != 0:
        # Abort the merge to leave clean state
        _run(["git", "merge", "--abort"], cwd=root)
        return StrategyResult(
            ok=False,
            detail="Merge conflicts detected — resolve conflicts manually, "
                   "then re-run /ship.",
        )
    return StrategyResult(ok=True, detail="Base branch merged successfully")


def push_branch(root: str, branch: str) -> StrategyResult:
    """Push branch to origin (no --force)."""
    result = _run(["git", "push", "origin", branch], cwd=root, timeout=60)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "non-fast-forward" in stderr or "rejected" in stderr:
            return StrategyResult(
                ok=False,
                detail="Push rejected — pull and rebase manually, "
                       "then re-run /ship.",
            )
        if "Could not resolve" in stderr or "unable to access" in stderr:
            return StrategyResult(
                ok=False,
                detail="Remote unreachable — check network and retry.",
            )
        return StrategyResult(ok=False, detail=f"Push failed: {stderr}")
    return StrategyResult(ok=True, detail="Pushed to origin")


def build_pr_body(
    summary: str = "",
    test_results: str = "",
    adversarial_report: str = "",
    dashboard_link: str = "",
) -> str:
    """Build structured PR body from components."""
    parts = []
    parts.append("## Summary")
    parts.append(summary or "_No summary provided._")
    parts.append("")
    parts.append("## Test Plan")
    parts.append(test_results or "_Tests not run or no results recorded._")
    if adversarial_report:
        parts.append("")
        parts.append("## Adversarial Report")
        parts.append(adversarial_report)
    if dashboard_link:
        parts.append("")
        parts.append(f"Dashboard: {dashboard_link}")
    return "\n".join(parts)


def create_pr(
    root: str,
    base: str,
    title: str,
    body: str = "",
    summary: str = "",
    test_results: str = "",
    adversarial_report: str = "",
    dashboard_link: str = "",
) -> StrategyResult:
    """Create a PR via `gh pr create`. If PR already exists, return its URL."""
    # Check for existing PR
    existing = _run(["gh", "pr", "view", "--json", "url", "-q", ".url"], cwd=root)
    if existing.returncode == 0 and existing.stdout.strip():
        url = existing.stdout.strip()
        return StrategyResult(ok=True, pr_url=url,
                              detail=f"PR already exists: {url}")

    if not body:
        body = build_pr_body(
            summary=summary or title,
            test_results=test_results,
            adversarial_report=adversarial_report,
            dashboard_link=dashboard_link,
        )

    args = ["gh", "pr", "create", "--base", base, "--title", title,
            "--body", body]
    result = _run(args, cwd=root, timeout=30)
    if result.returncode != 0:
        return StrategyResult(ok=False,
                              detail=f"PR creation failed: {result.stderr.strip()}")
    url = result.stdout.strip()
    return StrategyResult(ok=True, pr_url=url, detail=f"PR created: {url}")


def direct_merge(root: str, base: str, branch: str) -> StrategyResult:
    """Merge branch into base with --ff-only, then push base."""
    checkout = _run(["git", "checkout", base], cwd=root)
    if checkout.returncode != 0:
        return StrategyResult(ok=False,
                              detail=f"Checkout failed: {checkout.stderr.strip()}")

    merge = _run(["git", "merge", "--ff-only", branch], cwd=root)
    if merge.returncode != 0:
        # Go back to the feature branch
        _run(["git", "checkout", branch], cwd=root)
        return StrategyResult(
            ok=False,
            detail="Cannot fast-forward — fetch latest base and rebase "
                   "branch before direct merge.",
        )

    # Get the merge SHA
    sha_result = _run(["git", "rev-parse", "HEAD"], cwd=root)
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""

    push = _run(["git", "push", "origin", base], cwd=root, timeout=60)
    if push.returncode != 0:
        return StrategyResult(
            ok=False, merge_sha=sha,
            detail=f"Push to {base} failed: {push.stderr.strip()}",
        )

    return StrategyResult(
        ok=True, merge_sha=sha,
        detail=f"Merged to {base} (sha: {sha[:8]}). "
               f"Rollback: git revert {sha[:8]}",
    )
