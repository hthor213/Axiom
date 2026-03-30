#!/usr/bin/env python3
"""
Autonomous Orchestrator — Deterministic build loop with multi-model adversarial review.

Python controls the loop. LLMs provide intelligence.
Termination conditions are enforced in code, not LLM memory.

Usage:
    python -m orchestrator.orchestrator --root /path/to/project
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Build plan — the modules to build in order
# ---------------------------------------------------------------------------

@dataclass
class ModuleSpec:
    """Specification for a single module to build."""
    name: str                    # e.g. "project.py"
    path: str                    # relative path: "lib/python/harness/project.py"
    test_path: Optional[str]     # relative path: "tests/harness/test_project.py"
    phase: int                   # build phase (0-7)
    description: str             # what the module does
    estimated_loc: int           # target LOC
    dependencies: list[str] = field(default_factory=list)  # modules that must exist first
    spec_context: str = ""       # additional context from specs/CURRENT_TASKS.md


# The full build plan extracted from CURRENT_TASKS.md
BUILD_PLAN: list[ModuleSpec] = [
    # Phase 0: Test infrastructure
    ModuleSpec(
        name="conftest.py",
        path="tests/harness/conftest.py",
        test_path=None,
        phase=0,
        description="Shared pytest fixtures: temporary project directories with sample specs, "
                    "sample BACKLOG.md, sample CURRENT_TASKS.md, sample LAST_SESSION.md. "
                    "Fixtures should create realistic temp project structures that other tests use.",
        estimated_loc=100,
    ),

    # Phase 1: Foundation modules
    ModuleSpec(
        name="project.py",
        path="lib/python/harness/project.py",
        test_path="tests/harness/test_project.py",
        phase=1,
        description="Project structure detection, scaffolding, and legacy migration. "
                    "detect_structure(root) -> ProjectStructure dataclass (has_specs_dir, has_legacy_spec, "
                    "has_backlog, has_current_tasks, has_last_session, has_done, has_claude_md, project_type). "
                    "scaffold(root, project_name) -> create specs/README.md, 000-vision.md template, "
                    "BACKLOG.md, CURRENT_TASKS.md, LAST_SESSION.md, DONE.md from templates. "
                    "migrate_legacy(root) -> migrate SPEC.md to specs/ directory. "
                    "ensure_workflow_files(root) -> create missing workflow files. "
                    "Per Gummi: 'Structure before speed.'",
        estimated_loc=250,
        dependencies=["conftest.py"],
    ),
    ModuleSpec(
        name="git_ops.py",
        path="lib/python/harness/git_ops.py",
        test_path="tests/harness/test_git_ops.py",
        phase=1,
        description="Git operations via subprocess. "
                    "GitStatus dataclass (branch, base_branch, has_remote, uncommitted, staged, "
                    "recent_commits, is_clean). "
                    "BranchInfo dataclass (current, base, tracks_remote, remote_name). "
                    "gather_status(root) -> GitStatus. "
                    "detect_branches(root) -> BranchInfo. "
                    "stage_files(root, files) -> bool. "
                    "create_commit(root, message) -> bool. "
                    "All via subprocess.run with capture_output=True.",
        estimated_loc=200,
        dependencies=["conftest.py"],
    ),
    ModuleSpec(
        name="crons.py",
        path="lib/python/harness/crons.py",
        test_path=None,
        phase=1,
        description="Session cron configuration definitions. "
                    "CronConfig dataclass (schedule, name, prompt_template). "
                    "session_cron_configs() -> list[CronConfig] returning 3 configs: "
                    "checkpoint nudge (~17 * * * *), spec sweep (*/23 * * * *), "
                    "drift check (*/37 * * * *). Each with a prompt template string.",
        estimated_loc=80,
    ),

    # Phase 2: Scanner and context
    ModuleSpec(
        name="scanner.py",
        path="lib/python/harness/scanner.py",
        test_path="tests/harness/test_scanner.py",
        phase=2,
        description="Spec scanning — builds on existing parser.py. "
                    "SpecInfo dataclass (path, number, title, status, band, done_when_total, "
                    "done_when_checked, done_when_automatable). "
                    "SpecReport dataclass (specs, by_band, by_status, active_count, drift_candidates). "
                    "SpecContext dataclass (vision, active_specs, invariants, exclusions, index_exists). "
                    "scan_specs(specs_dir) -> SpecReport. "
                    "classify_band(number) -> str ('vision'|'foundation'|'mvp'|'v1'|'v2'|'backlog'). "
                    "build_spec_context(root) -> SpecContext. "
                    "extract_invariants(vision_path) -> list[str] (parse ## Invariants section). "
                    "extract_exclusions(vision_path) -> list[str]. "
                    "Import from harness.parser for low-level markdown parsing.",
        estimated_loc=300,
        dependencies=["conftest.py"],
    ),
    ModuleSpec(
        name="platform_check.py",
        path="lib/python/harness/platform_check.py",
        test_path="tests/harness/test_platform_check.py",
        phase=2,
        description="Platform dependency detection. "
                    "PlatformReport dataclass (vault_exists, has_env_platform, has_env, "
                    "credential_source, infrastructure_deps, recommendation). "
                    "PlatformSyncReport dataclass (new_credentials, new_infrastructure, "
                    "reusable_patterns, needs_action). "
                    "check_platform_deps(root) -> PlatformReport. "
                    "check_sync_needs(session_changes) -> PlatformSyncReport. "
                    "validate_credential_access(action) -> bool (enforce credential boundary).",
        estimated_loc=180,
        dependencies=["conftest.py"],
    ),

    # Phase 3: Session and drift
    ModuleSpec(
        name="session.py",
        path="lib/python/harness/session.py",
        test_path="tests/harness/test_session.py",
        phase=3,
        description="Session context reading and priority resolution. "
                    "SessionContext dataclass (last_session, current_tasks, backlog_items, "
                    "done_items, git, spec_context). "
                    "NextAction dataclass (source, description, spec_ref, needs_spec, reasoning). "
                    "read_session_context(root) -> SessionContext. "
                    "parse_last_session(path) -> dict (parse LAST_SESSION.md sections). "
                    "parse_backlog(path) -> list[dict] (parse BACKLOG.md P0-P3 sections). "
                    "resolve_next_action(ctx) -> NextAction (check last_session 'Next Session "
                    "Should Start With' -> current_tasks -> backlog P0 -> backlog next). "
                    "Graceful degradation when markdown doesn't match expected structure.",
        estimated_loc=350,
        dependencies=["conftest.py", "scanner.py", "git_ops.py"],
    ),
    ModuleSpec(
        name="drift.py",
        path="lib/python/harness/drift.py",
        test_path="tests/harness/test_drift.py",
        phase=3,
        description="Deterministic drift signals only (semantic alignment stays with LLM). "
                    "DriftItem dataclass (type, description, spec_ref, severity). "
                    "DriftReport dataclass (items, clean, summary). "
                    "check_alignment(root, spec_context) -> DriftReport. "
                    "check_stale_active_specs(root, active_specs, stale_days=7) -> list[DriftItem]. "
                    "check_done_regressions(root, done_specs) -> list[DriftItem] "
                    "(re-run automatable Done When checks on done specs). "
                    "check_uncovered_directories(root, spec_context) -> list[DriftItem] "
                    "(key dirs with no spec coverage).",
        estimated_loc=180,
        dependencies=["conftest.py", "scanner.py"],
    ),

    # Phase 4: Lifecycle operations
    ModuleSpec(
        name="checkpoint.py",
        path="lib/python/harness/checkpoint.py",
        test_path="tests/harness/test_checkpoint.py",
        phase=4,
        description="Checkpoint operations for end-of-session. "
                    "InvariantResult dataclass (invariant, status, check_type, evidence). "
                    "BacklogDiff dataclass (moved_to_done, new_items, reprioritized). "
                    "CommitPlan dataclass (files_to_stage, message, has_changes). "
                    "check_automatable_invariants(root, invariants) -> list[InvariantResult]. "
                    "generate_session_summary(ctx, accomplishments) -> str (LAST_SESSION.md template). "
                    "update_backlog(root, completed, new_items) -> BacklogDiff. "
                    "cleanup_artifacts(root) -> list[str] (remove screenshots etc). "
                    "prepare_commit(root, message_prefix) -> CommitPlan.",
        estimated_loc=280,
        dependencies=["conftest.py", "session.py", "scanner.py", "git_ops.py"],
    ),
    ModuleSpec(
        name="refresh.py",
        path="lib/python/harness/refresh.py",
        test_path="tests/harness/test_refresh.py",
        phase=4,
        description="Mid-session state save. "
                    "generate_refresh_state(ctx) -> str (LAST_SESSION.md with IN PROGRESS status). "
                    "prepare_state_commit(root) -> CommitPlan (stage specs + state files only, "
                    "leave code changes unstaged).",
        estimated_loc=120,
        dependencies=["conftest.py", "session.py", "checkpoint.py"],
    ),
    ModuleSpec(
        name="ux.py",
        path="lib/python/harness/ux.py",
        test_path=None,
        phase=4,
        description="UX formatting for structured reports and questions. "
                    "QuestionContext dataclass (project, branch, working_on). "
                    "QuestionOption dataclass (label, description, effort, tradeoff). "
                    "format_question(ctx, situation, recommendation, options, spec_ref) -> str. "
                    "format_start_report(ctx, next_action, drift, platform) -> str. "
                    "format_checkpoint_report(spec_status, committed, invariants, platform, next_focus) -> str.",
        estimated_loc=130,
        dependencies=["session.py", "drift.py", "platform_check.py", "checkpoint.py"],
    ),

    # Phase 5: Agent support
    ModuleSpec(
        name="maestro_support.py",
        path="lib/python/harness/maestro_support.py",
        test_path="tests/harness/test_maestro_support.py",
        phase=5,
        description="Deterministic support for the maestro agent. "
                    "FiveFileStatus dataclass (files dict, all_present, format_issues). "
                    "WorkTransition dataclass (item, from_file, to_file, spec_created, spec_ref). "
                    "TasksValidation dataclass (milestone_count, exceeds_limit, format_issues, valid). "
                    "MilestoneValidation dataclass (has_clear_scope, has_testable_criteria, "
                    "has_verification_method, is_independent, issues). "
                    "validate_five_files(root) -> FiveFileStatus. "
                    "validate_current_tasks(root) -> TasksValidation. "
                    "validate_milestone(milestone_text) -> MilestoneValidation. "
                    "transition_work_item(root, item, from_state, to_state) -> WorkTransition. "
                    "count_active_milestones(root) -> int. "
                    "diagnose_failure_type(task_result, success_criteria) -> str.",
        estimated_loc=320,
        dependencies=["conftest.py", "scanner.py", "session.py"],
    ),
    ModuleSpec(
        name="analyst_support.py",
        path="lib/python/harness/analyst_support.py",
        test_path=None,
        phase=5,
        description="Report format validation for the analyst agent. "
                    "FormatValidation dataclass (has_critical_section, has_architectural_section, "
                    "has_patterns_section, has_recommendations_section, issues, valid). "
                    "validate_report_format(report) -> FormatValidation.",
        estimated_loc=80,
        dependencies=[],
    ),
]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

STATE_FILE = ".orchestrator-state.json"
LOG_FILE = ".orchestrator-log.md"

@dataclass
class OrchestratorState:
    started_at: str = ""
    current_phase: int = 0
    current_module: str = ""
    completed_modules: list[str] = field(default_factory=list)
    failed_modules: list[str] = field(default_factory=list)
    consecutive_failures: int = 0
    test_results: dict = field(default_factory=lambda: {"passed": 0, "failed": 0})
    adversarial_reviews: list[dict] = field(default_factory=list)
    total_api_calls: int = 0
    total_loc_written: int = 0
    module_attempts: dict = field(default_factory=dict)  # {module_name: attempt_count}
    status: str = "running"  # running | completed | stopped
    stop_reason: str = ""


def load_state(root: str) -> OrchestratorState:
    path = os.path.join(root, STATE_FILE)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return OrchestratorState(**json.load(f))
        except Exception:
            pass
    return OrchestratorState(started_at=datetime.now(timezone.utc).isoformat())


def save_state(state: OrchestratorState, root: str):
    path = os.path.join(root, STATE_FILE)
    with open(path, "w") as f:
        json.dump(asdict(state), f, indent=2)
        f.write("\n")


def log(root: str, message: str):
    """Append to the human-readable build log."""
    path = os.path.join(root, LOG_FILE)
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open(path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# API callers
# ---------------------------------------------------------------------------

def _load_credentials(root: str) -> dict:
    """Load API keys from .env file."""
    creds = {"anthropic": None, "openai": None, "google": None}
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return creds
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if key == "ANTHROPIC_API_KEY":
                creds["anthropic"] = val
            elif key == "OPENAI_API_KEY":
                creds["openai"] = val
            elif key == "GOOGLE_API_KEY":
                creds["google"] = val
    return creds


def call_claude(prompt: str, system: str, api_key: str,
                model: str = "claude-opus-4-6", max_tokens: int = 32768,
                timeout: int = 300) -> str:
    """Call Anthropic Messages API. Returns text response."""
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


def call_gemini(prompt: str, system: str, api_key: str,
                model: str = "gemini-3.1-pro-preview", max_tokens: int = 65536,
                timeout: int = 300) -> str:
    """Call Google Gemini API. Returns text response."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError(f"Gemini returned no content parts. Full response: {json.dumps(data)[:500]}")
    return parts[0]["text"]


