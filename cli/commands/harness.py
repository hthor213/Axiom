"""
hth-platform harness — Deterministic session harness for spec-driven development.

Subcommands:
    hth-platform harness start          Initialize a new session
    hth-platform harness status         Show current session state
    hth-platform harness check          Run spec checks (Done When items)
    hth-platform harness gate           Run a gate evaluation
"""

import click
import os
import subprocess
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


def get_git_branch():
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


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
        click.echo("  Ensure lib/python/harness/ exists with state.py, "
                    "spec_check.py, gates.py, termination.py", err=True)
        sys.exit(1)


def _find_spec_file(specs_dir, spec_number):
    """Find a spec file by number prefix."""
    if not os.path.isdir(specs_dir):
        return None
    for fname in sorted(os.listdir(specs_dir)):
        if fname.startswith(spec_number) and fname.endswith(".md"):
            return os.path.join(specs_dir, fname)
    return None


@click.group()
@click.pass_context
def harness(ctx):
    """Deterministic session harness for spec-driven development."""
    ctx.ensure_object(dict)


@harness.command("start")
@click.pass_context
def start(ctx):
    """Initialize a new harness session."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root (no specs/ or .git directory found).",
            err=True
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.state import load_state, save_state, transition, SessionPhase
    from harness.parser import scan_active_specs

    # Load or create state, transition to STARTED
    state = load_state(project_root)
    state = transition(state, SessionPhase.STARTED)

    # Scan for active specs and record branch
    specs_dir = os.path.join(project_root, "specs")
    active_specs = scan_active_specs(specs_dir)
    branch = get_git_branch()

    state.branch = branch
    state.active_specs = [s["number"] for s in active_specs]
    save_state(state, project_root)

    # Report
    click.echo(click.style("Session initialized.", fg="green", bold=True))
    click.echo(f"  Project root: {project_root}")
    if branch:
        click.echo(f"  Branch:       {branch}")
    click.echo(f"  Active specs: {len(active_specs)}")
    for spec in active_specs:
        click.echo(f"    {click.style(spec['number'], bold=True)} — {spec['title']}")

    if not active_specs:
        click.echo(click.style(
            "  No active specs found. Mark a spec as **Status:** active to begin.",
            fg="yellow"
        ))


@harness.command("status")
@click.pass_context
def status(ctx):
    """Show current session state."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.state import load_state, SessionPhase

    state = load_state(project_root)

    if state.phase == SessionPhase.COLD:
        click.echo("No active session. Run " +
                    click.style("hth-platform harness start", bold=True) +
                    " to begin.")
        return

    # Phase with color
    phase_colors = {
        "started": "green",
        "working": "cyan",
        "refreshing": "yellow",
        "checkpointing": "yellow",
        "ended": "blue",
    }
    phase_name = state.phase.value
    color = phase_colors.get(phase_name, "white")
    click.echo(f"  Phase:       {click.style(phase_name.upper(), fg=color, bold=True)}")

    if state.started_at:
        click.echo(f"  Started:     {state.started_at}")
    if state.branch:
        click.echo(f"  Branch:      {state.branch}")

    if state.active_specs:
        click.echo(f"  Active specs: {', '.join(state.active_specs)}")
    if state.focus:
        click.echo(f"  Focus:       {click.style(state.focus, fg='cyan')}")

    if state.gates_passed:
        click.echo(f"  Gates:")
        for gate_name, passed in state.gates_passed.items():
            icon = click.style("PASS", fg="green") if passed else click.style("FAIL", fg="red")
            click.echo(f"    [{icon}] {gate_name}")


@harness.command("check")
@click.option("--spec", "spec_number", default=None,
              help="Spec number to check (e.g., 003). Checks all active if omitted.")
