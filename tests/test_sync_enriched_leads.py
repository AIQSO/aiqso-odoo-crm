"""Unit tests for scripts/sync_enriched_leads.py"""

import os
import sys
from unittest import mock

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from sync_enriched_leads import EnrichedLeadSync


class TestEnrichedLeadSyncInit:
    """Tests for EnrichedLeadSync initialization."""

    def test_init_with_default_configs(self):
        """Test initialization uses default config loaders."""
        with mock.patch("sync_enriched_leads.load_postgres_config") as mock_pg:
            with mock.patch("sync_enriched_leads.load_odoo_config") as mock_odoo:
                mock_pg.return_value = {"host": "localhost"}
                mock_odoo.return_value = {"url": "http://localhost"}

                syncer = EnrichedLeadSync()

                mock_pg.assert_called_once()
                mock_odoo.assert_called_once()
                assert syncer.pg_config == {"host": "localhost"}
                assert syncer.odoo_config == {"url": "http://localhost"}

    def test_init_with_custom_configs(self):
        """Test initialization with custom configs."""
        pg_config = {"host": "custom-pg", "port": 5432}
        odoo_config = {"url": "http://custom-odoo"}

        syncer = EnrichedLeadSync(postgres_config=pg_config, odoo_config=odoo_config)

        assert syncer.pg_config == pg_config
        assert syncer.odoo_config == odoo_config
        assert syncer.pg_conn is None
        assert syncer.odoo_uid is None
        assert syncer.odoo_models is None
        assert syncer._odoo_field_cache == {}


class TestConnectPostgres:
    """Tests for PostgreSQL connection."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked configs."""
        pg_config = {
            "host": "localhost",
            "port": 5432,
            "database": "test_db",
            "user": "test_user",
            "password": "test_pass",
        }
        odoo_config = {"url": "http://localhost", "db": "odoo", "username": "admin", "api_key": "key"}
        return EnrichedLeadSync(postgres_config=pg_config, odoo_config=odoo_config)

    @mock.patch("sync_enriched_leads.psycopg2.connect")
    def test_successful_connection(self, mock_connect, syncer):
        """Test successful PostgreSQL connection."""
        mock_conn = mock.MagicMock()
        mock_connect.return_value = mock_conn

        syncer.connect_postgres()

        mock_connect.assert_called_once_with(
            host="localhost",
            port=5432,
            database="test_db",
            user="test_user",
            password="test_pass",
        )
        assert syncer.pg_conn == mock_conn

    @mock.patch("sync_enriched_leads.psycopg2.connect")
    def test_connection_failure(self, mock_connect, syncer):
        """Test PostgreSQL connection failure exits."""
        mock_connect.side_effect = Exception("Connection refused")

        with pytest.raises(SystemExit):
            syncer.connect_postgres()

    def test_missing_config_exits(self):
        """Test missing config exits."""
        syncer = EnrichedLeadSync(postgres_config={}, odoo_config={})

        with pytest.raises(SystemExit):
            syncer.connect_postgres()


class TestConnectOdoo:
    """Tests for Odoo connection."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked configs."""
        pg_config = {"host": "localhost"}
        odoo_config = {
            "url": "http://localhost:8069",
            "db": "odoo_db",
            "username": "admin",
            "api_key": "secret_key",
        }
        return EnrichedLeadSync(postgres_config=pg_config, odoo_config=odoo_config)

    @mock.patch("sync_enriched_leads.xmlrpc.client.ServerProxy")
    def test_successful_connection(self, mock_proxy, syncer):
        """Test successful Odoo connection."""
        mock_common = mock.MagicMock()
        mock_common.authenticate.return_value = 123
        mock_models = mock.MagicMock()
        mock_proxy.side_effect = [mock_common, mock_models]

        syncer.connect_odoo()

        assert syncer.odoo_uid == 123
        assert syncer.odoo_models == mock_models
        mock_common.authenticate.assert_called_once_with("odoo_db", "admin", "secret_key", {})

    @mock.patch("sync_enriched_leads.xmlrpc.client.ServerProxy")
    def test_authentication_failure(self, mock_proxy, syncer):
        """Test Odoo authentication failure exits."""
        mock_common = mock.MagicMock()
        mock_common.authenticate.return_value = None
        mock_proxy.return_value = mock_common

        with pytest.raises(SystemExit):
            syncer.connect_odoo()

    @mock.patch("sync_enriched_leads.xmlrpc.client.ServerProxy")
    def test_connection_exception(self, mock_proxy, syncer):
        """Test Odoo connection exception exits."""
        mock_proxy.side_effect = Exception("Connection refused")

        with pytest.raises(SystemExit):
            syncer.connect_odoo()

    def test_missing_config_exits(self):
        """Test missing Odoo config exits."""
        syncer = EnrichedLeadSync(postgres_config={}, odoo_config={})

        with pytest.raises(SystemExit):
            syncer.connect_odoo()


