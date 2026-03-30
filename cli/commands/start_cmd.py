"""hth-platform start — Initialize and report project session state.

Detects project structure, scans specs, reads session context, gathers
git status, checks platform deps, resolves next action, and transitions
the harness state to STARTED.
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
            err=True
        )
        click.echo(f"  Import error: {e}", err=True)
        sys.exit(1)


@click.command("start")
@click.pass_context
def start(ctx):
    """Initialize a session and print a structured project report."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root (no specs/ or .git directory found).",
            err=True,
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.project import detect_structure
    from harness.scanner import scan_specs, build_spec_context
    from harness.session import read_session_context, resolve_next_action
    from harness.git_ops import gather_status
    from harness.platform_check import check_platform_deps
    from harness.state import load_state, save_state, transition, SessionPhase

    # --- Detect project structure ---
    structure = detect_structure(project_root)

    # If new/fresh project, suggest scaffolding
    if structure.project_type == "fresh":
        click.echo(click.style("New project detected.", fg="yellow", bold=True))
        click.echo("  Run " + click.style("hth-platform init <name>", bold=True) +
                    " to scaffold specs and workflow files.")
        return
    if structure.project_type == "legacy":
        click.echo(click.style("Legacy project detected.", fg="yellow", bold=True))
        click.echo("  Found SPEC.md but no specs/ directory.")
        click.echo("  Consider migrating with " +
                    click.style("hth-platform harness start", bold=True) + ".")

    # --- Scan specs ---
    specs_dir = os.path.join(project_root, "specs")
    spec_report = scan_specs(specs_dir)
    spec_context = build_spec_context(project_root)

    # --- Read session context ---
    session_ctx = read_session_context(project_root)

    # --- Gather git status ---
    git_status = gather_status(project_root)

    # --- Check platform deps ---
    platform_report = check_platform_deps(project_root)

    # --- Resolve next action ---
    next_action = resolve_next_action(session_ctx)

    # --- Transition harness state to STARTED ---
    state = load_state(project_root)
    try:
        state = transition(state, SessionPhase.STARTED)
    except ValueError:
        # Already past COLD — reset to COLD first, then start
        # Or if in a valid state, just note it
        pass

    state.branch = git_status.branch
    state.active_specs = [s.number for s in spec_context.active_specs]
    save_state(state, project_root)

    # =====================================================================
    # Print structured report
    # =====================================================================

    click.echo()
    click.echo(click.style("=== Platform Start ===", fg="cyan", bold=True))
    click.echo()

    # --- Project type + structure health ---
    type_colors = {
        "harness": "green",
        "legacy": "yellow",
        "fresh": "yellow",
        "unknown": "red",
    }
    ptype = structure.project_type
    click.echo(click.style("Project", bold=True))
    click.echo(f"  Type:       {click.style(ptype, fg=type_colors.get(ptype, 'white'))}")
    click.echo(f"  Root:       {project_root}")

    health_items = []
    if structure.has_specs_dir:
        health_items.append(click.style("specs/", fg="green"))
    else:
        health_items.append(click.style("specs/ missing", fg="red"))
    if structure.has_claude_md:
        health_items.append(click.style("CLAUDE.md", fg="green"))
    if structure.has_last_session:
        health_items.append(click.style("LAST_SESSION.md", fg="green"))
    if structure.has_backlog:
        health_items.append(click.style("BACKLOG.md", fg="green"))
    click.echo(f"  Structure:  {', '.join(health_items)}")
    click.echo()

    # --- Active specs by band ---
    click.echo(click.style("Specs", bold=True))
    click.echo(f"  Total: {len(spec_report.specs)}  "
               f"Active: {spec_report.active_count}  "
               f"Drift candidates: {len(spec_report.drift_candidates)}")

    band_order = ["vision", "foundation", "mvp", "v1", "v2", "backlog"]
    for band in band_order:
        specs_in_band = spec_report.by_band.get(band, [])
        if not specs_in_band:
            continue
        click.echo(f"  [{click.style(band.upper(), bold=True)}]")
        for s in specs_in_band:
            status_colors = {
                "active": "green",
                "done": "blue",
                "draft": "white",
            }
            sc = status_colors.get(s.status, "white")
            progress = ""
            if s.done_when_total > 0:
                progress = f" ({s.done_when_checked}/{s.done_when_total})"
            display_status = s.status
            if s.status == "active" and s.done_when_checked == 0:
                display_status = "ready"
            status_text = click.style(display_status, fg=sc, dim=(s.status == "draft"))
            click.echo(f"    {click.style(s.number, bold=True)} "
                       f"{status_text} "
                       f"{s.title}{progress}")
    click.echo()

    # --- Where we left off ---
    click.echo(click.style("Last Session", bold=True))
    last = session_ctx.last_session
    if last and last.get("_raw"):
        focus = last.get("focus", "")
        if isinstance(focus, str) and focus:
            click.echo(f"  Focus: {focus}")
        elif isinstance(focus, list) and focus:
            click.echo(f"  Focus: {'; '.join(str(x) for x in focus)}")

        date_val = last.get("date", "")
        if isinstance(date_val, str) and date_val:
            click.echo(f"  Date:  {date_val}")

        next_val = last.get("next", last.get("next session", ""))
        if isinstance(next_val, list):
            click.echo("  Next:")
            for item in next_val[:5]:
                click.echo(f"    - {item}")
        elif isinstance(next_val, str) and next_val:
            click.echo(f"  Next:  {next_val}")
    else:
        click.echo("  No previous session found.")
    click.echo()

    # --- Git status ---
    click.echo(click.style("Git", bold=True))
    if git_status.branch:
        click.echo(f"  Branch:      {click.style(git_status.branch, bold=True)}")
    else:
        click.echo(f"  Branch:      {click.style('(detached or not a repo)', fg='yellow')}")

    if git_status.is_clean:
        click.echo(f"  Status:      {click.style('clean', fg='green')}")
    else:
        uncommitted_count = len(git_status.uncommitted)
        staged_count = len(git_status.staged)
        parts = []
        if uncommitted_count:
            parts.append(f"{uncommitted_count} uncommitted")
        if staged_count:
            parts.append(f"{staged_count} staged")
        click.echo(f"  Status:      {click.style(', '.join(parts), fg='yellow')}")

    if git_status.recent_commits:
        click.echo(f"  Last commit: {git_status.recent_commits[0]}")
    click.echo()

    # --- Recommended next action ---
    click.echo(click.style("Next Action", bold=True))
    source_colors = {
        "last_session": "cyan",
        "current_tasks": "green",
        "backlog_p0": "red",
        "backlog": "yellow",
        "active_spec": "blue",
        "none": "dim",
    }
    sc = source_colors.get(next_action.source, "white")
    click.echo(f"  Source:  {click.style(next_action.source, fg=sc)}")
    click.echo(f"  Action:  {next_action.description}")
    if next_action.spec_ref:
        click.echo(f"  Spec:    {next_action.spec_ref}")
    click.echo(f"  Why:     {click.style(next_action.reasoning, dim=True)}")
    click.echo()

    # --- Platform status ---
    click.echo(click.style("Platform", bold=True))
    cred = platform_report.credential_source
    if cred == "none":
        click.echo(f"  Credentials:    {click.style('none detected', fg='yellow')}")
    else:
        click.echo(f"  Credentials:    {', '.join(platform_report.credential_sources)}")
    if platform_report.infrastructure_deps:
        click.echo(f"  Infrastructure: {', '.join(platform_report.infrastructure_deps)}")
    else:
        click.echo(f"  Infrastructure: none")
    click.echo(f"  {click.style(platform_report.recommendation, dim=True)}")
    click.echo()
