"""Result, history, and approval routes for the dashboard API.

Handles: GET /results, GET /results/{id}/files, POST /results/{id}/approve,
         GET /history, GET /history/tasks, GET /runs/active.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth, _active_runs, _cleanup_finished_runs


router = APIRouter()


class ApproveRequest(BaseModel):
    approved: bool
    reject_reason: Optional[str] = None


# ---- Results ----

@router.get("/results", dependencies=[Depends(require_auth)])
async def get_results(task_id: Optional[int] = None, pending_only: bool = True,
                      project: Optional[int] = None):
    """Get completed task results with spec info and review state.

    If ?project=<id> is provided, returns results for that project only.
    """
    store = get_store()

    results_with_spec = store.get_results_with_spec(limit=200, project_id=project)

    if task_id is not None:
        results_with_spec = [r for r in results_with_spec if r.get("task_id") == task_id]
    if pending_only:
        results_with_spec = [r for r in results_with_spec if r.get("approved") is None]

    pending_drafts = {d.task_id: d for d in store.get_draft_reviews(status="pending_answers")}
    for r in results_with_spec:
        r["has_pending_review"] = r.get("task_id") in pending_drafts

    return {"results": results_with_spec}


@router.get("/results/{result_id}/files", dependencies=[Depends(require_auth)])
async def get_result_files(result_id: int, path: str = ""):
    """Get file content from a result's worktree branch."""
    store = get_store()
    result = store.get_result(result_id)
    if not result or not result.branch_name:
        raise HTTPException(status_code=404, detail="Result or branch not found")

    repo_root = get_repo_root()
    if result.project_id:
        try:
            from runtime.project_db import ProjectStore
            ps = ProjectStore(store._pg_conn_string)
            p = ps.get_project(result.project_id)
            if p and p.repo_path:
                repo_root = p.repo_path
        except Exception:
            pass

    if path:
        try:
            out = subprocess.run(
                ["git", "show", f"{result.branch_name}:{path}"],
                cwd=repo_root, capture_output=True, text=True, timeout=10,
            )
            if out.returncode != 0:
                raise HTTPException(status_code=404,
                                    detail=f"File not found on branch {result.branch_name}")
            return {"path": path, "content": out.stdout, "branch": result.branch_name}
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Git operation timed out")
    else:
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", f"{result.commit_sha}^", result.commit_sha],
                cwd=repo_root, capture_output=True, text=True, timeout=10,
            )
            files = ([f for f in out.stdout.strip().split("\n") if f]
                     if out.returncode == 0 else [])
            return {"files": files, "branch": result.branch_name, "commit": result.commit_sha}
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Git operation timed out")


@router.post("/results/{result_id}/approve", dependencies=[Depends(require_auth)])
async def approve_result(result_id: int, req: ApproveRequest):
    """Approve or reject a result.

    On approve: merge the worktree branch into main and push.
    On reject: mark task as rejected, re-queue if needed.
    """
    store = get_store()
    result = store.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    if not req.approved:
        store.approve_result(result_id, False, reject_reason=req.reject_reason)
        try:
            if result.task_id:
                store.update_task_status(result.task_id, "rejected")
                task = store.get_task(result.task_id)
                if task and task.done_when_item == "__draft_review__":
                    drafts = store.get_draft_reviews(status="pending_answers")
                    for d in drafts:
                        if d.spec_number == task.spec_number and d.task_id == task.id:
                            store.update_draft_review(d.id, status="rejected")
        except Exception:
            pass
        return {"status": "ok", "approved": False}

    # Approve: merge branch into main and push
    repo_root = get_repo_root()
    if result.project_id:
        try:
            from runtime.project_db import ProjectStore
            ps = ProjectStore(store._pg_conn_string)
            p = ps.get_project(result.project_id)
            if p and p.repo_path:
                repo_root = p.repo_path
        except Exception:
            pass
    branch = result.branch_name
    merge_error = None

    if branch:
        try:
            # Ensure we're on main and up to date
            subprocess.run(["git", "checkout", "main"],
                           cwd=repo_root, capture_output=True, timeout=10)
            subprocess.run(["git", "pull", "--ff-only", "origin", "main"],
                           cwd=repo_root, capture_output=True, timeout=30)

            # Merge the worktree branch
            merge_result = subprocess.run(
                ["git", "merge", branch, "--no-edit"],
                cwd=repo_root, capture_output=True, text=True, timeout=30)

            if merge_result.returncode != 0:
                # Abort the failed merge
                subprocess.run(["git", "merge", "--abort"],
                               cwd=repo_root, capture_output=True, timeout=10)
                merge_error = merge_result.stderr.strip() or "Merge conflict"
            else:
                # Push to origin
                push_result = subprocess.run(
                    ["git", "push", "origin", "main"],
                    cwd=repo_root, capture_output=True, text=True, timeout=30)
                if push_result.returncode != 0:
                    merge_error = f"Merge succeeded but push failed: {push_result.stderr.strip()}"

                # Clean up worktree if task has one
                if result.task_id:
                    task = store.get_task(result.task_id)
                    if task and task.worktree_path:
                        try:
                            subprocess.run(
                                ["git", "worktree", "remove", task.worktree_path, "--force"],
                                cwd=repo_root, capture_output=True, timeout=10)
                        except Exception:
                            pass  # Best effort cleanup
        except subprocess.TimeoutExpired:
            merge_error = "Git operation timed out"
        except Exception as e:
            merge_error = str(e)

    if merge_error:
        # Don't mark as approved if merge failed
        return {"status": "error", "message": merge_error, "approved": False}

    store.approve_result(result_id, True)

    # Trigger deploy: rebuild dashboard image and restart container.
    # Uses docker.sock mounted from the host. The build runs while the
    # old container serves traffic. `docker compose up -d` swaps them.
    # If the old container dies mid-command, the Docker daemon still
    # completes the restart — the client doesn't need to stay alive.
    deploy_started = False
    if branch and os.path.exists("/var/run/docker.sock"):
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root, capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            subprocess.Popen(
                f"docker compose -f /repo/docker-compose.yml build "
                f"--build-arg GIT_COMMIT={commit} dashboard "
                f"&& docker compose -f /repo/docker-compose.yml up -d dashboard",
                shell=True,
                cwd=repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deploy_started = True
        except Exception:
            pass  # Deploy is best-effort — merge already succeeded

    return {"status": "ok", "approved": True, "merged": bool(branch),
            "deploy_started": deploy_started}


# ---- Active runs ----

@router.get("/runs/active", dependencies=[Depends(require_auth)])
async def get_active_runs():
    """Get count of currently active runs."""
    _cleanup_finished_runs()
    return {"active_runs": len(_active_runs)}


# ---- History ----

@router.get("/history", dependencies=[Depends(require_auth)])
async def get_history():
    """Get past runs."""
    store = get_store()
    runs = store.get_recent_runs()
    return {
        "runs": [
            {
                "id": r.id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "stop_reason": r.stop_reason,
                "tasks_completed": r.tasks_completed,
                "tasks_failed": r.tasks_failed,
                "total_turns": r.total_turns,
            }
            for r in runs
        ]
    }


@router.get("/history/tasks", dependencies=[Depends(require_auth)])
async def get_history_tasks(project: Optional[int] = None):
    """Get all results with spec info for the history view.

    If ?project=<id> is provided, returns results for that project only.
    """
    store = get_store()
    results = store.get_results_with_spec(limit=200, project_id=project)
    return {"results": results}
