"""Category/tag management for Odoo CRM."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiqso_crm.models import ValuationTier

if TYPE_CHECKING:
    from aiqso_crm.client import OdooClient

# Standard category colors matching Odoo's color palette
CATEGORY_COLORS: dict[str, int] = {
    "Lead List": 10,  # Purple
    "For Sale": 11,  # Pink
    "Outreach Target": 4,  # Light blue
    "Construction": 2,  # Orange
    "Healthcare": 8,  # Dark purple
    "Technology": 7,  # Dark blue
    "Government": 9,  # Teal
    "Real Estate": 3,  # Green
    "Premium": 6,  # Red
    "High Value": 5,  # Yellow
    "Medium Value": 3,  # Green
    "Low Value": 1,  # Gray
}

TIER_TAG_NAMES: dict[ValuationTier, str] = {
    ValuationTier.PREMIUM: "Premium",
    ValuationTier.HIGH: "High Value",
    ValuationTier.MEDIUM: "Medium Value",
    ValuationTier.LOW: "Low Value",
}


class CategoryManager:
    """Manages Odoo partner categories with caching."""

    def __init__(self, client: OdooClient):
        self.client = client
        self._cache: dict[str, int] = {}

    def get_or_create(self, name: str, parent_id: int | None = None, color: int | None = None) -> int:
        """Get or create a category, using cache."""
        cache_key = f"{name}:{parent_id or 0}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        cid = self.client.get_or_create_category(name, parent_id=parent_id, color=color)
        self._cache[cache_key] = cid
        return cid

    def setup_lead_list_structure(self, industry: str | None = None) -> dict:
        """Create the standard lead list category hierarchy."""
        parent_id = self.get_or_create("Lead List", color=CATEGORY_COLORS["Lead List"])

        result = {
            "parent": parent_id,
            "for_sale": self.get_or_create("For Sale", parent_id, CATEGORY_COLORS["For Sale"]),
            "outreach": self.get_or_create("Outreach Target", parent_id, CATEGORY_COLORS["Outreach Target"]),
            "industry": None,
            "value_tiers": {},
        }

        if industry:
            result["industry"] = self.get_or_create(industry, parent_id, CATEGORY_COLORS.get(industry, 2))

        for _tier, tag_name in TIER_TAG_NAMES.items():
            result["value_tiers"][tag_name] = self.get_or_create(tag_name, parent_id, CATEGORY_COLORS.get(tag_name, 0))

        return result

    def get_value_tier_tag(self, tier: ValuationTier) -> int | None:
        """Get the tag ID for a valuation tier."""
        tag_name = TIER_TAG_NAMES.get(tier)
        if not tag_name:
            return None
        cache_key = f"{tag_name}:0"
        return self._cache.get(cache_key)
