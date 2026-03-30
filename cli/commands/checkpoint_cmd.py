"""hth-platform checkpoint — End-of-session checkpoint with invariant checks.

Runs the checkpoint gate, checks automatable invariants, prepares a commit
plan, and reports spec status and invariant health.
"""

import click
import os
import sys


def find_project_root():
    """Walk up from cwd looking for specs/ or .git to find project root."""
    current = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(current, "specs")) or \
           os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def import_harness(ctx):
    """Import harness modules, adding lib/python to sys.path if needed."""
    platform_root = ctx.obj["platform_root"]
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    try:
        import harness
        return harness
    except ImportError as e:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not import harness modules from lib/python/harness/.",
            err=True,
        )
        click.echo(f"  Import error: {e}", err=True)
        sys.exit(1)


@click.command("checkpoint")
@click.option("--dry-run", is_flag=True, default=False,
              help="Report only, do not stage or commit.")
@click.option("--commit", "do_commit", is_flag=True, default=False,
              help="Actually stage and commit changes.")
@click.pass_context
def checkpoint(ctx, dry_run, do_commit):
    """Run checkpoint gate, check invariants, and prepare commit."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True,
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.gates import checkpoint_gate
    from harness.checkpoint import (
        check_automatable_invariants,
        prepare_commit,
    )
    from harness.scanner import build_spec_context
    from harness.git_ops import stage_files, create_commit

    click.echo()
    click.echo(click.style("=== Platform Checkpoint ===", fg="cyan", bold=True))
    click.echo()

    # --- Run checkpoint gate ---
    click.echo(click.style("Checkpoint Gate", bold=True))
    gate_result = checkpoint_gate(project_root)
    for c in gate_result.get("checks", []):
        passed = c.get("passed", False)
        icon = click.style("PASS", fg="green") if passed else click.style("FAIL", fg="red")
        desc = c.get("description", "")
        error_str = ""
        if not passed and c.get("error"):
            error_str = f" -- {c['error']}"
        click.echo(f"  [{icon}] {desc}{error_str}")

    if gate_result.get("passed"):
        click.echo(click.style("  Gate: PASSED", fg="green", bold=True))
    else:
        click.echo(click.style("  Gate: FAILED", fg="red", bold=True))
    click.echo()

    # --- Check automatable invariants ---
    click.echo(click.style("Invariant Health", bold=True))
    spec_context = build_spec_context(project_root)
    invariants = spec_context.invariants

    if invariants:
        inv_results = check_automatable_invariants(project_root, invariants)
        pass_count = sum(1 for r in inv_results if r.status == "pass")
        fail_count = sum(1 for r in inv_results if r.status == "fail")
        skip_count = sum(1 for r in inv_results if r.status == "skip")

        for r in inv_results:
            if r.status == "pass":
                icon = click.style("PASS", fg="green")
            elif r.status == "fail":
                icon = click.style("FAIL", fg="red")
            else:
                icon = click.style("SKIP", fg="yellow")
            click.echo(f"  [{icon}] {r.invariant}")
            if r.status == "fail":
                click.echo(f"         {click.style(r.evidence, dim=True)}")

        click.echo(f"  Summary: {pass_count} pass, {fail_count} fail, {skip_count} skip")
    else:
        click.echo("  No invariants defined in vision spec.")
    click.echo()

    # --- Prepare commit plan ---
    click.echo(click.style("Commit Plan", bold=True))
    plan = prepare_commit(project_root)

    if plan.has_changes:
        click.echo(f"  Message: {plan.message}")
        click.echo(f"  Files to stage ({len(plan.files_to_stage)}):")
        for f in plan.files_to_stage:
            click.echo(f"    {f}")
    else:
        click.echo("  No changes to commit.")
    click.echo()

    # --- Execute commit if requested ---
    if dry_run:
        click.echo(click.style("Dry run — no changes made.", fg="yellow"))
        return

    if do_commit and plan.has_changes:
        click.echo(click.style("Committing...", bold=True))
        staged_ok = stage_files(project_root, plan.files_to_stage)
        if staged_ok:
            committed = create_commit(project_root, plan.message)
            if committed:
                click.echo(click.style("  Commit created.", fg="green"))
            else:
                click.echo(click.style("  Commit failed.", fg="red"))
                sys.exit(1)
        else:
            click.echo(click.style("  Staging failed.", fg="red"))
            sys.exit(1)
    elif do_commit and not plan.has_changes:
        click.echo("Nothing to commit.")
    else:
        if plan.has_changes:
            click.echo("Use " + click.style("--commit", bold=True) +
                        " to stage and commit, or " +
                        click.style("--dry-run", bold=True) + " to preview only.")
