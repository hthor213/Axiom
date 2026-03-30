"""Ship pipeline step implementations.

Each function executes one named step and returns a StepResult.
Imported by pipeline.py which handles orchestration.
"""

from __future__ import annotations

import os
import time
from typing import List

from .state import StepResult
from .strategies import (
    StrategyResult, detect_base_branch, fetch_and_merge_base,
    push_branch, create_pr, direct_merge,
)
from .verify import discover_and_run_tests, check_spec_drift, check_backlog, _run_cmd
from .deploy import load_targets, run_deploy_sequence


def do_verify(opts) -> StepResult:
    """Run tests, check drift, check backlog."""
    details = []

    if not opts.no_tests:
        passed, detail = discover_and_run_tests(opts.root)
        if not passed:
            return StepResult(step="verify", status="failed",
                              detail=detail, timestamp=time.time())
        details.append(detail)

    drift = check_spec_drift(opts.root)
    if drift:
        details.append(f"[warn] Spec drift: {drift}")

    backlog = check_backlog(opts.root)
    if backlog:
        details.append(f"[warn] {backlog}")

    return StepResult(
        step="verify", status="ok",
        detail="; ".join(details) if details else "All checks passed",
        timestamp=time.time(),
    )


def do_commit(opts) -> StepResult:
    """Commit staged changes. Dirty tree = abort."""
    status = _run_cmd(["git", "status", "--porcelain"], cwd=opts.root)
    lines = [ln for ln in status.stdout.splitlines() if ln.strip()]

    has_dirty = any(ln[1] in ("M", "D") and ln[0] == " " for ln in lines)
    if has_dirty and opts.actor == "cli":
        return StepResult(
            step="commit", status="failed",
            detail="Dirty working tree — stage or stash changes before shipping.",
            timestamp=time.time(),
        )

    staged = _run_cmd(["git", "diff", "--cached", "--name-only"], cwd=opts.root)
    if not staged.stdout.strip():
        if opts.actor == "cli":
            return StepResult(step="commit", status="failed",
                              detail="Nothing to commit.",
                              timestamp=time.time())
        return StepResult(step="commit", status="ok",
                          detail="No new commit needed (dashboard).",
                          timestamp=time.time())

    msg = opts.message or "ship: automated commit"
    result = _run_cmd(["git", "commit", "--no-verify", "-m", msg], cwd=opts.root)
    if result.returncode != 0:
        return StepResult(step="commit", status="failed",
                          detail=f"Commit failed: {result.stderr.strip()}",
                          timestamp=time.time())

    sha = _run_cmd(["git", "rev-parse", "HEAD"], cwd=opts.root)
    return StepResult(step="commit", status="ok",
                      detail=f"Committed: {sha.stdout.strip()[:8]}",
                      timestamp=time.time())


def do_push(opts) -> StepResult:
    """Push current branch to origin."""
    branch = _run_cmd(["git", "branch", "--show-current"], cwd=opts.root)
    branch_name = branch.stdout.strip()
    if not branch_name:
        return StepResult(step="push", status="failed",
                          detail="Cannot determine current branch.",
                          timestamp=time.time())

    sr = push_branch(opts.root, branch_name)
    return StepResult(step="push", status="ok" if sr.ok else "failed",
                      detail=sr.detail, timestamp=time.time())


def should_run_review(opts) -> bool:
    """Check if /review skill is available to run."""
    skill_path = os.path.expanduser("~/.claude/skills/review/SKILL.md")
    return os.path.isfile(skill_path)


def do_review(opts) -> StepResult:
    """Run /review skill if available. Non-zero exit aborts pipeline."""
    skill_path = os.path.expanduser("~/.claude/skills/review/SKILL.md")
    if not os.path.isfile(skill_path):
        return StepResult(step="review", status="ok",
                          detail="No review skill found — skipped.",
                          timestamp=time.time())

    result = _run_cmd(["hth-platform", "review"], cwd=opts.root, timeout=300)
    if result.returncode != 0:
        return StepResult(
            step="review", status="failed",
            detail=f"Review failed: {(result.stdout + result.stderr).strip()[-300:]}",
            timestamp=time.time(),
        )
    return StepResult(step="review", status="ok",
                      detail="Review passed.",
                      timestamp=time.time())


def do_deploy(opts, result) -> StepResult:
    """Run deploy targets."""
    branch = _run_cmd(["git", "branch", "--show-current"], cwd=opts.root)
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""

    targets = load_targets(opts.root)
    if opts.deploy_targets:
        targets = [t for t in targets if t.name in opts.deploy_targets]

    if not targets:
        return StepResult(step="deploy", status="ok",
                          detail="No deploy targets configured.",
                          timestamp=time.time())

    test_targets = [t for t in targets if t.role == "test"]
    non_test_targets = [t for t in targets if t.role != "test"]
    run_targets = non_test_targets + test_targets
    results = run_deploy_sequence(run_targets, branch=branch_name)

    outputs = []
    for dr in results:
        status = "ok" if dr.ok else "failed"
        outputs.append(f"{dr.target}: {status}")
        if dr.url:
            result.test_url = dr.url

    all_ok = all(dr.ok for dr in results)
    if not all_ok:
        failed = next(dr for dr in results if not dr.ok)
        return StepResult(
            step="deploy", status="failed",
            detail=f"Deploy failed: {failed.target} — {failed.output[:200]}",
            timestamp=time.time(),
        )

    if test_targets and result.test_url:
        return StepResult(
            step="deploy", status="awaiting_promotion",
            detail=f"Test deploy complete. URL: {result.test_url}",
            timestamp=time.time(),
        )

    return StepResult(step="deploy", status="ok",
                      detail="; ".join(outputs),
                      timestamp=time.time())


def do_pr_or_merge(opts, result, find_step_fn) -> StepResult:
    """Create PR or direct merge."""
    base = detect_base_branch(opts.root)
    if not base:
        return StepResult(
            step="pr_or_merge", status="failed",
            detail="Cannot determine base branch — set SHIP_BASE_BRANCH.",
            timestamp=time.time(),
        )

    fm = fetch_and_merge_base(opts.root, base)
    if not fm.ok:
        return StepResult(step="pr_or_merge", status="failed",
                          detail=fm.detail, timestamp=time.time())

    branch = _run_cmd(["git", "branch", "--show-current"], cwd=opts.root)
    branch_name = branch.stdout.strip()

    if opts.strategy == "merge":
        sr = direct_merge(opts.root, base, branch_name)
        result.merge_sha = sr.merge_sha
        detail = sr.detail
    else:
        title = opts.message or "Ship"
        verify_step = find_step_fn(result.steps, "verify")
        test_results = verify_step.detail if verify_step else ""
        sr = create_pr(opts.root, base, title,
                       summary=title, test_results=test_results,
                       adversarial_report=opts.adversarial_report,
                       dashboard_link=opts.dashboard_link)
        result.pr_url = sr.pr_url
        detail = sr.detail

    return StepResult(
        step="pr_or_merge",
        status="ok" if sr.ok else "failed",
        detail=detail,
        timestamp=time.time(),
    )
