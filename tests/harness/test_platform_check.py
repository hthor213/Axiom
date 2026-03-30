"""Tests for lib/python/harness/platform_check.py"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.python.harness.platform_check import (
    PlatformReport,
    PlatformSyncReport,
    _detect_credential_env,
    _detect_env_platform,
    _detect_infrastructure_deps,
    _detect_vault,
    _determine_credential_sources,
    _generate_recommendation,
    check_platform_deps,
    check_sync_needs,
    validate_credential_access,
)


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestPlatformReport:
    def test_defaults(self) -> None:
        r = PlatformReport()
        assert r.vault_exists is False
        assert r.has_env_platform is False
        assert r.has_env == {}
        assert r.credential_source == "none"
        assert r.credential_sources == []
        assert r.infrastructure_deps == []
        assert r.recommendation == ""

    def test_to_dict_roundtrip(self) -> None:
        r = PlatformReport(vault_exists=True, credential_sources=["vault"],
                           infrastructure_deps=["docker"])
        d = r.to_dict()
        assert d["vault_exists"] is True
        assert d["credential_source"] == "vault"
        assert d["credential_sources"] == ["vault"]
        assert d["infrastructure_deps"] == ["docker"]


class TestPlatformSyncReport:
    def test_defaults(self) -> None:
        r = PlatformSyncReport()
        assert r.needs_action is False
        assert r.new_credentials == []

    def test_to_dict(self) -> None:
        r = PlatformSyncReport(new_credentials=["X"], needs_action=True)
        d = r.to_dict()
        assert d["new_credentials"] == ["X"]
        assert d["needs_action"] is True


# ---------------------------------------------------------------------------
# _detect_vault
# ---------------------------------------------------------------------------

class TestDetectVault:
    def test_vault_hcl_file(self, tmp_path: Path) -> None:
        (tmp_path / "vault.hcl").write_text("storage {}")
        assert _detect_vault(tmp_path) is True

    def test_vault_token_file(self, tmp_path: Path) -> None:
        (tmp_path / ".vault-token").write_text("s.abc")
        assert _detect_vault(tmp_path) is True

    def test_vault_config_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "vault"
        d.mkdir()
        (d / "config.hcl").write_text("")
        assert _detect_vault(tmp_path) is True

    def test_no_vault(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        assert _detect_vault(tmp_path) is False

    def test_vault_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", "https://vault.example.com")
        assert _detect_vault(tmp_path) is True


# ---------------------------------------------------------------------------
# _detect_env_platform / _detect_credential_env
# ---------------------------------------------------------------------------

class TestDetectEnv:
    def test_platform_env_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HTH_MODE", "dev")
        assert _detect_env_platform() is True

    def test_no_platform_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Remove all matching prefixes
        for key in list(os.environ):
            if key.startswith(("PLATFORM_", "HTH_", "HARNESS_", "SESSION_")):
                monkeypatch.delenv(key, raising=False)
        assert _detect_env_platform() is False

    def test_credential_env_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
        result = _detect_credential_env()
        assert result["AWS_ACCESS_KEY_ID"] is True

    def test_credential_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = _detect_credential_env()
        assert result["GITHUB_TOKEN"] is False


# ---------------------------------------------------------------------------
# _determine_credential_source
# ---------------------------------------------------------------------------

class TestDetermineCredentialSources:
    def test_vault_takes_priority(self) -> None:
        sources = _determine_credential_sources({"AWS_ACCESS_KEY_ID": True}, vault_exists=True)
        assert sources[0] == "vault"
        assert "aws" in sources

    def test_aws(self) -> None:
        assert _determine_credential_sources({"AWS_ACCESS_KEY_ID": True}, vault_exists=False) == ["aws"]

    def test_gcp(self) -> None:
        assert _determine_credential_sources({"GOOGLE_APPLICATION_CREDENTIALS": True}, False) == ["gcp"]

    def test_azure(self) -> None:
        assert _determine_credential_sources({"AZURE_CLIENT_ID": True}, False) == ["azure"]

    def test_github(self) -> None:
        assert _determine_credential_sources({"GH_TOKEN": True}, False) == ["github"]

    def test_ci(self) -> None:
        assert _determine_credential_sources({"CI_TOKEN": True}, False) == ["ci"]

    def test_generic_env(self) -> None:
        # Some credential set but not matching a known cloud
        assert _determine_credential_sources({"VAULT_TOKEN": True}, False) == ["env"]

    def test_none(self) -> None:
        assert _determine_credential_sources({}, False) == []


# ---------------------------------------------------------------------------
# _detect_infrastructure_deps
# ---------------------------------------------------------------------------

class TestDetectInfraDeps:
    def test_docker_compose(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("")
        deps = _detect_infrastructure_deps(tmp_path)
        assert "docker-compose" in deps

    def test_terraform_dir(self, tmp_path: Path) -> None:
        (tmp_path / "terraform").mkdir()
        deps = _detect_infrastructure_deps(tmp_path)
        assert "terraform" in deps

    def test_multiple_markers(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("")
        (tmp_path / ".env").write_text("")
        (tmp_path / "helm").mkdir()
        deps = _detect_infrastructure_deps(tmp_path)
        assert "docker" in deps
        assert "dotenv" in deps
        assert "helm" in deps

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert _detect_infrastructure_deps(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert _detect_infrastructure_deps(tmp_path / "nope") == []

    def test_infra_directory(self, tmp_path: Path) -> None:
        (tmp_path / "infra").mkdir()
        deps = _detect_infrastructure_deps(tmp_path)
        assert "infrastructure" in deps

    def test_deploy_directory(self, tmp_path: Path) -> None:
        (tmp_path / "deploy").mkdir()
        deps = _detect_infrastructure_deps(tmp_path)
        assert "deployment" in deps


# ---------------------------------------------------------------------------
# _generate_recommendation
# ---------------------------------------------------------------------------

class TestGenerateRecommendation:
    def test_no_creds(self) -> None:
        r = PlatformReport(credential_sources=[])
        rec = _generate_recommendation(r)
        assert "No credential source" in rec

    def test_vault_creds(self) -> None:
        r = PlatformReport(credential_sources=["vault"], has_env_platform=True)
        rec = _generate_recommendation(r)
        assert "Vault detected" in rec

    def test_infra_deps_mentioned(self) -> None:
        r = PlatformReport(credential_sources=[], has_env_platform=True,
                           infrastructure_deps=["docker", "terraform"])
        rec = _generate_recommendation(r)
        assert "docker" in rec
        assert "terraform" in rec
        assert "Verify services" in rec

    def test_no_platform_env_warning(self) -> None:
        r = PlatformReport(credential_sources=["aws"], has_env_platform=False)
        rec = _generate_recommendation(r)
        assert "PLATFORM_" in rec or "HTH_" in rec


# ---------------------------------------------------------------------------
# check_platform_deps (integration)
# ---------------------------------------------------------------------------

class TestCheckPlatformDeps:
    def test_with_tmp_project(self, tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        report = check_platform_deps(str(tmp_project))
        assert isinstance(report, PlatformReport)
        assert report.recommendation  # non-empty

    def test_empty_project(self, tmp_project_empty: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        report = check_platform_deps(str(tmp_project_empty))
        assert report.vault_exists is False
        assert report.credential_source in ("none", "env", "aws", "gcp", "azure",
                                              "github", "ci")

    def test_with_vault_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        (tmp_path / "vault.hcl").write_text("")
        report = check_platform_deps(str(tmp_path))
        assert report.vault_exists is True
        assert report.credential_source == "vault"


# ---------------------------------------------------------------------------
# check_sync_needs
# ---------------------------------------------------------------------------

class TestCheckSyncNeeds:
    def test_empty_changes(self) -> None:
        r = check_sync_needs({})
        assert r.needs_action is False
        assert r.new_credentials == []

    def test_credential_env_added(self) -> None:
        r = check_sync_needs({"env_added": ["DB_PASSWORD", "APP_NAME"]})
        assert "DB_PASSWORD" in r.new_credentials
        assert "APP_NAME" not in r.new_credentials
        assert r.needs_action is True

    def test_credential_file_added(self) -> None:
        r = check_sync_needs({"files_added": ["config/.env.local", "src/main.py"]})
        assert any(".env" in c for c in r.new_credentials)
        assert r.needs_action is True

    def test_infra_file_added(self) -> None:
        r = check_sync_needs({"files_added": ["Dockerfile"]})
        assert "docker" in r.new_infrastructure
        assert r.needs_action is True

    def test_infra_path_pattern(self) -> None:
        r = check_sync_needs({"files_added": ["deploy/kubernetes/app.yaml"]})
        # Should detect from path pattern
        assert any(dep in r.new_infrastructure for dep in ("deploy", "kubernetes"))

    def test_services_added(self) -> None:
        r = check_sync_needs({"services_added": ["redis", "postgres"]})
        assert "redis" in r.new_infrastructure
        assert "postgres" in r.new_infrastructure
        assert r.needs_action is True

    def test_patterns_used_recorded(self) -> None:
        r = check_sync_needs({"patterns_used": ["retry-backoff", "circuit-breaker"]})
        assert r.reusable_patterns == ["retry-backoff", "circuit-breaker"]
        # Patterns alone don't require action
        assert r.needs_action is False

    def test_modified_infra_file(self) -> None:
        r = check_sync_needs({"files_modified": ["main.tf"]})
        assert "terraform" in r.new_infrastructure

    def test_credential_keywords(self) -> None:
        """All credential keywords should be detected."""
        env_vars = ["MY_TOKEN", "APP_SECRET", "API_KEY", "USER_PASSWORD",
                     "GCP_CREDENTIAL", "AUTH_HEADER"]
        r = check_sync_needs({"env_added": env_vars})
        assert len(r.new_credentials) == len(env_vars)


# ---------------------------------------------------------------------------
# validate_credential_access
# ---------------------------------------------------------------------------

class TestValidateCredentialAccess:
    @pytest.mark.parametrize("action", [
        "read_credential",
        "read_credential:db_password",
        "check_credential",
        "list_credentials",
        "validate_credential",
        "refresh_credential",
    ])
    def test_allowed_actions(self, action: str) -> None:
        assert validate_credential_access(action) is True

    @pytest.mark.parametrize("action", [
        "delete_credential",
        "export_credential",
        "copy_credential_external",
        "send_credential",
        "delete_credential:db_password",
    ])
    def test_denied_actions(self, action: str) -> None:
        assert validate_credential_access(action) is False

    @pytest.mark.parametrize("action", [
        "unknown_action",
        "write_credential",
        "modify_credential",
        "credential_read",  # wrong order
    ])
    def test_default_deny(self, action: str) -> None:
        assert validate_credential_access(action) is False

    @pytest.mark.parametrize("action", [
        "",
        "   ",
        None,
        42,
    ])
    def test_invalid_input(self, action) -> None:
        assert validate_credential_access(action) is False

    def test_whitespace_stripped(self) -> None:
        assert validate_credential_access("  read_credential  ") is True

    def test_colon_delimiter(self) -> None:
        assert validate_credential_access("read_credential:db_password") is True

    def test_colon_with_slashes_rejected(self) -> None:
        assert validate_credential_access("read_credential:vault/secret/db") is False

    def test_space_delimiter_rejected(self) -> None:
        assert validate_credential_access("check_credential some_arg") is False
