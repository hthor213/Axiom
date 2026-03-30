"""Deterministic support for the maestro agent.

Provides validation, transition tracking, and diagnostic helpers that the
maestro orchestrator uses to maintain the five-file protocol, validate
milestones, and manage work-item state transitions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .parser import (
    count_current_tasks,
    extract_done_when,
    extract_spec_number,
    extract_spec_status,
    extract_spec_title,
    scan_active_specs,
)
from .scanner import build_spec_context, scan_specs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The five canonical files the maestro protocol requires at the project root.
FIVE_FILES: Dict[str, str] = {
    "README.md": "Project overview and orientation",
    "BACKLOG.md": "Prioritised work items",
    "CURRENT_TASKS.md": "Active and completed task tracking",
    "LAST_SESSION.md": "Previous session summary and next-action directives",
    "specs/": "Spec directory containing numbered spec files",
}

# Maximum number of milestones that should be active concurrently.
_MAX_ACTIVE_MILESTONES: int = 3

# Headings we recognise as milestone containers inside CURRENT_TASKS.md.
_MILESTONE_HEADING_PATTERNS: tuple[str, ...] = (
    "milestone",
    "milestones",
    "active milestone",
    "active milestones",
    "current milestone",
    "current milestones",
)

# Work-item state file mapping  (logical state -> canonical file).
_STATE_FILE_MAP: Dict[str, str] = {
    "backlog": "BACKLOG.md",
    "active": "CURRENT_TASKS.md",
    "done": "CURRENT_TASKS.md",
    "spec": "specs/",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FiveFileStatus:
    """Status of the five canonical project files.

    Attributes:
        files: Mapping of filename to a boolean indicating presence.
        all_present: ``True`` when every required file/dir exists.
        format_issues: List of human-readable format warnings.
    """

    files: Dict[str, bool] = field(default_factory=dict)
    all_present: bool = False
    format_issues: List[str] = field(default_factory=list)


@dataclass
class WorkTransition:
    """Record of a work-item transition between states.

    Attributes:
        item: Description of the work item being moved.
        from_file: Source canonical file the item was (logically) in.
        to_file: Destination canonical file the item moves to.
        spec_created: Whether a new spec file was created for this item.
        spec_ref: Spec number (e.g. ``"004"``) if a spec is associated.
    """

    item: str = ""
    from_file: str = ""
    to_file: str = ""
    spec_created: bool = False
    spec_ref: Optional[str] = None


@dataclass
class TasksValidation:
    """Validation result for CURRENT_TASKS.md.

    Attributes:
        milestone_count: Number of milestones detected in the file.
        exceeds_limit: ``True`` if milestone_count > allowed maximum.
        format_issues: List of human-readable format warnings.
        valid: ``True`` when no blocking issues were found.
    """

    milestone_count: int = 0
    exceeds_limit: bool = False
    format_issues: List[str] = field(default_factory=list)
    valid: bool = True


@dataclass
class MilestoneValidation:
    """Validation result for a single milestone description.

    Attributes:
        has_clear_scope: The milestone text describes a bounded deliverable.
        has_testable_criteria: At least one concrete, testable criterion found.
        has_verification_method: A verification / check method is mentioned.
        is_independent: The milestone doesn't depend on other incomplete work.
        issues: List of human-readable issues found during validation.
    """

    has_clear_scope: bool = False
    has_testable_criteria: bool = False
    has_verification_method: bool = False
    is_independent: bool = True
    issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_text(path: str) -> Optional[str]:
    """Read a text file, returning ``None`` on any failure."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _has_heading(text: str, level: int, pattern: str) -> bool:
    """Return ``True`` if *text* contains a heading at *level* matching *pattern*.

    Args:
        text: Markdown content.
        level: Heading level (1 for ``#``, 2 for ``##``, etc.).
        pattern: Substring to look for (case-insensitive) in the heading text.
    """
    prefix = "#" * level
    if pattern:
        regex = re.compile(
            rf"^{re.escape(prefix)}\s+.*\b{re.escape(pattern)}\b",
            re.IGNORECASE | re.MULTILINE,
        )
    else:
        regex = re.compile(
            rf"^{re.escape(prefix)}\s+.+",
            re.IGNORECASE | re.MULTILINE,
        )
    return regex.search(text) is not None