@click.pass_context
def check(ctx, spec_number):
    """Run spec checks (Done When items)."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.parser import scan_active_specs, extract_spec_title
    from harness.spec_check import check_spec

    specs_dir = os.path.join(project_root, "specs")

    # Determine which specs to check
    if spec_number:
        spec_path = _find_spec_file(specs_dir, spec_number)
        if not spec_path:
            click.echo(
                click.style("Error: ", fg="red") +
                f"No spec found matching number {spec_number}.",
                err=True
            )
            sys.exit(1)
        title = extract_spec_title(spec_path)
        specs = [{"path": spec_path, "number": spec_number, "title": title}]
    else:
        specs = scan_active_specs(specs_dir)
        if not specs:
            click.echo("No active specs to check.")
            return

    any_failures = False

    for spec in specs:
        click.echo(click.style(
            f"\n--- Spec {spec['number']}: {spec['title']} ---",
            bold=True
        ))

        result = check_spec(spec["path"], project_root)

        for item in result["items"]:
            r = item.get("result")
            text = item.get("text", "")

            if r is True:
                icon = click.style("PASS", fg="green")
            elif r is False:
                icon = click.style("FAIL", fg="red")
                any_failures = True
            else:
                icon = click.style("JUDGMENT", fg="yellow")

            checked = "[x]" if item.get("checked") else "[ ]"
            click.echo(f"  [{icon}] {checked} {text}")
            if r is False and item.get("error"):
                click.echo(f"         {click.style(item['error'], dim=True)}")

        auto_total = result["passed"] + result["failed"]
        click.echo(
            f"\n  {result['passed']}/{auto_total} automatable checks passed"
            + (f", {result['judgment']} need judgment" if result["judgment"] else "")
        )

    sys.exit(1 if any_failures else 0)


@harness.command("gate")
@click.argument("gate_name", type=click.Choice(
    ["activate", "complete", "checkpoint"], case_sensitive=False
))
@click.option("--spec", "spec_number", default=None,
              help="Spec number for activate/complete gates (e.g., 003)")
@click.pass_context
def gate(ctx, gate_name, spec_number):
    """Run a gate evaluation (activate, complete, checkpoint)."""
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not find project root.",
            err=True
        )
        sys.exit(1)

    import_harness(ctx)
    from harness.gates import GateEvaluator

    specs_dir = os.path.join(project_root, "specs")

    if gate_name in ("activate", "complete") and not spec_number:
        click.echo(
            click.style("Error: ", fg="red") +
            f"--spec is required for the {gate_name} gate.",
            err=True
        )
        sys.exit(1)

    evaluator = GateEvaluator(project_root)

    click.echo(click.style(
        f"Running {gate_name} gate"
        + (f" for spec {spec_number}" if spec_number else "")
        + " ...",
        bold=True
    ))

    # Run the appropriate gate
    if gate_name == "activate":
        spec_path = _find_spec_file(specs_dir, spec_number)
        if not spec_path:
            click.echo(click.style("Error: ", fg="red") + f"Spec {spec_number} not found.", err=True)
            sys.exit(1)
        result = evaluator.activation(spec_path)
    elif gate_name == "complete":
        spec_path = _find_spec_file(specs_dir, spec_number)
        if not spec_path:
            click.echo(click.style("Error: ", fg="red") + f"Spec {spec_number} not found.", err=True)
            sys.exit(1)
        result = evaluator.completion(spec_path)
    else:  # checkpoint
        result = evaluator.checkpoint()

    # Report individual checks
    for c in result.get("checks", []):
        desc = c.get("description", "")
        passed = c.get("passed", False)
        icon = click.style("PASS", fg="green") if passed else click.style("FAIL", fg="red")
        error_str = f" — {c['error']}" if c.get("error") and not passed else ""
        click.echo(f"  [{icon}] {desc}{error_str}")

    # Overall result
    if result.get("passed", False):
        click.echo(click.style("\nGate PASSED.", fg="green", bold=True))
        sys.exit(0)
    else:
        click.echo(click.style("\nGate FAILED.", fg="red", bold=True))
        sys.exit(1)
