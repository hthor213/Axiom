"""Tests for ship.state — SQLite-backed pipeline run persistence."""

import time
from pathlib import Path

import pytest

from lib.python.ship.state import (
    StepResult,
    PipelineRun,
    ShipStateStore,
    generate_run_id,
    STEP_NAMES,
    VALID_STATUSES,
)


class TestStepResult:
    def test_defaults(self):
        s = StepResult(step="verify", status="ok")
        assert s.detail == ""
        assert s.timestamp == 0.0

    def test_round_trip(self):
        s = StepResult(step="push", status="failed", detail="rejected", timestamp=1.0)
        d = s.to_dict()
        s2 = StepResult.from_dict(d)
        assert s2.step == "push"
        assert s2.status == "failed"
        assert s2.detail == "rejected"

    def test_to_dict_keys(self):
        s = StepResult(step="commit", status="ok")
        d = s.to_dict()
        assert set(d.keys()) == {"step", "status", "detail", "timestamp"}


class TestPipelineRun:
    def test_defaults(self):
        r = PipelineRun(run_id="r1", result_id="res1", actor="cli")
        assert r.strategy == "pr"
        assert r.status == "running"
        assert r.steps == []

    def test_to_dict(self):
        r = PipelineRun(
            run_id="r1", result_id="res1", actor="dashboard",
            steps=[StepResult(step="verify", status="ok")],
        )
        d = r.to_dict()
        assert d["run_id"] == "r1"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["step"] == "verify"


class TestGenerateRunId:
    def test_format(self):
        rid = generate_run_id()
        assert rid.startswith("run_")
        assert len(rid) == 16  # run_ + 12 hex chars

    def test_unique(self):
        ids = {generate_run_id() for _ in range(100)}
        assert len(ids) == 100


class TestShipStateStore:
    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test_ship.db")
        s = ShipStateStore(db_path=db_path)
        yield s
        s.close()

    def test_save_and_get(self, store):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="cli",
            created_at=time.time(),
        )
        store.save_run(run)
        loaded = store.get_run("r1")
        assert loaded is not None
        assert loaded.run_id == "r1"
        assert loaded.result_id == "res1"

    def test_get_nonexistent(self, store):
        assert store.get_run("nope") is None

    def test_upsert(self, store):
        run = PipelineRun(
            run_id="r1", result_id="res1", actor="cli",
            status="running", created_at=time.time(),
        )
        store.save_run(run)
        run.status = "shipped"
        run.steps.append(StepResult(step="verify", status="ok"))
        store.save_run(run)
        loaded = store.get_run("r1")
        assert loaded.status == "shipped"
        assert len(loaded.steps) == 1

    def test_get_runs_for_result(self, store):
        t = time.time()
        for i in range(3):
            run = PipelineRun(
                run_id=f"r{i}", result_id="res1", actor="cli",
                created_at=t + i,
            )
            store.save_run(run)
        runs = store.get_runs_for_result("res1")
        assert len(runs) == 3
        # Most recent first
        assert runs[0].run_id == "r2"

    def test_get_latest_run(self, store):
        t = time.time()
        store.save_run(PipelineRun(run_id="old", result_id="r1",
                                   actor="cli", created_at=t))
        store.save_run(PipelineRun(run_id="new", result_id="r1",
                                   actor="cli", created_at=t + 1))
        latest = store.get_latest_run("r1")
        assert latest.run_id == "new"

    def test_get_latest_run_none(self, store):
        assert store.get_latest_run("nope") is None

    def test_purge_old_runs(self, store):
        old_time = time.time() - (8 * 86400)  # 8 days ago
        store.save_run(PipelineRun(run_id="old", result_id="r1",
                                   actor="cli", created_at=old_time))
        store.save_run(PipelineRun(run_id="new", result_id="r1",
                                   actor="cli", created_at=time.time()))
        purged = store.purge_old_runs()
        assert purged == 1
        assert store.get_run("old") is None
        assert store.get_run("new") is not None


class TestConstants:
    def test_step_names(self):
        assert "verify" in STEP_NAMES
        assert "commit" in STEP_NAMES
        assert "push" in STEP_NAMES
        assert "deploy" in STEP_NAMES

    def test_valid_statuses(self):
        assert "ok" in VALID_STATUSES
        assert "failed" in VALID_STATUSES
        assert "awaiting_promotion" in VALID_STATUSES
