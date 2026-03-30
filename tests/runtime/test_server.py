"""Tests for the runtime server (mocked PostgreSQL, no real agents)."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

from lib.python.runtime.db import TaskStore, Task
from lib.python.runtime.server import RuntimeServer, RuntimeConfig


@pytest.fixture
def store():
    """Create a TaskStore with mocked PostgreSQL connection."""
    from tests.runtime.test_db import _make_mock_store, MockConnection
    s = _make_mock_store()
    s._connect = lambda: MockConnection(s)

    from tests.runtime.test_db import MockCursor
    s._dict_cursor = lambda conn: MockCursor(s, dict_mode=True)
    return s


@pytest.fixture
def config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    os.system(f"cd {repo} && git init && git checkout -b main 2>/dev/null")
    readme = repo / "README.md"
    readme.write_text("# test\n")
    os.system(
        f"cd {repo} && git add . && "
        f"GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=t@t.com "
        f"GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=t@t.com "
        f"git commit -m init --no-verify 2>/dev/null"
    )
    return RuntimeConfig(
        repo_root=str(repo),
        max_turns_per_task=5,
        time_limit_per_task_min=1,
        max_consecutive_failures=2,
        max_total_runtime_min=5,
        worktree_dir=str(tmp_path / "worktrees"),
        telegram_notify=False,
        run_adversarial=False,
    )


class TestRuntimeServerEmptyQueue:

    def test_process_empty_queue(self, store, config):
        server = RuntimeServer(store, config)
        run = server.process_queue()
        assert run.status == "completed"
        assert run.tasks_completed == 0
        assert run.tasks_failed == 0


class TestRuntimeServerProgressEvents:

    def test_emits_run_started(self, store, config):
        events = []
        server = RuntimeServer(store, config)
        server.set_progress_callback(lambda e: events.append(e))
        server.process_queue()
        assert any(e["type"] == "run_started" for e in events)
        assert any(e["type"] == "run_finished" for e in events)


class TestRuntimeServerStop:

    def test_stop_signal(self, store, config):
        """Server respects stop signal."""
        store.enqueue_task(Task(spec_number="014", spec_title="T",
                                done_when_item="build something"))

        server = RuntimeServer(store, config)
        server.stop()
        run = server.process_queue()
        assert run.stop_reason == "Stopped by signal"


class TestRuntimeServerConsecutiveFailures:

    @patch("lib.python.runtime.server.run_agent_session")
    @patch("lib.python.runtime.server.create_worktree")
    @patch("lib.python.runtime.server.cleanup_worktree")
    def test_stops_on_consecutive_failures(self, mock_cleanup, mock_wt,
                                            mock_agent, store, config):
        """Server stops after max consecutive failures."""
        from lib.python.runtime.worktree import Worktree

        mock_wt.return_value = Worktree(
            path="/tmp/fake", branch="auto/test", base_branch="main",
            base_commit="abc123", task_id=1, spec_number="014",
        )
        mock_agent.side_effect = RuntimeError("agent failed")
        mock_cleanup.return_value = True

        config.max_consecutive_failures = 2
        store.enqueue_task(Task(spec_number="014", spec_title="T1",
                                done_when_item="item 1"))
        store.enqueue_task(Task(spec_number="014", spec_title="T2",
                                done_when_item="item 2"))
        store.enqueue_task(Task(spec_number="014", spec_title="T3",
                                done_when_item="item 3"))

        server = RuntimeServer(store, config)
        run = server.process_queue()
        assert "consecutive failures" in run.stop_reason
        assert run.tasks_failed == 2


class TestRuntimeConfig:

    def test_defaults(self):
        config = RuntimeConfig(repo_root="/tmp/test")
        assert config.max_turns_per_task == 30
        assert config.time_limit_per_task_min == 60
        assert config.max_failures_per_task == 3
        assert config.max_consecutive_failures == 3
        assert config.max_total_runtime_min == 360
        assert config.base_branch == "main"
        assert config.telegram_notify is True
