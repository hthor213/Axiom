"""Deterministic codebase scanner for spec inference.

Scans a project's files and structure to produce a structured summary
that an LLM can use to propose specs. No LLM calls here — pure Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProjectSummary:
    """Structured scan of a project's codebase."""
    name: str
    readme: Optional[str] = None
    docs: dict[str, str] = field(default_factory=dict)   # filename -> content
    tree: list[str] = field(default_factory=list)         # relative paths
    languages: dict[str, int] = field(default_factory=dict)  # ext -> count
    package_meta: dict[str, str] = field(default_factory=dict)  # filename -> content
    entry_points: list[str] = field(default_factory=list)
    has_docker: bool = False
    has_ci: bool = False
    has_specs: bool = False

    def to_prompt_text(self) -> str:
        """Format as text suitable for an LLM prompt."""
        parts = [f"# Project: {self.name}\n"]

        if self.readme:
            parts.append(f"## README\n{self.readme}\n")

        if self.docs:
            parts.append("## Documentation Files")
            for fname, content in self.docs.items():
                parts.append(f"\n### {fname}\n{content}")
            parts.append("")

        if self.package_meta:
            parts.append("## Package Metadata")
            for fname, content in self.package_meta.items():
                parts.append(f"\n### {fname}\n```\n{content}\n```")
            parts.append("")

        if self.tree:
            parts.append("## Directory Structure\n```")
            parts.extend(self.tree[:80])
            if len(self.tree) > 80:
                parts.append(f"... ({len(self.tree) - 80} more files)")
            parts.append("```\n")

        if self.languages:
            parts.append("## Languages")
            for ext, count in sorted(
                self.languages.items(), key=lambda x: -x[1]
            ):
                parts.append(f"- {ext}: {count} files")
            parts.append("")

        if self.entry_points:
            parts.append("## Entry Points")
            for ep in self.entry_points:
                parts.append(f"- {ep}")
            parts.append("")

        flags = []
        if self.has_docker:
            flags.append("Docker")
        if self.has_ci:
            flags.append("CI/CD")
        if self.has_specs:
            flags.append("Has specs/ directory")
        if flags:
            parts.append(f"## Infrastructure: {', '.join(flags)}\n")

        return "\n".join(parts)


# ---- Scanner ----

# Files to read as documentation (case-insensitive basename match)
_DOC_FILES = {
    "readme.md", "requirements.md", "claude.md", "backlog.md",
    "current_tasks.md", "done.md", "changelog.md", "contributing.md",
    "architecture.md",
}

# Package/config files to capture
_PACKAGE_FILES = {
    "package.json", "setup.py", "setup.cfg", "pyproject.toml",
    "cargo.toml", "go.mod", "gemfile", "pom.xml",
    "requirements.txt", "pipfile",
}

# Common entry point patterns
_ENTRY_POINTS = {
    "main.py", "app.py", "index.py", "server.py", "manage.py",
    "index.js", "index.ts", "app.js", "app.ts", "server.js",
    "main.go", "main.rs", "lib.rs",
}

# Directories to skip during tree walk
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "coverage", ".eggs", "*.egg-info",
}

_MAX_FILE_SIZE = 32_000  # Max bytes to read from any single file


def scan_project(repo_path: str, name: str = "") -> ProjectSummary:
    """Scan a project directory and return a structured summary."""
    if not os.path.isdir(repo_path):
        return ProjectSummary(name=name or os.path.basename(repo_path))

    project_name = name or os.path.basename(repo_path)
    summary = ProjectSummary(name=project_name)

    # Walk directory tree (max 3 levels deep)
    _scan_tree(repo_path, summary)

    # Read documentation files
    _scan_docs(repo_path, summary)

    # Read package metadata
    _scan_packages(repo_path, summary)

    # Detect entry points
    _scan_entry_points(repo_path, summary)

    # Infrastructure flags
    summary.has_docker = any(
        f.lower().startswith("dockerfile") for f in os.listdir(repo_path)
    )
    summary.has_ci = os.path.isdir(os.path.join(repo_path, ".github"))
    summary.has_specs = os.path.isdir(os.path.join(repo_path, "specs"))

    return summary


def _safe_read(path: str) -> Optional[str]:
    """Read a file, returning None if too large or unreadable."""
    try:
        size = os.path.getsize(path)
        if size > _MAX_FILE_SIZE:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _should_skip(dirname: str) -> bool:
    """Check if a directory should be skipped."""
    lower = dirname.lower()
    return lower in _SKIP_DIRS or lower.startswith(".")


def _scan_tree(repo_path: str, summary: ProjectSummary) -> None:
    """Build directory tree and language breakdown."""
    for root, dirs, files in os.walk(repo_path):
        # Skip hidden/vendor dirs
        dirs[:] = [d for d in dirs if not _should_skip(d)]

        depth = root.replace(repo_path, "").count(os.sep)
        if depth >= 3:
            dirs.clear()
            continue

        for fname in sorted(files):
            rel = os.path.relpath(os.path.join(root, fname), repo_path)
            summary.tree.append(rel)

            # Language stats
            _, ext = os.path.splitext(fname)
            if ext:
                summary.languages[ext] = summary.languages.get(ext, 0) + 1


def _scan_docs(repo_path: str, summary: ProjectSummary) -> None:
    """Read documentation files from project root."""
    for fname in os.listdir(repo_path):
        if fname.lower() in _DOC_FILES:
            content = _safe_read(os.path.join(repo_path, fname))
            if content:
                if fname.lower() == "readme.md":
                    summary.readme = content
                else:
                    summary.docs[fname] = content


def _scan_packages(repo_path: str, summary: ProjectSummary) -> None:
    """Read package/config files from project root."""
    for fname in os.listdir(repo_path):
        if fname.lower() in _PACKAGE_FILES:
            content = _safe_read(os.path.join(repo_path, fname))
            if content:
                summary.package_meta[fname] = content


def _scan_entry_points(repo_path: str, summary: ProjectSummary) -> None:
    """Find common entry point files."""
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not _should_skip(d)]
        depth = root.replace(repo_path, "").count(os.sep)
        if depth >= 2:
            dirs.clear()
            continue
        for fname in files:
            if fname.lower() in _ENTRY_POINTS:
                rel = os.path.relpath(os.path.join(root, fname), repo_path)
                summary.entry_points.append(rel)