def _count_milestones_in_text(text: str) -> int:
    """Count milestone-related H2/H3 headings or top-level bullet items in
    milestone sections of CURRENT_TASKS.md content.

    Heuristic:
    - Each H2 or H3 heading containing 'milestone' starts a milestone section.
    - Bullet items directly under a recognised milestone heading each count
      as one milestone.
    - If a milestone section has no bullets, the heading itself counts as one.
    """
    lines = text.splitlines()
    total = 0
    in_milestone_section = False
    section_bullet_count = 0

    def _flush_section() -> None:
        nonlocal total, section_bullet_count
        if section_bullet_count > 0:
            total += section_bullet_count
        else:
            # The heading itself counts as one milestone
            total += 1
        section_bullet_count = 0

    for line in lines:
        stripped = line.strip()

        # Detect H2 / H3
        heading_match = re.match(r"^(#{2,3})\s+(.+)$", stripped)
        if heading_match:
            heading_text = heading_match.group(2).strip().lower()
            is_milestone_heading = any(
                p in heading_text for p in _MILESTONE_HEADING_PATTERNS
            )
            if is_milestone_heading:
                if in_milestone_section:
                    _flush_section()
                in_milestone_section = True
                section_bullet_count = 0
                continue
            else:
                if in_milestone_section:
                    _flush_section()
                    in_milestone_section = False
                continue

        # New H1 resets
        if re.match(r"^#\s+", stripped) and not re.match(r"^##", stripped):
            if in_milestone_section:
                _flush_section()
                in_milestone_section = False
            continue

        if in_milestone_section:
            bullet = re.match(r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped)
            if bullet:
                section_bullet_count += 1

    # Flush final section if we ended inside one
    if in_milestone_section:
        _flush_section()

    return total


def _validate_readme(root: str) -> List[str]:
    """Return format issues for README.md."""
    issues: List[str] = []
    text = _read_text(os.path.join(root, "README.md"))
    if text is None:
        return issues  # absence handled elsewhere

    if not text.strip():
        issues.append("README.md is empty")
        return issues

    if not re.search(r"^#\s+", text.lstrip()):
        issues.append("README.md should start with an H1 heading")

    return issues


def _validate_backlog(root: str) -> List[str]:
    """Return format issues for BACKLOG.md."""
    issues: List[str] = []
    text = _read_text(os.path.join(root, "BACKLOG.md"))
    if text is None:
        return issues

    if not text.strip():
        issues.append("BACKLOG.md is empty")
        return issues

    if not _has_heading(text, 1, ""):
        issues.append("BACKLOG.md should have an H1 title heading")

    # Should have at least one H2 section
    if not re.search(r"^##\s+", text, re.MULTILINE):
        issues.append("BACKLOG.md should have at least one H2 section for prioritised items")

    return issues


def _validate_current_tasks(root: str) -> List[str]:
    """Return format issues for CURRENT_TASKS.md."""
    issues: List[str] = []
    text = _read_text(os.path.join(root, "CURRENT_TASKS.md"))
    if text is None:
        return issues

    if not text.strip():
        issues.append("CURRENT_TASKS.md is empty")
        return issues

    has_active = _has_heading(text, 2, "active") or _has_heading(text, 2, "in progress")
    has_completed = _has_heading(text, 2, "completed") or _has_heading(text, 2, "done")

    if not has_active:
        issues.append("CURRENT_TASKS.md should have an '## Active' section")
    if not has_completed:
        issues.append("CURRENT_TASKS.md should have a '## Completed' (or '## Done') section")

    return issues


