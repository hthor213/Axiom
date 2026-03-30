"""Draft Q&A flow — question extraction, draft review handling, and resume logic.

Manages the lifecycle of draft spec reviews: extracting questions from
refined specs, saving draft review records, resuming after answers,
and running the Gemini 'teacher' validation.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from .db import Task, TaskStore, DraftReview
from .prompts import find_spec


def extract_questions(spec_text: str) -> list[dict]:
    """Extract structured questions from the '## Questions for Human' section.

    Returns list of dicts: {title, question, options: [{label, text, recommended}]}
    """
    questions = []
    match = re.search(r"## Questions for Human\s*\n(.*?)(?=\n## |\Z)", spec_text, re.DOTALL)
    if not match:
        return questions

    section = match.group(1).strip()

    # Split by ### Q headings
    q_blocks = re.split(r"###\s+Q\d+:\s*", section)
    for block in q_blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        title = lines[0].strip() if lines else ""

        # Find the question line (first non-empty line after title that ends with ?)
        question = ""
        options = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            # Option line: starts with - a), - b), etc.
            opt_match = re.match(r"^[-*]\s*([a-d])\)\s*(.*)", line)
            if opt_match:
                label = opt_match.group(1)
                text = opt_match.group(2).strip()
                recommended = "\u2190 RECOMMENDED" in text or "<- RECOMMENDED" in text
                text = re.sub(r"\s*\u2190?\s*<?-?\s*RECOMMENDED\s*", "", text).strip()
                options.append({"label": label, "text": text, "recommended": recommended})
            elif not question:
                question = line

        if question or options:
            questions.append({
                "title": title,
                "question": question,
                "options": options,
            })

    # Fallback: if no structured questions found, try simple bullet extraction
    if not questions:
        for line in section.split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line)
            cleaned = re.sub(r"^[-*]\s*", "", cleaned)
            if cleaned and "?" in cleaned:
                questions.append({
                    "title": cleaned[:50],
                    "question": cleaned,
                    "options": [],
                })

    return questions


def handle_draft_questions(worktree_path: str, task: Task, store: TaskStore,
                           repo_root: str, config, emit_fn: Callable,
                           adversarial_report: Optional[dict]):
    """Extract questions from refined spec, save draft review, notify via Telegram."""
    from .notifications import send_draft_questions

    # Read the refined spec from worktree
    spec_path = None
    specs_dir = os.path.join(worktree_path, "specs")
    if os.path.isdir(specs_dir):
        for fname in os.listdir(specs_dir):
            if fname.startswith(f"{task.spec_number}-") and fname.endswith(".md"):
                spec_path = os.path.join(specs_dir, fname)
                break

    if not spec_path or not os.path.isfile(spec_path):
        return

    try:
        with open(spec_path) as f:
            refined_spec = f.read()
    except OSError:
        return

    questions = extract_questions(refined_spec)
    if not questions:
        return

    # Read original spec for comparison
    original_spec = ""
    orig_path = find_spec(task.spec_number, repo_root)
    if orig_path:
        try:
            with open(orig_path) as f:
                original_spec = f.read()
        except OSError:
            pass

    # Get next version number
    version = store.get_latest_draft_version(task.spec_number) + 1

    # Gemini feedback text
    gemini_text = ""
    if adversarial_report:
        gemini_text = adversarial_report.get("summary", "")

    # Create draft review record
    draft = DraftReview(
        task_id=task.id,
        spec_number=task.spec_number,
        spec_title=task.spec_title,
        version=version,
        original_spec=original_spec,
        refined_spec=refined_spec,
        questions=questions,
        gemini_feedback=gemini_text,
        status="pending_answers",
    )
    draft = store.create_draft_review(draft)

    # Set task to waiting_for_human
    store.update_task_status(task.id, "waiting_for_human")

    # Send to Telegram (primary notification)
    if config.telegram_notify:
        send_draft_questions(draft, config)

    emit_fn("draft_questions", {
        "task_id": task.id,
        "draft_id": draft.id,
        "spec_number": task.spec_number,
        "question_count": len(questions),
    })


def resume_draft_review(draft_id: int, store: TaskStore) -> Optional[Task]:
    """Resume a draft review after answers are provided.

    Creates a new __draft_review__ task with enriched context including
    the original spec, previous refinement, Q&A, and Gemini feedback.
    """
    draft = store.get_draft_review(draft_id)
    if not draft or draft.status != "answered":
        return None

    # Build enriched prompt context
    qa_text = ""
    if draft.questions and draft.answers:
        for i, (q, a) in enumerate(zip(draft.questions, draft.answers), 1):
            if isinstance(q, dict):
                q_str = q.get("question", q.get("title", str(q)))
            else:
                q_str = str(q)
            qa_text += f"\n{i}. Q: {q_str}\n   A: {a}\n"

    context = f"""## Previous Context (v0.{draft.version})

