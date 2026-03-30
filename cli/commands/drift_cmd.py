"""hth-platform drift — Check spec alignment and detect drift.

Builds spec context, runs all deterministic drift checks, and prints a
report of stale active specs, regressed done specs, and uncovered
directories. Exits 0 if clean, 1 if drift detected.
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


@click.command("drift")
@click.pass_context
def drift(ctx):
    """Check spec alignment and report drift signals."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True,
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.scanner import build_spec_context
    from harness.drift import check_alignment

    click.echo()
    click.echo(click.style("=== Drift Check ===", fg="cyan", bold=True))
    click.echo()

    # --- Build context and check alignment ---
    spec_context = build_spec_context(project_root)
    report = check_alignment(project_root, spec_context)

    if report.clean:
        click.echo(click.style("No drift detected.", fg="green", bold=True))
        click.echo()
        sys.exit(0)

    # --- Group items by type ---
    severity_colors = {
        "error": "red",
        "warning": "yellow",
        "info": "cyan",
    }

    type_labels = {
        "stale_active_spec": "Stale Active Specs",
        "done_regression": "Done Spec Regressions",
        "uncovered_directory": "Uncovered Directories",
    }

    # Group by type
    by_type: dict[str, list] = {}
    for item in report.items:
        by_type.setdefault(item.type, []).append(item)

    # Print each group
    for drift_type, label in type_labels.items():
        items = by_type.get(drift_type, [])
        if not items:
            continue

        click.echo(click.style(label, bold=True))
        for item in items:
            sev_color = severity_colors.get(item.severity, "white")
            sev_label = click.style(item.severity.upper(), fg=sev_color)
            spec_ref = f" (spec:{item.spec_ref})" if item.spec_ref else ""
            click.echo(f"  [{sev_label}]{spec_ref} {item.description}")
        click.echo()

    # --- Summary ---
    click.echo(click.style("Summary", bold=True))
    click.echo(f"  {report.summary}")
    click.echo()

    sys.exit(1)
