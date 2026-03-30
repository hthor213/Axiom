"""Session state machine.

Defines phases, valid transitions, and persistence for session state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SessionPhase(Enum):
    COLD = "cold"
    STARTED = "started"
    WORKING = "working"
    REFRESHING = "refreshing"
    CHECKPOINTING = "checkpointing"
    ENDED = "ended"


VALID_TRANSITIONS: dict[SessionPhase, list[SessionPhase]] = {
    SessionPhase.COLD: [SessionPhase.STARTED],
    SessionPhase.STARTED: [SessionPhase.WORKING, SessionPhase.ENDED],
    SessionPhase.WORKING: [
        SessionPhase.REFRESHING,
        SessionPhase.CHECKPOINTING,
    ],
    SessionPhase.REFRESHING: [SessionPhase.WORKING],
    SessionPhase.CHECKPOINTING: [SessionPhase.ENDED, SessionPhase.WORKING],
    SessionPhase.ENDED: [SessionPhase.COLD],
}

STATE_FILE = ".harness.json"


@dataclass
class SessionState:
    phase: SessionPhase = SessionPhase.COLD
    started_at: Optional[str] = None
    branch: Optional[str] = None
    active_specs: list[str] = field(default_factory=list)
    focus: str = ""
    gates_passed: dict[str, bool] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    last_transition: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SessionState:
        d = dict(d)  # don't mutate the original
        phase_str = d.pop("phase", "cold")
        try:
            phase = SessionPhase(phase_str)
        except ValueError:
            phase = SessionPhase.COLD
        return cls(phase=phase, **d)


def load_state(project_root: str) -> SessionState:
    """Load session state from .harness.json. Returns COLD state if missing."""
    state_path = os.path.join(project_root, STATE_FILE)
    if not os.path.exists(state_path):
        return SessionState()
    try:
        with open(state_path, "r") as f:
            data = json.load(f)
        return SessionState.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return SessionState()


def save_state(state: SessionState, project_root: str) -> None:
    """Write session state to .harness.json."""
    state_path = os.path.join(project_root, STATE_FILE)
    with open(state_path, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
        f.write("\n")


def transition(state: SessionState, to_phase: SessionPhase) -> SessionState:
    """Validate and execute a phase transition.

    Returns a new SessionState with updated phase and last_transition.
    Raises ValueError if the transition is not allowed.
    """
    allowed = VALID_TRANSITIONS.get(state.phase, [])
    if to_phase not in allowed:
        raise ValueError(
            f"Invalid transition: {state.phase.value} -> {to_phase.value}. "
            f"Allowed: {[p.value for p in allowed]}"
        )

    now = datetime.now(timezone.utc).isoformat()
    new_state = SessionState(
        phase=to_phase,
        started_at=state.started_at if state.started_at else now,
        branch=state.branch,
        active_specs=list(state.active_specs),
        focus=state.focus,
        gates_passed=dict(state.gates_passed),
        artifacts=list(state.artifacts),
        last_transition=now,
    )
    return new_state
