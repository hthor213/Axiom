"""Classify developer feedback into clarification, expansion, contradiction.

Takes free-text developer feedback and returns structured classification.
This is a deterministic classifier for common patterns; complex cases
can be delegated to an LLM by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FeedbackItem:
    """A single classified feedback item."""

    issue: str
    category: str  # clarification | expansion | contradiction
    spec_ref: Optional[str] = None
    action: str = ""
    options: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "issue": self.issue,
            "category": self.category,
            "spec_ref": self.spec_ref,
            "action": self.action,
        }
        if self.options:
            d["options"] = self.options
        return d


@dataclass
class FeedbackClassification:
    """Structured result of feedback classification."""

    clarifications: List[FeedbackItem] = field(default_factory=list)
    expansions: List[FeedbackItem] = field(default_factory=list)
    contradictions: List[FeedbackItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "clarifications": [c.to_dict() for c in self.clarifications],
            "expansions": [e.to_dict() for e in self.expansions],
            "contradictions": [c.to_dict() for c in self.contradictions],
        }


# Keywords that suggest scope expansion (new feature, not a fix)
_EXPANSION_SIGNALS = (
    "also need", "we need", "add a", "add an", "should also",
    "new feature", "can we add", "would be nice", "missing feature",
    "filter", "search", "sort", "export", "import",
)

# Keywords that suggest contradiction (changing existing spec)
_CONTRADICTION_SIGNALS = (
    "actually", "instead of", "should not", "shouldn't",
    "wrong approach", "change from", "replace with",
    "not what I meant", "opposite",
)

# Keywords that suggest clarification (fix/adjustment to existing behavior)
_CLARIFICATION_SIGNALS = (
    "wrong", "broken", "doesn't work", "shows wrong",
    "display", "label", "format", "alignment", "layout",
    "bug", "error", "incorrect", "misaligned",
)


def classify_feedback(
    feedback: str,
    spec_refs: Optional[List[str]] = None,
) -> FeedbackClassification:
    """Classify free-text feedback into structured categories.

    This is a heuristic classifier. For production use, the caller
    may supplement with LLM-based classification for ambiguous items.

    Args:
        feedback: Free-text developer feedback.
        spec_refs: Optional list of spec references for context.

    Returns:
        FeedbackClassification with items sorted into categories.
    """
    result = FeedbackClassification()
    if not feedback.strip():
        return result

    # Split feedback on common delimiters
    segments = _split_feedback(feedback)

    for segment in segments:
        item = _classify_segment(segment, spec_refs)
        if item.category == "clarification":
            result.clarifications.append(item)
        elif item.category == "expansion":
            result.expansions.append(item)
        elif item.category == "contradiction":
            result.contradictions.append(item)

    return result


def _split_feedback(text: str) -> List[str]:
    """Split feedback text into individual segments."""
    # Split on common delimiters: comma+also, "also", numbered items
    import re
    # Split on ", also" or ". also" or "; also" or newlines
    parts = re.split(r"[,;.]\s*(?:also|and)\s+|(?:\n\s*[-*]\s*)", text)
    # Also split on "also " at start of clause
    expanded = []
    for part in parts:
        sub = re.split(r"\balso\b", part, maxsplit=1)
        expanded.extend(sub)
    return [p.strip() for p in expanded if p.strip()]


def _classify_segment(
    segment: str,
    spec_refs: Optional[List[str]],
) -> FeedbackItem:
    """Classify a single feedback segment."""
    lower = segment.lower()

    # Check contradiction first (strongest signal)
    for signal in _CONTRADICTION_SIGNALS:
        if signal in lower:
            return FeedbackItem(
                issue=segment,
                category="contradiction",
                spec_ref=spec_refs[0] if spec_refs else None,
                action="requires decision",
                options=["update_spec", "keep_current"],
            )

    # Check expansion
    for signal in _EXPANSION_SIGNALS:
        if signal in lower:
            return FeedbackItem(
                issue=segment,
                category="expansion",
                spec_ref=None,
                action="requires decision",
                options=["add_to_spec", "new_spec", "skip"],
            )

    # Default to clarification
    return FeedbackItem(
        issue=segment,
        category="clarification",
        spec_ref=spec_refs[0] if spec_refs else None,
        action="amend spec and redevelop",
    )
