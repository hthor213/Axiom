"""
Platform Network Detection — Determine how to reach MacStudio.

Usage:
    from platform_network import resolve_macstudio_host
    host, network = resolve_macstudio_host()
    # host = "YOUR_LAN_IP", network = "LAN"
    # host = "100.125.149.26", network = "Tailscale"
    # host = "YOUR_EXTERNAL_IP", network = "External"
"""

import subprocess
from pathlib import Path

# Default IPs (can be overridden by loading services/macstudio.yaml)
LAN_IP = "YOUR_LAN_IP"
EXTERNAL_IP = "YOUR_EXTERNAL_IP"
TAILSCALE_IP = "100.125.149.26"


def _load_config():
    """Load MacStudio IPs from services config if available."""
    config_path = Path(__file__).parent.parent.parent / "services" / "macstudio.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
            server = config.get("server", {})
            return (
                server.get("lan_ip", LAN_IP),
                server.get("external_ip", EXTERNAL_IP),
                server.get("tailscale_ip", TAILSCALE_IP),
            )
        except Exception:
            pass
    return LAN_IP, EXTERNAL_IP, TAILSCALE_IP


def _ping(ip, timeout=1):
    """Check if an IP is reachable via ping."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            capture_output=True, timeout=timeout + 1
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def resolve_macstudio_host():
    """
    Detect the best way to reach MacStudio.
    Returns (host_ip, network_type) where network_type is "LAN", "Tailscale", or "External".
    """
    lan_ip, external_ip, tailscale_ip = _load_config()

    if _ping(lan_ip):
        return lan_ip, "LAN"
    if _ping(tailscale_ip):
        return tailscale_ip, "Tailscale"
    return external_ip, "External"


def ssh_command(extra_args=None):
    """Build an SSH command list for MacStudio."""
    host, network = resolve_macstudio_host()
    cmd = ["ssh", f"${os.environ.get("SSH_USER", "user")}@{host}"]
    if extra_args:
        cmd.extend(extra_args)
    return cmd, network
