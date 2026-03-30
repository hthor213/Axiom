"""TaskOpsMixin: base DB helpers + task, run, and session CRUD operations."""

from __future__ import annotations

import json
from typing import Optional

from .db_models import Task, Run, AgentSession
from .db_converters import row_to_task, row_to_run, row_to_session


class TaskOpsMixin:
    """Mixin for task, run, and session database operations.

    Provides _connect/_dict_cursor/_pg_conn_string used by all other mixins.
    """

    def __init__(self, pg_conn_string: str):
        self._pg_conn_string = pg_conn_string

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self._pg_conn_string)

    def _dict_cursor(self, conn):
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        """No-op — connections are opened and closed per operation."""
        pass

    # ---- Task operations ----

    def enqueue_task_if_not_active(self, task: Task) -> Optional[Task]:
        """Atomically enqueue if no active task exists for this spec+item.

        Returns Task with ID if enqueued, None if duplicate.
        Single query — no TOCTOU race.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if task.project_id is not None:
                    cur.execute(
                        """INSERT INTO tasks (spec_number, spec_title, done_when_item,
                           status, priority, queued_by, user_instructions, project_id)
                           SELECT %s, %s, %s, 'queued', %s, %s, %s, %s
                           WHERE NOT EXISTS (
                               SELECT 1 FROM tasks
                               WHERE spec_number = %s AND done_when_item = %s
                               AND project_id = %s
                               AND status IN ('queued', 'running', 'waiting_for_human')
                           ) RETURNING id""",
                        (task.spec_number, task.spec_title, task.done_when_item,
                         task.priority, task.queued_by, task.user_instructions,
                         task.project_id,
                         task.spec_number, task.done_when_item, task.project_id),
                    )
                else:
                    cur.execute(
                        """INSERT INTO tasks (spec_number, spec_title, done_when_item,
                           status, priority, queued_by, user_instructions, project_id)
                           SELECT %s, %s, %s, 'queued', %s, %s, %s, %s
                           WHERE NOT EXISTS (
                               SELECT 1 FROM tasks
                               WHERE spec_number = %s AND done_when_item = %s
                               AND project_id IS NULL
                               AND status IN ('queued', 'running', 'waiting_for_human')
                           ) RETURNING id""",
                        (task.spec_number, task.spec_title, task.done_when_item,
                         task.priority, task.queued_by, task.user_instructions,
                         task.project_id,
                         task.spec_number, task.done_when_item),
                    )
                row = cur.fetchone()
            conn.commit()
            if row:
                task.id = row[0]
                return task
            return None
        finally:
            conn.close()

    def enqueue_task(self, task: Task) -> Task:
        """Add a task to the queue. Returns the task with assigned ID."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO tasks (spec_number, spec_title, done_when_item,
                       status, priority, branch_name, worktree_path, queued_by,
                       user_instructions, project_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (task.spec_number, task.spec_title, task.done_when_item,
                     task.status, task.priority, task.branch_name,
                     task.worktree_path, task.queued_by, task.user_instructions,
                     task.project_id),
                )
                task.id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return task

    def get_queued_tasks(self, limit: int = 50) -> list[Task]:
        """Get tasks with status='queued', ordered by priority."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute(
                    "SELECT * FROM tasks WHERE status='queued' ORDER BY priority, id LIMIT %s",
                    (limit,),
                )
                return [row_to_task(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_task(self, task_id: int) -> Optional[Task]:
        """Get a single task by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
                row = cur.fetchone()
                return row_to_task(dict(row)) if row else None
        finally:
            conn.close()

    def update_task_status(self, task_id: int, status: str,
                           branch_name: Optional[str] = None,
                           worktree_path: Optional[str] = None,
                           base_commit: Optional[str] = None,
                           pipeline_stage: Optional[str] = None,
                           stop_reason: Optional[str] = None) -> bool:
        """Update a task's status and optional fields."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                updates = ["status=%s", "updated_at=NOW()"]
                params: list = [status]
                if branch_name is not None:
                    updates.append("branch_name=%s")
                    params.append(branch_name)
                if worktree_path is not None:
                    updates.append("worktree_path=%s")
                    params.append(worktree_path)
                if base_commit is not None:
                    updates.append("base_commit=%s")
                    params.append(base_commit)
                if pipeline_stage is not None:
                    updates.append("pipeline_stage=%s")
                    params.append(pipeline_stage)
                if stop_reason is not None:
                    updates.append("stop_reason=%s")
                    params.append(stop_reason)
                params.append(task_id)
                cur.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE id=%s",
                    params,
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks regardless of status."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM tasks ORDER BY priority, id")
                return [row_to_task(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    # ---- Run operations ----

    def create_run(self, config: Optional[dict] = None, project_id: Optional[int] = None) -> Run:
        """Create a new run. Returns run with assigned ID."""
        run = Run(config=config or {}, project_id=project_id)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO runs (status, config, project_id) VALUES (%s, %s, %s) RETURNING id, started_at",
                    (run.status, json.dumps(run.config), run.project_id),
                )
                row = cur.fetchone()
                run.id = row[0]
                run.started_at = str(row[1])
            conn.commit()
        finally:
            conn.close()
        return run

    def finish_run(self, run_id: int, status: str, stop_reason: str,
                   tasks_completed: int, tasks_failed: int,
                   total_turns: int, total_api_calls: int) -> bool:
        """Mark a run as finished."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE runs SET finished_at=NOW(), status=%s, stop_reason=%s,
                       tasks_completed=%s, tasks_failed=%s, total_turns=%s,
                       total_api_calls=%s WHERE id=%s""",
                    (status, stop_reason, tasks_completed, tasks_failed,
                     total_turns, total_api_calls, run_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_run(self, run_id: int) -> Optional[Run]:
        """Get a single run by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM runs WHERE id=%s", (run_id,))
                row = cur.fetchone()
                return row_to_run(dict(row)) if row else None
        finally:
            conn.close()

    def get_recent_runs(self, limit: int = 20) -> list[Run]:
        """Get recent runs, newest first."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,))
                return [row_to_run(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    # ---- Session operations ----

    def create_session(self, session: AgentSession) -> AgentSession:
        """Create a new agent session."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_sessions (task_id, run_id, status,
                       max_turns, time_limit_min, max_failures)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                    (session.task_id, session.run_id, session.status,
                     session.max_turns, session.time_limit_min, session.max_failures),
                )
                session.id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return session

    def update_session(self, session_id: int, **kwargs) -> bool:
        """Update session fields."""
        conn = self._connect()
        try:
            if not kwargs:
                return False
            sets = [f"{k}=%s" for k in kwargs]
            vals = list(kwargs.values()) + [session_id]
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE agent_sessions SET {', '.join(sets)} WHERE id=%s",
                    vals,
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_session(self, session_id: int) -> Optional[AgentSession]:
        """Get a single agent session by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM agent_sessions WHERE id=%s", (session_id,))
                row = cur.fetchone()
                return row_to_session(dict(row)) if row else None
        finally:
            conn.close()

    def get_active_sessions(self) -> list[AgentSession]:
        """Get all running sessions."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM agent_sessions WHERE status='running'")
                return [row_to_session(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()
