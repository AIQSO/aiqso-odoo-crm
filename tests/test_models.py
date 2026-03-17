"""Tests for canonical data models."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aiqso_crm.models import Contact, DuplicateMatch, Lead, LeadSource, ValuationTier


class TestValuationTier:
    def test_from_value_premium(self):
        assert ValuationTier.from_value(1_000_000) == ValuationTier.PREMIUM

    def test_from_value_high(self):
        assert ValuationTier.from_value(200_000) == ValuationTier.HIGH

    def test_from_value_medium(self):
        assert ValuationTier.from_value(50_000) == ValuationTier.MEDIUM

    def test_from_value_low(self):
        assert ValuationTier.from_value(10_000) == ValuationTier.LOW

    def test_from_value_unknown(self):
        assert ValuationTier.from_value(0) == ValuationTier.UNKNOWN

    def test_boundary_500k(self):
        assert ValuationTier.from_value(500_000) == ValuationTier.PREMIUM

    def test_boundary_100k(self):
        assert ValuationTier.from_value(100_000) == ValuationTier.HIGH

    def test_boundary_25k(self):
        assert ValuationTier.from_value(25_000) == ValuationTier.MEDIUM


class TestLeadModel:
    def test_phone_normalization_10_digits(self):
        lead = Lead(name="Test", contact_phone="8175551234")
        assert lead.contact_phone == "(817) 555-1234"

    def test_phone_normalization_with_country(self):
        lead = Lead(name="Test", contact_phone="+18175551234")
        assert lead.contact_phone == "(817) 555-1234"

    def test_phone_normalization_formatted(self):
        lead = Lead(name="Test", contact_phone="(817) 555-1234")
        assert lead.contact_phone == "(817) 555-1234"

    def test_phone_normalization_none(self):
        lead = Lead(name="Test", contact_phone=None)
        assert lead.contact_phone is None

    def test_phone_normalization_empty(self):
        lead = Lead(name="Test", contact_phone="")
        assert lead.contact_phone is None

    def test_email_normalization(self):
        lead = Lead(name="Test", contact_email="  John@Example.COM  ")
        assert lead.contact_email == "john@example.com"

    def test_email_empty_string(self):
        lead = Lead(name="Test", contact_email="")
        assert lead.contact_email is None

    def test_to_odoo_values_basic(self):
        lead = Lead(
            name="Test Lead",
            contact_email="test@example.com",
            company_name="Acme Corp",
            expected_revenue=50000,
        )
        values = lead.to_odoo_lead_values()
        assert values["name"] == "Test Lead"
        assert values["email_from"] == "test@example.com"
        assert values["partner_name"] == "Acme Corp"
        assert values["expected_revenue"] == 50000
        assert values["type"] == "lead"

    def test_to_odoo_values_minimal(self):
        lead = Lead(name="Minimal")
        values = lead.to_odoo_lead_values()
        assert values == {"name": "Minimal", "type": "lead"}

    def test_source_default(self):
        lead = Lead(name="Test")
        assert lead.source == LeadSource.MANUAL

    def test_tags_default_empty(self):
        lead = Lead(name="Test")
        assert lead.tags == []


class TestContactModel:
    def test_phone_normalization_shared(self):
        contact = Contact(name="John", phone="8175551234")
        assert contact.phone == "(817) 555-1234"

    def test_email_normalization_shared(self):
        contact = Contact(name="John", email="  JOHN@test.com ")
        assert contact.email == "john@test.com"


class TestDuplicateMatch:
    def test_model(self):
        dm = DuplicateMatch(
            odoo_id=1,
            name="Test Lead",
            match_type="email",
            confidence=0.95,
        )
        assert dm.odoo_id == 1
        assert dm.confidence == 0.95
