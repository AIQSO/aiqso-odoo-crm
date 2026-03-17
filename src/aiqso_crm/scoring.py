"""Unified lead scoring engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from aiqso_crm.models import Lead, ValuationTier


@dataclass
class ScoringWeights:
    """Configurable scoring weights."""

    has_email: float = 20.0
    has_phone: float = 15.0
    has_company: float = 10.0
    valuation_premium: float = 25.0
    valuation_high: float = 20.0
    valuation_medium: float = 12.0
    valuation_low: float = 5.0
    has_permit: float = 10.0
    has_contact_role: float = 5.0
    source_weights: dict[str, float] = field(
        default_factory=lambda: {
            "accela": 5.0,
            "samgov": 8.0,
            "api_ingest": 3.0,
        }
    )


class LeadScoringEngine:
    """Score leads based on configurable criteria."""

    def __init__(self, weights: ScoringWeights | None = None):
        self.weights = weights or ScoringWeights()

    def score(self, lead: Lead) -> float:
        """Calculate lead score (0-100)."""
        total = 0.0

        if lead.contact_email:
            total += self.weights.has_email
        if lead.contact_phone:
            total += self.weights.has_phone
        if lead.company_name:
            total += self.weights.has_company
        if lead.permit_number:
            total += self.weights.has_permit
        if lead.contact_role:
            total += self.weights.has_contact_role

        # Valuation tier scoring
        tier = lead.valuation_tier
        if tier == ValuationTier.UNKNOWN and lead.expected_revenue > 0:
            tier = ValuationTier.from_value(lead.expected_revenue)

        tier_scores = {
            ValuationTier.PREMIUM: self.weights.valuation_premium,
            ValuationTier.HIGH: self.weights.valuation_high,
            ValuationTier.MEDIUM: self.weights.valuation_medium,
            ValuationTier.LOW: self.weights.valuation_low,
        }
        total += tier_scores.get(tier, 0)

        # Source bonus
        total += self.weights.source_weights.get(lead.source.value, 0)

        return min(total, 100.0)

    def tier(self, valuation: float) -> ValuationTier:
        """Get valuation tier from dollar amount."""
        return ValuationTier.from_value(valuation)

    def bulk_score(self, leads: list[Lead]) -> list[tuple[Lead, float]]:
        """Score multiple leads."""
        return [(lead, self.score(lead)) for lead in leads]
