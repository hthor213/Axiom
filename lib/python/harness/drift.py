"""Deterministic drift signals for spec alignment.

Detects structural drift — stale specs, regressions in done specs,
uncovered directories — without requiring LLM judgment.  Semantic
alignment remains the responsibility of the LLM layer.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .parser import extract_done_when, extract_spec_status
from .scanner import SpecContext, SpecInfo, build_spec_context, scan_specs
from .spec_check import classify_done_when, run_check


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DriftItem:
    """A single deterministic drift signal."""

    type: str
    description: str
    spec_ref: str
    severity: str  # "info", "warning", "error"


@dataclass
class DriftReport:
    """Aggregated drift report for a project."""

    items: List[DriftItem] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Return True when no drift items were detected."""
        return len(self.items) == 0

    @property
    def summary(self) -> str:
        """Human-readable one-line summary of the report."""
        if self.clean:
            return "No drift detected."
        by_sev: dict[str, int] = {}
        for item in self.items:
            by_sev[item.severity] = by_sev.get(item.severity, 0) + 1
        parts = [f"{count} {sev}" for sev, count in sorted(by_sev.items())]
        return f"{len(self.items)} drift signal(s): {', '.join(parts)}."


# ---------------------------------------------------------------------------
# Key project directories to check for spec coverage
# ---------------------------------------------------------------------------

_KEY_DIRS: list[str] = [
    "lib",
    "src",
    "app",
    "cmd",
    "scripts",
    "tests",
    "docs",
    "config",
    "infra",
    "deploy",
    "api",
    "pkg",
    "internal",
    "web",
]


# ---------------------------------------------------------------------------
# Check: stale active specs
# ---------------------------------------------------------------------------


def check_stale_active_specs(
    root: str,
    active_specs: List[SpecInfo],
    stale_days: int = 7,
) -> List[DriftItem]:
    """Detect active specs whose files haven't been modified recently.

    An active spec whose markdown file has not been touched in more than
    ``stale_days`` days is flagged as potentially stale — it may need
    re-evaluation or demotion back to draft.

    Args:
        root: Project root directory.
        active_specs: List of ``SpecInfo`` for specs with status ``active``.
        stale_days: Number of days after which an untouched spec is stale.

    Returns:
        List of ``DriftItem`` instances for each stale spec found.
    """
    items: List[DriftItem] = []
    now = time.time()
    threshold = stale_days * 86400  # seconds

    for spec in active_specs:
        spec_path = spec.path
        if not os.path.isfile(spec_path):
            continue
        try:
            mtime = os.path.getmtime(spec_path)
        except OSError:
            continue

        age_days = (now - mtime) / 86400
        if age_days > stale_days:
            items.append(DriftItem(
                type="stale_active_spec",
                description=(
                    f"Active spec {spec.number}-{spec.title} has not been "
                    f"modified in {int(age_days)} days (threshold: {stale_days})."
                ),
                spec_ref=str(spec.number),
                severity="warning",
            ))

    return items


# ---------------------------------------------------------------------------
# Check: done spec regressions
# ---------------------------------------------------------------------------


def check_done_regressions(
    root: str,
    done_specs: List[SpecInfo],
) -> List[DriftItem]:
    """Re-run automatable Done When checks on specs marked as done.

    If any automatable check now fails on a done spec, that's a regression
    signal — something in the project changed and the spec's completion
    criteria are no longer met.

    Args:
        root: Project root directory.
        done_specs: List of ``SpecInfo`` for specs with status ``done``.

    Returns:
        List of ``DriftItem`` instances for each regression found.
    """
    items: List[DriftItem] = []

    for spec in done_specs:
        spec_path = spec.path
        if not os.path.isfile(spec_path):
            continue

        try:
            done_when_items = extract_done_when(spec_path)
        except Exception:
            continue

        for dw_item in done_when_items:
            classified = classify_done_when(dw_item)
            check_type = classified.get("check_type", "judgment")

            # Only re-run automatable checks
            if check_type == "judgment":
                continue

            try:
                result = run_check(classified, root)
            except Exception as e:
                items.append(DriftItem(
                    type="done_regression",
                    description=(
                        f"Done spec {spec.number} check execution failed: "
                        f"\"{dw_item.get('text', '')[:80]}\" — {e}"
                    ),
                    spec_ref=str(spec.number),
                    severity="error",
                ))
                continue

            if result.get("result") is False:
                error_msg = result.get("error", "check failed")
                items.append(DriftItem(
                    type="done_regression",
                    description=(
                        f"Done spec {spec.number} regression: "
                        f"\"{dw_item.get('text', '')[:80]}\" — {error_msg}"
                    ),
                    spec_ref=str(spec.number),
                    severity="error",
                ))

    return items