class TestOdooExecute:
    """Tests for odoo_execute method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        return syncer

    def test_execute_passes_arguments(self, syncer):
        """Test odoo_execute passes arguments correctly."""
        syncer.odoo_models.execute_kw.return_value = [{"id": 1}]

        result = syncer.odoo_execute("res.partner", "search_read", [("name", "=", "Test")])

        syncer.odoo_models.execute_kw.assert_called_once()
        call_args = syncer.odoo_models.execute_kw.call_args
        assert call_args[0][0] == "test_db"
        assert call_args[0][1] == 1
        assert call_args[0][2] == "key"
        assert call_args[0][3] == "res.partner"
        assert call_args[0][4] == "search_read"
        assert result == [{"id": 1}]


class TestOdooModelFields:
    """Tests for odoo_model_fields method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        return syncer

    def test_returns_field_names(self, syncer):
        """Test returns set of field names."""
        syncer.odoo_models.execute_kw.return_value = {
            "name": {"string": "Name"},
            "email": {"string": "Email"},
            "phone": {"string": "Phone"},
        }

        fields = syncer.odoo_model_fields("res.partner")

        assert fields == {"name", "email", "phone"}

    def test_caches_results(self, syncer):
        """Test caches field results."""
        syncer.odoo_models.execute_kw.return_value = {"name": {"string": "Name"}}

        # First call
        syncer.odoo_model_fields("res.partner")
        # Second call
        syncer.odoo_model_fields("res.partner")

        # Should only call execute_kw once
        assert syncer.odoo_models.execute_kw.call_count == 1

    def test_handles_non_dict_response(self, syncer):
        """Test handles non-dict response."""
        syncer.odoo_models.execute_kw.return_value = None

        fields = syncer.odoo_model_fields("res.partner")

        assert fields == set()


class TestOdooFilterValues:
    """Tests for odoo_filter_values method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        syncer.odoo_models.execute_kw.return_value = {
            "name": {"string": "Name"},
            "email": {"string": "Email"},
        }
        return syncer

    def test_filters_invalid_fields(self, syncer):
        """Test filters out invalid fields."""
        values = {"name": "Test", "email": "test@example.com", "invalid_field": "value"}

        filtered = syncer.odoo_filter_values("res.partner", values)

        assert filtered == {"name": "Test", "email": "test@example.com"}
        assert "invalid_field" not in filtered


class TestGetEnrichedLeads:
    """Tests for get_enriched_leads method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked PostgreSQL connection."""
        syncer = EnrichedLeadSync(postgres_config={}, odoo_config={})
        syncer.pg_conn = mock.MagicMock()
        return syncer

    def test_returns_leads(self, syncer):
        """Test returns enriched leads."""
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchall.return_value = [
            {"lead_id": 1, "permit_number": "P001", "contact_email": "test@example.com"},
            {"lead_id": 2, "permit_number": "P002", "contact_email": "test2@example.com"},
        ]
        syncer.pg_conn.cursor.return_value.__enter__ = mock.MagicMock(return_value=mock_cursor)
        syncer.pg_conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)

        results = syncer.get_enriched_leads()

        assert len(results) == 2
        assert results[0]["permit_number"] == "P001"

    def test_filters_by_city(self, syncer):
        """Test filters by city when provided."""
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchall.return_value = []
        syncer.pg_conn.cursor.return_value.__enter__ = mock.MagicMock(return_value=mock_cursor)
        syncer.pg_conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)

        syncer.get_enriched_leads(city="Fort Worth")

        # Check that city was passed as parameter
        call_args = mock_cursor.execute.call_args
        assert "Fort Worth" in call_args[0][1]


class TestFindOdooLeadByPermit:
    """Tests for find_odoo_lead_by_permit method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked Odoo connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        return syncer

    def test_returns_lead_when_found(self, syncer):
        """Test returns lead when found."""
        syncer.odoo_models.execute_kw.return_value = [{"id": 100, "name": "[P001] Test Lead"}]

        result = syncer.find_odoo_lead_by_permit("P001")

        assert result == {"id": 100, "name": "[P001] Test Lead"}

    def test_returns_none_when_not_found(self, syncer):
        """Test returns None when not found."""
        syncer.odoo_models.execute_kw.return_value = []

        result = syncer.find_odoo_lead_by_permit("P999")

        assert result is None