def call_gpt(prompt: str, system: str, api_key: str,
             model: str = "gpt-5.4", max_tokens: int = 32768,
             timeout: int = 300) -> str:
    """Call OpenAI Chat Completions API. Returns text response."""
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Build step: generate a module
# ---------------------------------------------------------------------------

BUILD_SYSTEM = """You are a senior Python engineer building modules for the HTH AI Dev Framework.
You write clean, typed, documented Python code using only the stdlib (dataclasses, json, os, subprocess, pathlib, re, typing).
No external dependencies. Every function has type hints and a docstring.
When you write test files, use pytest conventions.
Return ONLY the Python code — no markdown fences, no explanation, just the .py file content."""


def build_module(module: ModuleSpec, root: str, creds: dict) -> tuple[str, Optional[str]]:
    """Generate module code and optionally test code via Claude API.

    Returns (module_code, test_code_or_none).
    """
    # Gather context: existing modules this depends on
    context_parts = []
    for dep in module.dependencies:
        # Find the dependency in BUILD_PLAN
        for m in BUILD_PLAN:
            if m.name == dep:
                dep_path = os.path.join(root, m.path)
                if os.path.exists(dep_path):
                    with open(dep_path) as f:
                        context_parts.append(f"# === {m.path} ===\n{f.read()}")
                break

    # Also include existing harness modules for reference
    for existing in ["parser.py", "spec_check.py", "state.py", "gates.py"]:
        existing_path = os.path.join(root, "lib/python/harness", existing)
        if os.path.exists(existing_path):
            with open(existing_path) as f:
                content = f.read()
            context_parts.append(f"# === lib/python/harness/{existing} (existing) ===\n{content}")

    context = "\n\n".join(context_parts)

    prompt = f"""Build the following Python module.

## Module: {module.name}
## Path: {module.path}
## Description:
{module.description}

## Target LOC: ~{module.estimated_loc}

## Existing code for context (import from these):
{context}

Write the complete module. Use dataclasses for all data structures. Import from existing harness modules where appropriate (e.g., from .parser import extract_done_when). Handle missing files gracefully (return defaults, don't crash)."""

    module_code = call_claude(prompt, BUILD_SYSTEM, creds["anthropic"])

    # Generate test if needed
    test_code = None
    if module.test_path:
        test_prompt = f"""Write pytest tests for the following module.

## Module being tested: {module.path}
## Module code:
{module_code}

## Test fixtures available (from conftest.py):
{context_parts[0] if context_parts else "Standard temp directory fixtures."}

Write comprehensive tests covering:
- Happy path for each function
- Edge cases (missing files, empty directories, malformed markdown)
- Dataclass construction and field defaults

Use pytest fixtures, tmp_path, and assertions. Target ~{module.estimated_loc // 2} LOC of tests."""

        test_code = call_claude(test_prompt, BUILD_SYSTEM, creds["anthropic"])

    return module_code, test_code


