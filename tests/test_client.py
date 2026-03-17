"""Tests for the shared OdooClient."""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aiqso_crm.client import OdooClient, OdooConnectionError


@pytest.fixture
def client():
    return OdooClient(
        url="http://localhost:8069",
        db="test_db",
        username="admin",
        api_key="test-key",
    )


@pytest.fixture
def connected_client(client):
    """Client with mocked XML-RPC proxies already connected."""
    mock_models = mock.MagicMock()
    client._uid = 1
    client._models = mock_models
    return client, mock_models


class TestOdooClientInit:
    def test_from_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "ODOO_URL": "http://test:8069",
                "ODOO_DB": "mydb",
                "ODOO_USERNAME": "user",
                "ODOO_API_KEY": "key123",
            },
        ):
            c = OdooClient.from_env()
            assert c.url == "http://test:8069"
            assert c.db == "mydb"
            assert c.username == "user"
            assert c.api_key == "key123"

    def test_from_env_missing_key(self):
        with mock.patch.dict(os.environ, {"ODOO_API_KEY": ""}, clear=False):
            os.environ.pop("ODOO_API_KEY", None)
            with pytest.raises(OdooConnectionError):
                OdooClient.from_env()

    def test_url_trailing_slash_stripped(self):
        c = OdooClient(url="http://test:8069/", db="db", username="u", api_key="k")
        assert c.url == "http://test:8069"


class TestAuthentication:
    @mock.patch("aiqso_crm.client.xmlrpc.client.ServerProxy")
    def test_authenticate_success(self, mock_proxy_cls, client):
        mock_proxy = mock.MagicMock()
        mock_proxy.authenticate.return_value = 42
        mock_proxy_cls.return_value = mock_proxy

        uid = client.uid
        assert uid == 42

    @mock.patch("aiqso_crm.client.xmlrpc.client.ServerProxy")
    def test_authenticate_failure(self, mock_proxy_cls, client):
        mock_proxy = mock.MagicMock()
        mock_proxy.authenticate.return_value = False
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(OdooConnectionError, match="Authentication failed"):
            _ = client.uid

    @mock.patch("aiqso_crm.client.xmlrpc.client.ServerProxy")
    def test_authenticate_cached(self, mock_proxy_cls, client):
        mock_proxy = mock.MagicMock()
        mock_proxy.authenticate.return_value = 42
        mock_proxy_cls.return_value = mock_proxy

        _ = client.uid
        _ = client.uid
        assert mock_proxy.authenticate.call_count == 1


class TestExecute:
    def test_search_read(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = [{"id": 1, "name": "Test"}]

        result = client.search_read("crm.lead", [], fields=["name"], limit=10)
        assert len(result) == 1
        assert result[0]["name"] == "Test"
        mock_models.execute_kw.assert_called_once()

    def test_create_returns_int(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = 99

        result = client.create("crm.lead", {"name": "New Lead"})
        assert result == 99

    def test_create_returns_list(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = [99]

        result = client.create("crm.lead", {"name": "New Lead"})
        assert result == 99

    def test_write(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = True

        result = client.write("crm.lead", [1], {"name": "Updated"})
        assert result is True

    def test_unlink(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = True

        result = client.unlink("crm.lead", [1])
        assert result is True

    def test_search_count(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = 42

        result = client.search_count("crm.lead", [])
        assert result == 42


class TestHighLevelHelpers:
    def test_get_or_create_partner_existing(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = [{"id": 5}]

        result = client.get_or_create_partner("Test", email="test@example.com")
        assert result == 5

    def test_get_or_create_partner_creates_new(self, connected_client):
        client, mock_models = connected_client
        # First call: search by name returns empty, second call: create returns ID
        mock_models.execute_kw.side_effect = [[], 10]

        result = client.get_or_create_partner("New Company", is_company=True)
        assert result == 10

    def test_get_or_create_category_existing(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = [{"id": 10}]

        result = client.get_or_create_category("Lead List")
        assert result == 10

    def test_move_lead_to_stage_success(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.side_effect = [
            [{"id": 3}],  # find stage
            True,  # write
        ]

        result = client.move_lead_to_stage(1, "Qualified")
        assert result is True

    def test_move_lead_to_stage_not_found(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = []

        result = client.move_lead_to_stage(1, "NonExistent")
        assert result is False

    def test_filter_values(self, connected_client):
        client, mock_models = connected_client
        mock_models.execute_kw.return_value = {"name": {"string": "Name"}, "email_from": {"string": "Email"}}

        filtered = client.filter_values("crm.lead", {"name": "Test", "invalid_field": "x"})
        assert "name" in filtered
        assert "invalid_field" not in filtered