class TestFindOdooContactByEmail:
    """Tests for find_odoo_contact_by_email method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked Odoo connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        return syncer

    def test_returns_contact_when_found(self, syncer):
        """Test returns contact when found."""
        syncer.odoo_models.execute_kw.return_value = [{"id": 50, "name": "John", "email": "john@example.com"}]

        result = syncer.find_odoo_contact_by_email("john@example.com")

        assert result["id"] == 50

    def test_returns_none_for_empty_email(self, syncer):
        """Test returns None for empty email."""
        result = syncer.find_odoo_contact_by_email("")

        assert result is None
        syncer.odoo_models.execute_kw.assert_not_called()

    def test_returns_none_when_not_found(self, syncer):
        """Test returns None when not found."""
        syncer.odoo_models.execute_kw.return_value = []

        result = syncer.find_odoo_contact_by_email("unknown@example.com")

        assert result is None


class TestUpdateOdooLead:
    """Tests for update_odoo_lead method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked Odoo connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        # Mock field validation to allow all common fields
        syncer._odoo_field_cache["crm.lead"] = {
            "email_from",
            "phone",
            "contact_name",
            "partner_name",
            "description",
        }
        return syncer

    def test_updates_email(self, syncer):
        """Test updates email field."""
        syncer.odoo_models.execute_kw.return_value = [{"description": ""}]

        result = syncer.update_odoo_lead(1, {"contact_email": "new@example.com"})

        assert result is True

    def test_formats_phone_number(self, syncer):
        """Test formats 10-digit phone number."""
        syncer.odoo_models.execute_kw.return_value = [{"description": ""}]

        syncer.update_odoo_lead(1, {"contact_phone": "5551234567"})

        # Check that write was called with formatted phone
        write_calls = [c for c in syncer.odoo_models.execute_kw.call_args_list if c[0][4] == "write"]
        assert len(write_calls) > 0

    def test_returns_false_when_no_updates(self, syncer):
        """Test returns False when no updates needed."""
        result = syncer.update_odoo_lead(1, {})

        assert result is False


