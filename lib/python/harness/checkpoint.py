"""Checkpoint operations for end-of-session.

Provides dataclasses and functions for checking invariants, generating
session summaries, updating backlogs, cleaning up artifacts, and
preparing git commits at the end of a session.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .git_ops import GitStatus, gather_status, stage_files, _staged_files, _uncommitted_files, _is_git_repo
from .parser import extract_done_when, extract_spec_status, scan_active_specs
from .scanner import build_spec_context, SpecContext
from .session import SessionContext, parse_backlog, parse_last_session
from .spec_check import classify_done_when, run_check


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InvariantResult:
    """Result of checking a single invariant.

    Attributes:
        invariant: The invariant text being checked.
        status: One of 'pass', 'fail', or 'skip'.
        check_type: The type of check performed (e.g. 'file_exists',
            'grep', 'spec_status', 'judgment').
        evidence: Human-readable evidence or reason for the status.
    """

    invariant: str
    status: str  # 'pass', 'fail', 'skip'
    check_type: str
    evidence: str


@dataclass
class BacklogDiff:
    """Summary of changes made to the backlog.

    Attributes:
        moved_to_done: Items moved from active/backlog to done.
        new_items: Newly added backlog items.
        reprioritized: Items whose priority changed.
    """

    moved_to_done: List[str] = field(default_factory=list)
    new_items: List[str] = field(default_factory=list)
    reprioritized: List[str] = field(default_factory=list)


@dataclass
class CommitPlan:
    """Plan for a git commit at checkpoint time.

    Attributes:
        files_to_stage: List of file paths (relative to root) to stage.
        message: The commit message to use.
        has_changes: Whether there are actual changes to commit.
    """

    files_to_stage: List[str] = field(default_factory=list)
    message: str = ""
    has_changes: bool = False


# ---------------------------------------------------------------------------
# Artifact patterns to clean up
# ---------------------------------------------------------------------------

_ARTIFACT_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
    ".screenshot", ".tmp", ".bak", ".swp", ".swo",
    ".pyc", ".pyo",
})

_ARTIFACT_PATTERNS = [
    re.compile(r"^screenshot[-_]", re.IGNORECASE),
    re.compile(r"^\.DS_Store$"),
    re.compile(r"^Thumbs\.db$", re.IGNORECASE),
    re.compile(r"^~\$"),  # Office lock files
    re.compile(r"\.orig$"),
    re.compile(r"^__pycache__$"),
]


# ---------------------------------------------------------------------------
# Invariant checking
# ---------------------------------------------------------------------------


def _classify_invariant(text: str) -> dict:
    """Classify an invariant string into a check item compatible with spec_check.

    Wraps the invariant text into the dict format expected by
    ``classify_done_when`` and returns the classified result.

    Args:
        text: The invariant text.

    Returns:
        A classified item dict with check_type and check_args.
    """
    item = {"text": text, "checked": False, "raw_line": f"- [ ] {text}"}
    return classify_done_when(item)


def check_automatable_invariants(
    root: str,
    invariants: List[str],
) -> List[InvariantResult]:
    """Check a list of invariant strings against the project.

    Each invariant is classified using the spec_check classifier. Automatable
    invariants (file_exists, grep, spec_status, command) are executed.
    Judgment invariants are returned with status 'skip'.

    Args:
        root: Project root directory path.
        invariants: List of invariant description strings.

    Returns:
        List of InvariantResult for each invariant.
    """
    results: List[InvariantResult] = []

    for inv_text in invariants:
        classified = _classify_invariant(inv_text)
        check_type = classified.get("check_type", "judgment")

        if check_type == "judgment":
            results.append(InvariantResult(
                invariant=inv_text,
                status="skip",
                check_type="judgment",
                evidence="Requires human or LLM judgment — not automatable.",
            ))
            continue

        # Run the automatable check
        executed = run_check(classified, root)
        result_value = executed.get("result")
        error = executed.get("error")

        if result_value is True:
            results.append(InvariantResult(
                invariant=inv_text,
                status="pass",
                check_type=check_type,
                evidence=f"Check passed for: {inv_text}",
            ))
        elif result_value is False:
            results.append(InvariantResult(
                invariant=inv_text,
                status="fail",
                check_type=check_type,
                evidence=error or f"Check failed for: {inv_text}",
            ))
        else:
            results.append(InvariantResult(
                invariant=inv_text,
                status="skip",
                check_type=check_type,
                evidence="Check returned no result.",
            ))

    return results


# ---------------------------------------------------------------------------
# Session summary generation
# ---------------------------------------------------------------------------

_SESSION_TEMPLATE = """\
# Last Session

