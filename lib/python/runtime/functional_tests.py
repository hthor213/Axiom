"""Playwright functional test generation — Gemini writes browser tests.

After Claude builds code, Gemini writes a Playwright test to verify
the feature actually works from a user's perspective. The server
decides when to run Playwright based on file extensions in the diff
(deterministic, not LLM-driven).

Flow:
1. should_run_playwright() checks if diff contains frontend files
2. build_playwright_prompt() assembles prompt from spec content
3. generate_playwright_test() calls Gemini and writes test to worktree
"""

from __future__ import annotations

import os
import re
import sys

from .spec_parser import extract_goal, extract_done_when_items
from .review import _get_changed_files

FRONTEND_EXTENSIONS = (".html", ".js", ".css", ".jsx", ".tsx", ".vue", ".svelte")

PLAYWRIGHT_SYSTEM = (
    "You write pytest-playwright functional tests for web applications. "
    "Return a single Python file. No explanation, no markdown fences. "
    "Test user-observable behavior — what a person would see and click. "
    "Do NOT test internal APIs, database state, or implementation details."
)

PLAYWRIGHT_TEMPLATE = '''\
from playwright.sync_api import Page, expect


def test_mission_achieved(page: Page):
    page.goto("http://localhost:8014")
    # Verify the mission is achieved from a user\'s perspective
    ...
'''


def should_run_playwright(worktree_path: str, base_commit: str,
                          base_branch: str) -> bool:
    """Check if the diff contains frontend files that warrant Playwright tests.

    Pure deterministic check — looks at file extensions only.
    """
    base_ref = base_commit or base_branch
    changed = _get_changed_files(worktree_path, base_ref)
    return any(f.endswith(FRONTEND_EXTENSIONS) for f in changed)


def build_playwright_prompt(spec_content: str) -> str:
    """Assemble the Gemini prompt from spec content.

    Extracts mission (first sentence of Goal) and unchecked Done When
    items, then combines with the pytest-playwright template.
    """
    goal_sentence, _ = extract_goal(spec_content)
    done_when = extract_done_when_items(spec_content)
    unchecked = [item["text"] for item in done_when if not item["checked"]]

    mission_block = goal_sentence if goal_sentence else "Verify the feature works."
    features_block = "\n".join(f"- {item}" for item in unchecked) if unchecked else "- Feature works as described in the spec"

    return f"""You are writing a functional test for a web application using pytest-playwright.

## Mission
{mission_block}

## Features to Verify
{features_block}

## Test Target
URL: http://localhost:8014
Framework: pytest with playwright (pytest-playwright package)

## Template
```python
{PLAYWRIGHT_TEMPLATE}```

## Critical: Test BEHAVIOR, Not DOM

Your job is to verify that the feature **works end-to-end**, not just that HTML elements
exist. A dropdown that renders but shows "No projects" is a FAILURE. A button that
appears but does nothing on click is a FAILURE.

For each Done When item, test the OUTCOME a user would experience:
- BAD: `expect(locator).to_be_visible()` — only checks the element exists
- GOOD: click the dropdown, verify it has real options, select one, verify the page
  updates with that project's data

Test the happy path first: can a user actually accomplish the mission? If the UI
element exists but has no data, no options, or no effect — that is a functional failure.

Write small, focused assertions with descriptive failure messages so the developer
knows exactly what is broken. Use `expect(x).to_have_text(...)` or
`expect(x).to_have_count(...)` over bare `.to_be_visible()`.

Do NOT test internal APIs, database state, or implementation details.
Each test should map to a Done When item where possible.
Return a single Python file."""


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from Gemini's response."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```python or ```)
        text = re.sub(r"^```\w*\n?", "", text)
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text


def generate_playwright_test(spec_number: str, spec_content: str,
                             worktree_path: str, repo_root: str) -> str:
    """Call Gemini to write a Playwright test and save it to the worktree.

    Returns the path to the written test file.
    """
    # Build prompt
    prompt = build_playwright_prompt(spec_content)

    # Load credentials and resolve Gemini model
    lib_path = os.path.join(repo_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from adversarial.credentials import load_credentials
    from adversarial.model_resolver import resolve_or_load
    from adversarial.challenger import _call_gemini

    creds = load_credentials(repo_root)
    api_key = creds.get("google")
    if not api_key:
        raise RuntimeError("No Google API key — cannot generate Playwright test")

    models = resolve_or_load(creds, repo_root)

    # Call Gemini with test-writing system prompt
    print(f"  Calling Gemini to write Playwright test for spec {spec_number}...",
          file=sys.stderr)
    raw_response = _call_gemini(prompt, models.google, api_key,
                                system=PLAYWRIGHT_SYSTEM)
    test_code = _strip_code_fences(raw_response)

    # Write test file to worktree
    test_dir = os.path.join(worktree_path, "tests", "functional")
    os.makedirs(test_dir, exist_ok=True)

    # Copy conftest.py if it doesn't exist in worktree
    conftest_dest = os.path.join(test_dir, "conftest.py")
    if not os.path.exists(conftest_dest):
        conftest_src = os.path.join(repo_root, "tests", "functional", "conftest.py")
        if os.path.exists(conftest_src):
            with open(conftest_src) as f:
                conftest_content = f.read()
            with open(conftest_dest, "w") as f:
                f.write(conftest_content)

    # Write __init__.py if missing
    init_path = os.path.join(test_dir, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            pass

    test_path = os.path.join(test_dir, f"test_spec_{spec_number}.py")
    with open(test_path, "w") as f:
        f.write(test_code)

    print(f"  Playwright test written to {test_path}", file=sys.stderr)
    return test_path
