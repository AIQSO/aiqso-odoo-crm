"""Tests for deduplication engine."""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aiqso_crm.dedup import (
    DeduplicationEngine,
    _clean_company_name,
    _fuzzy_company_match,
    _normalize_email,
    _normalize_phone,
)
from aiqso_crm.models import Lead


class TestNormalizePhone:
    def test_ten_digits(self):
        assert _normalize_phone("8175551234") == "8175551234"

    def test_with_plus_one(self):
        assert _normalize_phone("+18175551234") == "8175551234"

    def test_with_one_prefix(self):
        assert _normalize_phone("18175551234") == "8175551234"

    def test_formatted(self):
        assert _normalize_phone("(817) 555-1234") == "8175551234"

    def test_none(self):
        assert _normalize_phone(None) == ""

    def test_empty(self):
        assert _normalize_phone("") == ""


class TestNormalizeEmail:
    def test_lowercase(self):
        assert _normalize_email("JOHN@Example.COM") == "john@example.com"

    def test_strip_whitespace(self):
        assert _normalize_email("  john@test.com  ") == "john@test.com"

    def test_none(self):
        assert _normalize_email(None) == ""


class TestCleanCompanyName:
    def test_remove_llc(self):
        assert _clean_company_name("Acme LLC") == "acme"

    def test_remove_inc(self):
        assert _clean_company_name("Tech Inc.") == "tech"

    def test_remove_corp(self):
        assert _clean_company_name("Big Corp") == "big"

    def test_normalize_whitespace(self):
        assert _clean_company_name("  Acme   Corp  ") == "acme"


class TestFuzzyCompanyMatch:
    def test_exact_match(self):
        assert _fuzzy_company_match("Acme Corp", "Acme Corp") == 1.0

    def test_case_insensitive(self):
        assert _fuzzy_company_match("acme", "ACME") == 1.0

    def test_suffix_ignored(self):
        assert _fuzzy_company_match("Acme LLC", "Acme Inc") == 1.0

    def test_containment(self):
        score = _fuzzy_company_match("Acme", "Acme Construction Group")
        assert score >= 0.8

    def test_different_companies(self):
        score = _fuzzy_company_match("Acme", "Zenith Technologies")
        assert score < 0.5

    def test_empty(self):
        assert _fuzzy_company_match("", "") == 0.0


class TestDeduplicationEngine:
    @pytest.fixture
    def engine(self):
        client = mock.MagicMock()
        return DeduplicationEngine(client)

    def test_find_duplicates_by_email(self, engine):
        engine.client.search_read.return_value = [
            {"id": 1, "name": "Existing Lead", "email_from": "test@example.com", "phone": None}
        ]
        lead = Lead(name="New Lead", contact_email="test@example.com")
        matches = engine.find_lead_duplicates(lead)
        assert len(matches) == 1
        assert matches[0].match_type == "email"
        assert matches[0].confidence == 1.0

    def test_find_duplicates_no_match(self, engine):
        engine.client.search_read.return_value = []
        lead = Lead(name="Unique Lead")
        matches = engine.find_lead_duplicates(lead)
        assert len(matches) == 0

    def test_find_duplicates_by_source_id(self, engine):
        # No email/phone on lead, so it goes straight to source_id check
        engine.client.search_read.return_value = [{"id": 5, "name": "Permit Lead", "email_from": None, "phone": None}]
        lead = Lead(name="Test", source_id="PERMIT-123")
        matches = engine.find_lead_duplicates(lead)
        assert len(matches) >= 1
        # Should find via source_id match
        source_matches = [m for m in matches if m.match_type == "source_id"]
        assert len(source_matches) == 1

    def test_merge_leads(self, engine):
        engine.client.read.side_effect = [
            [
                {
                    "name": "Winner",
                    "email_from": "a@b.com",
                    "phone": None,
                    "partner_name": "Acme",
                    "description": "Main lead",
                    "expected_revenue": 100,
                    "contact_name": "John",
                }
            ],
            [
                {
                    "name": "Loser",
                    "email_from": None,
                    "phone": "555-1234",
                    "partner_name": "Acme",
                    "description": "Duplicate",
                    "expected_revenue": 50,
                    "contact_name": None,
                }
            ],
        ]
        engine.client.write.return_value = True

        result = engine.merge_leads(1, [2])
        assert result["winner_id"] == 1
        assert result["merged"] == 1
        assert engine.client.write.call_count == 2  # update winner + archive loser
