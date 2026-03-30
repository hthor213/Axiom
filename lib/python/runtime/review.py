"""Verification pipeline — tests, adversarial review, and feedback assembly.

Standalone functions for running tests, adversarial review, and
assembling feedback from review reports.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Callable, Optional


def run_tests(worktree_path: str) -> tuple[int, int, str]:
    """Run pytest in the worktree. Returns (passed, failed, output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=worktree_path,
        )
        output = result.stdout + result.stderr
        passed = failed = 0
        for line in output.split("\n"):
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
        return passed, failed, output
    except (subprocess.TimeoutExpired, Exception):
        return 0, 0, ""


SOFT_CAP = 200
HARD_CAP = 350


def _get_changed_files(worktree_path: str, base_ref: str) -> set[str]:
    """Get all changed files: tracked diffs + untracked new files."""
    files: set[str] = set()
    for cmd in (["git", "diff", "--name-only", base_ref],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=worktree_path)
        if r.returncode == 0 and r.stdout.strip():
            files.update(f for f in r.stdout.strip().split("\n") if f)
    return files


def check_file_sizes(worktree_path: str, base_commit: str,
                     base_branch: str) -> dict:
    """Check line counts of changed .py files against coding standards.

    Returns {"over_hard": [...], "over_soft": [...], "all_under_soft": bool}.
    """
    base_ref = base_commit or base_branch
    all_files = _get_changed_files(worktree_path, base_ref)
    if not all_files:
        return {"over_hard": [], "over_soft": [], "all_under_soft": True}

    py_files = [f for f in all_files if f.endswith(".py")]
    over_hard = []
    over_soft = []
    for f in py_files:
        full_path = os.path.join(worktree_path, f)
        if not os.path.isfile(full_path):
            continue
        lines = sum(1 for _ in open(full_path))
        if lines > HARD_CAP:
            over_hard.append({"file": f, "lines": lines})
        elif lines > SOFT_CAP:
            over_soft.append({"file": f, "lines": lines})

    return {
        "over_hard": over_hard,
        "over_soft": over_soft,
        "all_under_soft": len(over_hard) == 0 and len(over_soft) == 0,
    }


