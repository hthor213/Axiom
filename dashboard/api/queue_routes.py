"""Queue and run routes for the dashboard API.

Handles: POST /queue, POST /run.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth, _active_runs, _cleanup_finished_runs

from runtime.server import RuntimeServer, RuntimeConfig


router = APIRouter()


# ---- Pydantic models ----

class EnqueueRequest(BaseModel):
    tasks: list[dict]  # [{spec_number, spec_title, done_when_item, priority?}]
    user_instructions: Optional[str] = None
    project_id: Optional[int] = None


class RunRequest(BaseModel):
    task_ids: Optional[list[int]] = None
    max_turns_per_task: int = 30
    time_limit_per_task_min: int = 60
    run_plan: bool = True
    project_id: Optional[int] = None


# ---- Queue endpoint ----

@router.post("/queue", dependencies=[Depends(require_auth)])
async def enqueue_tasks(req: EnqueueRequest):
    """Enqueue tasks for autonomous execution. Deduplicates against active tasks."""
    from runtime.db import Task
    store = get_store()

    store.cleanup_rejected_tasks()

    enqueued = []
    skipped = 0
    for t in req.tasks:
        task = Task(
            spec_number=t.get("spec_number", ""),
            spec_title=t.get("spec_title", ""),
            done_when_item=t.get("done_when_item", ""),
            priority=t.get("priority", 100),
            queued_by="dashboard",
            user_instructions=req.user_instructions or t.get("user_instructions", ""),
            project_id=req.project_id,
        )
        result = store.enqueue_task_if_not_active(task)
        if result is None:
            skipped += 1
            continue
        enqueued.append({"id": result.id, "spec_number": result.spec_number})

    return {"enqueued": enqueued, "count": len(enqueued), "skipped": skipped}


# ---- Run endpoint (scoped — spec:025) ----

@router.post("/run", dependencies=[Depends(require_auth)])
async def trigger_run(req: RunRequest):
    """Trigger scoped queue processing.

    Requires task_ids — only those tasks are processed.
    POST /run without task_ids returns 400 (spec:025).
    """
    from .state import _ws_clients, _next_run_key_incr

    _cleanup_finished_runs()

    store = get_store()
    repo_root = get_repo_root()

    worktree_dir = "/tmp/hth-worktrees"
    if req.project_id:
        try:
            from runtime.project_db import ProjectStore
            ps = ProjectStore(store._pg_conn_string)
            p = ps.get_project(req.project_id)
            if p and p.repo_path:
                repo_root = p.repo_path
            worktree_dir = f"/tmp/hth-worktrees/{req.project_id}"
        except Exception:
            pass

    config = RuntimeConfig(
        repo_root=repo_root,
        max_turns_per_task=req.max_turns_per_task,
        time_limit_per_task_min=req.time_limit_per_task_min,
        run_plan=req.run_plan,
        telegram_notify=True,
        project_id=req.project_id,
        worktree_dir=worktree_dir,
    )

    server = RuntimeServer(store, config)

    loop = asyncio.get_running_loop()

    async def broadcast(event: dict):
        msg = json.dumps(event)
        disconnected = []
        for ws in _ws_clients:
            try:
                await ws.send_text(msg)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            _ws_clients.remove(ws)

    def sync_broadcast(event: dict):
        asyncio.run_coroutine_threadsafe(broadcast(event), loop)

    server.set_progress_callback(sync_broadcast)

    run_key = _next_run_key_incr()
    task_ids = req.task_ids
    _active_runs[run_key] = asyncio.create_task(
        asyncio.to_thread(server.process_queue, task_ids=task_ids)
    )

    # Optional n8n webhook
    n8n_webhook = os.environ.get("N8N_WEBHOOK_URL")
    if n8n_webhook:
        try:
            import urllib.request
            req_obj = urllib.request.Request(
                n8n_webhook,
                data=json.dumps({"action": "process_queue", "task_ids": task_ids}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req_obj, timeout=10)
        except Exception:
            pass

    active_count = len(_active_runs)
    return {"status": "started", "message": "Queue processing started",
            "active_runs": active_count, "task_ids": task_ids}


@router.get("/tasks/{task_id}/plan", dependencies=[Depends(require_auth)])
async def get_task_plan(task_id: int):
    """Get the build plan and mentor feedback for a task."""
    store = get_store()
    plan = store.get_plan_for_task(task_id)
    if not plan:
        return {"task_id": task_id, "plan": None}
    return {
        "task_id": task_id,
        "plan_id": plan.id,
        "plan_text": plan.plan_text,
        "mentor_feedback": plan.mentor_feedback,
        "status": plan.status,
        "created_at": plan.created_at,
    }