# ---------------------------------------------------------------------------
# Check: uncovered directories
# ---------------------------------------------------------------------------


def _extract_referenced_paths(specs: List[SpecInfo]) -> set[str]:
    """Extract file/directory path prefixes referenced in spec Done When items.

    Scans all backtick-wrapped paths in Done When items across all specs
    and returns the set of top-level directory names they reference.
    """
    dirs: set[str] = set()

    for spec in specs:
        if not os.path.isfile(spec.path):
            continue
        try:
            dw_items = extract_done_when(spec.path)
        except Exception:
            continue
        for item in dw_items:
            text = item.get("text", "")
            # Find backtick-wrapped paths
            for m in re.finditer(r"`([^`]+)`", text):
                path_str = m.group(1).strip()
                # Skip things that look like commands or short tokens
                if " " in path_str and not path_str.startswith(("/", ".")):
                    continue
                # Extract the first meaningful path component
                parts = Path(path_str).parts
                for part in parts:
                    cleaned = part.rstrip("/")
                    if cleaned and cleaned not in (".", "..", "/", "\\"):
                        dirs.add(cleaned)
                        break

    return dirs


def check_uncovered_directories(
    root: str,
    spec_context: SpecContext,
    all_scanned_specs: Optional[List[SpecInfo]] = None,
) -> List[DriftItem]:
    """Identify key project directories that have no spec coverage.

    Checks each existing directory in ``root`` against a list of
    commonly-important directory names.  If a key directory exists but
    is not referenced by any spec's Done When items, it is flagged.

    Args:
        root: Project root directory.
        spec_context: The ``SpecContext`` for the project.
        all_scanned_specs: Optional pre-scanned specs list to avoid redundant I/O.

    Returns:
        List of ``DriftItem`` instances for each uncovered directory.
    """
    items: List[DriftItem] = []

    # Gather all specs (active + any others we can find from context)
    all_specs: List[SpecInfo] = list(spec_context.active_specs)
    # Also include vision if present
    if spec_context.vision is not None:
        vision_paths = {s.path for s in all_specs}
        if spec_context.vision.path not in vision_paths:
            all_specs.append(spec_context.vision)

    # Include done/draft specs from pre-scanned list or scan now
    if all_scanned_specs is not None:
        existing_paths = {s.path for s in all_specs}
        for s in all_scanned_specs:
            if s.path not in existing_paths:
                all_specs.append(s)
    else:
        specs_dir = os.path.join(root, "specs")
        if os.path.isdir(specs_dir):
            report = scan_specs(specs_dir)
            existing_paths = {s.path for s in all_specs}
            for s in report.specs:
                if s.path not in existing_paths:
                    all_specs.append(s)

    referenced = _extract_referenced_paths(all_specs)

    # Check which key directories exist but aren't covered
    try:
        entries = os.listdir(root)
    except OSError:
        return items

    for entry in sorted(entries):
        if entry not in _KEY_DIRS:
            continue
        full_path = os.path.join(root, entry)
        if not os.path.isdir(full_path):
            continue
        if entry not in referenced:
            items.append(DriftItem(
                type="uncovered_directory",
                description=(
                    f"Directory '{entry}/' exists but is not referenced "
                    f"by any spec's Done When items."
                ),
                spec_ref="",
                severity="info",
            ))

    return items


# ---------------------------------------------------------------------------
# Main alignment check
# ---------------------------------------------------------------------------


def check_alignment(
    root: str,
    spec_context: Optional[SpecContext] = None,
) -> DriftReport:
    """Run all deterministic drift checks and return a unified report.

    This is the primary entry point for drift detection.  It builds a
    ``SpecContext`` if one is not provided, then runs each sub-check and
    aggregates results into a single ``DriftReport``.

    Args:
        root: Project root directory.
        spec_context: Pre-built context; built automatically if ``None``.

    Returns:
        A ``DriftReport`` containing all detected drift signals.
    """
    if spec_context is None:
        spec_context = build_spec_context(root)

    report = DriftReport()

    # --- Stale active specs ---
    report.items.extend(
        check_stale_active_specs(root, spec_context.active_specs)
    )

    # --- Done regressions ---
    specs_dir = os.path.join(root, "specs")
    full_report = None
    done_specs: List[SpecInfo] = []
    if os.path.isdir(specs_dir):
        full_report = scan_specs(specs_dir)
        done_specs = [s for s in full_report.specs if s.status == "done"]

    report.items.extend(
        check_done_regressions(root, done_specs)
    )

    # --- Uncovered directories ---
    report.items.extend(
        check_uncovered_directories(
            root,
            spec_context,
            all_scanned_specs=full_report.specs if full_report is not None else None,
        )
    )

    return report
