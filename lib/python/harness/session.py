"""Session context reading and priority resolution.

Provides dataclasses and functions for reading session context from a project
directory, parsing LAST_SESSION.md and BACKLOG.md, and resolving the next
action based on priority ordering.

Priority resolution order:
    1. LAST_SESSION.md "Next Session Should Start With" / "Next" section
    2. CURRENT_TASKS.md active items
    3. BACKLOG.md P0 items
    4. BACKLOG.md next priority tier (P1, P2, P3)
    5. Active specs from spec context
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .git_ops import GitStatus, gather_status
from .scanner import SpecContext, build_spec_context


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Full session context assembled from project root files and git state.

    Attributes:
        last_session: Parsed sections from LAST_SESSION.md as a dict of
            section_name -> content (string or list of strings).
        current_tasks: Dict with 'active' and 'completed' keys, each a list
            of task description strings.
        backlog_items: List of dicts, each with 'priority' (str like 'P0'),
            'text' (str), and 'section' (str, the raw heading text).
        done_items: List of task strings from the Completed section of
            CURRENT_TASKS.md.
        git: GitStatus snapshot of the repository.
        spec_context: SpecContext built from the specs/ directory.
    """

    last_session: Dict[str, object] = field(default_factory=dict)
    current_tasks: Dict[str, List[str]] = field(default_factory=dict)
    backlog_items: List[Dict[str, str]] = field(default_factory=list)
    done_items: List[str] = field(default_factory=list)
    git: GitStatus = field(default_factory=GitStatus)
    spec_context: SpecContext = field(default_factory=lambda: SpecContext(vision=None))


@dataclass
class NextAction:
    """Resolved next action with source provenance and reasoning.

    Attributes:
        source: Where this action was derived from, e.g.
            'last_session', 'current_tasks', 'backlog_p0', 'backlog',
            'active_spec', or 'none'.
        description: Human-readable description of what to do next.
        spec_ref: Optional spec reference (e.g. '001') if the action
            relates to a specific spec.
        needs_spec: Whether this action requires consulting a spec file
            for more detail.
        reasoning: Explanation of why this action was chosen.
    """

    source: str = "none"
    description: str = ""
    spec_ref: Optional[str] = None
    needs_spec: bool = False
    reasoning: str = ""


# ---------------------------------------------------------------------------
# LAST_SESSION.md parser
# ---------------------------------------------------------------------------

# Heading patterns we recognise as the "next action" indicator.
_NEXT_SESSION_HEADINGS = (
    "next session should start with",
    "next session",
    "next",
    "start with",
    "continue with",
)


