#!/usr/bin/env python3
"""AIQSO Odoo CRM MCP Server - Full-featured CRM operations via MCP protocol."""

import asyncio
import json
import logging
import os
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

# Add parent paths so we can import the shared library
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aiqso_crm.client import OdooClient, OdooConnectionError
from aiqso_crm.dedup import DeduplicationEngine
from aiqso_crm.enrichment import OllamaEnrichmentClient
from aiqso_crm.models import Lead, LeadSource
from aiqso_crm.scoring import LeadScoringEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("odoo-crm-mcp")

server = Server("aiqso-odoo-crm")

# Lazy-initialized singletons
_client: OdooClient | None = None
_dedup: DeduplicationEngine | None = None
_scorer: LeadScoringEngine | None = None
_enrichment: OllamaEnrichmentClient | None = None


def get_client() -> OdooClient:
    global _client
    if _client is None:
        _client = OdooClient.from_env()
    return _client


def get_dedup() -> DeduplicationEngine:
    global _dedup
    if _dedup is None:
        _dedup = DeduplicationEngine(get_client())
    return _dedup


def get_scorer() -> LeadScoringEngine:
    global _scorer
    if _scorer is None:
        _scorer = LeadScoringEngine()
    return _scorer


def get_enrichment() -> OllamaEnrichmentClient:
    global _enrichment
    if _enrichment is None:
        _enrichment = OllamaEnrichmentClient(
            base_url=os.getenv("OLLAMA_URL", "http://192.168.0.234:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        )
    return _enrichment


def _text(content: str) -> list[TextContent]:
    return [TextContent(type="text", text=content)]


def _json_text(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


# =============================================================================
# Lead Tools
# =============================================================================


@server.tool()
async def crm_search_leads(
    query: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    min_revenue: float | None = None,
    limit: int = 20,
) -> list[TextContent]:
    """Search CRM leads with filters. Use query for text search, stage for pipeline stage, source for lead source."""
    client = get_client()
    domain: list = []

    if query:
        domain.append("|")
        domain.append(("name", "ilike", query))
        domain.append(("partner_name", "ilike", query))
    if stage:
        domain.append(("stage_id.name", "=", stage))
    if source:
        domain.append(("ref", "ilike", source))
    if min_revenue:
        domain.append(("expected_revenue", ">=", min_revenue))

    leads = client.search_read(
        "crm.lead",
        domain,
        fields=[
            "name",
            "partner_name",
            "email_from",
            "phone",
            "expected_revenue",
            "stage_id",
            "create_date",
            "ref",
            "contact_name",
        ],
        limit=limit,
        order="create_date desc",
    )
    return _json_text({"count": len(leads), "leads": leads})


@server.tool()
async def crm_get_lead(lead_id: int) -> list[TextContent]:
    """Get full details of a CRM lead by ID."""
    client = get_client()
    leads = client.read("crm.lead", [lead_id])
    if not leads:
        return _text(f"Lead {lead_id} not found")
    return _json_text(leads[0])


@server.tool()
async def crm_create_lead(
    name: str,
    company_name: str | None = None,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    expected_revenue: float = 0,
    description: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
) -> list[TextContent]:
    """Create a new CRM lead with optional duplicate checking."""
    client = get_client()
    dedup = get_dedup()

    lead = Lead(
        name=name,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=email,
        contact_phone=phone,
        expected_revenue=expected_revenue,
        description=description,
        source=LeadSource(source) if source else LeadSource.MANUAL,
        tags=tags or [],
    )

    # Check for duplicates
    duplicates = dedup.find_lead_duplicates(lead)
    if duplicates:
        return _json_text(
            {
                "warning": "Potential duplicates found",
                "duplicates": [d.model_dump() for d in duplicates[:5]],
                "message": "Use crm_create_lead_force to create anyway, or crm_update_lead to update existing.",
            }
        )

    lead_id = client.create("crm.lead", lead.to_odoo_lead_values())
    return _json_text({"success": True, "lead_id": lead_id, "name": name})


@server.tool()
async def crm_create_lead_force(
    name: str,
    company_name: str | None = None,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    expected_revenue: float = 0,
    description: str | None = None,
) -> list[TextContent]:
    """Create a CRM lead without duplicate checking."""
    client = get_client()
    lead = Lead(
        name=name,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=email,
        contact_phone=phone,
        expected_revenue=expected_revenue,
        description=description,
    )
    lead_id = client.create("crm.lead", lead.to_odoo_lead_values())
    return _json_text({"success": True, "lead_id": lead_id})


@server.tool()
async def crm_update_lead(lead_id: int, **updates: Any) -> list[TextContent]:
    """Update a CRM lead. Pass field names as keyword arguments."""
    client = get_client()
    # Map friendly names to Odoo fields
    field_map = {
        "email": "email_from",
        "company_name": "partner_name",
        "revenue": "expected_revenue",
    }
    odoo_values = {}
    for k, v in updates.items():
        odoo_key = field_map.get(k, k)
        odoo_values[odoo_key] = v

    filtered = client.filter_values("crm.lead", odoo_values)
    if not filtered:
        return _text("No valid fields to update")

    client.write("crm.lead", [lead_id], filtered)
    return _json_text({"success": True, "lead_id": lead_id, "updated_fields": list(filtered.keys())})


@server.tool()
async def crm_score_lead(lead_id: int) -> list[TextContent]:
    """Calculate quality score for a lead."""
    client = get_client()
    scorer = get_scorer()

    leads = client.read(
        "crm.lead",
        [lead_id],
        fields=[
            "name",
            "email_from",
            "phone",
            "partner_name",
            "expected_revenue",
            "contact_name",
            "ref",
            "description",
        ],
    )
    if not leads:
        return _text(f"Lead {lead_id} not found")

    data = leads[0]
    lead = Lead(
        name=data["name"],
        contact_email=data.get("email_from"),
        contact_phone=data.get("phone"),
        company_name=data.get("partner_name"),
        expected_revenue=float(data.get("expected_revenue") or 0),
        contact_name=data.get("contact_name"),
        source_id=data.get("ref"),
    )
    score = scorer.score(lead)
    tier = scorer.tier(lead.expected_revenue)

    return _json_text(
        {
            "lead_id": lead_id,
            "score": round(score, 1),
            "tier": tier.value,
            "breakdown": {
                "has_email": bool(lead.contact_email),
                "has_phone": bool(lead.contact_phone),
                "has_company": bool(lead.company_name),
                "revenue": lead.expected_revenue,
            },
        }
    )


@server.tool()
async def crm_enrich_lead(lead_id: int) -> list[TextContent]:
    """Use AI to analyze and enrich a lead with industry classification and outreach suggestions."""
    client = get_client()
    enrichment = get_enrichment()

    leads = client.read(
        "crm.lead",
        [lead_id],
        fields=[
            "name",
            "email_from",
            "phone",
            "partner_name",
            "expected_revenue",
            "contact_name",
            "description",
            "ref",
        ],
    )
    if not leads:
        return _text(f"Lead {lead_id} not found")

    data = leads[0]
    lead = Lead(
        name=data["name"],
        contact_email=data.get("email_from"),
        contact_phone=data.get("phone"),
        company_name=data.get("partner_name"),
        expected_revenue=float(data.get("expected_revenue") or 0),
        contact_name=data.get("contact_name"),
        description=data.get("description"),
        odoo_lead_id=lead_id,
    )

    analysis = await enrichment.assess_lead_quality(lead)
    return _json_text(analysis.model_dump())


# =============================================================================
# Pipeline Tools
# =============================================================================


@server.tool()
async def crm_pipeline_summary() -> list[TextContent]:
    """Get pipeline summary with lead counts and revenue per stage."""
    client = get_client()
    stages = client.get_pipeline_stages()

    summary = []
    total_revenue = 0
    total_leads = 0

    for stage in stages:
        leads = client.search_read(
            "crm.lead",
            [("stage_id", "=", stage["id"]), ("active", "=", True)],
            fields=["expected_revenue"],
        )
        count = len(leads)
        revenue = sum(float(lead.get("expected_revenue") or 0) for lead in leads)
        total_leads += count
        total_revenue += revenue
        summary.append(
            {
                "stage": stage["name"],
                "stage_id": stage["id"],
                "leads": count,
                "revenue": round(revenue, 2),
            }
        )

    return _json_text(
        {
            "stages": summary,
            "total_leads": total_leads,
            "total_revenue": round(total_revenue, 2),
        }
    )


@server.tool()
async def crm_move_lead_stage(lead_id: int, stage_name: str) -> list[TextContent]:
    """Move a lead to a different pipeline stage."""
    client = get_client()
    success = client.move_lead_to_stage(lead_id, stage_name)
    if not success:
        return _text(f"Stage '{stage_name}' not found")
    return _json_text({"success": True, "lead_id": lead_id, "new_stage": stage_name})


@server.tool()
async def crm_stale_leads(days: int = 30, limit: int = 50) -> list[TextContent]:
    """Find leads with no activity in the last N days."""
    client = get_client()
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    leads = client.search_read(
        "crm.lead",
        [("write_date", "<", cutoff), ("active", "=", True)],
        fields=["name", "partner_name", "email_from", "stage_id", "write_date", "expected_revenue"],
        limit=limit,
        order="write_date asc",
    )
    return _json_text({"stale_count": len(leads), "cutoff_date": cutoff, "leads": leads})


# =============================================================================
# Duplicate Tools
# =============================================================================


@server.tool()
async def crm_find_duplicates(
    email: str | None = None,
    phone: str | None = None,
    company_name: str | None = None,
) -> list[TextContent]:
    """Find potential duplicate leads by email, phone, or company name."""
    dedup = get_dedup()
    lead = Lead(
        name="search",
        contact_email=email,
        contact_phone=phone,
        company_name=company_name,
    )
    matches = dedup.find_lead_duplicates(lead)
    return _json_text(
        {
            "duplicates_found": len(matches),
            "matches": [m.model_dump() for m in matches],
        }
    )


@server.tool()
async def crm_merge_leads(winner_id: int, loser_ids: list[int]) -> list[TextContent]:
    """Merge duplicate leads. Winner keeps data, losers are archived."""
    dedup = get_dedup()
    result = dedup.merge_leads(winner_id, loser_ids)
    return _json_text(result)


# =============================================================================
# Contact/Customer Tools
# =============================================================================


@server.tool()
async def crm_search_customers(
    query: str,
    is_company: bool | None = None,
    limit: int = 20,
) -> list[TextContent]:
    """Search customers/contacts by name or email."""
    client = get_client()
    domain: list = ["|", ("name", "ilike", query), ("email", "ilike", query)]
    if is_company is not None:
        domain = [("is_company", "=", is_company), *domain]

    customers = client.search_read(
        "res.partner",
        domain,
        fields=["name", "email", "phone", "company_type", "city", "is_company", "parent_id"],
        limit=limit,
    )
    return _json_text({"count": len(customers), "customers": customers})


@server.tool()
async def crm_create_customer(
    name: str,
    email: str | None = None,
    phone: str | None = None,
    is_company: bool = True,
) -> list[TextContent]:
    """Create a new customer/contact."""
    client = get_client()
    partner_id = client.get_or_create_partner(
        name=name,
        is_company=is_company,
        email=email,
        phone=phone,
    )
    return _json_text({"success": True, "partner_id": partner_id, "name": name})


# =============================================================================
# Tag Tools
# =============================================================================


@server.tool()
async def crm_list_tags(parent_name: str | None = None) -> list[TextContent]:
    """List all CRM tags/categories, optionally filtered by parent."""
    client = get_client()
    domain: list = []
    if parent_name:
        domain.append(("parent_id.name", "=", parent_name))

    tags = client.search_read(
        "res.partner.category",
        domain,
        fields=["name", "color", "parent_id"],
        order="name",
    )
    return _json_text({"count": len(tags), "tags": tags})


@server.tool()
async def crm_tag_lead(lead_id: int, tag_names: list[str]) -> list[TextContent]:
    """Add tags to a lead's partner. Creates tags if they don't exist."""
    client = get_client()

    # Get the lead's partner
    leads = client.read("crm.lead", [lead_id], fields=["partner_id"])
    if not leads or not leads[0].get("partner_id"):
        return _text(f"Lead {lead_id} has no associated partner")

    partner_id = leads[0]["partner_id"][0]

    tag_ids = []
    for name in tag_names:
        tag_id = client.get_or_create_category(name)
        tag_ids.append(tag_id)

    client.write("res.partner", [partner_id], {"category_id": [(4, tid) for tid in tag_ids]})
    return _json_text({"success": True, "partner_id": partner_id, "tags_added": tag_names})


# =============================================================================
# Analytics Tools
# =============================================================================


@server.tool()
async def crm_source_performance() -> list[TextContent]:
    """Analyze lead source performance - count and revenue by source."""
    client = get_client()

    # Get all active leads
    leads = client.search_read(
        "crm.lead",
        [("active", "=", True)],
        fields=["ref", "expected_revenue", "stage_id", "create_date"],
    )

    sources: dict[str, dict] = {}
    for lead in leads:
        ref = lead.get("ref") or ""
        if ref.startswith("SAMGOV"):
            source = "SAM.gov"
        elif ref.startswith("ACCELA") or "[" in (lead.get("name") or ""):
            source = "Accela/Permits"
        elif ref.startswith("cs_"):
            source = "Stripe"
        else:
            source = "Other"

        if source not in sources:
            sources[source] = {"count": 0, "revenue": 0, "stages": {}}

        sources[source]["count"] += 1
        sources[source]["revenue"] += float(lead.get("expected_revenue") or 0)

        stage_name = lead.get("stage_id", [0, "Unknown"])[1] if lead.get("stage_id") else "Unknown"
        sources[source]["stages"][stage_name] = sources[source]["stages"].get(stage_name, 0) + 1

    return _json_text(sources)


@server.tool()
async def crm_revenue_forecast() -> list[TextContent]:
    """Pipeline revenue forecast by stage with weighted probabilities."""
    client = get_client()
    stage_weights = {"New": 0.1, "Qualified": 0.3, "Proposition": 0.6, "Won": 1.0}

    stages = client.get_pipeline_stages()
    forecast = []
    total_weighted = 0

    for stage in stages:
        leads = client.search_read(
            "crm.lead",
            [("stage_id", "=", stage["id"]), ("active", "=", True)],
            fields=["expected_revenue"],
        )
        raw_revenue = sum(float(lead.get("expected_revenue") or 0) for lead in leads)
        weight = stage_weights.get(stage["name"], 0.2)
        weighted = raw_revenue * weight
        total_weighted += weighted

        forecast.append(
            {
                "stage": stage["name"],
                "leads": len(leads),
                "raw_revenue": round(raw_revenue, 2),
                "probability": weight,
                "weighted_revenue": round(weighted, 2),
            }
        )

    return _json_text(
        {
            "forecast": forecast,
            "total_weighted_revenue": round(total_weighted, 2),
        }
    )


@server.tool()
async def crm_lead_aging() -> list[TextContent]:
    """Lead aging report - distribution of leads by age."""
    client = get_client()
    from datetime import datetime, timedelta

    now = datetime.now()
    buckets = [
        ("0-7 days", now - timedelta(days=7)),
        ("8-30 days", now - timedelta(days=30)),
        ("31-90 days", now - timedelta(days=90)),
        ("90+ days", now - timedelta(days=3650)),
    ]

    report = []
    for label, cutoff in buckets:
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        if label == "0-7 days":
            domain = [("create_date", ">=", cutoff_str), ("active", "=", True)]
        elif label == "90+ days":
            domain = [("create_date", "<", cutoff_str), ("active", "=", True)]
        else:
            prev_cutoff = buckets[buckets.index((label, cutoff)) - 1][1].strftime("%Y-%m-%d")
            domain = [
                ("create_date", ">=", cutoff_str),
                ("create_date", "<", prev_cutoff),
                ("active", "=", True),
            ]

        count = client.search_count("crm.lead", domain)
        report.append({"bucket": label, "count": count})

    return _json_text(report)


# =============================================================================
# Product Tools (preserved from original MCP server)
# =============================================================================


@server.tool()
async def crm_list_products(limit: int = 20) -> list[TextContent]:
    """List products and services."""
    client = get_client()
    products = client.search_read(
        "product.template",
        [],
        fields=["name", "list_price", "type", "sale_ok", "default_code"],
        limit=limit,
    )
    return _json_text({"count": len(products), "products": products})


@server.tool()
async def crm_create_sale_order(partner_id: int, product_ids: list[int]) -> list[TextContent]:
    """Create a sales order for a customer with specified products."""
    client = get_client()
    order_vals = {
        "partner_id": partner_id,
        "order_line": [(0, 0, {"product_id": pid, "product_uom_qty": 1}) for pid in product_ids],
    }
    order_id = client.create("sale.order", order_vals)
    return _json_text({"success": True, "order_id": order_id})


# =============================================================================
# Health Check
# =============================================================================


@server.tool()
async def crm_health_check() -> list[TextContent]:
    """Check connectivity to Odoo and Ollama."""
    result: dict[str, Any] = {}

    try:
        client = get_client()
        _ = client.uid
        result["odoo"] = "connected"
    except OdooConnectionError as e:
        result["odoo"] = f"error: {e}"

    try:
        enrichment = get_enrichment()
        healthy = await enrichment.health_check()
        result["ollama"] = "connected" if healthy else "unavailable"
    except Exception as e:
        result["ollama"] = f"error: {e}"

    result["status"] = "healthy" if result["odoo"] == "connected" else "degraded"
    return _json_text(result)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
