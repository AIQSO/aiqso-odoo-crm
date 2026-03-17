"""Cross-source lead deduplication engine."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiqso_crm.models import DuplicateMatch, Lead

if TYPE_CHECKING:
    from aiqso_crm.client import OdooClient

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str | None) -> str:
    """Strip to 10 digits for comparison."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    return digits


def _normalize_email(email: str | None) -> str:
    if not email:
        return ""
    return email.strip().lower()


def _fuzzy_company_match(name1: str, name2: str) -> float:
    """Simple fuzzy company name match (0.0 - 1.0) without external deps."""
    a = _clean_company_name(name1)
    b = _clean_company_name(name2)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Check containment
    if a in b or b in a:
        return 0.85
    # Jaccard similarity on words
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _clean_company_name(name: str) -> str:
    """Remove common suffixes and normalize."""
    name = name.lower().strip()
    for suffix in ["llc", "inc", "corp", "ltd", "co", "company", "group", "holdings", "enterprises"]:
        name = re.sub(rf"\b{suffix}\.?\b", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(name.split())


class DeduplicationEngine:
    """Find and merge duplicate leads/contacts in Odoo."""

    def __init__(self, client: OdooClient, fuzzy_threshold: float = 0.8):
        self.client = client
        self.fuzzy_threshold = fuzzy_threshold

    def find_lead_duplicates(self, lead: Lead) -> list[DuplicateMatch]:
        """Find potential duplicates for a lead before creating it."""
        matches: list[DuplicateMatch] = []

        # 1. Exact email match
        if lead.contact_email:
            email = _normalize_email(lead.contact_email)
            existing = self.client.search_read(
                "crm.lead",
                [("email_from", "=ilike", email)],
                fields=["id", "name", "email_from", "phone"],
                limit=5,
            )
            for r in existing:
                matches.append(
                    DuplicateMatch(
                        odoo_id=r["id"],
                        name=r["name"],
                        match_type="email",
                        confidence=1.0,
                        existing_email=r.get("email_from"),
                        existing_phone=r.get("phone"),
                    )
                )

        # 2. Phone match
        if lead.contact_phone and not matches:
            phone_digits = _normalize_phone(lead.contact_phone)
            if len(phone_digits) >= 10:
                existing = self.client.search_read(
                    "crm.lead",
                    [("phone", "ilike", phone_digits[-7:])],  # last 7 digits
                    fields=["id", "name", "email_from", "phone"],
                    limit=10,
                )
                for r in existing:
                    if _normalize_phone(r.get("phone")) == phone_digits:
                        matches.append(
                            DuplicateMatch(
                                odoo_id=r["id"],
                                name=r["name"],
                                match_type="phone",
                                confidence=0.95,
                                existing_email=r.get("email_from"),
                                existing_phone=r.get("phone"),
                            )
                        )

        # 3. Source ID match (permit number, notice ID, etc.)
        if lead.source_id and not matches:
            existing = self.client.search_read(
                "crm.lead",
                [("ref", "=", lead.source_id)],
                fields=["id", "name", "email_from", "phone"],
                limit=3,
            )
            for r in existing:
                matches.append(
                    DuplicateMatch(
                        odoo_id=r["id"],
                        name=r["name"],
                        match_type="source_id",
                        confidence=0.98,
                        existing_email=r.get("email_from"),
                        existing_phone=r.get("phone"),
                    )
                )

        # 4. Fuzzy company name match
        if lead.company_name and not matches:
            # Search for similar company names
            words = lead.company_name.split()[:2]  # first 2 words
            if words:
                existing = self.client.search_read(
                    "crm.lead",
                    [("partner_name", "ilike", words[0])],
                    fields=["id", "name", "partner_name", "email_from", "phone"],
                    limit=20,
                )
                for r in existing:
                    if r.get("partner_name"):
                        score = _fuzzy_company_match(lead.company_name, r["partner_name"])
                        if score >= self.fuzzy_threshold:
                            matches.append(
                                DuplicateMatch(
                                    odoo_id=r["id"],
                                    name=r["name"],
                                    match_type="fuzzy_name",
                                    confidence=score,
                                    existing_email=r.get("email_from"),
                                    existing_phone=r.get("phone"),
                                )
                            )

        # Sort by confidence descending
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def find_contact_duplicates(
        self, email: str | None = None, phone: str | None = None, name: str | None = None
    ) -> list[DuplicateMatch]:
        """Find duplicate contacts."""
        matches: list[DuplicateMatch] = []

        if email:
            existing = self.client.search_read(
                "res.partner",
                [("email", "=ilike", _normalize_email(email))],
                fields=["id", "name", "email", "phone"],
                limit=5,
            )
            for r in existing:
                matches.append(
                    DuplicateMatch(
                        odoo_id=r["id"],
                        name=r["name"],
                        match_type="email",
                        confidence=1.0,
                        existing_email=r.get("email"),
                        existing_phone=r.get("phone"),
                    )
                )

        if phone and not matches:
            phone_digits = _normalize_phone(phone)
            if len(phone_digits) >= 10:
                existing = self.client.search_read(
                    "res.partner",
                    [("phone", "ilike", phone_digits[-7:])],
                    fields=["id", "name", "email", "phone"],
                    limit=10,
                )
                for r in existing:
                    if _normalize_phone(r.get("phone")) == phone_digits:
                        matches.append(
                            DuplicateMatch(
                                odoo_id=r["id"],
                                name=r["name"],
                                match_type="phone",
                                confidence=0.95,
                                existing_email=r.get("email"),
                                existing_phone=r.get("phone"),
                            )
                        )

        return matches

    def merge_leads(self, winner_id: int, loser_ids: list[int]) -> dict:
        """Merge duplicate leads - keep winner, archive losers."""
        winner = self.client.read(
            "crm.lead",
            [winner_id],
            fields=[
                "name",
                "email_from",
                "phone",
                "partner_name",
                "description",
                "expected_revenue",
                "contact_name",
            ],
        )
        if not winner:
            return {"error": f"Winner lead {winner_id} not found"}

        winner = winner[0]
        merged_count = 0

        for loser_id in loser_ids:
            loser = self.client.read(
                "crm.lead",
                [loser_id],
                fields=[
                    "name",
                    "email_from",
                    "phone",
                    "partner_name",
                    "description",
                    "expected_revenue",
                    "contact_name",
                ],
            )
            if not loser:
                continue
            loser = loser[0]

            # Fill in missing fields from loser
            updates: dict = {}
            if not winner.get("email_from") and loser.get("email_from"):
                updates["email_from"] = loser["email_from"]
            if not winner.get("phone") and loser.get("phone"):
                updates["phone"] = loser["phone"]
            if not winner.get("contact_name") and loser.get("contact_name"):
                updates["contact_name"] = loser["contact_name"]
            if loser.get("expected_revenue", 0) > winner.get("expected_revenue", 0):
                updates["expected_revenue"] = loser["expected_revenue"]

            # Append loser description
            if loser.get("description"):
                current_desc = winner.get("description") or ""
                updates["description"] = (
                    f"{current_desc}\n\n--- Merged from: {loser['name']} ---\n{loser['description']}"
                )

            if updates:
                self.client.write("crm.lead", [winner_id], updates)

            # Archive the loser
            self.client.write("crm.lead", [loser_id], {"active": False})
            merged_count += 1

        return {"winner_id": winner_id, "merged": merged_count}
