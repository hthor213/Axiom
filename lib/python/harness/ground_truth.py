"""Ground truth comparison — spec-file state vs dashboard task records.

Compares what the spec markdown files say is done (checked items)
against what the dashboard database has tracked (tasks/results).
Produces a GroundTruthReport showing mismatches per spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .scanner import SpecInfo, SpecReport


@dataclass
class SpecGroundTruth:
    """Ground truth for a single spec — spec file vs dashboard."""

    number: str
    title: str
    status: str
    band: str

    # From spec file (source of truth)
    spec_total: int = 0
    spec_checked: int = 0
    spec_items: List[dict] = field(default_factory=list)  # [{text, checked}]

    # From dashboard DB
    db_task_count: int = 0
    db_passed_count: int = 0
    db_imported_count: int = 0

    # Computed
    untracked_items: List[str] = field(default_factory=list)  # checked in spec, no DB record

    @property
    def spec_ratio(self) -> float:
        if self.spec_total == 0:
            return 0.0
        return self.spec_checked / self.spec_total

    @property
    def has_mismatch(self) -> bool:
        """True when spec says items are done but dashboard doesn't know."""
        return len(self.untracked_items) > 0

    @property
    def dashboard_aware(self) -> int:
        """Total items the dashboard knows about (passed + imported)."""
        return self.db_passed_count + self.db_imported_count


@dataclass
class GroundTruthReport:
    """Aggregated ground truth across all specs."""

    specs: List[SpecGroundTruth] = field(default_factory=list)
    scan_timestamp: Optional[str] = None

    @property
    def total_specs(self) -> int:
        return len(self.specs)

    @property
    def specs_with_mismatches(self) -> List[SpecGroundTruth]:
        return [s for s in self.specs if s.has_mismatch]

    @property
    def mismatch_count(self) -> int:
        return len(self.specs_with_mismatches)

    @property
    def total_spec_checked(self) -> int:
        return sum(s.spec_checked for s in self.specs)

    @property
    def total_dashboard_aware(self) -> int:
        return sum(s.dashboard_aware for s in self.specs)


def compare_spec_vs_db(
    spec_report: SpecReport,
    db_tasks_by_spec: dict[str, list[dict]],
) -> GroundTruthReport:
    """Compare spec-file state against dashboard task records.

    Args:
        spec_report: From ``scanner.scan_specs()``.
        db_tasks_by_spec: Dict mapping spec_number to list of task dicts,
            each with at least ``done_when_item`` and ``status`` keys.

    Returns:
        A ``GroundTruthReport`` with per-spec comparison.
    """
    from datetime import datetime, timezone

    report = GroundTruthReport(
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    for spec_info in spec_report.specs:
        gt = _build_spec_ground_truth(spec_info, db_tasks_by_spec)
        report.specs.append(gt)

    return report


def _build_spec_ground_truth(
    spec: SpecInfo,
    db_tasks_by_spec: dict[str, list[dict]],
) -> SpecGroundTruth:
    """Build ground truth for a single spec."""
    from .parser import extract_done_when

    # Get done-when items from spec file
    items = extract_done_when(spec.path)

    # Get DB tasks for this spec
    db_tasks = db_tasks_by_spec.get(spec.number, [])

    # Count DB states
    passed = sum(1 for t in db_tasks if t.get("status") in ("passed", "completed"))
    imported = sum(1 for t in db_tasks if t.get("status") == "imported")

    # Build set of done_when_item texts from DB for matching
    db_item_texts = {t.get("done_when_item", "") for t in db_tasks}
    # Also check for __full_spec__ tasks that passed (covers everything)
    has_full_spec_pass = any(
        t.get("done_when_item") == "__full_spec__"
        and t.get("status") in ("passed", "completed", "imported")
        for t in db_tasks
    )

    # Find items checked in spec but not tracked by dashboard
    untracked = []
    for item in items:
        if not item.get("checked"):
            continue
        text = item.get("text", "")
        # If dashboard ran __full_spec__ and it passed, all items are "tracked"
        if has_full_spec_pass:
            continue
        # Check if this specific item has a DB record
        if text not in db_item_texts:
            untracked.append(text)

    return SpecGroundTruth(
        number=spec.number,
        title=spec.title,
        status=spec.status,
        band=spec.band,
        spec_total=spec.done_when_total,
        spec_checked=spec.done_when_checked,
        spec_items=[{"text": i.get("text", ""), "checked": i.get("checked", False)} for i in items],
        db_task_count=len(db_tasks),
        db_passed_count=passed,
        db_imported_count=imported,
        untracked_items=untracked,
    )


def report_to_dict(report: GroundTruthReport) -> dict:
    """Serialize a GroundTruthReport to a JSON-friendly dict."""
    return {
        "scan_timestamp": report.scan_timestamp,
        "total_specs": report.total_specs,
        "mismatch_count": report.mismatch_count,
        "total_spec_checked": report.total_spec_checked,
        "total_dashboard_aware": report.total_dashboard_aware,
        "specs": [
            {
                "number": s.number,
                "title": s.title,
                "status": s.status,
                "band": s.band,
                "spec_total": s.spec_total,
                "spec_checked": s.spec_checked,
                "spec_ratio": round(s.spec_ratio, 2),
                "db_task_count": s.db_task_count,
                "db_passed_count": s.db_passed_count,
                "db_imported_count": s.db_imported_count,
                "dashboard_aware": s.dashboard_aware,
                "has_mismatch": s.has_mismatch,
                "untracked_items": s.untracked_items,
                "items": s.spec_items,
            }
            for s in report.specs
        ],
    }
