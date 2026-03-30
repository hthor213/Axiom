"""Draft context assembly — loading resume context for draft reviews.

These functions need the store (DB access), which is why they're
separate from the pure prompt templates in prompts.py.
"""

from __future__ import annotations

from typing import Optional

from .db import Task, TaskStore


def format_qa_text(questions: Optional[list], answers: Optional[list]) -> str:
    """Format questions and answers into readable text.

    Shared formatter used by both explicit draft context and
    prior draft lookup paths.
    """
    if not questions or not answers:
        return ""
    parts = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        if isinstance(q, dict):
            q_str = q.get("question", q.get("title", str(q)))
        else:
            q_str = str(q)
        parts.append(f"\n{i}. Q: {q_str}\n   A: {a}\n")
    return "".join(parts)


def load_resume_context(task: Task, store: TaskStore) -> str:
    """Load resume context for a draft review task.

    Handles two cases:
    1. Explicit draft_context reference (from resume_draft_review)
    2. Prior draft lookup (find latest draft for the spec)

    Returns the assembled context string, or empty string if none.
    """
    resume_context = ""

    # Case 1: explicit draft_context reference
    if (task.done_when_item == "__draft_review__"
            and task.worktree_path
            and task.worktree_path.startswith("__draft_context__:")):
        try:
            draft_id = int(task.worktree_path.split(":")[1])
            draft = store.get_draft_review(draft_id)
            if draft:
                qa_text = format_qa_text(draft.questions, draft.answers)
                resume_context = f"""
## Previous Review (v0.{draft.version})

### Gemini Feedback
{draft.gemini_feedback or '(none)'}

### Human Answers to Your Questions
{qa_text or '(none)'}

IMPORTANT: Incorporate the human's answers into your refinement. Do not ask the same questions again.
"""
        except (ValueError, IndexError):
            pass

    # Case 2: no explicit context — check for a prior draft review to build on
    if task.done_when_item == "__draft_review__" and not resume_context:
        try:
            prior = store.get_latest_draft_review(task.spec_number)
            if prior and prior.version > 0:
                qa_text = format_qa_text(prior.questions, prior.answers)

                # Check for rejection reason from the human
                reject_text = ""
                try:
                    results = store.get_results(task_id=prior.task_id)
                    for r in results:
                        if r.approved is False and r.reject_reason:
                            reject_text = (
                                f"\n### Human Rejection Feedback\n{r.reject_reason}\n\n"
                                f"IMPORTANT: The previous attempt was rejected. "
                                f"Address this feedback.\n"
                            )
                            break
                except Exception:
                    pass

                resume_context = f"""
## Previous Review (v0.{prior.version})

### Refined Spec from Previous Review
{prior.refined_spec or '(none)'}

### Gemini Feedback
{prior.gemini_feedback or '(none)'}

### Human Answers to Your Questions
{qa_text or '(none provided yet)'}
{reject_text}
IMPORTANT: Build on the previous refined spec. Incorporate any human answers. Do not ask the same questions again.
"""
        except Exception:
            pass

    return resume_context
