"""hth-platform refresh — Mid-session state save.

Generates a refresh state snapshot and optionally commits state files
(specs + session metadata) without touching code changes.
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


@click.command("refresh")
@click.option("--commit", "do_commit", is_flag=True, default=False,
              help="Actually stage and commit state files.")
@click.pass_context
def refresh(ctx, do_commit):
    """Generate mid-session state snapshot and optionally commit."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True,
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.refresh import generate_refresh_state, prepare_state_commit
    from harness.session import read_session_context
    from harness.git_ops import stage_files, create_commit

    click.echo()
    click.echo(click.style("=== Platform Refresh ===", fg="cyan", bold=True))
    click.echo()

    # --- Generate refresh state ---
    session_ctx = read_session_context(project_root)
    refresh_content = generate_refresh_state(session_ctx)

    click.echo(click.style("Refresh State Preview", bold=True))
    # Show a compact preview of the generated content
    for line in refresh_content.splitlines()[:20]:
        click.echo(f"  {line}")
    if len(refresh_content.splitlines()) > 20:
        click.echo(f"  ... ({len(refresh_content.splitlines()) - 20} more lines)")
    click.echo()

    # --- Prepare state commit ---
    plan = prepare_state_commit(project_root)

    click.echo(click.style("State Commit Plan", bold=True))
    if plan.has_changes:
        click.echo(f"  Message: {plan.message}")
        click.echo(f"  Files ({len(plan.files_to_stage)}):")
        for f in plan.files_to_stage:
            click.echo(f"    {f}")
    else:
        click.echo("  No state files to commit.")
    click.echo()

    # --- Execute commit if requested ---
    if do_commit and plan.has_changes:
        # Write the refresh content to LAST_SESSION.md
        last_session_path = os.path.join(project_root, "LAST_SESSION.md")
        try:
            with open(last_session_path, "w", encoding="utf-8") as f:
                f.write(refresh_content)
            click.echo(click.style("  LAST_SESSION.md updated.", fg="green"))
        except OSError as e:
            click.echo(click.style(f"  Failed to write LAST_SESSION.md: {e}", fg="red"))
            sys.exit(1)

        click.echo(click.style("Committing state...", bold=True))
        staged_ok = stage_files(project_root, plan.files_to_stage)
        if staged_ok:
            committed = create_commit(project_root, plan.message)
            if committed:
                click.echo(click.style("  State commit created.", fg="green"))
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
                        " to write LAST_SESSION.md and commit state files.")
