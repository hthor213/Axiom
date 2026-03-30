"""Platform dependency detection.

Detects vault credentials, environment platform variables, infrastructure
dependencies, and provides recommendations for session platform readiness.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Credential boundary: only these action prefixes are allowed to touch credentials
_ALLOWED_CREDENTIAL_ACTIONS = frozenset({
    "read_credential",
    "check_credential",
    "list_credentials",
    "validate_credential",
    "refresh_credential",
})

# Actions that are explicitly forbidden from credential access
_DENIED_CREDENTIAL_ACTIONS = frozenset({
    "delete_credential",
    "export_credential",
    "copy_credential_external",
    "send_credential",
})

# Known environment variable prefixes that indicate platform configuration
_PLATFORM_ENV_PREFIXES = (
    "PLATFORM_",
    "HTH_",
    "HARNESS_",
    "SESSION_",
)

# Known environment variables that indicate credential sources
_CREDENTIAL_ENV_VARS = (
    "VAULT_ADDR",
    "VAULT_TOKEN",
    "VAULT_ROLE_ID",
    "VAULT_SECRET_ID",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_TENANT_ID",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "CI_TOKEN",
)

# Known infrastructure dependency file markers
_INFRA_MARKERS: dict[str, str] = {
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "Dockerfile": "docker",
    "terraform.tf": "terraform",
    "main.tf": "terraform",
    "pulumi.yaml": "pulumi",
    "Pulumi.yaml": "pulumi",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "helm": "helm",
    ".env": "dotenv",
    ".env.local": "dotenv",
    "vault.hcl": "vault",
    "ansible.cfg": "ansible",
    "playbook.yml": "ansible",
}


@dataclass
class PlatformReport:
    """Report on platform dependencies for a project root."""

    vault_exists: bool = False
    has_env_platform: bool = False
    has_env: dict[str, bool] = field(default_factory=dict)
    credential_sources: list[str] = field(default_factory=list)
    infrastructure_deps: list[str] = field(default_factory=list)
    recommendation: str = ""

    @property
    def credential_source(self) -> str:
        """Return the primary credential source for backward compatibility."""
        return self.credential_sources[0] if self.credential_sources else "none"

    def to_dict(self) -> dict:
        """Serialize the report to a plain dict."""
        return {
            "vault_exists": self.vault_exists,
            "has_env_platform": self.has_env_platform,
            "has_env": dict(self.has_env),
            "credential_sources": list(self.credential_sources),
            "credential_source": self.credential_source,
            "infrastructure_deps": list(self.infrastructure_deps),
            "recommendation": self.recommendation,
        }


@dataclass
class PlatformSyncReport:
    """Report on what needs synchronization after session changes."""

    new_credentials: list[str] = field(default_factory=list)
    new_infrastructure: list[str] = field(default_factory=list)
    reusable_patterns: list[str] = field(default_factory=list)
    needs_action: bool = False

    def to_dict(self) -> dict:
        """Serialize the sync report to a plain dict."""
        return {
            "new_credentials": list(self.new_credentials),
            "new_infrastructure": list(self.new_infrastructure),
            "reusable_patterns": list(self.reusable_patterns),
            "needs_action": self.needs_action,
        }


def _detect_vault(root: Path) -> bool:
    """Check whether a vault configuration exists in the project tree."""
    vault_indicators = [
        root / "vault.hcl",
        root / ".vault-token",
        root / "vault" / "config.hcl",
        root / ".vault",
    ]
    for indicator in vault_indicators:
        if indicator.exists():
            return True
    # Also check environment
    if os.environ.get("VAULT_ADDR") or os.environ.get("VAULT_TOKEN"):
        return True
    return False


def _detect_env_platform() -> bool:
    """Check whether any PLATFORM_* or HTH_* environment variables are set."""
    for key in os.environ:
        for prefix in _PLATFORM_ENV_PREFIXES:
            if key.startswith(prefix):
                return True
    return False


def _detect_credential_env() -> dict[str, bool]:
    """Check which known credential environment variables are set."""
    result: dict[str, bool] = {}
    for var in _CREDENTIAL_ENV_VARS:
        result[var] = var in os.environ and bool(os.environ[var])
    return result


def _determine_credential_sources(env_creds: dict[str, bool], vault_exists: bool) -> list[str]:
    """Determine all credential sources based on detected environment."""
    sources: list[str] = []
    if vault_exists:
        sources.append("vault")
    if env_creds.get("AWS_ACCESS_KEY_ID") or env_creds.get("AWS_SESSION_TOKEN"):
        sources.append("aws")
    if env_creds.get("GOOGLE_APPLICATION_CREDENTIALS"):
        sources.append("gcp")
    if env_creds.get("AZURE_CLIENT_ID"):
        sources.append("azure")
    if env_creds.get("GITHUB_TOKEN") or env_creds.get("GH_TOKEN"):
        sources.append("github")
    if env_creds.get("CI_TOKEN"):
        sources.append("ci")
    # If some credential vars are set but don't match known sources
    if not sources and any(env_creds.values()):
        sources.append("env")
    return sources


def _detect_infrastructure_deps(root: Path) -> list[str]:
    """Scan project root for infrastructure dependency markers."""
    found: set[str] = set()
    if not root.is_dir():
        return []
    try:
        entries = {entry.name for entry in root.iterdir()}
    except OSError:
        return []

    for marker, dep_name in _INFRA_MARKERS.items():
        if marker in entries:
            found.add(dep_name)

    # Also check for infra directories
    infra_dirs = ["infrastructure", "infra", "deploy", "terraform", "k8s", "helm"]
    for d in infra_dirs:
        dir_path = root / d
        if dir_path.is_dir():
            # Map directory names to dependency types
            dep_map = {
                "infrastructure": "infrastructure",
                "infra": "infrastructure",
                "deploy": "deployment",
                "terraform": "terraform",
                "k8s": "kubernetes",
                "helm": "helm",
            }
            found.add(dep_map.get(d, d))

    return sorted(found)


def _generate_recommendation(report: PlatformReport) -> str:
    """Generate a human-readable recommendation based on the platform report."""
    parts: list[str] = []

    if report.credential_source == "none":
        parts.append("No credential source detected. Set up vault or environment credentials if needed.")
    elif report.credential_source == "vault":
        parts.append("Vault detected. Ensure vault token is fresh before session work.")
    else:
        parts.append(f"Credentials sourced from {report.credential_source}.")

    if not report.has_env_platform:
        parts.append("No platform environment variables found. Consider setting PLATFORM_* or HTH_* vars.")

    if report.infrastructure_deps:
        dep_str = ", ".join(report.infrastructure_deps)
        parts.append(f"Infrastructure dependencies detected: {dep_str}. Verify services are running.")
    else:
        parts.append("No infrastructure dependencies detected.")

    return " ".join(parts)


def check_platform_deps(root: str) -> PlatformReport:
    """Check platform dependencies for a project root.

    Scans the project directory and environment for vault configuration,
    platform environment variables, credential sources, and infrastructure
    dependency markers.

    Args:
        root: Path to the project root directory.

    Returns:
        A PlatformReport with detected platform dependencies.
    """
    root_path = Path(root)
    report = PlatformReport()

    report.vault_exists = _detect_vault(root_path)
    report.has_env_platform = _detect_env_platform()
    report.has_env = _detect_credential_env()
    report.infrastructure_deps = _detect_infrastructure_deps(root_path)
    report.credential_sources = _determine_credential_sources(
        report.has_env, report.vault_exists
    )
    report.recommendation = _generate_recommendation(report)

    return report


def check_sync_needs(session_changes: dict) -> PlatformSyncReport:
    """Check what platform synchronization is needed after session changes.

    Analyzes a dict of session changes to determine if new credentials,
    infrastructure, or reusable patterns have been introduced.

    Args:
        session_changes: Dict describing changes made during a session.
            Expected keys (all optional):
                - files_added: list[str] — paths of new files
                - files_modified: list[str] — paths of modified files
                - env_added: list[str] — new environment variable names
                - services_added: list[str] — new service/infra names
                - patterns_used: list[str] — pattern identifiers reused

    Returns:
        A PlatformSyncReport describing what needs attention.
    """
    report = PlatformSyncReport()

    files_added: list[str] = session_changes.get("files_added") or []
    files_modified: list[str] = session_changes.get("files_modified") or []
    env_added: list[str] = session_changes.get("env_added") or []
    services_added: list[str] = session_changes.get("services_added") or []
    patterns_used: list[str] = session_changes.get("patterns_used") or []

    # Detect new credentials from added environment variables
    all_files = files_added + files_modified
    for env_var in env_added:
        # Check if it looks like a credential variable
        cred_keywords = ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL", "AUTH")
        upper_var = env_var.upper()
        if any(kw in upper_var for kw in cred_keywords):
            report.new_credentials.append(env_var)

    # Detect credential files in added files
    cred_file_patterns = (
        ".env", ".secret", "credentials", "token", ".vault-token",
        "service-account", ".pem", ".key",
    )
    for fpath in files_added:
        fpath_lower = fpath.lower()
        if any(pat in fpath_lower for pat in cred_file_patterns):
            report.new_credentials.append(fpath)

    # Detect new infrastructure from added files
    for fpath in all_files:
        fname = Path(fpath).name
        if fname in _INFRA_MARKERS:
            dep = _INFRA_MARKERS[fname]
            if dep not in report.new_infrastructure:
                report.new_infrastructure.append(dep)

    # Detect infrastructure from path patterns
    infra_path_patterns = re.compile(
        r"(terraform|kubernetes|k8s|helm|docker|ansible|pulumi|deploy|infra)",
        re.IGNORECASE,
    )
    for fpath in all_files:
        m = infra_path_patterns.search(fpath)
        if m:
            dep_name = m.group(1).lower()
            if dep_name not in report.new_infrastructure:
                report.new_infrastructure.append(dep_name)

    # Add explicitly declared services
    for svc in services_added:
        if svc not in report.new_infrastructure:
            report.new_infrastructure.append(svc)

    # Record reusable patterns
    report.reusable_patterns = list(patterns_used)

    # Determine if action is needed
    report.needs_action = bool(
        report.new_credentials
        or report.new_infrastructure
    )

    return report


def validate_credential_access(action: str) -> bool:
    """Enforce credential boundary by validating an action string.

    Only actions whose prefix matches the allowed credential action set
    are permitted. Explicitly denied actions always return False.
    The suffix (after the colon) must be a simple alphanumeric identifier.

    Args:
        action: The action identifier to validate, e.g. 'read_credential:db_password'.

    Returns:
        True if the action is allowed to access credentials, False otherwise.
    """
    if not action or not isinstance(action, str):
        return False

    action_stripped = action.strip()
    if not action_stripped:
        return False

    # Strict format: action_base or action_base:identifier
    # No spaces, no multiple colons, no embedded actions
    pattern = re.compile(r'^([a-z_]+)(?::([a-zA-Z0-9_-]+))?$')
    m = pattern.match(action_stripped)
    if not m:
        return False

    action_base = m.group(1)

    # Check explicit denials first
    if action_base in _DENIED_CREDENTIAL_ACTIONS:
        return False

    # Check allowed actions
    if action_base in _ALLOWED_CREDENTIAL_ACTIONS:
        return True

    # Default deny — credential boundary enforcement
    return False
