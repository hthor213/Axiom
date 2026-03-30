"""Spec review routes: interactive GPT-mentor + Claude-editor review loop.

Handles: POST /specs/{n}/review, /specs/{n}/review/{id}/approve,
         /specs/{n}/review/{id}/modify.

Two flows depending on whether the user provides instructions:
- No instructions: GPT reviews spec → Claude incorporates feedback → human reviews
- With instructions: Claude edits per instructions → GPT reviews changes → human reviews

Iterates on Modify until human approves or rejects.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import urllib.request

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, get_repo_root, require_auth
from .spec_crud_routes import _resolve_repo_root


router = APIRouter()


# ---- Pydantic models ----

class SpecReviewRequest(BaseModel):
    modifications: str = ""


class SpecModifyRequest(BaseModel):
    comments: str


# ---- LLM call helpers ----

def _get_api_key(provider: str) -> str:
    key_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    key = os.environ.get(key_map.get(provider, ""))
    if not key:
        raise HTTPException(status_code=500,
                            detail=f"Missing {key_map.get(provider)} env var")
    return key


def _call_gpt(prompt: str, system: str) -> str:
    api_key = _get_api_key("openai")
    body = json.dumps({
        "model": "gpt-5.4",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": 16384,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _call_claude(prompt: str, system: str) -> str:
    api_key = _get_api_key("anthropic")
    body = json.dumps({
        "model": "claude-opus-4-6",
        "max_tokens": 16384,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


# ---- Prompts ----

GPT_MENTOR_SYSTEM = """You are reviewing a spec for a software development framework.
Your role is mentor — help the author see what they're missing.

Be a good teacher:
- Point out gaps, ambiguities, and missed edge cases
- Suggest concrete improvements
- No praise — assume the author wants honest help, not validation
- Not hostile — you're helping, not attacking
- Focus on: completeness, testability of Done When items, architectural
  clarity, missing constraints, prerequisite gaps

Keep your feedback structured and actionable. Use numbered points."""

GPT_CHANGE_REVIEWER_SYSTEM = """You are reviewing changes made to a spec for a software
development framework. Claude edited this spec based on the author's instructions.

Your role is mentor — review the changes and point out what's still missing.

Be a good teacher:
- Evaluate whether the edits address the author's intent
- Point out new gaps introduced by the changes
- No praise — assume the author wants honest help, not validation
- Not hostile — you're helping, not attacking
- Focus on: completeness, testability, architectural clarity

Keep your feedback structured and actionable. Use numbered points."""

CLAUDE_EDITOR_SYSTEM = """You are editing a spec based on mentor feedback.
You are trusted to make good corrections.

Rules:
- Preserve the existing markdown structure and format
- Address the mentor's feedback points
- Keep Done When items concrete and verifiable
- Return ONLY the complete updated spec markdown — no explanation, no fences"""

CLAUDE_INSTRUCTOR_SYSTEM = """You are editing a spec based on the author's instructions.
You are trusted to make good corrections.

Rules:
- Follow the author's instructions carefully
- Preserve the existing markdown structure and format
- Keep Done When items concrete and verifiable
- Return ONLY the complete updated spec markdown — no explanation, no fences"""

CLAUDE_REEDITOR_SYSTEM = """You are re-editing a spec based on human feedback
on your previous edit. You are trusted to make good corrections.

