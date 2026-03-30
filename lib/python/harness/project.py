"""Project structure detection, scaffolding, and legacy migration.

Detects project layout, creates scaffold from templates, migrates legacy
SPEC.md files, and ensures all workflow files exist.

Per Gummi: 'Structure before speed.'
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass
class ProjectStructure:
    """Detected project structure information."""

    has_specs_dir: bool = False
    has_legacy_spec: bool = False
    has_backlog: bool = False
    has_current_tasks: bool = False
    has_last_session: bool = False
    has_done: bool = False
    has_claude_md: bool = False
    project_type: str = "unknown"


# ---------------------------------------------------------------------------
# Template content
# ---------------------------------------------------------------------------

_VISION_TEMPLATE = """\
# {project_name} — Vision

**Status:** draft

## Overview

{project_name} project vision and goals.

## Goals

- Define the core purpose of {project_name}
- Establish success criteria
- Align all contributors on direction

## Done When

- [ ] `README.md` file exists
- [ ] `specs/` directory contains at least the vision spec
- [ ] All stakeholders agree on direction
"""

_SPECS_README_TEMPLATE = """\
# Specs

This directory contains numbered specification files for the project.

## Naming Convention

Files follow the pattern `NNN-slug.md` where:
- `NNN` is a zero-padded three-digit number (e.g. `000`, `001`)
- `slug` is a short kebab-case descriptor

## Statuses

- **draft** — idea captured, not yet committed to
- **active** — currently being worked on
- **done** — all Done When items satisfied
"""

_BACKLOG_TEMPLATE = """\
# BACKLOG

## Priorities

- (add priority items here)

## Icebox

- (add icebox items here)
"""

_CURRENT_TASKS_TEMPLATE = """\
# Current Tasks

## Active

- (add active tasks here)

## Completed

- (record completed tasks here)
"""

_LAST_SESSION_TEMPLATE = """\
# Last Session

## Date

{date}

## Focus

(describe session focus)

## Completed

- (list completed items)

## Next

- (list next steps)
"""

_DONE_TEMPLATE = """\
# Done

Completed specs and milestones.

## Completed Specs

(none yet)
"""

_CLAUDE_MD_TEMPLATE = """\
# CLAUDE.md

## Project: {project_name}

### Workflow

1. Read LAST_SESSION.md for context
2. Check CURRENT_TASKS.md for active work
3. Review relevant specs in specs/
4. Work in small, testable increments
5. Update LAST_SESSION.md before ending

### Conventions

