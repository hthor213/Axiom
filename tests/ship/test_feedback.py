"""Tests for ship.feedback — developer feedback classification."""

import pytest

from lib.python.ship.feedback import (
    FeedbackItem,
    FeedbackClassification,
    classify_feedback,
    _split_feedback,
)


class TestFeedbackItem:
    def test_to_dict(self):
        item = FeedbackItem(
            issue="labels wrong", category="clarification",
            spec_ref="spec:003", action="fix",
        )
        d = item.to_dict()
        assert d["issue"] == "labels wrong"
        assert d["category"] == "clarification"
        assert "options" not in d

    def test_to_dict_with_options(self):
        item = FeedbackItem(
            issue="new feature", category="expansion",
            options=["add_to_spec", "skip"],
        )
        d = item.to_dict()
        assert d["options"] == ["add_to_spec", "skip"]


class TestFeedbackClassification:
    def test_empty(self):
        fc = FeedbackClassification()
        d = fc.to_dict()
        assert d["clarifications"] == []
        assert d["expansions"] == []
        assert d["contradictions"] == []


class TestClassifyFeedback:
    def test_empty_feedback(self):
        result = classify_feedback("")
        assert result.clarifications == []
        assert result.expansions == []
        assert result.contradictions == []

    def test_clarification(self):
        result = classify_feedback("The labels show wrong values")
        assert len(result.clarifications) == 1
        assert result.clarifications[0].category == "clarification"

    def test_expansion(self):
        result = classify_feedback("We need a search filter for the list")
        assert len(result.expansions) == 1
        assert result.expansions[0].category == "expansion"
        assert "add_to_spec" in result.expansions[0].options

    def test_contradiction(self):
        result = classify_feedback(
            "Actually the enum should be free-text instead of fixed",
        )
        assert len(result.contradictions) == 1
        assert result.contradictions[0].category == "contradiction"

    def test_mixed_feedback(self):
        feedback = "The labels show wrong, also we need a search filter"
        result = classify_feedback(feedback)
        # Should have at least one clarification and one expansion
        total = (len(result.clarifications)
                 + len(result.expansions)
                 + len(result.contradictions))
        assert total >= 2

    def test_spec_refs_passed(self):
        result = classify_feedback(
            "Labels are broken",
            spec_refs=["spec:003"],
        )
        assert result.clarifications[0].spec_ref == "spec:003"


class TestSplitFeedback:
    def test_simple(self):
        parts = _split_feedback("one thing")
        assert len(parts) >= 1

    def test_comma_also(self):
        parts = _split_feedback("fix labels, also add sorting")
        assert len(parts) >= 2

    def test_semicolon_and(self):
        parts = _split_feedback("fix labels; and add search")
        assert len(parts) >= 2