def _validate_last_session(root: str) -> List[str]:
    """Return format issues for LAST_SESSION.md."""
    issues: List[str] = []
    text = _read_text(os.path.join(root, "LAST_SESSION.md"))
    if text is None:
        return issues

    if not text.strip():
        issues.append("LAST_SESSION.md is empty")
        return issues

    has_date = _has_heading(text, 2, "date")
    has_next = any(
        _has_heading(text, 2, kw)
        for kw in ("next", "start with", "continue with")
    )

    if not has_date:
        issues.append("LAST_SESSION.md should have a '## Date' section")
    if not has_next:
        issues.append("LAST_SESSION.md should have a '## Next' (or equivalent) section")

    return issues


def _validate_specs_dir(root: str) -> List[str]:
    """Return format issues for the specs/ directory."""
    issues: List[str] = []
    specs_dir = os.path.join(root, "specs")

    if not os.path.isdir(specs_dir):
        return issues  # absence handled by the caller

    try:
        md_files = [f for f in os.listdir(specs_dir) if f.endswith(".md")]
    except OSError:
        issues.append("specs/ directory exists but cannot be read")
        return issues

    if not md_files:
        issues.append("specs/ directory contains no .md files")
        return issues

    for fname in sorted(md_files):
        number = extract_spec_number(fname)
        if not number:
            issues.append(f"specs/{fname} does not follow NNN-slug.md naming convention")
            continue

        fpath = os.path.join(specs_dir, fname)
        status = extract_spec_status(fpath)
        if status == "unknown":
            issues.append(f"specs/{fname} is missing a **Status:** line")

        done_when = extract_done_when(fpath)
        if not done_when and status in ("active", "draft"):
            issues.append(f"specs/{fname} has no Done When items (status={status})")

    return issues


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def validate_five_files(root: str) -> FiveFileStatus:
    """Validate the presence and basic format of the five canonical files.

    Checks that ``README.md``, ``BACKLOG.md``, ``CURRENT_TASKS.md``,
    ``LAST_SESSION.md``, and the ``specs/`` directory exist at *root*.
    Also performs lightweight format checks on each file.

    Args:
        root: Project root directory path.

    Returns:
        A :class:`FiveFileStatus` with per-file presence and any format
        warnings.  Degrades gracefully if *root* itself is missing.
    """
    status = FiveFileStatus()

    for name in FIVE_FILES:
        path = os.path.join(root, name)
        if name.endswith("/"):
            status.files[name] = os.path.isdir(path)
        else:
            status.files[name] = os.path.isfile(path)

    status.all_present = all(status.files.values())

    # Collect format issues from each file that exists
    status.format_issues.extend(_validate_readme(root))
    status.format_issues.extend(_validate_backlog(root))
    status.format_issues.extend(_validate_current_tasks(root))
    status.format_issues.extend(_validate_last_session(root))
    status.format_issues.extend(_validate_specs_dir(root))

    return status


def validate_current_tasks(root: str) -> TasksValidation:
    """Validate CURRENT_TASKS.md with milestone-aware checks.

    Reads the file, counts milestones, checks against the active-milestone
    limit, and collects format issues.

    Args:
        root: Project root directory path.

    Returns:
        A :class:`TasksValidation` result.
    """
    result = TasksValidation()

    tasks_path = os.path.join(root, "CURRENT_TASKS.md")
    text = _read_text(tasks_path)

    if text is None:
        result.format_issues.append("CURRENT_TASKS.md not found")
        result.valid = False
        return result

    if not text.strip():
        result.format_issues.append("CURRENT_TASKS.md is empty")
        result.valid = False
        return result

    # Count milestones
    result.milestone_count = _count_milestones_in_text(text)
    result.exceeds_limit = result.milestone_count > _MAX_ACTIVE_MILESTONES

    if result.exceeds_limit:
        result.format_issues.append(
            f"Too many active milestones: {result.milestone_count} "
            f"(limit is {_MAX_ACTIVE_MILESTONES})"
        )

    # Standard format checks
    format_issues = _validate_current_tasks(root)
    result.format_issues.extend(format_issues)

    # Count active tasks
    active_count = count_current_tasks(tasks_path)
    if active_count == 0:
        has_active = _has_heading(text, 2, "active") or _has_heading(text, 2, "in progress")
        if has_active:
            result.format_issues.append(
                "Active section exists but contains no task items"
            )

    result.valid = len(result.format_issues) == 0

    return result


