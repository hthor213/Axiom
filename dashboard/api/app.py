"""FastAPI dashboard application for the autonomous runtime.

Core module: app setup, auth endpoints, WebSocket, health check, frontend serving.
Routes split into: queue_routes.py, result_routes.py, draft_routes.py.
Shared state lives in state.py to avoid circular imports.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .state import (
    get_store, require_auth, _ws_clients,
)
from .auth import verify_google_token, is_allowed, create_jwt, verify_jwt


# ---- App ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crash recovery on startup: mark orphaned running tasks as stopped
    try:
        store = get_store()
        recovered = store.recover_orphaned_tasks()
        if recovered:
            print(f"[startup] Crash recovery: marked {recovered} orphaned tasks as stopped")
        stale = store.cancel_stale_tasks()
        if stale:
            print(f"[startup] Stale cleanup: cancelled {stale} old queued tasks")
    except Exception as e:
        print(f"[startup] Recovery failed (non-fatal): {e}")

    # Auto-discover projects from GitHub + local directories
    try:
        from runtime.project_discovery import sync_projects
        # Support multiple GitHub accounts via comma-separated tokens
        gh_raw = os.environ.get("GITHUB_TOKENS") or os.environ.get("GITHUB_TOKEN") or ""
        gh_tokens = [t for t in gh_raw.split(",") if t.strip()]
        local_dirs = [d for d in [
            os.path.expanduser("~/code"),
            os.path.expanduser("~/Documents/GitHub"),
            os.path.expanduser("~/code"),
            os.path.expanduser("~/Documents/GitHub"),
        ] if os.path.isdir(d)]
        result = sync_projects(
            store._pg_conn_string,
            github_tokens=gh_tokens,
            local_dirs=local_dirs,
        )
        if result["added"]:
            print(f"[startup] Project discovery: added {result['added']} "
                  f"(total: {result['total']})")
    except Exception as e:
        print(f"[startup] Project discovery failed (non-fatal): {e}")
    yield
    # Cleanup
    try:
        store = get_store()
        store.close()
    except Exception:
        pass


app = FastAPI(
    title="HTH Dashboard",
    description="Human control plane for the autonomous runtime",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Include route modules ----

from .queue_routes import router as queue_router
from .task_routes import router as task_router
from .spec_crud_routes import router as spec_crud_router
from .result_routes import router as result_router
from .draft_routes import router as draft_router
from .spec_routes import router as spec_router
from .ship_routes import router as ship_router
from .health_routes import router as health_router
from .project_routes import router as project_router
from .infer_routes import router as infer_router

app.include_router(queue_router)
app.include_router(task_router)
app.include_router(spec_crud_router)
app.include_router(result_router)
app.include_router(draft_router)
app.include_router(spec_router)
app.include_router(ship_router)
app.include_router(health_router)
app.include_router(project_router)
app.include_router(infer_router)


# ---- Auth endpoints ----

class GoogleLoginRequest(BaseModel):
    token: str


@app.get("/auth/config")
async def auth_config():
    """Public endpoint: returns Google Client ID for the frontend."""
    from .auth import _get_google_client_id
    return {"google_client_id": _get_google_client_id()}


@app.post("/auth/google-login")
async def google_login(req: GoogleLoginRequest):
    """Exchange a Google ID token for a JWT."""
    user_info = verify_google_token(req.token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    if not is_allowed(user_info["email"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    token = create_jwt(user_info["email"], user_info.get("name", ""))
    return {"token": token, "email": user_info["email"],
            "name": user_info.get("name", ""), "picture": user_info.get("picture", "")}


@app.get("/auth/me", dependencies=[Depends(require_auth)])
async def get_me(request: Request):
    """Get current user info from JWT."""
    auth = request.headers.get("Authorization", "")
    payload = verify_jwt(auth[7:])
    return {"email": payload["sub"], "name": payload.get("name", "")}


# ---- Agents (Live) ----

@app.get("/agents", dependencies=[Depends(require_auth)])
async def get_agents():
    """Get running agent sessions with task/spec context."""
    store = get_store()
    sessions = store.get_active_sessions()
    result = []
    for s in sessions:
        entry = {
            "id": s.id,
            "task_id": s.task_id,
            "run_id": s.run_id,
            "status": s.status,
            "turns_used": s.turns_used,
            "max_turns": s.max_turns,
            "time_limit_min": s.time_limit_min,
            "failure_count": s.failure_count,
            "last_tool_call": s.last_tool_call,
            "started_at": s.started_at,
        }
        try:
            task = store.get_task(s.task_id)
            if task:
                entry["spec_number"] = task.spec_number
                entry["spec_title"] = task.spec_title
                entry["done_when_item"] = task.done_when_item
        except Exception:
            pass
        result.append(entry)
    return {"sessions": result}


# ---- WebSocket ----

@app.websocket("/live")
async def websocket_live(ws: WebSocket):
    """WebSocket endpoint for live agent progress streaming."""
    token = ws.query_params.get("token")
    if not token or not verify_jwt(token):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    _ws_clients.append(ws)

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "kill":
                    pass  # TODO: wire to stop_task
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ---- Health check (no auth) ----

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---- Serve frontend ----

_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/")
async def serve_frontend():
    """Serve the dashboard frontend."""
    from fastapi.responses import FileResponse
    index_path = os.path.join(_frontend_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"error": "Frontend not found"}
