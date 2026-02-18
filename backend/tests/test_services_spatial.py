"""
Tests for app.services.spatial — SpatialQueryService.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.spatial import SpatialQueryService
from app.spatial.transform import ViewportBounds


SLIDE_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class TestSpatialQueryService:
    """Tests with a mocked AsyncSession."""

    @pytest.fixture()
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture()
    def svc(self, mock_session):
        return SpatialQueryService(mock_session)

    # ── get_nuclei_in_viewport ────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_nuclei_in_viewport_empty(self, svc, mock_session):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=1000, y_max=1000)
        resp = await svc.get_nuclei_in_viewport(SLIDE_ID, bounds)

        assert resp.slide_id == SLIDE_ID
        assert resp.nuclei == []
        assert resp.bounds_l0["x_min"] == 0

    @pytest.mark.asyncio
    async def test_get_nuclei_in_viewport_returns_nuclei(self, svc, mock_session):
        row = MagicMock()
        row.id = 1
        row.x = 100.0
        row.y = 200.0
        row.cell_type = 1
        row.cell_type_name = "Neoplastic"
        row.probability = 0.95

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=1000, y_max=1000)
        resp = await svc.get_nuclei_in_viewport(SLIDE_ID, bounds)

        assert len(resp.nuclei) == 1
        assert resp.nuclei[0].x == 100.0

    @pytest.mark.asyncio
    async def test_get_nuclei_in_viewport_max_results(self, svc, mock_session):
        """Verify max_results is passed to the query."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=100, y_max=100)
        await svc.get_nuclei_in_viewport(SLIDE_ID, bounds, max_results=10)
        # Just verify it executed without error
        mock_session.execute.assert_called_once()

    # ── get_roi_stats ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_roi_stats_empty(self, svc, mock_session):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=1000, y_max=1000)
        resp = await svc.get_roi_stats(SLIDE_ID, bounds, mpp=0.25)

        assert resp.total_nuclei == 0
        assert resp.density_per_mm2 == 0.0
        assert resp.neoplastic_ratio == 0.0
        assert resp.cell_type_breakdown == []

    @pytest.mark.asyncio
    async def test_get_roi_stats_with_data(self, svc, mock_session):
        row1 = MagicMock()
        row1.cell_type = 1
        row1.cell_type_name = "Neoplastic"
        row1.cnt = 30

        row2 = MagicMock()
        row2.cell_type = 2
        row2.cell_type_name = "Inflammatory"
        row2.cnt = 70

        mock_result = MagicMock()
        mock_result.all.return_value = [row1, row2]
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=4000, y_max=4000)
        resp = await svc.get_roi_stats(SLIDE_ID, bounds, mpp=0.25)

        assert resp.total_nuclei == 100
        assert resp.neoplastic_ratio == 0.3
        assert len(resp.cell_type_breakdown) == 2
        assert resp.cell_type_breakdown[0].fraction == 0.3
        assert resp.cell_type_breakdown[1].fraction == 0.7
        assert resp.area_mm2 > 0
        assert resp.density_per_mm2 > 0

    @pytest.mark.asyncio
    async def test_get_roi_stats_zero_area(self, svc, mock_session):
        """Zero-area ROI should return density=0."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        bounds = ViewportBounds(x_min=0, y_min=0, x_max=0, y_max=0)
        resp = await svc.get_roi_stats(SLIDE_ID, bounds, mpp=0.25)
        assert resp.density_per_mm2 == 0.0
