"""Unit tests for scripts/import_commercial_leads.py"""

import csv
import os
import sys
import tempfile
from unittest import mock

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from import_commercial_leads import CATEGORY_COLORS, OdooCommercialImporter


class TestCategoryColors:
    """Tests for CATEGORY_COLORS constant."""

    def test_contains_required_categories(self):
        required = [
            "Lead List",
            "For Sale",
            "Outreach Target",
            "Construction",
            "Premium",
            "High Value",
            "Medium Value",
            "Low Value",
        ]
        for cat in required:
            assert cat in CATEGORY_COLORS

    def test_contains_project_categories(self):
        project_cats = ["Retail", "Office", "Industrial", "Restaurant", "Medical"]
        for cat in project_cats:
            assert cat in CATEGORY_COLORS

    def test_colors_are_integers(self):
        for name, color in CATEGORY_COLORS.items():
            assert isinstance(color, int), f"{name} color should be int"


class TestOdooCommercialImporterInit:
    """Tests for OdooCommercialImporter initialization."""

    @mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy")
    def test_successful_connection(self, mock_server_proxy):
        """Test successful Odoo connection."""
        mock_common = mock.MagicMock()
        mock_common.authenticate.return_value = 123
        mock_models = mock.MagicMock()
        mock_server_proxy.side_effect = [mock_common, mock_models]

        config = {
            "url": "http://test.odoo.com",
            "db": "test_db",
            "username": "admin",
            "api_key": "secret",
        }

        importer = OdooCommercialImporter(config)

        assert importer.uid == 123
        assert importer.models == mock_models
        assert importer._category_cache == {}
        mock_common.authenticate.assert_called_once_with("test_db", "admin", "secret", {})

    @mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy")
    def test_authentication_failure(self, mock_server_proxy):
        """Test handling of authentication failure."""
        mock_common = mock.MagicMock()
        mock_common.authenticate.return_value = None
        mock_server_proxy.return_value = mock_common

        config = {
            "url": "http://test.odoo.com",
            "db": "test_db",
            "username": "admin",
            "api_key": "wrong_key",
        }

        with pytest.raises(SystemExit):
            OdooCommercialImporter(config)

    @mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy")
    def test_connection_exception(self, mock_server_proxy):
        """Test handling of connection exception."""
        mock_server_proxy.side_effect = Exception("Connection refused")

        config = {
            "url": "http://test.odoo.com",
            "db": "test_db",
            "username": "admin",
            "api_key": "secret",
        }

        with pytest.raises(SystemExit):
            OdooCommercialImporter(config)


