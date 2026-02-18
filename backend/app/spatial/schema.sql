-- ============================================================
-- Slidekick — PostGIS Extension Initialization
-- ============================================================
-- This script ensures the PostGIS extension is available.
-- It runs once when the PostgreSQL container is first created
-- (via docker-entrypoint-initdb.d).
--
-- All table DDL is managed by SQLAlchemy's metadata.create_all
-- (called during FastAPI lifespan startup), which issues
-- CREATE TABLE IF NOT EXISTS for every ORM model.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
