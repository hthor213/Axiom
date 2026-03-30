"""Data models (dataclasses) for the autonomous runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Task:
    """A queued task for autonomous execution."""
    id: Optional[int] = None
    spec_number: str = ""
    spec_title: str = ""
    done_when_item: str = ""
    status: str = "queued"
    priority: int = 100
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    base_commit: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    queued_by: str = "dashboard"
    user_instructions: str = ""
    pipeline_stage: Optional[str] = None  # agent_building|tests_running|triage_fixing|adversarial_review|complete
    stop_reason: Optional[str] = None
    project_id: Optional[int] = None


@dataclass
class Run:
    """A single execution run (batch of tasks)."""
    id: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str = "running"
    stop_reason: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_turns: int = 0
    total_api_calls: int = 0
    config: dict = field(default_factory=dict)
    project_id: Optional[int] = None


@dataclass
class AgentSession:
    """A Claude Agent SDK session for a single task."""
    id: Optional[int] = None
    task_id: Optional[int] = None
    run_id: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str = "running"
    turns_used: int = 0
    max_turns: int = 30
    time_limit_min: int = 60
    failure_count: int = 0
    max_failures: int = 3
    last_tool_call: Optional[str] = None
    last_output: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Result:
    """Result of a completed task."""
    id: Optional[int] = None
    task_id: Optional[int] = None
    session_id: Optional[int] = None
    created_at: Optional[str] = None
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    diff_summary: Optional[str] = None
    test_passed: int = 0
    test_failed: int = 0
    test_output: Optional[str] = None
    adversarial_verdict: Optional[str] = None
    adversarial_report: Optional[dict] = None
    harness_check: Optional[dict] = None
    approved: Optional[bool] = None
    approved_at: Optional[str] = None
    reject_reason: Optional[str] = None
    project_id: Optional[int] = None


@dataclass
class DraftReview:
    """A draft spec review with questions for the human."""
    id: Optional[int] = None
    task_id: Optional[int] = None
    spec_number: str = ""
    spec_title: str = ""
    version: int = 1
    original_spec: Optional[str] = None
    refined_spec: Optional[str] = None
    questions: Optional[list] = None
    answers: Optional[list] = None
    gemini_feedback: Optional[str] = None
    status: str = "pending_answers"  # pending_answers | answered | resumed
    created_at: Optional[str] = None
    answered_at: Optional[str] = None
    resumed_at: Optional[str] = None


@dataclass
class TaskPlan:
    """A build plan generated before execution."""
    id: Optional[int] = None
    task_id: Optional[int] = None
    plan_text: str = ""
    mentor_feedback: Optional[str] = None
    status: str = "accepted"  # pending | accepted | rejected
    created_at: Optional[str] = None
    project_id: Optional[int] = None


@dataclass
class SpecReview:
    """Interactive spec review: GPT mentor → Claude editor → human approve/modify."""
    id: Optional[int] = None
    spec_number: str = ""
    version: int = 1
    original_content: str = ""
    user_modifications: Optional[str] = None
    gpt_feedback: Optional[str] = None
    edited_content: Optional[str] = None
    human_comments: Optional[str] = None
    status: str = "pending"  # pending | approved | rejected
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
