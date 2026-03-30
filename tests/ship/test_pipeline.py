"""Tests for ship.pipeline — core pipeline orchestration."""

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lib.python.ship.pipeline import (
    ShipOptions,
    ShipResult,
    run_pipeline,
)
from lib.python.ship.verify import (
    discover_and_run_tests as _discover_and_run_tests,
    check_spec_drift as _check_spec_drift,
    check_backlog as _check_backlog,
    _read_file,
)
from lib.python.ship.state import ShipStateStore, PipelineRun, StepResult


class TestShipOptions:
    def test_defaults(self):
        o = ShipOptions(root="/tmp")
        assert o.strategy == "pr"
        assert o.deploy is False
        assert o.dry_run is False
        assert o.no_tests is False
        assert o.actor == "cli"


class TestDiscoverAndRunTests:
    @patch("lib.python.ship.verify._run_cmd")
    def test_no_test_suite(self, mock_run, tmp_path):
        passed, detail = _discover_and_run_tests(str(tmp_path))
        assert passed is True
        assert "No test suite" in detail

    @patch("lib.python.ship.verify._run_cmd")
    def test_pytest_ini_found_passes(self, mock_run, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        passed, detail = _discover_and_run_tests(str(tmp_path))
        assert passed is True

    @patch("lib.python.ship.verify._run_cmd")
    def test_pytest_fails(self, mock_run, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        mock_run.return_value = MagicMock(
            returncode=1, stdout="FAILED test_foo", stderr="",
        )
        passed, detail = _discover_and_run_tests(str(tmp_path))
        assert passed is False
        assert "FAILED" in detail

    @patch("lib.python.ship.verify._run_cmd")
    def test_makefile_test_target(self, mock_run, tmp_path):
        (tmp_path / "Makefile").write_text("all:\n\techo hi\n\ntest:\n\tpytest\n")
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        passed, detail = _discover_and_run_tests(str(tmp_path))
        assert passed is True

    @patch("lib.python.ship.verify._run_cmd")
    def test_custom_test_command(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setenv("SHIP_TEST_COMMAND", "echo test")
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        passed, detail = _discover_and_run_tests(str(tmp_path))
        assert passed is True


class TestCheckSpecDrift:
    def test_no_specs(self, tmp_path):
        (tmp_path / "specs").mkdir()
        assert _check_spec_drift(str(tmp_path)) == ""

    def test_no_specs_dir(self, tmp_path):
        assert _check_spec_drift(str(tmp_path)) == ""


class TestCheckBacklog:
    def test_no_backlog(self, tmp_path):
        assert _check_backlog(str(tmp_path)) == ""

    def test_clean_backlog(self, tmp_path):
        (tmp_path / "BACKLOG.md").write_text(
            "## To Do\n- [ ] something\n\n## Done\n- finished task\n"
        )
        assert _check_backlog(str(tmp_path)) == ""

    def test_checked_not_in_done(self, tmp_path):
        (tmp_path / "BACKLOG.md").write_text(
            "## To Do\n- [x] finish widget\n\n## Done\n- other task\n"
        )
        result = _check_backlog(str(tmp_path))
        assert "checked items" in result


class TestRunPipeline:
    @pytest.fixture
    def store(self, tmp_path):
        s = ShipStateStore(db_path=str(tmp_path / "test.db"))
        yield s
        s.close()

    @patch("lib.python.ship.pipeline.do_verify")
    @patch("lib.python.ship.pipeline.do_commit")
    @patch("lib.python.ship.pipeline.do_push")
    @patch("lib.python.ship.pipeline.do_pr_or_merge")
    @patch("lib.python.ship.audit.log_step")
    def test_full_success(self, mock_log, mock_pr, mock_push,
                          mock_commit, mock_verify, store, tmp_path):
        mock_verify.return_value = StepResult(
            step="verify", status="ok", timestamp=time.time(),
        )
        mock_commit.return_value = StepResult(
            step="commit", status="ok", detail="sha: abc",
            timestamp=time.time(),
        )
        mock_push.return_value = StepResult(
            step="push", status="ok", timestamp=time.time(),
        )
        mock_pr.return_value = StepResult(
            step="pr_or_merge", status="ok", detail="PR created",
            timestamp=time.time(),
        )

        opts = ShipOptions(root=str(tmp_path), message="test",
                           result_id="res1")
        result = run_pipeline(opts, store=store)
        assert result.status == "shipped"
        assert len(result.steps) == 4

    @patch("lib.python.ship.pipeline.do_verify")
    @patch("lib.python.ship.audit.log_step")
    def test_verify_failure_stops_pipeline(self, mock_log, mock_verify,
                                            store, tmp_path):
        mock_verify.return_value = StepResult(
            step="verify", status="failed", detail="tests failed",
            timestamp=time.time(),
        )

        opts = ShipOptions(root=str(tmp_path), result_id="res2")
        result = run_pipeline(opts, store=store)
        assert result.status == "failed"
        assert len(result.steps) == 1

    def test_already_shipped(self, store, tmp_path):
        run = PipelineRun(
            run_id="r1", result_id="res3", actor="cli",
            status="shipped", created_at=time.time(),
        )
        store.save_run(run)

        opts = ShipOptions(root=str(tmp_path), result_id="res3")
        result = run_pipeline(opts, store=store)
        assert result.status == "already_shipped"
        assert result.run_id == "r1"

    @patch("lib.python.ship.pipeline.do_verify")
    @patch("lib.python.ship.pipeline.do_commit")
    @patch("lib.python.ship.pipeline.do_push")
    @patch("lib.python.ship.pipeline.do_pr_or_merge")
    @patch("lib.python.ship.audit.log_step")
    def test_resume_from_failure(self, mock_log, mock_pr, mock_push,
                                  mock_commit, mock_verify, store, tmp_path):
        """A failed run should be resumable."""
        # Create a run that failed at push
        run = PipelineRun(
            run_id="r_resume", result_id="res4", actor="cli",
            status="failed", created_at=time.time(),
            steps=[
                StepResult(step="verify", status="ok", timestamp=time.time()),
                StepResult(step="commit", status="ok", timestamp=time.time()),
                StepResult(step="push", status="failed", timestamp=time.time()),
            ],
        )
        store.save_run(run)

        mock_push.return_value = StepResult(
            step="push", status="ok", timestamp=time.time(),
        )
        mock_pr.return_value = StepResult(
            step="pr_or_merge", status="ok", timestamp=time.time(),
        )

        opts = ShipOptions(root=str(tmp_path), result_id="res4")
        result = run_pipeline(opts, store=store)
        assert result.status == "shipped"
        # verify and commit should have been skipped
        mock_verify.assert_not_called()
        mock_commit.assert_not_called()

    @patch("lib.python.ship.pipeline.do_verify")
    @patch("lib.python.ship.pipeline.do_commit")
    @patch("lib.python.ship.pipeline.do_push")
    @patch("lib.python.ship.pipeline.do_pr_or_merge")
    @patch("lib.python.ship.audit.log_step")
    def test_step_callback(self, mock_log, mock_pr, mock_push,
                           mock_commit, mock_verify, store, tmp_path):
        for mock in (mock_verify, mock_commit, mock_push, mock_pr):
            mock.return_value = StepResult(
                step="x", status="ok", timestamp=time.time(),
            )
        mock_verify.return_value.step = "verify"
        mock_commit.return_value.step = "commit"
        mock_push.return_value.step = "push"
        mock_pr.return_value.step = "pr_or_merge"

        callbacks = []
        opts = ShipOptions(root=str(tmp_path), result_id="res5")
        run_pipeline(opts, store=store,
                     on_step=lambda s, st: callbacks.append((s, st)))
        # Should have running + status for each step
        assert len(callbacks) == 8  # 4 steps x (running + status)
