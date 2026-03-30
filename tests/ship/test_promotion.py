"""Tests for ship.promotion — test-to-production promotion flow."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from lib.python.ship.promotion import (
    PromotionResult,
    promote_to_production,
    resolve_feedback,
)
from lib.python.ship.state import PipelineRun, StepResult, ShipStateStore
from lib.python.ship.deploy import DeployTarget


@pytest.fixture
def store(tmp_path):
    s = ShipStateStore(db_path=str(tmp_path / "test.db"))
    yield s
    s.close()


class TestPromoteToProduction:
    def test_not_awaiting(self, store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="cli",
            status="shipped", created_at=time.time(),
        )
        store.save_run(run)
        result = promote_to_production("res1", store, str(tmp_path))
        assert result.status == "not_awaiting"

    def test_no_run(self, store, tmp_path):
        result = promote_to_production("nonexistent", store, str(tmp_path))
        assert result.status == "not_awaiting"

    @patch("lib.python.ship.promotion.load_targets")
    @patch("lib.python.ship.promotion.run_deploy")
    def test_successful_promotion(self, mock_deploy, mock_targets,
                                   store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="cli",
            status="awaiting_promotion", created_at=time.time(),
        )
        store.save_run(run)

        mock_targets.return_value = [
            DeployTarget(name="Production", command="echo prod",
                         role="production"),
        ]
        mock_deploy.return_value = type("R", (), {
            "ok": True, "output": "deployed", "url": "",
        })()

        result = promote_to_production("res1", store, str(tmp_path))
        assert result.status == "promoted"

        # Check run status updated
        updated = store.get_run("r1")
        assert updated.status == "shipped"

    @patch("lib.python.ship.promotion.load_targets")
    def test_no_prod_targets(self, mock_targets, store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="cli",
            status="awaiting_promotion", created_at=time.time(),
        )
        store.save_run(run)
        mock_targets.return_value = [
            DeployTarget(name="Test", command="echo", role="test"),
        ]

        result = promote_to_production("res1", store, str(tmp_path))
        assert result.status == "failed"
        assert "No production" in result.steps[0].detail


class TestResolveFeedback:
    @patch("lib.python.ship.promotion.log_scope_change")
    def test_resolve_clarifications(self, mock_log, store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="dashboard",
            status="awaiting_promotion", created_at=time.time(),
        )
        store.save_run(run)

        result = resolve_feedback(
            "res1", store, str(tmp_path),
            clarification_actions=["amend_and_redevelop"],
        )
        assert result["status"] == "resolved"
        assert len(result["items"]) == 1
        assert mock_log.called

    @patch("lib.python.ship.promotion.log_scope_change")
    def test_resolve_expansions(self, mock_log, store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="dashboard",
            status="awaiting_promotion", created_at=time.time(),
        )
        store.save_run(run)

        result = resolve_feedback(
            "res1", store, str(tmp_path),
            expansion_decisions=[
                {"issue": "search filter", "decision": "new_spec"},
            ],
        )
        assert result["status"] == "resolved"
        assert result["items"][0]["type"] == "expansion"

    def test_no_run(self, store, tmp_path):
        result = resolve_feedback("nope", store, str(tmp_path))
        assert result["status"] == "not_found"
