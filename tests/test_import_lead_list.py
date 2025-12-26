"""Unit tests for scripts/import_lead_list.py"""

import csv
import os
import sys
import tempfile
from unittest import mock

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from import_lead_list import CATEGORY_COLORS, OdooLeadImporter


class TestCategoryColors:
    """Tests for CATEGORY_COLORS constant."""

    def test_contains_required_categories(self):
        required = ["Lead List", "For Sale", "Outreach Target", "Premium", "High Value", "Medium Value", "Low Value"]
        for cat in required:
            assert cat in CATEGORY_COLORS

    def test_colors_are_integers(self):
        for name, color in CATEGORY_COLORS.items():
            assert isinstance(color, int), f"{name} color should be int"


class TestOdooLeadImporterInit:
    """Tests for OdooLeadImporter initialization."""

    @mock.patch("import_lead_list.xmlrpc.client.ServerProxy")
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

        importer = OdooLeadImporter(config)

        assert importer.uid == 123
        assert importer.models == mock_models
        mock_common.authenticate.assert_called_once_with("test_db", "admin", "secret", {})

    @mock.patch("import_lead_list.xmlrpc.client.ServerProxy")
    def test_authentication_failure(self, mock_server_proxy):
        """Test handling of authentication failure."""
        mock_common = mock.MagicMock()
        mock_common.authenticate.return_value = None  # Auth failed

        mock_server_proxy.return_value = mock_common

        config = {
            "url": "http://test.odoo.com",
            "db": "test_db",
            "username": "admin",
            "api_key": "wrong_key",
        }

        with pytest.raises(SystemExit):
            OdooLeadImporter(config)

    @mock.patch("import_lead_list.xmlrpc.client.ServerProxy")
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
            OdooLeadImporter(config)


class TestOdooLeadImporterMethods:
    """Tests for OdooLeadImporter methods with mocked connection."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            imp = OdooLeadImporter(config)
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
        # call_args[0] = positional args: (db, uid, api_key, model, method, args_tuple, kwargs_dict)
        assert call_args[0][4] == "search_read"
        # kwargs_dict is at index 6
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
    """Tests for get_or_create_category method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            return OdooLeadImporter(config)

    def test_returns_existing_category(self, importer):
        """Test returns existing category ID."""
        importer.models.execute_kw.return_value = [{"id": 5, "name": "Lead List"}]

        result = importer.get_or_create_category("Lead List")

        assert result == 5

    def test_creates_new_category(self, importer):
        """Test creates category if not exists."""
        # First call returns empty (not found), second call creates
        importer.models.execute_kw.side_effect = [[], 10]

        result = importer.get_or_create_category("New Category", color=5)

        assert result == 10

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


class TestGetOrCreateCompany:
    """Tests for get_or_create_company method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            return OdooLeadImporter(config)

    def test_returns_none_for_empty_name(self, importer):
        """Test returns None for empty company name."""
        assert importer.get_or_create_company("") is None
        assert importer.get_or_create_company("   ") is None
        assert importer.get_or_create_company(None) is None

    def test_returns_existing_company(self, importer):
        """Test returns existing company ID."""
        importer.models.execute_kw.return_value = [{"id": 100, "name": "Acme Corp"}]

        result = importer.get_or_create_company("Acme Corp")

        assert result == 100

    def test_creates_new_company(self, importer):
        """Test creates company if not exists."""
        importer.models.execute_kw.side_effect = [[], 200]

        result = importer.get_or_create_company("New Corp")

        assert result == 200

    def test_updates_categories_on_existing(self, importer):
        """Test updates categories on existing company."""
        importer.models.execute_kw.side_effect = [
            [{"id": 100, "name": "Acme Corp"}],  # search_read
            True,  # write
        ]

        result = importer.get_or_create_company("Acme Corp", category_id=[(4, 1)])

        assert result == 100
        # Verify write was called
        assert importer.models.execute_kw.call_count == 2


class TestGetOrCreateContact:
    """Tests for get_or_create_contact method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            return OdooLeadImporter(config)

    def test_returns_none_for_empty_name(self, importer):
        """Test returns None for empty contact name."""
        assert importer.get_or_create_contact("") is None
        assert importer.get_or_create_contact("   ") is None

    def test_searches_by_email_when_provided(self, importer):
        """Test searches by email when provided."""
        importer.models.execute_kw.return_value = [{"id": 50, "name": "John"}]

        result = importer.get_or_create_contact("John Doe", email="john@example.com")

        assert result == 50
        # Check domain used email - args_tuple is at index 5, domain is first element
        call_args = importer.models.execute_kw.call_args
        domain = call_args[0][5][0]  # The domain argument (first element of args tuple)
        assert ("email", "=", "john@example.com") in domain

    def test_creates_contact_with_company(self, importer):
        """Test creates contact linked to company."""
        importer.models.execute_kw.side_effect = [[], 60]

        result = importer.get_or_create_contact("Jane Doe", company_id=100)

        assert result == 60

    def test_creates_contact_with_categories(self, importer):
        """Test creates contact with category IDs."""
        importer.models.execute_kw.side_effect = [[], 70]

        result = importer.get_or_create_contact("Bob Smith", category_ids=[1, 2, 3])

        assert result == 70


