"""Unit tests for scripts/config.py"""

import os
import sys
from unittest import mock

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from config import _getenv, load_odoo_config, load_postgres_config, require_config


class TestGetenv:
    """Tests for _getenv helper function."""

    def test_returns_value_when_set(self):
        with mock.patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            assert _getenv("TEST_VAR") == "test_value"

    def test_returns_default_when_not_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert _getenv("NONEXISTENT_VAR", "default") == "default"

    def test_returns_default_when_empty_string(self):
        with mock.patch.dict(os.environ, {"EMPTY_VAR": ""}):
            assert _getenv("EMPTY_VAR", "default") == "default"

    def test_returns_none_when_not_set_and_no_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert _getenv("NONEXISTENT_VAR") is None


class TestLoadOdooConfig:
    """Tests for load_odoo_config function."""

    def test_returns_defaults_when_no_env_vars(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_odoo_config()

            assert config["url"] == "http://192.168.0.230:8069"
            assert config["db"] == "aiqso_db"
            assert config["username"] == "quinn@aiqso.io"
            assert config["api_key"] is None

    def test_reads_from_environment_variables(self):
        env = {
            "ODOO_URL": "http://custom.odoo.com:8080",
            "ODOO_DB": "custom_db",
            "ODOO_USERNAME": "admin@example.com",
            "ODOO_API_KEY": "secret_key_123",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_odoo_config()

            assert config["url"] == "http://custom.odoo.com:8080"
            assert config["db"] == "custom_db"
            assert config["username"] == "admin@example.com"
            assert config["api_key"] == "secret_key_123"

    def test_overrides_take_precedence(self):
        env = {"ODOO_URL": "http://env.odoo.com"}
        overrides = {"url": "http://override.odoo.com", "db": "override_db"}

        with mock.patch.dict(os.environ, env, clear=True):
            config = load_odoo_config(overrides=overrides)

            assert config["url"] == "http://override.odoo.com"
            assert config["db"] == "override_db"

    def test_none_overrides_are_ignored(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_odoo_config(overrides={"url": None, "db": ""})

            # Should keep defaults, not override with None/empty
            assert config["url"] == "http://192.168.0.230:8069"
            assert config["db"] == "aiqso_db"

    def test_partial_env_vars(self):
        env = {"ODOO_URL": "http://partial.odoo.com"}

        with mock.patch.dict(os.environ, env, clear=True):
            config = load_odoo_config()

            assert config["url"] == "http://partial.odoo.com"
            assert config["db"] == "aiqso_db"  # default


class TestLoadPostgresConfig:
    """Tests for load_postgres_config function."""

    def test_returns_defaults_when_no_env_vars(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_postgres_config()

            assert config["host"] == "192.168.0.71"
            assert config["port"] == 5433
            assert config["database"] == "permits_db"
            assert config["user"] == "permits"
            assert config["password"] is None

    def test_reads_from_environment_variables(self):
        env = {
            "POSTGRES_HOST": "db.example.com",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "production_db",
            "POSTGRES_USER": "prod_user",
            "POSTGRES_PASSWORD": "secret_password",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_postgres_config()

            assert config["host"] == "db.example.com"
            assert config["port"] == 5432
            assert config["database"] == "production_db"
            assert config["user"] == "prod_user"
            assert config["password"] == "secret_password"

    def test_port_is_integer(self):
        env = {"POSTGRES_PORT": "1234"}

        with mock.patch.dict(os.environ, env, clear=True):
            config = load_postgres_config()

            assert config["port"] == 1234
            assert isinstance(config["port"], int)

    def test_overrides_take_precedence(self):
        overrides = {"host": "override.db.com", "port": 9999}

        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_postgres_config(overrides=overrides)

            assert config["host"] == "override.db.com"
            assert config["port"] == 9999

    def test_none_overrides_are_ignored(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_postgres_config(overrides={"host": None, "database": ""})

            assert config["host"] == "192.168.0.71"
            assert config["database"] == "permits_db"


class TestRequireConfig:
    """Tests for require_config function."""

    def test_passes_when_all_keys_present(self):
        config = {"url": "http://example.com", "db": "mydb", "api_key": "secret"}

        # Should not raise
        require_config(config, ["url", "db", "api_key"], "TEST_VARS")

    def test_raises_system_exit_when_keys_missing(self):
        config = {"url": "http://example.com", "db": None}

        with pytest.raises(SystemExit) as exc_info:
            require_config(config, ["url", "db", "api_key"], "TEST_VARS")

        error_message = str(exc_info.value)
        assert "db" in error_message
        assert "api_key" in error_message
        assert "TEST_VARS" in error_message

    def test_raises_when_key_is_empty_string(self):
        config = {"url": "http://example.com", "db": ""}

        with pytest.raises(SystemExit) as exc_info:
            require_config(config, ["url", "db"], "TEST_VARS")

        assert "db" in str(exc_info.value)

    def test_raises_when_key_is_none(self):
        config = {"url": "http://example.com", "db": None}

        with pytest.raises(SystemExit) as exc_info:
            require_config(config, ["url", "db"], "TEST_VARS")

        assert "db" in str(exc_info.value)

    def test_passes_with_empty_required_keys(self):
        config = {"url": "http://example.com"}

        # Should not raise
        require_config(config, [], "TEST_VARS")

    def test_error_message_format(self):
        config = {"a": "value"}

        with pytest.raises(SystemExit) as exc_info:
            require_config(config, ["a", "b", "c"], "ENV_HINT")

        error_message = str(exc_info.value)
        assert "Missing required configuration values: b, c" in error_message
        assert "ENV_HINT" in error_message