def validate_milestone(milestone_text: str) -> MilestoneValidation:
    """Validate a single milestone description for quality criteria.

    Uses heuristic text analysis to determine whether the milestone has:
    - A clear, bounded scope
    - At least one testable success criterion
    - A verification method
    - Independence from other milestones

    Args:
        milestone_text: The full text of the milestone (may be multi-line).

    Returns:
        A :class:`MilestoneValidation` with boolean flags and issue list.
    """
    result = MilestoneValidation()
    text = milestone_text.strip()

    if not text:
        result.issues.append("Milestone text is empty")
        return result

    lower = text.lower()

    # --- Clear scope ---
    # A milestone with a clear scope typically:
    # - Is under ~500 chars (not a sprawling epic)
    # - Contains actionable language (implement, create, add, build, etc.)
    scope_verbs = (
        "implement", "create", "add", "build", "write", "define",
        "configure", "set up", "setup", "deploy", "migrate", "refactor",
        "extract", "integrate", "design", "update", "fix", "remove",
        "establish", "enable", "support",
    )
    has_verb = any(re.search(rf'\b{re.escape(v)}\b', lower) for v in scope_verbs)
    is_bounded = len(text) < 500

    result.has_clear_scope = has_verb and is_bounded
    if not has_verb:
        result.issues.append(
            "Milestone lacks actionable language (e.g. implement, create, build)"
        )
    if not is_bounded:
        result.issues.append(
            "Milestone description is too long (>500 chars); consider splitting"
        )

    # --- Testable criteria ---
    # Look for patterns that indicate measurable / verifiable outcomes:
    # - checklist items (- [ ])
    # - "should", "must", "returns", "passes", "exists"
    # - backtick-wrapped file paths or commands
    # - numeric thresholds
    testable_patterns = [
        r"-\s+\[[ xX]\]",          # checklist items
        r"\b(?:should|must|shall)\b",  # requirement language
        r"\b(?:returns?|passes?|exists?|contains?)\b",  # verifiable actions
        r"`[^`]+`",                 # backtick references (files, commands)
        r"\b\d+\s*%",              # percentage thresholds
        r"(?:at least|at most|exactly|no more than)\s+\d+",  # numeric bounds
    ]
    has_testable = any(
        re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        for pat in testable_patterns
    )
    result.has_testable_criteria = has_testable
    if not has_testable:
        result.issues.append(
            "No testable success criteria found; add checklist items or "
            "measurable outcomes"
        )

    # --- Verification method ---
    # Look for mentions of how to verify: test, check, run, verify, confirm,
    # pytest, CI, review
    verification_keywords = (
        "test", "check", "verify", "confirm", "run", "pytest",
        "ci", "review", "validate", "assert", "inspect", "demo",
        "spec_check", "gate",
    )
    has_verification = any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in verification_keywords)
    result.has_verification_method = has_verification
    if not has_verification:
        result.issues.append(
            "No verification method mentioned; describe how completion "
            "will be checked"
        )

    # --- Independence ---
    # Look for explicit dependency markers that suggest coupling.
    dependency_patterns = [
        r"\b(?:depends on|blocked by|requires completion of|after milestone)\b",
        r"\b(?:prerequisite|dependency)\b",
        r"(?:waiting|wait) (?:for|on)\b",
    ]
    has_dependency = any(
        re.search(pat, text, re.IGNORECASE)
        for pat in dependency_patterns
    )
    result.is_independent = not has_dependency
    if has_dependency:
        result.issues.append(
            "Milestone appears to depend on other work; prefer independent milestones"
        )

    return result