class TestCreateCrmLead:
    """Tests for create_crm_lead method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            return OdooLeadImporter(config)

    def test_creates_lead_with_all_fields(self, importer):
        """Test creates lead with all fields."""
        importer.models.execute_kw.return_value = 500

        result = importer.create_crm_lead(
            name="Test Lead",
            contact_id=10,
            partner_name="Acme Corp",
            email="test@example.com",
            phone="555-1234",
            expected_revenue=50000,
            description="Test description",
        )

        assert result == 500

    def test_creates_lead_with_minimal_fields(self, importer):
        """Test creates lead with minimal fields."""
        importer.models.execute_kw.return_value = 501

        result = importer.create_crm_lead(name="Simple Lead")

        assert result == 501

    def test_includes_partner_id_when_contact_provided(self, importer):
        """Test includes partner_id when contact_id provided."""
        importer.models.execute_kw.return_value = 502

        importer.create_crm_lead(name="Lead", contact_id=25)

        call_args = importer.models.execute_kw.call_args
        # args_tuple is at index 5, first element is [values], so values dict is [5][0][0]
        values = call_args[0][5][0][0]  # The values dict
        assert values["partner_id"] == 25


class TestImportCsv:
    """Tests for import_csv method."""

    @pytest.fixture
    def importer(self):
        """Create an importer with mocked connection."""
        with mock.patch("import_lead_list.xmlrpc.client.ServerProxy") as mock_proxy:
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
            return OdooLeadImporter(config)

    def test_import_csv_file_not_found(self, importer):
        """Test import_csv exits when file not found."""
        with pytest.raises(SystemExit):
            importer.import_csv("/nonexistent/file.csv")

    def test_import_csv_auto_generates_list_name(self, importer):
        """Test import_csv auto-generates list name from filename."""
        # Mock all the Odoo calls
        importer.models.execute_kw.return_value = []  # For category lookups
        importer.models.execute_kw.side_effect = [
            # setup_lead_list_categories calls
            [],
            1,  # Lead List category
            [],
            2,  # For Sale
            [],
            3,  # Outreach Target
            [],
            4,  # Premium
            [],
            5,  # High Value
            [],
            6,  # Medium Value
            [],
            7,  # Low Value
            # create_lead_list_company calls
            [],
            100,  # umbrella company
            [],
            101,  # list company
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("contact_name,contact_email\n")
            f.flush()

            try:
                stats = importer.import_csv(f.name)
                assert stats["skipped"] == 0
                assert stats["leads_created"] == 0
            finally:
                os.unlink(f.name)

    def test_import_csv_processes_rows(self, importer):
        """Test import_csv processes CSV rows."""
        # Create a simple mock that returns incrementing IDs
        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            # args: (db, uid, api_key, model, method, args_tuple, kwargs_dict)
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []  # Nothing exists
            elif method == "create":
                return call_count[0]  # Return incrementing IDs
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["contact_name", "contact_email", "company_name", "project_valuation"])
            writer.writerow(["John Doe", "john@example.com", "Acme Corp", "50000"])
            writer.writerow(["Jane Smith", "jane@example.com", "Beta Inc", "75000"])
            f.flush()

            try:
                stats = importer.import_csv(f.name, list_name="Test List")
                assert stats["leads_created"] == 2
            finally:
                os.unlink(f.name)

    def test_import_csv_skips_empty_contact_name(self, importer):
        """Test import_csv skips rows with empty contact name."""

        def mock_execute(*args, **kwargs):
            # args: (db, uid, api_key, model, method, args_tuple, kwargs_dict)
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return 1
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["contact_name", "contact_email"])
            writer.writerow(["", "empty@example.com"])  # Empty name
            writer.writerow(["OUT TO BID", "bid@example.com"])  # Special skip value
            writer.writerow(["Valid Name", "valid@example.com"])
            f.flush()

            try:
                stats = importer.import_csv(f.name, list_name="Test List")
                assert stats["skipped"] == 2
                assert stats["leads_created"] == 1
            finally:
                os.unlink(f.name)

    def test_import_csv_handles_valuation_formats(self, importer):
        """Test import_csv handles various valuation formats."""

        def mock_execute(*args, **kwargs):
            # args: (db, uid, api_key, model, method, args_tuple, kwargs_dict)
            method = args[4] if len(args) > 4 else ""
            if method == "search_read":
                return []
            elif method == "create":
                return 1
            return True

        importer.models.execute_kw.side_effect = mock_execute

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["contact_name", "project_valuation"])
            writer.writerow(["Test1", "$50,000"])
            writer.writerow(["Test2", "75000"])
            writer.writerow(["Test3", "invalid"])
            f.flush()

            try:
                stats = importer.import_csv(f.name, list_name="Test List")
                assert stats["leads_created"] == 3
            finally:
                os.unlink(f.name)
