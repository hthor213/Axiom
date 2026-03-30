"""QueueOpsMixin: queue visibility, stop/cancel/recovery, and aggregate query ops."""

from __future__ import annotations

from typing import Optional

from .db_models import Task
from .db_converters import row_to_task, row_to_result, result_to_dict


class QueueOpsMixin:
    """Mixin providing queue management, stop/cancel, and result aggregate queries.

    Relies on _connect() and _dict_cursor() from TaskOpsMixin.
    """

    # ---- Atomic task claiming ----

    def claim_next_task(self, task_ids: Optional[list[int]] = None,
                        project_id: Optional[int] = None) -> Optional[Task]:
        """Atomically claim the next queued task using FOR UPDATE SKIP LOCKED.

        Args:
            task_ids: If provided, only claim from this set of task IDs.
                      This enables scoped runs (spec:025).
            project_id: If provided, only claim tasks belonging to this project.
        """
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                if task_ids:
                    cur.execute(
                        """UPDATE tasks SET status='running', updated_at=NOW()
                           WHERE id = (
                               SELECT id FROM tasks WHERE status='queued'
                               AND id = ANY(%s)
                               ORDER BY priority, id LIMIT 1
                               FOR UPDATE SKIP LOCKED
                           ) RETURNING *""",
                        (task_ids,),
                    )
                elif project_id is not None:
                    cur.execute(
                        """UPDATE tasks SET status='running', updated_at=NOW()
                           WHERE id = (
                               SELECT id FROM tasks WHERE status='queued'
                               AND project_id = %s
                               ORDER BY priority, id LIMIT 1
                               FOR UPDATE SKIP LOCKED
                           ) RETURNING *""",
                        (project_id,),
                    )
                else:
                    cur.execute(
                        """UPDATE tasks SET status='running', updated_at=NOW()
                           WHERE id = (
                               SELECT id FROM tasks WHERE status='queued'
                               ORDER BY priority, id LIMIT 1
                               FOR UPDATE SKIP LOCKED
                           ) RETURNING *"""
                    )
                row = cur.fetchone()
            conn.commit()
            return row_to_task(dict(row)) if row else None
        finally:
            conn.close()

    def cleanup_rejected_tasks(self) -> int:
        """Mark tasks as 'rejected' if their result was rejected but task status wasn't updated."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks SET status='rejected', updated_at=NOW()
                       WHERE status IN ('queued','running','waiting_for_human')
                       AND id IN (
                           SELECT t.id FROM tasks t
                           JOIN results r ON r.task_id = t.id
                           WHERE r.approved = false
                       )"""
                )
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            conn.close()

    def has_active_task(self, spec_number: str, done_when_item: str,
                        project_id: Optional[int] = None) -> bool:
        """Check if a task with the same spec+item is already queued or running.

        In multi-repo environments, spec_number is only unique per project, so
        project_id must be provided to avoid false positives across projects.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if project_id is not None:
                    cur.execute(
                        "SELECT COUNT(*) FROM tasks WHERE spec_number=%s AND done_when_item=%s "
                        "AND project_id=%s "
                        "AND status IN ('queued','running','waiting_for_human')",
                        (spec_number, done_when_item, project_id),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM tasks WHERE spec_number=%s AND done_when_item=%s "
                        "AND status IN ('queued','running','waiting_for_human')",
                        (spec_number, done_when_item),
                    )
                return cur.fetchone()[0] > 0
        finally:
            conn.close()

    def get_tasks_for_run(self, run_id: int) -> list[Task]:
        """Get all tasks associated with a run via agent_sessions."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute(
                    """SELECT DISTINCT t.* FROM tasks t
                       JOIN agent_sessions s ON s.task_id = t.id
                       WHERE s.run_id = %s""",
                    (run_id,),
                )
                return [row_to_task(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_results_with_spec(self, limit: int = 50,
                               project_id: int | None = None) -> list[dict]:
        """Get results joined with task spec info.

        If project_id is provided, filters to results for that project.
        """
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                if project_id is not None:
                    cur.execute(
                        """SELECT r.*, t.spec_number, t.spec_title, t.done_when_item
                           FROM results r
                           LEFT JOIN tasks t ON r.task_id = t.id
                           WHERE r.project_id = %s
                           ORDER BY r.id DESC LIMIT %s""",
                        (project_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT r.*, t.spec_number, t.spec_title, t.done_when_item
                           FROM results r
                           LEFT JOIN tasks t ON r.task_id = t.id
                           ORDER BY r.id DESC LIMIT %s""",
                        (limit,),
                    )
                results = []
                for row in cur.fetchall():
                    row = dict(row)
                    r = row_to_result(row)
                    results.append({
                        **result_to_dict(r),
                        "spec_number": row.get("spec_number"),
                        "spec_title": row.get("spec_title"),
                        "done_when_item": row.get("done_when_item"),
                    })
                return results
        finally:
            conn.close()

    def get_result_summary_by_spec(self, project_id: Optional[int] = None) -> dict:
        """Get aggregated result counts per spec number.

        Lifecycle: merged > approved > adversarial verdict.
        An approved result counts as 'passed' regardless of adversarial verdict.

        In multi-repo environments, project_id must be provided — spec_number is
        only unique per project, so cross-project aggregation produces wrong counts.
        """
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                if project_id is not None:
                    cur.execute(
                        """SELECT t.spec_number,
                                  COUNT(r.id) as total,
                                  SUM(CASE WHEN r.approved = true THEN 1
                                           WHEN r.adversarial_verdict='PASS' THEN 1
                                           ELSE 0 END) as passed,
                                  SUM(CASE WHEN r.approved = false THEN 1
                                           WHEN r.approved IS NULL AND r.adversarial_verdict='FAIL' THEN 1
                                           ELSE 0 END) as failed,
                                  SUM(CASE WHEN r.approved IS NULL AND r.adversarial_verdict NOT IN ('PASS','FAIL')
                                           THEN 1 ELSE 0 END) as pending,
                                  SUM(CASE WHEN r.approved = true THEN 1 ELSE 0 END) as approved,
                                  SUM(CASE WHEN r.approved = false THEN 1 ELSE 0 END) as rejected
                           FROM results r
                           JOIN tasks t ON r.task_id = t.id
                           WHERE t.project_id = %s
                           GROUP BY t.spec_number""",
                        (project_id,),
                    )
                else:
                    cur.execute(
                        """SELECT t.spec_number,
                                  COUNT(r.id) as total,
                                  SUM(CASE WHEN r.approved = true THEN 1
                                           WHEN r.adversarial_verdict='PASS' THEN 1
                                           ELSE 0 END) as passed,
                                  SUM(CASE WHEN r.approved = false THEN 1
                                           WHEN r.approved IS NULL AND r.adversarial_verdict='FAIL' THEN 1
                                           ELSE 0 END) as failed,
                                  SUM(CASE WHEN r.approved IS NULL AND r.adversarial_verdict NOT IN ('PASS','FAIL')
                                           THEN 1 ELSE 0 END) as pending,
                                  SUM(CASE WHEN r.approved = true THEN 1 ELSE 0 END) as approved,
                                  SUM(CASE WHEN r.approved = false THEN 1 ELSE 0 END) as rejected
                           FROM results r
                           JOIN tasks t ON r.task_id = t.id
                           GROUP BY t.spec_number"""
                    )
                return {row["spec_number"]: dict(row) for row in cur.fetchall()}
        finally:
            conn.close()

    def get_latest_code_status_by_spec(self) -> dict:
        """Get the latest code lifecycle status for each spec.

        Returns dict: {spec_number: {status, approved, verdict, ...}}.
        Only the most recent result matters — historical rejections are ignored.
        """
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute(
                    """SELECT DISTINCT ON (t.spec_number)
                              t.spec_number,
                              r.approved,
                              r.adversarial_verdict,
                              r.created_at,
                              r.commit_sha,
                              t.status as task_status
                       FROM results r
                       JOIN tasks t ON r.task_id = t.id
                       ORDER BY t.spec_number, r.created_at DESC"""
                )
                result = {}
                for row in cur.fetchall():
                    sn = row["spec_number"]
                    if row["approved"] is True:
                        status = "merged"
                    elif row["approved"] is False:
                        status = "rejected"
                    else:
                        status = "review_pending"
                    result[sn] = {
                        "code_status": status,
                        "commit_sha": row.get("commit_sha"),
                    }

                # Also check for specs with running/queued tasks but no results
                cur.execute(
                    """SELECT spec_number FROM tasks
                       WHERE status IN ('running', 'queued')
                       AND spec_number NOT IN (
                           SELECT DISTINCT t2.spec_number FROM results r2
                           JOIN tasks t2 ON r2.task_id = t2.id
                       )"""
                )
                for row in cur.fetchall():
                    result[row["spec_number"]] = {"code_status": "building"}

                return result
        finally:
            conn.close()

    # ---- Queue visibility + stop/resume operations (spec:025) ----

    def get_visible_tasks(self, project_id: int | None = None) -> list[Task]:
        """Get queued, running, and stopped tasks for the Live tab."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                if project_id is not None:
                    cur.execute(
                        """SELECT * FROM tasks
                           WHERE status IN ('queued', 'running', 'stopped')
                             AND project_id = %s
                           ORDER BY
                               CASE status WHEN 'running' THEN 0
                                           WHEN 'queued' THEN 1
                                           WHEN 'stopped' THEN 2 END,
                               priority, id""",
                        (project_id,),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM tasks
                           WHERE status IN ('queued', 'running', 'stopped')
                           ORDER BY
                               CASE status WHEN 'running' THEN 0
                                           WHEN 'queued' THEN 1
                                           WHEN 'stopped' THEN 2 END,
                               priority, id"""
                    )
                return [row_to_task(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def cancel_task(self, task_id: int) -> bool:
        """Cancel a queued task. Only works on queued tasks."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks SET status='cancelled', updated_at=NOW()
                       WHERE id=%s AND status='queued'""",
                    (task_id,),
                )
                count = cur.rowcount
            conn.commit()
            return count > 0
        finally:
            conn.close()

    def stop_task(self, task_id: int, reason: str = "user_stopped") -> bool:
        """Stop a running task. Preserves pipeline_stage and worktree."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks SET status='stopped', stop_reason=%s, updated_at=NOW()
                       WHERE id=%s AND status='running'""",
                    (reason, task_id),
                )
                count = cur.rowcount
            conn.commit()
            return count > 0
        finally:
            conn.close()

    def recover_orphaned_tasks(self) -> int:
        """Mark orphaned running tasks as stopped (crash recovery).

        Called on startup. Tasks with status='running' but no live process
        are marked 'stopped' with reason 'crash_recovery'.
        Also closes orphaned agent_sessions.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks SET status='stopped', stop_reason='crash_recovery',
                       updated_at=NOW()
                       WHERE status='running'"""
                )
                count = cur.rowcount
                cur.execute(
                    """UPDATE agent_sessions SET status='finished',
                       finished_at=NOW(), error='crash_recovery'
                       WHERE status='running'"""
                )
            conn.commit()
            return count
        finally:
            conn.close()

    def cancel_stale_tasks(self, max_age_hours: int = 24) -> int:
        """Cancel queued tasks older than max_age_hours."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks SET status='cancelled', updated_at=NOW(),
                       stop_reason='stale_cleanup'
                       WHERE status='queued'
                       AND created_at < NOW() - INTERVAL '%s hours'""",
                    (max_age_hours,),
                )
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            conn.close()