# ---------------------------------------------------------------------------
# Review step: adversarial critique
# ---------------------------------------------------------------------------

CHALLENGER_SYSTEM = """You are an adversarial code reviewer for a Python framework.
Find bugs, edge cases, security issues, missing error handling, and design problems.
Be specific: cite line numbers, explain why it's a problem, suggest fixes.
Focus on correctness and robustness, not style preferences.
Respond in JSON: {"issues": [{"severity": "critical|high|medium|low", "description": "...", "suggestion": "..."}], "summary": "..."}"""

AUTHOR_SYSTEM = """You are a senior Python engineer defending your code.
Review each issue raised by the challenger. For each:
- If valid: accept it and provide the fix (actual code, not description)
- If wrong: rebut with technical reasoning
Respond in JSON: {"responses": [{"issue_index": 0, "verdict": "accept|rebut", "reasoning": "...", "fix": "..."}], "summary": "..."}"""

ARBITER_SYSTEM = """You are a senior technical arbiter. The author and reviewer disagree on some issues.
For each disputed point, make a final ruling.
Respond in JSON: {"rulings": [{"issue_index": 0, "side": "challenger|author", "reasoning": "..."}], "summary": "..."}"""


def adversarial_review(code: str, module: ModuleSpec, creds: dict) -> dict:
    """Run 3-model adversarial review on generated code.

    Returns dict with challenger_output, author_output, arbiter_output (if needed).
    """
    result = {"challenger": None, "author": None, "arbiter": None, "changes_needed": []}

    # Step 1: Gemini challenger
    challenge_prompt = f"Review this Python module critically:\n\n## {module.path}\n```python\n{code}\n```\n\n## Purpose: {module.description}"
    try:
        raw = call_gemini(challenge_prompt, CHALLENGER_SYSTEM, creds["google"])
        # Try to parse JSON from response
        challenger = _extract_json(raw)
        result["challenger"] = challenger
    except Exception as e:
        result["challenger"] = {"issues": [], "summary": f"Challenger failed: {e}"}
        return result

    issues = challenger.get("issues", [])
    if not issues:
        result["challenger"]["summary"] = "No issues found."
        return result

    # Step 2: Claude author rebuttal
    author_prompt = f"The challenger found these issues in your code:\n\n{json.dumps(issues, indent=2)}\n\nYour code:\n```python\n{code}\n```\n\nRespond to each issue."
    try:
        raw = call_claude(author_prompt, AUTHOR_SYSTEM, creds["anthropic"])
        author = _extract_json(raw)
        result["author"] = author
    except Exception as e:
        result["author"] = {"responses": [], "summary": f"Author failed: {e}"}
        return result

    # Check for disputes (author rebutted)
    responses = author.get("responses", [])
    disputes = [r for r in responses if r.get("verdict") == "rebut"]

    if not disputes:
        # Author accepted everything — collect fixes
        for r in responses:
            if r.get("fix"):
                result["changes_needed"].append(r["fix"])
        return result

    # Step 3: GPT arbiter for disputes
    arbiter_prompt = f"Disputed issues:\n\nChallenger's issues: {json.dumps(issues, indent=2)}\n\nAuthor's responses: {json.dumps(responses, indent=2)}\n\nRule on the disputes."
    try:
        raw = call_gpt(arbiter_prompt, ARBITER_SYSTEM, creds["openai"])
        arbiter = _extract_json(raw)
        result["arbiter"] = arbiter

        # Collect fixes from accepted issues (challenger wins or author accepted)
        for r in responses:
            if r.get("verdict") == "accept" and r.get("fix"):
                result["changes_needed"].append(r["fix"])
    except Exception as e:
        result["arbiter"] = {"rulings": [], "summary": f"Arbiter failed: {e}"}

    return result


