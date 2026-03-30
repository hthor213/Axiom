"""Spec CRUD routes: list, content view, and activate.

Handles: GET /specs, GET /specs/{number}/content,
         POST /specs/{number}/activate.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .state import get_store, get_repo_root, require_auth, _active_runs, _cleanup_finished_runs


router = APIRouter()


# ---- Helpers ----

def _resolve_repo_root(store, project_id: Optional[int]) -> Optional[str]:
    """Return repo root for the given project, or the default repo root.

    When a project is selected: returns its repo_path if it exists on disk,
    None if cloud-only (URL), None if path doesn't exist (stale/uncloned).
    Never falls back to REPO_ROOT for a selected project — that would show
    the wrong project's specs.

    When no project is selected: returns REPO_ROOT (the framework itself).
    """
    if project_id:
        try:
            from runtime.project_db import ProjectStore
            ps = ProjectStore(store._pg_conn_string)
            p = ps.get_project(project_id)
            if p and p.repo_path:
                if os.path.isdir(p.repo_path):
                    return p.repo_path
                # Cloud-only (URL) — no local clone
                if p.repo_path.startswith(("git@", "https://", "http://")):
                    return None
                # Host path doesn't exist in container — check if this
                # is the framework repo mounted at REPO_ROOT
                repo_root = get_repo_root()
                if "ai-dev-framework" in p.repo_path and os.path.isdir(repo_root):
                    return repo_root
                return None
        except Exception:
            pass
        return None
    return get_repo_root()


def _is_ancestor(commit: str, descendant: str, repo_root: str) -> bool:
    """Check if commit is an ancestor of descendant using git."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, descendant],
            cwd=repo_root, capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _count_imported_tasks(store, spec_number: str) -> int:
    """Count imported tasks for a spec (from bootstrap/sync)."""
    try:
        conn = store._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM tasks WHERE spec_number=%s AND status='imported'",
                (spec_number,),
            )
            return cur.fetchone()[0]
    except Exception:
        return 0


# ---- Endpoints ----

@router.get("/specs", dependencies=[Depends(require_auth)])
async def get_specs(project: Optional[int] = None):
    """Get spec list with status. Includes 'live' flag for specs with queued/running tasks.

    If ?project=<id> is provided, scans specs from that project's repo_path.
    """
    store = get_store()
    repo_root = _resolve_repo_root(store, project)
    if repo_root is None:
        return {"specs": []}  # cloud-only project, no local clone
    specs_dir = os.path.join(repo_root, "specs")

    _cleanup_finished_runs()
    live_specs: set[str] = set()
    try:
        if len(_active_runs) > 0:
            all_tasks = store.get_all_tasks()
            for t in all_tasks:
                if t.status == "running":
                    live_specs.add(t.spec_number)
    except Exception:
        pass

    code_statuses = {}
    try:
        code_statuses = store.get_latest_code_status_by_spec()
    except Exception:
        pass

    # Check which specs have been through the review pipeline
    spec_review_status = {}
    try:
        conn = store._connect()
        with store._dict_cursor(conn) as cur:
            cur.execute(
                """SELECT spec_number, status FROM spec_reviews
                   WHERE id IN (
                       SELECT MAX(id) FROM spec_reviews GROUP BY spec_number
                   )"""
            )
            for row in cur.fetchall():
                spec_review_status[row["spec_number"]] = row["status"]
        conn.close()
    except Exception:
        pass

    specs = []
    if os.path.isdir(specs_dir):
        from harness.parser import extract_spec_status, extract_done_when

        for fname in sorted(os.listdir(specs_dir)):
            if not fname.endswith(".md") or not fname[0].isdigit():
                continue
            full_path = os.path.join(specs_dir, fname)
            status = extract_spec_status(full_path)
            done_when = extract_done_when(full_path)

            goal = ""
            try:
                with open(full_path, "r") as f:
                    content = f.read()
                goal_match = re.search(r'## Goal\s*\n\s*(.+?)(?:\n|$)', content)
                if goal_match:
                    goal = goal_match.group(1).strip()
                    for sep in ['. ', '.\n']:
                        if sep in goal:
                            goal = goal[:goal.index(sep) + 1]
                            break
                    if len(goal) > 150:
                        goal = goal[:147] + "..."
            except Exception:
                pass

            parts = fname.replace(".md", "").split("-", 1)
            number = parts[0]
            title = parts[1].replace("-", " ") if len(parts) > 1 else fname

            # Spec lifecycle: draft → reviewed → approved
            review = spec_review_status.get(number)
            if review == "approved":
                spec_status = "approved"
            elif review == "pending":
                spec_status = "reviewed"
            elif status in ("active", "ready"):
                spec_status = "active"
            else:
                spec_status = status  # draft, done, merged, etc.

            # Code lifecycle: — → synced → merged → deployed
            # Priority: building > deployed > merged > synced > rejected > review_pending > —
            cs = code_statuses.get(number, {})
            pipeline_status = cs.get("code_status")  # None, building, merged, review_pending, rejected
            has_imported = _count_imported_tasks(store, number) > 0
            deployed_commit = os.environ.get("GIT_COMMIT")

            if number in live_specs:
                code_status = "building"
            elif deployed_commit and has_imported:
                # Ground truth (spec files) says work is done + server is running = deployed
                code_status = "deployed"
            elif pipeline_status == "merged":
                merge_sha = cs.get("commit_sha")
                if deployed_commit and merge_sha and _is_ancestor(merge_sha, deployed_commit, repo_root):
                    code_status = "deployed"
                else:
                    code_status = "merged"
            elif has_imported:
                code_status = "synced"
            elif pipeline_status:
                code_status = pipeline_status  # rejected, review_pending
            else:
                code_status = None

            specs.append({
                "number": number,
                "title": title,
                "filename": fname,
                "status": status,  # raw spec file status (for Build draft warning)
                "spec_status": spec_status,
                "code_status": code_status,
                "goal": goal,
                "live": number in live_specs,
                "done_when": [
                    {"text": item["text"], "checked": item.get("checked", False)}
                    for item in done_when
                ],
                "total_items": len(done_when),
                "checked_items": sum(1 for item in done_when if item.get("checked")),
            })

    return {"specs": specs}


