"""Tests for lead scoring engine."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aiqso_crm.models import Lead, LeadSource, ValuationTier
from aiqso_crm.scoring import LeadScoringEngine, ScoringWeights


class TestLeadScoringEngine:
    def setup_method(self):
        self.scorer = LeadScoringEngine()

    def test_minimal_lead_scores_zero(self):
        lead = Lead(name="Empty Lead")
        score = self.scorer.score(lead)
        assert score == 0

    def test_email_adds_score(self):
        lead = Lead(name="Test", contact_email="test@example.com")
        score = self.scorer.score(lead)
        assert score >= 20

    def test_phone_adds_score(self):
        lead = Lead(name="Test", contact_phone="8175551234")
        score = self.scorer.score(lead)
        assert score >= 15

    def test_company_adds_score(self):
        lead = Lead(name="Test", company_name="Acme")
        score = self.scorer.score(lead)
        assert score >= 10

    def test_premium_valuation(self):
        lead = Lead(name="Test", expected_revenue=1_000_000)
        score = self.scorer.score(lead)
        assert score >= 25

    def test_full_lead_high_score(self):
        lead = Lead(
            name="Full Lead",
            contact_email="test@example.com",
            contact_phone="8175551234",
            company_name="Big Corp",
            expected_revenue=500_000,
            permit_number="P123",
            contact_role="Manager",
            source=LeadSource.ACCELA,
        )
        score = self.scorer.score(lead)
        assert score >= 80

    def test_score_capped_at_100(self):
        lead = Lead(
            name="Max Lead",
            contact_email="a@b.com",
            contact_phone="8175551234",
            company_name="Corp",
            expected_revenue=1_000_000,
            permit_number="P1",
            contact_role="CEO",
            source=LeadSource.SAMGOV,
        )
        score = self.scorer.score(lead)
        assert score <= 100

    def test_custom_weights(self):
        weights = ScoringWeights(has_email=50.0, has_phone=0.0)
        scorer = LeadScoringEngine(weights=weights)
        lead = Lead(name="Test", contact_email="test@example.com")
        score = scorer.score(lead)
        assert score == 50

    def test_bulk_score(self):
        leads = [
            Lead(name="A", contact_email="a@b.com"),
            Lead(name="B"),
        ]
        results = self.scorer.bulk_score(leads)
        assert len(results) == 2
        assert results[0][1] > results[1][1]

    def test_tier_from_valuation(self):
        assert self.scorer.tier(600_000) == ValuationTier.PREMIUM
        assert self.scorer.tier(200_000) == ValuationTier.HIGH
        assert self.scorer.tier(50_000) == ValuationTier.MEDIUM
        assert self.scorer.tier(5_000) == ValuationTier.LOW
        assert self.scorer.tier(0) == ValuationTier.UNKNOWN

    def test_source_bonus_accela(self):
        lead_no_source = Lead(name="Test", contact_email="a@b.com")
        lead_accela = Lead(name="Test", contact_email="a@b.com", source=LeadSource.ACCELA)
        assert self.scorer.score(lead_accela) > self.scorer.score(lead_no_source)