class TestOdooCommercialImporterMethods:
    """Tests for OdooCommercialImporter methods with mocked connection."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            imp = OdooCommercialImporter(config)
            imp.models = mock_models
            return imp

    def test_execute(self, importer):
        """Test _execute method."""
        importer.models.execute_kw.return_value = [{"id": 1}]

        result = importer._execute("res.partner", "search_read", [("name", "=", "Test")])

        importer.models.execute_kw.assert_called_once()
        assert result == [{"id": 1}]

    def test_search_read_with_fields_and_limit(self, importer):
        """Test search_read with fields and limit."""
        importer.models.execute_kw.return_value = [{"id": 1, "name": "Test"}]

        importer.search_read("res.partner", [("id", "=", 1)], fields=["id", "name"], limit=10)

        call_args = importer.models.execute_kw.call_args
        assert call_args[0][4] == "search_read"
        assert call_args[0][6]["fields"] == ["id", "name"]
        assert call_args[0][6]["limit"] == 10

    def test_create_returns_id(self, importer):
        """Test create returns ID."""
        importer.models.execute_kw.return_value = 42

        result = importer.create("res.partner", {"name": "Test"})

        assert result == 42

    def test_create_handles_list_response(self, importer):
        """Test create handles list response from Odoo."""
        importer.models.execute_kw.return_value = [42]

        result = importer.create("res.partner", {"name": "Test"})

        assert result == 42

    def test_create_handles_empty_list(self, importer):
        """Test create handles empty list response."""
        importer.models.execute_kw.return_value = []

        result = importer.create("res.partner", {"name": "Test"})

        assert result is None

    def test_write(self, importer):
        """Test write method."""
        importer.models.execute_kw.return_value = True

        result = importer.write("res.partner", [1], {"name": "Updated"})

        assert result is True

    def test_search_with_limit(self, importer):
        """Test search with limit."""
        importer.models.execute_kw.return_value = [1, 2, 3]

        result = importer.search("res.partner", [("is_company", "=", True)], limit=10)

        assert result == [1, 2, 3]


class TestGetOrCreateCategory:
    """Tests for get_or_create_category method with caching."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_returns_existing_category(self, importer):
        """Test returns existing category ID."""
        importer.models.execute_kw.return_value = [{"id": 5, "name": "Lead List"}]

        result = importer.get_or_create_category("Lead List")

        assert result == 5

    def test_creates_new_category(self, importer):
        """Test creates category if not exists."""
        importer.models.execute_kw.side_effect = [[], 10]

        result = importer.get_or_create_category("New Category", color=5)

        assert result == 10

    def test_caches_category_id(self, importer):
        """Test caches category ID for repeated calls."""
        importer.models.execute_kw.return_value = [{"id": 5, "name": "Lead List"}]

        # First call
        result1 = importer.get_or_create_category("Lead List")
        # Second call should use cache
        result2 = importer.get_or_create_category("Lead List")

        assert result1 == result2 == 5
        # Should only call execute_kw once due to caching
        assert importer.models.execute_kw.call_count == 1

    def test_handles_parent_id_as_list(self, importer):
        """Test handles parent_id when passed as list."""
        importer.models.execute_kw.side_effect = [[], 15]

        result = importer.get_or_create_category("Child", parent_id=[1], color=3)

        assert result == 15

    def test_handles_parent_id_as_int(self, importer):
        """Test handles parent_id when passed as int."""
        importer.models.execute_kw.side_effect = [[], 15]

        result = importer.get_or_create_category("Child", parent_id=1, color=3)

        assert result == 15


class TestSetupCategories:
    """Tests for setup_categories method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_returns_category_structure(self, importer):
        """Test returns complete category structure."""
        # Mock all category lookups to return empty (will create new)
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return call_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        result = importer.setup_categories()

        assert "parent" in result
        assert "for_sale" in result
        assert "outreach" in result
        assert "construction" in result
        assert "value_tiers" in result
        assert "project_cats" in result


class TestGetOrCreateListCompany:
    """Tests for get_or_create_list_company method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_creates_umbrella_and_list_company(self, importer):
        """Test creates both umbrella and list company."""
        importer.models.execute_kw.side_effect = [
            [],  # umbrella doesn't exist
            100,  # create umbrella
            [],  # list company doesn't exist
            101,  # create list company
        ]

        category_ids = {"parent": 1, "construction": 2, "for_sale": 3, "outreach": 4}
        result = importer.get_or_create_list_company("Fort Worth", category_ids)

        assert result == 101

    def test_uses_existing_umbrella(self, importer):
        """Test uses existing umbrella company."""
        importer.models.execute_kw.side_effect = [
            [{"id": 100}],  # umbrella exists
            [],  # list company doesn't exist
            101,  # create list company
        ]

        category_ids = {"parent": 1, "construction": 2, "for_sale": 3, "outreach": 4}
        result = importer.get_or_create_list_company("Arlington", category_ids)

        assert result == 101

    def test_returns_existing_list_company(self, importer):
        """Test returns existing list company."""
        importer.models.execute_kw.side_effect = [
            [{"id": 100}],  # umbrella exists
            [{"id": 200}],  # list company exists
        ]

        category_ids = {"parent": 1, "construction": 2, "for_sale": 3, "outreach": 4}
        result = importer.get_or_create_list_company("Dallas", category_ids)

        assert result == 200


