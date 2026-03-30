"""Deploy command execution with timeout and ship.toml parsing.

Reads deploy configuration from DEPLOY_COMMAND env var or ship.toml.
Each target has a timeout (default 120s) and is killed on timeout.
"""

from __future__ import annotations

import os
import re
import subprocess
import signal
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


_DEFAULT_TIMEOUT = 120


@dataclass
class DeployTarget:
    """A single deploy target from ship.toml or env."""

    name: str
    command: str
    url_pattern: str = ""
    timeout: int = _DEFAULT_TIMEOUT
    role: str = "production"  # test | production | smoke


@dataclass
class DeployResult:
    """Result of executing a deploy target."""

    target: str
    ok: bool
    output: str = ""
    url: str = ""
    timed_out: bool = False


def slug_from_branch(branch: str) -> str:
    """Derive a URL slug from a branch name.

    Example: 'auto/spec-003-task-12' -> 'spec-003-task-12'
    """
    # Strip common prefixes
    for prefix in ("auto/", "feature/", "fix/", "refs/heads/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix):]
            break
    # Sanitize for URL usage
    return re.sub(r"[^a-zA-Z0-9._-]", "-", branch).strip("-")


def load_targets(root: str) -> List[DeployTarget]:
    """Load deploy targets from ship.toml or DEPLOY_COMMAND env.

    Priority: ship.toml > DEPLOY_COMMAND env var.
    """
    toml_path = os.path.join(root, "ship.toml")
    if os.path.isfile(toml_path) and tomllib is not None:
        targets = _parse_ship_toml(toml_path)
        if targets:
            return targets

    # Fall back to env var
    cmd = os.environ.get("DEPLOY_COMMAND", "")
    if cmd:
        timeout = int(os.environ.get("DEPLOY_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        return [DeployTarget(name="default", command=cmd, timeout=timeout)]

    return []


def _parse_ship_toml(path: str) -> List[DeployTarget]:
    """Parse ship.toml for deploy targets."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError, KeyError):
        return []

    targets = []
    for t in data.get("targets", []):
        targets.append(DeployTarget(
            name=t.get("name", "unnamed"),
            command=t.get("command", ""),
            url_pattern=t.get("url_pattern", ""),
            timeout=t.get("timeout", _DEFAULT_TIMEOUT),
            role=t.get("role", "production"),
        ))
    return targets


def run_deploy(
    target: DeployTarget,
    branch: str = "",
) -> DeployResult:
    """Execute a deploy target command with timeout.

    Returns DeployResult. On timeout, the process is killed.
    """
    slug = slug_from_branch(branch) if branch else ""
    url = target.url_pattern.replace("{slug}", slug) if target.url_pattern else ""

    try:
        proc = subprocess.Popen(
            target.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=target.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return DeployResult(
                target=target.name,
                ok=False,
                output=f"Deploy timed out after {target.timeout}s",
                url=url,
                timed_out=True,
            )

        return DeployResult(
            target=target.name,
            ok=proc.returncode == 0,
            output=stdout.strip() if stdout else "",
            url=url,
        )

    except (OSError, FileNotFoundError) as e:
        return DeployResult(
            target=target.name,
            ok=False,
            output=str(e),
        )


def run_deploy_sequence(
    targets: List[DeployTarget],
    branch: str = "",
    filter_names: Optional[List[str]] = None,
) -> List[DeployResult]:
    """Run deploy targets in order. Stop on first failure."""
    results = []
    for target in targets:
        if filter_names and target.name not in filter_names:
            continue
        result = run_deploy(target, branch)
        results.append(result)
        if not result.ok:
            break
    return results
