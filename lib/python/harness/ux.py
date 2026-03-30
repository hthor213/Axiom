"""UX formatting for structured reports and questions.

Provides dataclasses and formatting functions for presenting structured
information to the user during session operations — start reports,
checkpoint reports, and decision questions with options.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import List, Optional

from .checkpoint import InvariantResult
from .drift import DriftReport
from .platform_check import PlatformReport
from .session import NextAction


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class QuestionContext:
    """Context for a question being posed to the user or LLM.

    Attributes:
        project: Name or path of the current project.
        branch: Current git branch name.
        working_on: Short description of the current focus area.
    """

    project: str = ""
    branch: str = ""
    working_on: str = ""


@dataclass
class QuestionOption:
    """A single option in a structured question.

    Attributes:
        label: Short label for the option (e.g. 'A', 'B', '1').
        description: Human-readable description of what this option does.
        effort: Estimated effort level (e.g. 'low', 'medium', 'high').
        tradeoff: Description of tradeoffs for choosing this option.
    """

    label: str = ""
    description: str = ""
    effort: str = ""
    tradeoff: str = ""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _indent(text: str, prefix: str = "  ") -> str:
    """Indent all lines of a multi-line string.

    Args:
        text: The text to indent.
        prefix: The prefix string to prepend to each line.

    Returns:
        The indented text.
    """
    return textwrap.indent(str(text), prefix)


def _format_header(title: str, char: str = "=") -> str:
    """Create a section header with an underline.

    Args:
        title: The header text.
        char: The character used for the underline.

    Returns:
        A two-line string with title and underline.
    """
    return f"{title}\n{char * len(title)}"


def _format_context_block(ctx: QuestionContext) -> str:
    """Format a QuestionContext into a compact context block.

    Args:
        ctx: The question context to format.

    Returns:
        A multi-line string describing the context.
    """
    if ctx is None:
        return "  (no context available)"

    lines: List[str] = []
    if ctx.project:
        lines.append(f"  Project:    {ctx.project}")
    if ctx.branch:
        lines.append(f"  Branch:     {ctx.branch}")
    if ctx.working_on:
        lines.append(f"  Working on: {ctx.working_on}")
    if not lines:
        lines.append("  (no context available)")
    return "\n".join(lines)


def _format_drift_summary(drift: DriftReport) -> str:
    """Format a DriftReport into a human-readable summary block.

    Args:
        drift: The drift report to summarize.

    Returns:
        A multi-line string with drift details.
    """
    if drift is None:
        return "  No drift report available."

    if drift.clean:
        return "  No drift detected. Specs are aligned."

    lines: List[str] = []
    lines.append(_indent(drift.summary))
    for item in drift.items:
        severity_tag = f"[{item.severity.upper()}]" if getattr(item, 'severity', None) else "[UNKNOWN]"
        lines.append(f"    {severity_tag} {item.description}")
        if item.spec_ref:
            lines.append(f"           spec:{item.spec_ref}")
    return "\n".join(lines)


def _format_platform_summary(platform: PlatformReport) -> str:
    """Format a PlatformReport into a human-readable summary block.

    Args:
        platform: The platform report to summarize.

    Returns:
        A multi-line string with platform details.
    """
    if platform is None:
        return "  No platform report available."

    lines: List[str] = []
    cred = platform.credential_source
    if cred and cred != "none":
        lines.append(f"  Credentials: {cred}")
    else:
        lines.append("  Credentials: none detected")

    if platform.infrastructure_deps:
        deps = ", ".join(str(dep) for dep in platform.infrastructure_deps)
        lines.append(f"  Infrastructure: {deps}")
    else:
        lines.append("  Infrastructure: none detected")

    if platform.recommendation:
        lines.append(f"  Recommendation: {platform.recommendation}")

    return "\n".join(lines)


def _format_invariant_summary(invariants: List[InvariantResult]) -> str:
    """Format invariant check results into a summary block.

    Args:
        invariants: List of invariant results.

    Returns:
        A multi-line string summarizing invariant status.
    """
    if not invariants:
        return "  No invariants checked."

    passed = sum(1 for i in invariants if i.status == "pass")
    failed = sum(1 for i in invariants if i.status == "fail")
    skipped = sum(1 for i in invariants if i.status == "skip")

    lines: List[str] = []
    lines.append(f"  Total: {len(invariants)}  |  Pass: {passed}  |  Fail: {failed}  |  Skip: {skipped}")

    for inv in invariants:
        if inv.status == "pass":
            icon = "✓"
        elif inv.status == "fail":
            icon = "✗"
        else:
            icon = "○"
        lines.append(f"    {icon} {inv.invariant}")
        if inv.status == "fail" and inv.evidence:
            lines.append(f"      → {inv.evidence}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public formatting functions
# ---------------------------------------------------------------------------


def format_question(
    ctx: QuestionContext,
    situation: str,
    recommendation: str,
    options: List[QuestionOption],
    spec_ref: Optional[str] = None,
) -> str:
    """Format a structured question for the user or LLM.

    Presents a situation description, optional spec reference, a
    recommendation, and numbered options with effort and tradeoff details.

    Args:
        ctx: The current question context (project, branch, focus).
        situation: Description of the current situation requiring a decision.
        recommendation: The recommended course of action.
        options: List of QuestionOption instances to present.
        spec_ref: Optional spec reference (e.g. '001') related to the question.

    Returns:
        A formatted multi-line string suitable for display.
    """
    sections: List[str] = []

    # Header
    sections.append(_format_header("Decision Required"))
    sections.append("")

    # Context
    sections.append("Context:")
    sections.append(_format_context_block(ctx))
    sections.append("")

    # Spec reference
    if spec_ref:
        sections.append(f"Related Spec: spec:{spec_ref}")
        sections.append("")

    # Situation
    sections.append("Situation:")
    sections.append(_indent(situation))
    sections.append("")

    # Options
    if options:
        sections.append("Options:")
        for opt in options:
            label = opt.label if opt.label else "?"
            sections.append(f"  [{label}] {opt.description}")
            if opt.effort:
                sections.append(f"       Effort: {opt.effort}")
            if opt.tradeoff:
                sections.append("       Tradeoff: " + opt.tradeoff.replace("\n", "\n                 "))
        sections.append("")

    # Recommendation
    sections.append("Recommendation:")
    sections.append(_indent(recommendation))

    return "\n".join(sections)


def format_start_report(
    ctx: QuestionContext,
    next_action: NextAction,
    drift: DriftReport,
    platform: PlatformReport,
) -> str:
    """Format a session start report.

    Summarizes the project state at session start: what to work on,
    drift signals, and platform readiness.

    Args:
        ctx: The current question context (project, branch, focus).
        next_action: The resolved next action for the session.
        drift: The drift report for the project.
        platform: The platform dependency report.

    Returns:
        A formatted multi-line string suitable for display.
    """
    sections: List[str] = []

    # Header
    sections.append(_format_header("Session Start Report"))
    sections.append("")

    # Context
    sections.append("Context:")
    sections.append(_format_context_block(ctx))
    sections.append("")

    # Next action
    sections.append("Next Action:")
    if next_action is None:
        sections.append("  No next action resolved.")
    else:
        sections.append(_indent(next_action.description))
        if next_action.source and next_action.source != "none":
            sections.append(f"  Source: {next_action.source}")
        if next_action.spec_ref:
            sections.append(f"  Spec: spec:{next_action.spec_ref}")
        if next_action.reasoning:
            sections.append("  Reasoning: " + next_action.reasoning.replace("\n", "\n             "))
    sections.append("")

    # Drift
    sections.append("Drift Check:")
    sections.append(_format_drift_summary(drift))
    sections.append("")

    # Platform
    sections.append("Platform:")
    sections.append(_format_platform_summary(platform))

    return "\n".join(sections)


def format_checkpoint_report(
    spec_status: List[dict],
    committed: List[str],
    invariants: List[InvariantResult],
    platform: PlatformReport,
    next_focus: str,
) -> str:
    """Format a checkpoint (end-of-session) report.

    Summarizes the session outcome: spec status, committed files,
    invariant results, platform state, and recommended next focus.

    Args:
        spec_status: List of dicts with keys 'number', 'title', 'status',
            'passed', 'failed', 'judgment' describing each spec's state.
            Missing keys are handled gracefully.
        committed: List of file paths that were committed.
        invariants: List of InvariantResult from invariant checks.
        platform: The platform dependency report.
        next_focus: Description of what to focus on next session.

    Returns:
        A formatted multi-line string suitable for display.
    """
    sections: List[str] = []

    # Header
    sections.append(_format_header("Checkpoint Report"))
    sections.append("")

    # Spec status
    sections.append("Spec Status:")
    if spec_status:
        for spec in spec_status:
            if not isinstance(spec, dict):
                sections.append(f"  (malformed entry: {spec!r})")
                continue
            number = spec.get("number", "???")
            title = spec.get("title", "untitled")
            status = spec.get("status", "unknown")
            passed = spec.get("passed", 0)
            failed = spec.get("failed", 0)
            judgment = spec.get("judgment", 0)
            sections.append(
                f"  spec:{number} — {title} [{status}]"
                f"  (pass:{passed} fail:{failed} judgment:{judgment})"
            )
    else:
        sections.append("  No specs tracked.")
    sections.append("")

    # Committed files
    sections.append("Committed Files:")
    if committed:
        for fpath in committed:
            sections.append(f"  • {fpath}")
    else:
        sections.append("  No files committed.")
    sections.append("")

    # Invariants
    sections.append("Invariants:")
    sections.append(_format_invariant_summary(invariants))
    sections.append("")

    # Platform
    sections.append("Platform:")
    sections.append(_format_platform_summary(platform))
    sections.append("")

    # Next focus
    sections.append("Next Focus:")
    if next_focus:
        sections.append(_indent(next_focus))
    else:
        sections.append("  No next focus specified.")

    return "\n".join(sections)
