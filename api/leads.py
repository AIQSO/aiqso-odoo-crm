"""Lead management API endpoints."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

# Add src to path for shared library
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from auth import require_api_key

from aiqso_crm.client import OdooClient
from aiqso_crm.dedup import DeduplicationEngine
from aiqso_crm.models import Lead, LeadSource
from aiqso_crm.scoring import LeadScoringEngine

router = APIRouter(prefix="/api/leads", tags=["leads"])

# Singletons
_client: OdooClient | None = None
_dedup: DeduplicationEngine | None = None
_scorer: LeadScoringEngine | None = None


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


# Request/Response Models


class IngestLeadRequest(BaseModel):
    name: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company_name: str | None = None
    expected_revenue: float = 0
    description: str | None = None
    source: str = "api_ingest"
    source_id: str | None = None
    industry: str | None = None
    city: str | None = None
    address: str | None = None
    permit_number: str | None = None
    permit_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    skip_dedup: bool = False


class IngestLeadResponse(BaseModel):
    success: bool
    lead_id: int | None = None
    is_duplicate: bool = False
    duplicate_ids: list[int] = Field(default_factory=list)
    score: float | None = None
    message: str


class BulkIngestRequest(BaseModel):
    leads: list[IngestLeadRequest]
    skip_dedup: bool = False


class BulkIngestResponse(BaseModel):
    total: int
    created: int
    duplicates: int
    errors: int
    results: list[IngestLeadResponse]


class DuplicateEntry(BaseModel):
    odoo_id: int
    name: str
    match_type: str
    confidence: float


class PipelineAnalyticsResponse(BaseModel):
    stages: list[dict[str, Any]]
    total_leads: int
    total_revenue: float


class StaleLeadEntry(BaseModel):
    id: int
    name: str
    partner_name: str | None
    stage: str | None
    last_updated: str | None
    expected_revenue: float


# Endpoints


@router.post("/ingest", response_model=IngestLeadResponse)
async def ingest_lead(
    request: IngestLeadRequest,
    _key: str = Depends(require_api_key),
):
    """Universal lead ingestion endpoint. Validates, deduplicates, scores, and creates."""
    client = get_client()
    dedup = get_dedup()
    scorer = get_scorer()

    try:
        source = LeadSource(request.source)
    except ValueError:
        source = LeadSource.API_INGEST

    lead = Lead(
        name=request.name,
        contact_name=request.contact_name,
        contact_email=request.contact_email,
        contact_phone=request.contact_phone,
        company_name=request.company_name,
        expected_revenue=request.expected_revenue,
        description=request.description,
        source=source,
        source_id=request.source_id,
        industry=request.industry,
        city=request.city,
        address=request.address,
        permit_number=request.permit_number,
        permit_type=request.permit_type,
        tags=request.tags,
    )

    # Score the lead
    score = scorer.score(lead)

    # Check for duplicates
    if not request.skip_dedup:
        duplicates = dedup.find_lead_duplicates(lead)
        if duplicates and duplicates[0].confidence >= 0.9:
            return IngestLeadResponse(
                success=False,
                is_duplicate=True,
                duplicate_ids=[d.odoo_id for d in duplicates],
                score=score,
                message=f"Duplicate found: {duplicates[0].name} (confidence: {duplicates[0].confidence:.0%})",
            )

    # Create the lead
    values = lead.to_odoo_lead_values()
    lead_id = client.create("crm.lead", values)

    return IngestLeadResponse(
        success=True,
        lead_id=lead_id,
        score=score,
        message=f"Lead created (score: {score:.0f})",
    )


@router.post("/bulk", response_model=BulkIngestResponse)
async def bulk_ingest(
    request: BulkIngestRequest,
    _key: str = Depends(require_api_key),
):
    """Batch import multiple leads."""
    results = []
    created = 0
    duplicates = 0
    errors = 0

    for lead_req in request.leads:
        lead_req.skip_dedup = request.skip_dedup
        try:
            result = await ingest_lead(lead_req, _key="internal")
            results.append(result)
            if result.success:
                created += 1
            elif result.is_duplicate:
                duplicates += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            results.append(IngestLeadResponse(success=False, message=f"Error: {e}"))

    return BulkIngestResponse(
        total=len(request.leads),
        created=created,
        duplicates=duplicates,
        errors=errors,
        results=results,
    )


@router.get("/duplicates")
async def find_duplicates(
    email: str | None = Query(None),
    phone: str | None = Query(None),
    company: str | None = Query(None),
    _key: str = Depends(require_api_key),
):
    """Find potential duplicate leads."""
    dedup = get_dedup()
    lead = Lead(
        name="search",
        contact_email=email,
        contact_phone=phone,
        company_name=company,
    )
    matches = dedup.find_lead_duplicates(lead)
    return {
        "duplicates_found": len(matches),
        "matches": [m.model_dump() for m in matches],
    }


@router.post("/merge")
async def merge_leads(
    winner_id: int,
    loser_ids: list[int],
    _key: str = Depends(require_api_key),
):
    """Merge duplicate leads into a single winner."""
    dedup = get_dedup()
    result = dedup.merge_leads(winner_id, loser_ids)
    return result


@router.get("/pipeline", response_model=PipelineAnalyticsResponse)
async def pipeline_analytics(_key: str = Depends(require_api_key)):
    """Get pipeline analytics - leads and revenue per stage."""
    client = get_client()
    stages = client.get_pipeline_stages()

    stage_data = []
    total_leads = 0
    total_revenue = 0.0

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
        stage_data.append(
            {
                "name": stage["name"],
                "id": stage["id"],
                "leads": count,
                "revenue": round(revenue, 2),
            }
        )

    return PipelineAnalyticsResponse(
        stages=stage_data,
        total_leads=total_leads,
        total_revenue=round(total_revenue, 2),
    )


@router.get("/stale")
async def stale_leads(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    _key: str = Depends(require_api_key),
):
    """Find leads with no activity in the last N days."""
    client = get_client()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    leads = client.search_read(
        "crm.lead",
        [("write_date", "<", cutoff), ("active", "=", True)],
        fields=["name", "partner_name", "email_from", "stage_id", "write_date", "expected_revenue"],
        limit=limit,
        order="write_date asc",
    )

    return {
        "stale_count": len(leads),
        "cutoff_date": cutoff,
        "days": days,
        "leads": [
            StaleLeadEntry(
                id=lead["id"],
                name=lead["name"],
                partner_name=lead.get("partner_name"),
                stage=lead["stage_id"][1] if lead.get("stage_id") else None,
                last_updated=lead.get("write_date"),
                expected_revenue=float(lead.get("expected_revenue") or 0),
            ).model_dump()
            for lead in leads
        ],
    }
