"""Adversarial evaluation pipeline runner.

Deterministic orchestrator: Python controls the flow, three models
challenge each other's code, results are collected into a report.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .arbiter import run_arbiter
from .author_rebuttal import run_author_rebuttal
from .challenger import run_challenger, run_counter_rebuttal
from .model_resolver import ResolvedModels
from .report import generate_report, write_report, write_tests

MAX_DEBATE_ROUNDS = 3


def gather_file_data(files: list[str], project_root: str) -> list[dict]:
    """Read file contents and git diff for each file.

    Args:
        files: list of file paths (absolute or relative to project_root).
        project_root: project root directory.

    Returns:
        List of {path, content, diff} dicts.
    """
    result: list[dict] = []
    for fpath in files:
        abs_path = fpath if os.path.isabs(fpath) else os.path.join(project_root, fpath)
        rel_path = os.path.relpath(abs_path, project_root)

        # Read content
        try:
            with open(abs_path) as f:
                content = f.read()
        except OSError as exc:
            print(f"  Warning: cannot read {abs_path}: {exc}", file=sys.stderr)
            continue

        # Get git diff (staged + unstaged)
        diff = ""
        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD", "--", rel_path],
                capture_output=True, text=True, timeout=10,
                cwd=project_root,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                diff = proc.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        result.append({"path": rel_path, "content": content, "diff": diff})

    return result


def get_spec_context(project_root: str,
                     spec_number: str = "") -> str:
    """Read spec Goal and Done-When criteria for context.

    If spec_number is provided, returns only that spec's Goal + Done-When.
    Otherwise falls back to all specs (legacy behavior).
    """
    specs_dir = os.path.join(project_root, "specs")

    # If a specific spec is requested, find only that one
    if spec_number and os.path.isdir(specs_dir):
        for name in sorted(os.listdir(specs_dir)):
            if (name.startswith(f"{spec_number}-")
                    and name.endswith(".md")):
                full = os.path.join(specs_dir, name)
                goal = _extract_goal(full)
                dw = _extract_done_when(full)
                parts = [f"## {name}"]
                if goal:
                    parts.append(f"### Mission\n{goal}")
                if dw:
                    parts.append(f"### Done When\n{dw}")
                return "\n".join(parts) if len(parts) > 1 else ""
        return ""

    # Try SPEC.md first (legacy single-spec projects)
    spec_path = os.path.join(project_root, "SPEC.md")
    if os.path.isfile(spec_path):
        return _extract_done_when(spec_path)

    # Try specs/ directory — all specs
    if os.path.isdir(specs_dir):
        parts: list[str] = []
        for name in sorted(os.listdir(specs_dir)):
            if name.endswith(".md") and name[0].isdigit():
                full = os.path.join(specs_dir, name)
                dw = _extract_done_when(full)
                if dw:
                    parts.append(f"## {name}\n{dw}")
        return "\n\n".join(parts)

    return ""


def _extract_goal(path: str) -> str:
    """Extract the first sentence of the Goal section from a spec file."""
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return ""

    import re
    match = re.search(
        r"^##\s+Goal\s*\n(.*?)(?=\n##\s|\Z)",
        content, re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    text = match.group(1).strip()
    if not text:
        return ""
    # First sentence
    sentence = re.match(r"(.+?\.)\s", text, re.DOTALL)
    return sentence.group(1).strip() if sentence else text.split("\n")[0].strip()


def _extract_done_when(path: str) -> str:
    """Extract Done-When section from a spec markdown file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return ""

    capturing = False
    result: list[str] = []
    for line in lines:
        stripped = line.strip().lower()
        if "done when" in stripped or "done-when" in stripped:
            capturing = True
            continue
        if capturing:
            # Stop at next heading
            if line.startswith("#") and result:
                break
            result.append(line)

    return "".join(result).strip()


