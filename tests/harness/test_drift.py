"""Tests for harness.drift — deterministic drift signal detection."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

import pytest

from lib.python.harness.drift import (
    DriftItem,
    DriftReport,
    _extract_referenced_paths,
    check_alignment,
    check_done_regressions,
    check_stale_active_specs,
    check_uncovered_directories,
)
from lib.python.harness.scanner import SpecInfo, build_spec_context


# ---------------------------------------------------------------------------
# DriftItem / DriftReport dataclass tests
# ---------------------------------------------------------------------------


def test_drift_item_construction() -> None:
    """DriftItem stores all four fields."""
    item = DriftItem(
        type="stale_active_spec",
        description="old spec",
        spec_ref="001",
        severity="warning",
    )
    assert item.type == "stale_active_spec"
    assert item.severity == "warning"
    assert item.spec_ref == "001"


def test_drift_report_clean_when_empty() -> None:
    """A fresh DriftReport with no items is clean."""
    report = DriftReport()
    assert report.clean is True
    assert report.summary == "No drift detected."


def test_drift_report_summary_with_items() -> None:
    """Summary aggregates severities correctly."""
    report = DriftReport(items=[
        DriftItem(type="a", description="x", spec_ref="1", severity="error"),
        DriftItem(type="b", description="y", spec_ref="2", severity="warning"),
        DriftItem(type="c", description="z", spec_ref="3", severity="error"),
    ])
    assert report.clean is False
    assert "3 drift signal(s)" in report.summary
    assert "2 error" in report.summary
    assert "1 warning" in report.summary


# ---------------------------------------------------------------------------
# check_stale_active_specs
# ---------------------------------------------------------------------------


def test_stale_active_specs_detects_old_file(tmp_project: Path) -> None:
    """A spec file modified long ago should be flagged stale."""
    spec_path = tmp_project / "specs" / "001-session-harness.md"
    # Set mtime to 30 days ago
    old_time = time.time() - 30 * 86400
    os.utime(spec_path, (old_time, old_time))

    spec_info = SpecInfo(
        number="001",
        title="session-harness",
        status="active",
        path=str(spec_path),
        band="foundation",
        done_when_total=4,
        done_when_checked=0,
        done_when_automatable=2,
    )
    items = check_stale_active_specs(str(tmp_project), [spec_info], stale_days=7)
    assert len(items) == 1
    assert items[0].type == "stale_active_spec"
    assert items[0].severity == "warning"
    assert "30 days" in items[0].description


def test_stale_active_specs_ignores_fresh_file(tmp_project: Path) -> None:
    """A recently modified spec should not be flagged."""
    spec_path = tmp_project / "specs" / "001-session-harness.md"
    spec_info = SpecInfo(
        number="001",
        title="session-harness",
        status="active",
        path=str(spec_path),
        band="foundation",
        done_when_total=4,
        done_when_checked=0,
        done_when_automatable=2,
    )
    items = check_stale_active_specs(str(tmp_project), [spec_info], stale_days=7)
    assert items == []


def test_stale_active_specs_missing_file(tmp_path: Path) -> None:
    """A SpecInfo pointing to a non-existent file should be silently skipped."""
    spec_info = SpecInfo(
        number="999",
        title="ghost",
        status="active",
        path=str(tmp_path / "specs" / "999-ghost.md"),
        band="mvp",
        done_when_total=0,
        done_when_checked=0,
        done_when_automatable=0,
    )
    items = check_stale_active_specs(str(tmp_path), [spec_info], stale_days=1)
    assert items == []


def test_stale_active_specs_empty_list(tmp_project: Path) -> None:
    """An empty active-specs list produces no items."""
    assert check_stale_active_specs(str(tmp_project), []) == []


# ---------------------------------------------------------------------------
# check_done_regressions
# ---------------------------------------------------------------------------


def test_done_regressions_on_passing_spec(tmp_project: Path) -> None:
    """A done spec whose file_exists checks still pass should produce no items."""
    spec_path = tmp_project / "specs" / "003-validation-tiers.md"
    spec_info = SpecInfo(
        number="003",
        title="validation-tiers",
        status="done",
        path=str(spec_path),
        band="foundation",
        done_when_total=2,
        done_when_checked=2,
        done_when_automatable=1,
    )
    items = check_done_regressions(str(tmp_project), [spec_info])
    # gates.py exists in tmp_project, so the file_exists check should pass
    assert all(i.type != "done_regression" or "gates.py" not in i.description for i in items)


def test_done_regressions_detects_missing_file(tmp_project: Path) -> None:
    """If a done spec references a file that was deleted, flag a regression."""
    # Remove gates.py to break the done check
    gates_path = tmp_project / "lib" / "python" / "harness" / "gates.py"
    gates_path.unlink()

    spec_path = tmp_project / "specs" / "003-validation-tiers.md"
    spec_info = SpecInfo(
        number="003",
        title="validation-tiers",
        status="done",
        path=str(spec_path),
        band="foundation",
        done_when_total=2,
        done_when_checked=2,
        done_when_automatable=1,
    )
    items = check_done_regressions(str(tmp_project), [spec_info])
    regression_items = [i for i in items if i.type == "done_regression"]
    assert len(regression_items) >= 1
    assert regression_items[0].severity == "error"
    assert "003" in regression_items[0].spec_ref


def test_done_regressions_missing_spec_file(tmp_path: Path) -> None:
    """A SpecInfo pointing to a missing file is silently skipped."""
    spec_info = SpecInfo(
        number="999",
        title="gone",
        status="done",
        path=str(tmp_path / "specs" / "999-gone.md"),
        band="mvp",
        done_when_total=0,
        done_when_checked=0,
        done_when_automatable=0,
    )
    assert check_done_regressions(str(tmp_path), [spec_info]) == []


def test_done_regressions_empty_list(tmp_project: Path) -> None:
    """No done specs means no regressions."""
    assert check_done_regressions(str(tmp_project), []) == []


# ---------------------------------------------------------------------------
# _extract_referenced_paths
# ---------------------------------------------------------------------------


def test_extract_referenced_paths(tmp_project: Path) -> None:
    """Paths wrapped in backticks inside Done When items are extracted."""
    spec_path = tmp_project / "specs" / "001-session-harness.md"
    spec_info = SpecInfo(
        number="001",
        title="session-harness",
        status="active",
        path=str(spec_path),
        band="foundation",
        done_when_total=4,
        done_when_checked=0,
        done_when_automatable=2,
    )
    refs = _extract_referenced_paths([spec_info])
    assert "lib" in refs


def test_extract_referenced_paths_empty() -> None:
    """An empty spec list returns an empty set."""
    assert _extract_referenced_paths([]) == set()


def test_extract_referenced_paths_missing_file(tmp_path: Path) -> None:
    """Non-existent spec files are skipped gracefully."""
    spec_info = SpecInfo(
        number="999",
        title="ghost",
        status="active",
        path=str(tmp_path / "nonexistent.md"),
        band="mvp",
        done_when_total=0,
        done_when_checked=0,
        done_when_automatable=0,
    )
    assert _extract_referenced_paths([spec_info]) == set()


# ---------------------------------------------------------------------------
# check_uncovered_directories
# ---------------------------------------------------------------------------


def test_uncovered_directories_flags_unreferenced(tmp_project: Path) -> None:
    """A key directory that exists but isn't in any spec should be flagged."""
    # Create an 'api/' directory that no spec references
    (tmp_project / "api").mkdir()
    ctx = build_spec_context(str(tmp_project))
    items = check_uncovered_directories(str(tmp_project), ctx)
    uncovered_names = [i.description for i in items]
    assert any("api/" in d for d in uncovered_names)
    assert all(i.severity == "info" for i in items)
    assert all(i.type == "uncovered_directory" for i in items)


