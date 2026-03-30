"""Tests for harness/session.py — parsing, context assembly, and priority resolution."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

import pytest

from harness.session import (
    NextAction,
    SessionContext,
    _classify_priority,
    _extract_next_items_from_session,
    _extract_spec_ref,
    _parse_current_tasks,
    parse_backlog,
    parse_last_session,
    read_session_context,
    resolve_next_action,
)
from harness.scanner import SpecContext, SpecInfo


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclassDefaults:
    """Verify default construction of dataclasses."""

    def test_session_context_defaults(self) -> None:
        ctx = SessionContext()
        assert ctx.last_session == {}
        assert ctx.current_tasks == {}
        assert ctx.backlog_items == []
        assert ctx.done_items == []
        assert ctx.spec_context.vision is None

    def test_next_action_defaults(self) -> None:
        na = NextAction()
        assert na.source == "none"
        assert na.description == ""
        assert na.spec_ref is None
        assert na.needs_spec is False
        assert na.reasoning == ""


# ---------------------------------------------------------------------------
# parse_last_session
# ---------------------------------------------------------------------------


class TestParseLastSession:
    """Tests for LAST_SESSION.md parsing."""

    def test_happy_path(self, tmp_project: Path) -> None:
        result = parse_last_session(str(tmp_project / "LAST_SESSION.md"))
        assert "_raw" in result
        assert "date" in result
        assert "next" in result
        # Next section has bullet items
        assert isinstance(result["next"], list)
        assert len(result["next"]) == 2

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = parse_last_session(str(tmp_path / "NONEXISTENT.md"))
        assert result == {}
        assert "_raw" not in result

    def test_prose_section(self, tmp_path: Path) -> None:
        md = "# Session\n\n## Focus\nDoing important work.\n"
        p = tmp_path / "session.md"
        p.write_text(md, encoding="utf-8")
        result = parse_last_session(str(p))
        assert result["focus"] == "Doing important work."

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.md"
        p.write_text("", encoding="utf-8")
        result = parse_last_session(str(p))
        assert result == {"_raw": ""}

    def test_mixed_section(self, tmp_path: Path) -> None:
        md = "## Mixed\nSome prose\n- bullet one\n- bullet two\n"
        p = tmp_path / "mixed.md"
        p.write_text(md, encoding="utf-8")
        result = parse_last_session(str(p))
        assert "mixed" in result
        assert "mixed_items" in result
        assert result["mixed_items"] == ["bullet one", "bullet two"]

    def test_checkbox_bullets_stripped(self, tmp_path: Path) -> None:
        md = "## Tasks\n- [x] Done thing\n- [ ] Open thing\n"
        p = tmp_path / "cb.md"
        p.write_text(md, encoding="utf-8")
        result = parse_last_session(str(p))
        assert result["tasks"] == ["Done thing", "Open thing"]


# ---------------------------------------------------------------------------
# _extract_next_items_from_session
# ---------------------------------------------------------------------------


class TestExtractNextItems:
    """Tests for extracting next-action items from parsed session dict."""

    def test_extracts_from_next_key(self) -> None:
        session: Dict[str, object] = {"next": ["Do A", "Do B"]}
        assert _extract_next_items_from_session(session) == ["Do A", "Do B"]

    def test_extracts_from_next_session_should_start_with(self) -> None:
        session: Dict[str, object] = {
            "next session should start with": "Write tests"
        }
        items = _extract_next_items_from_session(session)
        assert items == ["Write tests"]

    def test_skips_private_keys(self) -> None:
        session: Dict[str, object] = {"_raw": "next stuff", "other": "val"}
        assert _extract_next_items_from_session(session) == []

    def test_empty_session(self) -> None:
        assert _extract_next_items_from_session({}) == []

    def test_multiline_prose(self) -> None:
        session: Dict[str, object] = {"next": "Line one\nLine two"}
        items = _extract_next_items_from_session(session)
        assert items == ["Line one", "Line two"]


# ---------------------------------------------------------------------------
# parse_backlog
# ---------------------------------------------------------------------------


class TestParseBacklog:
    """Tests for BACKLOG.md parsing."""

    def test_happy_path(self, tmp_project: Path) -> None:
        items = parse_backlog(str(tmp_project / "BACKLOG.md"))
        assert len(items) > 0
        # "Priorities" section maps to P1
        priorities_items = [i for i in items if i["section"] == "Priorities"]
        assert all(i["priority"] == "P1" for i in priorities_items)
        # "Icebox" maps to P3
        icebox_items = [i for i in items if i["section"] == "Icebox"]
        assert all(i["priority"] == "P3" for i in icebox_items)

    def test_missing_file(self, tmp_path: Path) -> None:
        assert parse_backlog(str(tmp_path / "nope.md")) == []

    def test_explicit_priority_in_heading(self, tmp_path: Path) -> None:
        md = "# Backlog\n\n## P0 Critical Stuff\n- Fix prod\n\n## P2 Nice to have\n- Polish\n"
        p = tmp_path / "bl.md"
        p.write_text(md, encoding="utf-8")
        items = parse_backlog(str(p))
        assert items[0]["priority"] == "P0"
        assert items[1]["priority"] == "P2"

    def test_no_sections(self, tmp_path: Path) -> None:
        p = tmp_path / "bl.md"
        p.write_text("Just plain text, no headings.\n", encoding="utf-8")
        assert parse_backlog(str(p)) == []

    def test_checkbox_items(self, tmp_path: Path) -> None:
        md = "## P1 Tasks\n- [ ] Open item\n- [x] Closed item\n"
        p = tmp_path / "bl.md"
        p.write_text(md, encoding="utf-8")
        items = parse_backlog(str(p))
        assert len(items) == 2
        assert items[0]["text"] == "Open item"
        assert items[1]["text"] == "Closed item"


# ---------------------------------------------------------------------------
# _classify_priority
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    """Tests for heading-to-priority mapping."""

    @pytest.mark.parametrize("heading,expected", [
        ("P0 — On Fire", "P0"),
        ("P1 items", "P1"),
        ("Urgent bugs", "P0"),
        ("Low priority", "P3"),
        ("Icebox", "P3"),
        ("Someday/maybe", "P3"),
        ("Random Heading", "P2"),
    ])
    def test_classification(self, heading: str, expected: str) -> None:
        assert _classify_priority(heading) == expected


# ---------------------------------------------------------------------------
# _parse_current_tasks
# ---------------------------------------------------------------------------


class TestParseCurrentTasks:
    """Tests for CURRENT_TASKS.md parsing."""

    def test_happy_path(self, tmp_project: Path) -> None:
        result = _parse_current_tasks(str(tmp_project / "CURRENT_TASKS.md"))
        assert len(result["active"]) == 2
        assert len(result["completed"]) == 2
        assert "Finish spec:001 Done When automation" in result["active"]

    def test_missing_file(self, tmp_path: Path) -> None:
        result = _parse_current_tasks(str(tmp_path / "NONE.md"))
        assert result == {"active": [], "completed": []}

    def test_alternate_headings(self, tmp_path: Path) -> None:
        md = "## In Progress\n- Task A\n\n## Done\n- Task B\n"
        p = tmp_path / "tasks.md"
        p.write_text(md, encoding="utf-8")
        result = _parse_current_tasks(str(p))
        assert result["active"] == ["Task A"]
        assert result["completed"] == ["Task B"]


# ---------------------------------------------------------------------------
# _extract_spec_ref
# ---------------------------------------------------------------------------


class TestExtractSpecRef:
    """Tests for spec reference extraction."""

    @pytest.mark.parametrize("text,expected", [
        ("Work on spec:001 stuff", "001"),
        ("See spec 002 for details", "002"),
        ("Implement 003-some-slug feature", "003"),
        ("No spec here", None),
        ("Random 42 number", None),
    ])
    def test_extraction(self, text: str, expected: str | None) -> None:
        assert _extract_spec_ref(text) == expected


# ---------------------------------------------------------------------------
# resolve_next_action — priority ladder
# ---------------------------------------------------------------------------


class TestResolveNextAction:
    """Tests for priority resolution across all tiers."""

    def test_last_session_wins(self) -> None:
        ctx = SessionContext(
            last_session={"next": ["Write tests"]},
            current_tasks={"active": ["Other task"]},
            backlog_items=[{"priority": "P0", "text": "Fix it", "section": "P0"}],
        )
        action = resolve_next_action(ctx)
        assert action.source == "last_session"
        assert "Write tests" in action.description

    def test_current_tasks_when_no_next(self) -> None:
        ctx = SessionContext(
            last_session={"focus": "Something"},
            current_tasks={"active": ["Implement feature"]},
        )
        action = resolve_next_action(ctx)
        assert action.source == "current_tasks"
        assert action.description == "Implement feature"

    def test_backlog_p0(self) -> None:
        ctx = SessionContext(
            backlog_items=[{"priority": "P0", "text": "Critical fix", "section": "P0"}],
        )
        action = resolve_next_action(ctx)
        assert action.source == "backlog_p0"

    def test_backlog_lower_tier(self) -> None:
        ctx = SessionContext(
            backlog_items=[{"priority": "P2", "text": "Nice to have", "section": "Med"}],
        )
        action = resolve_next_action(ctx)
        assert action.source == "backlog"
        assert "P2" in action.reasoning

    def test_active_spec_fallback(self) -> None:
        spec = SpecInfo(
            path="/fake/001-test.md", number="001",
            title="Test Spec", status="active",
            band="foundation", done_when_total=0,
            done_when_checked=0, done_when_automatable=0,
        )
        spec_ctx = SpecContext(vision=None, active_specs=[spec])
        ctx = SessionContext(spec_context=spec_ctx)
        action = resolve_next_action(ctx)
        assert action.source == "active_spec"
        assert action.spec_ref == "001"
        assert action.needs_spec is True

    def test_no_action_fallback(self) -> None:
        ctx = SessionContext()
        action = resolve_next_action(ctx)
        assert action.source == "none"
        assert "No actionable items" in action.description

    def test_spec_ref_propagated(self) -> None:
        ctx = SessionContext(
            last_session={"next": ["Continue spec:002 work"]},
        )
        action = resolve_next_action(ctx)
        assert action.spec_ref == "002"
        assert action.needs_spec is True

    def test_p1_before_p2(self) -> None:
        ctx = SessionContext(
            backlog_items=[
                {"priority": "P2", "text": "Low", "section": "Med"},
                {"priority": "P1", "text": "High", "section": "High"},
            ],
        )
        action = resolve_next_action(ctx)
        assert action.description == "High"


# ---------------------------------------------------------------------------
# read_session_context (integration-ish, with mocked git/spec)
# ---------------------------------------------------------------------------


class TestReadSessionContext:
    """Tests for the top-level context assembly function."""

    def test_assembles_from_tmp_project(self, tmp_project: Path) -> None:
        with patch("harness.session.gather_status") as mock_git, \
             patch("harness.session.build_spec_context") as mock_spec:
            from harness.git_ops import GitStatus
            mock_git.return_value = GitStatus()
            mock_spec.return_value = SpecContext(vision=None)

            ctx = read_session_context(str(tmp_project))

        assert "_raw" in ctx.last_session
        assert len(ctx.current_tasks["active"]) == 2
        assert len(ctx.done_items) == 2
        assert len(ctx.backlog_items) > 0

    def test_empty_project_graceful(self, tmp_project_empty: Path) -> None:
        with patch("harness.session.gather_status") as mock_git, \
             patch("harness.session.build_spec_context") as mock_spec:
            from harness.git_ops import GitStatus
            mock_git.return_value = GitStatus()
            mock_spec.return_value = SpecContext(vision=None)

            ctx = read_session_context(str(tmp_project_empty))

        assert ctx.last_session == {}
        assert ctx.current_tasks == {"active": [], "completed": []}
        assert ctx.backlog_items == []
        assert ctx.done_items == []