def transition_work_item(
    root: str,
    item: str,
    from_state: str,
    to_state: str,
) -> WorkTransition:
    """Record and validate a work-item state transition.

    Determines the canonical source and destination files based on the
    logical state names (``backlog``, ``active``, ``done``, ``spec``).
    If *to_state* is ``"spec"``, checks whether an appropriate spec file
    already exists or notes that one should be created.

    This function does **not** mutate any files — it returns a
    :class:`WorkTransition` describing what should happen.  File mutations
    are the caller's responsibility.

    Args:
        root: Project root directory path.
        item: Human-readable description of the work item.
        from_state: Logical state the item is currently in.
        to_state: Logical state the item should move to.

    Returns:
        A :class:`WorkTransition` describing the transition.
    """
    from_file = _STATE_FILE_MAP.get(from_state, from_state)
    to_file = _STATE_FILE_MAP.get(to_state, to_state)

    transition = WorkTransition(
        item=item,
        from_file=from_file,
        to_file=to_file,
    )

    # If moving to spec, figure out the next spec number and whether one
    # already covers this item.
    if to_state == "spec":
        specs_dir = os.path.join(root, "specs")
        transition.spec_created = False

        if os.path.isdir(specs_dir):
            # Look for an existing spec whose title roughly matches the item
            existing_ref = _find_matching_spec(specs_dir, item)
            if existing_ref:
                transition.spec_ref = existing_ref
                transition.spec_created = False
            else:
                # Determine next available spec number
                next_num = _next_spec_number(specs_dir)
                transition.spec_ref = next_num
                transition.spec_created = True
        else:
            transition.spec_ref = "001"
            transition.spec_created = True

    return transition


def count_active_milestones(root: str) -> int:
    """Count the number of active milestones in CURRENT_TASKS.md.

    Args:
        root: Project root directory path.

    Returns:
        Integer count of detected milestones.  Returns ``0`` if the file
        is missing or contains no milestone sections.
    """
    tasks_path = os.path.join(root, "CURRENT_TASKS.md")
    text = _read_text(tasks_path)
    if text is None:
        return 0
    return _count_milestones_in_text(text)


def diagnose_failure_type(task_result: str, success_criteria: str) -> str:
    """Classify a task failure into a diagnostic category.

    Analyses the *task_result* text against the *success_criteria* to
    determine the most likely failure mode.  This is a deterministic
    heuristic — no LLM calls.

    Categories returned:
        ``"missing_file"``
            A required file or artifact was not created.
        ``"wrong_content"``
            A file exists but doesn't contain the expected content.
        ``"test_failure"``
            Tests ran but produced failures or errors.
        ``"incomplete"``
            Work was started but not finished; partial progress evident.
        ``"blocked"``
            External dependency or prerequisite prevented completion.
        ``"scope_mismatch"``
            The work done doesn't align with what was asked for.
        ``"unknown"``
            Could not determine the failure type from available information.

    Args:
        task_result: Description of what happened (output, error messages,
            or human summary).
        success_criteria: What was expected to be true on success.

    Returns:
        A string category name from the list above.
    """
    result_lower = task_result.lower().strip()
    criteria_lower = success_criteria.lower().strip()

    if not result_lower:
        return "unknown"

    # --- missing_file ---
    missing_file_patterns = [
        r"file\s+not\s+found",
        r"no such file",
        r"(?:file|directory|path|module)\s+(?:does not|doesn't) exist",
        r"missing\s+file",
        r"filenotfounderror",
        r"enoent",
        r"(?:file|directory|path)\s+.*not\s+found",
    ]
    for pat in missing_file_patterns:
        if re.search(pat, result_lower):
            return "missing_file"

    # --- test_failure ---
    test_failure_patterns = [
        r"\bfailed\b.*\btest",
        r"\btest.*\bfailed\b",
        r"\berror.*\btest",
        r"\btest.*\berror\b",
        r"\bassert(?:ion)?(?:error)?\b",
        r"\bpytest\b",
        r"\bfailure\b.*\btest",
        r"\btest.*\bfailure\b",
        r"\d+\s+failed",
        r"FAILED",
        r"traceback",
    ]
    for pat in test_failure_patterns:
        if re.search(pat, result_lower):
            return "test_failure"

    # --- blocked ---
    blocked_patterns = [
        r"\bblocked\b",
        r"\bwaiting\b",
        r"\bdepends on\b",
        r"\bprerequisite\b",
        r"\bcannot proceed\b",
        r"\bpermission denied\b",
        r"\baccess denied\b",
        r"\btimeout\b",
        r"\bconnection refused\b",
        r"\brate limit\b",
    ]
    for pat in blocked_patterns:
        if re.search(pat, result_lower):
            return "blocked"

    # --- wrong_content ---
    wrong_content_patterns = [
        r"(?:not contain|doesn't contain|does not contain)",
        r"(?:wrong|incorrect|unexpected)\s+(?:content|output|value|result)",
        r"(?:pattern|string|text)\s+not\s+found",
        r"(?:mismatch|differ)",
        r"expected\b.*\bbut\b.*\b(?:got|found|was)\b",
    ]
    for pat in wrong_content_patterns:
        if re.search(pat, result_lower):
            return "wrong_content"

    # --- scope_mismatch ---
    scope_patterns = [
        r"\bwrong\s+(?:spec|task|scope|file)\b",
        r"\bscope\b.*\bmismatch\b",
        r"\bnot\s+(?:what was|the)\s+(?:asked|requested|expected)\b",
        r"\bunrelated\b",
        r"\bout of scope\b",
    ]
    for pat in scope_patterns:
        if re.search(pat, result_lower):
            return "scope_mismatch"

    # --- incomplete ---
    incomplete_patterns = [
        r"\bpartial\b",
        r"\bincomplete\b",
        r"\bnot\s+finished\b",
        r"\bwork\s+in\s+progress\b",
        r"\bwip\b",
        r"\btodo\b",
        r"\bremaining\b",
        r"\bstill\s+need",
        r"\bnot\s+(?:all|fully|completely)\b",
    ]
    for pat in incomplete_patterns:
        if re.search(pat, result_lower):
            return "incomplete"

    # --- Check criteria for file-existence hints if result doesn't help ---
    if re.search(r"\bexists?\b", criteria_lower):
        # The criterion wants a file to exist and we haven't matched above
        if any(kw in result_lower for kw in ("false", "fail", "no", "missing")):
            return "missing_file"

    if re.search(r"\bcontains?\b", criteria_lower):
        if any(kw in result_lower for kw in ("false", "fail", "no")):
            return "wrong_content"

    return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers for transition_work_item
