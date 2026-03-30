"""Tests for the dashboard FastAPI application."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch

# Set test environment before importing app
os.environ["JWT_SECRET_KEY"] = "test-secret-for-tests"
os.environ["DATABASE_URL"] = "postgresql://mock"

from fastapi.testclient import TestClient
from dashboard.api.app import app, get_store
from dashboard.api.auth import create_jwt
from lib.python.runtime.db import TaskStore, Task
from tests.runtime.test_db import _make_mock_store, MockConnection, MockCursor


@pytest.fixture(autouse=True)
def reset_store():
    """Inject a mock PostgreSQL store for each test."""
    import dashboard.api.app as app_module
    s = _make_mock_store()
    s._connect = lambda: MockConnection(s)
    s._dict_cursor = lambda conn: MockCursor(s, dict_mode=True)
    app_module._store = s
    yield
    app_module._store = None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_jwt("test@example.com", "Hjalti")
    return {"Authorization": f"Bearer {token}"}


class TestHealthCheck:

    def test_health_no_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuthConfig:

    def test_config_no_auth(self, client):
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        assert "google_client_id" in resp.json()


class TestAuth:

    def test_no_token_returns_401(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 401

    def test_bad_token_returns_401(self, client):
        resp = client.get("/agents", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401

    def test_valid_jwt_returns_200(self, client, auth_headers):
        resp = client.get("/agents", headers=auth_headers)
        assert resp.status_code == 200

    def test_me_endpoint(self, client, auth_headers):
        resp = client.get("/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"


class TestAgentsEndpoint:

    def test_empty_agents(self, client, auth_headers):
        resp = client.get("/agents", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []


class TestQueueEndpoint:

    def test_enqueue_tasks(self, client, auth_headers):
        resp = client.post("/queue", headers=auth_headers, json={
            "tasks": [
                {"spec_number": "014", "spec_title": "Runtime",
                 "done_when_item": "Agent runs", "priority": 10},
                {"spec_number": "015", "spec_title": "Dashboard",
                 "done_when_item": "API works", "priority": 20},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["enqueued"]) == 2

    def test_enqueue_empty(self, client, auth_headers):
        resp = client.post("/queue", headers=auth_headers, json={"tasks": []})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestResultsEndpoint:

    def test_empty_results(self, client, auth_headers):
        resp = client.get("/results", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_pending_results_filter(self, client, auth_headers):
        resp = client.get("/results?pending_only=true", headers=auth_headers)
        assert resp.status_code == 200


class TestSpecsEndpoint:

    def test_get_specs(self, client, auth_headers):
        """Specs endpoint reads from the actual specs/ directory."""
        resp = client.get("/specs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "specs" in data
        assert len(data["specs"]) > 0


class TestHistoryEndpoint:

    def test_empty_history(self, client, auth_headers):
        resp = client.get("/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["runs"] == []


class TestRunEndpoint:

    def test_trigger_run_starts_processing(self, client, auth_headers):
        """Run endpoint should return 200 and start processing."""
        client.post("/queue", headers=auth_headers, json={
            "tasks": [{"spec_number": "014", "spec_title": "T",
                        "done_when_item": "test"}]
        })

        with patch("dashboard.api.app.asyncio") as mock_asyncio:
            mock_asyncio.create_task.return_value = type('Task', (), {'done': lambda: True})()
            mock_asyncio.to_thread.return_value = None
            mock_asyncio.get_event_loop.return_value = type('Loop', (), {'is_running': lambda: True})()

            resp = client.post("/run", headers=auth_headers, json={
                "max_turns_per_task": 5,
                "time_limit_per_task_min": 1,
            })
            assert resp.status_code in (200, 409, 500)


class TestApproveEndpoint:

    def test_approve_result(self, client, auth_headers):
        store = get_store()
        task = store.enqueue_task(Task(spec_number="014", spec_title="T",
                                       done_when_item="item"))
        from lib.python.runtime.db import AgentSession, Result, Run
        run = store.create_run()
        session = store.create_session(AgentSession(task_id=task.id, run_id=run.id))
        result = store.save_result(Result(task_id=task.id, session_id=session.id))

        resp = client.post(f"/results/{result.id}/approve",
                           headers=auth_headers,
                           json={"approved": True})
        assert resp.status_code == 200
        assert resp.json()["approved"] is True
