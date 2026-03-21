#!/usr/bin/env python3
"""AIQSO Odoo CRM MCP Server - Full-featured CRM operations via MCP protocol."""

import asyncio
import json
import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

# Add parent paths so we can import the shared library
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from aiqso_crm.client import OdooClient, OdooConnectionError
from aiqso_crm.dedup import DeduplicationEngine
from aiqso_crm.enrichment import OllamaEnrichmentClient
from aiqso_crm.models import Lead, LeadSource
from aiqso_crm.scoring import LeadScoringEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("odoo-crm-mcp")

server = FastMCP("aiqso-odoo-crm")

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


def _text(content: str) -> str:
    return content


def _json_text(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


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
) -> str:
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
async def crm_get_lead(lead_id: int) -> str:
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
) -> str:
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
) -> str:
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
async def crm_update_lead(lead_id: int, **updates: Any) -> str:
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
async def crm_score_lead(lead_id: int) -> str:
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
async def crm_enrich_lead(lead_id: int) -> str:
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
async def crm_pipeline_summary() -> str:
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
async def crm_move_lead_stage(lead_id: int, stage_name: str) -> str:
    """Move a lead to a different pipeline stage."""
    client = get_client()
    success = client.move_lead_to_stage(lead_id, stage_name)
    if not success:
        return _text(f"Stage '{stage_name}' not found")
    return _json_text({"success": True, "lead_id": lead_id, "new_stage": stage_name})


@server.tool()
async def crm_stale_leads(days: int = 30, limit: int = 50) -> str:
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
) -> str:
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
async def crm_merge_leads(winner_id: int, loser_ids: list[int]) -> str:
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
) -> str:
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
) -> str:
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
async def crm_list_tags(parent_name: str | None = None) -> str:
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
async def crm_tag_lead(lead_id: int, tag_names: list[str]) -> str:
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
async def crm_source_performance() -> str:
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
async def crm_revenue_forecast() -> str:
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
async def crm_lead_aging() -> str:
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
async def crm_list_products(limit: int = 20) -> str:
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
async def crm_create_sale_order(partner_id: int, product_ids: list[int]) -> str:
    """Create a sales order for a customer with specified products."""
    client = get_client()
    order_vals = {
        "partner_id": partner_id,
        "order_line": [(0, 0, {"product_id": pid, "product_uom_qty": 1}) for pid in product_ids],
    }
    order_id = client.create("sale.order", order_vals)
    return _json_text({"success": True, "order_id": order_id})


# =============================================================================
# Project Management Tools
# =============================================================================


@server.tool()
async def pm_list_projects(
    limit: int = 50,
) -> str:
    """List all Odoo projects with task counts."""
    client = get_client()
    projects = client.search_read(
        "project.project",
        [],
        fields=["name", "description", "task_count", "active"],
        limit=limit,
        order="name",
    )
    return _json_text({"count": len(projects), "projects": projects})


@server.tool()
async def pm_get_project(project_id: int) -> str:
    """Get full details of a project by ID."""
    client = get_client()
    projects = client.read("project.project", [project_id])
    if not projects:
        return _text(f"Project {project_id} not found")
    return _json_text(projects[0])


@server.tool()
async def pm_list_tasks(
    project_name: str | None = None,
    stage: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
    limit: int = 50,
) -> str:
    """List project tasks with filters. Use project_name, stage, assignee, priority, or tag to filter."""
    client = get_client()
    domain: list = []

    if project_name:
        domain.append(("project_id.name", "ilike", project_name))
    if stage:
        domain.append(("stage_id.name", "=", stage))
    if assignee:
        domain.append(("user_ids.name", "ilike", assignee))
    if priority:
        prio_map = {"low": "0", "normal": "0", "high": "1", "urgent": "2"}
        domain.append(("priority", "=", prio_map.get(priority.lower(), priority)))
    if tag:
        domain.append(("tag_ids.name", "ilike", tag))

    tasks = client.search_read(
        "project.task",
        domain,
        fields=[
            "name",
            "project_id",
            "stage_id",
            "user_ids",
            "priority",
            "date_deadline",
            "tag_ids",
            "description",
            "create_date",
            "write_date",
        ],
        limit=limit,
        order="priority desc, date_deadline asc, create_date desc",
    )
    return _json_text({"count": len(tasks), "tasks": tasks})


@server.tool()
async def pm_get_task(task_id: int) -> str:
    """Get full details of a task by ID."""
    client = get_client()
    tasks = client.read("project.task", [task_id])
    if not tasks:
        return _text(f"Task {task_id} not found")
    return _json_text(tasks[0])


