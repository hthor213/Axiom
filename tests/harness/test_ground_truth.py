"""Tests for harness/ground_truth.py — spec-vs-DB comparison and bootstrap idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.ground_truth import compare_spec_vs_db, GroundTruthReport, SpecGroundTruth
from harness.scanner import SpecInfo, SpecReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec_file(specs_dir: Path, number: str, items: list[tuple[str, bool]]) -> Path:
    """Write a spec markdown file with Done When items. Returns path."""
    lines = [
        f"# Spec {number}",
        "",
        "**Status:** active",
        "",
        "## Done When",
        "",
    ]
    for text, checked in items:
        mark = "x" if checked else " "
        lines.append(f"- [{mark}] {text}")
    lines.append("")
    path = specs_dir / f"{number}-test.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _make_spec_info(path: Path, number: str, checked: int, total: int) -> SpecInfo:
    return SpecInfo(
        path=str(path),
        number=number,
        title=f"Spec {number}",
        status="active",
        band="foundation",
        done_when_total=total,
        done_when_checked=checked,
        done_when_automatable=0,
    )


def _make_spec_report(*spec_infos: SpecInfo) -> SpecReport:
    report = SpecReport(specs=list(spec_infos))
    return report


def _task(done_when_item: str, status: str) -> dict:
    return {"done_when_item": done_when_item, "status": status, "id": 1}


# ---------------------------------------------------------------------------
# compare_spec_vs_db — basic behaviour
# ---------------------------------------------------------------------------

class TestCompareSpecVsDb:

    def test_empty_db_all_items_untracked(self, tmp_path: Path) -> None:
        """Checked spec items are untracked when DB has no records."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [
            ("Item A", True),
            ("Item B", True),
            ("Item C", False),
        ])
        spec = _make_spec_info(path, "001", checked=2, total=3)
        report = compare_spec_vs_db(_make_spec_report(spec), {})

        gt = report.specs[0]
        assert set(gt.untracked_items) == {"Item A", "Item B"}

    def test_unchecked_items_never_untracked(self, tmp_path: Path) -> None:
        """Unchecked spec items never appear in untracked_items."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [
            ("Item A", False),
            ("Item B", False),
        ])
        spec = _make_spec_info(path, "001", checked=0, total=2)
        report = compare_spec_vs_db(_make_spec_report(spec), {})

        assert report.specs[0].untracked_items == []

    def test_passed_task_tracks_item(self, tmp_path: Path) -> None:
        """A passed DB task marks the item as tracked."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [("Item A", True)])
        spec = _make_spec_info(path, "001", checked=1, total=1)
        db = {"001": [_task("Item A", "passed")]}
        report = compare_spec_vs_db(_make_spec_report(spec), db)

        assert report.specs[0].untracked_items == []

    def test_full_spec_pass_tracks_all_items(self, tmp_path: Path) -> None:
        """A __full_spec__ passed task causes all items to be considered tracked."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [
            ("Item A", True),
            ("Item B", True),
        ])
        spec = _make_spec_info(path, "001", checked=2, total=2)
        db = {"001": [_task("__full_spec__", "passed")]}
        report = compare_spec_vs_db(_make_spec_report(spec), db)

        assert report.specs[0].untracked_items == []


# ---------------------------------------------------------------------------
# Bootstrap idempotency — running twice creates no duplicates
# ---------------------------------------------------------------------------

class TestBootstrapIdempotency:
    """Verify that compare_spec_vs_db sees imported records as 'tracked',
    so a second bootstrap run finds nothing new to import."""

    def test_imported_record_prevents_duplicate(self, tmp_path: Path) -> None:
        """An existing 'imported' task means the item is already tracked."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [("Feature A done", True)])
        spec = _make_spec_info(path, "001", checked=1, total=1)

        # Simulate first bootstrap run having already created an imported record
        db_after_first_run = {"001": [_task("Feature A done", "imported")]}

        report = compare_spec_vs_db(_make_spec_report(spec), db_after_first_run)

        # Second run: nothing to import
        assert report.specs[0].untracked_items == []
        assert not report.specs[0].has_mismatch

    def test_second_run_imports_nothing(self, tmp_path: Path) -> None:
        """Full scenario: first run detects 2 items; second run detects 0."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "026", [
            ("API endpoint exists", True),
            ("Health tab renders", True),
            ("Tests pass", False),
        ])
        spec = _make_spec_info(path, "026", checked=2, total=3)

        # --- First run ---
        report_first = compare_spec_vs_db(_make_spec_report(spec), {})
        assert set(report_first.specs[0].untracked_items) == {
            "API endpoint exists",
            "Health tab renders",
        }

        # Simulate what bootstrap writes to DB after first run
        db_after_first = {
            "026": [
                _task("API endpoint exists", "imported"),
                _task("Health tab renders", "imported"),
            ]
        }

        # --- Second run ---
        report_second = compare_spec_vs_db(_make_spec_report(spec), db_after_first)
        assert report_second.specs[0].untracked_items == []

    def test_mixed_statuses_only_missing_items_untracked(self, tmp_path: Path) -> None:
        """Only items with no DB record at all are untracked; status is irrelevant."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [
            ("Item A", True),
            ("Item B", True),
            ("Item C", True),
        ])
        spec = _make_spec_info(path, "001", checked=3, total=3)

        db = {
            "001": [
                _task("Item A", "imported"),   # already imported
                _task("Item B", "passed"),     # passed via pipeline
                # Item C has no record
            ]
        }
        report = compare_spec_vs_db(_make_spec_report(spec), db)

        # Only Item C is untracked
        assert report.specs[0].untracked_items == ["Item C"]

    def test_idempotent_across_multiple_specs(self, tmp_path: Path) -> None:
        """Idempotency holds when multiple specs are present."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        path_a = _make_spec_file(specs_dir, "001", [("Done A", True)])
        path_b = _make_spec_file(specs_dir, "002", [("Done B", True)])

        spec_a = _make_spec_info(path_a, "001", checked=1, total=1)
        spec_b = _make_spec_info(path_b, "002", checked=1, total=1)

        # Both already imported
        db = {
            "001": [_task("Done A", "imported")],
            "002": [_task("Done B", "imported")],
        }
        report = compare_spec_vs_db(_make_spec_report(spec_a, spec_b), db)

        for gt in report.specs:
            assert gt.untracked_items == [], f"Spec {gt.number} should have no untracked items"

    def test_imported_queued_by_bootstrap_is_tracked(self, tmp_path: Path) -> None:
        """Records created by bootstrap (queued_by='bootstrap') are treated as tracked."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        path = _make_spec_file(specs_dir, "001", [("Item X", True)])
        spec = _make_spec_info(path, "001", checked=1, total=1)

        # Task as bootstrap would create it (queued_by field is extra but status is what matters)
        db = {"001": [
            {"done_when_item": "Item X", "status": "imported", "id": 42, "queued_by": "bootstrap"}
        ]}
        report = compare_spec_vs_db(_make_spec_report(spec), db)
        assert report.specs[0].untracked_items == []


# ---------------------------------------------------------------------------
# GroundTruthReport aggregates
# ---------------------------------------------------------------------------

class TestGroundTruthReport:

    def test_mismatch_count(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        path_a = _make_spec_file(specs_dir, "001", [("Done", True)])
        path_b = _make_spec_file(specs_dir, "002", [("Also done", True)])

        spec_a = _make_spec_info(path_a, "001", checked=1, total=1)
        spec_b = _make_spec_info(path_b, "002", checked=1, total=1)

        # Only spec_a has a matching record
        db = {"001": [_task("Done", "imported")]}
        report = compare_spec_vs_db(_make_spec_report(spec_a, spec_b), db)

        assert report.mismatch_count == 1
        assert report.specs_with_mismatches[0].number == "002"

    def test_total_dashboard_aware(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        path = _make_spec_file(specs_dir, "001", [("X", True), ("Y", True)])
        spec = _make_spec_info(path, "001", checked=2, total=2)

        db = {"001": [
            _task("X", "passed"),
            _task("Y", "imported"),
        ]}
        report = compare_spec_vs_db(_make_spec_report(spec), db)

        assert report.total_dashboard_aware == 2
        assert report.specs[0].db_passed_count == 1
        assert report.specs[0].db_imported_count == 1
