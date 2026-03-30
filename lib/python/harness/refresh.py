"""Mid-session state save and refresh operations.

Provides two main functions:
- generate_refresh_state(ctx) -> str: Generate LAST_SESSION.md content with
  IN PROGRESS status for mid-session saves.
- prepare_state_commit(root) -> CommitPlan: Stage only specs + state files,
  leaving code changes unstaged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .checkpoint import CommitPlan
from .git_ops import _is_git_repo, _uncommitted_files, _staged_files
from .session import SessionContext


# ---------------------------------------------------------------------------
# Refresh-specific state files and patterns
# ---------------------------------------------------------------------------

_STATE_FILES = frozenset({
    "LAST_SESSION.md",
    "CURRENT_TASKS.md",
    "BACKLOG.md",
    ".harness.json",
})

_REFRESH_TEMPLATE = """\
# Last Session

## Status
IN PROGRESS

## Date
{date}

## Focus
{focus}

## Accomplished So Far
{accomplished}

## Active Specs
{active_specs}

## Current State
{current_state}

## Next
{next_items}
"""


# ---------------------------------------------------------------------------
# generate_refresh_state
# ---------------------------------------------------------------------------


def _format_bullet_list(items: List[str], fallback: str) -> str:
    """Format a list of strings as markdown bullet items.

    Args:
        items: Strings to format as bullets.
        fallback: Text to use if the list is empty.

    Returns:
        Markdown-formatted bullet list or fallback bullet.
    """
    if not items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in items)


def _extract_focus(ctx: SessionContext) -> str:
    """Extract the current focus from session context.

    Checks last_session data first, then falls back to active tasks.

    Args:
        ctx: The current SessionContext.

    Returns:
        A human-readable focus string.
    """
    if ctx.last_session:
        focus_val = ctx.last_session.get("focus", "")
        if isinstance(focus_val, str) and focus_val.strip():
            return focus_val.strip()
        if isinstance(focus_val, list) and focus_val:
            return "; ".join(str(x) for x in focus_val)

    active_tasks = ctx.current_tasks.get("active", [])
    if active_tasks:
        return active_tasks[0]

    return "Mid-session work in progress"


def generate_refresh_state(ctx: SessionContext) -> str:
    """Generate LAST_SESSION.md content with IN PROGRESS status.

    Produces a markdown document suitable for writing to LAST_SESSION.md
    during a mid-session refresh/save. The Status section is set to
    IN PROGRESS to distinguish from end-of-session summaries.

    Args:
        ctx: The current SessionContext with parsed project state.

    Returns:
        A rendered markdown string for LAST_SESSION.md.
    """
    today = date.today().isoformat()
    focus = _extract_focus(ctx)

    # Accomplished so far: completed items from current tasks
    done_items = ctx.done_items or []
    accomplished = _format_bullet_list(
        done_items, "Work in progress — no items completed yet"
    )

    # Active specs
    spec_ctx = ctx.spec_context
    if spec_ctx and spec_ctx.active_specs:
        spec_lines = [
            f"spec:{s.number} — {s.title} ({s.status})"
            for s in spec_ctx.active_specs
        ]
        active_specs_text = _format_bullet_list(spec_lines, "No active specs")
    else:
        active_specs_text = "- No active specs"

    # Current state: summarise git and task status
    state_lines: List[str] = []
    active_tasks = ctx.current_tasks.get("active", [])
    if active_tasks:
        state_lines.append(f"{len(active_tasks)} active task(s) in progress")
    if ctx.backlog_items:
        state_lines.append(f"{len(ctx.backlog_items)} backlog item(s) tracked")

    branch = getattr(ctx.git, "branch", None)
    if branch:
        state_lines.append(f"Branch: {branch}")

    modified = getattr(ctx.git, "modified", [])
    if modified:
        state_lines.append(f"{len(modified)} file(s) modified")

    current_state = _format_bullet_list(
        state_lines, "Session state captured mid-work"
    )

    # Next items: active tasks or backlog
    next_lines: List[str] = []
    for task in active_tasks[:3]:
        next_lines.append(task)
    if not next_lines:
        for item in (ctx.backlog_items or [])[:3]:
            next_lines.append(item.get("text", ""))
    next_items = _format_bullet_list(
        next_lines, "Continue current work"
    )

    return _REFRESH_TEMPLATE.format(
        date=today,
        focus=focus,
        accomplished=accomplished,
        active_specs=active_specs_text,
        current_state=current_state,
        next_items=next_items,
    )


# ---------------------------------------------------------------------------
# prepare_state_commit
# ---------------------------------------------------------------------------


def _is_state_or_spec_file(filepath: str) -> bool:
    """Determine whether a file path is a state file or spec file.

    Args:
        filepath: Relative file path from project root.

    Returns:
        True if the file is a state/session file or a spec markdown file.
    """
    basename = os.path.basename(filepath)
    if basename in _STATE_FILES:
        return True
    parts = Path(filepath).parts
    if len(parts) >= 2 and parts[0] == "specs" and filepath.endswith(".md"):
        return True
    return False


def prepare_state_commit(root: str) -> CommitPlan:
    """Prepare a commit plan that stages only specs and state files.

    Identifies modified state files (LAST_SESSION.md, CURRENT_TASKS.md,
    BACKLOG.md, .harness.json) and spec files. Code changes are
    intentionally left unstaged so that only session metadata is committed
    during a mid-session refresh.

    Args:
        root: Project root directory path.

    Returns:
        A CommitPlan with files_to_stage limited to state and spec files,
        an appropriate commit message, and has_changes flag.
    """
    root_path = Path(root)

    if not root_path.is_dir():
        return CommitPlan(files_to_stage=[], message="", has_changes=False)

    today = date.today().isoformat()
    message = f"refresh: mid-session state save {today}"

    # Non-git fallback: check file existence
    if not _is_git_repo(root):
        files_to_stage: List[str] = []
        for fname in sorted(_STATE_FILES):
            if (root_path / fname).is_file():
                files_to_stage.append(fname)
        specs_dir = root_path / "specs"
        if specs_dir.is_dir():
            try:
                for spec_file in sorted(specs_dir.rglob("*.md")):
                    if spec_file.is_file():
                        rel = str(spec_file.relative_to(root_path))
                        files_to_stage.append(rel)
            except OSError:
                pass
        return CommitPlan(
            files_to_stage=files_to_stage,
            message=message,
            has_changes=len(files_to_stage) > 0,
        )

    # Git-aware: gather changed files and filter to state/spec only
    uncommitted = _uncommitted_files(root)
    staged = _staged_files(root)
    all_changed = set(uncommitted) | set(staged)

    files_to_stage: List[str] = []
    for filepath in sorted(all_changed):
        if _is_state_or_spec_file(filepath):
            files_to_stage.append(filepath)

    # Also include state files that exist but may not show as changed
    # (e.g., newly created during this session)
    for fname in sorted(_STATE_FILES):
        if fname not in files_to_stage and (root_path / fname).is_file():
            files_to_stage.append(fname)

    spec_count = sum(1 for f in files_to_stage if Path(f).parts and Path(f).parts[0] == "specs")
    if spec_count:
        message = f"refresh: mid-session state save {today} ({spec_count} spec(s))"

    return CommitPlan(
        files_to_stage=files_to_stage,
        message=message,
        has_changes=len(files_to_stage) > 0,
    )