class TestUpdateOdooContact:
    """Tests for update_odoo_contact method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked Odoo connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        syncer._odoo_field_cache["res.partner"] = {"phone", "parent_id"}
        return syncer

    def test_updates_phone(self, syncer):
        """Test updates phone field."""
        syncer.odoo_models.execute_kw.return_value = True

        result = syncer.update_odoo_contact(1, {"contact_phone": "5551234567"})

        assert result is True

    def test_links_to_company(self, syncer):
        """Test links contact to existing company."""
        syncer.odoo_models.execute_kw.side_effect = [[{"id": 100}], True]

        result = syncer.update_odoo_contact(1, {"company_name": "Acme Corp"})

        assert result is True

    def test_returns_false_when_no_updates(self, syncer):
        """Test returns False when no updates needed."""
        result = syncer.update_odoo_contact(1, {})

        assert result is False


class TestCreateOdooLead:
    """Tests for create_odoo_lead method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked Odoo connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        syncer._odoo_field_cache["crm.lead"] = {
            "name",
            "type",
            "partner_name",
            "expected_revenue",
            "description",
            "contact_name",
            "email_from",
            "phone",
            "street",
        }
        return syncer

    def test_creates_lead_with_all_fields(self, syncer):
        """Test creates lead with all fields."""
        syncer.odoo_models.execute_kw.return_value = 500

        enriched_data = {
            "permit_number": "P001",
            "city_name": "Fort Worth",
            "company_name": "Acme Corp",
            "contact_name": "John Doe",
            "contact_email": "john@example.com",
            "contact_phone": "5551234567",
            "project_valuation": 100000,
            "permit_type": "Commercial",
            "owner_name": "Jane Owner",
            "contact_role": "Manager",
            "score": 85,
            "valuation_tier": "High Value",
            "address_line1": "123 Main St",
        }

        result = syncer.create_odoo_lead(enriched_data)

        assert result == 500

    def test_creates_lead_with_minimal_fields(self, syncer):
        """Test creates lead with minimal fields."""
        syncer.odoo_models.execute_kw.return_value = 501

        result = syncer.create_odoo_lead({"permit_number": "P002"})

        assert result == 501

    def test_handles_list_response(self, syncer):
        """Test handles list response from Odoo."""
        syncer.odoo_models.execute_kw.return_value = [502]

        result = syncer.create_odoo_lead({"permit_number": "P003"})

        assert result == 502

    def test_handles_exception(self, syncer):
        """Test handles exception during creation."""
        syncer.odoo_models.execute_kw.side_effect = Exception("Create failed")

        result = syncer.create_odoo_lead({"permit_number": "P004"})

        assert result is None

    def test_formats_phone_number(self, syncer):
        """Test formats 10-digit phone number."""
        syncer.odoo_models.execute_kw.return_value = 503

        syncer.create_odoo_lead({"permit_number": "P005", "contact_phone": "5551234567"})

        call_args = syncer.odoo_models.execute_kw.call_args
        values = call_args[0][5][0][0]
        assert values["phone"] == "(555) 123-4567"


