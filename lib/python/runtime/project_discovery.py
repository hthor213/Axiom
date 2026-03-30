"""Auto-discover projects from GitHub and local directories.

On dashboard startup, merges three sources into the projects table:
  1. GitHub repos (all, public + private) — requires GITHUB_TOKEN
  2. Local git repos in workspace directories
  3. Already-registered projects (preserved as-is)

New repos are registered as cloud-only (☁) or local-only (💾).
Existing rows are never overwritten — only new repos are added.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

import urllib.request
import json


def _github_user(token: str) -> Optional[str]:
    """Get the authenticated user's login for this token."""
    req = urllib.request.Request("https://api.github.com/user", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("login")
    except Exception:
        return None


def discover_github_repos(token: str) -> list[dict]:
    """Fetch all repos (public + private) owned by the authenticated user."""
    owner = _github_user(token)
    if not owner:
        print("[discovery] GitHub: could not determine authenticated user")
        return []

    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/user/repos?per_page=100&page={page}&affiliation=owner"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                batch = json.loads(resp.read())
        except Exception as e:
            print(f"[discovery] GitHub API error on page {page}: {e}")
            break
        if not batch:
            break
        for r in batch:
            # Only include repos actually owned by this token's user
            repo_owner = r.get("owner", {}).get("login", "")
            if repo_owner.lower() != owner.lower():
                continue
            repos.append({
                "name": r["name"],
                "remote_url": r.get("ssh_url") or r.get("clone_url"),
                "default_branch": r.get("default_branch", "main"),
            })
        page += 1
    print(f"[discovery] GitHub user {owner}: {len(repos)} owned repos")
    return repos


def discover_local_repos(directories: list[str]) -> list[dict]:
    """Scan directories for git repos (one level deep)."""
    repos = []
    for parent in directories:
        if not os.path.isdir(parent):
            continue
        for name in os.listdir(parent):
            repo_path = os.path.join(parent, name)
            if not os.path.isdir(repo_path):
                continue
            git_dir = os.path.join(repo_path, ".git")
            if not os.path.exists(git_dir):
                continue
            remote_url = _detect_remote(repo_path)
            repos.append({
                "name": name,
                "repo_path": repo_path,
                "remote_url": remote_url,
            })
    return repos


def _detect_remote(repo_path: str) -> Optional[str]:
    """Read origin remote URL from a local git repo."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def sync_projects(pg_conn_string: str, github_tokens: Optional[list[str]] = None,
                  local_dirs: Optional[list[str]] = None) -> dict:
    """Merge discovered projects into the DB. Returns counts."""
    from runtime.project_db import Project, ProjectStore
    ps = ProjectStore(pg_conn_string)
    existing = ps.list_projects(active_only=False)

    # Index existing by remote_url, repo_path, and name
    by_remote = {}
    by_path = {}
    by_name = {}
    for p in existing:
        if p.remote_url:
            by_remote[_normalize_remote(p.remote_url)] = p
        if p.repo_path:
            by_path[p.repo_path] = p
        by_name[p.name.lower()] = p

    added = 0

    # 1. GitHub repos (from all tokens/accounts)
    gh_repos = []
    for token in (github_tokens or []):
        if not token.strip():
            continue
        batch = discover_github_repos(token.strip())
        gh_repos.extend(batch)
    if gh_repos:
        print(f"[discovery] GitHub: found {len(gh_repos)} repos")
        for r in gh_repos:
            norm = _normalize_remote(r["remote_url"])
            if norm in by_remote:
                continue  # already registered by URL
            if r["name"].lower() in by_name:
                # Same name exists (e.g. registered locally without remote_url)
                existing_proj = by_name[r["name"].lower()]
                if not existing_proj.remote_url:
                    ps.update_project(existing_proj.id, remote_url=r["remote_url"])
                    by_remote[norm] = existing_proj
                continue
            project = Project(
                name=r["name"],
                repo_path=r["remote_url"],  # placeholder until cloned
                remote_url=r["remote_url"],
                base_branch=r.get("default_branch", "main"),
            )
            created = ps.create_project(project)
            by_remote[norm] = created
            added += 1

    # 2. Local repos
    if local_dirs:
        local_repos = discover_local_repos(local_dirs)
        print(f"[discovery] Local: found {len(local_repos)} repos")
        for r in local_repos:
            if r["repo_path"] in by_path:
                continue  # already registered by path
            # Check if we already have it by remote URL
            if r.get("remote_url"):
                norm = _normalize_remote(r["remote_url"])
                if norm in by_remote:
                    # Update existing cloud-only entry with local path
                    existing_proj = by_remote[norm]
                    if not existing_proj.repo_path:
                        ps.update_project(existing_proj.id, repo_path=r["repo_path"])
                    continue
            project = Project(
                name=r["name"],
                repo_path=r["repo_path"],
                remote_url=r.get("remote_url"),
            )
            created = ps.create_project(project)
            by_path[r["repo_path"]] = created
            if r.get("remote_url"):
                by_remote[_normalize_remote(r["remote_url"])] = created
            added += 1

    return {"existing": len(existing), "added": added, "total": len(existing) + added}


def _normalize_remote(url: str) -> str:
    """Normalize git remote URLs for comparison.

    git@github.com:user/repo.git and https://github.com/user/repo.git
    should match.
    """
    if not url:
        return ""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH → path
    if url.startswith("git@"):
        # git@github.com:user/repo → github.com/user/repo
        url = url.replace(":", "/", 1).replace("git@", "", 1)
    # HTTPS → path
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.lower()
