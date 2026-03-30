"""Row-to-dataclass converters for the autonomous runtime database."""

from __future__ import annotations

import json
from typing import Optional

from .db_models import Task, Run, AgentSession, Result, DraftReview, SpecReview, TaskPlan


def dt_str(val) -> Optional[str]:
    """Convert datetime objects to ISO strings."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return val.isoformat() if hasattr(val, 'isoformat') else str(val)


def row_to_task(row: dict) -> Task:
    return Task(
        id=row["id"],
        spec_number=row["spec_number"],
        spec_title=row["spec_title"],
        done_when_item=row["done_when_item"],
        status=row["status"],
        priority=row["priority"],
        branch_name=row["branch_name"],
        worktree_path=row["worktree_path"],
        base_commit=row.get("base_commit"),
        created_at=dt_str(row["created_at"]),
        updated_at=dt_str(row["updated_at"]),
        queued_by=row["queued_by"],
        user_instructions=row.get("user_instructions", ""),
        pipeline_stage=row.get("pipeline_stage"),
        stop_reason=row.get("stop_reason"),
        project_id=row.get("project_id"),
    )


def row_to_run(row: dict) -> Run:
    config = row["config"]
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            config = {}
    return Run(
        id=row["id"],
        started_at=dt_str(row["started_at"]),
        finished_at=dt_str(row["finished_at"]),
        status=row["status"],
        stop_reason=row["stop_reason"],
        tasks_completed=row["tasks_completed"],
        tasks_failed=row["tasks_failed"],
        total_turns=row["total_turns"],
        total_api_calls=row["total_api_calls"],
        config=config or {},
    )


def row_to_session(row: dict) -> AgentSession:
    return AgentSession(
        id=row["id"],
        task_id=row["task_id"],
        run_id=row["run_id"],
        started_at=dt_str(row["started_at"]),
        finished_at=dt_str(row["finished_at"]),
        status=row["status"],
        turns_used=row["turns_used"],
        max_turns=row["max_turns"],
        time_limit_min=row["time_limit_min"],
        failure_count=row["failure_count"],
        max_failures=row["max_failures"],
        last_tool_call=row["last_tool_call"],
        last_output=row["last_output"],
        error=row["error"],
    )


def row_to_result(row: dict) -> Result:
    adv_report = row["adversarial_report"]
    if isinstance(adv_report, str):
        try:
            adv_report = json.loads(adv_report)
        except (json.JSONDecodeError, TypeError):
            adv_report = None
    harness = row["harness_check"]
    if isinstance(harness, str):
        try:
            harness = json.loads(harness)
        except (json.JSONDecodeError, TypeError):
            harness = None
    approved = row["approved"]
    if isinstance(approved, int):
        approved = bool(approved)
    return Result(
        id=row["id"],
        task_id=row["task_id"],
        session_id=row["session_id"],
        created_at=dt_str(row["created_at"]),
        branch_name=row["branch_name"],
        commit_sha=row["commit_sha"],
        diff_summary=row["diff_summary"],
        test_passed=row["test_passed"],
        test_failed=row["test_failed"],
        test_output=row.get("test_output"),
        adversarial_verdict=row["adversarial_verdict"],
        adversarial_report=adv_report,
        harness_check=harness,
        approved=approved,
        approved_at=dt_str(row["approved_at"]),
        reject_reason=row.get("reject_reason"),
    )


def result_to_dict(r: Result) -> dict:
    """Convert a Result to a JSON-safe dict."""
    return {
        "id": r.id,
        "task_id": r.task_id,
        "session_id": r.session_id,
        "branch_name": r.branch_name,
        "commit_sha": r.commit_sha,
        "diff_summary": r.diff_summary,
        "test_passed": r.test_passed,
        "test_failed": r.test_failed,
        "adversarial_verdict": r.adversarial_verdict,
        "adversarial_report": r.adversarial_report,
        "harness_check": r.harness_check,
        "approved": r.approved,
        "approved_at": r.approved_at,
        "reject_reason": r.reject_reason,
        "created_at": r.created_at,
    }


def row_to_draft_review(row: dict) -> DraftReview:
    questions = row["questions"]
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except (json.JSONDecodeError, TypeError):
            questions = None
    answers = row["answers"]
    if isinstance(answers, str):
        try:
            answers = json.loads(answers)
        except (json.JSONDecodeError, TypeError):
            answers = None
    return DraftReview(
        id=row["id"],
        task_id=row["task_id"],
        spec_number=row["spec_number"],
        spec_title=row["spec_title"],
        version=row["version"],
        original_spec=row["original_spec"],
        refined_spec=row["refined_spec"],
        questions=questions,
        answers=answers,
        gemini_feedback=row["gemini_feedback"],
        status=row["status"],
        created_at=dt_str(row["created_at"]),
        answered_at=dt_str(row["answered_at"]),
        resumed_at=dt_str(row["resumed_at"]),
    )


def row_to_plan(row: dict) -> TaskPlan:
    return TaskPlan(
        id=row["id"],
        task_id=row["task_id"],
        plan_text=row["plan_text"],
        mentor_feedback=row.get("mentor_feedback"),
        status=row["status"],
        created_at=dt_str(row["created_at"]),
        project_id=row.get("project_id"),
    )


def row_to_spec_review(row: dict) -> SpecReview:
    return SpecReview(
        id=row["id"],
        spec_number=row["spec_number"],
        version=row["version"],
        original_content=row["original_content"],
        user_modifications=row.get("user_modifications"),
        gpt_feedback=row.get("gpt_feedback"),
        edited_content=row.get("edited_content"),
        human_comments=row.get("human_comments"),
        status=row["status"],
        created_at=dt_str(row.get("created_at")),
        updated_at=dt_str(row.get("updated_at")),
    )
