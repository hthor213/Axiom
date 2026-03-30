"""Audit logging for the ship pipeline.

Appends JSONL entries to logs/ship.log. Each entry records a pipeline
step with timestamp, run_id, result_id, actor, step, status, and detail.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import PipelineRun, StepResult
    from .pipeline import ShipOptions


def _log_dir(root: str) -> str:
    """Get or create the logs directory under the project root."""
    d = os.path.join(root, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def log_step(
    run: PipelineRun,
    step: StepResult,
    opts: ShipOptions,
) -> None:
    """Append a step result to the ship audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run.run_id,
        "result_id": run.result_id,
        "actor": run.actor,
        "step": step.step,
        "status": step.status,
        "detail": step.detail,
    }
    log_path = os.path.join(_log_dir(opts.root), "ship.log")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Logging failure is non-fatal


def log_scope_change(
    run: PipelineRun,
    reason: str,
    detail: str,
    opts: ShipOptions,
) -> None:
    """Log a scope change decision (clarification/expansion/contradiction)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run.run_id,
        "result_id": run.result_id,
        "actor": run.actor,
        "step": "scope_change",
        "status": "ok",
        "detail": detail,
        "reason": reason,
    }
    log_path = os.path.join(_log_dir(opts.root), "ship.log")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
