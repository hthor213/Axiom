"""Project management routes for the multi-repo dashboard (spec:022).

Handles: GET /projects, POST /projects, GET /projects/{id},
         GET /projects/{id}/sync, POST /projects/{id}/clone,
         POST /projects/{id}/pull, POST /projects/new.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth

router = APIRouter(prefix="/projects", tags=["projects"])


# ---- Pydantic models ----

class AddProjectRequest(BaseModel):
    name: str
    repo_path: str
    remote_url: Optional[str] = None
    base_branch: str = "main"


class NewProjectRequest(BaseModel):
    name: str
    workspace_dir: Optional[str] = None  # defaults to ~/code/<name>


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    remote_url: Optional[str] = None
    base_branch: Optional[str] = None


# ---- Helpers ----

def _project_store(store):
    """Return ProjectStore from the composed TaskStore."""
    from runtime.project_db import ProjectStore
    return ProjectStore(store._pg_conn_string)


def _is_local_path(path: str) -> bool:
    """Check if a string looks like a filesystem path (not a URL)."""
    return bool(path) and not path.startswith(("git@", "https://", "http://"))


def _effective_path(project) -> str:
    """Return the on-disk repo path.

    Falls back to REPO_ROOT only for the framework repo itself (container
    stores host path but repo is mounted at /repo). Other projects with
    stale paths return the path as-is — callers must check existence.
    Cloud-only projects (URL as repo_path) return the URL as-is.
    """
    if os.path.isdir(project.repo_path):
        return project.repo_path
    if _is_local_path(project.repo_path):
        # Only fall back for the framework repo (mounted at /repo)
        repo_root = get_repo_root()
        if "ai-dev-framework" in (project.repo_path or ""):
            return repo_root
    # Cloud-only or stale path: return as-is
    return project.repo_path


def _with_sync(project, pstore, fast: bool = False) -> dict:
    """Serialize project with live sync status."""
    from runtime.sync_status import compute_sync_status
    path = _effective_path(project)
    status = compute_sync_status(path, project.remote_url, fast=fast)
    return {
        "id": project.id,
        "name": project.name,
        "repo_path": project.repo_path,
        "remote_url": project.remote_url,
        "base_branch": project.base_branch,
        "active": project.active,
        "created_at": project.created_at,
        "sync": status.to_dict(),
    }


# ---- Endpoints ----

@router.get("", dependencies=[Depends(require_auth)])
async def list_projects():
    """List all active projects with live sync status."""
    store = get_store()
    ps = _project_store(store)
    projects = ps.list_projects(active_only=True)
    return {"projects": [_with_sync(p, ps, fast=True) for p in projects]}


@router.post("", dependencies=[Depends(require_auth)])
async def add_project(req: AddProjectRequest):
    """Register an existing local (or remote) project.

    If repo_path is a git repo with a remote, detects remote_url automatically.
    """
    from runtime.project_db import Project, ProjectStore

    store = get_store()
    ps = _project_store(store)

    # Check for duplicate path
    existing = ps.get_project_by_path(req.repo_path)
    if existing:
        raise HTTPException(status_code=409, detail="Project with this path already registered")

    remote_url = req.remote_url
    effective = req.repo_path if os.path.isdir(req.repo_path) else get_repo_root()
    if not remote_url and os.path.isdir(effective):
        remote_url = ps.detect_remote_url(effective)

    project = Project(
        name=req.name,
        repo_path=req.repo_path,
        remote_url=remote_url,
        base_branch=req.base_branch,
    )
    created = ps.create_project(project)
    return {"project": _with_sync(created, ps)}


@router.post("/new", dependencies=[Depends(require_auth)])
async def create_new_project(req: NewProjectRequest):
    """Create a brand-new project with git init, empty vision spec, and CLAUDE.md.

    Status icon will be ✦ (New / empty) — no remote, no commits yet.
    """
    from runtime.project_db import Project

    store = get_store()
    ps = _project_store(store)

    # Determine path
    workspace = req.workspace_dir or os.path.expanduser("~/code")
    slug = req.name.lower().replace(" ", "-").replace("_", "-")
    repo_path = os.path.join(workspace, slug)

    if os.path.exists(repo_path):
        raise HTTPException(status_code=409, detail=f"Directory already exists: {repo_path}")
    if ps.get_project_by_path(repo_path):
        raise HTTPException(status_code=409, detail="Project with this path already registered")

    # Scaffold
    try:
        _scaffold_new_project(repo_path, req.name, slug)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scaffold failed: {e}")

    project = Project(name=req.name, repo_path=repo_path, base_branch="main")
    created = ps.create_project(project)
    return {"project": _with_sync(created, ps)}


@router.get("/{project_id}", dependencies=[Depends(require_auth)])
async def get_project(project_id: int):
    """Get a single project with live sync status."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": _with_sync(project, ps)}


