#!/usr/bin/env python3
"""
HTH CLI — Central launchpad for all projects.

Usage:
    hth-platform env generate          Generate .env from .env.platform manifest
    hth-platform env show [key]        Show a credential from the vault
    hth-platform ssh                   Network-aware SSH to MacStudio
    hth-platform status                Check all MacStudio services
    hth-platform init <name>           Scaffold a new project from template
"""

import click
import os
import sys

# Add parent dir so commands can import shared code
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commands.env_generate import env_group
from commands.ssh_connect import ssh
from commands.status import status
from commands.init_project import init
from commands.harness import harness
from commands.adversarial import adversarial
from commands.start_cmd import start
from commands.checkpoint_cmd import checkpoint
from commands.refresh_cmd import refresh
from commands.scan_cmd import scan
from commands.drift_cmd import drift
from commands.serve_cmd import serve
from commands.runtime_cmd import runtime
from commands.chain_cmd import chain
from commands.ship_cmd import ship
from commands.bootstrap_cmd import bootstrap
from commands.project_cmd import project

PLATFORM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@click.group()
@click.pass_context
def cli(ctx):
    """HTH — Central launchpad for all projects."""
    ctx.ensure_object(dict)
    ctx.obj["platform_root"] = PLATFORM_ROOT


cli.add_command(env_group, "env")
cli.add_command(ssh)
cli.add_command(status)
cli.add_command(init)
cli.add_command(harness)
cli.add_command(adversarial)
cli.add_command(start)
cli.add_command(checkpoint)
cli.add_command(refresh)
cli.add_command(scan)
cli.add_command(drift)
cli.add_command(serve)
cli.add_command(runtime)
cli.add_command(chain)
cli.add_command(ship)
cli.add_command(bootstrap)
cli.add_command(project)


if __name__ == "__main__":
    cli()
