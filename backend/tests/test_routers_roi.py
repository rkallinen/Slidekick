"""
Tests for app.routers.roi — ROI stats and viewport nuclei endpoints.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.roi import router
from app.schemas.nucleus import ROIStatsResponse, ViewportNucleiResponse, NucleusBase, CellTypeCount
from app.spatial.transform import ViewportBounds
from tests.conftest import SAMPLE_SLIDE_ID, make_slide_row


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture()
def app():
    return _create_test_app()


@pytest.fixture()
def mock_db():
    return AsyncMock()


@pytest.fixture()
def client(app, mock_db):
    from app.models.database import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# ═══════════════════════════════════════════════════════════════════
# POST /roi/stats
# ═══════════════════════════════════════════════════════════════════
class TestROIStats:
    @pytest.mark.asyncio
    async def test_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.post("/api/roi/stats", json={
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000,
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("app.routers.roi.SpatialQueryService")
    async def test_roi_stats_success(self, mock_svc_cls, client, mock_db):
        mock_db.get.return_value = make_slide_row()

        mock_svc = AsyncMock()
        mock_svc.get_roi_stats.return_value = ROIStatsResponse(
            slide_id=SAMPLE_SLIDE_ID,
            total_nuclei=100,
            area_mm2=1.0,
            density_per_mm2=100.0,
            neoplastic_ratio=0.3,
            cell_type_breakdown=[
                CellTypeCount(cell_type=1, cell_type_name="Neoplastic", count=30, fraction=0.3),
            ],
            mpp=0.25,
            bounds_l0={"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
        )
        mock_svc_cls.return_value = mock_svc

        resp = await client.post("/api/roi/stats", json={
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nuclei"] == 100
        assert data["neoplastic_ratio"] == 0.3


# ═══════════════════════════════════════════════════════════════════
# POST /roi/nuclei
# ═══════════════════════════════════════════════════════════════════
class TestViewportNuclei:
    @pytest.mark.asyncio
    async def test_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.post("/api/roi/nuclei", json={
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x": 0, "y": 0, "width": 1000, "height": 1000,
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("app.routers.roi.SpatialQueryService")
    async def test_viewport_nuclei_success(self, mock_svc_cls, client, mock_db):
        mock_db.get.return_value = make_slide_row()

        mock_svc = AsyncMock()
        mock_svc.get_nuclei_in_viewport.return_value = ViewportNucleiResponse(
            slide_id=SAMPLE_SLIDE_ID,
            bounds_l0={"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
            nuclei=[
                NucleusBase(
                    id=1, x=100, y=200,
                    cell_type=1, cell_type_name="Neoplastic",
                    probability=0.9,
                ),
            ],
        )
        mock_svc_cls.return_value = mock_svc

        resp = await client.post("/api/roi/nuclei", json={
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x": 0, "y": 0, "width": 1000, "height": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nuclei"]) == 1
        assert data["nuclei"][0]["cell_type_name"] == "Neoplastic"

    @pytest.mark.asyncio
    async def test_invalid_negative_level(self, client, mock_db):
        """ViewportQuery rejects negative level."""
        resp = await client.post("/api/roi/nuclei", json={
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x": 0, "y": 0, "width": 100, "height": 100,
            "level": -1,
        })
        assert resp.status_code == 422
