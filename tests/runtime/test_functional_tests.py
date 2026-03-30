"""Tests for runtime.functional_tests — Playwright test generation."""

import os
from unittest.mock import patch, MagicMock

import pytest


def test_should_run_playwright_with_html():
    """Frontend files in diff trigger Playwright."""
    from runtime.functional_tests import should_run_playwright

    with patch("runtime.functional_tests._get_changed_files",
               return_value={"dashboard/frontend/index.html", "lib/foo.py"}):
        assert should_run_playwright("/tmp/wt", "abc123", "main") is True


def test_should_run_playwright_with_js():
    """JS files trigger Playwright."""
    from runtime.functional_tests import should_run_playwright

    with patch("runtime.functional_tests._get_changed_files",
               return_value={"dashboard/frontend/app.js"}):
        assert should_run_playwright("/tmp/wt", "abc123", "main") is True


def test_should_run_playwright_with_css():
    """CSS files trigger Playwright."""
    from runtime.functional_tests import should_run_playwright

    with patch("runtime.functional_tests._get_changed_files",
               return_value={"styles.css", "lib/foo.py"}):
        assert should_run_playwright("/tmp/wt", "abc123", "main") is True


def test_should_run_playwright_python_only():
    """Python-only changes skip Playwright."""
    from runtime.functional_tests import should_run_playwright

    with patch("runtime.functional_tests._get_changed_files",
               return_value={"lib/foo.py", "tests/test_bar.py"}):
        assert should_run_playwright("/tmp/wt", "abc123", "main") is False


def test_should_run_playwright_empty_diff():
    """Empty diff skips Playwright."""
    from runtime.functional_tests import should_run_playwright

    with patch("runtime.functional_tests._get_changed_files",
               return_value=set()):
        assert should_run_playwright("/tmp/wt", "abc123", "main") is False


def test_build_playwright_prompt_includes_mission():
    """Prompt includes the goal sentence as mission."""
    from runtime.functional_tests import build_playwright_prompt

    spec = """# 022: Multi-Repo Dashboard

## Goal

Enable the dashboard to manage multiple repos simultaneously.

## Done When
- [ ] Project selector dropdown visible in header
- [x] Projects table exists in database
"""
    prompt = build_playwright_prompt(spec)
    assert "Enable the dashboard to manage multiple repos simultaneously." in prompt
    assert "Project selector dropdown visible in header" in prompt
    # Checked items should NOT appear in features to verify
    assert "Projects table exists in database" not in prompt


def test_build_playwright_prompt_no_goal():
    """Prompt handles missing Goal section gracefully."""
    from runtime.functional_tests import build_playwright_prompt

    spec = """# Some spec

## Done When
- [ ] Feature works
"""
    prompt = build_playwright_prompt(spec)
    assert "Verify the feature works." in prompt
    assert "Feature works" in prompt


def test_strip_code_fences_python():
    """Strips ```python ... ``` fences."""
    from runtime.functional_tests import _strip_code_fences

    raw = '```python\nimport pytest\n\ndef test_foo():\n    pass\n```'
    result = _strip_code_fences(raw)
    assert result == 'import pytest\n\ndef test_foo():\n    pass'
    assert "```" not in result


def test_strip_code_fences_bare():
    """Strips bare ``` fences."""
    from runtime.functional_tests import _strip_code_fences

    raw = '```\nsome code\n```'
    result = _strip_code_fences(raw)
    assert result == "some code"


def test_strip_code_fences_none():
    """No fences means no change."""
    from runtime.functional_tests import _strip_code_fences

    code = "import pytest\n\ndef test_foo():\n    pass"
    assert _strip_code_fences(code) == code


def test_generate_writes_test_file(tmp_path):
    """generate_playwright_test writes test file to worktree."""
    from runtime.functional_tests import generate_playwright_test

    spec_content = """# 022: Test

## Goal

Verify the dropdown works.

## Done When
- [ ] Dropdown visible
"""
    fake_response = "from playwright.sync_api import Page\n\ndef test_dropdown(page: Page):\n    pass"

    with patch("adversarial.credentials.load_credentials",
               return_value={"google": "fake-key", "anthropic": None, "openai": None}), \
         patch("adversarial.model_resolver.resolve_or_load",
               return_value=MagicMock(google="gemini-2.0-flash")), \
         patch("adversarial.challenger._call_gemini",
               return_value=fake_response):

        worktree = str(tmp_path / "worktree")
        os.makedirs(worktree)
        repo_root = str(tmp_path / "repo")
        os.makedirs(repo_root)

        result = generate_playwright_test("022", spec_content, worktree, repo_root)

        assert result.endswith("test_spec_022.py")
        assert os.path.exists(result)
        with open(result) as f:
            content = f.read()
        assert "def test_dropdown" in content


def test_generate_strips_fences_from_response(tmp_path):
    """generate_playwright_test strips code fences from Gemini response."""
    from runtime.functional_tests import generate_playwright_test

    spec_content = "## Goal\nTest.\n\n## Done When\n- [ ] Works\n"
    fenced = "```python\nimport pytest\ndef test_x(): pass\n```"

    with patch("adversarial.credentials.load_credentials",
               return_value={"google": "fake-key", "anthropic": None, "openai": None}), \
         patch("adversarial.model_resolver.resolve_or_load",
               return_value=MagicMock(google="gemini-2.0-flash")), \
         patch("adversarial.challenger._call_gemini",
               return_value=fenced):

        worktree = str(tmp_path / "wt")
        os.makedirs(worktree)
        repo_root = str(tmp_path / "repo")
        os.makedirs(repo_root)

        result = generate_playwright_test("099", spec_content, worktree, repo_root)
        with open(result) as f:
            content = f.read()
        assert "```" not in content
        assert "import pytest" in content
