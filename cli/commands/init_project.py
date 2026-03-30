"""
hth-platform init — Scaffold a new project from a template.
"""

import click
import os
import shutil


TEMPLATES = {
    "fastapi": "FastAPI + Python backend",
    "react-vite": "React + Vite frontend",
}


@click.command()
@click.argument("name")
@click.option("--template", "-t", type=click.Choice(list(TEMPLATES.keys())),
              default="fastapi", help="Project template to use")
@click.option("--dir", "-d", "target_dir", default=None,
              help="Target directory (default: ~/Documents/GitHub/<name>)")
@click.pass_context
def init(ctx, name, template, target_dir):
    """Scaffold a new project from a template."""
    platform_root = ctx.obj["platform_root"]

    if target_dir is None:
        github_dir = os.path.dirname(platform_root)
        target_dir = os.path.join(github_dir, name)

    if os.path.exists(target_dir):
        click.echo(f"Error: {target_dir} already exists.", err=True)
        raise SystemExit(1)

    template_dir = os.path.join(platform_root, "templates", template)
    shared_dir = os.path.join(platform_root, "templates", "shared")

    if not os.path.exists(template_dir):
        click.echo(f"Error: Template '{template}' not found at {template_dir}", err=True)
        raise SystemExit(1)

    # Copy template
    shutil.copytree(template_dir, target_dir)

    # Copy shared files (don't overwrite)
    if os.path.exists(shared_dir):
        for item in os.listdir(shared_dir):
            src = os.path.join(shared_dir, item)
            dst = os.path.join(target_dir, item)
            if not os.path.exists(dst):
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

    click.echo(f"Created {template} project at {target_dir}")
    click.echo(f"\nNext steps:")
    click.echo(f"  cd {target_dir}")
    click.echo(f"  # Edit .env.platform to declare which credentials you need")
    click.echo(f"  hth-platform env generate")
    click.echo(f"  git init && git add -A && git commit -m 'Initial scaffold from hth-platform'")