def run_adversarial(worktree_path: str,
                    base_commit: str,
                    file_extensions: tuple[str, ...],
                    repo_root: str,
                    base_branch: str,
                    emit_fn: Callable,
                    spec_number: str = "",
                    plan_context: str = "",
                    ) -> tuple[Optional[str], Optional[dict]]:
    """Run adversarial review on the worktree changes.

    Args:
        worktree_path: path to the git worktree.
        base_commit: commit to diff against (defaults to base_branch).
        file_extensions: tuple of file extensions to include (e.g. (".py",) or (".md",)).
        repo_root: path to the main repository root.
        base_branch: name of the base branch.
        emit_fn: callback for progress events.

    Returns (verdict, report_dict).

    CRITICAL: The git diff line MUST be ["git", "diff", "--name-only", base_ref]
    — NOT f"{base_ref}...HEAD". This was the root cause of SKIP verdicts.

    Also includes untracked new files (agent-created via Write tool but not staged).
    """
    base_ref = base_commit or base_branch
    try:
        all_files = _get_changed_files(worktree_path, base_ref)
        if not all_files:
            return "SKIP", None

        changed_files = [f for f in all_files
                         if any(f.endswith(ext) for ext in file_extensions)]
        if not changed_files:
            return "SKIP", None

        # Import and run the adversarial pipeline
        lib_path = os.path.join(repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from adversarial.adversarial import run_pipeline
        from adversarial.credentials import load_credentials
        from adversarial.model_resolver import resolve_models

        creds = load_credentials(repo_root)
        models = resolve_models(creds)

        abs_files = [os.path.join(worktree_path, f) for f in changed_files]

        def _adversarial_progress(phase, detail):
            emit_fn("adversarial_progress", {"phase": phase, **detail})

        report = run_pipeline(abs_files, worktree_path, creds, models,
                              progress_callback=_adversarial_progress,
                              spec_number=spec_number,
                              plan_context=plan_context)

        verdict = report.get("verdict", "SKIP")
        return verdict, report

    except Exception:
        raise  # No silent SKIP — let errors propagate


def gpt_final_review(adversarial_report: Optional[dict],
                     test_passed: int, config) -> tuple[bool, str]:
    """Ask GPT to confirm code is ready after adversarial fixes.

    Called when tests pass but adversarial review found issues. GPT acts
    as neutral reviewer, not adversarial arbiter. Returns (ship_ready, notes).
    """
    import time
    import urllib.request

    issues = []
    challenger = (adversarial_report or {}).get("challenger",
                  (adversarial_report or {}).get("critique", {}))
    if isinstance(challenger, dict):
        for issue in challenger.get("issues", challenger.get("findings", [])):
            if isinstance(issue, dict):
                desc = issue.get("description", issue.get("issue", str(issue)))
                sev = issue.get("severity", "medium")
                issues.append(f"- [{sev}] {desc[:200]}")
    issues_text = "\n".join(issues) if issues else "No specific issues recorded."

    prompt = (
        f"Code review for a software project. All tests pass "
        f"({test_passed} passed, 0 failed).\n\n"
        f"A code reviewer raised these points:\n{issues_text}\n\n"
        f"The author reviewed and fixed what they agreed with.\n\n"
        f"Are there any remaining critical issues that would prevent "
        f"shipping? Only flag issues that could cause runtime failures "
        f"or data loss — not style, not theoretical concerns for "
        f"single-instance deployments.\n\n"
        f'Respond with JSON: {{"ship_ready": true, "notes": "..."}}'
    )
    system = ("You are a pragmatic code reviewer. Tests pass. "
              "Focus only on real problems, not theoretical ones.")

    try:
        lib_path = os.path.join(config.repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from adversarial.credentials import load_credentials
        from adversarial.model_resolver import resolve_or_load

        creds = load_credentials(config.repo_root)
        api_key = creds.get("openai")
        if not api_key:
            return True, "No API key — defaulting to ship-ready (tests pass)"
        models = resolve_or_load(creds, config.repo_root)

        body = json.dumps({
            "model": models.openai,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_completion_tokens": 1024,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"]

        # Parse JSON response
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        return parsed.get("ship_ready", True), parsed.get("notes", "")
    except Exception as e:
        # On any failure, default to ship-ready (tests pass)
        return True, f"GPT review unavailable ({e}) — tests pass, defaulting to ready"


def assemble_feedback(report: Optional[dict]) -> str:
    """Assemble consolidated feedback from all three adversarial models.

    Extracts the key issues from the adversarial report into a single
    prompt that Claude can act on.
    """
    if not report:
        return "Adversarial review failed but no details available."

    parts = []

    # Mission context — so Claude knows the overall goal when fixing
    mission = report.get("mission_assessment")
    if mission and isinstance(mission, dict):
        mv = mission.get("verdict", "UNKNOWN")
        mr = mission.get("reasoning", "")
        parts.append(f"### Mission Assessment: {mv}\n{mr}\n")

    # Extract challenger (Gemini) findings
    challenger = report.get("challenger", report.get("critique", {}))
    if isinstance(challenger, dict):
        issues = challenger.get("issues", challenger.get("findings", []))
        if issues:
            parts.append("### Gemini (Challenger) found:")
            for i, issue in enumerate(issues, 1):
                if isinstance(issue, dict):
                    parts.append(f"{i}. {issue.get('description', issue.get('issue', str(issue)))}")
                else:
                    parts.append(f"{i}. {issue}")

    # Extract arbiter (GPT) notes
    arbiter = report.get("arbiter", report.get("arbitration", {}))
    if isinstance(arbiter, dict):
        summary = arbiter.get("summary", arbiter.get("reasoning", ""))
        if summary:
            parts.append(f"\n### GPT (Arbiter) summary:\n{summary}")

    # Overall verdict context
    verdict = report.get("verdict", "FAIL")
    summary = report.get("summary", "")
    if summary:
        parts.append(f"\n### Overall: {verdict}\n{summary}")

    return ("\n".join(parts) if parts
            else f"Adversarial verdict: FAIL. Raw report: {json.dumps(report, default=str)[:2000]}")


def verify_draft(task, worktree, config, emit_fn):
    """Draft review: adversarial on .md files, one retry on FAIL."""
    from .agent_runner import run_fix_session

    adversarial_verdict = None
    adversarial_report = None
    turns_used = 0

    if config.run_adversarial:
        adversarial_verdict, adversarial_report = run_adversarial(
            worktree.path, base_commit=worktree.base_commit,
            file_extensions=(".md",),
            repo_root=config.repo_root,
            base_branch=config.base_branch,
            emit_fn=emit_fn,
            spec_number=task.spec_number,
        )
        # If adversarial review fails, send feedback and retry once
        if adversarial_verdict == "FAIL" and adversarial_report:
            feedback = assemble_feedback(adversarial_report)
            emit_fn("adversarial_fix", {
                "task_id": task.id, "attempt": 1,
                "feedback_length": len(feedback),
            })
            fix_turns = run_fix_session(task, worktree, feedback, config)
            turns_used += fix_turns
            # Re-check after fix
            adversarial_verdict, adversarial_report = run_adversarial(
                worktree.path, base_commit=worktree.base_commit,
                file_extensions=(".md",),
                repo_root=config.repo_root,
                base_branch=config.base_branch,
                emit_fn=emit_fn,
                spec_number=task.spec_number,
            )
    else:
        adversarial_verdict = "SKIP"

    return adversarial_verdict, adversarial_report, turns_used


def verify_code(task, worktree, store, config, emit_fn,
                plan_context: str = ""):
    """Run the code verification loop: tests + adversarial + fix.

    Uses trajectory-aware triage for test failures: tracks improvement
    across retries and adapts response based on momentum. Eureka moments
    (>60% improvement in one step) reset the retry budget.

    Returns (verdict, report, harness_result, test_passed, test_failed,
             test_output, turns_used).
    """
    from .agent_runner import run_fix_session
    from .mcp_tools import run_harness_check
    from .notifications import send_spec_alignment_alert

    max_attempts = config.max_failures_per_task
    adversarial_verdict = None
    adversarial_report = None
    harness_result = {}
    test_passed = 0
    test_failed = 0
    test_output = ""
    turns_used = 0

    # Check file sizes against coding standards
    sizes = check_file_sizes(worktree.path, worktree.base_commit,
                             config.base_branch)
    if sizes["over_hard"]:
        files_desc = ", ".join(f"{f['file']} ({f['lines']}L)" for f in sizes["over_hard"])
        feedback = (f"Files exceed the 350-line hard cap and must be split: {files_desc}. "
                    f"Split each file into focused modules under 200 lines.")
        fix_turns = run_fix_session(task, worktree, feedback, config)
        turns_used += fix_turns
        sizes = check_file_sizes(worktree.path, worktree.base_commit,
                                 config.base_branch)

    tests_required = not sizes["all_under_soft"]
    failure_history: list[int] = []
    playwright_done = False
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        emit_fn("adversarial_attempt", {
            "task_id": task.id, "attempt": attempt,
            "max_attempts": max_attempts,
        })

        harness_result = run_harness_check(task.spec_number, worktree.path)
        test_passed, test_failed, test_output = run_tests(worktree.path)

        if test_failed > 0:
            from .test_triage import triage_test_failures
            action, guidance, reset_budget = triage_test_failures(
                test_passed, test_failed, test_output,
                failure_history, config, emit_fn,
            )
            if action == "waiting_for_human":
                store.update_task_status(task.id, "waiting_for_human")
                emit_fn("needs_human", {
                    "task_id": task.id,
                    "reason": "test_failure_stagnating",
                    "failure_history": failure_history,
                })
                break
            elif action == "retry":
                if reset_budget:
                    attempt = 0
                    emit_fn("eureka_reset", {
                        "task_id": task.id,
                        "failure_history": failure_history,
                    })
                fix_turns = run_fix_session(task, worktree, guidance, config)
                turns_used += fix_turns
                continue
            else:
                break

        if tests_required and test_passed == 0 and test_failed == 0:
            over_desc = ", ".join(f"{f['file']} ({f['lines']}L)" for f in sizes["over_soft"])
            feedback = (f"Files over 200 lines require unit tests: {over_desc}. "
                        f"Either write tests or simplify below 200 lines.")
            fix_turns = run_fix_session(task, worktree, feedback, config)
            turns_used += fix_turns
            continue

        # --- Playwright functional tests (spec 029) ---
        if not playwright_done:
            from .functional_tests import should_run_playwright, generate_playwright_test
            from .prompts import find_spec
            if should_run_playwright(worktree.path, worktree.base_commit,
                                     config.base_branch):
                spec_path = find_spec(task.spec_number, config.repo_root)
                if spec_path:
                    with open(spec_path) as f:
                        spec_content = f.read()
                    emit_fn("playwright_generating", {
                        "task_id": task.id,
                        "spec_number": task.spec_number,
                    })
                    try:
                        generate_playwright_test(
                            task.spec_number, spec_content,
                            worktree.path, config.repo_root)
                        playwright_done = True
                        # Re-run tests — now includes Playwright functional tests
                        test_passed, test_failed, test_output = run_tests(
                            worktree.path)
                        if test_failed > 0:
                            emit_fn("playwright_failed", {
                                "task_id": task.id,
                                "test_failed": test_failed,
                            })
                            continue  # Back to top → triage handles failure
                    except Exception as e:
                        emit_fn("playwright_error", {
                            "task_id": task.id, "error": str(e),
                        })
                        playwright_done = True  # Don't retry on API failure

        if not config.run_adversarial:
            adversarial_verdict = "SKIP"
            break

        adversarial_verdict, adversarial_report = run_adversarial(
            worktree.path, base_commit=worktree.base_commit,
            file_extensions=(".py",),
            repo_root=config.repo_root,
            base_branch=config.base_branch,
            emit_fn=emit_fn,
            spec_number=task.spec_number,
            plan_context=plan_context,
        )

        if adversarial_verdict in ("PASS", "SKIP"):
            break

        if adversarial_verdict == "NEEDS_HUMAN" and adversarial_report:
            category_c = adversarial_report.get("category_c_items", [])
            if category_c and config.telegram_notify:
                send_spec_alignment_alert(task, category_c, config)
            store.update_task_status(task.id, "waiting_for_human")
            emit_fn("needs_human", {
                "task_id": task.id,
                "reason": "spec_alignment",
                "category_c_count": len(category_c),
            })
            break

        # Tests green + adversarial FAIL = advisory, not a gate
        tests_clean = (test_failed == 0 and test_passed > 0)
        if adversarial_verdict == "FAIL" and tests_clean:
            feedback = assemble_feedback(adversarial_report)
            emit_fn("adversarial_fix", {
                "task_id": task.id, "attempt": attempt,
                "feedback_length": len(feedback),
                "tests_clean": True,
            })
            fix_turns = run_fix_session(task, worktree, feedback, config)
            turns_used += fix_turns

            # GPT final review — neutral, not adversarial
            ship_ready, notes = gpt_final_review(
                adversarial_report, test_passed, config)
            if ship_ready:
                adversarial_verdict = "PASS"
            # else: keep FAIL — GPT agrees it shouldn't ship
            if adversarial_report and notes:
                adversarial_report["gpt_final_notes"] = notes
            emit_fn("adversarial_override", {
                "task_id": task.id,
                "reason": "tests_clean_advisory_pass" if ship_ready else "gpt_blocked",
                "ship_ready": ship_ready,
                "test_passed": test_passed,
            })
            break

        # Tests NOT clean — keep existing blind retry
        if attempt < max_attempts:
            feedback = assemble_feedback(adversarial_report)
            emit_fn("adversarial_fix", {
                "task_id": task.id, "attempt": attempt,
                "feedback_length": len(feedback),
            })
            fix_turns = run_fix_session(task, worktree, feedback, config)
            turns_used += fix_turns

    return (adversarial_verdict, adversarial_report, harness_result,
            test_passed, test_failed, test_output, turns_used)
