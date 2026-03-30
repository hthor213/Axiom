"""Pipeline run state persistence — SQLite-backed, keyed by run_id.

Each pipeline run tracks step-by-step progress so retries can resume
from the failed step. State is retained for 7 days, then purged.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

STEP_NAMES = ("verify", "commit", "push", "pr_or_merge", "deploy")
VALID_STATUSES = ("ok", "failed", "skipped", "awaiting_promotion", "pending")

_RETENTION_DAYS = 7
_DB_NAME = "ship_state.db"


@dataclass
class StepResult:
    """Result of a single pipeline step."""

    step: str
    status: str  # ok | failed | skipped | awaiting_promotion | pending
    detail: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "status": self.status,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StepResult:
        return cls(
            step=d["step"],
            status=d["status"],
            detail=d.get("detail", ""),
            timestamp=d.get("timestamp", 0.0),
        )


@dataclass
class PipelineRun:
    """Full state of a pipeline run."""

    run_id: str
    result_id: str
    actor: str  # "cli" or "dashboard"
    strategy: str = "pr"  # "pr" or "merge"
    status: str = "running"  # running | shipped | failed | awaiting_promotion
    steps: List[StepResult] = field(default_factory=list)
    created_at: float = 0.0
    commit_message: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "result_id": self.result_id,
            "actor": self.actor,
            "strategy": self.strategy,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "commit_message": self.commit_message,
        }


def generate_run_id() -> str:
    """Generate a unique run ID."""
    return f"run_{uuid.uuid4().hex[:12]}"


class ShipStateStore:
    """SQLite-backed store for pipeline run state."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.getcwd(), _DB_NAME)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                result_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                strategy TEXT NOT NULL DEFAULT 'pr',
                status TEXT NOT NULL DEFAULT 'running',
                steps_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                commit_message TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_result
            ON pipeline_runs(result_id)
        """)
        conn.commit()

    def save_run(self, run: PipelineRun) -> None:
        """Insert or update a pipeline run."""
        conn = self._get_conn()
        steps_json = json.dumps([s.to_dict() for s in run.steps])
        conn.execute("""
            INSERT INTO pipeline_runs
                (run_id, result_id, actor, strategy, status,
                 steps_json, created_at, commit_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                steps_json=excluded.steps_json,
                commit_message=excluded.commit_message
        """, (run.run_id, run.result_id, run.actor, run.strategy,
              run.status, steps_json, run.created_at, run.commit_message))
        conn.commit()

    def get_run(self, run_id: str) -> Optional[PipelineRun]:
        """Load a pipeline run by run_id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_run(row)

    def get_runs_for_result(self, result_id: str) -> List[PipelineRun]:
        """Get all pipeline runs for a given result_id."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE result_id = ? ORDER BY created_at DESC",
            (result_id,),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def get_latest_run(self, result_id: str) -> Optional[PipelineRun]:
        """Get the most recent pipeline run for a result."""
        runs = self.get_runs_for_result(result_id)
        return runs[0] if runs else None

    def purge_old_runs(self) -> int:
        """Remove runs older than retention period. Returns count removed."""
        conn = self._get_conn()
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        cursor = conn.execute(
            "DELETE FROM pipeline_runs WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        return cursor.rowcount

    def _row_to_run(self, row: tuple) -> PipelineRun:
        steps_data = json.loads(row[5])
        return PipelineRun(
            run_id=row[0],
            result_id=row[1],
            actor=row[2],
            strategy=row[3],
            status=row[4],
            steps=[StepResult.from_dict(s) for s in steps_data],
            created_at=row[6],
            commit_message=row[7],
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
