"""Project CRUD operations for multi-repo dashboard support.

Projects are stored in PostgreSQL and represent separate git repos managed
by the dashboard. Each project has isolated tasks, runs, results, and worktrees.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class Project:
    """A registered project (git repository) managed by the dashboard."""
    id: Optional[int] = None
    name: str = ""
    repo_path: str = ""
    remote_url: Optional[str] = None
    base_branch: str = "main"
    active: bool = True
    created_at: Optional[str] = None


class ProjectStore:
    """PostgreSQL-backed project registry.

    Designed to be composed with TaskStore — share the same pg_conn_string.
    """

    def __init__(self, pg_conn_string: str):
        self._pg_conn_string = pg_conn_string

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self._pg_conn_string)

    def _dict_cursor(self, conn):
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ---- CRUD ----

    def create_project(self, project: Project) -> Project:
        """Insert a new project. Returns project with assigned id."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO projects (name, repo_path, remote_url, base_branch, active)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at""",
                    (project.name, project.repo_path, project.remote_url,
                     project.base_branch, project.active),
                )
                row = cur.fetchone()
            conn.commit()
            project.id = row[0]
            project.created_at = str(row[1]) if row[1] else None
            return project
        finally:
            conn.close()

    def get_project(self, project_id: int) -> Optional[Project]:
        """Fetch a single project by id."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
            return _row_to_project(row) if row else None
        finally:
            conn.close()

    def get_project_by_path(self, repo_path: str) -> Optional[Project]:
        """Fetch project by repo_path (unique)."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM projects WHERE repo_path = %s", (repo_path,))
                row = cur.fetchone()
            return _row_to_project(row) if row else None
        finally:
            conn.close()

    def list_projects(self, active_only: bool = True) -> list[Project]:
        """List all projects, optionally filtered to active."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                if active_only:
                    cur.execute(
                        "SELECT * FROM projects WHERE active = true ORDER BY name")
                else:
                    cur.execute("SELECT * FROM projects ORDER BY name")
                rows = cur.fetchall()
            return [_row_to_project(r) for r in rows]
        finally:
            conn.close()

    def update_project(self, project_id: int, **kwargs) -> bool:
        """Update project fields. Returns True if found."""
        allowed = {"name", "repo_path", "remote_url", "base_branch", "active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        cols = ", ".join(f"{k} = %s" for k in updates)
        vals = list(updates.values()) + [project_id]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE projects SET {cols} WHERE id = %s", vals)
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()

    def delete_project(self, project_id: int) -> bool:
        """Soft-delete a project by setting active=false."""
        return self.update_project(project_id, active=False)

    # ---- Remote detection ----

    def detect_remote_url(self, repo_path: str) -> Optional[str]:
        """Read remote URL from a local git repo (origin)."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path, capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except Exception:
            pass
        return None


def _row_to_project(row: dict) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        repo_path=row["repo_path"],
        remote_url=row.get("remote_url"),
        base_branch=row.get("base_branch", "main"),
        active=row.get("active", True),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )
