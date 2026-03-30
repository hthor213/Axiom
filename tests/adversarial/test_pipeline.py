"""Tests for the adversarial evaluation pipeline.

Tests parsers, counter-rebuttal logic, debate flow, and report generation.
"""
import pytest

from lib.python.adversarial.prompts import (
    parse_challenger_response,
    parse_author_response,
    parse_arbiter_response,
    parse_counter_rebuttal_response,
    build_counter_rebuttal_prompt,
)
from lib.python.adversarial.report import generate_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeModels:
    anthropic = "claude-test"
    google = "gemini-test"
    openai = "gpt-test"


@pytest.fixture
def models():
    return FakeModels()


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseChallenger:
    def test_parses_issues(self):
        text = """\
## Summary
Missing error handling in two modules.

## Issues
### issue-1: [severity: high] [file: server.py:42]
Category: bug
The function does not handle None input.

### issue-2: [severity: low] [file: utils.py:10]
Category: performance
Unnecessary list copy on every call.
"""
        result = parse_challenger_response(text)
        assert len(result["issues"]) == 2
        assert result["issues"][0]["severity"] == "high"
        assert result["issues"][0]["file"] == "server.py"
        assert result["issues"][0]["line"] == 42
        assert result["issues"][1]["severity"] == "low"
        assert result["summary"] == "Missing error handling in two modules."

    def test_no_issues(self):
        text = """\
## Summary
No issues found.

## Issues
No issues found.
"""
        result = parse_challenger_response(text)
        assert len(result["issues"]) == 0

    def test_parses_spec_alignment_with_category_d(self):
        text = """\
## Summary
Missing implementation.

## Issues
### issue-1: [severity: high] [file: api.py:1]
Category: design
No authentication middleware.

## Spec Alignment
### change-1: [category: A] [spec_item: "API returns JSON"]
Endpoint returns JSON as specified.

### change-2: [category: D] [spec_item: "Authentication required"]
No auth code found despite spec requirement.
"""
        result = parse_challenger_response(text)
        assert len(result["spec_alignment"]) == 2
        assert result["spec_alignment"][0]["category"] == "A"
        assert result["spec_alignment"][1]["category"] == "D"
        assert result["spec_alignment"][1]["spec_item"] == "Authentication required"


class TestParseAuthor:
    def test_parses_accept_and_rebut(self):
        text = """\
## Summary
One valid issue, one false positive.

## Responses
### issue-1: ACCEPT
Valid point, will fix the None check.

### issue-2: REBUT
The list copy is needed for thread safety — the caller mutates the list.
"""
        result = parse_author_response(text)
        assert result["accepted_count"] == 1
        assert result["rebutted_count"] == 1
        assert result["unresolved"] == ["issue-2"]


class TestParseCounterRebuttal:
    def test_parses_concede_and_maintain(self):
        text = """\
## Summary
One rebuttal holds, one does not.

## Counter-Rebuttals
### issue-2: CONCEDE
Fair point about thread safety. The copy is justified.

### issue-3: MAINTAIN
The author claims the timeout is sufficient but provides no evidence.
Under load, 100ms will not be enough.
"""
        result = parse_counter_rebuttal_response(text)
        assert result["conceded_count"] == 1
        assert result["maintained_count"] == 1
        assert result["maintained_ids"] == ["issue-3"]
        assert result["counter_rebuttals"][0]["verdict"] == "concede"
        assert result["counter_rebuttals"][1]["verdict"] == "maintain"

    def test_all_conceded(self):
        text = """\
## Summary
All rebuttals are valid.

## Counter-Rebuttals
### issue-1: CONCEDE
The author is correct.
"""
        result = parse_counter_rebuttal_response(text)
        assert result["conceded_count"] == 1
        assert result["maintained_count"] == 0
        assert result["maintained_ids"] == []

    def test_all_maintained(self):
        text = """\
## Summary
None of the rebuttals hold up.

## Counter-Rebuttals
### issue-1: MAINTAIN
Still broken.

### issue-2: MAINTAIN
Still wrong.
"""
        result = parse_counter_rebuttal_response(text)
        assert result["conceded_count"] == 0
        assert result["maintained_count"] == 2
        assert result["maintained_ids"] == ["issue-1", "issue-2"]


class TestParseArbiter:
    def test_parses_rulings(self):
        text = """\
## Summary
Mixed results.

## Rulings
### issue-3: CHALLENGER [confidence: high]
The timeout is indeed too short for production load.

### issue-4: AUTHOR [confidence: medium]
The error handling is adequate for this context.
"""
        result = parse_arbiter_response(text)
        assert len(result["rulings"]) == 2
        assert result["rulings"][0]["side"] == "challenger"
        assert result["rulings"][0]["confidence"] == "high"
        assert result["rulings"][1]["side"] == "author"


# ---------------------------------------------------------------------------
# Counter-rebuttal prompt builder
# ---------------------------------------------------------------------------

