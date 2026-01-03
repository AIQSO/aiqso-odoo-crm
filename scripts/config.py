import os
from typing import Any


def _getenv(name: str, default=None):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def load_odoo_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Load Odoo XML-RPC connection settings from environment variables.

    Env vars:
      - ODOO_URL
      - ODOO_DB
      - ODOO_USERNAME
      - ODOO_API_KEY
    """
    config: dict[str, Any] = {
        "url": _getenv("ODOO_URL", "http://192.168.0.230:8069"),
        "db": _getenv("ODOO_DB", "aiqso_db"),
        "username": _getenv("ODOO_USERNAME", "quinn@aiqso.io"),
        "api_key": _getenv("ODOO_API_KEY", None),
    }
    if overrides:
        config.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return config


def load_postgres_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Load PostgreSQL connection settings from environment variables.

    Env vars:
      - POSTGRES_HOST
      - POSTGRES_PORT
      - POSTGRES_DB
      - POSTGRES_USER
      - POSTGRES_PASSWORD
    """
    config: dict[str, Any] = {
        "host": _getenv("POSTGRES_HOST", "192.168.0.71"),
        "port": int(_getenv("POSTGRES_PORT", 5433)),
        "database": _getenv("POSTGRES_DB", "permits_db"),
        "user": _getenv("POSTGRES_USER", "permits"),
        "password": _getenv("POSTGRES_PASSWORD", None),
    }
    if overrides:
        config.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return config


def require_config(config: dict[str, Any], required_keys: list[str], source_hint: str) -> None:
    missing = [k for k in required_keys if not config.get(k)]
    if not missing:
        return

    missing_str = ", ".join(missing)
    raise SystemExit(
        f"Missing required configuration values: {missing_str}. "
        f"Set them via environment variables ({source_hint}) or CLI flags."
    )


def get_odoo_connection() -> tuple[str, str, int, str]:
    """
    Establish XML-RPC connection to Odoo and return connection tuple.

    Returns:
        Tuple of (url, db, uid, api_key) for use with execute_kw calls.
    """
    import xmlrpc.client

    config = load_odoo_config()
    require_config(config, ["url", "db", "username", "api_key"], "ODOO_*")

    url = config["url"]
    db = config["db"]
    username = config["username"]
    api_key = config["api_key"]

    # Authenticate to get user ID
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, api_key, {})

    if not uid:
        raise SystemExit("Odoo authentication failed. Check your credentials.")

    return (url, db, uid, api_key)
