"""Canonical data models for CRM operations."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ValuationTier(str, Enum):
    PREMIUM = "premium"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @classmethod
    def from_value(cls, valuation: float) -> ValuationTier:
        if valuation >= 500_000:
            return cls.PREMIUM
        if valuation >= 100_000:
            return cls.HIGH
        if valuation >= 25_000:
            return cls.MEDIUM
        if valuation > 0:
            return cls.LOW
        return cls.UNKNOWN


class LeadSource(str, Enum):
    CSV_IMPORT = "csv_import"
    POSTGRES_SYNC = "postgres_sync"
    API_INGEST = "api_ingest"
    ACCELA = "accela"
    SAMGOV = "samgov"
    MANUAL = "manual"
    PHONE = "phone"
    WEB = "web"


class Lead(BaseModel):
    """Unified lead model covering all import sources."""

    name: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company_name: str | None = None
    expected_revenue: float = 0
    description: str | None = None
    source: LeadSource = LeadSource.MANUAL
    source_id: str | None = None  # external reference (permit_number, notice_id, etc.)
    valuation_tier: ValuationTier = ValuationTier.UNKNOWN
    score: float | None = None
    permit_number: str | None = None
    permit_type: str | None = None
    owner_name: str | None = None
    contact_role: str | None = None
    industry: str | None = None
    city: str | None = None
    address: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Populated after sync to Odoo
    odoo_lead_id: int | None = None
    odoo_partner_id: int | None = None
    odoo_company_id: int | None = None

    @field_validator("contact_phone", mode="before")
    @classmethod
    def normalize_phone(cls, v: Any) -> str | None:
        if not v:
            return None
        phone = re.sub(r"[^\d+]", "", str(v))
        if phone.startswith("+1"):
            phone = phone[2:]
        elif phone.startswith("1") and len(phone) == 11:
            phone = phone[1:]
        if len(phone) == 10:
            return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
        return phone or None

    @field_validator("contact_email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> str | None:
        if not v or str(v).strip() == "":
            return None
        return str(v).strip().lower()

    def to_odoo_lead_values(self) -> dict[str, Any]:
        """Convert to Odoo crm.lead field values."""
        values: dict[str, Any] = {
            "name": self.name,
            "type": "lead",
        }
        if self.contact_name:
            values["contact_name"] = self.contact_name
        if self.contact_email:
            values["email_from"] = self.contact_email
        if self.contact_phone:
            values["phone"] = self.contact_phone
        if self.company_name:
            values["partner_name"] = self.company_name
        if self.expected_revenue:
            values["expected_revenue"] = self.expected_revenue
        if self.description:
            values["description"] = self.description
        if self.address:
            values["street"] = self.address
        if self.source_id:
            values["ref"] = self.source_id
        return values


class Contact(BaseModel):
    """Contact/person model."""

    name: str
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    role: str | None = None
    odoo_id: int | None = None
    odoo_company_id: int | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v: Any) -> str | None:
        return Lead.normalize_phone(v)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> str | None:
        return Lead.normalize_email(v)


class Company(BaseModel):
    """Company model."""

    name: str
    industry: str | None = None
    city: str | None = None
    address: str | None = None
    odoo_id: int | None = None
    tags: list[str] = Field(default_factory=list)


class Tag(BaseModel):
    """CRM tag/category."""

    name: str
    color: int = 0
    parent_name: str | None = None
    odoo_id: int | None = None


class PipelineStage(BaseModel):
    """CRM pipeline stage."""

    name: str
    sequence: int = 0
    odoo_id: int | None = None


class DuplicateMatch(BaseModel):
    """Result of a duplicate check."""

    odoo_id: int
    name: str
    match_type: str  # "email", "phone", "company_name", "fuzzy_name"
    confidence: float  # 0.0 - 1.0
    existing_email: str | None = None
    existing_phone: str | None = None


class LeadAnalysis(BaseModel):
    """AI-generated lead analysis."""

    lead_id: int | None = None
    industry_classification: str | None = None
    quality_score: float | None = None
    quality_reasoning: str | None = None
    outreach_suggestion: str | None = None
    competitive_intel: str | None = None
