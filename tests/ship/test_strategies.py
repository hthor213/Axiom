"""Tests for ship.strategies — PR and merge logic."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lib.python.ship.strategies import (
    StrategyResult,
    detect_base_branch,
    fetch_and_merge_base,
    push_branch,
    create_pr,
    direct_merge,
    _run,
)


def _make_result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


class TestDetectBaseBranch:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHIP_BASE_BRANCH", "develop")
        assert detect_base_branch("/tmp") == "develop"

    @patch("lib.python.ship.strategies._run")
    def test_main_found(self, mock_run, monkeypatch):
        monkeypatch.delenv("SHIP_BASE_BRANCH", raising=False)
        mock_run.return_value = _make_result(returncode=0)
        assert detect_base_branch("/tmp") == "main"

    @patch("lib.python.ship.strategies._run")
    def test_master_fallback(self, mock_run, monkeypatch):
        monkeypatch.delenv("SHIP_BASE_BRANCH", raising=False)
        def side_effect(args, cwd, timeout=30):
            if "main" in args:
                return _make_result(returncode=1)
            return _make_result(returncode=0)
        mock_run.side_effect = side_effect
        assert detect_base_branch("/tmp") == "master"

    @patch("lib.python.ship.strategies._run")
    def test_none_found(self, mock_run, monkeypatch):
        monkeypatch.delenv("SHIP_BASE_BRANCH", raising=False)
        mock_run.return_value = _make_result(returncode=1)
        assert detect_base_branch("/tmp") == ""


class TestFetchAndMergeBase:
    @patch("lib.python.ship.strategies._run")
    def test_success(self, mock_run):
        mock_run.return_value = _make_result(returncode=0)
        r = fetch_and_merge_base("/tmp", "main")
        assert r.ok is True

    @patch("lib.python.ship.strategies._run")
    def test_fetch_fails(self, mock_run):
        mock_run.return_value = _make_result(returncode=1, stderr="network error")
        r = fetch_and_merge_base("/tmp", "main")
        assert r.ok is False
        assert "Fetch failed" in r.detail

    @patch("lib.python.ship.strategies._run")
    def test_merge_conflict(self, mock_run):
        calls = []
        def side_effect(args, cwd, timeout=30):
            calls.append(args)
            if "merge" in args and "--abort" not in args and "fetch" not in args[0:2]:
                return _make_result(returncode=1, stderr="CONFLICT")
            return _make_result(returncode=0)
        mock_run.side_effect = side_effect
        r = fetch_and_merge_base("/tmp", "main")
        assert r.ok is False
        assert "Merge conflicts" in r.detail
        # Should have called merge --abort
        abort_calls = [c for c in calls if "--abort" in c]
        assert len(abort_calls) == 1


class TestPushBranch:
    @patch("lib.python.ship.strategies._run")
    def test_success(self, mock_run):
        mock_run.return_value = _make_result(returncode=0)
        r = push_branch("/tmp", "feature")
        assert r.ok is True

    @patch("lib.python.ship.strategies._run")
    def test_rejected(self, mock_run):
        mock_run.return_value = _make_result(
            returncode=1, stderr="rejected non-fast-forward",
        )
        r = push_branch("/tmp", "feature")
        assert r.ok is False
        assert "rejected" in r.detail.lower()

    @patch("lib.python.ship.strategies._run")
    def test_network_error(self, mock_run):
        mock_run.return_value = _make_result(
            returncode=1, stderr="Could not resolve host",
        )
        r = push_branch("/tmp", "feature")
        assert r.ok is False
        assert "unreachable" in r.detail.lower()


class TestCreatePR:
    @patch("lib.python.ship.strategies._run")
    def test_creates_new_pr(self, mock_run):
        def side_effect(args, cwd, timeout=30):
            if "view" in args:
                return _make_result(returncode=1)
            return _make_result(returncode=0, stdout="https://github.com/pr/1\n")
        mock_run.side_effect = side_effect
        r = create_pr("/tmp", "main", "feat: something")
        assert r.ok is True
        assert r.pr_url == "https://github.com/pr/1"

    @patch("lib.python.ship.strategies._run")
    def test_existing_pr(self, mock_run):
        mock_run.return_value = _make_result(
            returncode=0, stdout="https://github.com/pr/99\n",
        )
        r = create_pr("/tmp", "main", "feat: something")
        assert r.ok is True
        assert "already exists" in r.detail

    @patch("lib.python.ship.strategies._run")
    def test_gh_fails(self, mock_run):
        def side_effect(args, cwd, timeout=30):
            if "view" in args:
                return _make_result(returncode=1)
            return _make_result(returncode=1, stderr="auth error")
        mock_run.side_effect = side_effect
        r = create_pr("/tmp", "main", "feat: test")
        assert r.ok is False


class TestDirectMerge:
    @patch("lib.python.ship.strategies._run")
    def test_success(self, mock_run):
        def side_effect(args, cwd, timeout=30):
            if "rev-parse" in args:
                return _make_result(stdout="abc123def456\n")
            return _make_result(returncode=0)
        mock_run.side_effect = side_effect
        r = direct_merge("/tmp", "main", "feature")
        assert r.ok is True
        assert r.merge_sha == "abc123def456"
        assert "Rollback" in r.detail

    @patch("lib.python.ship.strategies._run")
    def test_ff_fails(self, mock_run):
        def side_effect(args, cwd, timeout=30):
            if "--ff-only" in args:
                return _make_result(returncode=1, stderr="not ff")
            return _make_result(returncode=0)
        mock_run.side_effect = side_effect
        r = direct_merge("/tmp", "main", "feature")
        assert r.ok is False
        assert "fast-forward" in r.detail.lower()


class TestStrategyResult:
    def test_defaults(self):
        r = StrategyResult(ok=True)
        assert r.detail == ""
        assert r.pr_url == ""
        assert r.merge_sha == ""
