"""Tests for the PostgreSQL schema module."""

from __future__ import annotations

import pytest

from lib.python.runtime.schema import get_schema_sql, SCHEMA_VERSION


def test_schema_sql_not_empty():
    sql = get_schema_sql()
    assert len(sql) > 100


def test_schema_creates_required_tables():
    sql = get_schema_sql()
    assert "CREATE TABLE IF NOT EXISTS tasks" in sql
    assert "CREATE TABLE IF NOT EXISTS runs" in sql
    assert "CREATE TABLE IF NOT EXISTS agent_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS results" in sql
    assert "CREATE TABLE IF NOT EXISTS schema_version" in sql


def test_schema_has_required_columns():
    sql = get_schema_sql()
    # Tasks
    assert "spec_number" in sql
    assert "done_when_item" in sql
    assert "worktree_path" in sql
    # Agent sessions
    assert "max_turns" in sql
    assert "time_limit_min" in sql
    assert "failure_count" in sql
    assert "max_failures" in sql
    # Results
    assert "adversarial_verdict" in sql
    assert "harness_check" in sql
    assert "approved" in sql


def test_schema_has_indexes():
    sql = get_schema_sql()
    assert "idx_tasks_status" in sql
    assert "idx_results_approved" in sql


def test_schema_version():
    assert SCHEMA_VERSION == 5
