"""
hth-platform ssh — Network-aware SSH to MacStudio.
Detects LAN vs external vs Tailscale and connects accordingly.
"""

import click
import subprocess
import sys
import os
import yaml


def load_macstudio_config(platform_root):
    config_path = os.path.join(platform_root, "services", "macstudio.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def detect_network(lan_ip):
    """Ping the LAN IP to detect if we're on the home network."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", lan_ip],
            capture_output=True, timeout=3
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_tailscale(tailscale_ip):
    """Check if Tailscale IP is reachable."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", tailscale_ip],
            capture_output=True, timeout=3
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@click.command()
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ssh(ctx, extra_args):
    """Network-aware SSH to MacStudio. Detects LAN/Tailscale/external automatically."""
    platform_root = ctx.obj["platform_root"]
    config = load_macstudio_config(platform_root)
    server = config["server"]

    user = server["user"]
    lan_ip = server["lan_ip"]
    external_ip = server["external_ip"]
    tailscale_ip = server["tailscale_ip"]

    # Detect best connection method
    if detect_network(lan_ip):
        host = lan_ip
        network = "LAN"
    elif detect_tailscale(tailscale_ip):
        host = tailscale_ip
        network = "Tailscale"
    else:
        host = external_ip
        network = "External"

    click.echo(f"Connecting to MacStudio via {network} ({host})")

    cmd = ["ssh", f"{user}@{host}"] + list(extra_args)
    os.execvp("ssh", cmd)
