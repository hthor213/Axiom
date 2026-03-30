"""Report format validation for the analyst agent.

Validates that analyst reports contain required sections and conform
to the expected markdown structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Section heading patterns the analyst report must contain
_CRITICAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^##\s+.*critical\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*blockers?\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*urgent\b", re.IGNORECASE | re.MULTILINE),
]

_ARCHITECTURAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^##\s+.*architect", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*design\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*structure\b", re.IGNORECASE | re.MULTILINE),
]

_PATTERNS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^##\s+.*pattern", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*observation", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*finding", re.IGNORECASE | re.MULTILINE),
]

_RECOMMENDATIONS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^##\s+.*recommend", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*action\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*next\s+step", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+.*suggestion", re.IGNORECASE | re.MULTILINE),
]


@dataclass
class FormatValidation:
    """Result of validating an analyst report's format.

    Attributes:
        has_critical_section: Whether the report contains a critical/blockers section.
        has_architectural_section: Whether the report contains an architecture section.
        has_patterns_section: Whether the report contains a patterns/observations section.
        has_recommendations_section: Whether the report contains a recommendations section.
        issues: List of human-readable validation issue descriptions.
        valid: Whether the report passes all format checks.
    """

    has_critical_section: bool = False
    has_architectural_section: bool = False
    has_patterns_section: bool = False
    has_recommendations_section: bool = False
    issues: list[str] = field(default_factory=list)
    valid: bool = False


def _has_any_match(content: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return True if any pattern matches within the content."""
    for pattern in patterns:
        if pattern.search(content):
            return True
    return False


def validate_report_format(report: str) -> FormatValidation:
    """Validate that an analyst report contains the required sections.

    Checks for the presence of four required section types:
    - Critical / Blockers
    - Architectural / Design
    - Patterns / Observations
    - Recommendations / Actions

    Also checks basic structural requirements like having a title
    and minimum content length.

    Args:
        report: The full markdown text of the analyst report.

    Returns:
        A FormatValidation dataclass with per-section results,
        a list of issues found, and an overall valid flag.
    """
    result = FormatValidation()

    if not report or not report.strip():
        result.issues.append("Report is empty")
        return result

    content = report.strip()

    # Check for a title (H1 heading)
    has_title = bool(re.search(r"^#\s+.+", content, re.MULTILINE))
    if not has_title:
        result.issues.append("Report is missing a title (H1 heading)")

    # Check minimum content length (at least a few meaningful lines)
    non_empty_lines = [l for l in content.splitlines() if l.strip()]
    if len(non_empty_lines) < 5:
        result.issues.append(
            f"Report appears too short ({len(non_empty_lines)} non-empty lines, expected at least 5)"
        )

    # Check each required section
    result.has_critical_section = _has_any_match(content, _CRITICAL_PATTERNS)
    if not result.has_critical_section:
        result.issues.append("Missing required section: Critical / Blockers")

    result.has_architectural_section = _has_any_match(content, _ARCHITECTURAL_PATTERNS)
    if not result.has_architectural_section:
        result.issues.append("Missing required section: Architectural / Design")

    result.has_patterns_section = _has_any_match(content, _PATTERNS_PATTERNS)
    if not result.has_patterns_section:
        result.issues.append("Missing required section: Patterns / Observations")

    result.has_recommendations_section = _has_any_match(content, _RECOMMENDATIONS_PATTERNS)
    if not result.has_recommendations_section:
        result.issues.append("Missing required section: Recommendations / Actions")

    # Overall validity: all four sections present, has title, and sufficient length
    result.valid = (
        result.has_critical_section
        and result.has_architectural_section
        and result.has_patterns_section
        and result.has_recommendations_section
        and len(result.issues) == 0
    )

    return result