@router.get("/{project_id}/sync", dependencies=[Depends(require_auth)])
async def refresh_sync(project_id: int):
    """Compute and return the current sync status for a project."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from runtime.sync_status import compute_sync_status
    path = _effective_path(project)
    status = compute_sync_status(path, project.remote_url)
    return {"project_id": project_id, "sync": status.to_dict()}


@router.post("/{project_id}/clone", dependencies=[Depends(require_auth)])
async def clone_project(project_id: int):
    """Clone a cloud-only project to the workspace directory.

    Computes a local path from CLONE_WORKSPACE/<slug>, clones the repo,
    and updates repo_path in the DB so specs become visible.
    If the directory already exists (previously cloned), just links it.
    """
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.remote_url:
        raise HTTPException(status_code=400, detail="Project has no remote_url to clone from")

    # Compute clone destination — check for existing dir first
    workspace = os.environ.get("CLONE_WORKSPACE", "/workspace")
    slug = project.name.lower().replace(" ", "-").replace("_", "-")
    clone_path = os.path.join(workspace, slug)

    # Check common name variations (original name, slug) for existing git repos
    existing = None
    for candidate in [project.name, slug]:
        candidate_path = os.path.join(workspace, candidate)
        git_dir = os.path.join(candidate_path, ".git")
        if os.path.isdir(candidate_path) and os.path.isdir(git_dir):
            existing = candidate_path
            break

    if existing:
        # Already on disk — just link to DB
        ps.update_project(project_id, repo_path=existing)
        clone_path = existing
    else:
        from runtime.sync_status import clone_project as do_clone
        success = do_clone(project.remote_url, clone_path)
        if not success:
            raise HTTPException(status_code=500, detail="git clone failed")
        ps.update_project(project_id, repo_path=clone_path)

    from runtime.sync_status import compute_sync_status
    status = compute_sync_status(clone_path, project.remote_url)
    return {"status": "cloned", "project_id": project_id, "sync": status.to_dict()}


@router.post("/{project_id}/pull", dependencies=[Depends(require_auth)])
async def pull_project(project_id: int):
    """Run git pull --ff-only on a project's local repo."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    path = _effective_path(project)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Local repo does not exist")

    from runtime.sync_status import pull_project as do_pull
    success, output = do_pull(path)
    if not success:
        return {"status": "error", "output": output}
    return {"status": "ok", "output": output}


@router.patch("/{project_id}", dependencies=[Depends(require_auth)])
async def update_project(project_id: int, req: UpdateProjectRequest):
    """Update project name, remote_url, or base_branch."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = {k: v for k, v in req.dict().items() if v is not None}
    if updates:
        ps.update_project(project_id, **updates)
    updated = ps.get_project(project_id)
    return {"project": _with_sync(updated, ps)}


@router.delete("/{project_id}", dependencies=[Depends(require_auth)])
async def delete_project(project_id: int):
    """Soft-delete a project (sets active=false)."""
    store = get_store()
    ps = _project_store(store)
    success = ps.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok", "project_id": project_id}


# ---- Scaffold helper ----

_VISION_TEMPLATE = """\
# 001: Vision

**Status:** draft

## Goal

<!-- What is this project? What problem does it solve? Write your vision here. -->

## Done When
- [ ] Vision is written and committed
"""

_CLAUDE_MD_TEMPLATE = """\
# {name} — Claude Code Project Context

## What This Is
<!-- Describe this project and its purpose. -->

## Development Commands
```bash
# Add your development commands here
```

## Key Invariants
<!-- Document the most important rules for this project. -->
"""


def _run_git(args: list, cwd: str) -> bool:
    """Run a git command in the given directory. Returns True on success."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def _scaffold_new_project(repo_path: str, name: str, slug: str) -> None:
    """Create directory, git init, write specs/ and CLAUDE.md, initial commit."""
    os.makedirs(repo_path, exist_ok=False)
    specs_dir = os.path.join(repo_path, "specs")
    os.makedirs(specs_dir)

    # Write vision spec
    with open(os.path.join(specs_dir, "001-vision.md"), "w") as f:
        f.write(_VISION_TEMPLATE)

    # Write CLAUDE.md
    with open(os.path.join(repo_path, "CLAUDE.md"), "w") as f:
        f.write(_CLAUDE_MD_TEMPLATE.format(name=name))

    # Git init + initial commit
    _run_git(["init"], cwd=repo_path)
    _run_git(["config", "user.email", "hth@local"], cwd=repo_path)
    _run_git(["config", "user.name", "HTH Platform"], cwd=repo_path)
    _run_git(["add", "-A"], cwd=repo_path)
    _run_git(["commit", "-m", "Initial commit: empty vision spec"], cwd=repo_path)