class TestParseValuation:
    """Tests for parse_valuation method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_parses_k_notation(self, importer):
        """Test parses $420K format."""
        assert importer.parse_valuation("$420K") == 420000

    def test_parses_m_notation(self, importer):
        """Test parses $1.2M format."""
        assert importer.parse_valuation("$1.2M") == 1200000

    def test_parses_plain_number(self, importer):
        """Test parses plain number."""
        assert importer.parse_valuation("$50,000") == 50000

    def test_handles_tbd(self, importer):
        """Test handles TBD value."""
        assert importer.parse_valuation("TBD") == 0

    def test_handles_empty_string(self, importer):
        """Test handles empty string."""
        assert importer.parse_valuation("") == 0

    def test_handles_none(self, importer):
        """Test handles None."""
        assert importer.parse_valuation(None) == 0

    def test_handles_invalid_value(self, importer):
        """Test handles invalid value."""
        assert importer.parse_valuation("invalid") == 0

    def test_case_insensitive(self, importer):
        """Test is case insensitive."""
        assert importer.parse_valuation("$420k") == 420000
        assert importer.parse_valuation("$1.2m") == 1200000


class TestGetValueTier:
    """Tests for get_value_tier method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_premium_tier(self, importer):
        """Test Premium tier for >= $500K."""
        assert importer.get_value_tier(500000) == "Premium"
        assert importer.get_value_tier(1000000) == "Premium"

    def test_high_value_tier(self, importer):
        """Test High Value tier for >= $100K."""
        assert importer.get_value_tier(100000) == "High Value"
        assert importer.get_value_tier(499999) == "High Value"

    def test_medium_value_tier(self, importer):
        """Test Medium Value tier for >= $25K."""
        assert importer.get_value_tier(25000) == "Medium Value"
        assert importer.get_value_tier(99999) == "Medium Value"

    def test_low_value_tier(self, importer):
        """Test Low Value tier for > $0."""
        assert importer.get_value_tier(1) == "Low Value"
        assert importer.get_value_tier(24999) == "Low Value"

    def test_no_tier_for_zero(self, importer):
        """Test returns None for zero valuation."""
        assert importer.get_value_tier(0) is None


class TestMapProjectCategory:
    """Tests for map_project_category method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_maps_retail(self, importer):
        """Test maps retail category."""
        assert importer.map_project_category("Retail Store") == "Retail"
        assert importer.map_project_category("RETAIL") == "Retail"

    def test_maps_office(self, importer):
        """Test maps office category."""
        assert importer.map_project_category("Office Building") == "Office"

    def test_maps_industrial(self, importer):
        """Test maps industrial category."""
        assert importer.map_project_category("Industrial") == "Industrial"
        assert importer.map_project_category("Warehouse") == "Industrial"

    def test_maps_restaurant(self, importer):
        """Test maps restaurant category."""
        assert importer.map_project_category("Restaurant") == "Restaurant"
        assert importer.map_project_category("Food Service") == "Restaurant"

    def test_maps_medical(self, importer):
        """Test maps medical category."""
        assert importer.map_project_category("Medical Clinic") == "Medical"
        assert importer.map_project_category("Healthcare") == "Medical"
        assert importer.map_project_category("Health Center") == "Medical"

    def test_returns_none_for_unknown(self, importer):
        """Test returns None for unknown category."""
        assert importer.map_project_category("Unknown") is None
        assert importer.map_project_category("") is None
        assert importer.map_project_category(None) is None


class TestCreateCrmLead:
    """Tests for create_crm_lead method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_creates_lead_with_all_fields(self, importer):
        """Test creates lead with all fields."""
        importer.models.execute_kw.return_value = 500

        result = importer.create_crm_lead(
            name="Test Lead",
            partner_name="Acme Corp",
            expected_revenue=100000,
            description="Test description",
            street="123 Main St",
        )

        assert result == 500

    def test_creates_lead_with_minimal_fields(self, importer):
        """Test creates lead with minimal fields."""
        importer.models.execute_kw.return_value = 501

        result = importer.create_crm_lead(name="Simple Lead")

        assert result == 501