def test_uncovered_directories_ignores_nonkey(tmp_project: Path) -> None:
    """A directory whose name isn't in _KEY_DIRS shouldn't appear."""
    (tmp_project / "random_stuff").mkdir()
    ctx = build_spec_context(str(tmp_project))
    items = check_uncovered_directories(str(tmp_project), ctx)
    assert all("random_stuff" not in i.description for i in items)


def test_uncovered_directories_covered_dir_not_flagged(tmp_project: Path) -> None:
    """The 'lib' directory is referenced by specs and should not be flagged."""
    ctx = build_spec_context(str(tmp_project))
    items = check_uncovered_directories(str(tmp_project), ctx)
    assert all("'lib/'" not in i.description for i in items)


def test_uncovered_directories_empty_project(tmp_project_empty: Path) -> None:
    """An empty project with no key dirs produces no uncovered items."""
    ctx = build_spec_context(str(tmp_project_empty))
    items = check_uncovered_directories(str(tmp_project_empty), ctx)
    assert items == []


# ---------------------------------------------------------------------------
# check_alignment (integration)
# ---------------------------------------------------------------------------


def test_check_alignment_returns_report(tmp_project: Path) -> None:
    """check_alignment returns a DriftReport with expected structure."""
    report = check_alignment(str(tmp_project))
    assert isinstance(report, DriftReport)
    assert isinstance(report.items, list)
    # All items are DriftItem instances
    for item in report.items:
        assert isinstance(item, DriftItem)
        assert item.severity in ("info", "warning", "error")


def test_check_alignment_with_prebuilt_context(tmp_project: Path) -> None:
    """check_alignment accepts an optional pre-built SpecContext."""
    ctx = build_spec_context(str(tmp_project))
    report = check_alignment(str(tmp_project), spec_context=ctx)
    assert isinstance(report, DriftReport)


def test_check_alignment_empty_project(tmp_project_empty: Path) -> None:
    """An empty project should produce a clean or near-clean report."""
    report = check_alignment(str(tmp_project_empty))
    assert isinstance(report, DriftReport)
    # No specs means no stale/regression items
    stale = [i for i in report.items if i.type == "stale_active_spec"]
    regressions = [i for i in report.items if i.type == "done_regression"]
    assert stale == []
    assert regressions == []


def test_check_alignment_detects_stale_and_uncovered(tmp_project: Path) -> None:
    """Integration: stale spec + uncovered dir both appear in one report."""
    # Make spec 000 stale
    spec_path = tmp_project / "specs" / "000-vision.md"
    old_time = time.time() - 15 * 86400
    os.utime(spec_path, (old_time, old_time))

    # Create uncovered key directory
    (tmp_project / "deploy").mkdir()

    report = check_alignment(str(tmp_project))
    types = {i.type for i in report.items}
    assert "stale_active_spec" in types
    assert "uncovered_directory" in types
    assert not report.clean