def _extract_json(text: str) -> dict:
    """Extract JSON from a response that might have markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"issues": [], "summary": f"Could not parse JSON from response", "raw": text[:500]}


# ---------------------------------------------------------------------------
# Apply fixes step
# ---------------------------------------------------------------------------

def apply_fixes(original_code: str, fixes: list[str], module: ModuleSpec, creds: dict) -> str:
    """Have Claude apply the accepted fixes to the code."""
    if not fixes:
        return original_code

    fixes_text = "\n\n".join(f"Fix {i+1}:\n{fix}" for i, fix in enumerate(fixes))
    prompt = f"""Apply these fixes to the module. Return the complete updated module code.

## Fixes to apply:
{fixes_text}

## Current code:
```python
{original_code}
```

Return ONLY the complete updated Python code."""

    return call_claude(prompt, BUILD_SYSTEM, creds["anthropic"])


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(root: str) -> tuple[int, int, str]:
    """Run pytest on the harness tests. Returns (passed, failed, output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/harness/", "-v", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=120, cwd=root,
        )
        output = result.stdout + result.stderr

        # Parse pytest output for counts
        passed = failed = 0
        for line in output.split("\n"):
            if "passed" in line:
                import re
                m = re.search(r"(\d+) passed", line)
                if m:
                    passed = int(m.group(1))
                m = re.search(r"(\d+) failed", line)
                if m:
                    failed = int(m.group(1))

        return passed, failed, output
    except subprocess.TimeoutExpired:
        return 0, 1, "Tests timed out after 120s"
    except Exception as e:
        return 0, 0, f"Test runner error: {e}"