## Date
{date}

## Focus
{focus}

## Accomplishments
{accomplishments}

## Invariant Check Summary
{invariant_summary}

## Active Specs
{active_specs}

## Next
{next_items}
"""


def generate_session_summary(
    ctx: SessionContext,
    accomplishments: List[str],
) -> str:
    """Generate a LAST_SESSION.md summary from session context and accomplishments.

    Produces a markdown document suitable for writing to LAST_SESSION.md
    at the end of a session.

    Args:
        ctx: The current SessionContext.
        accomplishments: List of accomplishment description strings.

    Returns:
        A rendered markdown string for LAST_SESSION.md.
    """
    today = date.today().isoformat()

    # Determine focus from context
    focus = ""
    if ctx.last_session:
        focus_val = ctx.last_session.get("focus", "")
        if isinstance(focus_val, str):
            focus = focus_val
        elif isinstance(focus_val, list):
            focus = "; ".join(focus_val)
    if not focus:
        # Fall back to first active task
        active_tasks = ctx.current_tasks.get("active", [])
        if active_tasks:
            focus = active_tasks[0]
        else:
            focus = "Session work"

    # Format accomplishments
    if accomplishments:
        accomplishments_text = "\n".join(f"- {a}" for a in accomplishments)
    else:
        accomplishments_text = "- No accomplishments recorded"

    # Invariant summary
    spec_ctx = ctx.spec_context
    if spec_ctx and spec_ctx.invariants:
        inv_lines = []
        for inv in spec_ctx.invariants:
            inv_lines.append(f"- {inv}")
        invariant_summary = "\n".join(inv_lines)
    else:
        invariant_summary = "- No invariants defined"

    # Active specs
    if spec_ctx and spec_ctx.active_specs:
        spec_lines = []
        for s in spec_ctx.active_specs:
            spec_lines.append(f"- spec:{s.number} — {s.title} ({s.status})")
        active_specs_text = "\n".join(spec_lines)
    else:
        active_specs_text = "- No active specs"

    # Next items from backlog or current tasks
    next_lines: List[str] = []
    active_tasks = ctx.current_tasks.get("active", [])
    if active_tasks:
        for task in active_tasks[:3]:
            next_lines.append(f"- {task}")

    if not next_lines:
        # Try backlog
        for item in ctx.backlog_items[:3]:
            next_lines.append(f"- {item.get('text', '')}")

    if not next_lines:
        next_lines.append("- Review project goals and plan next steps")

    next_text = "\n".join(next_lines)

    return _SESSION_TEMPLATE.format(
        date=today,
        focus=focus,
        accomplishments=accomplishments_text,
        invariant_summary=invariant_summary,
        active_specs=active_specs_text,
        next_items=next_text,
    )


# ---------------------------------------------------------------------------
# Backlog update
# ---------------------------------------------------------------------------


def update_backlog(
    root: str,
    completed: List[str],
    new_items: List[str],
) -> BacklogDiff:
    """Update BACKLOG.md by removing completed items and adding new ones.

    Reads the current BACKLOG.md, removes lines matching completed item
    descriptions (including any child lines indented beneath them), appends
    new items to the Priorities section, and writes the updated file back.

    Args:
        root: Project root directory.
        completed: List of item descriptions that have been completed.
        new_items: List of new item descriptions to add.

    Returns:
        A BacklogDiff summarizing the changes made.
    """
    diff = BacklogDiff()
    backlog_path = os.path.join(root, "BACKLOG.md")

    try:
        content = Path(backlog_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # No backlog file — create one if we have new items
        if new_items:
            lines = ["# BACKLOG\n", "\n", "## Priorities\n"]
            for item in new_items:
                lines.append(f"- {item}\n")
                diff.new_items.append(item)
            lines.append("\n")
            Path(backlog_path).parent.mkdir(parents=True, exist_ok=True)
            Path(backlog_path).write_text("".join(lines), encoding="utf-8")
        return diff

    original_lines = content.splitlines(keepends=True)
    output_lines: List[str] = []

    # Normalize completed items for matching
    completed_lower = {c.strip().lower() for c in completed if c.strip()}

    # Track where to insert new items (after ## Priorities heading)
    priorities_insert_idx: Optional[int] = None

    # Track indentation level for skipping children of removed items
    skip_indent: Optional[int] = None

    for i, line in enumerate(original_lines):
        stripped = line.strip()

        # If we're skipping children of a removed item, check indentation
        if skip_indent is not None:
            # Calculate leading whitespace
            leading = len(line) - len(line.lstrip())
            if leading > skip_indent or (leading == skip_indent and not re.match(r'^[-*+]\s', stripped)):
                continue  # Skip child line
            else:
                skip_indent = None  # Done skipping children

        # Check if this is a bullet that matches a completed item
        bullet_match = re.match(r"^([-*+]\s+)(?:\[[ xX]\]\s+)?(.+)$", stripped)
        if bullet_match and completed_lower:
            item_text = bullet_match.group(2).strip().lower()
            if item_text in completed_lower:
                diff.moved_to_done.append(bullet_match.group(2).strip())
                completed_lower.discard(item_text)
                skip_indent = len(line) - len(line.lstrip())
                continue  # Skip this line (remove from backlog)

        output_lines.append(line)

        # Detect ## Priorities heading for insertion point
        if re.match(r"^##\s+Priorities?\b", stripped, re.IGNORECASE):
            priorities_insert_idx = len(output_lines)

    # Insert new items after Priorities heading
    if new_items:
        insert_idx = priorities_insert_idx if priorities_insert_idx is not None else len(output_lines)
        new_lines: List[str] = []
        for item in new_items:
            new_lines.append(f"- {item}\n")
            diff.new_items.append(item)
        for i, nl in enumerate(new_lines):
            output_lines.insert(insert_idx + i, nl)

    # Write back
    Path(backlog_path).write_text("".join(output_lines), encoding="utf-8")

    return diff


# ---------------------------------------------------------------------------
# Artifact cleanup
# ---------------------------------------------------------------------------


def _is_artifact(name: str) -> bool:
    """Determine whether a filename looks like a temporary artifact.

    Args:
        name: The filename (not full path).

    Returns:
        True if the file matches artifact patterns.
    """
    # Check extension
    _, ext = os.path.splitext(name)
    if ext.lower() in _ARTIFACT_EXTENSIONS:
        return True

    # Check name patterns
    for pattern in _ARTIFACT_PATTERNS:
        if pattern.search(name):
            return True

    return False


def cleanup_artifacts(root: str) -> List[str]:
    """Remove temporary artifacts from the project root.

    Scans the root directory for files matching known artifact patterns
    (screenshots, temp files, OS metadata, etc.) and removes them.
    Also recursively removes __pycache__ directories.

    Args:
        root: Project root directory.

    Returns:
        List of removed file paths (relative to root).
    """
    removed: List[str] = []
    root_path = Path(root)

    if not root_path.is_dir():
        return removed

    # Recursively remove __pycache__ directories
    try:
        for pycache_dir in list(root_path.rglob('__pycache__')):
            if pycache_dir.is_dir() and not pycache_dir.is_symlink():
                try:
                    shutil.rmtree(pycache_dir, ignore_errors=True)
                    removed.append(str(pycache_dir.relative_to(root_path)))
                except OSError:
                    pass
    except OSError:
        pass

    # Scan root directory (non-recursively) for artifact files
    try:
        entries = list(root_path.iterdir())
    except OSError:
        return removed

    for entry in entries:
        if not entry.is_file():
            continue

        if _is_artifact(entry.name):
            try:
                entry.unlink()
                removed.append(entry.name)
            except OSError:
                pass

    return removed


def _rmtree_simple(path: Path) -> None:
    """Remove a directory tree safely.

    Args:
        path: Directory to remove recursively.
    """
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Commit preparation
# ---------------------------------------------------------------------------

# Files that are typically relevant for checkpoint commits
_CHECKPOINT_FILES = [
    "LAST_SESSION.md",
    "CURRENT_TASKS.md",
    "BACKLOG.md",
    ".harness.json",
]


def prepare_commit(root: str, message_prefix: str = "") -> CommitPlan:
    """Prepare a git commit plan for the checkpoint.

    Identifies which tracked/modified files should be staged and builds
    an appropriate commit message. Does NOT actually stage or commit —
    the caller should use git_ops.stage_files and git_ops.create_commit.

    Includes session files (LAST_SESSION.md, CURRENT_TASKS.md, BACKLOG.md,
    .harness.json) and any modified spec files.

    Args:
        root: Project root directory.
        message_prefix: Optional prefix for the commit message. If empty,
            defaults to 'checkpoint'.

    Returns:
        A CommitPlan with the files to stage, message, and whether
        there are changes.
    """
    root_path = Path(root)

    if not root_path.is_dir():
        return CommitPlan(
            files_to_stage=[],
            message="",
            has_changes=False,
        )

    # Check if this is a git repo
    if not _is_git_repo(root):
        # Not a git repo — return plan based on file existence
        files_to_stage: List[str] = []
        for fname in _CHECKPOINT_FILES:
            fpath = root_path / fname
            if fpath.is_file():
                files_to_stage.append(fname)

        # Include modified specs
        specs_dir = root_path / "specs"
        if specs_dir.is_dir():
            try:
                for spec_file in sorted(specs_dir.iterdir()):
                    if spec_file.suffix == ".md" and spec_file.is_file():
                        files_to_stage.append(str(spec_file.relative_to(root_path)))
            except OSError:
                pass

        prefix = message_prefix.strip() if message_prefix.strip() else "checkpoint"
        today = date.today().isoformat()
        message = f"{prefix}: session {today}"

        return CommitPlan(
            files_to_stage=files_to_stage,
            message=message,
            has_changes=len(files_to_stage) > 0,
        )

    # Gather git status to find modified files
    uncommitted = _uncommitted_files(root)
    staged = _staged_files(root)

    # Combine all changed files
    all_changed = set(uncommitted) | set(staged)

    files_to_stage: List[str] = []

    # Always include checkpoint files if they exist and are changed
    for fname in _CHECKPOINT_FILES:
        fpath = root_path / fname
        if fpath.is_file():
            if fname in all_changed:
                files_to_stage.append(fname)

    # Include any changed spec files
    for changed_file in sorted(all_changed):
        if changed_file.startswith("specs/") and changed_file.endswith(".md"):
            if changed_file not in files_to_stage:
                files_to_stage.append(changed_file)

    # Include other changed session-relevant files
    for changed_file in sorted(all_changed):
        if changed_file in files_to_stage:
            continue
        # Include files that look session-relevant
        if changed_file.endswith(".md") or changed_file == ".harness.json":
            files_to_stage.append(changed_file)

    # Build commit message
    prefix = message_prefix.strip() if message_prefix.strip() else "checkpoint"
    today = date.today().isoformat()

    # Count spec changes for a more descriptive message
    spec_changes = [f for f in files_to_stage if f.startswith("specs/")]
    if spec_changes:
        message = f"{prefix}: session {today} ({len(spec_changes)} spec(s) updated)"
    else:
        message = f"{prefix}: session {today}"

    has_changes = len(files_to_stage) > 0

    return CommitPlan(
        files_to_stage=files_to_stage,
        message=message,
        has_changes=has_changes,
    )
