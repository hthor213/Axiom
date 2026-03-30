"""PostgreSQL schema for the autonomous runtime.

Tables: tasks, runs, agent_sessions, results.
Uses raw SQL — no ORM dependency. Applied via psycopg2 or any PostgreSQL client.
"""

from __future__ import annotations

SCHEMA_VERSION = 5

SCHEMA_SQL = """
-- Autonomous runtime schema v1
-- Applied to: orchestrator_dev database on MacStudio (:5433)

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    spec_number     VARCHAR(10) NOT NULL,       -- e.g. "014"
    spec_title      VARCHAR(255) NOT NULL,
    done_when_item  TEXT NOT NULL,               -- specific Done When line
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
                    -- queued | running | passed | failed | rejected
    priority        INTEGER NOT NULL DEFAULT 100,
    branch_name     VARCHAR(255),               -- git branch for this task
    worktree_path   VARCHAR(512),               -- absolute path to worktree
    base_commit     VARCHAR(40),                -- SHA of the branch base for accurate diffs
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    queued_by       VARCHAR(50) DEFAULT 'dashboard',  -- dashboard | n8n | manual
    user_instructions TEXT DEFAULT ''           -- free-text guidance from human
);

CREATE TABLE IF NOT EXISTS runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished_at     TIMESTAMP WITH TIME ZONE,
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
                    -- running | completed | stopped | failed
    stop_reason     TEXT,
    tasks_completed INTEGER DEFAULT 0,
    tasks_failed    INTEGER DEFAULT 0,
    total_turns     INTEGER DEFAULT 0,
    total_api_calls INTEGER DEFAULT 0,
    config          JSONB DEFAULT '{}'::jsonb     -- max_turns, time_limit, etc.
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id),
    run_id          INTEGER REFERENCES runs(id),
    started_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished_at     TIMESTAMP WITH TIME ZONE,
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
                    -- running | completed | failed | killed
    turns_used      INTEGER DEFAULT 0,
    max_turns       INTEGER DEFAULT 30,
    time_limit_min  INTEGER DEFAULT 60,
    failure_count   INTEGER DEFAULT 0,
    max_failures    INTEGER DEFAULT 3,
    last_tool_call  TEXT,                        -- last tool the agent called
    last_output     TEXT,                        -- truncated last output
    error           TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id),
    session_id      INTEGER REFERENCES agent_sessions(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    branch_name     VARCHAR(255),
    commit_sha      VARCHAR(40),
    diff_summary    TEXT,                        -- abbreviated git diff
    test_passed     INTEGER DEFAULT 0,
    test_failed     INTEGER DEFAULT 0,
    test_output     TEXT,                        -- captured pytest output for triage
    adversarial_verdict VARCHAR(10),            -- PASS | FAIL | SKIP
    adversarial_report  JSONB,
    harness_check   JSONB,                      -- output of hth-platform harness check
    approved        BOOLEAN,                    -- NULL = pending, TRUE = approved, FALSE = rejected
    approved_at     TIMESTAMP WITH TIME ZONE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_spec ON tasks(spec_number);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_sessions_run ON agent_sessions(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON agent_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_results_task ON results(task_id);
CREATE INDEX IF NOT EXISTS idx_results_approved ON results(approved);

-- Prevent duplicate active tasks for the same spec+item
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_active_dedup
ON tasks (spec_number, done_when_item)
WHERE status IN ('queued', 'running', 'waiting_for_human');

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
INSERT INTO schema_version (version)
VALUES (1)
ON CONFLICT (version) DO NOTHING;
"""

# ---- Migration v2: pipeline_stage + stopped status + stop_reason on tasks ----

MIGRATION_V2_SQL = """
-- Add pipeline_stage column to tasks (tracks position in build pipeline)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pipeline_stage VARCHAR(30);
-- Stages: agent_building | tests_running | triage_fixing | adversarial_review | complete

-- Add stop_reason column to tasks (why a task was stopped)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS stop_reason TEXT;

-- Update dedup index to include 'stopped' status (stopped tasks block re-queue)
DROP INDEX IF EXISTS idx_tasks_active_dedup;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_active_dedup
ON tasks (spec_number, done_when_item)
WHERE status IN ('queued', 'running', 'waiting_for_human', 'stopped');

-- Schema version
INSERT INTO schema_version (version)
VALUES (2)
ON CONFLICT (version) DO NOTHING;
"""


MIGRATION_V3_SQL = """
-- Spec reviews: interactive GPT-mentor + Claude-editor review loop
CREATE TABLE IF NOT EXISTS spec_reviews (
    id              SERIAL PRIMARY KEY,
    spec_number     VARCHAR(10) NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    original_content TEXT NOT NULL,
    user_modifications TEXT,
    gpt_feedback    TEXT,
    edited_content  TEXT,
    human_comments  TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- pending | approved | rejected
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spec_reviews_spec ON spec_reviews(spec_number);
CREATE INDEX IF NOT EXISTS idx_spec_reviews_status ON spec_reviews(status);

INSERT INTO schema_version (version)
VALUES (3)
ON CONFLICT (version) DO NOTHING;
"""


MIGRATION_V4_SQL = """
-- Multi-repo support: projects table + project_id FK on tasks/runs/results

CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    repo_path   TEXT NOT NULL UNIQUE,
    remote_url  TEXT,
    base_branch TEXT DEFAULT 'main',
    active      BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE tasks   ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id);
ALTER TABLE runs    ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id);
ALTER TABLE results ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS idx_tasks_project   ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_project    ON runs(project_id);
CREATE INDEX IF NOT EXISTS idx_results_project ON results(project_id);

INSERT INTO schema_version (version) VALUES (4) ON CONFLICT (version) DO NOTHING;
"""


MIGRATION_V5_SQL = """
-- Plan-then-execute: store build plans and mentor feedback
CREATE TABLE IF NOT EXISTS task_plans (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id) NOT NULL,
    plan_text       TEXT NOT NULL,
    mentor_feedback TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'accepted',
                    -- pending | accepted | rejected
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    project_id      INTEGER REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS idx_task_plans_task ON task_plans(task_id);

INSERT INTO schema_version (version) VALUES (5) ON CONFLICT (version) DO NOTHING;
"""


def get_migration_v5_sql() -> str:
    """Return the v5 migration SQL."""
    return MIGRATION_V5_SQL


def get_migration_v4_sql() -> str:
    """Return the v4 migration SQL."""
    return MIGRATION_V4_SQL


def get_migration_v3_sql() -> str:
    """Return the v3 migration SQL."""
    return MIGRATION_V3_SQL


def get_migration_v2_sql() -> str:
    """Return the v2 migration SQL."""
    return MIGRATION_V2_SQL


def get_schema_sql() -> str:
    """Return the full schema SQL for applying to PostgreSQL."""
    return SCHEMA_SQL


def apply_schema(connection_string: str) -> bool:
    """Apply the schema to a PostgreSQL database.

    Args:
        connection_string: PostgreSQL connection string.

    Returns:
        True if schema was applied successfully.
    """
    try:
        import psycopg2
    except ImportError:
        raise ImportError("psycopg2 required. Install with: pip install psycopg2-binary")

    try:
        conn = psycopg2.connect(connection_string)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute(MIGRATION_V2_SQL)
            cur.execute(MIGRATION_V3_SQL)
            cur.execute(MIGRATION_V4_SQL)
            cur.execute(MIGRATION_V5_SQL)
        conn.close()
        return True
    except Exception as e:
        print(f"Schema apply failed: {e}")
        return False
