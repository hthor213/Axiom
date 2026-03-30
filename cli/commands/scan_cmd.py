"""hth-platform scan — Scan and report on all specs.

Scans the specs/ directory and prints a health report grouped by band,
showing totals, statuses, and drift candidates.
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


@click.command("scan")
@click.pass_context
def scan(ctx):
    """Scan all specs and print a health report."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True,
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.scanner import scan_specs

    specs_dir = os.path.join(project_root, "specs")

    if not os.path.isdir(specs_dir):
        click.echo(
            click.style("Warning: ", fg="yellow") +
            f"No specs/ directory found at {project_root}.",
        )
        sys.exit(0)

    report = scan_specs(specs_dir)

    click.echo()
    click.echo(click.style("=== Spec Scan ===", fg="cyan", bold=True))
    click.echo()

    # --- Summary ---
    total = len(report.specs)
    active = report.active_count
    done_count = len(report.by_status.get("done", []))
    draft_count = len(report.by_status.get("draft", []))
    drift_count = len(report.drift_candidates)

    click.echo(click.style("Summary", bold=True))
    click.echo(f"  Total:    {total}")
    click.echo(f"  Active:   {click.style(str(active), fg='green')}")
    click.echo(f"  Done:     {click.style(str(done_count), fg='blue')}")
    click.echo(f"  Draft:    {click.style(str(draft_count), dim=True)}")
    click.echo(f"  Drift:    {click.style(str(drift_count), fg='yellow' if drift_count else 'green')}")
    click.echo()

    # --- Specs by band ---
    band_order = ["vision", "foundation", "mvp", "v1", "v2", "backlog"]

    for band in band_order:
        specs_in_band = report.by_band.get(band, [])
        if not specs_in_band:
            continue

        click.echo(click.style(f"  [{band.upper()}]", bold=True))

        for s in specs_in_band:
            status_colors = {
                "active": "green",
                "done": "blue",
                "draft": "white",
            }
            sc = status_colors.get(s.status, "white")

            # Progress indicator
            progress = ""
            if s.done_when_total > 0:
                ratio = s.done_when_checked / s.done_when_total
                progress = f" [{s.done_when_checked}/{s.done_when_total}]"
                if ratio >= 1.0:
                    progress = click.style(progress, fg="green")
                elif ratio > 0:
                    progress = click.style(progress, fg="yellow")
                else:
                    progress = click.style(progress, dim=True)

            # Drift marker
            drift_marker = ""
            if s in report.drift_candidates:
                drift_marker = click.style(" [DRIFT]", fg="yellow")

            display_status = s.status
            if s.status == "active" and s.done_when_checked == 0:
                display_status = "ready"
            click.echo(
                f"    {click.style(s.number, bold=True)} "
                f"{click.style(display_status.ljust(7), fg=sc)} "
                f"{s.title}{progress}{drift_marker}"
            )

        click.echo()

    # --- Drift candidates detail ---
    if report.drift_candidates:
        click.echo(click.style("Drift Candidates", bold=True, fg="yellow"))
        for s in report.drift_candidates:
            reason = ""
            if s.status == "active" and s.done_when_total == 0:
                reason = "active with no Done When items"
            elif s.status == "active" and s.done_when_checked >= s.done_when_total:
                reason = "all Done When items checked -- consider promoting to done"
            elif s.status == "draft" and s.done_when_checked > 0:
                reason = "draft with checked items -- consider promoting to active"
            click.echo(f"  {click.style(s.number, bold=True)} {s.title}: {reason}")
        click.echo()

    if total == 0:
        click.echo("No spec files found. Create specs in specs/ to get started.")
