"""Spec scanning — builds on existing parser.py.

Provides dataclasses and functions for scanning spec directories,
classifying specs by band, building spec context, and extracting
invariants and exclusions from vision specs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .parser import (
    extract_done_when,
    extract_spec_status,
    extract_spec_number,
    extract_spec_title,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SpecInfo:
    """Rich information about a single spec file."""

    path: str
    number: str
    title: str
    status: str
    band: str
    done_when_total: int
    done_when_checked: int
    done_when_automatable: int

    @property
    def completion_ratio(self) -> float:
        """Return fraction of done-when items that are checked (0.0–1.0)."""
        if self.done_when_total == 0:
            return 0.0
        return self.done_when_checked / self.done_when_total

    @property
    def is_active(self) -> bool:
        """Return True when the spec status is 'active'."""
        return self.status == "active"


@dataclass
class SpecReport:
    """Aggregated report across all specs in a directory."""

    specs: List[SpecInfo] = field(default_factory=list)
    by_band: dict[str, List[SpecInfo]] = field(default_factory=dict)
    by_status: dict[str, List[SpecInfo]] = field(default_factory=dict)
    active_count: int = 0
    drift_candidates: List[SpecInfo] = field(default_factory=list)


@dataclass
class SpecContext:
    """High-level project context derived from specs and vision."""

    vision: Optional[SpecInfo]
    active_specs: List[SpecInfo] = field(default_factory=list)
    invariants: List[str] = field(default_factory=list)
    exclusions: List[str] = field(default_factory=list)
    index_exists: bool = False


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

# Band boundaries expressed as inclusive integer ranges.
_BAND_RANGES: list[tuple[int, int, str]] = [
    (0, 0, "vision"),
    (1, 49, "foundation"),
    (50, 99, "mvp"),
    (100, 199, "v1"),
    (200, 299, "v2"),
]


def classify_band(number: str) -> str:
    """Classify a spec number string into a development band.

    Args:
        number: Zero-padded spec number, e.g. ``"001"``, ``"052"``, ``"210"``.

    Returns:
        One of ``'vision'``, ``'foundation'``, ``'mvp'``, ``'v1'``, ``'v2'``,
        or ``'backlog'`` if the number doesn't fall into a known range.
    """
    try:
        n = int(number)
    except (ValueError, TypeError):
        return "backlog"

    for low, high, band_name in _BAND_RANGES:
        if low <= n <= high:
            return band_name

    return "backlog"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_automatable(items: List[dict]) -> int:
    """Count done-when items that look automatable (not pure judgment).

    An item is considered automatable if its text matches any of the
    patterns recognised by ``spec_check.classify_done_when``.  We do a
    lightweight heuristic here to avoid a circular import — we check for
    backtick-wrapped paths, ``spec:NNN`` references, and command-like
    patterns.
    """
    automatable = 0
    for item in items:
        text = item.get("text") or ""
        # file_exists patterns
        if re.search(r"`[^`]+`\s+(?:file\s+)?exists\b", text, re.IGNORECASE):
            automatable += 1
            continue
        if re.search(r"exists\s+at\s+`[^`]+`", text, re.IGNORECASE):
            automatable += 1
            continue
        # spec_status pattern
        if re.search(r"spec:\d{3}\s+status\s+is\s+", text, re.IGNORECASE):
            automatable += 1
            continue
        # grep patterns (mentions / contains / references / includes)
        if re.search(
            r"`[^`]+`\s+(?:mentions?|contains?|references?|includes?)\s+",
            text,
            re.IGNORECASE,
        ):
            automatable += 1
            continue
        # command patterns (backtick starting with known command prefix)
        cmd_starters = (
            "python", "pip", "npm", "node", "gh ", "git ",
            "platform ", "make", "pytest", "curl", "bash", "sh ", "test ",
        )
        found_cmd = False
        for m in re.finditer(r"`([^`]+)`", text):
            cmd = m.group(1)
            if any(cmd.startswith(s) for s in cmd_starters):
                found_cmd = True
                break
        if found_cmd:
            automatable += 1
            continue
    return automatable


def _build_spec_info(spec_path: str) -> Optional[SpecInfo]:
    """Build a ``SpecInfo`` from a single spec file path.

    Returns ``None`` if the file cannot be parsed (e.g. missing number).
    """
    fname = os.path.basename(spec_path)
    number = extract_spec_number(fname)
    if not number:
        return None

    title = extract_spec_title(spec_path)
    status = extract_spec_status(spec_path)
    band = classify_band(number)

    done_when_items = extract_done_when(spec_path)
    total = len(done_when_items)
    checked = sum(1 for item in done_when_items if item.get("checked", False))
    automatable = _count_automatable(done_when_items)

    return SpecInfo(
        path=spec_path,
        number=number,
        title=title,
        status=status,
        band=band,
        done_when_total=total,
        done_when_checked=checked,
        done_when_automatable=automatable,
    )


def _is_drift_candidate(spec: SpecInfo) -> bool:
    """Determine whether a spec looks like it may have drifted.

    A spec is a drift candidate when:
    - It is marked ``active`` but has zero done-when items, OR
    - It is marked ``active`` but all done-when items are already checked
      (suggesting it could be promoted to ``done``), OR
    - It is marked ``draft`` but has checked items (work started without
      status update).
    """
    if spec.status == "active":
        if spec.done_when_total == 0:
            return True
        if spec.done_when_checked >= spec.done_when_total:
            return True
    if spec.status == "draft" and spec.done_when_checked > 0:
        return True
    return False


# ---------------------------------------------------------------------------
# Public scanning functions
# ---------------------------------------------------------------------------


def scan_specs(specs_dir: str) -> SpecReport:
    """Scan a specs directory and return a comprehensive ``SpecReport``.

    Args:
        specs_dir: Path to the ``specs/`` directory.

    Returns:
        A ``SpecReport`` with all specs catalogued by band and status,
        active count tallied, and drift candidates identified.
    """
    report = SpecReport()

    if not os.path.isdir(specs_dir):
        return report

    try:
        entries = sorted(os.listdir(specs_dir))
    except OSError:
        return report

    for fname in entries:
        if not fname.endswith(".md"):
            continue

        fpath = os.path.join(specs_dir, fname)
        if not os.path.isfile(fpath):
            continue

        info = _build_spec_info(fpath)
        if info is None:
            continue

        report.specs.append(info)

        # Index by band
        report.by_band.setdefault(info.band, []).append(info)

        # Index by status
        report.by_status.setdefault(info.status, []).append(info)

        # Count actives
        if info.is_active:
            report.active_count += 1

        # Detect drift
        if _is_drift_candidate(info):
            report.drift_candidates.append(info)

    return report


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------


def _extract_section_items(file_path: str, section_heading: str) -> List[str]:
    """Extract bullet items from a named ``## Section`` in a markdown file.

    Reads lines under the given H2 heading until the next H1 or H2 (or EOF).
    Returns the stripped text of each ``- item`` line found.

    Args:
        file_path: Absolute or relative path to the markdown file.
        section_heading: The heading text to look for (case-insensitive),
                         e.g. ``"Invariants"``.

    Returns:
        List of bullet-item strings (leading ``- `` removed).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return []

    in_section = False
    items: List[str] = []
    heading_re = re.compile(
        r"^##\s+" + re.escape(section_heading) + r"\b",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()

        if heading_re.match(stripped):
            in_section = True
            continue

        # A new H1 or H2 ends the section
        if in_section and re.match(r"^#{1,2}\s+", stripped):
            break

        if not in_section:
            continue

        # Match plain bullets and checklist bullets (-, *, +)
        m = re.match(r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped)
        if m:
            items.append(m.group(1).strip())

    return items


def extract_invariants(vision_path: str) -> List[str]:
    """Parse the ``## Invariants`` section from a vision spec.

    Args:
        vision_path: Path to the vision spec file (typically ``000-vision.md``).

    Returns:
        List of invariant strings extracted from the section's bullet list.
        Returns an empty list if the file or section is missing.
    """
    return _extract_section_items(vision_path, "Invariants")


def extract_exclusions(vision_path: str) -> List[str]:
    """Parse the ``## Exclusions`` section from a vision spec.

    Also recognises the common variant headings ``## Non-Goals`` and
    ``## Out of Scope`` as equivalent sections.

    Args:
        vision_path: Path to the vision spec file.

    Returns:
        List of exclusion strings.  Returns an empty list if nothing found.
    """
    for heading in ("Exclusions", "Non-Goals", "Out of Scope"):
        items = _extract_section_items(vision_path, heading)
        if items:
            return items
    return []


# ---------------------------------------------------------------------------
# Vision spec locator
# ---------------------------------------------------------------------------


def _find_vision_spec(specs_dir: str) -> Optional[str]:
    """Locate the vision spec (``000-*.md``) in a specs directory.

    Returns the full path or ``None`` if not found.
    """
    if not os.path.isdir(specs_dir):
        return None

    for fname in sorted(os.listdir(specs_dir)):
        if fname.startswith("000-") and fname.endswith(".md"):
            return os.path.join(specs_dir, fname)

    return None


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def build_spec_context(root: str) -> SpecContext:
    """Build a high-level ``SpecContext`` for a project root.

    Scans the ``specs/`` directory, identifies the vision spec, extracts
    invariants and exclusions, and collects active specs.

    Args:
        root: Project root directory.

    Returns:
        A ``SpecContext`` instance.  Fields default gracefully when files
        or sections are missing.
    """
    specs_dir = os.path.join(root, "specs")

    # Check for index file (specs/INDEX.md or specs/index.md)
    index_exists = any(
        os.path.isfile(os.path.join(specs_dir, name))
        for name in ("INDEX.md", "index.md")
    )

    # Scan all specs
    report = scan_specs(specs_dir)

    # Locate vision spec
    vision_path = _find_vision_spec(specs_dir)
    vision_info: Optional[SpecInfo] = None

    if vision_path is not None:
        vision_info = _build_spec_info(vision_path)

    # Extract invariants and exclusions from vision
    invariants: List[str] = []
    exclusions: List[str] = []
    if vision_path is not None:
        invariants = extract_invariants(vision_path)
        exclusions = extract_exclusions(vision_path)

    # Collect active specs
    active_specs = [s for s in report.specs if s.is_active]

    return SpecContext(
        vision=vision_info,
        active_specs=active_specs,
        invariants=invariants,
        exclusions=exclusions,
        index_exists=index_exists,
    )
