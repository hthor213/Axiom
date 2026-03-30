"""
hth-platform env generate — Generate .env from .env.platform manifest and encrypted vault.
hth-platform env show [path] — Show a credential value from the vault.
"""

import click
import os
import subprocess
import sys
import yaml
import re


def get_vault_path(platform_root):
    return os.path.join(platform_root, "credentials", "vault.yaml")


def get_vault_enc_path(platform_root):
    return os.path.join(platform_root, "credentials", "vault.enc")


def get_age_key_path(platform_root):
    return os.path.join(platform_root, "credentials", "age-key.txt")


def decrypt_vault(platform_root):
    """Decrypt vault.enc to vault.yaml if needed, then load it."""
    vault_path = get_vault_path(platform_root)
    vault_enc_path = get_vault_enc_path(platform_root)
    age_key_path = get_age_key_path(platform_root)

    # If decrypted vault exists and is newer than encrypted, use it
    if os.path.exists(vault_path):
        if not os.path.exists(vault_enc_path) or \
           os.path.getmtime(vault_path) >= os.path.getmtime(vault_enc_path):
            with open(vault_path) as f:
                return yaml.safe_load(f)

    # Decrypt
    if not os.path.exists(vault_enc_path):
        click.echo("Error: No vault.enc found. Run from the platform directory.", err=True)
        sys.exit(1)

    if not os.path.exists(age_key_path):
        click.echo("Error: No age-key.txt found. Copy your age key to credentials/age-key.txt", err=True)
        sys.exit(1)

    result = subprocess.run(
        ["age", "-d", "-i", age_key_path, vault_enc_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        click.echo(f"Error decrypting vault: {result.stderr}", err=True)
        sys.exit(1)

    # Write decrypted for caching (it's .gitignored)
    with open(vault_path, "w") as f:
        f.write(result.stdout)

    return yaml.safe_load(result.stdout)


def resolve_ref(vault, ref):
    """
    Resolve a vault reference like:
        anthropic[orchestrator-primary].key
        telegram.bot_token
        infrastructure.postgresql.host
    """
    # Handle array lookup: section[name].field
    array_match = re.match(r'^(\w+)\[([^\]]+)\]\.(\w+)$', ref)
    if array_match:
        section, name, field = array_match.groups()
        items = vault.get(section, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name") == name:
                    return str(item.get(field, ""))
        click.echo(f"  Warning: Could not resolve {ref}", err=True)
        return ""

    # Handle nested dict lookup: section.subsection.field
    parts = ref.split(".")
    current = vault
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            # Try to find by name
            found = None
            for item in current:
                if isinstance(item, dict) and item.get("name") == part:
                    found = item
                    break
            current = found
        else:
            click.echo(f"  Warning: Could not resolve {ref} (stuck at {part})", err=True)
            return ""
        if current is None:
            click.echo(f"  Warning: Could not resolve {ref} (missing {part})", err=True)
            return ""

    return str(current) if current is not None else ""


def interpolate_value(vault, value):
    """Replace ${vault.refs} in a value string."""
    def replacer(match):
        ref = match.group(1)
        return resolve_ref(vault, ref)

    # Handle ${...} interpolation
    if "${" in value:
        return re.sub(r'\$\{([^}]+)\}', replacer, value)

    # Handle direct vault reference (no ${})
    return resolve_ref(vault, value)


@click.group("env")
def env_group():
    """Credential and environment management."""
    pass


@env_group.command("generate")
@click.option("--manifest", "-m", default=".env.platform",
              help="Path to .env.platform manifest file")
@click.option("--output", "-o", default=".env",
              help="Output .env file path")
@click.option("--dry-run", is_flag=True, help="Print to stdout instead of writing")
@click.pass_context
def generate(ctx, manifest, output, dry_run):
    """Generate .env file from .env.platform manifest and encrypted vault."""
    platform_root = ctx.obj["platform_root"]

    if not os.path.exists(manifest):
        click.echo(f"Error: {manifest} not found in current directory.", err=True)
        click.echo("Create a .env.platform file declaring which vault credentials this project needs.", err=True)
        sys.exit(1)

    vault = decrypt_vault(platform_root)
    lines = []

    with open(manifest) as f:
        for line in f:
            line = line.rstrip("\n")

            # Pass through comments and blank lines
            if not line or line.startswith("#"):
                lines.append(line)
                continue

            # Parse KEY=vault_ref
            if "=" not in line:
                lines.append(line)
                continue

            key, ref = line.split("=", 1)
            key = key.strip()
            ref = ref.strip()

            # If it's a literal value (quoted or no vault ref), pass through
            if ref.startswith('"') or ref.startswith("'") or "." not in ref and "[" not in ref and "${" not in ref:
                lines.append(f"{key}={ref}")
                continue

            # Resolve vault reference
            resolved = interpolate_value(vault, ref)
            lines.append(f"{key}={resolved}")

    result = "\n".join(lines) + "\n"

    if dry_run:
        click.echo(result)
    else:
        with open(output, "w") as f:
            f.write(result)
        click.echo(f"Generated {output} from {manifest} ({len(lines)} lines)")


@env_group.command("show")
@click.argument("path")
@click.pass_context
def show(ctx, path):
    """Show a credential value from the vault. Example: hth-platform env show anthropic[orchestrator-primary].key"""
    platform_root = ctx.obj["platform_root"]
    vault = decrypt_vault(platform_root)
    value = resolve_ref(vault, path)
    if value:
        click.echo(value)
    else:
        click.echo(f"Not found: {path}", err=True)
        sys.exit(1)
