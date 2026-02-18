"""Routers subpackage — HTTP layer for all API endpoints."""

from app.routers import boxes, inference, roi, slides

__all__ = ["boxes", "inference", "roi", "slides"]