Rules:
- Address the human's specific comments
- Preserve the existing markdown structure and format
- Keep Done When items concrete and verifiable
- Return ONLY the complete updated spec markdown — no explanation, no fences"""


# ---- Helpers ----

def _find_spec_file(spec_number: str, repo_root: Optional[str] = None) -> tuple[str, str]:
    root = repo_root or get_repo_root()
    specs_dir = os.path.join(root, "specs")
    if not os.path.isdir(specs_dir):
        raise HTTPException(status_code=404, detail="No specs directory")
    for fname in sorted(os.listdir(specs_dir)):
        if fname.startswith(spec_number) and fname.endswith(".md"):
            return os.path.join(specs_dir, fname), fname
    raise HTTPException(status_code=404, detail=f"Spec {spec_number} not found")


def _simple_diff(original: str, edited: str) -> str:
    orig_lines = original.splitlines()
    edit_lines = edited.splitlines()
    diff_parts = []
    max_lines = max(len(orig_lines), len(edit_lines))
    for i in range(max_lines):
        orig = orig_lines[i] if i < len(orig_lines) else ""
        edit = edit_lines[i] if i < len(edit_lines) else ""
        if orig != edit:
            if orig and edit:
                diff_parts.append(f"~L{i+1}: {orig[:80]} → {edit[:80]}")
            elif edit:
                diff_parts.append(f"+L{i+1}: {edit[:80]}")
            else:
                diff_parts.append(f"-L{i+1}: {orig[:80]}")
    return "\n".join(diff_parts[:50]) if diff_parts else "(no changes)"


def _run_review_no_instructions(original: str) -> tuple[str, str]:
    """No instructions: GPT reviews → Claude incorporates."""
    mentor_prompt = (
        f"Here is the spec:\n\n{original}\n\n"
        f"What is this spec missing? What could be clearer?"
    )
    gpt_feedback = _call_gpt(mentor_prompt, GPT_MENTOR_SYSTEM)

    editor_prompt = (
        f"Original spec:\n\n{original}\n\n"
        f"Mentor (GPT) feedback:\n\n{gpt_feedback}"
    )
    edited = _call_claude(editor_prompt, CLAUDE_EDITOR_SYSTEM)
    return gpt_feedback, edited


def _run_review_with_instructions(original: str, instructions: str) -> tuple[str, str]:
    """With instructions: Claude edits first → GPT reviews changes."""
    editor_prompt = (
        f"Original spec:\n\n{original}\n\n"
        f"Author's instructions:\n{instructions}"
    )
    edited = _call_claude(editor_prompt, CLAUDE_INSTRUCTOR_SYSTEM)

    reviewer_prompt = (
        f"Original spec:\n\n{original}\n\n"
        f"Author's instructions for changes:\n{instructions}\n\n"
        f"Updated spec (Claude's edits):\n\n{edited}\n\n"
        f"Review the changes. What's still missing?"
    )
    gpt_feedback = _call_gpt(reviewer_prompt, GPT_CHANGE_REVIEWER_SYSTEM)
    return gpt_feedback, edited


# ---- Endpoints ----

@router.post("/specs/{spec_number}/review", dependencies=[Depends(require_auth)])
async def review_spec(spec_number: str, req: SpecReviewRequest,
                      project: Optional[int] = None):
    """Start spec review. Runs LLM calls in a thread to avoid blocking.

    - No instructions: GPT reviews → Claude incorporates feedback
    - With instructions: Claude edits per instructions → GPT reviews changes
    """
    store = get_store()
    repo_root = _resolve_repo_root(store, project)
    spec_path, _ = _find_spec_file(spec_number, repo_root=repo_root)
    with open(spec_path) as f:
        original = f.read()

    modifications = req.modifications.strip()

    if modifications:
        gpt_feedback, edited = await asyncio.to_thread(
            _run_review_with_instructions, original, modifications)
    else:
        gpt_feedback, edited = await asyncio.to_thread(
            _run_review_no_instructions, original)

    from runtime.db import SpecReview
    store = get_store()
    review = store.create_spec_review(SpecReview(
        spec_number=spec_number,
        version=1,
        original_content=original,
        user_modifications=modifications or None,
        gpt_feedback=gpt_feedback,
        edited_content=edited,
        status="pending",
    ))

    return {
        "review_id": review.id,
        "original": original,
        "edited": edited,
        "diff": _simple_diff(original, edited),
        "gpt_feedback": gpt_feedback,
    }


@router.post("/specs/{spec_number}/review/{review_id}/approve",
              dependencies=[Depends(require_auth)])
async def approve_spec_review(spec_number: str, review_id: int,
                              project: Optional[int] = None):
    """Accept Claude's edits — write to disk and commit."""
    store = get_store()
    review = store.get_spec_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.spec_number != spec_number:
        raise HTTPException(status_code=400, detail="Spec number mismatch")
    if review.status != "pending":
        raise HTTPException(status_code=400,
                            detail=f"Review is {review.status}, not pending")

    repo_root = _resolve_repo_root(store, project) or get_repo_root()
    spec_path, _ = _find_spec_file(spec_number, repo_root=repo_root)
    with open(spec_path, "w") as f:
        f.write(review.edited_content)
    try:
        subprocess.run(["git", "add", spec_path],
                        cwd=repo_root, check=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m",
             f"spec: {spec_number} reviewed — GPT mentor + Claude editor"],
            cwd=repo_root, check=True, timeout=10)
        subprocess.run(["git", "push", "origin"], cwd=repo_root, timeout=30)
    except subprocess.CalledProcessError:
        pass

    store.update_spec_review(review_id, status="approved")
    return {"status": "ok", "spec_number": spec_number}


@router.post("/specs/{spec_number}/review/{review_id}/modify",
              dependencies=[Depends(require_auth)])
async def modify_spec_review(spec_number: str, review_id: int,
                              req: SpecModifyRequest):
    """Human wants changes — Claude re-edits, GPT re-reviews."""
    store = get_store()
    review = store.get_spec_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.spec_number != spec_number:
        raise HTTPException(status_code=400, detail="Spec number mismatch")

    def _do_modify():
        reeditor_prompt = (
            f"Original spec:\n\n{review.original_content}\n\n"
            f"Your previous edit:\n\n{review.edited_content}\n\n"
            f"Human's feedback on your edit:\n{req.comments}"
        )
        new_edited = _call_claude(reeditor_prompt, CLAUDE_REEDITOR_SYSTEM)

        rereview_prompt = (
            f"You previously reviewed this spec and gave feedback. The author "
            f"made changes based on your feedback and additional human input.\n\n"
            f"Original spec:\n\n{review.original_content}\n\n"
            f"Your previous feedback:\n\n{review.gpt_feedback}\n\n"
            f"Human's additional comments:\n{req.comments}\n\n"
            f"Updated spec (Claude's edits):\n\n{new_edited}\n\n"
            f"What do you think of the changes? What's still missing?"
        )
        new_gpt = _call_gpt(rereview_prompt, GPT_MENTOR_SYSTEM)
        return new_edited, new_gpt

    edited, gpt_feedback = await asyncio.to_thread(_do_modify)

    new_version = review.version + 1
    store.update_spec_review(
        review_id,
        version=new_version,
        edited_content=edited,
        gpt_feedback=gpt_feedback,
        human_comments=req.comments,
    )

    return {
        "review_id": review_id,
        "version": new_version,
        "original": review.original_content,
        "edited": edited,
        "diff": _simple_diff(review.original_content, edited),
        "gpt_feedback": gpt_feedback,
    }