- Specs live in `specs/` with `NNN-slug.md` naming
- Every spec has a **Done When** checklist
- Use `BACKLOG.md` for future work, `DONE.md` for completed milestones
"""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_structure(root: str) -> ProjectStructure:
    """Detect the project structure at the given root path.

    Examines the filesystem for specs/, legacy SPEC.md, workflow markdown
    files, and CLAUDE.md. Infers project_type from available signals.

    Args:
        root: Path to the project root directory.

    Returns:
        A ProjectStructure dataclass describing what was found.
    """
    root_path = Path(root)

    has_specs_dir = (root_path / "specs").is_dir()
    has_legacy_spec = (root_path / "SPEC.md").is_file()
    has_backlog = (root_path / "BACKLOG.md").is_file()
    has_current_tasks = (root_path / "CURRENT_TASKS.md").is_file()
    has_last_session = (root_path / "LAST_SESSION.md").is_file()
    has_done = (root_path / "DONE.md").is_file()
    has_claude_md = (root_path / "CLAUDE.md").is_file()

    project_type = _infer_project_type(root_path, has_specs_dir, has_legacy_spec)

    return ProjectStructure(
        has_specs_dir=has_specs_dir,
        has_legacy_spec=has_legacy_spec,
        has_backlog=has_backlog,
        has_current_tasks=has_current_tasks,
        has_last_session=has_last_session,
        has_done=has_done,
        has_claude_md=has_claude_md,
        project_type=project_type,
    )


def _infer_project_type(
    root_path: Path,
    has_specs_dir: bool,
    has_legacy_spec: bool,
) -> str:
    """Infer the project type from filesystem signals.

    Args:
        root_path: Project root.
        has_specs_dir: Whether specs/ directory exists.
        has_legacy_spec: Whether SPEC.md exists.

    Returns:
        One of: 'harness', 'legacy', 'fresh', 'unknown'.
    """
    # Has specs dir — it's a harness project (with or without numbered files)
    if has_specs_dir:
        return "harness"

    # Legacy project: has SPEC.md but no specs/
    if has_legacy_spec:
        return "legacy"

    if not root_path.is_dir():
        return "unknown"

    # Fresh project: directory exists but has minimal structure
    contents = _safe_listdir(root_path)
    if not contents or len(contents) <= 2:
        return "fresh"

    # Has files but doesn't match known patterns
    return "unknown"


def _safe_listdir(path: Path) -> list[str]:
    """List directory contents, returning empty list if directory doesn't exist.

    Args:
        path: Directory path.

    Returns:
        Sorted list of filenames, or empty list on error.
    """
    try:
        if path.is_dir():
            return sorted(os.listdir(str(path)))
    except OSError:
        pass
    return []


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------

def scaffold(root: str, project_name: str) -> list[str]:
    """Create a complete project scaffold with specs and workflow files.

    Creates:
        specs/README.md
        specs/000-vision.md
        BACKLOG.md
        CURRENT_TASKS.md
        LAST_SESSION.md
        DONE.md
        CLAUDE.md

    Existing files are NOT overwritten.

    Args:
        root: Path to the project root directory.
        project_name: Human-readable project name for templates.

    Returns:
        List of file paths (relative to root) that were created.
    """
    root_path = Path(root)
    today = date.today().isoformat()

    files_to_create: list[tuple[str, str]] = [
        (
            os.path.join("specs", "README.md"),
            _SPECS_README_TEMPLATE,
        ),
        (
            os.path.join("specs", "000-vision.md"),
            _VISION_TEMPLATE.format(project_name=project_name),
        ),
        (
            "BACKLOG.md",
            _BACKLOG_TEMPLATE,
        ),
        (
            "CURRENT_TASKS.md",
            _CURRENT_TASKS_TEMPLATE,
        ),
        (
            "LAST_SESSION.md",
            _LAST_SESSION_TEMPLATE.format(date=today),
        ),
        (
            "DONE.md",
            _DONE_TEMPLATE,
        ),
        (
            "CLAUDE.md",
            _CLAUDE_MD_TEMPLATE.format(project_name=project_name),
        ),
    ]

    created: list[str] = []
    for rel_path, content in files_to_create:
        full_path = root_path / rel_path
        if not full_path.exists():
            try:
                _write_file(full_path, content)
                created.append(rel_path)
            except OSError:
                pass  # Skip files that can't be written

    return created


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------

def migrate_legacy(root: str) -> list[str]:
    """Migrate legacy SPEC.md into the specs/ directory structure.

    If SPEC.md exists at the project root, it is:
    1. Copied to specs/000-vision.md (if that file doesn't already exist)
    2. The original SPEC.md is renamed to SPEC.md.bak

    If SPEC.md contains numbered sections, they are split into separate
    spec files where possible.

    Args:
        root: Path to the project root directory.

    Returns:
        List of file paths (relative to root) that were created or moved.
    """
    root_path = Path(root)
    legacy_path = root_path / "SPEC.md"

    if not legacy_path.is_file():
        return []

    changes: list[str] = []

    try:
        content = legacy_path.read_text(encoding="utf-8")
    except OSError:
        return []

    specs_dir = root_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Try to extract numbered sections (## 001 - Title or ## NNN-slug patterns)
    sections = _split_legacy_sections(content)

    if sections:
        used_filenames: set[str] = set()
        for number, slug, section_content in sections:
            filename = f"{number}-{slug}.md"
            # Deduplicate filenames
            if filename in used_filenames:
                counter = 1
                while f"{number}-{slug}-{counter}.md" in used_filenames:
                    counter += 1
                filename = f"{number}-{slug}-{counter}.md"
            used_filenames.add(filename)
            target = specs_dir / filename
            if not target.exists():
                _write_file(target, section_content)
                changes.append(os.path.join("specs", filename))
    else:
        # No numbered sections found — migrate as 000-vision.md
        vision_path = specs_dir / "000-vision.md"
        if not vision_path.exists():
            _write_file(vision_path, content)
            changes.append(os.path.join("specs", "000-vision.md"))

    # Create a README.md in specs/ if missing
    specs_readme = specs_dir / "README.md"
    if not specs_readme.exists():
        _write_file(specs_readme, _SPECS_README_TEMPLATE)
        changes.append(os.path.join("specs", "README.md"))

    # Rename original SPEC.md to SPEC.md.bak
    backup_path = root_path / "SPEC.md.bak"
    try:
        if backup_path.exists():
            # Find a unique backup name
            counter = 1
            while backup_path.exists():
                backup_path = root_path / f"SPEC.md.bak.{counter}"
                counter += 1
        shutil.move(str(legacy_path), str(backup_path))
        changes.append(backup_path.name)
    except OSError:
        pass

    return changes


def _split_legacy_sections(content: str) -> list[tuple[str, str, str]]:
    """Attempt to split legacy SPEC.md into numbered sections.

    Looks for H2 headings like:
        ## 001 - Session Harness
        ## 002-backlog-workflow

    Args:
        content: Full text of the legacy SPEC.md.

    Returns:
        List of (number, slug, section_content) tuples. Empty if no
        numbered sections were found.
    """
    pattern = re.compile(
        r"^##\s+(\d{3})\s*[-–—]\s*(.+)$",
        re.MULTILINE,
    )

    matches = list(pattern.finditer(content))
    if len(matches) < 2:
        # Not enough numbered sections to warrant splitting
        return []

    sections: list[tuple[str, str, str]] = []

    # Capture any content before the first numbered section
    preamble = content[:matches[0].start()].strip()
    if preamble:
        sections.append(("000", "vision", f"# Vision\n\n**Status:** draft\n\n{preamble}\n"))

    for i, match in enumerate(matches):
        number = match.group(1)
        raw_title = match.group(2).strip()
        slug = _slugify(raw_title)

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_content = content[start:end].strip() + "\n"

        # Format as a proper spec with H1 title
        section_content = f"# {raw_title}\n\n**Status:** draft\n\n{section_content}"
        sections.append((number, slug, section_content))

    return sections


def _slugify(text: str) -> str:
    """Convert a title string to a kebab-case slug.

    Args:
        text: Title text to slugify.

    Returns:
        Kebab-case string suitable for filenames.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


# ---------------------------------------------------------------------------
# Ensure workflow files
# ---------------------------------------------------------------------------

def ensure_workflow_files(root: str) -> list[str]:
    """Create any missing workflow files without overwriting existing ones.

    Checks for and creates if missing:
        BACKLOG.md
        CURRENT_TASKS.md
        LAST_SESSION.md
        DONE.md

    Does NOT create specs/ or CLAUDE.md — use scaffold() for full setup.

    Args:
        root: Path to the project root directory.

    Returns:
        List of file paths (relative to root) that were created.
    """
    root_path = Path(root)
    today = date.today().isoformat()

    workflow_files: list[tuple[str, str]] = [
        ("BACKLOG.md", _BACKLOG_TEMPLATE),
        ("CURRENT_TASKS.md", _CURRENT_TASKS_TEMPLATE),
        ("LAST_SESSION.md", _LAST_SESSION_TEMPLATE.format(date=today)),
        ("DONE.md", _DONE_TEMPLATE),
    ]

    created: list[str] = []
    for filename, content in workflow_files:
        full_path = root_path / filename
        if not full_path.exists():
            _write_file(full_path, content)
            created.append(filename)

    return created


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Target file path.
        content: String content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
