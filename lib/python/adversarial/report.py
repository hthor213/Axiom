"""Report generation for the adversarial evaluation pipeline.

Produces structured JSON and human-readable Markdown reports,
and writes generated test files.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ResolvedModels


def generate_report(
    models: ResolvedModels,
    challenger: dict,
    author: dict,
    arbiter: dict | None,
    files: list[str],
    counter_rebuttal: dict | None = None,
    debate_history: list[dict] | None = None,
) -> dict:
    """Generate structured report from pipeline results.

    Args:
        models: resolved model IDs for all three providers.
        challenger: parsed challenger output (or empty dict if skipped).
        author: parsed author output (or empty dict if skipped).
        arbiter: parsed arbiter output, or None if not invoked.
        files: list of file paths that were reviewed.
        counter_rebuttal: parsed counter-rebuttal output, or None.
        debate_history: list of round summaries from the debate loop.

    Returns:
        Report dict ready for JSON serialization.
    """
    issues = challenger.get("issues", [])

    # Severity counts
    by_severity: dict[str, int] = {}
    for issue in issues:
        sev = issue.get("severity", "unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Build lookup tables for verdicts
    author_verdicts: dict[str, str] = {}
    for resp in author.get("responses", []):
        author_verdicts[resp.get("issue_id", "")] = resp.get("verdict", "")

    # Build concession lookup — issues the challenger gave up on
    conceded_ids: set[str] = set()
    if counter_rebuttal:
        for cr in counter_rebuttal.get("counter_rebuttals", []):
            if cr.get("verdict") == "concede":
                conceded_ids.add(cr.get("issue_id", ""))

    arbiter_sides: dict[str, dict] = {}
    if arbiter:
        for ruling in arbiter.get("rulings", []):
            arbiter_sides[ruling.get("issue_id", "")] = ruling

    # Determine final verdict per issue and overall
    enriched_issues: list[dict] = []
    has_critical_high_fail = False
    has_medium_unresolved = False
    has_low_confidence = False

    for issue in issues:
        iid = issue.get("id", "")
        severity = issue.get("severity", "low")
        author_verdict = author_verdicts.get(iid, "")

        # Determine final outcome
        if iid in conceded_ids:
            # Challenger conceded during debate — author wins
            final_side = "author"
            resolution = "challenger_conceded"
        elif author_verdict == "accept":
            final_side = "challenger"
            resolution = "author_accepted"
        elif author_verdict == "rebut" and iid in arbiter_sides:
            ruling = arbiter_sides[iid]
            final_side = ruling.get("side", "author")
            resolution = "arbiter"
            if ruling.get("confidence") == "low":
                has_low_confidence = True
        elif author_verdict == "rebut":
            # No arbiter ruling — author's rebuttal stands unchallenged
            final_side = "author"
            resolution = "rebuttal_uncontested"
        else:
            # No author response — treat as accepted
            final_side = "challenger"
            resolution = "no_response"

        challenger_wins = final_side == "challenger"

        if challenger_wins and severity in ("critical", "high"):
            has_critical_high_fail = True
        if challenger_wins and severity == "medium":
            has_medium_unresolved = True

        enriched_issues.append({
            **issue,
            "author_verdict": author_verdict,
            "final_side": final_side,
            "resolution": resolution,
            "arbiter_ruling": arbiter_sides.get(iid),
        })

    # Overall verdict
    if has_critical_high_fail:
        verdict = "FAIL"
    elif has_medium_unresolved or has_low_confidence:
        verdict = "NEEDS_ATTENTION"
    else:
        verdict = "PASS"

    # Arbiter summary
    arbiter_summary = None
    if arbiter:
        rulings = arbiter.get("rulings", [])
        arbiter_summary = {
            "challenger_wins": sum(1 for r in rulings if r.get("side") == "challenger"),
            "author_wins": sum(1 for r in rulings if r.get("side") == "author"),
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models": {
            "anthropic": models.anthropic,
            "google": models.google,
            "openai": models.openai,
        },
        "files_reviewed": files,
        "mission_assessment": challenger.get("mission_assessment"),
        "challenger": {
            "issues_found": len(issues),
            "by_severity": by_severity,
            "tests_generated": len(issues),
        },
        "author": {
            "accepted": author.get("accepted_count", 0),
            "rebutted": author.get("rebutted_count", 0),
        },
        "debate": {
            "rounds": len(debate_history) if debate_history else 0,
            "challenger_conceded": len(conceded_ids),
            "escalated_to_arbiter": len(arbiter_sides),
            "history": debate_history or [],
        },
        "arbiter": arbiter_summary,
        "verdict": verdict,
        "tests_written": [],  # populated by write_tests
        "issues": enriched_issues,
    }


def _render_markdown(report: dict) -> str:
    """Render report dict as human-readable Markdown."""
    lines: list[str] = []
    lines.append("# Adversarial Evaluation Report\n")
    lines.append(f"**Timestamp:** {report['timestamp']}  ")
    lines.append(f"**Verdict:** {report['verdict']}\n")

    lines.append("## Models")
    for provider, model in report["models"].items():
        lines.append(f"- **{provider}:** {model or 'skipped'}")
    lines.append("")

    mission = report.get("mission_assessment")
    if mission:
        lines.append(f"**Mission:** {mission.get('verdict', 'UNKNOWN')} — "
                      f"{mission.get('reasoning', '')}\n")

    lines.append("## Files Reviewed")
    for f in report["files_reviewed"]:
        lines.append(f"- `{f}`")
    lines.append("")

    ch = report["challenger"]
    lines.append("## Challenger Summary")
    lines.append(f"- Issues found: {ch['issues_found']}")
    lines.append(f"- By severity: {ch['by_severity']}")
    lines.append(f"- Tests generated: {ch['tests_generated']}")
    lines.append("")

    au = report["author"]
    lines.append("## Author Response")
    lines.append(f"- Accepted: {au['accepted']}")
    lines.append(f"- Rebutted: {au['rebutted']}")
    lines.append("")

    debate = report.get("debate", {})
    if debate.get("rounds", 0) > 0:
        lines.append("## Debate")
        lines.append(f"- Rounds: {debate['rounds']}")
        lines.append(f"- Challenger conceded: {debate.get('challenger_conceded', 0)}")
        lines.append(f"- Escalated to arbiter: {debate.get('escalated_to_arbiter', 0)}")
        for rnd in debate.get("history", []):
            lines.append(f"- Round {rnd['round']}: author accepted {rnd['author_accepted']}, "
                          f"rebutted {rnd['author_rebutted']} | "
                          f"challenger conceded {rnd['challenger_conceded']}, "
                          f"maintained {rnd['challenger_maintained']}")
        lines.append("")

    if report["arbiter"]:
        ab = report["arbiter"]
        lines.append("## Arbiter Rulings")
        lines.append(f"- Challenger wins: {ab['challenger_wins']}")
        lines.append(f"- Author wins: {ab['author_wins']}")
        lines.append("")

    lines.append("## Issues Detail\n")
    for issue in report["issues"]:
        emoji = "FAIL" if issue["final_side"] == "challenger" else "OK"
        lines.append(f"### [{emoji}] {issue.get('id', '?')} — {issue.get('severity', '?')} "
                      f"/ {issue.get('category', '?')}")
        lines.append(f"**File:** `{issue.get('file', '?')}`  ")
        lines.append(f"**Description:** {issue.get('description', '')}")
        lines.append(f"**Author verdict:** {issue.get('author_verdict', 'none')}  ")
        lines.append(f"**Resolution:** {issue.get('resolution', 'unknown')}  ")
        lines.append(f"**Final side:** {issue['final_side']}")
        if issue.get("arbiter_ruling"):
            r = issue["arbiter_ruling"]
            lines.append(f"**Arbiter:** {r.get('side', '?')} (confidence: {r.get('confidence', '?')})")
            lines.append(f"  {r.get('reasoning', '')}")
        lines.append("")

    if report["tests_written"]:
        lines.append("## Tests Written")
        for t in report["tests_written"]:
            lines.append(f"- `{t}`")
        lines.append("")

    return "\n".join(lines)


def write_report(report: dict, project_root: str) -> None:
    """Write .adversarial-report.json and .adversarial-report.md to project root."""
    json_path = os.path.join(project_root, ".adversarial-report.json")
    md_path = os.path.join(project_root, ".adversarial-report.md")

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Wrote {json_path}", file=sys.stderr)

    with open(md_path, "w") as f:
        f.write(_render_markdown(report))
    print(f"  Wrote {md_path}", file=sys.stderr)


def write_tests(challenger_output: dict, project_root: str) -> list[str]:
    """Write generated test files to tests/adversarial/.

    Returns:
        List of file paths written (relative to project_root).
    """
    tests_content = challenger_output.get("tests_file_content", "")
    if not tests_content or not tests_content.strip():
        return []

    tests_dir = os.path.join(project_root, "tests", "adversarial")
    os.makedirs(tests_dir, exist_ok=True)

    test_path = os.path.join(tests_dir, "test_adversarial.py")
    with open(test_path, "w") as f:
        f.write(tests_content)

    rel_path = os.path.join("tests", "adversarial", "test_adversarial.py")
    print(f"  Wrote {test_path}", file=sys.stderr)
    return [rel_path]
