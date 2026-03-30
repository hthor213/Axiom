"""Task management routes for the dashboard API.

Handles: GET /tasks/visible, POST /tasks/{id}/cancel, POST /tasks/{id}/stop,
         POST /tasks/clear-stale, POST /git/pull.
"""

from __future__ import annotations

import subprocess

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .state import get_store, get_repo_root, require_auth


router = APIRouter()


def _resolve_repo_root(store, project_id: Optional[int]) -> str:
    """Return repo root for the given project, or the default repo root."""
    if project_id:
        try:
            from runtime.project_db import ProjectStore
            ps = ProjectStore(store._pg_conn_string)
            p = ps.get_project(project_id)
            if p and p.repo_path:
                return p.repo_path
        except Exception:
            pass
    return get_repo_root()


@router.get("/tasks/visible", dependencies=[Depends(require_auth)])
async def get_visible_tasks(project: Optional[int] = None):
    """Get queued, running, and stopped tasks for the Live tab.

    Enriches running tasks with agent session info (elapsed time, time limit)
    so the frontend doesn't need a separate /agents call.

    If ?project=<id> is provided, returns tasks for that project only.
    """
    store = get_store()
    tasks = store.get_visible_tasks(project_id=project)

    # Build session lookup: task_id → session for running sessions
    session_by_task: dict[int, dict] = {}
    try:
        for s in store.get_active_sessions():
            session_by_task[s.task_id] = {
                "started_at": s.started_at,
                "time_limit_min": s.time_limit_min,
                "turns_used": s.turns_used,
                "max_turns": s.max_turns,
            }
    except Exception:
        pass

    return {"tasks": [
        {
            "id": t.id,
            "spec_number": t.spec_number,
            "spec_title": t.spec_title,
            "done_when_item": t.done_when_item,
            "status": t.status,
            "pipeline_stage": t.pipeline_stage,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "stop_reason": t.stop_reason,
            "project_id": t.project_id,
            **(session_by_task.get(t.id, {})),
        }
        for t in tasks
    ]}


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_task(task_id: int):
    """Cancel a queued task."""
    store = get_store()
    success = store.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not found or not in queued status")
    return {"status": "ok", "task_id": task_id}


@router.post("/tasks/{task_id}/stop", dependencies=[Depends(require_auth)])
async def stop_task(task_id: int):
    """Stop a running task. Sends SIGTERM to the runtime process."""
    store = get_store()
    success = store.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not found or not running")
    return {"status": "ok", "task_id": task_id, "message": "Task marked as stopped"}


@router.post("/tasks/clear-stale", dependencies=[Depends(require_auth)])
async def clear_stale_tasks():
    """Cancel all stale queued tasks (older than 24h)."""
    store = get_store()
    count = store.cancel_stale_tasks()
    return {"status": "ok", "cancelled": count}


@router.post("/git/pull", dependencies=[Depends(require_auth)])
async def git_pull(project: Optional[int] = None):
    """Run git pull on the repo. Used for external code import workflow.

    If ?project=<id> is provided, pulls the specific project's repository.
    """
    store = get_store()
    repo_root = _resolve_repo_root(store, project)
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_root, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"status": "error", "output": result.stderr.strip()}
        return {"status": "ok", "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git pull timed out")
