"""Ship pipeline — orchestration layer.

Drives the step sequence, manages run state, handles resume-on-failure.
Step implementations live in steps.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .state import (
    PipelineRun, StepResult, ShipStateStore, generate_run_id,
)
from .audit import log_step
from .steps import (
    do_verify, do_commit, do_push,
    should_run_review, do_review,
    do_deploy, do_pr_or_merge,
)


@dataclass
class ShipOptions:
    """Configuration for a pipeline run."""

    root: str
    message: str = ""
    strategy: str = "pr"  # "pr" or "merge"
    deploy: bool = False
    deploy_targets: List[str] = field(default_factory=list)
    dry_run: bool = False
    no_tests: bool = False
    actor: str = "cli"
    result_id: str = ""
    adversarial_report: str = ""
    dashboard_link: str = ""


@dataclass
class ShipResult:
    """Final result of the pipeline."""

    status: str  # shipped | failed | awaiting_promotion | already_shipped
    run_id: str = ""
    steps: List[StepResult] = field(default_factory=list)
    pr_url: str = ""
    merge_sha: str = ""
    test_url: str = ""


StepCallback = Optional[Callable[[str, str], None]]


def run_pipeline(
    opts: ShipOptions,
    store: Optional[ShipStateStore] = None,
    on_step: StepCallback = None,
) -> ShipResult:
    """Execute the ship pipeline. Returns ShipResult."""
    if store is None:
        store = ShipStateStore()

    existing = store.get_latest_run(opts.result_id) if opts.result_id else None
    if existing and existing.status == "shipped":
        return ShipResult(
            status="already_shipped", run_id=existing.run_id,
            steps=existing.steps,
        )

    run = _create_or_resume_run(existing, opts, store)
    result = ShipResult(status="running", run_id=run.run_id, steps=run.steps)

    for step_name, step_fn in _step_sequence(opts, result):
        existing_step = _find_step(run.steps, step_name)
        if existing_step and existing_step.status == "ok":
            if on_step:
                on_step(step_name, f"skipped (already {existing_step.status})")
            continue

        if on_step:
            on_step(step_name, "running")

        step_result = step_fn()
        _update_step(run, step_result)
        store.save_run(run)
        log_step(run, step_result, opts)

        if on_step:
            on_step(step_result.step, step_result.status)

        if step_result.status == "failed":
            run.status = "failed"
            result.status = "failed"
            store.save_run(run)
            return result

        if step_result.status == "awaiting_promotion":
            run.status = "awaiting_promotion"
            result.status = "awaiting_promotion"
            store.save_run(run)
            return result

    run.status = "shipped"
    result.status = "shipped"
    store.save_run(run)
    return result


def _create_or_resume_run(
    existing: Optional[PipelineRun], opts: ShipOptions,
    store: ShipStateStore,
) -> PipelineRun:
    if existing and existing.status in ("failed", "running"):
        existing.status = "running"
        store.save_run(existing)
        return existing

    run = PipelineRun(
        run_id=generate_run_id(),
        result_id=opts.result_id or generate_run_id(),
        actor=opts.actor,
        strategy=opts.strategy,
        created_at=time.time(),
        commit_message=opts.message,
    )
    store.save_run(run)
    return run


def _find_step(steps: List[StepResult], name: str) -> Optional[StepResult]:
    for s in steps:
        if s.step == name:
            return s
    return None


def _update_step(run: PipelineRun, step: StepResult) -> None:
    for i, s in enumerate(run.steps):
        if s.step == step.step:
            run.steps[i] = step
            return
    run.steps.append(step)


def _step_sequence(opts: ShipOptions, result: ShipResult):
    """Yield (step_name, step_fn) tuples for the pipeline."""
    yield "verify", lambda: do_verify(opts)
    yield "commit", lambda: do_commit(opts)
    yield "push", lambda: do_push(opts)
    if should_run_review(opts):
        yield "review", lambda: do_review(opts)
    yield "pr_or_merge", lambda: do_pr_or_merge(opts, result, _find_step)
    if opts.deploy or opts.deploy_targets:
        yield "deploy", lambda: do_deploy(opts, result)
