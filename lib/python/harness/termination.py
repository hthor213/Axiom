"""Termination condition evaluation.

Builds and evaluates conditions that determine when a session should stop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .parser import scan_active_specs
from .spec_check import check_spec
from .state import SessionState


@dataclass
class TerminationCondition:
    type: str  # "spec_complete", "time_limit"
    description: str
    spec: Optional[str] = None
    max_minutes: Optional[int] = None
    command: Optional[str] = None


def build_conditions(
    state: SessionState, specs_dir: str
) -> list[TerminationCondition]:
    """Build termination conditions from active specs and session state.

    Generates:
    - One spec_complete condition per active spec
    - One time_limit condition (default 120 min from session start)
    """
    conditions: list[TerminationCondition] = []

    # Spec-complete conditions from active specs
    active = scan_active_specs(specs_dir)
    for spec in active:
        conditions.append(TerminationCondition(
            type="spec_complete",
            description=f"spec:{spec['number']} ({spec['title']}) — all automatable checks pass",
            spec=spec["number"],
        ))

    # Time limit condition
    conditions.append(TerminationCondition(
        type="time_limit",
        description="Session time limit (120 minutes)",
        max_minutes=120,
    ))

    return conditions


def _check_spec_complete(condition: TerminationCondition, project_root: str) -> bool:
    """Check if a spec's automatable Done When items all pass."""
    if not condition.spec:
        return False
    specs_dir = os.path.join(project_root, "specs")
    if not os.path.isdir(specs_dir):
        return False
    # Find the spec file
    for fname in os.listdir(specs_dir):
        if fname.startswith(condition.spec + "-") and fname.endswith(".md"):
            result = check_spec(os.path.join(specs_dir, fname), project_root)
            return result["failed"] == 0 and result["total"] > 0
    return False


def _check_time_limit(condition: TerminationCondition, project_root: str) -> bool:
    """Check if the session has exceeded its time limit."""
    from .state import load_state

    state = load_state(project_root)
    if not state.started_at:
        return False

    max_minutes = condition.max_minutes or 120
    try:
        started = datetime.fromisoformat(state.started_at)
        now = datetime.now(timezone.utc)
        elapsed = (now - started).total_seconds() / 60
        return elapsed >= max_minutes
    except (ValueError, TypeError):
        return False


def evaluate_conditions(
    conditions: list[TerminationCondition], project_root: str
) -> dict:
    """Evaluate all termination conditions.

    Returns dict with:
        should_stop: True if any condition is met
        reason: description of first met condition (or empty)
        conditions_met: list of met condition descriptions
        conditions_remaining: list of unmet condition descriptions
    """
    met: list[str] = []
    remaining: list[str] = []

    for cond in conditions:
        if cond.type == "spec_complete":
            is_met = _check_spec_complete(cond, project_root)
        elif cond.type == "time_limit":
            is_met = _check_time_limit(cond, project_root)
        else:
            is_met = False

        if is_met:
            met.append(cond.description)
        else:
            remaining.append(cond.description)

    should_stop = len(met) > 0
    reason = met[0] if met else ""

    return {
        "should_stop": should_stop,
        "reason": reason,
        "conditions_met": met,
        "conditions_remaining": remaining,
    }


class TerminationEvaluator:
    """Convenience wrapper for termination evaluation."""

    def __init__(self, project_root: str, state: SessionState):
        self.project_root = project_root
        self.state = state
        self.specs_dir = os.path.join(project_root, "specs")

    def build(self) -> list[TerminationCondition]:
        return build_conditions(self.state, self.specs_dir)

    def evaluate(self, conditions: Optional[list[TerminationCondition]] = None) -> dict:
        if conditions is None:
            conditions = self.build()
        return evaluate_conditions(conditions, self.project_root)
