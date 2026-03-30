"""
hth-platform project — Register, clone, and create projects for the multi-repo dashboard.

Subcommands:
    project add   --name X --path /local/path [--url git@... ] [--branch main]
    project clone --name X --url git@...      [--path /dir]   [--branch main]
    project new   --name X                    [--workspace /dir]
    project list
"""

from __future__ import annotations

import os
import sys

import click


def _get_store():
    """Return a ProjectStore using DATABASE_URL from environment."""
    from dotenv import load_dotenv
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        click.echo("Error: DATABASE_URL environment variable is not set.", err=True)
        click.echo("Run 'hth-platform env generate' to populate .env first.", err=True)
        raise SystemExit(1)

    # Add lib path
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from runtime.project_db import ProjectStore
    return ProjectStore(db_url)


@click.group()
def project():
    """Manage projects in the multi-repo dashboard."""


@project.command("list")
def project_list():
    """List all registered projects with sync status."""
    # Add lib path before import
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    ps = _get_store()
    from runtime.sync_status import compute_sync_status
    projects = ps.list_projects(active_only=True)

    if not projects:
        click.echo("No projects registered. Use 'hth-platform project add' to register one.")
        return

    click.echo(f"{'ID':<4} {'Icon':<4} {'Name':<25} {'Branch':<8} {'Path'}")
    click.echo("-" * 80)
    for p in projects:
        status = compute_sync_status(p.repo_path, p.remote_url)
        click.echo(f"{p.id:<4} {status.icon:<4} {p.name:<25} {p.base_branch:<8} {p.repo_path}")


@project.command("add")
@click.option("--name", required=True, help="Project display name")
@click.option("--path", "repo_path", required=True, help="Absolute path to the local git repo")
@click.option("--url", "remote_url", default=None, help="Remote URL (auto-detected if omitted)")
@click.option("--branch", default="main", help="Base branch (default: main)")
def project_add(name, repo_path, remote_url, branch):
    """Register an existing local git repository as a project."""
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    ps = _get_store()
    from runtime.project_db import Project
    from runtime.sync_status import compute_sync_status

    repo_path = os.path.abspath(repo_path)

    existing = ps.get_project_by_path(repo_path)
    if existing:
        click.echo(f"Error: Project at '{repo_path}' is already registered (id={existing.id}).", err=True)
        raise SystemExit(1)

    # Auto-detect remote if not provided
    if not remote_url:
        remote_url = ps.detect_remote_url(repo_path)
        if remote_url:
            click.echo(f"  Detected remote: {remote_url}")

    p = Project(name=name, repo_path=repo_path, remote_url=remote_url, base_branch=branch)
    created = ps.create_project(p)
    status = compute_sync_status(repo_path, remote_url)
    click.echo(f"  Registered project '{created.name}' (id={created.id}) {status.icon} {status.label}")


@project.command("clone")
@click.option("--name", required=True, help="Project display name")
@click.option("--url", "remote_url", required=True, help="Remote git URL to clone")
@click.option("--path", "local_path", default=None,
              help="Local path to clone into (default: ~/code/<name>)")
@click.option("--branch", default="main", help="Base branch (default: main)")
def project_clone(name, remote_url, local_path, branch):
    """Clone a remote git repository and register it as a project."""
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    ps = _get_store()
    from runtime.project_db import Project
    from runtime.sync_status import clone_project, compute_sync_status

    if not local_path:
        slug = name.lower().replace(" ", "-")
        local_path = os.path.join(os.path.expanduser("~/code"), slug)

    local_path = os.path.abspath(local_path)

    if os.path.exists(local_path):
        click.echo(f"Error: Path already exists: {local_path}", err=True)
        raise SystemExit(1)

    existing = ps.get_project_by_path(local_path)
    if existing:
        click.echo(f"Error: Project at '{local_path}' is already registered.", err=True)
        raise SystemExit(1)

    click.echo(f"  Cloning {remote_url} → {local_path} ...")
    success = clone_project(remote_url, local_path)
    if not success:
        click.echo("Error: git clone failed.", err=True)
        raise SystemExit(1)

    p = Project(name=name, repo_path=local_path, remote_url=remote_url, base_branch=branch)
    created = ps.create_project(p)
    status = compute_sync_status(local_path, remote_url)
    click.echo(f"  Registered project '{created.name}' (id={created.id}) {status.icon} {status.label}")


@project.command("new")
@click.option("--name", required=True, help="Project name (used as directory slug)")
@click.option("--workspace", default=None,
              help="Workspace directory (default: ~/code). Project created at <workspace>/<slug>")
def project_new(name, workspace):
    """Create a new git project with an empty vision spec and CLAUDE.md."""
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    ps = _get_store()
    from runtime.project_db import Project
    from runtime.sync_status import compute_sync_status

    workspace_dir = workspace or os.path.expanduser("~/code")
    slug = name.lower().replace(" ", "-").replace("_", "-")
    repo_path = os.path.join(workspace_dir, slug)

    if os.path.exists(repo_path):
        click.echo(f"Error: Directory already exists: {repo_path}", err=True)
        raise SystemExit(1)

    click.echo(f"  Creating project at {repo_path} ...")
    try:
        _scaffold_project(repo_path, name)
    except Exception as e:
        click.echo(f"Error: Scaffold failed: {e}", err=True)
        raise SystemExit(1)

    p = Project(name=name, repo_path=repo_path, base_branch="main")
    created = ps.create_project(p)
    status = compute_sync_status(repo_path, None)
    click.echo(f"  Created project '{created.name}' (id={created.id}) {status.icon} {status.label}")
    click.echo(f"\nNext: edit {repo_path}/specs/001-vision.md to write your vision.")


# ---- Scaffold ----

_VISION = """\
# 001: Vision

**Status:** draft

## Goal

<!-- What is this project? What problem does it solve? Write your vision here. -->

## Done When
- [ ] Vision is written and committed
"""

_CLAUDE_MD = """\
# {name} — Claude Code Project Context

## What This Is
<!-- Describe this project and its purpose. -->

## Development Commands
```bash
# Add your development commands here
```

## Key Invariants
<!-- Document the most important rules for this project. -->
"""


def _scaffold_project(repo_path: str, name: str) -> None:
    """Create directory structure, git init, vision spec, CLAUDE.md, initial commit."""
    import subprocess

    os.makedirs(repo_path)
    os.makedirs(os.path.join(repo_path, "specs"))

    with open(os.path.join(repo_path, "specs", "001-vision.md"), "w") as f:
        f.write(_VISION)

    with open(os.path.join(repo_path, "CLAUDE.md"), "w") as f:
        f.write(_CLAUDE_MD.format(name=name))

    def git(*args):
        subprocess.run(["git"] + list(args), cwd=repo_path,
                       capture_output=True, timeout=30)

    git("init")
    git("config", "user.email", "hth@local")
    git("config", "user.name", "HTH Platform")
    git("add", "-A")
    git("commit", "-m", "Initial commit: empty vision spec")