def parse_last_session(path: str) -> Dict[str, object]:
    """Parse LAST_SESSION.md into a dict of section_name -> content.

    Recognises H1 and H2 headings.  Content under each heading is collected
    as either a single string (for short scalar sections like Date) or a
    list of bullet-item strings.

    Sections with only bullet items get a ``list[str]`` value.
    Sections with only plain text get a ``str`` value.
    Mixed sections get a ``str`` value with the full text block.

    The special key ``'_raw'`` holds the entire file content.

    Args:
        path: Filesystem path to LAST_SESSION.md.

    Returns:
        Dict mapping lowercased section names to their content.
        Returns an empty dict (with no ``'_raw'`` key) if the file is
        missing or unreadable.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    result: Dict[str, object] = {"_raw": text}
    lines = text.splitlines()

    current_heading: Optional[str] = None
    current_lines: List[str] = []

    def _flush() -> None:
        """Flush accumulated lines into the result dict."""
        nonlocal current_heading, current_lines
        if current_heading is None:
            return

        key = current_heading.lower().strip()
        if not key:
            return

        # Determine whether the section is all bullets, all prose, or mixed
        bullet_items: List[str] = []
        prose_lines: List[str] = []

        for ln in current_lines:
            stripped = ln.strip()
            m = re.match(r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped)
            if m:
                bullet_items.append(m.group(1).strip())
            elif stripped:
                prose_lines.append(stripped)

        if bullet_items and not prose_lines:
            result[key] = bullet_items
        elif not bullet_items and prose_lines:
            result[key] = "\n".join(prose_lines)
        elif bullet_items and prose_lines:
            # Mixed — store both but primary value is the full block
            result[key] = "\n".join(
                ln.strip() for ln in current_lines if ln.strip()
            )
            # Also store bullets under a helper key
            result[key + "_items"] = bullet_items
        else:
            result[key] = ""

        current_heading = None
        current_lines = []

    for line in lines:
        stripped = line.strip()

        # Detect H1 or H2
        heading_match = re.match(r"^(#{1,2})\s+(.+)$", stripped)
        if heading_match:
            _flush()
            current_heading = heading_match.group(2).strip()
            current_lines = []
            continue

        if current_heading is not None:
            current_lines.append(line)

    # Flush the last section
    _flush()

    return result


def _extract_next_items_from_session(session: Dict[str, object]) -> List[str]:
    """Extract "next action" items from a parsed last-session dict.

    Looks for sections whose heading matches one of the known next-session
    heading patterns.

    Returns:
        List of action description strings.  May be empty.
    """
    for heading_pattern in _NEXT_SESSION_HEADINGS:
        for key, value in session.items():
            if key.startswith("_"):
                continue
            if heading_pattern in key.lower():
                # Prefer the parsed _items list if it exists (mixed sections)
                items_key = f"{key}_items"
                if items_key in session:
                    return list(session[items_key])
                if isinstance(value, list):
                    return list(value)
                if isinstance(value, str) and value.strip():
                    # Split multi-line prose into individual items
                    items = [
                        ln.strip() for ln in value.strip().splitlines()
                        if ln.strip()
                    ]
                    return items
    return []


# ---------------------------------------------------------------------------
# BACKLOG.md parser
# ---------------------------------------------------------------------------

# Priority heading patterns.  We look for H2 headings that match P0–P3
# or well-known synonyms.
_PRIORITY_MAP: Dict[str, str] = {
    "p0": "P0",
    "p1": "P1",
    "p2": "P2",
    "p3": "P3",
    "critical": "P0",
    "urgent": "P0",
    "high": "P1",
    "priorities": "P1",
    "medium": "P2",
    "low": "P3",
    "icebox": "P3",
    "someday": "P3",
    "backlog": "P2",
}


def _classify_priority(heading: str) -> str:
    """Map a section heading to a priority level string.

    Args:
        heading: Raw heading text (without the ``##`` prefix).

    Returns:
        One of 'P0', 'P1', 'P2', 'P3', or 'P2' as default.
    """
    lower = heading.lower().strip()

    # Direct P0-P3 match anywhere in the heading
    m = re.search(r"\b(p[0-3])\b", lower)
    if m:
        return m.group(1).upper()

    # Check known synonyms with word boundary matching
    for keyword, priority in _PRIORITY_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lower):
            return priority

    # Default to P2 for unrecognised sections
    return "P2"


def parse_backlog(path: str) -> List[Dict[str, str]]:
    """Parse BACKLOG.md into a list of prioritised backlog items.

    Recognises H2 sections and maps them to priority levels (P0–P3) based
    on heading text.  Each bullet item under a section becomes a dict with:

    - ``priority``: str like 'P0', 'P1', 'P2', 'P3'
    - ``text``: The item description (leading ``- `` stripped)
    - ``section``: The raw section heading text

    Items are returned in file order, which typically means highest-priority
    sections appear first.

    Args:
        path: Filesystem path to BACKLOG.md.

    Returns:
        List of item dicts.  Returns an empty list if the file is missing,
        unreadable, or contains no recognisable sections.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    items: List[Dict[str, str]] = []
    lines = text.splitlines()

    current_section: Optional[str] = None
    current_priority: str = "P2"

    for line in lines:
        stripped = line.strip()

        # Detect H1 — skip, just a title
        if re.match(r"^#\s+", stripped) and not re.match(r"^##\s+", stripped):
            current_section = None
            continue

        # Detect H2 — new section
        h2_match = re.match(r"^##\s+(.+)$", stripped)
        if h2_match:
            current_section = h2_match.group(1).strip()
            current_priority = _classify_priority(current_section)
            continue

        # Collect bullet items
        if current_section is not None:
            bullet_match = re.match(
                r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped
            )
            if bullet_match:
                item_text = bullet_match.group(1).strip()
                items.append({
                    "priority": current_priority,
                    "text": item_text,
                    "section": current_section,
                })
            elif stripped and items and items[-1]["section"] == current_section:
                # Continuation line for multi-line bullet
                items[-1]["text"] += f" {stripped}"

    return items


# ---------------------------------------------------------------------------
# CURRENT_TASKS.md parser
# ---------------------------------------------------------------------------


def _parse_current_tasks(path: str) -> Dict[str, List[str]]:
    """Parse CURRENT_TASKS.md into active and completed task lists.

    Looks for H2 sections named ``Active`` (or ``In Progress``, ``Current``)
    and ``Completed`` (or ``Done``, ``Finished``).

    Args:
        path: Filesystem path to CURRENT_TASKS.md.

    Returns:
        Dict with keys ``'active'`` and ``'completed'``, each mapping to
        a list of task description strings.  Returns empty lists if file
        is missing or sections are not found.
    """
    result: Dict[str, List[str]] = {"active": [], "completed": []}

    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return result

    lines = text.splitlines()
    current_bucket: Optional[str] = None

    _active_headings = {"active", "in progress", "current", "todo", "to do"}
    _completed_headings = {"completed", "done", "finished", "closed"}

    for line in lines:
        stripped = line.strip()

        h2_match = re.match(r"^##\s+(.+)$", stripped)
        if h2_match:
            heading_lower = h2_match.group(1).strip().lower()
            if any(kw in heading_lower for kw in _active_headings):
                current_bucket = "active"
            elif any(kw in heading_lower for kw in _completed_headings):
                current_bucket = "completed"
            else:
                current_bucket = None
            continue

        # A new H1 resets
        if re.match(r"^#\s+", stripped) and not re.match(r"^##", stripped):
            current_bucket = None
            continue

        if current_bucket is not None:
            bullet_match = re.match(
                r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped
            )
            if bullet_match:
                result[current_bucket].append(bullet_match.group(1).strip())
            elif stripped and result[current_bucket]:
                # Continuation line for multi-line bullet
                result[current_bucket][-1] += f" {stripped}"

    return result


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def read_session_context(root: str) -> SessionContext:
    """Read and assemble a complete SessionContext from a project root.

    Gathers information from:
    - ``LAST_SESSION.md`` — parsed into sections
    - ``CURRENT_TASKS.md`` — active and completed task lists
    - ``BACKLOG.md`` — prioritised backlog items
    - Git status via ``git_ops.gather_status``
    - Spec context via ``scanner.build_spec_context``

    All file reads degrade gracefully — missing files produce empty defaults
    rather than exceptions.

    Args:
        root: Path to the project root directory.

    Returns:
        A fully populated SessionContext dataclass.
    """
    root_path = Path(root)

    # Parse LAST_SESSION.md
    last_session_path = str(root_path / "LAST_SESSION.md")
    last_session = parse_last_session(last_session_path)

    # Parse CURRENT_TASKS.md
    tasks_path = str(root_path / "CURRENT_TASKS.md")
    tasks = _parse_current_tasks(tasks_path)

    # Parse BACKLOG.md
    backlog_path = str(root_path / "BACKLOG.md")
    backlog_items = parse_backlog(backlog_path)

    # Gather git status
    git_status = gather_status(root)

    # Build spec context
    spec_context = build_spec_context(root)

    return SessionContext(
        last_session=last_session,
        current_tasks=tasks,
        backlog_items=backlog_items,
        done_items=tasks.get("completed", []),
        git=git_status,
        spec_context=spec_context,
    )


# ---------------------------------------------------------------------------
# Spec reference extraction
# ---------------------------------------------------------------------------


def _extract_spec_ref(text: str) -> Optional[str]:
    """Extract a spec reference (e.g. '001') from a text string.

    Looks for patterns like ``spec:001``, ``spec 001``, ``spec:001-slug``,
    or inline ``001-some-slug``.

    Args:
        text: Text to scan.

    Returns:
        Three-digit spec number string, or None if not found.
    """
    # spec:NNN or spec NNN
    m = re.search(r"spec[:\s]+(\d{3})(?!\d)", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # NNN-slug pattern (must be at word boundary)
    m = re.search(r"\b(\d{3})(?!\d)-[a-z]", text, re.IGNORECASE)
    if m:
        return m.group(1)

    return None


# ---------------------------------------------------------------------------
# Priority resolution
# ---------------------------------------------------------------------------


def resolve_next_action(ctx: SessionContext) -> NextAction:
    """Resolve the highest-priority next action from session context.

    Priority order:
        1. LAST_SESSION.md "Next Session Should Start With" / "Next" section
        2. CURRENT_TASKS.md active items (first item)
        3. BACKLOG.md P0 items (first item)
        4. BACKLOG.md next tier (P1, then P2, then P3 — first item)
        5. First active spec from spec context
        6. Fallback: no action resolved

    Args:
        ctx: A SessionContext populated by ``read_session_context``.

    Returns:
        A NextAction dataclass describing what to do next.
    """

    # -----------------------------------------------------------------------
    # 1. Check last session "next" directive
    # -----------------------------------------------------------------------
    next_items = _extract_next_items_from_session(ctx.last_session)
    if next_items:
        combined = next_items[0] if len(next_items) == 1 else "; ".join(next_items)
        spec_ref = _extract_spec_ref(combined)
        return NextAction(
            source="last_session",
            description=combined,
            spec_ref=spec_ref,
            needs_spec=spec_ref is not None,
            reasoning=(
                "LAST_SESSION.md contains a 'Next' directive indicating what "
                "the next session should focus on. This takes highest priority."
            ),
        )

    # -----------------------------------------------------------------------
    # 2. Check current active tasks
    # -----------------------------------------------------------------------
    active_tasks = ctx.current_tasks.get("active", [])
    if active_tasks:
        first_task = active_tasks[0]
        spec_ref = _extract_spec_ref(first_task)
        return NextAction(
            source="current_tasks",
            description=first_task,
            spec_ref=spec_ref,
            needs_spec=spec_ref is not None,
            reasoning=(
                f"CURRENT_TASKS.md has {len(active_tasks)} active task(s). "
                f"The first active task is selected as the next action."
            ),
        )

    # -----------------------------------------------------------------------
    # 3. Check backlog P0 items
    # -----------------------------------------------------------------------
    p0_items = [item for item in ctx.backlog_items if item.get("priority") == "P0"]
    if p0_items:
        first_p0 = p0_items[0]
        spec_ref = _extract_spec_ref(first_p0["text"])
        return NextAction(
            source="backlog_p0",
            description=first_p0["text"],
            spec_ref=spec_ref,
            needs_spec=spec_ref is not None,
            reasoning=(
                f"BACKLOG.md has {len(p0_items)} P0 (critical) item(s). "
                f"The first P0 item is selected as the next action."
            ),
        )

    # -----------------------------------------------------------------------
    # 4. Check backlog next tier (P1 -> P2 -> P3)
    # -----------------------------------------------------------------------
    for priority in ("P1", "P2", "P3"):
        tier_items = [
            item for item in ctx.backlog_items
            if item.get("priority") == priority
        ]
        if tier_items:
            first_item = tier_items[0]
            spec_ref = _extract_spec_ref(first_item["text"])
            return NextAction(
                source="backlog",
                description=first_item["text"],
                spec_ref=spec_ref,
                needs_spec=spec_ref is not None,
                reasoning=(
                    f"No P0 items in BACKLOG.md. Found {len(tier_items)} "
                    f"{priority} item(s). The first {priority} item is "
                    f"selected as the next action."
                ),
            )

    # -----------------------------------------------------------------------
    # 5. Fall back to active specs
    # -----------------------------------------------------------------------
    active_specs = ctx.spec_context.active_specs
    if active_specs:
        spec = active_specs[0]
        return NextAction(
            source="active_spec",
            description=f"Continue work on spec:{spec.number} — {spec.title}",
            spec_ref=spec.number,
            needs_spec=True,
            reasoning=(
                f"No explicit next actions in LAST_SESSION.md, "
                f"CURRENT_TASKS.md, or BACKLOG.md. Falling back to the "
                f"first active spec ({spec.number} — {spec.title})."
            ),
        )

    # -----------------------------------------------------------------------
    # 6. No action resolved
    # -----------------------------------------------------------------------
    return NextAction(
        source="none",
        description="No actionable items found. Consider reviewing project goals.",
        spec_ref=None,
        needs_spec=False,
        reasoning=(
            "No next-session directives, active tasks, backlog items, "
            "or active specs were found. The project may need initial "
            "setup or the session files may be missing."
        ),
    )
