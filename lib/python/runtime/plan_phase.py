"""Plan phase orchestration — plan generation + mentor review + storage.

Called from server._process_task() before the build phase.
Returns a plan context string to include in the execution prompt.
"""

from __future__ import annotations

import os
import sys
from typing import Callable

from .db_models import TaskPlan, Task
from .agent_runner import run_plan_session
from .plan_prompts import build_plan_prompt, build_full_spec_plan_prompt
from .plan_review import review_plan
from .spec_parser import extract_done_when_items


def run_plan_phase(task: Task, worktree, config, store,
                   emit_fn: Callable) -> str:
    """Orchestrate plan generation, mentor review, and DB storage.

    Returns the plan context string to embed in the execution prompt.
    Returns empty string if plan generation fails or is skipped.
    """
    from .prompts import find_spec

    store.update_task_status(task.id, "running", pipeline_stage="planning")
    emit_fn("plan_started", {"task_id": task.id})

    # Load spec content
    spec_path = find_spec(task.spec_number, config.repo_root)
    spec_content = ""
    if spec_path:
        try:
            with open(spec_path) as f:
                spec_content = f.read()
        except OSError:
            pass

    # Build plan prompt based on task type
    if task.done_when_item == "__full_spec__":
        prompt = build_full_spec_plan_prompt(
            task.spec_number, task.spec_title,
            spec_content, task.user_instructions)
    else:
        prompt = build_plan_prompt(
            task.done_when_item, task.spec_number,
            task.spec_title, spec_content, task.user_instructions)

    # Generate plan via Claude in plan mode
    plan_text = run_plan_session(task, worktree, config, emit_fn, prompt)
    if not plan_text:
        emit_fn("plan_failed", {"task_id": task.id, "reason": "empty_plan"})
        return ""

    # GPT mentor review
    done_when = extract_done_when_items(spec_content)
    unchecked = [item["text"] for item in done_when if not item["checked"]]
    mentor_feedback = review_plan(
        plan_text, spec_content, unchecked, config.repo_root)

    # Store in database
    plan = TaskPlan(
        task_id=task.id,
        plan_text=plan_text,
        mentor_feedback=mentor_feedback,
        status="accepted",
        project_id=config.project_id,
    )
    plan = store.save_plan(plan)

    emit_fn("plan_completed", {
        "task_id": task.id,
        "plan_id": plan.id,
        "mentor_feedback_length": len(mentor_feedback) if mentor_feedback else 0,
    })

    # Build context string for execution prompt
    parts = [f"## Your Plan (auto-generated, mentor-reviewed)\n{plan_text}"]
    if mentor_feedback and not mentor_feedback.startswith("Mentor review unavailable"):
        parts.append(f"\n## Mentor Feedback on Plan\n{mentor_feedback}")
    return "\n".join(parts)
