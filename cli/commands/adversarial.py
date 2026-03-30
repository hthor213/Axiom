"""
hth-platform adversarial — Adversarial evaluation pipeline.

Subcommands:
    hth-platform adversarial resolve    Resolve and cache model configuration
    hth-platform adversarial run        Run adversarial evaluation on files
    hth-platform adversarial report     Pretty-print the last evaluation report
"""

import click
import json
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


def import_adversarial(ctx):
    """Import adversarial modules, adding lib/python to sys.path if needed."""
    platform_root = ctx.obj["platform_root"]
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    try:
        import adversarial as adv
        return adv
    except ImportError as e:
        click.echo(
            click.style("Error: ", fg="red") +
            "Could not import adversarial modules from lib/python/adversarial/.",
            err=True
        )
        click.echo(f"  Import error: {e}", err=True)
        sys.exit(1)


@click.group()
@click.pass_context
def adversarial(ctx):
    """Adversarial evaluation pipeline."""
    ctx.ensure_object(dict)


@adversarial.command("resolve")
@click.pass_context
def resolve(ctx):
    """Resolve and cache current top-tier models from all three providers."""
    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: ", fg="red") + "Could not find project root.", err=True)
        sys.exit(1)

    import_adversarial(ctx)
    from adversarial.credentials import load_credentials
    from adversarial.model_resolver import resolve_models, save_cached_models

    platform_root = ctx.obj["platform_root"]
    creds = load_credentials(platform_root)

    missing = [k for k, v in creds.items() if not v]
    if missing:
        click.echo(click.style("Warning: ", fg="yellow") + f"Missing API keys: {', '.join(missing)}")

    click.echo("Querying provider APIs...")
    models = resolve_models(creds)
    save_cached_models(models, project_root)

    click.echo(click.style("\nResolved models:", bold=True))
    click.echo(f"  Author (Anthropic):     {click.style(models.anthropic, fg='cyan')}")
    click.echo(f"  Challenger (Google):    {click.style(models.google, fg='yellow')}")
    click.echo(f"  Arbiter (OpenAI):       {click.style(models.openai, fg='green')}")
    click.echo(f"  Resolved at:            {models.resolved_at}")

    if models.fallback_used:
        click.echo(click.style("\nFallbacks used:", fg="yellow"))
        for provider, reason in models.fallback_used.items():
            click.echo(f"  {provider}: {reason}")

    click.echo(f"\nCached to {click.style('.adversarial-models.json', dim=True)}")


@adversarial.command("run")
@click.argument("files", nargs=-1, type=click.Path())
@click.option("--diff", "diff_ref", default=None,
              help="Git ref to diff against (e.g., HEAD~1, main)")
@click.pass_context
def run(ctx, files, diff_ref):
    """Run adversarial evaluation on files."""
    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: ", fg="red") + "Could not find project root.", err=True)
        sys.exit(1)

    # Determine file list
    target_files = list(files)
    if diff_ref:
        try:
            result = subprocess.run(
                ["git", "diff", diff_ref, "--name-only"],
                capture_output=True, text=True, timeout=10, cwd=project_root
            )
            if result.returncode == 0:
                diff_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
                target_files.extend(diff_files)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            click.echo(click.style("Error: ", fg="red") + f"git diff failed: {e}", err=True)
            sys.exit(1)

    if not target_files:
        click.echo(click.style("Error: ", fg="red") + "No files specified.", err=True)
        click.echo("  Usage: hth-platform adversarial run file1.py file2.py", err=True)
        click.echo("         hth-platform adversarial run --diff HEAD~1", err=True)
        sys.exit(1)

    import_adversarial(ctx)
    from adversarial.credentials import load_credentials
    from adversarial.model_resolver import resolve_or_load
    from adversarial.adversarial import run_pipeline

    platform_root = ctx.obj["platform_root"]
    creds = load_credentials(platform_root)

    missing = [k for k, v in creds.items() if not v]
    if missing:
        click.echo(click.style("Warning: ", fg="yellow") + f"Missing API keys: {', '.join(missing)}")

    # Resolve or use cached models
    models = resolve_or_load(creds, project_root)

    click.echo(click.style(
        f"Running adversarial evaluation on {len(target_files)} file(s)...",
        bold=True
    ))
    click.echo(f"  Author:     {click.style(models.anthropic, fg='cyan')}")
    click.echo(f"  Challenger: {click.style(models.google, fg='yellow')}")
    click.echo(f"  Arbiter:    {click.style(models.openai, fg='green')}")
    click.echo()

    for f in target_files:
        click.echo(f"  {click.style(f, dim=True)}")
    click.echo()

    # Run pipeline
    report = run_pipeline(
        files=target_files,
        project_root=project_root,
        credentials=creds,
        models=models,
    )

    # Print verdict
    _print_verdict(report)

    verdict = report.get("verdict", "NEEDS_ATTENTION")
    if verdict == "PASS":
        sys.exit(0)
    elif verdict == "FAIL":
        sys.exit(1)
    else:
        sys.exit(2)


@adversarial.command("report")
@click.pass_context
def report(ctx):
    """Pretty-print the last evaluation report."""
    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: ", fg="red") + "Could not find project root.", err=True)
        sys.exit(1)

    report_path = os.path.join(project_root, ".adversarial-report.json")
    if not os.path.exists(report_path):
        click.echo("No adversarial report found. Run " +
                    click.style("hth-platform adversarial run", bold=True) + " first.")
        return

    with open(report_path) as f:
        report_data = json.load(f)

    _print_verdict(report_data)


def _print_verdict(report):
    """Print adversarial evaluation verdict."""
    verdict = report.get("verdict", "UNKNOWN")
    colors = {"PASS": "green", "FAIL": "red", "NEEDS_ATTENTION": "yellow"}
    color = colors.get(verdict, "white")

    click.echo(click.style(f"\n{'=' * 50}", dim=True))
    click.echo(click.style(f"  ADVERSARIAL EVALUATION: {verdict}", fg=color, bold=True))
    click.echo(click.style(f"{'=' * 50}", dim=True))

    # Files
    files = report.get("files_reviewed", [])
    if files:
        click.echo(f"\n  Files: {len(files)}")

    # Challenger summary
    ch = report.get("challenger", {})
    if ch.get("issues_found", 0) > 0:
        click.echo(f"\n  Challenger found {click.style(str(ch['issues_found']), bold=True)} issues:")
        for sev, count in ch.get("by_severity", {}).items():
            sev_color = {"critical": "red", "high": "red", "medium": "yellow", "low": "cyan"}.get(sev, "white")
            click.echo(f"    {click.style(sev.upper(), fg=sev_color)}: {count}")
    else:
        click.echo(f"\n  Challenger: {click.style('No issues found', fg='green')}")

    # Author response
    au = report.get("author", {})
    if au:
        click.echo(f"  Author: accepted {au.get('accepted', 0)}, rebutted {au.get('rebutted', 0)}")

    # Arbiter
    ar = report.get("arbiter")
    if ar:
        click.echo(f"  Arbiter: challenger wins {ar.get('challenger_wins', 0)}, "
                    f"author wins {ar.get('author_wins', 0)}")

    # Tests
    tests = report.get("tests_written", [])
    if tests:
        click.echo(f"\n  Tests written:")
        for t in tests:
            click.echo(f"    {click.style(t, fg='cyan')}")

    click.echo()