# ---------------------------------------------------------------------------
# Code cleaning
# ---------------------------------------------------------------------------

def clean_code(code: str) -> str:
    """Remove markdown fences and other non-Python artifacts from generated code."""
    lines = code.split("\n")
    cleaned = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence or True:  # Keep all lines outside fences
            cleaned.append(line)
    result = "\n".join(cleaned).strip()
    # Ensure the file ends with a newline
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def count_loc(code: str) -> int:
    """Count non-blank, non-comment lines."""
    count = 0
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

MAX_CONSECUTIVE_FAILURES = 3
MAX_MODULE_ATTEMPTS = 2  # Max retries per individual module
MAX_RUNTIME = timedelta(hours=6)


def run(root: str):
    """Main orchestrator loop."""
    state = load_state(root)
    creds = _load_credentials(root)

    # Verify we have at least Claude (required for building)
    if not creds.get("anthropic"):
        log(root, "FATAL: No Anthropic API key in .env. Cannot build.")
        return

    start_time = datetime.now(timezone.utc)
    log(root, "=" * 60)
    log(root, "ORCHESTRATOR STARTED")
    log(root, f"  Anthropic key: {'YES' if creds.get('anthropic') else 'NO'}")
    log(root, f"  Google key:    {'YES' if creds.get('google') else 'NO'}")
    log(root, f"  OpenAI key:    {'YES' if creds.get('openai') else 'NO'}")
    log(root, f"  Modules to build: {len(BUILD_PLAN)}")
    log(root, f"  Already completed: {len(state.completed_modules)}")
    log(root, "=" * 60)

    for module in BUILD_PLAN:
        # Skip already completed
        if module.name in state.completed_modules:
            continue

        # Check dependencies
        deps_met = all(d in state.completed_modules for d in module.dependencies)
        if not deps_met:
            missing = [d for d in module.dependencies if d not in state.completed_modules]
            log(root, f"SKIP {module.name} — waiting for deps: {missing}")
            continue

        # Check per-module attempt limit
        attempts = state.module_attempts.get(module.name, 0)
        if attempts >= MAX_MODULE_ATTEMPTS:
            log(root, f"SKIP {module.name} — exceeded {MAX_MODULE_ATTEMPTS} attempts")
            continue

        # Check termination conditions
        elapsed = datetime.now(timezone.utc) - start_time
        if elapsed > MAX_RUNTIME:
            state.status = "stopped"
            state.stop_reason = f"Time limit reached ({elapsed})"
            log(root, f"STOPPING: {state.stop_reason}")
            break

        if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            state.status = "stopped"
            state.stop_reason = f"{state.consecutive_failures} consecutive failures"
            log(root, f"STOPPING: {state.stop_reason}")
            break

        # Build this module
        state.current_module = module.name
        state.current_phase = module.phase
        state.module_attempts[module.name] = state.module_attempts.get(module.name, 0) + 1
        save_state(state, root)

        log(root, "")
        log(root, f"--- Phase {module.phase}: Building {module.name} ---")
        log(root, f"  Path: {module.path}")
        log(root, f"  Target: ~{module.estimated_loc} LOC")

        try:
            # Step 1: Generate code
            log(root, "  Step 1: Generating code via Claude...")
            module_code, test_code = build_module(module, root, creds)
            state.total_api_calls += 1 + (1 if test_code else 0)

            module_code = clean_code(module_code)
            if test_code:
                test_code = clean_code(test_code)

            loc = count_loc(module_code)
            log(root, f"  Generated {loc} LOC")

            # Step 2: Write to disk
            module_path = os.path.join(root, module.path)
            os.makedirs(os.path.dirname(module_path), exist_ok=True)
            with open(module_path, "w") as f:
                f.write(module_code)
            log(root, f"  Written to {module.path}")

            if test_code and module.test_path:
                test_path = os.path.join(root, module.test_path)
                os.makedirs(os.path.dirname(test_path), exist_ok=True)
                with open(test_path, "w") as f:
                    f.write(test_code)
                log(root, f"  Tests written to {module.test_path}")

            # Step 3: Run tests
            log(root, "  Step 2: Running tests...")
            passed, failed, test_output = run_tests(root)
            state.test_results = {"passed": passed, "failed": failed}
            log(root, f"  Tests: {passed} passed, {failed} failed")

            if failed > 0:
                # Try to fix test failures
                log(root, "  Tests failing — asking Claude to fix...")
                fix_prompt = f"""The following tests are failing. Fix the module code.

## Test output:
{test_output[-2000:]}

## Current module code ({module.path}):
```python
{module_code}
```

{f'## Current test code ({module.test_path}):' + chr(10) + '```python' + chr(10) + test_code + chr(10) + '```' if test_code else ''}

Fix the issues. Return ONLY the corrected module code."""

                fixed_code = call_claude(fix_prompt, BUILD_SYSTEM, creds["anthropic"])
                fixed_code = clean_code(fixed_code)
                state.total_api_calls += 1

                with open(module_path, "w") as f:
                    f.write(fixed_code)
                module_code = fixed_code

                # Re-run tests
                passed, failed, test_output = run_tests(root)
                state.test_results = {"passed": passed, "failed": failed}
                log(root, f"  After fix: {passed} passed, {failed} failed")

                if failed > 0:
                    # One more attempt — also fix the tests if needed
                    log(root, "  Still failing — fixing both module and tests...")
                    fix_prompt2 = f"""Tests are still failing after one fix attempt. Fix BOTH the module and the tests.

## Test output:
{test_output[-2000:]}

## Module ({module.path}):
```python
{module_code}
```

{f'## Tests ({module.test_path}):' + chr(10) + '```python' + chr(10) + test_code + chr(10) + '```' if test_code else ''}

Return the fixed module code first, then a line containing exactly "---SPLIT---", then the fixed test code."""

                    combined = call_claude(fix_prompt2, BUILD_SYSTEM, creds["anthropic"])
                    state.total_api_calls += 1

                    if "---SPLIT---" in combined:
                        parts = combined.split("---SPLIT---")
                        module_code = clean_code(parts[0])
                        test_code = clean_code(parts[1]) if len(parts) > 1 else test_code
                    else:
                        module_code = clean_code(combined)

                    with open(module_path, "w") as f:
                        f.write(module_code)
                    if test_code and module.test_path:
                        with open(test_path, "w") as f:
                            f.write(test_code)

                    passed, failed, _ = run_tests(root)
                    state.test_results = {"passed": passed, "failed": failed}
                    log(root, f"  After 2nd fix: {passed} passed, {failed} failed")

            # Step 4: Adversarial review (if Google key available)
            if creds.get("google"):
                log(root, "  Step 3: Adversarial review (Gemini → Claude → GPT)...")
                review = adversarial_review(module_code, module, creds)
                state.adversarial_reviews.append({
                    "module": module.name,
                    "challenger_issues": len(review.get("challenger", {}).get("issues", [])),
                    "changes_needed": len(review.get("changes_needed", [])),
                    "arbiter_invoked": review.get("arbiter") is not None,
                })
                state.total_api_calls += 1  # challenger
                if review.get("author"):
                    state.total_api_calls += 1
                if review.get("arbiter"):
                    state.total_api_calls += 1

                n_issues = len(review.get("challenger", {}).get("issues", []))
                n_fixes = len(review.get("changes_needed", []))
                log(root, f"  Challenger found {n_issues} issues, {n_fixes} fixes accepted")

                # Apply fixes if any — but REVERT if tests regress
                if review.get("changes_needed"):
                    log(root, "  Applying accepted fixes...")
                    pre_fix_code = module_code  # Save for revert
                    pre_fix_passed = state.test_results.get("passed", 0)
                    pre_fix_failed = state.test_results.get("failed", 0)

                    module_code = apply_fixes(module_code, review["changes_needed"], module, creds)
                    module_code = clean_code(module_code)
                    state.total_api_calls += 1

                    with open(module_path, "w") as f:
                        f.write(module_code)

                    # Re-run tests after fixes
                    passed, failed, _ = run_tests(root)

                    if failed > pre_fix_failed:
                        # Fixes broke tests — REVERT
                        log(root, f"  Adversarial fixes regressed tests ({pre_fix_failed} -> {failed} failures) — REVERTING")
                        module_code = pre_fix_code
                        with open(module_path, "w") as f:
                            f.write(module_code)
                        passed, failed, _ = run_tests(root)

                    state.test_results = {"passed": passed, "failed": failed}
                    log(root, f"  After adversarial step: {passed} passed, {failed} failed")
            else:
                log(root, "  Skipping adversarial review (no Google key)")

            # Step 5: Final assessment
            final_loc = count_loc(module_code)
            state.total_loc_written += final_loc

            if state.test_results["failed"] == 0:
                state.completed_modules.append(module.name)
                state.consecutive_failures = 0
                log(root, f"  COMPLETE: {module.name} ({final_loc} LOC, {passed} tests passing)")
            else:
                state.failed_modules.append(module.name)
                state.consecutive_failures += 1
                log(root, f"  FAILED: {module.name} ({failed} tests still failing)")

        except Exception as e:
            log(root, f"  ERROR: {module.name} — {e}")
            state.failed_modules.append(module.name)
            state.consecutive_failures += 1

        save_state(state, root)

    # Final summary
    if all(m.name in state.completed_modules for m in BUILD_PLAN):
        state.status = "completed"
        state.stop_reason = "All modules built successfully"

    elapsed = datetime.now(timezone.utc) - start_time
    log(root, "")
    log(root, "=" * 60)
    log(root, f"ORCHESTRATOR FINISHED — {state.status.upper()}")
    log(root, f"  Reason: {state.stop_reason or 'all done'}")
    log(root, f"  Completed: {len(state.completed_modules)}/{len(BUILD_PLAN)} modules")
    log(root, f"  Failed: {len(state.failed_modules)}")
    log(root, f"  Total LOC written: {state.total_loc_written}")
    log(root, f"  Total API calls: {state.total_api_calls}")
    log(root, f"  Tests: {state.test_results['passed']} passed, {state.test_results['failed']} failed")
    log(root, f"  Runtime: {elapsed}")
    log(root, "=" * 60)

    save_state(state, root)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous orchestrator")
    parser.add_argument("--root", default=os.getcwd(), help="Project root")
    args = parser.parse_args()
    run(args.root)
