"""
Tests for app.config — Settings, properties, and factory.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestSettings:
    """Tests for the Settings pydantic-settings model."""

    def _make_settings(self, **overrides):
        """Create a fresh Settings instance with optional overrides via env vars.

        We explicitly set _env_file=None so that the real .env file does
        not interfere with unit-test assertions about built-in defaults.
        """
        env = {f"SLIDEKICK_{k.upper()}": str(v) for k, v in overrides.items()}
        # Remove any SLIDEKICK_* env vars that could leak from the host
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("SLIDEKICK_")}
        clean_env.update(env)
        with patch.dict(os.environ, clean_env, clear=True):
            from app.config import Settings
            return Settings(_env_file=None)

    # ── Defaults ──────────────────────────────────────────────

    def test_default_app_name(self):
        s = self._make_settings()
        assert s.app_name == "Slidekick"

    def test_default_debug(self):
        s = self._make_settings()
        assert s.debug is False

    def test_default_db_host(self):
        s = self._make_settings()
        assert s.db_host == "localhost"

    def test_default_db_port(self):
        s = self._make_settings()
        assert s.db_port == 5432

    def test_default_db_user(self):
        s = self._make_settings()
        assert s.db_user == "slidekick"

    def test_default_db_password(self):
        s = self._make_settings()
        assert s.db_password == "slidekick_secret"

    def test_default_db_name(self):
        s = self._make_settings()
        assert s.db_name == "slidekick"

    def test_default_hovernet_model(self):
        s = self._make_settings()
        assert s.hovernet_model == "hovernet_fast-pannuke"

    def test_default_device_empty(self):
        s = self._make_settings()
        assert s.device == ""

    def test_default_tile_size(self):
        s = self._make_settings()
        assert s.tile_size == 256

    def test_default_batch_size(self):
        s = self._make_settings()
        assert s.batch_size == 8

    def test_default_allow_untrusted_model_load(self):
        s = self._make_settings()
        assert s.allow_untrusted_model_load is False

    def test_default_mpp(self):
        s = self._make_settings()
        assert s.default_mpp == 0.25

    def test_default_cors_origins(self):
        s = self._make_settings()
        assert "localhost:5173" in s.cors_origins

    def test_default_cell_type_map(self):
        s = self._make_settings()
        assert s.cell_type_map[0] == "Background"
        assert s.cell_type_map[1] == "Neoplastic"
        assert s.cell_type_map[2] == "Inflammatory"
        assert s.cell_type_map[3] == "Connective"
        assert s.cell_type_map[4] == "Dead"
        assert s.cell_type_map[5] == "Non-Neoplastic Epithelial"

    # ── Properties ────────────────────────────────────────────

    def test_database_url(self):
        s = self._make_settings()
        url = s.database_url
        assert url.startswith("postgresql+asyncpg://")
        assert "slidekick" in url
        assert "5432" in url

    def test_cors_origins_list(self):
        s = self._make_settings()
        origins = s.cors_origins_list
        assert isinstance(origins, list)
        assert "http://localhost:5173" in origins
        assert "http://localhost:3000" in origins

    def test_cors_origins_list_single(self):
        s = self._make_settings()
        # Override cors_origins to a single value
        s.cors_origins = "http://example.com"
        assert s.cors_origins_list == ["http://example.com"]

    def test_cors_origins_list_empty_entries(self):
        s = self._make_settings()
        s.cors_origins = "http://a.com, , http://b.com, "
        result = s.cors_origins_list
        assert result == ["http://a.com", "http://b.com"]

    # ── Env overrides ─────────────────────────────────────────

    def test_override_debug(self):
        s = self._make_settings(debug="true")
        assert s.debug is True

    def test_override_db_port(self):
        s = self._make_settings(db_port="5555")
        assert s.db_port == 5555

    def test_override_default_mpp(self):
        s = self._make_settings(default_mpp="0.5")
        assert s.default_mpp == 0.5


class TestGetSettings:
    """Tests for the get_settings cached factory."""

    def test_returns_settings_instance(self):
        from app.config import Settings, get_settings
        # Clear cache for clean test
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_caching(self):
        from app.config import get_settings
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_returns_fresh(self):
        from app.config import get_settings
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # New instance after cache clear
        assert s1 is not s2
