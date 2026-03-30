"""
Platform Database Helpers — PostgreSQL connection for MacStudio.

Usage:
    from platform_db import get_connection_string, get_engine

    # Get connection string for a specific database
    url = get_connection_string("orchestrator_dev")

    # Get SQLAlchemy engine (requires sqlalchemy)
    engine = get_engine("orchestrator_dev")
"""

import os
from pathlib import Path


# Defaults from services/databases.yaml
DEFAULT_HOST = "YOUR_LAN_IP"
DEFAULT_PORT = 5433
DEFAULT_USER = "postgres"


def _load_config():
    """Load database config from services/databases.yaml."""
    config_path = Path(__file__).parent.parent.parent / "services" / "databases.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    return None


def _get_password():
    """Get PostgreSQL password from env or vault."""
    password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("MACSTUDIO_POSTGRES_PASSWORD")
    if password:
        return password

    vault_path = Path(__file__).parent.parent.parent / "credentials" / "vault.yaml"
    if vault_path.exists():
        try:
            import yaml
            with open(vault_path) as f:
                vault = yaml.safe_load(f)
            infra = vault.get("infrastructure", {})
            pg = infra.get("postgresql", {})
            passwords = pg.get("passwords", [])
            if passwords:
                return passwords[0].get("password", "")
        except Exception:
            pass

    return ""


def get_connection_string(database="orchestrator_dev", host=None, port=None, user=None, password=None):
    """Build a PostgreSQL connection string."""
    config = _load_config()
    pg = config.get("postgresql", {}) if config else {}

    host = host or os.environ.get("POSTGRES_HOST") or pg.get("host", DEFAULT_HOST)
    port = port or os.environ.get("POSTGRES_PORT") or pg.get("port", DEFAULT_PORT)
    user = user or os.environ.get("POSTGRES_USER") or pg.get("user", DEFAULT_USER)
    password = password or _get_password()

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_engine(database="orchestrator_dev", **kwargs):
    """Get a SQLAlchemy engine for a MacStudio PostgreSQL database."""
    try:
        from sqlalchemy import create_engine
    except ImportError:
        raise ImportError("sqlalchemy is required. Install with: pip install sqlalchemy")

    url = get_connection_string(database, **kwargs)
    return create_engine(url)
