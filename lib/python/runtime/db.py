"""Database operations for the autonomous runtime.

Thin wrapper around psycopg2 for task queue management.
PostgreSQL only — SQLite support was removed in the consolidation.

TaskStore is composed from focused mixins:
  TaskOpsMixin   — task, run, and session CRUD (db_task_ops.py)
  QueueOpsMixin  — queue visibility, stop/cancel/recovery (db_queue_ops.py)
  ResultOpsMixin — result, draft review, spec review CRUD (db_result_ops.py)

Row converters live in db_converters.py; dataclasses in db_models.py.
All public names are re-exported here for backward compatibility.
"""

from .db_models import Task, Run, AgentSession, Result, DraftReview, SpecReview, TaskPlan
from .db_task_ops import TaskOpsMixin
from .db_queue_ops import QueueOpsMixin
from .db_result_ops import ResultOpsMixin
from .db_plan_ops import PlanOpsMixin

__all__ = [
    "Task", "Run", "AgentSession", "Result", "DraftReview", "SpecReview",
    "TaskPlan", "TaskStore",
]


class TaskStore(TaskOpsMixin, QueueOpsMixin, ResultOpsMixin, PlanOpsMixin):
    """PostgreSQL-backed store for the autonomous runtime.

    Combines task/run/session ops, queue management, result/review ops,
    and plan ops.
    Constructor: TaskStore(pg_conn_string: str)
    """
