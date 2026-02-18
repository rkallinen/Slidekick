"""
Async SQLAlchemy engine & session factory for PostGIS.

Table Creation
--------------
``init_models()`` uses ``Base.metadata.create_all`` (via
``run_sync``) to issue ``CREATE TABLE IF NOT EXISTS`` for every
registered ORM model.  It's idempotent, running it against an
already-provisioned database is a no-op.  The function is called
once during the FastAPI lifespan startup phase.

Session Lifecycle
-----------------
The ``get_db`` dependency yields an ``AsyncSession`` with **no
automatic commit**.  Callers (routers / services) must explicitly
call ``await session.commit()`` when their unit-of-work succeeds.

This pattern prevents the race condition where a concurrent request
triggers an auto-commit in the middle of another request's
transaction.  Each session is independent and short-lived.

Error Handling
--------------
- ``SQLAlchemyError`` is caught explicitly so database-specific
  issues (constraint violations, deadlocks, connection drops) are
  rolled back and re-raised with clear context.
- A broad ``Exception`` catch handles unexpected errors from
  middleware or business logic that occur while the session is open.
- ``session.close()`` runs in the ``finally`` block regardless.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """
    FastAPI dependency — yields an async DB session.

    **No auto-commit.**  The caller (router / service) is responsible
    for calling ``await session.commit()`` at the appropriate
    transaction boundary.  This prevents race conditions caused by
    one request's auto-commit interleaving with another's writes.

    On error the session is rolled back, and the exception is
    re-raised so FastAPI's exception handlers can produce the correct
    HTTP response.
    """
    session = async_session_factory()
    try:
        yield session
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error("Database error: %s", exc, exc_info=True)
        raise
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_models() -> None:
    """
    Create all tables defined in ``Base.metadata`` if they do not
    already exist.

    Uses ``run_sync`` to execute SQLAlchemy Core's
    ``metadata.create_all`` inside the async engine.  This is
    idempotent (``CREATE TABLE IF NOT EXISTS``) and safe to call on
    every startup. Existing tables and data are never dropped.

    Must be called **after** all model modules have been imported
    so that ``Base.metadata`` is fully populated.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
