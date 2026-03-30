"""PlanOpsMixin: task plan database operations."""

from __future__ import annotations

from typing import Optional

from .db_models import TaskPlan
from .db_converters import row_to_plan


class PlanOpsMixin:
    """Mixin providing task plan CRUD operations.

    Relies on _connect() and _dict_cursor() from TaskOpsMixin.
    """

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        """Save a task plan."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO task_plans
                       (task_id, plan_text, mentor_feedback, status, project_id)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (plan.task_id, plan.plan_text, plan.mentor_feedback,
                     plan.status, plan.project_id),
                )
                plan.id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return plan

    def get_plan_for_task(self, task_id: int) -> Optional[TaskPlan]:
        """Get the latest plan for a task."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute(
                    "SELECT * FROM task_plans WHERE task_id=%s "
                    "ORDER BY id DESC LIMIT 1",
                    (task_id,),
                )
                row = cur.fetchone()
                return row_to_plan(dict(row)) if row else None
        finally:
            conn.close()

    def update_plan(self, plan_id: int, **kwargs) -> None:
        """Update plan fields (mentor_feedback, status, etc.)."""
        if not kwargs:
            return
        allowed = {"plan_text", "mentor_feedback", "status"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        values = list(fields.values()) + [plan_id]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE task_plans SET {set_clause} WHERE id=%s",
                    values,
                )
            conn.commit()
        finally:
            conn.close()
