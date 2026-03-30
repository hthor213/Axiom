"""Tests for ship.audit — JSONL audit logging."""

import json
import os
from pathlib import Path

import pytest

from lib.python.ship.audit import log_step, log_scope_change
from lib.python.ship.state import PipelineRun, StepResult
from lib.python.ship.pipeline import ShipOptions


@pytest.fixture
def run():
    return PipelineRun(
        run_id="r_test", result_id="res_test", actor="cli",
    )


@pytest.fixture
def opts(tmp_path):
    return ShipOptions(root=str(tmp_path), actor="cli", result_id="res_test")


class TestLogStep:
    def test_creates_log_file(self, run, opts, tmp_path):
        step = StepResult(step="verify", status="ok", detail="all good")
        log_step(run, step, opts)

        log_path = tmp_path / "logs" / "ship.log"
        assert log_path.exists()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["run_id"] == "r_test"
        assert entry["step"] == "verify"
        assert entry["status"] == "ok"
        assert "timestamp" in entry

    def test_appends_multiple_entries(self, run, opts, tmp_path):
        for step_name in ("verify", "commit", "push"):
            step = StepResult(step=step_name, status="ok")
            log_step(run, step, opts)

        log_path = tmp_path / "logs" / "ship.log"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_log_fields(self, run, opts, tmp_path):
        step = StepResult(step="push", status="failed", detail="rejected")
        log_step(run, step, opts)

        log_path = tmp_path / "logs" / "ship.log"
        entry = json.loads(log_path.read_text().strip())
        assert entry["actor"] == "cli"
        assert entry["result_id"] == "res_test"
        assert entry["detail"] == "rejected"


class TestLogScopeChange:
    def test_scope_change_entry(self, run, opts, tmp_path):
        log_scope_change(run, "clarification", "labels fixed", opts)

        log_path = tmp_path / "logs" / "ship.log"
        entry = json.loads(log_path.read_text().strip())
        assert entry["step"] == "scope_change"
        assert entry["reason"] == "clarification"
        assert entry["detail"] == "labels fixed"
