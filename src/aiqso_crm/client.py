"""Typed Odoo XML-RPC client with retry and caching."""

from __future__ import annotations

import logging
import os
import threading
import time
import xmlrpc.client
from typing import Any

logger = logging.getLogger(__name__)


class OdooConnectionError(Exception):
    """Raised when Odoo connection or authentication fails."""


class OdooClient:
    """Thread-safe Odoo XML-RPC client with retry and field caching.

    Usage:
        client = OdooClient.from_env()
        leads = client.search_read("crm.lead", [], fields=["name", "email_from"], limit=10)
    """

    def __init__(self, url: str, db: str, username: str, api_key: str):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.api_key = api_key
        self._uid: int | None = None
        self._lock = threading.Lock()
        self._common: xmlrpc.client.ServerProxy | None = None
        self._models: xmlrpc.client.ServerProxy | None = None
        self._field_cache: dict[str, set[str]] = {}

    @classmethod
    def from_env(cls) -> OdooClient:
        """Create client from environment variables."""
        url = os.getenv("ODOO_URL", "http://192.168.0.230:8069")
        db = os.getenv("ODOO_DB", "aiqso_db")
        username = os.getenv("ODOO_USERNAME", "quinn@aiqso.io")
        api_key = os.getenv("ODOO_API_KEY")
        if not api_key:
            raise OdooConnectionError("ODOO_API_KEY environment variable is required")
        return cls(url=url, db=db, username=username, api_key=api_key)

    @property
    def uid(self) -> int:
        """Authenticate and return cached UID."""
        if self._uid is not None:
            return self._uid
        with self._lock:
            if self._uid is not None:
                return self._uid
            self._uid = self._authenticate()
            return self._uid

    @property
    def common(self) -> xmlrpc.client.ServerProxy:
        if self._common is None:
            self._common = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/common", allow_none=True
            )
        return self._common

    @property
    def models(self) -> xmlrpc.client.ServerProxy:
        if self._models is None:
            self._models = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/object", allow_none=True
            )
        return self._models

    def _authenticate(self) -> int:
        """Authenticate with Odoo, retry on transient failures."""
        last_error = None
        for attempt in range(3):
            try:
                result = self.common.authenticate(self.db, self.username, self.api_key, {})
                if not result:
                    raise OdooConnectionError("Authentication failed - check credentials")
                logger.info("Authenticated to Odoo as UID %s", result)
                return int(result)
            except (ConnectionError, OSError, xmlrpc.client.ProtocolError) as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning("Auth attempt %d failed: %s, retrying in %ds", attempt + 1, e, wait)
                time.sleep(wait)
        raise OdooConnectionError(f"Failed to authenticate after 3 attempts: {last_error}")

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute an Odoo model method with retry on transient failures."""
        last_error = None
        for attempt in range(3):
            try:
                return self.models.execute_kw(
                    self.db, self.uid, self.api_key, model, method, list(args), kwargs
                )
            except xmlrpc.client.Fault:
                raise  # Application errors are not retryable
            except (ConnectionError, OSError, xmlrpc.client.ProtocolError) as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(
                    "execute(%s, %s) attempt %d failed: %s, retrying in %ds",
                    model, method, attempt + 1, e, wait,
                )
                time.sleep(wait)
                # Reset connection on failure
                self._models = None
                self._uid = None
        raise OdooConnectionError(f"execute({model}, {method}) failed after 3 attempts: {last_error}")

    # Convenience methods

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records."""
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain, **kwargs)

    def search(self, model: str, domain: list, limit: int | None = None) -> list[int]:
        """Search for record IDs."""
        kwargs: dict[str, Any] = {}
        if limit:
            kwargs["limit"] = limit
        return self.execute(model, "search", domain, **kwargs)

    def read(self, model: str, ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Read records by IDs."""
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute(model, "read", ids, **kwargs)

    def create(self, model: str, values: dict[str, Any]) -> int:
        """Create a record. Returns the new record ID."""
        result = self.execute(model, "create", [values])
        if isinstance(result, list):
            return result[0] if result else 0
        return int(result)

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        """Update records."""
        return self.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        """Delete records."""
        return self.execute(model, "unlink", ids)

    def fields_get(self, model: str) -> dict[str, Any]:
        """Get field definitions for a model (cached)."""
        if model not in self._field_cache:
            fields = self.execute(model, "fields_get", [], attributes=["string"])
            self._field_cache[model] = set(fields.keys()) if isinstance(fields, dict) else set()
        return {f: {} for f in self._field_cache[model]}

    def filter_values(self, model: str, values: dict[str, Any]) -> dict[str, Any]:
        """Filter dict to only include valid fields for the model."""
        if model not in self._field_cache:
            self.fields_get(model)
        allowed = self._field_cache.get(model, set())
        return {k: v for k, v in values.items() if k in allowed}

    def search_count(self, model: str, domain: list) -> int:
        """Count records matching domain."""
        return self.execute(model, "search_count", domain)

    # High-level helpers

    def get_or_create_partner(
        self,
        name: str,
        is_company: bool = False,
        email: str | None = None,
        phone: str | None = None,
        parent_id: int | None = None,
        category_ids: list[int] | None = None,
        **extra: Any,
    ) -> int:
        """Find existing partner by email/name or create new one."""
        # Search by email first (most reliable)
        if email:
            existing = self.search_read("res.partner", [("email", "=", email)], fields=["id"], limit=1)
            if existing:
                if category_ids:
                    self.write("res.partner", [existing[0]["id"]], {
                        "category_id": [(4, cid) for cid in category_ids]
                    })
                return existing[0]["id"]

        # Search by name + company type
        domain = [("name", "=", name), ("is_company", "=", is_company)]
        existing = self.search_read("res.partner", domain, fields=["id"], limit=1)
        if existing:
            if category_ids:
                self.write("res.partner", [existing[0]["id"]], {
                    "category_id": [(4, cid) for cid in category_ids]
                })
            return existing[0]["id"]

        # Create new
        values: dict[str, Any] = {
            "name": name,
            "is_company": is_company,
            "company_type": "company" if is_company else "person",
        }
        if email:
            values["email"] = email
        if phone:
            values["phone"] = phone
        if parent_id:
            values["parent_id"] = parent_id
        if category_ids:
            values["category_id"] = [(4, cid) for cid in category_ids]
        values.update(extra)
        return self.create("res.partner", values)

    def get_or_create_category(
        self, name: str, parent_id: int | None = None, color: int | None = None
    ) -> int:
        """Find or create a partner category/tag."""
        domain: list = [("name", "=", name)]
        if parent_id:
            domain.append(("parent_id", "=", parent_id))

        existing = self.search_read("res.partner.category", domain, fields=["id"], limit=1)
        if existing:
            return existing[0]["id"]

        values: dict[str, Any] = {"name": name}
        if parent_id:
            values["parent_id"] = parent_id
        if color is not None:
            values["color"] = color
        return self.create("res.partner.category", values)

    def get_pipeline_stages(self) -> list[dict[str, Any]]:
        """Get CRM pipeline stages."""
        return self.search_read(
            "crm.stage", [], fields=["name", "sequence"], order="sequence"
        )

    def move_lead_to_stage(self, lead_id: int, stage_name: str) -> bool:
        """Move a lead to a named stage."""
        stages = self.search_read("crm.stage", [("name", "=", stage_name)], fields=["id"], limit=1)
        if not stages:
            return False
        return self.write("crm.lead", [lead_id], {"stage_id": stages[0]["id"]})
