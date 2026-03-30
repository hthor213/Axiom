"""Test-to-production promotion flow.

After a test deploy, the pipeline enters awaiting_promotion state.
This module handles the promotion action: running production deploy
targets for an existing pipeline run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from .state import PipelineRun, StepResult, ShipStateStore
from .deploy import DeployTarget, DeployResult, run_deploy, load_targets
from .audit import log_step, log_scope_change


@dataclass
class PromotionResult:
    """Result of promoting a test deploy to production."""

    status: str  # promoted | failed | not_awaiting
    run_id: str = ""
    steps: List[StepResult] = field(default_factory=list)


def promote_to_production(
    result_id: str,
    store: ShipStateStore,
    root: str,
    branch: str = "",
) -> PromotionResult:
    """Promote a test deploy to production.

    Finds the latest run in awaiting_promotion state and executes
    production deploy targets. No re-merge occurs.

    Args:
        result_id: The result being promoted.
        store: Pipeline state store.
        root: Project root for loading targets.
        branch: Branch name for slug substitution.

    Returns:
        PromotionResult with status and step details.
    """
    run = store.get_latest_run(result_id)
    if not run or run.status != "awaiting_promotion":
        return PromotionResult(
            status="not_awaiting",
            run_id=run.run_id if run else "",
        )

    targets = load_targets(root)
    prod_targets = [t for t in targets if t.role == "production"]

    if not prod_targets:
        return PromotionResult(
            status="failed",
            run_id=run.run_id,
            steps=[StepResult(
                step="deploy_production",
                status="failed",
                detail="No production deploy targets configured.",
                timestamp=time.time(),
            )],
        )

    steps: List[StepResult] = []
    all_ok = True

    for target in prod_targets:
        deploy_result = run_deploy(target, branch)
        step = StepResult(
            step="deploy_production",
            status="ok" if deploy_result.ok else "failed",
            detail=deploy_result.output or target.name,
            timestamp=time.time(),
        )
        steps.append(step)
        run.steps.append(step)

        if not deploy_result.ok:
            all_ok = False
            break

    if all_ok:
        run.status = "shipped"
    else:
        run.status = "failed"
    store.save_run(run)

    return PromotionResult(
        status="promoted" if all_ok else "failed",
        run_id=run.run_id,
        steps=steps,
    )


def resolve_feedback(
    result_id: str,
    store: ShipStateStore,
    root: str,
    clarification_actions: Optional[List[str]] = None,
    expansion_decisions: Optional[List[dict]] = None,
) -> dict:
    """Resolve feedback decisions and log scope changes.

    Args:
        result_id: The result being resolved.
        store: Pipeline state store.
        root: Project root for logging.
        clarification_actions: Actions for clarifications.
        expansion_decisions: Decisions for expansions.

    Returns:
        Dict with resolved items and their outcomes.
    """
    run = store.get_latest_run(result_id)
    if not run:
        return {"status": "not_found"}

    resolved = []

    if clarification_actions:
        for action in clarification_actions:
            resolved.append({
                "type": "clarification",
                "action": action,
                "status": "accepted",
            })

    if expansion_decisions:
        for decision in expansion_decisions:
            resolved.append({
                "type": "expansion",
                "issue": decision.get("issue", ""),
                "decision": decision.get("decision", ""),
                "status": "accepted",
            })

    # Log scope changes using a minimal ShipOptions-like object
    from .pipeline import ShipOptions
    opts = ShipOptions(root=root, actor=run.actor, result_id=result_id)

    for item in resolved:
        log_scope_change(
            run=run,
            reason=item["type"],
            detail=f"{item['type']}: {item.get('action', item.get('decision', ''))}",
            opts=opts,
        )

    return {"status": "resolved", "items": resolved}