class TestBuildCounterRebuttalPrompt:
    def test_only_includes_rebutted_issues(self):
        challenger = {
            "issues": [
                {"id": "issue-1", "severity": "high", "file": "a.py",
                 "line": 1, "description": "Bug A"},
                {"id": "issue-2", "severity": "low", "file": "b.py",
                 "line": 5, "description": "Bug B"},
            ]
        }
        author = {
            "responses": [
                {"issue_id": "issue-1", "verdict": "accept", "reasoning": "OK"},
                {"issue_id": "issue-2", "verdict": "rebut",
                 "reasoning": "Not a bug because X"},
            ]
        }
        prompt = build_counter_rebuttal_prompt(challenger, author, round_num=0)
        assert "issue-1" not in prompt  # accepted, not included
        assert "issue-2" in prompt
        assert "Not a bug because X" in prompt


# ---------------------------------------------------------------------------
# Report generation with counter-rebuttal
# ---------------------------------------------------------------------------

class TestReportWithDebate:
    def test_conceded_issues_are_author_wins(self, models):
        challenger = {
            "issues": [
                {"id": "issue-1", "severity": "high", "file": "a.py",
                 "line": 1, "category": "bug", "description": "Bug"},
                {"id": "issue-2", "severity": "medium", "file": "b.py",
                 "line": 5, "category": "design", "description": "Bad design"},
            ]
        }
        author = {
            "responses": [
                {"issue_id": "issue-1", "verdict": "rebut"},
                {"issue_id": "issue-2", "verdict": "rebut"},
            ],
            "accepted_count": 0,
            "rebutted_count": 2,
        }
        counter_rebuttal = {
            "counter_rebuttals": [
                {"issue_id": "issue-1", "verdict": "concede", "reasoning": "OK"},
                {"issue_id": "issue-2", "verdict": "maintain", "reasoning": "No"},
            ],
            "conceded_count": 1,
            "maintained_count": 1,
            "maintained_ids": ["issue-2"],
        }
        # No arbiter — issue-2 maintained but unresolved
        report = generate_report(
            models, challenger, author, None, ["a.py", "b.py"],
            counter_rebuttal=counter_rebuttal,
            debate_history=[{
                "round": 1, "author_accepted": 0, "author_rebutted": 2,
                "challenger_conceded": 1, "challenger_maintained": 1,
            }],
        )

        issues_by_id = {i["id"]: i for i in report["issues"]}
        assert issues_by_id["issue-1"]["final_side"] == "author"
        assert issues_by_id["issue-1"]["resolution"] == "challenger_conceded"
        assert issues_by_id["issue-2"]["final_side"] == "author"  # no arbiter, rebuttal stands
        assert issues_by_id["issue-2"]["resolution"] == "rebuttal_uncontested"

    def test_maintained_issue_goes_to_arbiter(self, models):
        challenger = {
            "issues": [
                {"id": "issue-1", "severity": "critical", "file": "a.py",
                 "line": 1, "category": "security", "description": "SQL injection"},
            ]
        }
        author = {
            "responses": [
                {"issue_id": "issue-1", "verdict": "rebut"},
            ],
            "accepted_count": 0,
            "rebutted_count": 1,
        }
        counter_rebuttal = {
            "counter_rebuttals": [
                {"issue_id": "issue-1", "verdict": "maintain", "reasoning": "Still bad"},
            ],
            "conceded_count": 0,
            "maintained_count": 1,
            "maintained_ids": ["issue-1"],
        }
        arbiter = {
            "rulings": [
                {"issue_id": "issue-1", "side": "challenger", "confidence": "high",
                 "reasoning": "This is indeed SQL injection."},
            ],
            "summary": "Challenger is right.",
        }
        report = generate_report(
            models, challenger, author, arbiter, ["a.py"],
            counter_rebuttal=counter_rebuttal,
            debate_history=[{
                "round": 1, "author_accepted": 0, "author_rebutted": 1,
                "challenger_conceded": 0, "challenger_maintained": 1,
            }],
        )

        assert report["verdict"] == "FAIL"
        assert report["issues"][0]["final_side"] == "challenger"
        assert report["issues"][0]["resolution"] == "arbiter"

    def test_debate_section_in_report(self, models):
        report = generate_report(
            models, {"issues": []}, {}, None, ["a.py"],
            debate_history=[
                {"round": 1, "author_accepted": 1, "author_rebutted": 2,
                 "challenger_conceded": 1, "challenger_maintained": 1},
                {"round": 2, "author_accepted": 0, "author_rebutted": 1,
                 "challenger_conceded": 1, "challenger_maintained": 0},
            ],
        )
        assert report["debate"]["rounds"] == 2
        assert len(report["debate"]["history"]) == 2

    def test_no_debate_when_no_counter_rebuttal(self, models):
        report = generate_report(
            models, {"issues": []}, {}, None, ["a.py"],
        )
        assert report["debate"]["rounds"] == 0

    def test_accepted_issues_still_challenger_wins(self, models):
        challenger = {
            "issues": [
                {"id": "issue-1", "severity": "high", "file": "a.py",
                 "line": 1, "category": "bug", "description": "Real bug"},
            ]
        }
        author = {
            "responses": [
                {"issue_id": "issue-1", "verdict": "accept"},
            ],
            "accepted_count": 1,
            "rebutted_count": 0,
        }
        report = generate_report(
            models, challenger, author, None, ["a.py"],
        )
        assert report["issues"][0]["final_side"] == "challenger"
        assert report["issues"][0]["resolution"] == "author_accepted"
        assert report["verdict"] == "FAIL"  # high severity = FAIL
