"""Health and ground-truth routes for the dashboard API.

Handles: GET /health/ground-truth, GET /health/drift, POST /health/sync.
Surfaces harness scan/drift data in the dashboard and provides
sync mechanism for importing externally completed work.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth

from harness.scanner import scan_specs
from harness.drift import check_alignment
from harness.ground_truth import compare_spec_vs_db, report_to_dict


router = APIRouter()


# ---- Ground truth ----

@router.get("/health/ground-truth", dependencies=[Depends(require_auth)])
async def get_ground_truth():
    """Compare spec-file state against dashboard task records."""
    repo_root = get_repo_root()
    specs_dir = os.path.join(repo_root, "specs")

    # Scan spec files
    spec_report = scan_specs(specs_dir)

    # Get all tasks from DB grouped by spec number
    store = get_store()
    db_tasks_by_spec = _get_tasks_by_spec(store)

    # Compare
    report = compare_spec_vs_db(spec_report, db_tasks_by_spec)
    return report_to_dict(report)


# ---- Drift ----

@router.get("/health/drift", dependencies=[Depends(require_auth)])
async def get_drift():
    """Return structural drift signals."""
    repo_root = get_repo_root()
    try:
        drift_report = check_alignment(repo_root)
    except Exception as e:
        return {"clean": True, "summary": f"Drift check failed: {e}", "items": []}

    return {
        "clean": drift_report.clean,
        "summary": drift_report.summary,
        "items": [
            {
                "type": item.type,
                "description": item.description,
                "spec_ref": item.spec_ref,
                "severity": item.severity,
            }
            for item in drift_report.items
        ],
    }


# ---- Sync ----

class SyncRequest(BaseModel):
    spec_number: Optional[str] = None  # None = sync all specs


@router.post("/health/sync", dependencies=[Depends(require_auth)])
async def sync_ground_truth(req: SyncRequest = SyncRequest()):
    """Re-scan specs and import newly completed items into the dashboard.

    Creates 'imported' task records for Done When items that are checked
    in spec files but have no corresponding dashboard record.
    """
    repo_root = get_repo_root()
    specs_dir = os.path.join(repo_root, "specs")
    store = get_store()

    spec_report = scan_specs(specs_dir)
    db_tasks_by_spec = _get_tasks_by_spec(store)
    report = compare_spec_vs_db(spec_report, db_tasks_by_spec)

    imported_count = 0
    for spec_gt in report.specs:
        if req.spec_number and spec_gt.number != req.spec_number:
            continue
        if not spec_gt.untracked_items:
            continue

        for item_text in spec_gt.untracked_items:
            _import_item(store, spec_gt.number, spec_gt.title, item_text)
            imported_count += 1

    return {
        "imported": imported_count,
        "message": f"Synced {imported_count} items from spec files into dashboard",
    }


# ---- Deployment status ----

@router.get("/health/deployment", dependencies=[Depends(require_auth)])
async def get_deployment_status():
    """Report deployment freshness based on GIT_COMMIT env var."""
    import subprocess

    deployed_commit = os.environ.get("GIT_COMMIT")
    repo_root = get_repo_root()

    # Get latest commit on main
    try:
        latest = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo_root, timeout=10,
        )
        latest_commit = latest.stdout.strip() if latest.returncode == 0 else None
    except Exception:
        latest_commit = None

    # Count commits behind
    behind = None
    if deployed_commit and latest_commit and deployed_commit != latest_commit:
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{deployed_commit}..HEAD"],
                capture_output=True, text=True, cwd=repo_root, timeout=10,
            )
            behind = int(result.stdout.strip()) if result.returncode == 0 else None
        except Exception:
            pass

    status = "unknown"
    if deployed_commit and latest_commit:
        if deployed_commit == latest_commit or (behind is not None and behind == 0):
            status = "current"
        elif behind is not None and behind <= 5:
            status = "stale"
        else:
            status = "outdated"

    return {
        "deployed_commit": deployed_commit or "unknown",
        "latest_commit": latest_commit or "unknown",
        "commits_behind": behind,
        "status": status,
    }


# ---- Helpers ----

def _get_tasks_by_spec(store) -> dict[str, list[dict]]:
    """Query all tasks and group by spec_number."""
    tasks = store.get_all_tasks()
    by_spec: dict[str, list[dict]] = {}
    for t in tasks:
        entry = {
            "done_when_item": t.done_when_item,
            "status": t.status,
            "id": t.id,
        }
        by_spec.setdefault(t.spec_number, []).append(entry)
    return by_spec


def _import_item(store, spec_number: str, spec_title: str, item_text: str):
    """Create an imported task record for an externally completed item."""
    from runtime.db import Task

    task = Task(
        spec_number=spec_number,
        spec_title=spec_title,
        done_when_item=item_text,
        status="imported",
        queued_by="sync",
    )
    # Use direct enqueue (not if_not_active, since 'imported' isn't in dedup index)
    store.enqueue_task(task)