class TestSync:
    """Tests for sync method."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked connections."""
        syncer = EnrichedLeadSync(
            postgres_config={
                "host": "localhost",
                "port": 5432,
                "database": "test",
                "user": "user",
                "password": "pass",
            },
            odoo_config={
                "url": "http://localhost",
                "db": "odoo",
                "username": "admin",
                "api_key": "key",
            },
        )
        return syncer

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    def test_sync_with_no_leads(self, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync with no enriched leads."""
        mock_get_leads.return_value = []

        stats = syncer.sync()

        assert stats["synced"] == 0
        assert stats["not_found"] == 0

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    @mock.patch.object(EnrichedLeadSync, "update_odoo_lead")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_contact_by_email")
    @mock.patch.object(EnrichedLeadSync, "update_odoo_contact")
    def test_sync_updates_existing_leads(
        self, mock_update_contact, mock_find_contact, mock_update, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer
    ):
        """Test sync updates existing leads."""
        mock_get_leads.return_value = [
            {"permit_number": "P001", "contact_email": "new@example.com"},
        ]
        mock_find.return_value = {"id": 100, "email_from": "old@example.com"}
        mock_update.return_value = True
        mock_find_contact.return_value = {"id": 50}
        mock_update_contact.return_value = True
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync()

        assert stats["synced"] == 1
        mock_update.assert_called_once()

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    def test_sync_dry_run_mode(self, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync in dry run mode."""
        mock_get_leads.return_value = [
            {"permit_number": "P001", "contact_email": "test@example.com", "contact_name": "John"},
        ]
        mock_find.return_value = {"id": 100, "email_from": "old@example.com"}
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync(dry_run=True)

        assert stats["synced"] == 1

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    def test_sync_counts_not_found(self, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync counts leads not found in Odoo."""
        mock_get_leads.return_value = [
            {"permit_number": "P001", "contact_email": "test@example.com"},
        ]
        mock_find.return_value = None
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync()

        assert stats["not_found"] == 1

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    @mock.patch.object(EnrichedLeadSync, "create_odoo_lead")
    def test_sync_creates_new_leads(self, mock_create, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync creates new leads when create_new=True."""
        mock_get_leads.return_value = [
            {"permit_number": "P001", "contact_email": "test@example.com"},
        ]
        mock_find.return_value = None
        mock_create.return_value = 500
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync(create_new=True)

        assert stats["created"] == 1
        mock_create.assert_called_once()

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    def test_sync_skips_empty_permit(self, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync skips leads with empty permit number."""
        mock_get_leads.return_value = [
            {"permit_number": "", "contact_email": "test@example.com"},
        ]
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync()

        assert stats["skipped"] == 1
        mock_find.assert_not_called()

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    @mock.patch.object(EnrichedLeadSync, "find_odoo_lead_by_permit")
    def test_sync_skips_already_synced(self, mock_find, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync skips leads with same email already in Odoo."""
        mock_get_leads.return_value = [
            {"permit_number": "P001", "contact_email": "same@example.com"},
        ]
        mock_find.return_value = {"id": 100, "email_from": "same@example.com"}
        syncer.pg_conn = mock.MagicMock()

        stats = syncer.sync()

        assert stats["skipped"] == 1

    @mock.patch.object(EnrichedLeadSync, "connect_postgres")
    @mock.patch.object(EnrichedLeadSync, "connect_odoo")
    @mock.patch.object(EnrichedLeadSync, "get_enriched_leads")
    def test_sync_with_city_filter(self, mock_get_leads, mock_odoo, mock_pg, syncer):
        """Test sync passes city filter."""
        mock_get_leads.return_value = []
        syncer.pg_conn = mock.MagicMock()

        syncer.sync(city="Fort Worth")

        mock_get_leads.assert_called_once_with(city="Fort Worth")


class TestPhoneFormatting:
    """Tests for phone number formatting in various methods."""

    @pytest.fixture
    def syncer(self):
        """Create syncer with mocked connection."""
        syncer = EnrichedLeadSync(
            postgres_config={},
            odoo_config={"db": "test_db", "api_key": "key"},
        )
        syncer.odoo_uid = 1
        syncer.odoo_models = mock.MagicMock()
        syncer._odoo_field_cache["crm.lead"] = {"phone", "email_from", "description"}
        syncer._odoo_field_cache["res.partner"] = {"phone", "parent_id"}
        return syncer

    def test_formats_10_digit_phone_in_lead(self, syncer):
        """Test formats 10-digit phone in update_odoo_lead."""
        syncer.odoo_models.execute_kw.return_value = [{"description": ""}]

        syncer.update_odoo_lead(1, {"contact_phone": "5551234567"})

        write_calls = [c for c in syncer.odoo_models.execute_kw.call_args_list if c[0][4] == "write"]
        if write_calls:
            values = write_calls[0][0][5][1]
            assert values.get("phone") == "(555) 123-4567"

    def test_formats_10_digit_phone_in_contact(self, syncer):
        """Test formats 10-digit phone in update_odoo_contact."""
        syncer.odoo_models.execute_kw.return_value = True

        syncer.update_odoo_contact(1, {"contact_phone": "5551234567"})

        call_args = syncer.odoo_models.execute_kw.call_args
        values = call_args[0][5][1]
        assert values.get("phone") == "(555) 123-4567"

    def test_preserves_non_10_digit_phone(self, syncer):
        """Test preserves non-10-digit phone numbers."""
        syncer.odoo_models.execute_kw.return_value = [{"description": ""}]

        syncer.update_odoo_lead(1, {"contact_phone": "12345"})

        write_calls = [c for c in syncer.odoo_models.execute_kw.call_args_list if c[0][4] == "write"]
        if write_calls:
            values = write_calls[0][0][5][1]
            assert values.get("phone") == "12345"
