"""Tests for ship.deploy — deploy execution and ship.toml parsing."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lib.python.ship.deploy import (
    DeployTarget,
    DeployResult,
    slug_from_branch,
    load_targets,
    run_deploy,
    run_deploy_sequence,
    _DEFAULT_TIMEOUT,
)


class TestSlugFromBranch:
    def test_auto_prefix(self):
        assert slug_from_branch("auto/spec-003-task-12") == "spec-003-task-12"

    def test_feature_prefix(self):
        assert slug_from_branch("feature/my-thing") == "my-thing"

    def test_no_prefix(self):
        assert slug_from_branch("my-branch") == "my-branch"

    def test_sanitize_special_chars(self):
        assert slug_from_branch("auto/foo bar@baz") == "foo-bar-baz"

    def test_strip_dashes(self):
        result = slug_from_branch("auto/---test---")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestDeployTarget:
    def test_defaults(self):
        t = DeployTarget(name="test", command="echo hi")
        assert t.timeout == _DEFAULT_TIMEOUT
        assert t.role == "production"
        assert t.url_pattern == ""


class TestLoadTargets:
    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPLOY_COMMAND", "echo deploy")
        monkeypatch.setenv("DEPLOY_TIMEOUT", "60")
        targets = load_targets(str(tmp_path))
        assert len(targets) == 1
        assert targets[0].name == "default"
        assert targets[0].timeout == 60

    def test_no_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEPLOY_COMMAND", raising=False)
        targets = load_targets(str(tmp_path))
        assert targets == []

    def test_ship_toml(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEPLOY_COMMAND", raising=False)
        toml_content = b"""
[[targets]]
name = "Test URL"
command = "echo test"
url_pattern = "https://example.com/test/{slug}"
timeout = 30
role = "test"

[[targets]]
name = "Production"
command = "echo prod"
timeout = 60
role = "production"
"""
        (tmp_path / "ship.toml").write_bytes(toml_content)
        targets = load_targets(str(tmp_path))
        assert len(targets) == 2
        assert targets[0].name == "Test URL"
        assert targets[0].role == "test"
        assert targets[1].role == "production"


class TestRunDeploy:
    def test_success(self):
        target = DeployTarget(name="test", command="echo hello", timeout=10)
        result = run_deploy(target, branch="auto/test-branch")
        assert result.ok is True
        assert "hello" in result.output

    def test_with_url_pattern(self):
        target = DeployTarget(
            name="test", command="echo ok",
            url_pattern="https://example.com/{slug}",
            timeout=10,
        )
        result = run_deploy(target, branch="auto/my-feature")
        assert result.url == "https://example.com/my-feature"

    def test_failure(self):
        target = DeployTarget(name="test", command="exit 1", timeout=10)
        result = run_deploy(target)
        assert result.ok is False

    def test_timeout(self):
        target = DeployTarget(name="test", command="sleep 10", timeout=1)
        result = run_deploy(target)
        assert result.ok is False
        assert result.timed_out is True
        assert "timed out" in result.output.lower()


class TestRunDeploySequence:
    def test_stops_on_failure(self):
        targets = [
            DeployTarget(name="first", command="echo ok", timeout=5),
            DeployTarget(name="fail", command="exit 1", timeout=5),
            DeployTarget(name="skip", command="echo skip", timeout=5),
        ]
        results = run_deploy_sequence(targets)
        assert len(results) == 2
        assert results[0].ok is True
        assert results[1].ok is False

    def test_filter_names(self):
        targets = [
            DeployTarget(name="a", command="echo a", timeout=5),
            DeployTarget(name="b", command="echo b", timeout=5),
        ]
        results = run_deploy_sequence(targets, filter_names=["b"])
        assert len(results) == 1
        assert results[0].target == "b"
