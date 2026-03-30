"""Tests for harness/scanner.py — spec scanning, classification, and context building."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

from harness.scanner import (
    SpecInfo,
    SpecReport,
    SpecContext,
    classify_band,
    scan_specs,
    extract_invariants,
    extract_exclusions,
    build_spec_context,
    _count_automatable,
    _build_spec_info,
    _is_drift_candidate,
    _extract_section_items,
    _find_vision_spec,
)


# ---------------------------------------------------------------------------
# classify_band
# ---------------------------------------------------------------------------

class TestClassifyBand:
    """Tests for the band classification function."""

    @pytest.mark.parametrize("number,expected", [
        ("000", "vision"),
        ("001", "foundation"),
        ("049", "foundation"),
        ("050", "mvp"),
        ("099", "mvp"),
        ("100", "v1"),
        ("199", "v1"),
        ("200", "v2"),
        ("299", "v2"),
    ])
    def test_known_ranges(self, number: str, expected: str) -> None:
        """Numbers within defined ranges return the correct band."""
        assert classify_band(number) == expected

    @pytest.mark.parametrize("number", ["300", "500", "999"])
    def test_backlog_for_high_numbers(self, number: str) -> None:
        """Numbers above all defined ranges fall into backlog."""
        assert classify_band(number) == "backlog"

    @pytest.mark.parametrize("number", ["abc", "", None])
    def test_non_numeric_returns_backlog(self, number: str) -> None:
        """Non-numeric or empty input returns backlog."""
        assert classify_band(number) == "backlog"


# ---------------------------------------------------------------------------
# SpecInfo dataclass
# ---------------------------------------------------------------------------

class TestSpecInfo:
    """Tests for the SpecInfo dataclass properties."""

    def _make(self, **overrides) -> SpecInfo:
        defaults = dict(
            path="specs/001-foo.md", number="001", title="Foo",
            status="active", band="foundation",
            done_when_total=4, done_when_checked=2, done_when_automatable=3,
        )
        defaults.update(overrides)
        return SpecInfo(**defaults)

    def test_completion_ratio(self) -> None:
        assert self._make(done_when_total=4, done_when_checked=2).completion_ratio == 0.5

    def test_completion_ratio_zero_total(self) -> None:
        assert self._make(done_when_total=0, done_when_checked=0).completion_ratio == 0.0

    def test_is_active_true(self) -> None:
        assert self._make(status="active").is_active is True

    def test_is_active_false(self) -> None:
        assert self._make(status="draft").is_active is False


# ---------------------------------------------------------------------------
# SpecReport / SpecContext defaults
# ---------------------------------------------------------------------------

class TestDataclassDefaults:
    def test_spec_report_defaults(self) -> None:
        r = SpecReport()
        assert r.specs == []
        assert r.by_band == {}
        assert r.by_status == {}
        assert r.active_count == 0
        assert r.drift_candidates == []

    def test_spec_context_defaults(self) -> None:
        c = SpecContext(vision=None)
        assert c.active_specs == []
        assert c.invariants == []
        assert c.exclusions == []
        assert c.index_exists is False


# ---------------------------------------------------------------------------
# _count_automatable
# ---------------------------------------------------------------------------

class TestCountAutomatable:
    def test_file_exists_pattern(self) -> None:
        items = [{"text": "`README.md` file exists"}]
        assert _count_automatable(items) == 1

    def test_exists_at_pattern(self) -> None:
        items = [{"text": "exists at `lib/foo.py`"}]
        assert _count_automatable(items) == 1

    def test_spec_status_pattern(self) -> None:
        items = [{"text": "spec:001 status is active"}]
        assert _count_automatable(items) == 1

    def test_grep_pattern(self) -> None:
        items = [{"text": "`file.py` contains extract_done_when"}]
        assert _count_automatable(items) == 1

    def test_command_pattern(self) -> None:
        items = [{"text": "`pytest tests/` runs cleanly"}]
        assert _count_automatable(items) == 1

    def test_non_automatable(self) -> None:
        items = [{"text": "All stakeholders agree on direction"}]
        assert _count_automatable(items) == 0

    def test_empty_list(self) -> None:
        assert _count_automatable([]) == 0


# ---------------------------------------------------------------------------
# _is_drift_candidate
# ---------------------------------------------------------------------------

class TestIsDriftCandidate:
    def _make(self, **kw) -> SpecInfo:
        defaults = dict(
            path="x", number="001", title="T", status="active",
            band="foundation", done_when_total=2, done_when_checked=0,
            done_when_automatable=1,
        )
        defaults.update(kw)
        return SpecInfo(**defaults)

    def test_active_zero_items(self) -> None:
        s = self._make(done_when_total=0)
        assert _is_drift_candidate(s) is True

    def test_active_all_checked(self) -> None:
        s = self._make(done_when_total=3, done_when_checked=3, done_when_automatable=2)
        assert _is_drift_candidate(s) is True

    def test_draft_with_checked(self) -> None:
        s = self._make(status="draft", done_when_checked=1)
        assert _is_drift_candidate(s) is True

    def test_active_normal(self) -> None:
        s = self._make(done_when_total=3, done_when_checked=1, done_when_automatable=2)
        assert _is_drift_candidate(s) is False

    def test_done_spec_not_drift(self) -> None:
        s = self._make(status="done", done_when_checked=2)
        assert _is_drift_candidate(s) is False


# ---------------------------------------------------------------------------
# scan_specs
# ---------------------------------------------------------------------------

class TestScanSpecs:
    def test_happy_path(self, tmp_project: Path) -> None:
        report = scan_specs(str(tmp_project / "specs"))
        assert len(report.specs) == 4
        assert report.active_count == 2  # 000 and 001

    def test_empty_dir(self, tmp_project_empty: Path) -> None:
        report = scan_specs(str(tmp_project_empty / "specs"))
        assert report.specs == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        report = scan_specs(str(tmp_path / "no_such_dir"))
        assert report.specs == []

    def test_by_band_keys(self, tmp_project: Path) -> None:
        report = scan_specs(str(tmp_project / "specs"))
        assert "vision" in report.by_band
        assert "foundation" in report.by_band

    def test_by_status_keys(self, tmp_project: Path) -> None:
        report = scan_specs(str(tmp_project / "specs"))
        assert "active" in report.by_status
        assert "draft" in report.by_status
        assert "done" in report.by_status

    def test_non_md_files_ignored(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "notes.txt").write_text("not a spec", encoding="utf-8")
        report = scan_specs(str(specs_dir))
        assert report.specs == []


# ---------------------------------------------------------------------------
# _extract_section_items / extract_invariants / extract_exclusions
# ---------------------------------------------------------------------------

class TestSectionExtraction:
    def _write_vision(self, tmp_path: Path, extra_sections: str = "") -> Path:
        content = (
            "# Vision\n\n**Status:** active\n\n"
            "## Invariants\n\n"
            "- All code must be typed\n"
            "- No external dependencies\n\n"
            "## Exclusions\n\n"
            "- No GUI support\n"
            "- No Windows-specific code\n\n"
            f"{extra_sections}"
        )
        p = tmp_path / "000-vision.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_extract_invariants(self, tmp_path: Path) -> None:
        p = self._write_vision(tmp_path)
        items = extract_invariants(str(p))
        assert items == ["All code must be typed", "No external dependencies"]

    def test_extract_exclusions(self, tmp_path: Path) -> None:
        p = self._write_vision(tmp_path)
        items = extract_exclusions(str(p))
        assert items == ["No GUI support", "No Windows-specific code"]

    def test_extract_invariants_missing_file(self) -> None:
        assert extract_invariants("/nonexistent/path.md") == []

    def test_extract_exclusions_non_goals_variant(self, tmp_path: Path) -> None:
        content = "# V\n\n## Non-Goals\n\n- No cloud deploy\n"
        p = tmp_path / "000-vision.md"
        p.write_text(content, encoding="utf-8")
        assert extract_exclusions(str(p)) == ["No cloud deploy"]

    def test_section_stops_at_next_heading(self, tmp_path: Path) -> None:
        p = self._write_vision(tmp_path, extra_sections="## Another\n\n- extra\n")
        items = extract_invariants(str(p))
        assert "extra" not in items

    def test_checklist_bullets_parsed(self, tmp_path: Path) -> None:
        content = "# V\n\n## Invariants\n\n- [x] Checked item\n- [ ] Unchecked item\n"
        p = tmp_path / "vision.md"
        p.write_text(content, encoding="utf-8")
        items = _extract_section_items(str(p), "Invariants")
        assert items == ["Checked item", "Unchecked item"]


# ---------------------------------------------------------------------------
# _find_vision_spec
# ---------------------------------------------------------------------------

class TestFindVisionSpec:
    def test_found(self, tmp_project: Path) -> None:
        result = _find_vision_spec(str(tmp_project / "specs"))
        assert result is not None
        assert "000-vision.md" in result

    def test_not_found(self, tmp_project_empty: Path) -> None:
        assert _find_vision_spec(str(tmp_project_empty / "specs")) is None

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert _find_vision_spec(str(tmp_path / "nope")) is None


# ---------------------------------------------------------------------------
# build_spec_context
# ---------------------------------------------------------------------------

class TestBuildSpecContext:
    def test_happy_path(self, tmp_project: Path) -> None:
        ctx = build_spec_context(str(tmp_project))
        assert ctx.vision is not None
        assert ctx.vision.number == "000"
        assert len(ctx.active_specs) == 2

    def test_empty_project(self, tmp_project_empty: Path) -> None:
        ctx = build_spec_context(str(tmp_project_empty))
        assert ctx.vision is None
        assert ctx.active_specs == []
        assert ctx.invariants == []
        assert ctx.exclusions == []

    def test_index_exists_flag(self, tmp_project: Path) -> None:
        (tmp_project / "specs" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
        ctx = build_spec_context(str(tmp_project))
        assert ctx.index_exists is True

    def test_no_index(self, tmp_project: Path) -> None:
        ctx = build_spec_context(str(tmp_project))
        assert ctx.index_exists is False

    def test_minimal_project(self, tmp_project_minimal: Path) -> None:
        ctx = build_spec_context(str(tmp_project_minimal))
        assert ctx.vision is not None
        assert len(ctx.active_specs) == 1
