"""Done When classification and execution.

Classifies each Done When item into automatable check types and runs them.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from .parser import extract_done_when, extract_spec_status


def classify_done_when(item: dict) -> dict:
    """Classify a parsed Done When item by its check type.

    Returns the item dict augmented with:
        check_type: one of file_exists, grep, spec_status, command, judgment
        check_args: dict of arguments for the check (varies by type)
    """
    text = item["text"]
    result = dict(item)

    # --- file_exists ---
    # Patterns: "X file exists", "X exists at Y", "skill exists at `path`"
    m = re.search(r"exists\s+at\s+`([^`]+)`", text)
    if m:
        result["check_type"] = "file_exists"
        result["check_args"] = {"path": m.group(1)}
        return result

    m = re.search(r"`([^`]+)`\s+(?:file\s+)?exists\b", text)
    if m:
        result["check_type"] = "file_exists"
        result["check_args"] = {"path": m.group(1)}
        return result

    # Simpler: "X exists" where X is a backtick-wrapped path
    m = re.search(r"`([^`]+(?:\.\w+|/))`\s+exists\b", text)
    if m:
        result["check_type"] = "file_exists"
        result["check_args"] = {"path": m.group(1)}
        return result

    # --- spec_status ---
    # Pattern: "(-> spec:NNN)" with context about status, or "spec:NNN status is done"
    m = re.search(r"spec:(\d{3})\s+status\s+is\s+(draft|active|done)", text, re.IGNORECASE)
    if m:
        result["check_type"] = "spec_status"
        result["check_args"] = {"spec": m.group(1), "expected": m.group(2).lower()}
        return result

    # --- grep ---
    # Patterns: "X mentions Y", "X contains Y", "X references Y"
    m = re.search(
        r"`([^`]+)`\s+(?:mentions?|contains?|references?|includes?)\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if m:
        file_ref = m.group(1)
        pattern = m.group(2).strip().strip("`").strip('"').strip("'")
        result["check_type"] = "grep"
        result["check_args"] = {"file": file_ref, "pattern": pattern}
        return result

    # Also match: "Vision spec (-> spec:000) mentions X"
    m = re.search(
        r"(?:spec|vision)\s+(?:spec\s+)?\(->\s*spec:(\d{3})\)\s+(?:mentions?|contains?|references?)\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if m:
        result["check_type"] = "grep"
        result["check_args"] = {"file": f"spec:{m.group(1)}", "pattern": m.group(2).strip()}
        return result

    # --- command ---
    # Pattern: backtick-wrapped command that looks executable
    m = re.search(r"`([^`]+)`", text)
    if m:
        cmd_candidate = m.group(1)
        # Only classify as command if it looks like a shell command (starts with
        # a known command or contains spaces suggesting arguments)
        # Only allow safe, read-only commands — never shell interpreters or network tools
        _SAFE_CMD_STARTERS = (
            "python", "pip", "npm", "node", "platform ",
            "make", "pytest", "git status", "git log", "git diff",
        )
        _BLOCKED_CMD_STARTERS = (
            "curl", "wget", "bash", "sh ", "rm ", "sudo",
        )
        if any(cmd_candidate.startswith(s) for s in _BLOCKED_CMD_STARTERS):
            # Dangerous command — classify as judgment, never auto-execute
            result["check_type"] = "judgment"
            result["check_args"] = {"reason": "blocked_command"}
            return result
        if any(cmd_candidate.startswith(s) for s in _SAFE_CMD_STARTERS):
            result["check_type"] = "command"
            result["check_args"] = {"cmd": cmd_candidate}
            return result

    # --- judgment ---
    # Everything else requires LLM evaluation
    result["check_type"] = "judgment"
    result["check_args"] = {}
    return result


def _resolve_path(path: str, project_root: str) -> str:
    """Resolve a path relative to project_root, handling ~ expansion."""
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(project_root, path)


def _resolve_spec_file(spec_ref: str, project_root: str) -> Optional[str]:
    """Resolve 'spec:NNN' to a file path in specs/."""
    specs_dir = os.path.join(project_root, "specs")
    if not os.path.isdir(specs_dir):
        return None
    for fname in os.listdir(specs_dir):
        if fname.startswith(spec_ref + "-") and fname.endswith(".md"):
            return os.path.join(specs_dir, fname)
    return None


def run_check(classified_item: dict, project_root: str) -> dict:
    """Execute an automatable check.

    Returns the item with added fields:
        result: True (pass), False (fail), or None (judgment/skipped)
        error: str describing the failure, or None
    """
    item = dict(classified_item)
    check_type = item.get("check_type", "judgment")
    args = item.get("check_args", {})

    if check_type == "judgment":
        item["result"] = None
        item["error"] = None
        return item

    if check_type == "file_exists":
        path = _resolve_path(args["path"], project_root)
        exists = os.path.exists(path)
        item["result"] = exists
        item["error"] = None if exists else f"File not found: {path}"
        return item

    if check_type == "grep":
        file_ref = args["file"]
        pattern = args["pattern"]

        # Resolve spec: references
        if file_ref.startswith("spec:"):
            spec_num = file_ref.split(":")[1]
            resolved = _resolve_spec_file(spec_num, project_root)
            if not resolved:
                item["result"] = False
                item["error"] = f"Could not resolve {file_ref} to a file"
                return item
            file_ref = resolved
        else:
            file_ref = _resolve_path(file_ref, project_root)

        if not os.path.exists(file_ref):
            item["result"] = False
            item["error"] = f"File not found: {file_ref}"
            return item

        try:
            with open(file_ref, "r") as f:
                content = f.read()
            found = pattern.lower() in content.lower()
            item["result"] = found
            item["error"] = None if found else f"Pattern '{pattern}' not found in {file_ref}"
        except Exception as e:
            item["result"] = False
            item["error"] = str(e)
        return item

    if check_type == "spec_status":
        spec_num = args["spec"]
        expected = args["expected"]
        spec_path = _resolve_spec_file(spec_num, project_root)
        if not spec_path:
            item["result"] = False
            item["error"] = f"Could not find spec file for spec:{spec_num}"
            return item
        actual = extract_spec_status(spec_path)
        passed = actual == expected
        item["result"] = passed
        item["error"] = None if passed else f"spec:{spec_num} status is '{actual}', expected '{expected}'"
        return item

    if check_type == "command":
        cmd = args["cmd"]
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            passed = proc.returncode == 0
            item["result"] = passed
            item["error"] = None if passed else f"Command failed (rc={proc.returncode}): {proc.stderr[:200]}"
        except subprocess.TimeoutExpired:
            item["result"] = False
            item["error"] = f"Command timed out after 30s: {cmd}"
        except Exception as e:
            item["result"] = False
            item["error"] = str(e)
        return item

    # Unknown check type — treat as judgment
    item["result"] = None
    item["error"] = None
    return item


def check_spec(spec_path: str, project_root: str) -> dict:
    """Full pipeline: extract, classify, run checks, return summary.

    Returns dict with:
        spec_path, items (list of checked items),
        passed, failed, judgment, total
    """
    items = extract_done_when(spec_path)
    checked_items: list[dict] = []
    passed = 0
    failed = 0
    judgment = 0

    for item in items:
        classified = classify_done_when(item)
        result = run_check(classified, project_root)
        checked_items.append(result)

        if result["result"] is True:
            passed += 1
        elif result["result"] is False:
            failed += 1
        else:
            judgment += 1

    return {
        "spec_path": spec_path,
        "items": checked_items,
        "passed": passed,
        "failed": failed,
        "judgment": judgment,
        "total": len(checked_items),
    }


class SpecChecker:
    """Convenience wrapper for spec checking operations."""

    def __init__(self, project_root: str):
        self.project_root = project_root

    def check(self, spec_path: str) -> dict:
        return check_spec(spec_path, self.project_root)

    def classify(self, item: dict) -> dict:
        return classify_done_when(item)

    def run(self, classified_item: dict) -> dict:
        return run_check(classified_item, self.project_root)