class TestImportCsv:
    """Tests for import_csv method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_commercial_leads.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_common = mock.MagicMock()
            mock_common.authenticate.return_value = 1
            mock_models = mock.MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]

            config = {
                "url": "http://test.odoo.com",
                "db": "test_db",
                "username": "admin",
                "api_key": "secret",
            }
            return OdooCommercialImporter(config)

    def test_import_csv_file_not_found(self, importer):
        """Test import_csv exits when file not found."""
        with pytest.raises(SystemExit):
            importer.import_csv("/nonexistent/file.csv")

    def test_import_csv_processes_rows(self, importer):
        """Test import_csv processes CSV rows."""
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return call_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "City",
                    "Permit Number",
                    "Full Address",
                    "Valuation",
                    "Project Category",
                    "Project Type",
                    "Property Owner",
                ]
            )
            writer.writerow(["Fort Worth", "P001", "123 Main St", "$500K", "Retail", "New", "John Owner"])
            writer.writerow(["Fort Worth", "P002", "456 Oak Ave", "$1.2M", "Office", "Renovation", "Jane Owner"])
            f.flush()

            try:
                stats = importer.import_csv(f.name)
                assert stats["leads_created"] == 2
                assert "Fort Worth" in stats["by_city"]
            finally:
                os.unlink(f.name)

    def test_import_csv_filters_by_city(self, importer):
        """Test import_csv filters by city."""
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return call_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["City", "Permit Number", "Full Address", "Valuation"])
            writer.writerow(["Fort Worth", "P001", "123 Main St", "$500K"])
            writer.writerow(["Arlington", "P002", "456 Oak Ave", "$1.2M"])
            writer.writerow(["Fort Worth", "P003", "789 Elm St", "$300K"])
            f.flush()

            try:
                stats = importer.import_csv(f.name, city_filter="Fort Worth")
                assert stats["leads_created"] == 2
                assert "Fort Worth" in stats["by_city"]
                assert "Arlington" not in stats["by_city"]
            finally:
                os.unlink(f.name)

    def test_import_csv_excludes_cities(self, importer):
        """Test import_csv excludes specified cities."""
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return call_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["City", "Permit Number", "Full Address", "Valuation"])
            writer.writerow(["Fort Worth", "P001", "123 Main St", "$500K"])
            writer.writerow(["Arlington", "P002", "456 Oak Ave", "$1.2M"])
            writer.writerow(["Dallas", "P003", "789 Elm St", "$300K"])
            f.flush()

            try:
                stats = importer.import_csv(f.name, exclude_cities=["Fort Worth"])
                assert "Fort Worth" not in stats["by_city"]
                assert "Arlington" in stats["by_city"]
                assert "Dallas" in stats["by_city"]
            finally:
                os.unlink(f.name)

    def test_import_csv_skips_empty_city(self, importer):
        """Test import_csv skips rows with empty city."""
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return call_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["City", "Permit Number", "Full Address", "Valuation"])
            writer.writerow(["", "P001", "123 Main St", "$500K"])  # Empty city
            writer.writerow(["Fort Worth", "P002", "456 Oak Ave", "$1.2M"])
            f.flush()

            try:
                stats = importer.import_csv(f.name)
                assert stats["leads_created"] == 1
            finally:
                os.unlink(f.name)

    def test_import_csv_handles_errors(self, importer):
        """Test import_csv handles row processing errors."""
        call_count = [0]
        create_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                create_count[0] += 1
                # Fail on CRM lead creation (after category and company setup)
                # Categories: ~13 creates, Companies: ~2 creates = ~15 total before leads
                if create_count[0] > 15:
                    raise Exception("Create failed")
                return create_count[0]
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["City", "Permit Number", "Full Address", "Valuation"])
            writer.writerow(["Fort Worth", "P001", "123 Main St", "$500K"])
            f.flush()

            try:
                stats = importer.import_csv(f.name)
                # Should have skipped the failed row
                assert stats["skipped"] >= 1
            finally:
                os.unlink(f.name)
