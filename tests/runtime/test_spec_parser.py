"""Tests for runtime.spec_parser — north star extraction from spec markdown."""

import pytest
from runtime.spec_parser import (
    extract_goal,
    extract_done_when_items,
    build_mission_criterion,
)

# ---------------------------------------------------------------------------
# Sample spec content for tests
# ---------------------------------------------------------------------------

SPEC_022 = """
# 022: Multi-Repo Dashboard — Project Selector and Session Isolation

**Status:** draft

## Goal

The dashboard (spec:015) currently manages a single repo. This spec adds a project selector so the developer can manage multiple repos from the same dashboard, with each repo getting its own isolated Claude Code sessions, task queues, worktrees, and adversarial reviews.

This is the difference between "a dashboard for one project" and "a control plane for all your projects."

## Architecture

Some architecture details here.

## Done When
- [ ] Projects table exists in PostgreSQL with CRUD endpoints
- [x] Dashboard header has a project selector dropdown
- [ ] Sync status is computed live
- [x] Cloud-only projects can be cloned to local
- [ ] All views are scoped to the selected project
"""

SPEC_NO_GOAL = """
# 099: Something

**Status:** draft

## Architecture

Just architecture, no goal.

## Done When
- [ ] Item one
- [ ] Item two
"""

SPEC_EMPTY = ""

SPEC_WITH_CODE_FENCE = """
# 022: Multi-Repo Dashboard

**Status:** draft

## Goal

Add a project selector to the dashboard. This enables multi-repo management.

## Architecture

Example vision template:
```markdown
## Goal
<!-- placeholder -->

## Done When
- [ ] Vision is written and committed
```

## Done When
- [ ] Real item one
- [ ] Real item two
- [x] Real item three
"""

SPEC_ALL_CHECKED = """
# 010: Harness

**Status:** done

## Goal

Add a deterministic execution layer. It prevents drift.

## Done When
- [x] State machine works
- [x] Scanner reads specs
- [x] Gate checks pass
"""


class TestExtractGoal:
    def test_extracts_first_sentence(self):
        first, full = extract_goal(SPEC_022)
        assert first == "The dashboard (spec:015) currently manages a single repo."
        assert "control plane for all your projects" in full

    def test_full_goal_includes_all_text(self):
        _, full = extract_goal(SPEC_022)
        assert "project selector" in full
        assert "Architecture" not in full  # stops at next ##

    def test_no_goal_section(self):
        first, full = extract_goal(SPEC_NO_GOAL)
        assert first == ""
        assert full == ""

    def test_empty_content(self):
        first, full = extract_goal(SPEC_EMPTY)
        assert first == ""
        assert full == ""

    def test_short_goal(self):
        first, full = extract_goal(SPEC_ALL_CHECKED)
        assert first == "Add a deterministic execution layer."
        assert "prevents drift" in full


class TestExtractDoneWhenItems:
    def test_extracts_all_items(self):
        items = extract_done_when_items(SPEC_022)
        assert len(items) == 5

    def test_checked_unchecked(self):
        items = extract_done_when_items(SPEC_022)
        unchecked = [i for i in items if not i["checked"]]
        checked = [i for i in items if i["checked"]]
        assert len(unchecked) == 3
        assert len(checked) == 2

    def test_text_content(self):
        items = extract_done_when_items(SPEC_022)
        assert items[0]["text"] == "Projects table exists in PostgreSQL with CRUD endpoints"
        assert items[0]["checked"] is False
        assert items[1]["text"] == "Dashboard header has a project selector dropdown"
        assert items[1]["checked"] is True

    def test_no_done_when(self):
        items = extract_done_when_items(SPEC_EMPTY)
        assert items == []

    def test_all_checked(self):
        items = extract_done_when_items(SPEC_ALL_CHECKED)
        assert all(i["checked"] for i in items)
        assert len(items) == 3

    def test_skips_code_fence_done_when(self):
        items = extract_done_when_items(SPEC_WITH_CODE_FENCE)
        assert len(items) == 3
        assert items[0]["text"] == "Real item one"
        assert items[2]["checked"] is True

    def test_goal_skips_code_fence(self):
        first, full = extract_goal(SPEC_WITH_CODE_FENCE)
        assert first == "Add a project selector to the dashboard."
        assert "placeholder" not in full


class TestBuildMissionCriterion:
    def test_basic(self):
        result = build_mission_criterion("Build a project selector.")
        assert result == "The spec goal is achieved: Build a project selector"

    def test_no_trailing_period(self):
        result = build_mission_criterion("Build a selector")
        assert result == "The spec goal is achieved: Build a selector"

    def test_empty(self):
        assert build_mission_criterion("") == ""
