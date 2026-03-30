"""Gate definitions and evaluation.

Three gates control session progression:
- activation_gate: can we start working on a spec?
- completion_gate: is a spec's automatable work done?
- checkpoint_gate: is the session ready to checkpoint?
"""

from __future__ import annotations

import os
from datetime import date

from .parser import extract_spec_status, scan_active_specs, count_current_tasks
from .spec_check import check_spec
from .state import load_state, SessionPhase


def _check(description: str, passed: bool, error: str | None = None) -> dict:
    return {"description": description, "passed": passed, "error": error}


def activation_gate(spec_path: str, tasks_path: str, specs_dir: str) -> dict:
    """Check whether a spec can be activated for work.

    Checks:
    - Spec file exists
    - Spec status is draft or active (not done)
    - CURRENT_TASKS.md has < 3 active items
    """
    checks: list[dict] = []
    errors: list[str] = []

    # Check 1: spec file exists
    exists = os.path.exists(spec_path)
    checks.append(_check("Spec file exists", exists, None if exists else f"Not found: {spec_path}"))
    if not exists:
        errors.append(f"Spec file not found: {spec_path}")

    # Check 2: spec status is draft or active
    if exists:
        status = extract_spec_status(spec_path)
        ok = status in ("draft", "active")
        checks.append(_check(
            f"Spec status is workable (draft/active)",
            ok,
            None if ok else f"Spec status is '{status}' — already done or unknown",
        ))
        if not ok:
            errors.append(f"Spec status is '{status}'")
    else:
        checks.append(_check("Spec status is workable", False, "Cannot check — file missing"))

    # Check 3: task count < 3
    task_count = count_current_tasks(tasks_path)
    ok = task_count < 3
    checks.append(_check(
        f"Active tasks < 3 (currently {task_count})",
        ok,
        None if ok else f"Too many active tasks: {task_count}",
    ))
    if not ok:
        errors.append(f"Too many active tasks ({task_count})")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "errors": errors}


def completion_gate(spec_path: str, project_root: str) -> dict:
    """Check whether a spec's automatable Done When items all pass.

    Gate passes if all automatable checks pass. Judgment items don't block.
    """
    checks: list[dict] = []
    errors: list[str] = []

    result = check_spec(spec_path, project_root)

    for item in result["items"]:
        if item["result"] is None:
            # Judgment item — note but don't block
            checks.append(_check(
                f"[judgment] {item['text'][:80]}",
                True,  # doesn't block
                "Requires LLM judgment",
            ))
        elif item["result"]:
            checks.append(_check(item["text"][:80], True))
        else:
            checks.append(_check(item["text"][:80], False, item.get("error")))
            errors.append(item.get("error", f"Check failed: {item['text'][:80]}"))

    passed = result["failed"] == 0
    return {"passed": passed, "checks": checks, "errors": errors}


def checkpoint_gate(project_root: str) -> dict:
    """Check whether the session is ready to checkpoint.

    Checks:
    - LAST_SESSION.md exists and was modified today
    - All active specs have been checked
    - .harness.json shows phase is WORKING or CHECKPOINTING
    """
    checks: list[dict] = []
    errors: list[str] = []

    # Check 1: LAST_SESSION.md exists and modified today
    ls_path = os.path.join(project_root, "LAST_SESSION.md")
    if os.path.exists(ls_path):
        mtime = os.path.getmtime(ls_path)
        mod_date = date.fromtimestamp(mtime)
        today = date.today()
        is_today = mod_date == today
        checks.append(_check(
            "LAST_SESSION.md exists and modified today",
            is_today,
            None if is_today else f"Last modified {mod_date}, not today ({today})",
        ))
        if not is_today:
            errors.append(f"LAST_SESSION.md last modified {mod_date}")
    else:
        checks.append(_check("LAST_SESSION.md exists and modified today", False, "File not found"))
        errors.append("LAST_SESSION.md not found")

    # Check 2: all active specs checked
    specs_dir = os.path.join(project_root, "specs")
    active = scan_active_specs(specs_dir)
    all_specs_ok = True
    for spec in active:
        result = check_spec(spec["path"], project_root)
        spec_ok = result["failed"] == 0
        checks.append(_check(
            f"spec:{spec['number']} — {result['passed']} pass, {result['failed']} fail, {result['judgment']} judgment",
            spec_ok,
            None if spec_ok else f"{result['failed']} automatable check(s) failing",
        ))
        if not spec_ok:
            all_specs_ok = False
            errors.append(f"spec:{spec['number']} has {result['failed']} failing check(s)")

    # Check 3: phase is WORKING or CHECKPOINTING
    state = load_state(project_root)
    phase_ok = state.phase in (SessionPhase.WORKING, SessionPhase.CHECKPOINTING)
    checks.append(_check(
        f"Session phase is WORKING or CHECKPOINTING (currently {state.phase.value})",
        phase_ok,
        None if phase_ok else f"Phase is {state.phase.value}",
    ))
    if not phase_ok:
        errors.append(f"Session phase is {state.phase.value}")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "errors": errors}


class GateEvaluator:
    """Convenience wrapper for gate evaluation."""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.specs_dir = os.path.join(project_root, "specs")
        self.tasks_path = os.path.join(project_root, "CURRENT_TASKS.md")

    def activation(self, spec_path: str) -> dict:
        return activation_gate(spec_path, self.tasks_path, self.specs_dir)

    def completion(self, spec_path: str) -> dict:
        return completion_gate(spec_path, self.project_root)

    def checkpoint(self) -> dict:
        return checkpoint_gate(self.project_root)