### Original Spec
{draft.original_spec or '(not available)'}

### Claude's Refinement (v0.{draft.version})
{draft.refined_spec or '(not available)'}

### Gemini Feedback
{draft.gemini_feedback or '(none)'}

### Human Answers to Questions
{qa_text or '(none)'}
"""

    # Create a new task with the enriched context
    new_task = Task(
        spec_number=draft.spec_number,
        spec_title=draft.spec_title,
        done_when_item="__draft_review__",
        priority=50,  # Higher priority than default
        queued_by="draft_resume",
    )
    new_task = store.enqueue_task(new_task)

    # Update draft status
    store.update_draft_review(
        draft_id,
        status="resumed",
        resumed_at=datetime.now(timezone.utc).isoformat(),
    )

    # Store the context for the agent prompt builder to find
    # We store it as a special field on the task using worktree_path temporarily
    # A cleaner approach would be a task_context table, but this works for now
    store.update_task_status(
        new_task.id, "queued",
        worktree_path=f"__draft_context__:{draft_id}",
    )

    return new_task


def run_draft_review(worktree_path: str, task_spec_number: str,
                     repo_root: str) -> tuple[Optional[str], Optional[dict]]:
    """Run Gemini as 'teacher' to validate a draft spec refinement.

    Sends the refined spec to Gemini and asks: did the student do a good job?
    Returns (verdict, report_dict).
    """
    spec_path = None
    specs_dir = os.path.join(worktree_path, "specs")
    if os.path.isdir(specs_dir):
        for fname in os.listdir(specs_dir):
            if fname.startswith(f"{task_spec_number}-") and fname.endswith(".md"):
                spec_path = os.path.join(specs_dir, fname)
                break

    if not spec_path or not os.path.isfile(spec_path):
        return "SKIP", None

    try:
        with open(spec_path) as f:
            refined_spec = f.read()
    except OSError:
        return "SKIP", None

    original_spec = ""
    orig_path = find_spec(task_spec_number, repo_root)
    if orig_path:
        try:
            with open(orig_path) as f:
                original_spec = f.read()
        except OSError:
            pass

    try:
        lib_path = os.path.join(repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from adversarial.credentials import load_credentials
        from adversarial.model_resolver import resolve_models

        creds = load_credentials(repo_root)
        if "google" not in creds:
            return "SKIP", None

        models = resolve_models(creds)

        prompt = f"""You are a senior technical reviewer evaluating a spec refinement.

## Original draft spec
{original_spec}

## Refined spec (student's work)
{refined_spec}

## Evaluation criteria
1. Did the student ADD genuine value, or just pad with fluff?
2. Are all Done When items concrete and automatable (no subjective language)?
3. Did the student ask at least 3 genuine questions (not obvious ones)?
4. Did the student INVENT requirements not in the original, or stay faithful?
5. Are architecture decisions explicit with file paths and data structures?
6. Is anything still vague ("should", "properly", "correctly")?

## Respond in this format
## Verdict: PASS or FAIL

## Summary
One paragraph assessment.

## Issues (if FAIL)
- Issue 1: what's wrong
- Issue 2: what's wrong
"""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{models.google}:generateContent?key={creds['google']}"
        )
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
        }).encode()

        req = urllib.request.Request(url, data=body,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        verdict = "FAIL"
        verdict_match = re.search(r"Verdict:\s*(PASS|FAIL)", text, re.IGNORECASE)
        if verdict_match:
            verdict = verdict_match.group(1).upper()

        report = {
            "verdict": verdict,
            "summary": text,
            "challenger": {"issues": [], "findings": [text]},
        }
        return verdict, report

    except Exception as e:
        print(f"[runtime] draft review failed: {e}", file=sys.stderr)
        return "SKIP", {"error": str(e)}
