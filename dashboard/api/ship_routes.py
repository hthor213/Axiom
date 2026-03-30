"""Ship pipeline routes for the dashboard API.

Handles: POST /results/{id}/ship, POST /results/{id}/promote,
         POST /results/{id}/feedback, POST /results/{id}/feedback/resolve.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth

# Add lib path for ship imports
_lib_path = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "python")
if _lib_path not in sys.path:
    sys.path.insert(0, os.path.abspath(_lib_path))

from ship.pipeline import ShipOptions, run_pipeline
from ship.state import ShipStateStore
from ship.feedback import classify_feedback
from ship.promotion import promote_to_production, resolve_feedback

router = APIRouter()

# Per-result lock to prevent concurrent ship operations
_ship_locks: dict[str, threading.Lock] = {}
_lock_guard = threading.Lock()


def _get_ship_store() -> ShipStateStore:
    """Get or create the ship state store."""
    repo_root = get_repo_root()
    db_path = os.path.join(repo_root, "ship_state.db")
    return ShipStateStore(db_path=db_path)


def _get_lock(result_id: str) -> threading.Lock:
    """Get a per-result lock for concurrency control."""
    with _lock_guard:
        if result_id not in _ship_locks:
            _ship_locks[result_id] = threading.Lock()
        return _ship_locks[result_id]


# ---- Request models ----

class ShipRequest(BaseModel):
    commit_message: str = ""
    strategy: str = "pr"
    deploy_targets: List[str] = []


class FeedbackRequest(BaseModel):
    feedback: str


class FeedbackResolveRequest(BaseModel):
    clarification_actions: List[str] = []
    expansion_decisions: List[dict] = []


# ---- Routes ----

@router.post("/results/{result_id}/ship", dependencies=[Depends(require_auth)])
async def ship_result(result_id: int, req: ShipRequest):
    """Ship a result: commit, push, PR/merge, optionally deploy."""
    lock = _get_lock(str(result_id))
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="Ship in progress for this result")

    try:
        ship_store = _get_ship_store()
        try:
            # Check already shipped
            existing = ship_store.get_latest_run(str(result_id))
            if existing and existing.status == "shipped":
                return {
                    "status": "already_shipped",
                    "run_id": existing.run_id,
                }

            repo_root = get_repo_root()
            opts = ShipOptions(
                root=repo_root,
                message=req.commit_message,
                strategy=req.strategy,
                deploy=bool(req.deploy_targets),
                deploy_targets=req.deploy_targets,
                actor="dashboard",
                result_id=str(result_id),
            )

            result = run_pipeline(opts, store=ship_store)
            response = {
                "status": result.status,
                "run_id": result.run_id,
                "steps": [s.to_dict() for s in result.steps],
            }
            if result.pr_url:
                response["pr_url"] = result.pr_url
            if result.merge_sha:
                response["merge_sha"] = result.merge_sha
            if result.test_url:
                response["test_url"] = result.test_url
            return response

        finally:
            ship_store.close()
    finally:
        lock.release()


@router.post("/results/{result_id}/promote",
             dependencies=[Depends(require_auth)])
async def promote_result(result_id: int):
    """Promote a test deploy to production."""
    ship_store = _get_ship_store()
    try:
        repo_root = get_repo_root()
        result = promote_to_production(
            str(result_id), ship_store, repo_root,
        )
        return {
            "status": result.status,
            "run_id": result.run_id,
            "steps": [s.to_dict() for s in result.steps],
        }
    finally:
        ship_store.close()


@router.post("/results/{result_id}/feedback",
             dependencies=[Depends(require_auth)])
async def submit_feedback(result_id: int, req: FeedbackRequest):
    """Classify developer feedback on a shipped result."""
    classification = classify_feedback(req.feedback)
    return classification.to_dict()


@router.post("/results/{result_id}/feedback/resolve",
             dependencies=[Depends(require_auth)])
async def resolve_result_feedback(result_id: int,
                                   req: FeedbackResolveRequest):
    """Act on feedback decisions (clarifications, expansions)."""
    ship_store = _get_ship_store()
    try:
        repo_root = get_repo_root()
        result = resolve_feedback(
            str(result_id),
            ship_store,
            repo_root,
            clarification_actions=req.clarification_actions,
            expansion_decisions=req.expansion_decisions,
        )
        return result
    finally:
        ship_store.close()