@server.tool()
async def pm_create_task(
    name: str,
    project_name: str,
    description: str | None = None,
    stage: str | None = None,
    priority: str = "normal",
    deadline: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Create a new project task. Priority: normal, high, urgent. Deadline format: YYYY-MM-DD."""
    client = get_client()

    # Find the project
    projects = client.search_read(
        "project.project",
        [("name", "ilike", project_name)],
        fields=["id", "name"],
        limit=1,
    )
    if not projects:
        return _text(f"Project '{project_name}' not found")

    project = projects[0]
    prio_map = {"low": "0", "normal": "0", "high": "1", "urgent": "2"}

    values: dict = {
        "name": name,
        "project_id": project["id"],
        "priority": prio_map.get(priority.lower(), "0"),
    }

    if description:
        values["description"] = description
    if deadline:
        values["date_deadline"] = deadline

    if stage:
        stages = client.search_read(
            "project.task.type",
            [("name", "=", stage), ("project_ids", "in", [project["id"]])],
            fields=["id"],
            limit=1,
        )
        if stages:
            values["stage_id"] = stages[0]["id"]

    if tags:
        tag_ids = []
        for tag_name in tags:
            existing = client.search_read(
                "project.tags", [("name", "=", tag_name)], fields=["id"], limit=1
            )
            if existing:
                tag_ids.append(existing[0]["id"])
            else:
                tag_ids.append(client.create("project.tags", {"name": tag_name}))
        values["tag_ids"] = [(6, 0, tag_ids)]

    task_id = client.create("project.task", values)
    return _json_text({
        "success": True,
        "task_id": task_id,
        "project": project["name"],
        "name": name,
    })


@server.tool()
async def pm_update_task(
    task_id: int,
    name: str | None = None,
    description: str | None = None,
    stage: str | None = None,
    priority: str | None = None,
    deadline: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update a project task. Change name, description, stage, priority, deadline, or tags (replaces existing)."""
    client = get_client()

    tasks = client.read("project.task", [task_id], fields=["project_id"])
    if not tasks:
        return _text(f"Task {task_id} not found")

    values: dict = {}
    if name:
        values["name"] = name
    if description:
        values["description"] = description
    if priority:
        prio_map = {"low": "0", "normal": "0", "high": "1", "urgent": "2"}
        values["priority"] = prio_map.get(priority.lower(), priority)
    if deadline:
        values["date_deadline"] = deadline

    if tags is not None:
        tag_ids = []
        for tag_name in tags:
            existing = client.search_read(
                "project.tags", [("name", "=", tag_name)], fields=["id"], limit=1
            )
            if existing:
                tag_ids.append(existing[0]["id"])
            else:
                tag_ids.append(client.create("project.tags", {"name": tag_name}))
        values["tag_ids"] = [(6, 0, tag_ids)]

    if stage:
        project_id = tasks[0]["project_id"][0] if tasks[0].get("project_id") else None
        stage_domain: list = [("name", "=", stage)]
        if project_id:
            stage_domain.append(("project_ids", "in", [project_id]))
        stages = client.search_read(
            "project.task.type", stage_domain, fields=["id"], limit=1
        )
        if stages:
            values["stage_id"] = stages[0]["id"]
        else:
            return _text(f"Stage '{stage}' not found")

    if not values:
        return _text("No fields to update")

    client.write("project.task", [task_id], values)
    return _json_text({
        "success": True,
        "task_id": task_id,
        "updated_fields": list(values.keys()),
    })


@server.tool()
async def pm_move_task(task_id: int, stage: str) -> str:
    """Move a task to a different stage (e.g. 'In Progress', 'Human Review', 'Done')."""
    return await pm_update_task(task_id, stage=stage)


@server.tool()
async def pm_search_tasks(
    query: str,
    limit: int = 20,
) -> str:
    """Search tasks by name or description across all projects."""
    client = get_client()
    tasks = client.search_read(
        "project.task",
        ["|", ("name", "ilike", query), ("description", "ilike", query)],
        fields=[
            "name",
            "project_id",
            "stage_id",
            "priority",
            "date_deadline",
            "user_ids",
        ],
        limit=limit,
        order="write_date desc",
    )
    return _json_text({"count": len(tasks), "query": query, "tasks": tasks})


@server.tool()
async def pm_project_board(project_name: str) -> str:
    """Get a kanban-style board view of a project — tasks grouped by stage."""
    client = get_client()

    projects = client.search_read(
        "project.project",
        [("name", "ilike", project_name)],
        fields=["id", "name", "type_ids"],
        limit=1,
    )
    if not projects:
        return _text(f"Project '{project_name}' not found")

    project = projects[0]
    stages = client.search_read(
        "project.task.type",
        [("project_ids", "in", [project["id"]])],
        fields=["name", "sequence"],
        order="sequence",
    )

    board: dict = {"project": project["name"], "stages": []}
    for stage in stages:
        tasks = client.search_read(
            "project.task",
            [("project_id", "=", project["id"]), ("stage_id", "=", stage["id"])],
            fields=["name", "priority", "date_deadline", "user_ids"],
            order="priority desc, date_deadline asc",
        )
        board["stages"].append({
            "stage": stage["name"],
            "task_count": len(tasks),
            "tasks": tasks,
        })

    return _json_text(board)


@server.tool()
async def pm_list_tags(
    query: str | None = None,
    limit: int = 50,
) -> str:
    """List all project tags, optionally filtered by name."""
    client = get_client()
    domain: list = []
    if query:
        domain.append(("name", "ilike", query))

    tags = client.search_read(
        "project.tags",
        domain,
        fields=["name", "color"],
        limit=limit,
        order="name",
    )
    return _json_text({"count": len(tags), "tags": tags})


@server.tool()
async def pm_tag_task(task_id: int, tag_names: list[str]) -> str:
    """Add tags to a project task. Creates tags if they don't exist."""
    client = get_client()

    tasks = client.read("project.task", [task_id], fields=["name"])
    if not tasks:
        return _text(f"Task {task_id} not found")

    tag_ids = []
    for tag_name in tag_names:
        existing = client.search_read(
            "project.tags", [("name", "=", tag_name)], fields=["id"], limit=1
        )
        if existing:
            tag_ids.append(existing[0]["id"])
        else:
            tag_ids.append(client.create("project.tags", {"name": tag_name}))

    # Use (4, id) to add without replacing existing tags
    client.write("project.task", [task_id], {"tag_ids": [(4, tid) for tid in tag_ids]})
    return _json_text({"success": True, "task_id": task_id, "tags_added": tag_names})


@server.tool()
async def pm_untag_task(task_id: int, tag_names: list[str]) -> str:
    """Remove tags from a project task."""
    client = get_client()

    tasks = client.read("project.task", [task_id], fields=["name"])
    if not tasks:
        return _text(f"Task {task_id} not found")

    removed = []
    for tag_name in tag_names:
        existing = client.search_read(
            "project.tags", [("name", "=", tag_name)], fields=["id"], limit=1
        )
        if existing:
            # Use (3, id) to unlink without deleting the tag
            client.write("project.task", [task_id], {"tag_ids": [(3, existing[0]["id"])]})
            removed.append(tag_name)

    return _json_text({"success": True, "task_id": task_id, "tags_removed": removed})


@server.tool()
async def pm_task_stages() -> str:
    """List all available task stages."""
    client = get_client()
    stages = client.search_read(
        "project.task.type",
        [],
        fields=["name", "sequence", "fold", "project_ids"],
        order="sequence",
    )
    return _json_text({"count": len(stages), "stages": stages})


@server.tool()
async def pm_my_tasks(
    stage: str | None = None,
    limit: int = 30,
) -> str:
    """List tasks assigned to the current user, optionally filtered by stage."""
    client = get_client()
    domain: list = [("user_ids", "in", [client.uid])]
    if stage:
        domain.append(("stage_id.name", "=", stage))

    tasks = client.search_read(
        "project.task",
        domain,
        fields=[
            "name",
            "project_id",
            "stage_id",
            "priority",
            "date_deadline",
            "tag_ids",
        ],
        limit=limit,
        order="priority desc, date_deadline asc",
    )
    return _json_text({"count": len(tasks), "tasks": tasks})


@server.tool()
async def pm_sprint_summary() -> str:
    """Get a summary of all active tasks across all projects, grouped by stage."""
    client = get_client()

    stages = client.search_read(
        "project.task.type",
        [("fold", "=", False)],
        fields=["name", "sequence"],
        order="sequence",
    )

    seen_names: set = set()
    unique_stages = []
    for s in stages:
        if s["name"] not in seen_names:
            seen_names.add(s["name"])
            unique_stages.append(s)

    summary: dict = {"stages": [], "total_tasks": 0}
    for stage in unique_stages:
        count = client.search_count(
            "project.task",
            [("stage_id.name", "=", stage["name"])],
        )
        summary["stages"].append({"stage": stage["name"], "count": count})
        summary["total_tasks"] += count

    return _json_text(summary)


# =============================================================================
# Health Check
# =============================================================================


@server.tool()
async def crm_health_check() -> str:
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


if __name__ == "__main__":
    server.run()
