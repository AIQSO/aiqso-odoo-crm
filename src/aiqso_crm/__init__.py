"""AIQSO CRM - Shared Odoo client library for lead management."""

__version__ = "0.9.0"

from aiqso_crm.client import OdooClient
from aiqso_crm.models import Company, Contact, Lead, LeadSource, PipelineStage, Tag, ValuationTier

__all__ = [
    "Company",
    "Contact",
    "Lead",
    "LeadSource",
    "OdooClient",
    "PipelineStage",
    "Tag",
    "ValuationTier",
]
