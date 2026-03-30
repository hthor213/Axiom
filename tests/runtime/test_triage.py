"""Tests for trajectory-aware test failure triage."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from lib.python.runtime.test_triage import (
    evaluate_trajectory,
    triage_test_failures,
    call_helper_model,
    _parse_helper_response,
)


class TestEvaluateTrajectory:

    def test_empty_history(self):
        assert evaluate_trajectory([], 100) == "improving"

    def test_first_attempt_low_failures(self):
        assert evaluate_trajectory([5], 100) == "almost_done"

    def test_first_attempt_moderate_failures(self):
        assert evaluate_trajectory([30], 100) == "improving"

    def test_first_attempt_catastrophic(self):
        assert evaluate_trajectory([60], 100) == "catastrophic"

    def test_eureka_moment(self):
        # 99 -> 2: massive improvement (>60%)
        assert evaluate_trajectory([99, 2], 100) == "almost_done"

    def test_eureka_not_almost_done(self):
        # 99 -> 30: big improvement but still >5% failing
        assert evaluate_trajectory([99, 30], 100) == "eureka"

    def test_stagnating_no_improvement(self):
        assert evaluate_trajectory([50, 50], 100) == "stagnating"

    def test_stagnating_tiny_improvement(self):
        # 100 -> 95: only 5% improvement
        assert evaluate_trajectory([100, 95], 200) == "stagnating"

    def test_improving_moderate(self):
        # 50 -> 35: 30% improvement
        assert evaluate_trajectory([50, 35], 100) == "improving"

    def test_getting_worse(self):
        assert evaluate_trajectory([50, 55], 100) == "stagnating"

    def test_multi_step_eureka(self):
        # 99 -> 96 -> 2: eureka on third step
        assert evaluate_trajectory([99, 96, 2], 100) == "almost_done"

    def test_almost_done_threshold(self):
        # Exactly 5% = almost_done
        assert evaluate_trajectory([5], 100) == "almost_done"
        # 6% = not almost_done
        assert evaluate_trajectory([6], 100) != "almost_done"

    def test_zero_total_tests(self):
        # Edge case: no tests at all
        assert evaluate_trajectory([0], 0) == "almost_done"


class TestTriageTestFailures:

    def _make_config(self):
        config = MagicMock()
        config.repo_root = "/fake/repo"
        return config

    def _make_emit(self):
        events = []
        return lambda name, data: events.append((name, data)), events

    def test_catastrophic_first_attempt(self):
        config = self._make_config()
        emit_fn, events = self._make_emit()
        history = []

        action, guidance, reset = triage_test_failures(
            10, 90, "lots of failures", history, config, emit_fn,
        )
        assert action == "retry"
        assert "50%" in guidance
        assert reset is False
        assert history == [90]

    @patch("lib.python.runtime.test_triage.call_helper_model")
    def test_catastrophic_second_attempt_stagnating_calls_helper(self, mock_helper):
        mock_helper.return_value = {
            "recommendation": "fix_code",
            "reasoning": "still broken",
            "guidance": "try again",
        }
        config = self._make_config()
        emit_fn, events = self._make_emit()
        history = [90]  # first catastrophic attempt already recorded

        action, guidance, reset = triage_test_failures(
            10, 85, "still failing", history, config, emit_fn,
        )
        # [90, 85] is stagnating but only 1 step — calls helper, retries
        assert action == "retry"
        mock_helper.assert_called_once()

    def test_catastrophic_twice_escalates(self):
        config = self._make_config()
        emit_fn, events = self._make_emit()
        # Two catastrophic failures (>50%)
        history = [90, 85, 83]  # two stagnating steps

        action, guidance, reset = triage_test_failures(
            12, 80, "still very broken", history, config, emit_fn,
        )
        # [90, 85, 83, 80] — 3 stagnating steps, escalates
        assert action == "waiting_for_human"

    @patch("lib.python.runtime.test_triage.call_helper_model")
    def test_minor_failure_calls_helper(self, mock_helper):
        mock_helper.return_value = {
            "recommendation": "fix_code",
            "reasoning": "test expects wrong value",
            "guidance": "change expected value to 42",
        }
        config = self._make_config()
        emit_fn, events = self._make_emit()
        history = []

        action, guidance, reset = triage_test_failures(
            98, 2, "2 tests failed", history, config, emit_fn,
        )
        assert action == "retry"
        assert "helper model" in guidance.lower()
        mock_helper.assert_called_once()

    @patch("lib.python.runtime.test_triage.call_helper_model")
    def test_eureka_resets_budget(self, mock_helper):
        mock_helper.return_value = {
            "recommendation": "fix_tests",
            "reasoning": "almost there",
            "guidance": "fix the last test",
        }
        config = self._make_config()
        emit_fn, events = self._make_emit()
        # Previous attempt had 99 failures, now only 30
        history = [99]

        action, guidance, reset = triage_test_failures(
            70, 30, "30 still failing", history, config, emit_fn,
        )
        assert action == "retry"
        assert reset is True  # eureka -> reset budget

    def test_improving_no_helper_needed(self):
        config = self._make_config()
        emit_fn, events = self._make_emit()
        history = [50]

        action, guidance, reset = triage_test_failures(
            70, 30, "30 still failing", history, config, emit_fn,
        )
        assert action == "retry"
        assert reset is False

    def test_stagnating_twice_escalates(self):
        config = self._make_config()
        emit_fn, events = self._make_emit()
        # Two stagnating steps already
        history = [50, 49]

        action, guidance, reset = triage_test_failures(
            52, 48, "48 failing", history, config, emit_fn,
        )
        assert action == "waiting_for_human"
        assert "ambiguous" in guidance.lower() or "stagnated" in guidance.lower()

    def test_history_is_mutated(self):
        config = self._make_config()
        emit_fn, _ = self._make_emit()
        history = []

        triage_test_failures(50, 50, "output", history, config, emit_fn)
        assert history == [50]

        triage_test_failures(60, 40, "output", history, config, emit_fn)
        assert history == [50, 40]

    def test_emits_triage_event(self):
        config = self._make_config()
        emit_fn, events = self._make_emit()

        triage_test_failures(90, 10, "output", [], config, emit_fn)
        triage_events = [e for e in events if e[0] == "test_triage"]
        assert len(triage_events) == 1
        assert triage_events[0][1]["trajectory"] == "improving"


class TestParseHelperResponse:

    def test_valid_json(self):
        text = '{"recommendation": "fix_code", "reasoning": "bug", "guidance": "fix it"}'
        result = _parse_helper_response(text)
        assert result["recommendation"] == "fix_code"

    def test_json_with_surrounding_text(self):
        text = 'Here is my analysis:\n{"recommendation": "fix_tests", "reasoning": "wrong assertion", "guidance": "update test"}\nDone.'
        result = _parse_helper_response(text)
        assert result["recommendation"] == "fix_tests"

    def test_invalid_json_fallback(self):
        text = "This is not JSON at all"
        result = _parse_helper_response(text)
        assert result["recommendation"] == "fix_code"
        assert "not JSON" in result["reasoning"]

    def test_markdown_code_block(self):
        text = '```json\n{"recommendation": "skip_tests", "reasoning": "irrelevant", "guidance": "skip"}\n```'
        result = _parse_helper_response(text)
        assert result["recommendation"] == "skip_tests"
