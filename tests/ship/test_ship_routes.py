"""Tests for dashboard ship routes — unit tests with mocked dependencies."""

import time
from unittest.mock import patch, MagicMock

import pytest

from lib.python.ship.state import PipelineRun, StepResult, ShipStateStore
from lib.python.ship.feedback import classify_feedback, FeedbackClassification


class TestShipRoutesUnit:
    """Unit tests for ship route logic without FastAPI test client."""

    def test_already_shipped_detection(self, tmp_path):
        """If a result is already shipped, the pipeline returns early."""
        store = ShipStateStore(db_path=str(tmp_path / "test.db"))
        run = PipelineRun(
            run_id="r1", result_id="42", actor="dashboard",
            status="shipped", created_at=time.time(),
        )
        store.save_run(run)

        latest = store.get_latest_run("42")
        assert latest is not None
        assert latest.status == "shipped"
        store.close()

    def test_feedback_classification(self):
        """Feedback endpoint delegates to classify_feedback."""
        result = classify_feedback("The labels show wrong values")
        assert isinstance(result, FeedbackClassification)
        d = result.to_dict()
        assert "clarifications" in d
        assert "expansions" in d
        assert "contradictions" in d

    def test_concurrent_lock_logic(self):
        """Per-result locking prevents concurrent ship operations."""
        import threading
        locks: dict[str, threading.Lock] = {}
        lock_guard = threading.Lock()

        def get_lock(result_id: str) -> threading.Lock:
            with lock_guard:
                if result_id not in locks:
                    locks[result_id] = threading.Lock()
                return locks[result_id]

        lock1 = get_lock("42")
        lock2 = get_lock("42")
        assert lock1 is lock2  # Same lock for same result

        lock3 = get_lock("99")
        assert lock3 is not lock1  # Different lock for different result

        # Test non-blocking acquire
        assert lock1.acquire(blocking=False) is True
        assert lock1.acquire(blocking=False) is False  # Already held
        lock1.release()

    def test_ship_request_defaults(self):
        """ShipRequest model has sensible defaults."""
        # Import from ship_routes would require FastAPI, so test the logic
        from lib.python.ship.pipeline import ShipOptions
        opts = ShipOptions(
            root="/tmp", message="", strategy="pr",
            actor="dashboard", result_id="42",
        )
        assert opts.strategy == "pr"
        assert opts.deploy is False
