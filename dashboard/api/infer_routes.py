"""Spec inference routes — propose specs from codebase analysis.

Handles: POST /projects/{id}/infer-specs  (scan + LLM → proposed specs)
         POST /projects/{id}/save-specs   (write approved specs to disk)
         POST /projects/{id}/sync-specs   (compare specs vs code reality)
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .state import get_store, require_auth

router = APIRouter(prefix="/projects", tags=["spec-inference"])


# ---- Helpers ----

def _project_store(store):
    from runtime.project_db import ProjectStore
    return ProjectStore(store._pg_conn_string)


def _effective_path(project) -> Optional[str]:
    """Return local repo path, or None if not available.

    No REPO_ROOT fallback — inference must scan the actual project,
    never a different repo. If the path doesn't exist, return None.
    """
    path = project.repo_path
    if path and os.path.isdir(path):
        return path
    return None


def _call_claude(prompt: str, system: str) -> str:
    """Call Claude API for spec inference."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing ANTHROPIC_API_KEY")
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 16384,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


# ---- Prompts ----

INFER_SYSTEM = """You are a software architect who writes specs for existing projects.

Given a structured summary of a project's codebase (directory tree, README, docs,
package files, entry points), propose a set of specs that accurately describe what
this project IS and DOES.

Rules:
- Start with spec 000: a vision spec — what this project is, who it's for, why it exists
- Then add feature specs ONLY for truly distinct, separable features
- IMPORTANT: match the number of specs to the project's complexity:
  - A simple single-purpose app (image resizer, calculator, todo list) → 1 vision spec only, maybe 1 feature spec
  - A medium app with 3-5 distinct features → 2-4 specs total
  - A complex platform with many subsystems → up to 10 specs
  - When in doubt, FEWER specs is better. Combine related functionality.
- Number feature specs starting from 001
- Every spec MUST follow this exact format (no extra sections):

```markdown
# NNN: Title

**Status:** done

## Goal
What this feature/component does and why.

## Done When
- [x] Concrete, verifiable criterion (checked because it already exists)
```

- Since these are existing features, mark status as "done" and check all Done When items
- Done When items must be verifiable: "API endpoint /foo returns data", not "works well"
- Do NOT create separate specs for: deployment, storage, frontend, backend, cleanup — unless they are genuinely independent features a user would recognize
- Return ONLY a JSON array of objects: [{"number": "000", "title": "...", "filename": "000-title-slug.md", "content": "...markdown..."}]
- No commentary outside the JSON array"""


# ---- Endpoints ----

class SaveSpecsRequest(BaseModel):
    specs: list[dict]  # [{number, filename, content}, ...]


@router.post("/{project_id}/infer-specs", dependencies=[Depends(require_auth)])
async def infer_specs(project_id: int):
    """Scan a project's codebase and propose specs via LLM."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    repo_path = _effective_path(project)
    if not repo_path:
        raise HTTPException(400, "Project has no local clone — clone it first")

    # Deterministic scan
    from harness.spec_infer import scan_project
    summary = scan_project(repo_path, name=project.name)

    # Note: we allow inference even if specs exist — the LLM can propose
    # specs for uncovered features. The frontend should warn the user.

    # LLM inference
    prompt = summary.to_prompt_text()
    try:
        raw = _call_claude(prompt, INFER_SYSTEM)
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    # Parse JSON from response (handle markdown code fences)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        specs = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "raw": raw,
                "message": "LLM response was not valid JSON"}

    return {
        "status": "ok",
        "specs": specs,
        "has_existing_specs": summary.has_specs,
        "summary_lines": len(prompt.splitlines()),
    }


@router.post("/{project_id}/save-specs", dependencies=[Depends(require_auth)])
async def save_specs(project_id: int, req: SaveSpecsRequest):
    """Write approved specs to the project's specs/ directory and commit."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    repo_path = _effective_path(project)
    if not repo_path:
        raise HTTPException(400, "Project has no local clone")

    specs_dir = os.path.join(repo_path, "specs")
    os.makedirs(specs_dir, exist_ok=True)

    written = []
    for spec in req.specs:
        filename = spec.get("filename", f"{spec['number']}-untitled.md")
        filepath = os.path.join(specs_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(spec["content"])
        written.append(filename)

    # Git add + commit
    try:
        subprocess.run(
            ["git", "add", "specs/"],
            cwd=repo_path, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m",
             f"feat: inferred specs from codebase ({len(written)} specs)"],
            cwd=repo_path, capture_output=True, timeout=10,
        )
    except Exception:
        pass  # Non-fatal — files are written even if commit fails

    return {"status": "ok", "written": written}


# ---- Spec-Reality Sync ----

SYNC_SYSTEM = """You are a software architect comparing a project's specs against its actual codebase.

Given:
1. A structured summary of the codebase (directory tree, docs, packages, entry points)
2. The existing specs (full markdown content)

Analyze the alignment between specs and code. Return a JSON object with:

{
  "alignment_score": 0-100,
  "summary": "One paragraph overall assessment",
  "uncovered_features": [
    {"feature": "...", "evidence": "...", "suggested_spec": "NNN: Title"}
  ],
  "stale_specs": [
    {"spec": "NNN: Title", "issue": "..."}
  ],
  "mismatches": [
    {"spec": "NNN: Title", "claim": "...", "reality": "..."}
  ],
  "suggestions": ["..."]
}

Rules:
- uncovered_features: things the code does that no spec describes
- stale_specs: specs that describe something the code no longer does
- mismatches: spec claims that don't match what the code actually does
- Be specific: cite filenames, endpoints, function names as evidence
- Only flag real gaps, not minor wording differences
- Return ONLY the JSON object, no commentary"""


def _read_existing_specs(repo_path: str) -> str:
    """Read all spec files from a project's specs/ directory."""
    specs_dir = os.path.join(repo_path, "specs")
    if not os.path.isdir(specs_dir):
        return ""
    parts = []
    for fname in sorted(os.listdir(specs_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(specs_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            parts.append(f"### {fname}\n{content}")
        except Exception:
            continue
    return "\n\n".join(parts)


@router.post("/{project_id}/sync-specs", dependencies=[Depends(require_auth)])
async def sync_specs(project_id: int):
    """Compare existing specs against the actual codebase via LLM."""
    store = get_store()
    ps = _project_store(store)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    repo_path = _effective_path(project)
    if not repo_path:
        raise HTTPException(400, "Project has no local clone — clone it first")

    # Read existing specs
    specs_text = _read_existing_specs(repo_path)
    if not specs_text:
        raise HTTPException(400, "Project has no specs — use infer-specs first")

    # Deterministic scan
    from harness.spec_infer import scan_project
    summary = scan_project(repo_path, name=project.name)
    scan_text = summary.to_prompt_text()

    prompt = (
        f"{scan_text}\n\n"
        f"---\n\n"
        f"# Existing Specs\n\n{specs_text}"
    )

    try:
        raw = _call_claude(prompt, SYNC_SYSTEM)
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    # Parse JSON
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "raw": raw,
                "message": "LLM response was not valid JSON"}

    return {"status": "ok", "sync": result}
