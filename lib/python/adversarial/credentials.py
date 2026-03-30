"""
Load API keys for Anthropic, Google, and OpenAI.

Resolution order: environment variables first, then vault.yaml fallback.
"""

import os
from pathlib import Path
from typing import Optional


def _load_vault(platform_root: str) -> Optional[dict]:
    """Load and parse vault.yaml from the platform credentials directory."""
    vault_path = Path(platform_root) / "credentials" / "vault.yaml"
    if not vault_path.exists():
        return None
    try:
        import yaml
        with open(vault_path) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _find_named_key(items: list, name: str, field: str = "key") -> Optional[str]:
    """Find a named entry in a vault list and return the specified field."""
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            val = item.get(field)
            return str(val) if val is not None else None
    return None


def _deep_get(d: dict, *keys) -> Optional[str]:
    """Navigate nested dicts by key sequence, returning None on any miss."""
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
        if current is None:
            return None
    return str(current) if current is not None else None


def _read_dotenv(root: str) -> dict:
    """Read .env file, handling both KEY=VALUE and bare-value lines."""
    env_path = os.path.join(root, ".env") if root else ".env"
    result = {}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    result[key.strip()] = val.strip()
                elif line.startswith("AIza"):
                    # Bare Google API key
                    result["GOOGLE_API_KEY"] = line
                elif line.startswith("sk-ant-"):
                    result["ANTHROPIC_API_KEY"] = line
                elif line.startswith("sk-"):
                    result["OPENAI_API_KEY"] = line
    except FileNotFoundError:
        pass
    return result


def load_credentials(platform_root: str = None) -> dict:
    """Return {"anthropic": key, "openai": key, "google": key}.

    Resolution order: environment variables -> .env file -> vault.yaml.
    Missing keys are returned as None.
    """
    creds = {
        "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
        "openai": os.environ.get("OPENAI_API_KEY"),
        "google": os.environ.get("GOOGLE_API_KEY"),
    }

    # Try .env file for any missing keys
    if not all(creds.values()) and platform_root:
        dotenv = _read_dotenv(platform_root)
        for key in ("anthropic", "openai", "google"):
            if not creds[key]:
                env_key = f"{key.upper()}_API_KEY"
                creds[key] = dotenv.get(env_key)

    # SECURITY: Never fall back to reading vault directly.
    # Credentials come from env vars or .env file only (human-reviewed).
    # Use `hth-platform env generate` to populate .env from vault via manifest.
    return creds
