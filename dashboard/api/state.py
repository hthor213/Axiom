"""Shared state and dependencies for dashboard API routes.

Extracted to avoid circular imports between app.py and route modules.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

from fastapi import HTTPException, Request, WebSocket

# Add lib path for imports
_lib_path = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "python")
if _lib_path not in sys.path:
    sys.path.insert(0, os.path.abspath(_lib_path))

from runtime.db import TaskStore

from .auth import verify_jwt


# ---- Shared state ----

_store: Optional[TaskStore] = None
_ws_clients: list[WebSocket] = []
_active_runs: dict[int, asyncio.Task] = {}  # run_key -> asyncio.Task
_next_run_key: int = 0


def get_store() -> TaskStore:
    """Get or create the TaskStore singleton."""
    global _store
    if _store is None:
        # Allow test injection via dashboard.api.app._store (avoids circular import)
        import sys
        app_mod = sys.modules.get("dashboard.api.app")
        if app_mod is not None and getattr(app_mod, "_store", None) is not None:
            return app_mod._store
        pg_conn = os.environ.get("DATABASE_URL")
        if not pg_conn:
            raise RuntimeError("DATABASE_URL environment variable required")
        _store = TaskStore(pg_conn_string=pg_conn)
    return _store


def get_repo_root() -> str:
    """Get the repository root path."""
    return os.environ.get("REPO_ROOT",
                          os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _next_run_key_incr() -> int:
    """Increment and return the next run key."""
    global _next_run_key
    _next_run_key += 1
    return _next_run_key


def _cleanup_finished_runs():
    """Remove completed runs from _active_runs dict."""
    finished = [k for k, t in _active_runs.items() if t.done()]
    for k in finished:
        del _active_runs[k]


# ---- Auth dependency ----

async def require_auth(request: Request):
    """Extract and verify JWT from Authorization: Bearer header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    payload = verify_jwt(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
