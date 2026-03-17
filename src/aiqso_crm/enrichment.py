"""AI-powered lead enrichment via Ollama."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from aiqso_crm.models import Lead, LeadAnalysis

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://192.168.0.234:11434"
DEFAULT_MODEL = "qwen3:8b"


class OllamaEnrichmentClient:
    """Enrich leads using local Ollama LLM."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def _generate(self, prompt: str, system: str | None = None) -> str:
        """Call Ollama generate endpoint."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.HTTPError as e:
            logger.warning("Ollama request failed: %s", e)
            return ""

    async def classify_industry(self, company_name: str, description: str | None = None) -> str:
        """Classify a company's industry."""
        context = f"Company: {company_name}"
        if description:
            context += f"\nDetails: {description}"

        prompt = f"""Classify this company into ONE industry category. Return ONLY the category name.
Categories: Construction, Technology, Healthcare, Real Estate, Manufacturing, Government, Professional Services, Retail, Finance, Other

{context}

Industry:"""

        result = await self._generate(prompt)
        return result.strip().split("\n")[0].strip() if result else "Unknown"

    async def assess_lead_quality(self, lead: Lead) -> LeadAnalysis:
        """AI assessment of lead quality and recommended actions."""
        lead_info = f"""Lead: {lead.name}
Company: {lead.company_name or "Unknown"}
Contact: {lead.contact_name or "Unknown"}
Email: {lead.contact_email or "None"}
Phone: {lead.contact_phone or "None"}
Revenue: ${lead.expected_revenue:,.0f}
Industry: {lead.industry or "Unknown"}
Source: {lead.source.value}
Permit: {lead.permit_number or "None"}"""

        system = "You are a B2B sales analyst. Assess lead quality and provide actionable insights. Respond in JSON."
        prompt = f"""Analyze this lead and respond with ONLY a JSON object:
{{
  "quality_score": <0-100>,
  "quality_reasoning": "<2 sentences>",
  "industry_classification": "<industry>",
  "outreach_suggestion": "<specific action to take>"
}}

{lead_info}"""

        result = await self._generate(prompt, system=system)
        try:
            # Try to extract JSON from response
            json_str = result
            if "```" in json_str:
                json_str = json_str.split("```")[1].strip()
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()
            data = json.loads(json_str)
            return LeadAnalysis(
                lead_id=lead.odoo_lead_id,
                quality_score=float(data.get("quality_score", 0)),
                quality_reasoning=data.get("quality_reasoning"),
                industry_classification=data.get("industry_classification"),
                outreach_suggestion=data.get("outreach_suggestion"),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return LeadAnalysis(
                lead_id=lead.odoo_lead_id,
                quality_reasoning=result[:500] if result else "Analysis unavailable",
            )

    async def generate_outreach_draft(self, lead: Lead, template: str | None = None) -> str:
        """Generate personalized outreach email draft."""
        lead_context = f"""Contact: {lead.contact_name or "Decision Maker"}
Company: {lead.company_name or "their company"}
Industry: {lead.industry or "their industry"}
Project Value: ${lead.expected_revenue:,.0f}
Permit Type: {lead.permit_type or "N/A"}"""

        prompt = f"""Write a short, professional outreach email (3-4 sentences) for this B2B prospect.
Mention their specific project if relevant. Include a clear call to action.

{lead_context}

Subject: """

        return await self._generate(prompt)

    async def health_check(self) -> bool:
        """Check if Ollama is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
