"""hth-platform ship — Review, commit, push, and deploy pipeline.

Runs the full ship pipeline: verify (tests + spec drift + backlog),
commit, push, create PR or merge directly, optionally deploy.
"""

import os
import sys
import time

import click


def _import_ship(ctx):
    """Import ship modules, adding lib/python to sys.path if needed."""
    platform_root = ctx.obj["platform_root"]
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    try:
        import ship
        return ship
    except ImportError as e:
        click.echo(
            click.style("Error: ", fg="red")
            + "Could not import ship modules from lib/python/ship/.",
            err=True,
        )
        click.echo(f"  Import error: {e}", err=True)
        sys.exit(1)


def _step_callback(step: str, status: str) -> None:
    """Print per-step status lines."""
    if status == "running":
        click.echo(f"  [ship] {step}: running...", nl=False)
    elif status == "ok":
        click.echo(click.style(f"\r  [ship] {step}: passed", fg="green")
                    + "                    ")
    elif status == "failed":
        click.echo(click.style(f"\r  [ship] {step}: FAILED", fg="red")
                    + "                    ")
    elif status == "awaiting_promotion":
        click.echo(click.style(
            f"\r  [ship] {step}: awaiting promotion", fg="yellow",
        ) + "            ")
    else:
        click.echo(f"\r  [ship] {step}: {status}"
                    + "                    ")


@click.command("ship")
@click.option("--message", "-m", default="", help="Commit message.")
@click.option("--strategy", type=click.Choice(["pr", "merge"]),
              default="pr", help="PR or direct merge.")
@click.option("--deploy", "do_deploy", is_flag=True, default=False,
              help="Run deploy after merge/PR.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Verify only, no commits or pushes.")
@click.option("--no-tests", is_flag=True, default=False,
              help="Skip test suite.")
@click.pass_context
def ship(ctx, message, strategy, do_deploy, dry_run, no_tests):
    """Run the ship pipeline: verify, commit, push, PR/merge, deploy."""
    _import_ship(ctx)
    from ship.pipeline import ShipOptions, run_pipeline
    from ship.state import ShipStateStore

    root = _find_project_root()
    if not root:
        click.echo(click.style("Error: ", fg="red")
                    + "Could not find project root.", err=True)
        sys.exit(1)

    click.echo()
    click.echo(click.style("=== Ship Pipeline ===", fg="cyan", bold=True))
    click.echo()

    if dry_run:
        click.echo(click.style("  Dry run mode — no changes will be made.",
                                fg="yellow"))
        click.echo()

    opts = ShipOptions(
        root=root,
        message=message,
        strategy=strategy,
        deploy=do_deploy,
        dry_run=dry_run,
        no_tests=no_tests,
        actor="cli",
    )

    store = ShipStateStore(
        db_path=os.path.join(root, "ship_state.db"),
    )

    try:
        result = run_pipeline(opts, store=store, on_step=_step_callback)
    finally:
        store.close()

    click.echo()
    _print_result(result)

    if result.status == "failed":
        sys.exit(1)


def _print_result(result) -> None:
    """Print the final pipeline result."""
    if result.status == "shipped":
        click.echo(click.style("  Pipeline: SHIPPED", fg="green", bold=True))
    elif result.status == "already_shipped":
        click.echo(click.style("  Already shipped.", fg="yellow"))
    elif result.status == "awaiting_promotion":
        click.echo(click.style("  Awaiting promotion.", fg="yellow", bold=True))
        if result.test_url:
            click.echo(f"  Test URL: {result.test_url}")
    elif result.status == "failed":
        click.echo(click.style("  Pipeline: FAILED", fg="red", bold=True))

    if result.pr_url:
        click.echo(f"  PR: {result.pr_url}")
    if result.merge_sha:
        click.echo(f"  Merge SHA: {result.merge_sha}")
        click.echo(f"  Rollback: git revert {result.merge_sha[:8]}")

    # Print step details for failures
    for step in result.steps:
        if step.status == "failed":
            click.echo(click.style(f"\n  [error] {step.step}: {step.detail}",
                                    fg="red"))
        elif "[warn]" in step.detail:
            click.echo(click.style(f"  [warn] {step.detail}", fg="yellow"))


def _find_project_root():
    """Walk up from cwd looking for specs/ or .git."""
    current = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(current, "specs")) or \
           os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
