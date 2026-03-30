"""Runtime command — runs the autonomous task queue processor."""

import os
import sys
import click


@click.command("runtime")
@click.option("--max-turns", default=30, help="Max turns per agent session")
@click.option("--time-limit", default=60, help="Time limit per task in minutes")
@click.option("--no-telegram", is_flag=True, help="Disable Telegram notifications")
@click.option("--no-adversarial", is_flag=True, help="Skip adversarial review")
@click.option("--pg-url", default=None, help="PostgreSQL connection URL")
@click.pass_context
def runtime(ctx, max_turns, time_limit, no_telegram, no_adversarial, pg_url):
    """Process the task queue autonomously.

    Reads queued tasks from the database, runs Claude Agent SDK sessions
    in isolated git worktrees, runs tests and adversarial review, and
    saves results. Sends Telegram notification when done.
    """
    platform_root = ctx.obj.get("platform_root", os.getcwd())
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from runtime.db import TaskStore
    from runtime.server import RuntimeServer, RuntimeConfig

    pg_conn = pg_url or os.environ.get("DATABASE_URL")
    if not pg_conn:
        click.echo("Error: PostgreSQL connection required. Set DATABASE_URL or use --pg-url")
        raise SystemExit(1)

    store = TaskStore(pg_conn_string=pg_conn)

    config = RuntimeConfig(
        repo_root=platform_root,
        max_turns_per_task=max_turns,
        time_limit_per_task_min=time_limit,
        telegram_notify=not no_telegram,
        run_adversarial=not no_adversarial,
    )

    click.echo(f"Starting runtime processor")
    click.echo(f"  Repo: {platform_root}")
    click.echo(f"  Max turns/task: {max_turns}")
    click.echo(f"  Time limit/task: {time_limit}min")
    click.echo(f"  Telegram: {'off' if no_telegram else 'on'}")
    click.echo(f"  Adversarial: {'off' if no_adversarial else 'on'}")

    queued = store.get_queued_tasks()
    click.echo(f"  Queued tasks: {len(queued)}")

    if not queued:
        click.echo("No tasks in queue. Enqueue via dashboard or:")
        click.echo("  hth-platform serve  (then use the web UI)")
        return

    server = RuntimeServer(store, config)
    run = server.process_queue()

    click.echo(f"\nRun #{run.id} finished: {run.status}")
    click.echo(f"  Completed: {run.tasks_completed}")
    click.echo(f"  Failed: {run.tasks_failed}")
    click.echo(f"  Reason: {run.stop_reason}")
