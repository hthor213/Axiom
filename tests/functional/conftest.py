"""Shared Playwright fixtures for functional tests.

pytest-playwright provides the `page` fixture automatically.
These fixtures configure browser launch args for headless Docker execution.
"""

import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Launch args for Chromium inside Docker (runs as root)."""
    return {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}


@pytest.fixture(scope="session")
def browser_context_args():
    """Browser context defaults."""
    return {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }
