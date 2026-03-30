"""Tests for the plan-then-execute pipeline.

Tests: plan prompts, plan session output parsing, plan review,
TaskPlan model, and plan phase orchestration.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from runtime.plan_prompts import build_plan_prompt, build_full_spec_plan_prompt
from runtime.db_models import TaskPlan
from runtime.db_converters import row_to_plan
from runtime.agent_runner import _extract_text_from_stream


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """
# 030: Sample Feature

**Status:** draft

## Goal

Add a widget to the dashboard that shows real-time metrics.

## Done When
- [ ] Widget component renders on the dashboard
- [ ] Metrics API endpoint returns live data
- [x] Database schema supports metric storage
"""


# ---------------------------------------------------------------------------
# Plan prompt tests
# ---------------------------------------------------------------------------

class TestBuildPlanPrompt:
    def test_includes_mission(self):
        prompt = build_plan_prompt(
            "Widget component renders on the dashboard",
            "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "YOUR MISSION" in prompt
        assert "Widget component" in prompt

    def test_includes_spec_content(self):
        prompt = build_plan_prompt(
            "Metrics API endpoint", "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "## Full Spec" in prompt
        assert "## Goal" in prompt

    def test_includes_user_instructions(self):
        prompt = build_plan_prompt(
            "task", "030", "Sample Feature", SAMPLE_SPEC, "Use React hooks")
        assert "Use React hooks" in prompt

    def test_plan_only_instruction(self):
        prompt = build_plan_prompt(
            "task", "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "Do NOT execute any changes" in prompt


class TestBuildFullSpecPlanPrompt:
    def test_includes_mission(self):
        prompt = build_full_spec_plan_prompt(
            "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "YOUR MISSION" in prompt

    def test_includes_unchecked_criteria(self):
        prompt = build_full_spec_plan_prompt(
            "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "Widget component renders" in prompt
        assert "Metrics API endpoint" in prompt
        # Checked item should NOT appear in criteria
        assert "Database schema supports" not in prompt.split("Remaining Acceptance")[1]

    def test_milestone_instructions(self):
        prompt = build_full_spec_plan_prompt(
            "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "milestone" in prompt.lower()


# ---------------------------------------------------------------------------
# Stream text extraction tests
# ---------------------------------------------------------------------------

class TestExtractTextFromStream:
    def test_extracts_text_deltas(self):
        lines = [
            json.dumps({"event": {"type": "content_block_delta",
                                  "delta": {"type": "text_delta", "text": "Step 1: "}}}),
            json.dumps({"event": {"type": "content_block_delta",
                                  "delta": {"type": "text_delta", "text": "Create file.py"}}}),
        ]
        output = "\n".join(lines)
        assert _extract_text_from_stream(output) == "Step 1: Create file.py"

    def test_ignores_non_text_events(self):
        lines = [
            json.dumps({"event": {"type": "content_block_start",
                                  "content_block": {"type": "tool_use"}}}),
            json.dumps({"event": {"type": "content_block_delta",
                                  "delta": {"type": "text_delta", "text": "plan text"}}}),
        ]
        output = "\n".join(lines)
        assert _extract_text_from_stream(output) == "plan text"

    def test_handles_empty_output(self):
        assert _extract_text_from_stream("") == ""

    def test_handles_malformed_json(self):
        output = "not json\n{bad json\n"
        assert _extract_text_from_stream(output) == ""


# ---------------------------------------------------------------------------
# TaskPlan model and converter tests
# ---------------------------------------------------------------------------

class TestTaskPlan:
    def test_defaults(self):
        plan = TaskPlan()
        assert plan.status == "accepted"
        assert plan.plan_text == ""
        assert plan.mentor_feedback is None

    def test_row_to_plan(self):
        row = {
            "id": 1,
            "task_id": 42,
            "plan_text": "Step 1: do things",
            "mentor_feedback": "Also consider X",
            "status": "accepted",
            "created_at": "2026-03-29T10:00:00+00:00",
            "project_id": None,
        }
        plan = row_to_plan(row)
        assert plan.id == 1
        assert plan.task_id == 42
        assert plan.plan_text == "Step 1: do things"
        assert plan.mentor_feedback == "Also consider X"

    def test_row_to_plan_null_feedback(self):
        row = {
            "id": 2,
            "task_id": 43,
            "plan_text": "plan",
            "mentor_feedback": None,
            "status": "accepted",
            "created_at": None,
            "project_id": 5,
        }
        plan = row_to_plan(row)
        assert plan.mentor_feedback is None
        assert plan.project_id == 5


# ---------------------------------------------------------------------------
# Plan review tests (mocked GPT)
# ---------------------------------------------------------------------------

class TestPlanReview:
    @patch("runtime.plan_review._call_gpt")
    def test_review_plan_returns_feedback(self, mock_gpt):
        mock_gpt.return_value = "1. Also handle error cases"
        from runtime.plan_review import review_plan
        result = review_plan("Step 1: create widget", SAMPLE_SPEC,
                             ["Widget renders"], "/fake/root")
        assert "error cases" in result
        mock_gpt.assert_called_once()

    @patch("runtime.plan_review._call_gpt", side_effect=RuntimeError("No key"))
    def test_review_plan_graceful_failure(self, mock_gpt):
        from runtime.plan_review import review_plan
        result = review_plan("plan", SAMPLE_SPEC, [], "/fake/root")
        assert "unavailable" in result.lower()


# ---------------------------------------------------------------------------
# Code prompt plan_context integration tests
# ---------------------------------------------------------------------------

class TestPlanContextInPrompts:
    def test_code_prompt_includes_plan(self):
        from runtime.prompts import build_code_prompt
        prompt = build_code_prompt(
            "Build widget", "030", "Sample Feature",
            SAMPLE_SPEC, "", plan_context="## Your Plan\nStep 1: ...")
        assert "## Your Plan" in prompt
        assert "Step 1: ..." in prompt

    def test_code_prompt_no_plan(self):
        from runtime.prompts import build_code_prompt
        prompt = build_code_prompt(
            "Build widget", "030", "Sample Feature", SAMPLE_SPEC, "")
        assert "Your Plan" not in prompt

    def test_full_spec_prompt_includes_plan(self):
        from runtime.prompts import build_full_spec_prompt
        prompt = build_full_spec_prompt(
            "030", "Sample Feature", SAMPLE_SPEC, "",
            plan_context="## Your Plan\nMilestone 1")
        assert "## Your Plan" in prompt
        assert "Milestone 1" in prompt
