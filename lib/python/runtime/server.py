"""Autonomous runtime server — the main loop.

Deterministic server that processes a task queue:
1. Read next task from DB
2. Create git worktree
3. Run Claude Agent SDK session
4. Run tests + adversarial review
5. Save results
6. Send Telegram notification when batch completes

Python controls the loop. LLMs provide intelligence.
Termination conditions are enforced in code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable

from .db import TaskStore, Task, Run, AgentSession, Result
from .worktree import create_worktree, cleanup_worktree, get_worktree_diff, commit_in_worktree
from .agent_runner import run_agent_session
from .prompts import build_agent_prompt
from .review import verify_draft, verify_code
from .draft_lifecycle import handle_draft_questions, resume_draft_review
from .notifications import send_batch_complete


@dataclass
class RuntimeConfig:
    """Configuration for a runtime execution run."""
    repo_root: str
    max_turns_per_task: int = 30
    time_limit_per_task_min: int = 60
    max_failures_per_task: int = 3
    max_consecutive_failures: int = 3
    max_total_runtime_min: int = 360  # 6 hours
    base_branch: str = "main"
    worktree_dir: str = "/tmp/hth-worktrees"
    run_adversarial: bool = True
    run_plan: bool = True
    telegram_notify: bool = True
    dashboard_url: str = "https://spliffdonk.com"
    project_id: Optional[int] = None   # None = default (single-project mode)


class RuntimeServer:
    """The autonomous runtime server.

    Processes queued tasks by running Claude Agent SDK sessions,
    verifying results, and saving outcomes to the database.
    """

    def __init__(self, store: TaskStore, config: RuntimeConfig):
        self.store = store
        self.config = config
        self._progress_callback: Optional[Callable] = None
        self._should_stop = False

    def set_progress_callback(self, callback: Callable[[dict], None]):
        """Set a callback for progress updates (used by WebSocket streaming)."""
        self._progress_callback = callback

    def stop(self):
        """Signal the server to stop after the current task."""
        self._should_stop = True

    def _emit(self, event_type: str, data: dict):
        """Emit a progress event. Includes project_id when configured."""
        event = {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
        if self.config.project_id is not None:
            event.setdefault("project_id", self.config.project_id)
        if self._progress_callback:
            self._progress_callback(event)

    def process_queue(self, task_ids: list[int] | None = None) -> Run:
        """Process queued tasks. Returns the Run record.

        Args:
            task_ids: If provided, only process these specific tasks (scoped run).
                      If None, processes all queued tasks.
        """
        run = self.store.create_run(config={
            "max_turns_per_task": self.config.max_turns_per_task,
            "time_limit_per_task_min": self.config.time_limit_per_task_min,
            "max_failures_per_task": self.config.max_failures_per_task,
            "task_ids": task_ids,
        })

        start_time = datetime.now(timezone.utc)
        spec_failures: dict[str, int] = {}
        global_consecutive = 0
        tasks_completed = 0
        tasks_failed = 0
        total_turns = 0

        self._emit("run_started", {"run_id": run.id})

        try:
            while not self._should_stop:
                # Check total runtime limit
                elapsed = datetime.now(timezone.utc) - start_time
                if elapsed > timedelta(minutes=self.config.max_total_runtime_min):
                    stop_reason = f"Total runtime limit ({self.config.max_total_runtime_min}min) exceeded"
                    break

                # Check per-spec and global failure limits
                max_spec_fails = max(spec_failures.values()) if spec_failures else 0
                if max_spec_fails >= self.config.max_consecutive_failures:
                    worst = max(spec_failures, key=spec_failures.get)
                    stop_reason = f"Spec {worst}: {max_spec_fails} consecutive failures"
                    break
                if global_consecutive >= self.config.max_consecutive_failures + 2:
                    stop_reason = f"{global_consecutive} consecutive failures (global)"
                    break

                # Get next task (atomic claim — safe for parallel runs)
                task = self.store.claim_next_task(task_ids=task_ids,
                                                  project_id=self.config.project_id)
                if not task:
                    stop_reason = "Queue empty — all tasks processed"
                    break
                self._emit("task_started", {
                    "task_id": task.id,
                    "spec_number": task.spec_number,
                    "done_when": task.done_when_item,
                })

                # Process the task
                try:
                    session_turns = self._process_task(task, run)
                    total_turns += session_turns

                    # Check result
                    task = self.store.get_task(task.id)
                    if task and task.status == "passed":
                        tasks_completed += 1
                        spec_failures[task.spec_number] = 0
                        global_consecutive = 0
                        self._emit("task_completed", {"task_id": task.id, "status": "passed"})
                    else:
                        tasks_failed += 1
                        spec_failures[task.spec_number] = spec_failures.get(task.spec_number, 0) + 1
                        global_consecutive += 1
                        self._emit("task_completed", {"task_id": task.id, "status": "failed"})

                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
                    tasks_failed += 1
                    spec_failures[task.spec_number] = spec_failures.get(task.spec_number, 0) + 1
                    global_consecutive += 1
                    self.store.update_task_status(task.id, "failed")
                    self._emit("task_error", {"task_id": task.id, "error": str(e)})
            else:
                stop_reason = "Stopped by signal"

        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
            stop_reason = f"Runtime error: {e}"

        # Finalize the run
        status = "completed" if tasks_failed == 0 and tasks_completed > 0 else "stopped"
        if not tasks_completed and not tasks_failed:
            status = "completed"  # empty queue is fine

        self.store.finish_run(
            run.id, status, stop_reason,
            tasks_completed, tasks_failed,
            total_turns, 0,
        )

        self._emit("run_finished", {
            "run_id": run.id,
            "status": status,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "stop_reason": stop_reason,
        })

        # Send Telegram notification (skip empty runs — no spam)
        if self.config.telegram_notify and (tasks_completed > 0 or tasks_failed > 0):
            send_batch_complete(run.id, tasks_completed, tasks_failed,
                                stop_reason, self.store, self.config)

        return self.store.get_run(run.id)

    def _maybe_run_plan(self, task: Task, worktree) -> str:
        """Run plan phase if enabled and applicable. Returns plan context."""
        if not self.config.run_plan or task.done_when_item == "__draft_review__":
            return ""
        from .plan_phase import run_plan_phase
        return run_plan_phase(task, worktree, self.config, self.store, self._emit)

    def _build_agent_prompt(self, task: Task, plan_context: str = "") -> str:
        """Build the prompt for the Claude Agent SDK session."""
        return build_agent_prompt(task, self.store, self.config.repo_root,
                                  plan_context=plan_context)

    def _process_task(self, task: Task, run: Run) -> int:
        """Process a single task: worktree → plan → build → test → review → commit."""
        # Preserve draft context before worktree_path gets overwritten
        draft_context_ref = task.worktree_path if (
            task.worktree_path and task.worktree_path.startswith("__draft_context__:")
        ) else None

        worktree = create_worktree(
            self.config.repo_root,
            task.id,
            task.spec_number,
            self.config.base_branch,
            self.config.worktree_dir,
        )
        self.store.update_task_status(
            task.id, "running",
            branch_name=worktree.branch,
            worktree_path=worktree.path,
            base_commit=worktree.base_commit,
            pipeline_stage="agent_building",
        )
        # Keep draft_context_ref on the in-memory task so _build_agent_prompt can read it
        if draft_context_ref:
            task.worktree_path = draft_context_ref

        session = AgentSession(
            task_id=task.id,
            run_id=run.id,
            max_turns=self.config.max_turns_per_task,
            time_limit_min=self.config.time_limit_per_task_min,
            max_failures=self.config.max_failures_per_task,
        )
        session = self.store.create_session(session)
        self._emit("session_started", {
            "session_id": session.id,
            "task_id": task.id,
            "run_id": run.id,
        })

        turns_used = 0
        try:
            # Plan phase (optional) — generate plan before building
            plan_context = self._maybe_run_plan(task, worktree)

            # Step 3: Initial build
            prompt = self._build_agent_prompt(task, plan_context=plan_context)
            turns_used = run_agent_session(
                task, session, worktree, self.store, self.config, self._emit, prompt,
            )

            # If agent session failed, don't proceed — the agent did no work.
            refreshed = self.store.get_session(session.id)
            if refreshed and refreshed.status == "failed":
                self.store.update_task_status(task.id, "failed")
                result = Result(
                    task_id=task.id, session_id=session.id,
                    branch_name=worktree.branch, adversarial_verdict="SKIP",
                    adversarial_report={"error": refreshed.error or "Agent session failed"},
                    project_id=self.config.project_id,
                )
                self.store.save_result(result)
                self._emit("task_completed", {"task_id": task.id, "status": "failed"})
                return turns_used

            self.store.update_session(session.id, turns_used=turns_used,
                                       status="completed",
                                       finished_at=datetime.now(timezone.utc).isoformat())

            # Delegate to verification path
            is_draft_review = task.done_when_item == "__draft_review__"
            harness_result = {}
            test_passed = test_failed = 0
            test_output = ""

            if is_draft_review:
                self.store.update_task_status(task.id, "running",
                                              pipeline_stage="adversarial_review")
                adversarial_verdict, adversarial_report, extra_turns = verify_draft(
                    task, worktree, self.config, self._emit)
                turns_used += extra_turns
                handle_draft_questions(
                    worktree.path, task, self.store,
                    self.config.repo_root, self.config, self._emit,
                    adversarial_report)
            else:
                self.store.update_task_status(task.id, "running",
                                              pipeline_stage="tests_running")
                (adversarial_verdict, adversarial_report, harness_result,
                 test_passed, test_failed, test_output, extra_turns) = verify_code(
                    task, worktree, self.store, self.config, self._emit,
                    plan_context=plan_context)
                turns_used += extra_turns

            # Step 8: Commit, evaluate quality gates, save result
            commit_sha = commit_in_worktree(
                worktree.path,
                f"auto: spec:{task.spec_number} — {task.done_when_item[:60]}")
            diff_summary = get_worktree_diff(
                worktree.path, self.config.base_branch,
                base_commit=worktree.base_commit)

            adversarial_ok = adversarial_verdict in ("PASS", "SKIP")
            is_waiting = adversarial_verdict == "NEEDS_HUMAN"
            tests_ran = test_passed > 0 or test_failed > 0

            # Tests exempt if: draft review OR all changed files ≤ 200 lines
            from .review import check_file_sizes
            sizes = check_file_sizes(worktree.path, worktree.base_commit,
                                     self.config.base_branch)
            tests_exempt = is_draft_review or sizes["all_under_soft"]
            tests_ok = test_failed == 0 and (tests_ran or tests_exempt)

            task_passed = (tests_ok
                           and harness_result.get("failed", 0) == 0
                           and (adversarial_ok or is_draft_review))

            if not is_waiting:
                self.store.update_task_status(
                    task.id, "passed" if task_passed else "failed",
                    pipeline_stage="complete")

            result = Result(
                task_id=task.id, session_id=session.id,
                branch_name=worktree.branch, commit_sha=commit_sha,
                diff_summary=diff_summary, test_passed=test_passed,
                test_failed=test_failed, test_output=test_output or None,
                adversarial_verdict=adversarial_verdict,
                adversarial_report=adversarial_report, harness_check=harness_result,
                project_id=self.config.project_id)
            self.store.save_result(result)

        except Exception as e:
            self.store.update_session(session.id,
                                       status="failed",
                                       error=str(e),
                                       finished_at=datetime.now(timezone.utc).isoformat())
            self.store.update_task_status(task.id, "failed")
            raise
        finally:
            try:
                cleanup_worktree(self.config.repo_root, worktree.path)
            except Exception:
                pass

        return turns_used

    def resume_draft_review(self, draft_id: int):
        """Resume a draft review after answers are provided.

        Delegates to draft_lifecycle.resume_draft_review().
        """
        return resume_draft_review(draft_id, self.store)
