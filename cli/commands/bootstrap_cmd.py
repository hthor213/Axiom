"""hth-platform bootstrap — One-time import of spec progress into dashboard DB.

Reads all spec files, finds checked Done When items with no corresponding
dashboard task record, and creates 'imported' records to bring the DB
in sync with spec-file reality.
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


@click.command("bootstrap")
@click.option("--spec", default=None, help="Only bootstrap a specific spec number (e.g., 025)")
@click.option("--dry-run", is_flag=True, help="Show what would be imported without writing to DB")
@click.option("--db-url", envvar="DATABASE_URL", help="PostgreSQL connection string")
@click.pass_context
def bootstrap(ctx, spec, dry_run, db_url):
    """Import checked spec items into dashboard DB (one-time sync)."""
    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: ", fg="red") + "Could not find project root.", err=True)
        sys.exit(1)

    if not db_url:
        click.echo(click.style("Error: ", fg="red") + "DATABASE_URL required (set env var or --db-url).", err=True)
        sys.exit(1)

    import_harness(ctx)
    from harness.scanner import scan_specs
    from harness.ground_truth import compare_spec_vs_db
    from runtime.db import TaskStore, Task

    specs_dir = os.path.join(project_root, "specs")
    if not os.path.isdir(specs_dir):
        click.echo(click.style("Warning: ", fg="yellow") + "No specs/ directory found.")
        sys.exit(0)

    # Scan specs
    spec_report = scan_specs(specs_dir)
    click.echo(f"Scanned {len(spec_report.specs)} specs")

    # Connect to DB and get existing tasks
    store = TaskStore(pg_conn_string=db_url)
    all_tasks = store.get_all_tasks()

    # Group tasks by spec
    db_tasks_by_spec = {}
    for t in all_tasks:
        entry = {"done_when_item": t.done_when_item, "status": t.status, "id": t.id}
        db_tasks_by_spec.setdefault(t.spec_number, []).append(entry)

    # Compare
    report = compare_spec_vs_db(spec_report, db_tasks_by_spec)

    # Find untracked items
    total_import = 0
    for spec_gt in report.specs:
        if spec and spec_gt.number != spec:
            continue
        if not spec_gt.untracked_items:
            continue

        click.echo()
        click.echo(click.style(f"  {spec_gt.number}: {spec_gt.title}", bold=True))
        click.echo(f"    Spec: {spec_gt.spec_checked}/{spec_gt.spec_total} checked | DB: {spec_gt.dashboard_aware} tracked")

        for item_text in spec_gt.untracked_items:
            total_import += 1
            prefix = click.style("  [DRY]", fg="yellow") if dry_run else click.style("  [ADD]", fg="green")
            click.echo(f"    {prefix} {item_text[:100]}")

            if not dry_run:
                task = Task(
                    spec_number=spec_gt.number,
                    spec_title=spec_gt.title,
                    done_when_item=item_text,
                    status="imported",
                    queued_by="bootstrap",
                )
                store.enqueue_task(task)

    click.echo()
    if dry_run:
        click.echo(f"Would import {total_import} items. Run without --dry-run to apply.")
    elif total_import > 0:
        click.echo(click.style(f"Imported {total_import} items.", fg="green"))
    else:
        click.echo(click.style("Already in sync.", fg="green") + " No untracked items found.")