@router.get("/specs/{spec_number}/content", dependencies=[Depends(require_auth)])
async def get_spec_content(spec_number: str, project: Optional[int] = None):
    """Get the full content of a spec file."""
    store = get_store()
    repo_root = _resolve_repo_root(store, project)
    if not repo_root:
        raise HTTPException(status_code=400, detail="Project has no local clone")
    specs_dir = os.path.join(repo_root, "specs")
    if not os.path.isdir(specs_dir):
        raise HTTPException(status_code=404, detail="No specs directory")
    for fname in sorted(os.listdir(specs_dir)):
        if fname.startswith(spec_number) and fname.endswith(".md"):
            with open(os.path.join(specs_dir, fname)) as f:
                return {"content": f.read(), "filename": fname}
    raise HTTPException(status_code=404, detail=f"Spec {spec_number} not found")


@router.post("/specs/{spec_number}/activate", dependencies=[Depends(require_auth)])
async def activate_spec(spec_number: str, project: Optional[int] = None):
    """Move a spec from draft to active status. Commits and pushes."""
    store = get_store()
    repo_root = _resolve_repo_root(store, project)
    if not repo_root:
        raise HTTPException(status_code=400, detail="Project has no local clone")
    specs_dir = os.path.join(repo_root, "specs")

    target = None
    for fname in sorted(os.listdir(specs_dir)):
        if fname.startswith(spec_number) and fname.endswith(".md"):
            target = os.path.join(specs_dir, fname)
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Spec {spec_number} not found")

    with open(target) as f:
        content = f.read()

    if "**Status:** draft" not in content:
        raise HTTPException(status_code=400, detail="Spec is not in draft status")

    content = content.replace("**Status:** draft", "**Status:** active", 1)
    with open(target, "w") as f:
        f.write(content)

    try:
        subprocess.run(["git", "add", target], cwd=repo_root, check=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", f"spec: activate {spec_number} — start development"],
            cwd=repo_root, check=True, timeout=10,
        )
        subprocess.run(["git", "push", "origin"], cwd=repo_root, timeout=30)
    except subprocess.CalledProcessError:
        pass  # Best effort push

    return {"status": "ok", "spec_number": spec_number, "new_status": "active"}
