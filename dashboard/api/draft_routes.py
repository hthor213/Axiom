"""Draft review routes for the dashboard API.

Handles: GET /drafts, GET /drafts/{id}, POST /drafts/{id}/answer,
         POST /drafts/{id}/approve.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth

from runtime.server import RuntimeServer, RuntimeConfig


router = APIRouter()


class AnswerRequest(BaseModel):
    answers: list[str]


@router.get("/drafts", dependencies=[Depends(require_auth)])
async def get_drafts(status: Optional[str] = None):
    """List draft reviews."""
    store = get_store()
    drafts = store.get_draft_reviews(status=status)
    return {
        "drafts": [
            {
                "id": d.id,
                "task_id": d.task_id,
                "spec_number": d.spec_number,
                "spec_title": d.spec_title,
                "version": d.version,
                "questions": d.questions,
                "answers": d.answers,
                "gemini_feedback": d.gemini_feedback,
                "status": d.status,
                "created_at": d.created_at,
                "answered_at": d.answered_at,
            }
            for d in drafts
        ]
    }


@router.get("/drafts/{draft_id}", dependencies=[Depends(require_auth)])
async def get_draft(draft_id: int):
    """Get a single draft review with full context."""
    store = get_store()
    d = store.get_draft_review(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {
        "id": d.id,
        "task_id": d.task_id,
        "spec_number": d.spec_number,
        "spec_title": d.spec_title,
        "version": d.version,
        "original_spec": d.original_spec,
        "refined_spec": d.refined_spec,
        "questions": d.questions,
        "answers": d.answers,
        "gemini_feedback": d.gemini_feedback,
        "status": d.status,
        "created_at": d.created_at,
        "answered_at": d.answered_at,
        "resumed_at": d.resumed_at,
    }


@router.post("/drafts/{draft_id}/answer", dependencies=[Depends(require_auth)])
async def answer_draft(draft_id: int, req: AnswerRequest):
    """Submit answers to a draft review's questions. Triggers re-queue."""
    store = get_store()
    d = store.get_draft_review(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    if d.status != "pending_answers":
        raise HTTPException(status_code=400,
                            detail=f"Draft is in '{d.status}' state, not pending_answers")

    store.update_draft_review(
        draft_id,
        answers=req.answers,
        status="answered",
        answered_at=datetime.now(timezone.utc).isoformat(),
    )

    repo_root = get_repo_root()
    config = RuntimeConfig(repo_root=repo_root)
    server = RuntimeServer(store, config)
    new_task = server.resume_draft_review(draft_id)

    if new_task:
        return {"status": "ok", "message": "Answers saved, new review task queued",
                "task_id": new_task.id}
    return {"status": "ok", "message": "Answers saved"}


@router.post("/drafts/{draft_id}/approve", dependencies=[Depends(require_auth)])
async def approve_draft(draft_id: int):
    """Mark a draft as done (no more iterations needed)."""
    store = get_store()
    d = store.get_draft_review(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")

    store.update_draft_review(draft_id, status="approved")
    if d.task_id:
        store.update_task_status(d.task_id, "passed")

    return {"status": "ok", "message": "Draft approved"}