# ---------------------------------------------------------------------------


def _find_matching_spec(specs_dir: str, item_description: str) -> Optional[str]:
    """Find an existing spec whose title is a close match to *item_description*.

    Uses a simple word-overlap heuristic.  Returns the spec number string
    (e.g. ``"003"``) or ``None`` if no good match is found.
    """
    item_words = set(re.findall(r"[a-z]+", item_description.lower()))
    if not item_words:
        return None

    # Filter out very common words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "for", "on", "with", "and", "or", "not",
        "it", "this", "that", "from", "by", "as", "at", "but",
    }
    item_words -= stop_words

    if not item_words:
        return None

    best_match: Optional[str] = None
    best_score: float = 0.0

    try:
        entries = sorted(os.listdir(specs_dir))
    except OSError:
        return None

    for fname in entries:
        if not fname.endswith(".md"):
            continue
        number = extract_spec_number(fname)
        if not number:
            continue

        fpath = os.path.join(specs_dir, fname)
        title = extract_spec_title(fpath)
        if not title:
            continue

        title_words = set(re.findall(r"[a-z]+", title.lower())) - stop_words
        if not title_words:
            continue

        # Jaccard similarity
        intersection = item_words & title_words
        union = item_words | title_words
        score = len(intersection) / len(union) if union else 0.0

        if score > best_score and score >= 0.4:
            best_score = score
            best_match = number

    return best_match


def _next_spec_number(specs_dir: str) -> str:
    """Determine the next available spec number in NNN format.

    Scans existing spec files and returns one higher than the maximum
    found, zero-padded to three digits.
    """
    max_num = 0

    try:
        entries = os.listdir(specs_dir)
    except OSError:
        return "001"

    for fname in entries:
        if not fname.endswith(".md"):
            continue
        number = extract_spec_number(fname)
        if number:
            try:
                n = int(number)
                if n > max_num:
                    max_num = n
            except ValueError:
                continue

    return f"{max_num + 1:03d}"
