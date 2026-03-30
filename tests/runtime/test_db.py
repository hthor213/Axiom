"""Tests for runtime database operations (PostgreSQL backend, mocked)."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from lib.python.runtime.db import TaskStore, Task, Run, AgentSession, Result


def _make_mock_store():
    """Create a TaskStore with a mocked PostgreSQL connection that uses in-memory dicts."""
    store = TaskStore.__new__(TaskStore)
    store._pg_conn_string = "postgresql://mock"

    # In-memory storage
    store._tables = {
        "tasks": [],
        "runs": [],
        "agent_sessions": [],
        "results": [],
        "draft_reviews": [],
    }
    store._sequences = {t: 0 for t in store._tables}
    return store


class MockCursor:
    """Simulates psycopg2 cursor with in-memory storage."""

    def __init__(self, store, dict_mode=False):
        self._store = store
        self._dict_mode = dict_mode
        self._results = []
        self._rowcount = 0

    def execute(self, sql, params=None):
        sql_lower = sql.strip().lower()
        # Route to appropriate handler
        if sql_lower.startswith("insert into tasks"):
            self._handle_insert("tasks", params, sql)
        elif sql_lower.startswith("insert into runs"):
            self._handle_insert("runs", params, sql)
        elif sql_lower.startswith("insert into agent_sessions"):
            self._handle_insert("agent_sessions", params, sql)
        elif sql_lower.startswith("insert into results"):
            self._handle_insert("results", params, sql)
        elif sql_lower.startswith("update tasks set status"):
            if "where id = (" in sql_lower:
                # claim_next_task
                self._handle_claim()
            elif "where status in" in sql_lower:
                # cleanup_rejected_tasks
                self._rowcount = 0
                self._results = []
            else:
                self._handle_update("tasks", params, sql_lower)
        elif sql_lower.startswith("update runs"):
            self._handle_update("runs", params, sql_lower)
        elif sql_lower.startswith("update agent_sessions"):
            self._handle_update("agent_sessions", params, sql_lower)
        elif sql_lower.startswith("update results"):
            self._handle_update("results", params, sql_lower)
        elif "count(*)" in sql_lower:
            self._handle_count(params, sql_lower)
        elif sql_lower.startswith("select") and "from tasks" in sql_lower:
            self._handle_select("tasks", params, sql_lower)
        elif sql_lower.startswith("select") and "from runs" in sql_lower:
            self._handle_select("runs", params, sql_lower)
        elif sql_lower.startswith("select") and "from agent_sessions" in sql_lower:
            self._handle_select("agent_sessions", params, sql_lower)
        elif sql_lower.startswith("select") and "from results" in sql_lower:
            self._handle_select("results", params, sql_lower)
        else:
            self._results = []

    def _next_id(self, table):
        self._store._sequences[table] += 1
        return self._store._sequences[table]

    def _handle_insert(self, table, params, sql):
        row_id = self._next_id(table)
        row = {"id": row_id}
        # Map params based on table
        if table == "tasks":
            keys = ["spec_number", "spec_title", "done_when_item", "status",
                     "priority", "branch_name", "worktree_path", "queued_by", "user_instructions"]
            for i, k in enumerate(keys):
                row[k] = params[i] if i < len(params) else None
            row.update({"base_commit": None, "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T00:00:00"})
        elif table == "runs":
            row.update({"status": params[0], "config": params[1] if len(params) > 1 else "{}",
                        "started_at": "2026-01-01T00:00:00", "finished_at": None,
                        "stop_reason": None, "tasks_completed": 0, "tasks_failed": 0,
                        "total_turns": 0, "total_api_calls": 0})
        elif table == "agent_sessions":
            keys = ["task_id", "run_id", "status", "max_turns", "time_limit_min", "max_failures"]
            for i, k in enumerate(keys):
                row[k] = params[i] if i < len(params) else None
            row.update({"started_at": "2026-01-01T00:00:00", "finished_at": None,
                        "turns_used": 0, "failure_count": 0, "last_tool_call": None,
                        "last_output": None, "error": None})
        elif table == "results":
            keys = ["task_id", "session_id", "branch_name", "commit_sha", "diff_summary",
                    "test_passed", "test_failed", "test_output", "adversarial_verdict",
                    "adversarial_report", "harness_check", "approved"]
            for i, k in enumerate(keys):
                row[k] = params[i] if i < len(params) else None
            row.update({"created_at": "2026-01-01T00:00:00", "approved_at": None,
                        "reject_reason": None})
        self._store._tables[table].append(row)
        if table == "runs":
            self._results = [(row_id, "2026-01-01T00:00:00")]
        else:
            self._results = [(row_id,)]

    def _handle_update(self, table, params, sql_lower):
        # Find the row by ID (last param)
        row_id = params[-1]
        for row in self._store._tables[table]:
            if row["id"] == row_id:
                if "status" in sql_lower and table == "tasks":
                    row["status"] = params[0]
                    idx = 1
                    if "branch_name" in sql_lower:
                        row["branch_name"] = params[idx]
                        idx += 1
                    if "worktree_path" in sql_lower:
                        row["worktree_path"] = params[idx]
                        idx += 1
                    if "base_commit" in sql_lower:
                        row["base_commit"] = params[idx]
                elif table == "runs":
                    row["status"] = params[0]
                    row["stop_reason"] = params[1]
                    row["tasks_completed"] = params[2]
                    row["tasks_failed"] = params[3]
                    row["total_turns"] = params[4]
                    row["total_api_calls"] = params[5]
                    row["finished_at"] = "2026-01-01T01:00:00"
                elif table == "agent_sessions":
                    # Generic kwargs update
                    pass
                elif table == "results" and "approved" in sql_lower:
                    row["approved"] = params[0]
                    row["reject_reason"] = params[1]
                    row["approved_at"] = "2026-01-01T01:00:00"
                break
        self._results = []

    def _handle_select(self, table, params, sql_lower):
        rows = self._store._tables[table]
        if "where id=" in sql_lower.replace(" ", ""):
            target_id = params[0] if params else None
            rows = [r for r in rows if r["id"] == target_id]
        elif "status='queued'" in sql_lower:
            rows = [r for r in rows if r["status"] == "queued"]
            rows.sort(key=lambda r: (r.get("priority", 100), r["id"]))
        elif "status='running'" in sql_lower:
            rows = [r for r in rows if r["status"] == "running"]
        if "task_id=" in sql_lower.replace(" ", "") and params:
            target = params[0]
            rows = [r for r in rows if r.get("task_id") == target]
        if "approved is null" in sql_lower:
            rows = [r for r in rows if r.get("approved") is None]
        if "order by id desc" in sql_lower:
            rows = sorted(rows, key=lambda r: r["id"], reverse=True)
        if "limit" in sql_lower and params:
            limit_val = params[-1] if isinstance(params[-1], int) else None
            if limit_val:
                rows = rows[:limit_val]
        self._results = rows

    def _handle_claim(self):
        rows = [r for r in self._store._tables["tasks"] if r["status"] == "queued"]
        rows.sort(key=lambda r: (r.get("priority", 100), r["id"]))
        if rows:
            rows[0]["status"] = "running"
            rows[0]["updated_at"] = "2026-01-01T01:00:00"
            self._results = [rows[0]]
        else:
            self._results = [None]

    def _handle_count(self, params, sql_lower):
        count = 0
        if "from tasks" in sql_lower and params:
            for r in self._store._tables["tasks"]:
                if (r["spec_number"] == params[0] and
                    r["done_when_item"] == params[1] and
                    r["status"] in ("queued", "running", "waiting_for_human")):
                    count += 1
        self._results = [(count,)]

    def fetchone(self):
        if self._results:
            row = self._results[0]
            if isinstance(row, dict) and self._dict_mode:
                return row
            return row
        return None

    def fetchall(self):
        return self._results

    @property
    def rowcount(self):
        return self._rowcount

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockConnection:
    def __init__(self, store, dict_mode=False):
        self._store = store
        self._dict_mode = dict_mode

    def cursor(self, cursor_factory=None):
        return MockCursor(self._store, dict_mode=cursor_factory is not None)

    def commit(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def store():
    """Create a TaskStore with mocked PostgreSQL."""
    s = _make_mock_store()
    # Patch _connect to return our mock connection
    s._connect = lambda: MockConnection(s)
    s._dict_cursor = lambda conn: MockCursor(s, dict_mode=True)

    # Override _dict_cursor to return a context manager
    original_dict_cursor = s._dict_cursor

    def patched_dict_cursor(conn):
        return MockCursor(s, dict_mode=True)

    s._dict_cursor = patched_dict_cursor
    return s


class TestTaskOperations:

    def test_enqueue_task(self, store):
        task = Task(spec_number="014", spec_title="Autonomous Runtime",
                    done_when_item="Agent SDK session runs")
        result = store.enqueue_task(task)
        assert result.id is not None
        assert result.id > 0
        assert result.status == "queued"

    def test_get_queued_tasks(self, store):
        store.enqueue_task(Task(spec_number="014", spec_title="T1",
                                done_when_item="item 1", priority=50))
        store.enqueue_task(Task(spec_number="015", spec_title="T2",
                                done_when_item="item 2", priority=10))
        store.enqueue_task(Task(spec_number="016", spec_title="T3",
                                done_when_item="item 3", priority=30))

        tasks = store.get_queued_tasks()
        assert len(tasks) == 3
        assert tasks[0].spec_number == "015"  # priority 10
        assert tasks[1].spec_number == "016"  # priority 30
        assert tasks[2].spec_number == "014"  # priority 50

    def test_get_task(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        fetched = store.get_task(task.id)
        assert fetched is not None
        assert fetched.spec_number == "014"
        assert fetched.done_when_item == "item"

    def test_get_nonexistent_task(self, store):
        assert store.get_task(999) is None

    def test_update_task_status(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        store.update_task_status(task.id, "running",
                                 branch_name="auto/spec-014-task-1",
                                 worktree_path="/tmp/worktree")
        updated = store.get_task(task.id)
        assert updated.status == "running"
        assert updated.branch_name == "auto/spec-014-task-1"
        assert updated.worktree_path == "/tmp/worktree"

    def test_get_all_tasks(self, store):
        store.enqueue_task(Task(spec_number="014", spec_title="T1",
                                done_when_item="item 1"))
        store.enqueue_task(Task(spec_number="015", spec_title="T2",
                                done_when_item="item 2"))
        store.update_task_status(1, "passed")
        tasks = store.get_all_tasks()
        assert len(tasks) == 2

    def test_queued_tasks_excludes_running(self, store):
        store.enqueue_task(Task(spec_number="014", spec_title="T1",
                                done_when_item="item 1"))
        store.enqueue_task(Task(spec_number="015", spec_title="T2",
                                done_when_item="item 2"))
        store.update_task_status(1, "running")
        queued = store.get_queued_tasks()
        assert len(queued) == 1
        assert queued[0].spec_number == "015"


class TestRunOperations:

    def test_create_run(self, store):
        run = store.create_run(config={"max_turns": 30})
        assert run.id is not None
        assert run.status == "running"
        assert run.config == {"max_turns": 30}

    def test_finish_run(self, store):
        run = store.create_run()
        store.finish_run(run.id, "completed", "all done", 5, 1, 100, 20)
        updated = store.get_run(run.id)
        assert updated.status == "completed"
        assert updated.stop_reason == "all done"
        assert updated.tasks_completed == 5
        assert updated.tasks_failed == 1

    def test_get_recent_runs(self, store):
        store.create_run()
        store.create_run()
        store.create_run()
        runs = store.get_recent_runs(limit=2)
        assert len(runs) == 2
        assert runs[0].id > runs[1].id


class TestSessionOperations:

    def test_create_session(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        run = store.create_run()
        session = AgentSession(task_id=task.id, run_id=run.id,
                               max_turns=30, time_limit_min=60)
        created = store.create_session(session)
        assert created.id is not None
        assert created.task_id == task.id
        assert created.run_id == run.id

    def test_get_active_sessions(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        run = store.create_run()
        store.create_session(AgentSession(task_id=task.id, run_id=run.id))
        active = store.get_active_sessions()
        assert len(active) == 1
        assert active[0].status == "running"


class TestResultOperations:

    def test_save_and_get_result(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        run = store.create_run()
        session = store.create_session(AgentSession(task_id=task.id, run_id=run.id))

        result = Result(
            task_id=task.id,
            session_id=session.id,
            branch_name="auto/spec-014-task-1",
            commit_sha="abc123",
            diff_summary="3 files changed",
            test_passed=10,
            test_failed=0,
            adversarial_verdict="PASS",
            adversarial_report={"verdict": "PASS", "issues": []},
            harness_check={"passed": 5, "failed": 0},
        )
        saved = store.save_result(result)
        assert saved.id is not None

    def test_approve_result(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        run = store.create_run()
        session = store.create_session(AgentSession(task_id=task.id, run_id=run.id))
        result = store.save_result(Result(task_id=task.id, session_id=session.id))
        store.approve_result(result.id, True)

    def test_reject_result(self, store):
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        run = store.create_run()
        session = store.create_session(AgentSession(task_id=task.id, run_id=run.id))
        result = store.save_result(Result(task_id=task.id, session_id=session.id))
        store.approve_result(result.id, False)
