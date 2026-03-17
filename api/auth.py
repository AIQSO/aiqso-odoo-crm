"""API key authentication middleware."""

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_valid_keys() -> set[str]:
    raw = os.getenv("API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


async def require_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Dependency that requires a valid API key."""
    valid_keys = _get_valid_keys()
    if not valid_keys:
        # No keys configured = auth disabled (backward compat)
        return "no-auth"
    if not api_key or api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


async def optional_api_key(api_key: str | None = Security(_api_key_header)) -> str | None:
    """Dependency that checks API key if configured, passes through otherwise."""
    valid_keys = _get_valid_keys()
    if not valid_keys:
        return None
    if not api_key or api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key