def run_pipeline(
    files: list[str],
    project_root: str,
    credentials: dict,
    models: ResolvedModels,
    progress_callback=None,
    spec_number: str = "",
    plan_context: str = "",
) -> dict:
    """Full deterministic pipeline.

    Steps:
        1. Gather file data (read files + git diff)
        2. Get spec context
        3. Challenger reviews (Google/Gemini)
        4. Author rebuts (Anthropic/Claude)
        5. Arbiter decides (OpenAI/GPT) — only if unresolved disagreements
        6. Write tests
        7. Generate and write report

    Args:
        files: list of file paths to evaluate.
        project_root: project root directory.
        credentials: dict with 'anthropic', 'openai', 'google' keys.
        models: resolved model IDs.

    Returns:
        Report dict.
    """
    # Steps: 1 gather, 2 spec, 3 challenger, then up to 3 debate rounds
    # (2 steps each: author + counter-rebuttal), then arbiter, then report
    total_steps = 3 + (MAX_DEBATE_ROUNDS * 2) + 1  # 10

    def _progress(phase: str, detail: dict | None = None):
        if progress_callback:
            progress_callback(phase, detail or {})

    # Step 1: Gather file data
    print(f"Step 1/{total_steps}: Gathering file data...", file=sys.stderr)
    file_data = gather_file_data(files, project_root)
    if not file_data:
        print("  No files to evaluate — aborting.", file=sys.stderr)
        return {
            "error": "No readable files provided",
            "verdict": "PASS",
            "issues": [],
        }

    # Step 2: Get spec context
    print(f"Step 2/{total_steps}: Reading spec context...", file=sys.stderr)
    spec_context = get_spec_context(project_root, spec_number)
    if plan_context:
        plan_section = (
            "\n\n## Build Plan (generated by agent before execution)\n"
            f"{plan_context}\n\n"
            "Evaluate whether the implementation follows this plan. Flag "
            "plan steps not implemented, deviations without justification, "
            "and incorrect implementations."
        )
        spec_context = (spec_context or "") + plan_section
    if spec_context:
        label = f"spec {spec_number}" if spec_number else "all specs"
        print(f"  Found spec context ({label})", file=sys.stderr)
    else:
        print("  No spec context found", file=sys.stderr)

    # Step 3: Challenger (Google/Gemini)
    print(f"Step 3/{total_steps}: Running challenger (Google)...", file=sys.stderr)
    _progress("challenger_start", {})
    challenger_output: dict = {}
    if credentials.get("google"):
        try:
            challenger_output = run_challenger(
                file_data, spec_context, models.google, credentials["google"]
            )
        except Exception as exc:
            print(f"  Challenger failed: {exc}", file=sys.stderr)
            challenger_output = {
                "issues": [],
                "summary": f"Challenger step failed: {exc}",
                "tests_file_content": "",
                "error": str(exc),
            }
    else:
        print("  Skipped — no Google API key", file=sys.stderr)
        challenger_output = {
            "issues": [],
            "summary": "Skipped — no Google API key",
            "tests_file_content": "",
        }

    # Check spec alignment: C = outside spec, D = missing from spec
    spec_alignment = challenger_output.get("spec_alignment", [])
    category_c_items = [item for item in spec_alignment if item.get("category") == "C"]
    category_d_items = [item for item in spec_alignment if item.get("category") == "D"]
    if category_c_items:
        challenger_output["category_c_items"] = category_c_items
    if category_d_items:
        challenger_output["category_d_items"] = category_d_items

    # If no issues found, short-circuit (but still check spec alignment)
    if not challenger_output.get("issues"):
        print("  No issues found — skipping author and arbiter steps", file=sys.stderr)
        report = generate_report(
            models, challenger_output, {}, None, [f["path"] for f in file_data]
        )
        report["tests_written"] = write_tests(challenger_output, project_root)
        report["spec_alignment"] = spec_alignment
        report["category_c_items"] = category_c_items
        report["category_d_items"] = category_d_items
        # Category C (outside spec) or D (missing spec items) → FAIL
        if category_c_items or category_d_items:
            report["verdict"] = "FAIL"
            if category_d_items:
                d_desc = "; ".join(i.get("description", "?")[:80] for i in category_d_items)
                report["summary"] = (report.get("summary", "") +
                    f" SPEC MISMATCH: {len(category_d_items)} Done When item(s) "
                    f"have no corresponding code: {d_desc}")
        write_report(report, project_root)
        return report

    # Steps 4+: Debate loop — Gemini ↔ Claude, up to MAX_DEBATE_ROUNDS
    # Each round: Claude rebuts → Gemini counter-rebuts
    # Issues Gemini concedes are resolved (author wins).
    # Issues still maintained after all rounds escalate to GPT arbiter.
    #
    # We accumulate all author responses across rounds so the report
    # has the final verdict for every issue, not just the last round's.
    all_author_responses: dict[str, dict] = {}  # issue_id -> response
    author_output: dict = {}
    counter_rebuttal_output: dict | None = None
    debate_history: list[dict] = []

    has_anthropic = bool(credentials.get("anthropic"))
    has_google = bool(credentials.get("google"))

    for round_num in range(MAX_DEBATE_ROUNDS):
        step = 4 + (round_num * 2)

        # Author rebuttal
        print(f"Step {step}/{total_steps}: Running author rebuttal "
              f"(round {round_num + 1}/{MAX_DEBATE_ROUNDS})...", file=sys.stderr)
        _progress("debate_round", {
            "round": round_num + 1,
            "max_rounds": MAX_DEBATE_ROUNDS,
            "phase": "claude_rebuttal",
            "issues_in_play": len(round_challenger.get("issues", [])) if round_num > 0 else len(challenger_output.get("issues", [])),
        })

        if not has_anthropic:
            print("  Skipped — no Anthropic API key", file=sys.stderr)
            author_output = {
                "responses": [], "accepted_count": 0, "rebutted_count": 0,
                "unresolved": [], "summary": "Skipped — no Anthropic API key",
            }
            break

        # Build challenger input for this round — filter to only maintained issues
        round_challenger = challenger_output
        if counter_rebuttal_output and counter_rebuttal_output.get("maintained_ids"):
            maintained = set(counter_rebuttal_output["maintained_ids"])
            round_challenger = {
                **challenger_output,
                "issues": [i for i in challenger_output["issues"]
                           if i.get("id") in maintained],
            }

        try:
            author_output = run_author_rebuttal(
                round_challenger, file_data, models.anthropic, credentials["anthropic"]
            )
        except Exception as exc:
            print(f"  Author rebuttal failed: {exc}", file=sys.stderr)
            author_output = {
                "responses": [], "accepted_count": 0, "rebutted_count": 0,
                "unresolved": [], "summary": f"Author step failed: {exc}",
                "error": str(exc),
            }
            break

        # Accumulate responses across rounds
        for resp in author_output.get("responses", []):
            all_author_responses[resp.get("issue_id", "")] = resp

        # If author accepted everything, no need for counter-rebuttal
        if not author_output.get("unresolved"):
            print("  Author accepted all issues — debate resolved", file=sys.stderr)
            break

        # Challenger counter-rebuttal
        print(f"Step {step + 1}/{total_steps}: Running challenger counter-rebuttal "
              f"(round {round_num + 1}/{MAX_DEBATE_ROUNDS})...", file=sys.stderr)
        _progress("debate_round", {
            "round": round_num + 1,
            "max_rounds": MAX_DEBATE_ROUNDS,
            "phase": "gemini_counter",
            "author_accepted": author_output.get("accepted_count", 0),
            "author_rebutted": author_output.get("rebutted_count", 0),
        })

        if not has_google:
            print("  Skipped — no Google API key", file=sys.stderr)
            break

        try:
            counter_rebuttal_output = run_counter_rebuttal(
                round_challenger, author_output, models.google,
                credentials["google"], round_num,
            )
        except Exception as exc:
            print(f"  Counter-rebuttal failed: {exc}", file=sys.stderr)
            break

        debate_history.append({
            "round": round_num + 1,
            "author_accepted": author_output.get("accepted_count", 0),
            "author_rebutted": author_output.get("rebutted_count", 0),
            "challenger_conceded": counter_rebuttal_output.get("conceded_count", 0),
            "challenger_maintained": counter_rebuttal_output.get("maintained_count", 0),
        })

        # If challenger conceded everything, debate resolved
        if not counter_rebuttal_output.get("maintained_ids"):
            print("  Challenger conceded all rebuttals — debate resolved",
                  file=sys.stderr)
            break

        print(f"  {counter_rebuttal_output['maintained_count']} issues still "
              f"disputed after round {round_num + 1}", file=sys.stderr)

        # Brief pause between debate rounds to avoid hammering APIs
        time.sleep(3)

    # Build merged author output with all responses across rounds
    merged_responses = list(all_author_responses.values())
    author_output = {
        "responses": merged_responses,
        "accepted_count": sum(1 for r in merged_responses if r.get("verdict") == "accept"),
        "rebutted_count": sum(1 for r in merged_responses if r.get("verdict") == "rebut"),
        "unresolved": [r["issue_id"] for r in merged_responses if r.get("verdict") == "rebut"],
        "summary": author_output.get("summary", ""),
    }

    # Determine which issues are still unresolved after debate
    # Start with author's rebutted issues
    unresolved = set(author_output.get("unresolved", []))
    # Remove issues the challenger conceded
    if counter_rebuttal_output:
        conceded = set(
            cr["issue_id"] for cr in counter_rebuttal_output.get("counter_rebuttals", [])
            if cr["verdict"] == "concede"
        )
        unresolved -= conceded

    # Arbiter (OpenAI/GPT) — only for issues that survived the debate
    arbiter_step = 4 + (min(len(debate_history), MAX_DEBATE_ROUNDS) * 2) + 1
    print(f"Step {arbiter_step}/{total_steps}: Running arbiter (OpenAI)...",
          file=sys.stderr)
    arbiter_output: dict | None = None

    if not unresolved:
        print("  No disputed issues after debate — skipping arbiter", file=sys.stderr)
        _progress("arbiter_skip", {"reason": "all_resolved"})
    elif not credentials.get("openai"):
        print("  Skipped — no OpenAI API key", file=sys.stderr)
    else:
        # Filter challenger/author outputs to only unresolved issues for arbiter
        arbiter_challenger = {
            **challenger_output,
            "issues": [i for i in challenger_output["issues"]
                       if i.get("id") in unresolved],
        }
        arbiter_author = {
            **author_output,
            "responses": [r for r in author_output.get("responses", [])
                          if r.get("issue_id") in unresolved],
        }
        _progress("arbiter_start", {"unresolved_count": len(unresolved)})
        try:
            arbiter_output = run_arbiter(
                arbiter_challenger, arbiter_author, models.openai,
                credentials["openai"],
            )
        except Exception as exc:
            print(f"  Arbiter failed: {exc}", file=sys.stderr)
            arbiter_output = {
                "rulings": [], "summary": f"Arbiter step failed: {exc}",
                "error": str(exc),
            }

    # Generate report
    print("Generating report...", file=sys.stderr)
    file_paths = [f["path"] for f in file_data]
    report = generate_report(
        models, challenger_output, author_output, arbiter_output, file_paths,
        counter_rebuttal=counter_rebuttal_output,
        debate_history=debate_history,
    )

    # Write tests
    tests_written = write_tests(challenger_output, project_root)
    report["tests_written"] = tests_written

    # Add spec alignment data
    report["spec_alignment"] = spec_alignment
    report["category_c_items"] = category_c_items
    report["category_d_items"] = category_d_items
    # Category D (missing spec items) → FAIL regardless of code quality
    if category_d_items and report.get("verdict") in ("PASS", "NEEDS_ATTENTION"):
        report["verdict"] = "FAIL"
        d_desc = "; ".join(i.get("description", "?")[:80] for i in category_d_items)
        report["summary"] = (report.get("summary", "") +
            f" SPEC MISMATCH: {len(category_d_items)} Done When item(s) "
            f"have no corresponding code: {d_desc}")
    # Category C (outside spec) → FAIL
    if category_c_items and report.get("verdict") == "PASS":
        report["verdict"] = "FAIL"

    # Write report files
    write_report(report, project_root)

    print(f"Pipeline complete — verdict: {report['verdict']}", file=sys.stderr)
    return report
