"""
hth-platform status — Check health of all MacStudio services.
"""

import click
import os
import yaml
import subprocess
import socket


def load_macstudio_config(platform_root):
    config_path = os.path.join(platform_root, "services", "macstudio.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def check_port(host, port, timeout=2):
    """Check if a TCP port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except (socket.error, OSError):
        return False


def check_http(url, timeout=3):
    """Check if an HTTP endpoint responds."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status == 200
    except Exception:
        return False


@click.command()
@click.option("--host", default=None, help="Override MacStudio host (default: auto-detect)")
@click.pass_context
def status(ctx, host):
    """Check health of all MacStudio services."""
    platform_root = ctx.obj["platform_root"]
    config = load_macstudio_config(platform_root)
    server = config["server"]

    # Auto-detect host
    if host is None:
        from commands.ssh_connect import detect_network, detect_tailscale
        lan_ip = server["lan_ip"]
        tailscale_ip = server["tailscale_ip"]
        external_ip = server["external_ip"]

        if detect_network(lan_ip):
            host = lan_ip
            network = "LAN"
        elif detect_tailscale(tailscale_ip):
            host = tailscale_ip
            network = "Tailscale"
        else:
            host = external_ip
            network = "External"
        click.echo(f"Checking MacStudio via {network} ({host})\n")
    else:
        click.echo(f"Checking MacStudio at {host}\n")

    services = config.get("services", {})
    results = []

    for name, svc in services.items():
        port = svc.get("port")
        health = svc.get("health_endpoint")
        protected = svc.get("protected", False)

        # Check port
        port_ok = check_port(host, port) if port else None

        # Check health endpoint if available
        health_ok = None
        if health and port_ok:
            health_url = health.replace("localhost", host).replace("127.0.0.1", host)
            health_ok = check_http(health_url)

        # Format result
        if port_ok is False:
            status_str = click.style("DOWN", fg="red")
        elif health_ok is False:
            status_str = click.style("PORT OK / HEALTH FAIL", fg="yellow")
        elif health_ok is True:
            status_str = click.style("HEALTHY", fg="green")
        elif port_ok is True:
            status_str = click.style("UP", fg="green")
        else:
            status_str = click.style("UNKNOWN", fg="yellow")

        lock = " [PROTECTED]" if protected else ""
        results.append((name, port, status_str, lock))

    # Print table
    max_name = max(len(r[0]) for r in results)
    for name, port, st, lock in results:
        port_str = f":{port}" if port else "    "
        click.echo(f"  {name:<{max_name}}  {port_str:<6}  {st}{lock}")
