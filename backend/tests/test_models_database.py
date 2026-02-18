"""
Tests for app.models.database — engine, session factory, get_db, and init_models.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError


# ═══════════════════════════════════════════════════════════════════
# get_db session lifecycle
# ═══════════════════════════════════════════════════════════════════
class TestGetDb:
    """Tests for the get_db async generator dependency."""

    @pytest.mark.asyncio
    async def test_yields_session_and_closes(self):
        mock_session = AsyncMock()

        with patch("app.models.database.async_session_factory", return_value=mock_session):
            from app.models.database import get_db

            gen = get_db()
            session = await gen.__anext__()
            assert session is mock_session

            # Simulate normal completion
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_on_sqlalchemy_error(self):
        mock_session = AsyncMock()

        with patch("app.models.database.async_session_factory", return_value=mock_session):
            from app.models.database import get_db

            gen = get_db()
            session = await gen.__anext__()

            # Throw a SQLAlchemy error into the generator
            with pytest.raises(SQLAlchemyError):
                await gen.athrow(SQLAlchemyError("test db error"))

            mock_session.rollback.assert_awaited_once()
            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_on_generic_exception(self):
        mock_session = AsyncMock()

        with patch("app.models.database.async_session_factory", return_value=mock_session):
            from app.models.database import get_db

            gen = get_db()
            session = await gen.__anext__()

            with pytest.raises(RuntimeError):
                await gen.athrow(RuntimeError("unexpected"))

            mock_session.rollback.assert_awaited_once()
            mock_session.close.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# Module-level objects
# ═══════════════════════════════════════════════════════════════════
class TestModuleLevelObjects:
    def test_engine_exists(self):
        from app.models.database import engine
        assert engine is not None

    def test_session_factory_exists(self):
        from app.models.database import async_session_factory
        assert async_session_factory is not None

    def test_base_class(self):
        from app.models.database import Base
        assert hasattr(Base, "metadata")


# ═══════════════════════════════════════════════════════════════════
# init_models
# ═══════════════════════════════════════════════════════════════════
class TestInitModels:
    """Tests for the init_models async startup function."""

    @pytest.mark.asyncio
    async def test_init_models_calls_create_all(self):
        """init_models should call Base.metadata.create_all via run_sync."""
        mock_conn = MagicMock()
        mock_conn.run_sync = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.models.database.engine") as mock_engine:
            mock_engine.begin.return_value = mock_ctx
            from app.models.database import init_models
            await init_models()

        mock_conn.run_sync.assert_awaited_once()
        # The argument passed to run_sync should be Base.metadata.create_all
        from app.models.database import Base
        call_args = mock_conn.run_sync.call_args
        assert call_args[0][0] == Base.metadata.create_all
