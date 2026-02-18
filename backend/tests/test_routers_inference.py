"""
Tests for app.routers.inference — viewport inference, _compute_box_stats,
_assign_analysis_label, and SSE endpoint.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.inference import (
    _assign_analysis_label,
    _compute_box_stats,
    router,
)
from app.spatial.transform import ViewportBounds
from tests.conftest import SAMPLE_SLIDE_ID, make_slide_row


# ═══════════════════════════════════════════════════════════════════
# _compute_box_stats
# ═══════════════════════════════════════════════════════════════════
class TestComputeBoxStats:
    def _make_nuc(self, cell_type=1, cell_type_name="Neoplastic"):
        nuc = MagicMock()
        nuc.cell_type = cell_type
        nuc.cell_type_name = cell_type_name
        return nuc

    def test_empty_nuclei(self):
        bounds = ViewportBounds(x_min=0, y_min=0, x_max=1000, y_max=1000)
        stats = _compute_box_stats([], bounds, mpp=0.25)
        assert stats["total_nuclei"] == 0
        assert stats["neoplastic_ratio"] == 0.0
        assert stats["density_per_mm2"] == 0.0

    def test_with_nuclei(self):
        nuclei = [
            self._make_nuc(1, "Neoplastic"),
            self._make_nuc(1, "Neoplastic"),
            self._make_nuc(2, "Inflammatory"),
        ]
        bounds = ViewportBounds(x_min=0, y_min=0, x_max=4000, y_max=4000)
        stats = _compute_box_stats(nuclei, bounds, mpp=0.25)

        assert stats["total_nuclei"] == 3
        # 2 neoplastic / 3 total
        assert abs(stats["neoplastic_ratio"] - 2 / 3) < 1e-9
        assert stats["area_mm2"] > 0
        assert stats["density_per_mm2"] > 0
        assert "1" in stats["cell_type_counts"]
        assert "2" in stats["cell_type_counts"]

    def test_zero_area(self):
        nuclei = [self._make_nuc()]
        bounds = ViewportBounds(x_min=0, y_min=0, x_max=0, y_max=0)
        stats = _compute_box_stats(nuclei, bounds, mpp=0.25)
        assert stats["density_per_mm2"] == 0.0


# ═══════════════════════════════════════════════════════════════════
# _assign_analysis_label
# ═══════════════════════════════════════════════════════════════════
class TestAssignAnalysisLabel:
    @pytest.mark.asyncio
    async def test_first_label(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 1"

    @pytest.mark.asyncio
    async def test_next_available(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "Analysis 1", "Analysis 2", "Analysis 3",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 4"

    @pytest.mark.asyncio
    async def test_gap_filling(self):
        """Should fill gaps: [1,3] → 2."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "Analysis 1", "Analysis 3",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 2"

    @pytest.mark.asyncio
    async def test_non_matching_labels_ignored(self):
        """Labels not matching 'Analysis N' should be ignored."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "Custom Label", "My Analysis", "Analysis 1",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 2"

    @pytest.mark.asyncio
    async def test_non_string_labels_ignored(self):
        """Non-string labels should be silently skipped."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            None, 123, "Analysis 1",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 2"

    @pytest.mark.asyncio
    async def test_whitespace_in_label(self):
        """Labels with extra whitespace should still match."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "  Analysis 1  ", "Analysis 2",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 3"

    @pytest.mark.asyncio
    async def test_very_large_number(self):
        """Analysis label with a very large number should still parse."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "Analysis 999999999999999999999999",
        ]
        mock_db.execute.return_value = mock_result

        label = await _assign_analysis_label(mock_db, SAMPLE_SLIDE_ID)
        assert label == "Analysis 1"


# ═══════════════════════════════════════════════════════════════════
# POST /inference/viewport-stream (SSE endpoint)
# ═══════════════════════════════════════════════════════════════════

def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture()
def inf_app():
    return _create_test_app()


@pytest.fixture()
def inf_mock_db():
    return AsyncMock()


@pytest.fixture()
def inf_client(inf_app, inf_mock_db):
    from app.models.database import get_db

    async def override_get_db():
        yield inf_mock_db

    inf_app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=inf_app)
    return AsyncClient(transport=transport, base_url="http://testserver")


class TestViewportStream:
    """Test the SSE infer_viewport_stream endpoint."""

    def _make_request_body(self, **overrides):
        body = {
            "slide_id": str(SAMPLE_SLIDE_ID),
            "x": 0,
            "y": 0,
            "width": 1000,
            "height": 1000,
        }
        body.update(overrides)
        return body

    @pytest.mark.asyncio
    async def test_slide_not_found(self, inf_client, inf_mock_db):
        """When slide doesn't exist, SSE should stream error event."""
        inf_mock_db.get.return_value = None

        resp = await inf_client.post(
            "/api/inference/viewport-stream",
            json=self._make_request_body(),
        )
        # SSE returns 200 with text/event-stream
        assert resp.status_code == 200
        # Parse SSE body for error event
        assert "Slide not found" in resp.text

    @pytest.mark.asyncio
    async def test_invalid_bounds(self, inf_client, inf_mock_db):
        """When bounds result in zero or negative dimensions, should stream error."""
        slide = make_slide_row()
        inf_mock_db.get.return_value = slide

        resp = await inf_client.post(
            "/api/inference/viewport-stream",
            json=self._make_request_body(width=0, height=0),
        )
        assert resp.status_code == 200
        assert "Invalid viewport bounds" in resp.text

    @pytest.mark.asyncio
    @patch("app.routers.inference.bulk_insert_nuclei_async", new_callable=AsyncMock)
    @patch("app.routers.inference.get_slide_service")
    @patch("app.routers.inference.get_inference_engine")
    async def test_successful_inference(
        self, mock_engine_fn, mock_svc_fn, mock_bulk_insert,
        inf_client, inf_mock_db,
    ):
        """Full successful inference flow through SSE."""
        slide = make_slide_row()
        inf_mock_db.get.return_value = slide

        # Mock engine
        mock_engine = MagicMock()
        from app.services.inference import InferenceResult, DetectedNucleus
        fake_nuc = DetectedNucleus(
            centroid_x=500, centroid_y=400,
            contour=np.array([[490, 390], [510, 390], [510, 410], [490, 410]]),
            cell_type=1, cell_type_name="Neoplastic",
            probability=0.95,
        )
        fake_result = InferenceResult(nuclei=[fake_nuc], tile_x=0, tile_y=0, tile_w=1000, tile_h=1000)
        mock_engine.infer_tile.return_value = fake_result
        mock_engine_fn.return_value = mock_engine

        # Mock slide service
        mock_svc = MagicMock()
        mock_svc.read_region_l0.return_value = np.zeros((1000, 1000, 3), dtype=np.uint8)
        mock_svc_fn.return_value = mock_svc

        # Mock bulk insert
        mock_bulk_insert.return_value = 1

        # Mock _assign_analysis_label
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        inf_mock_db.execute.return_value = mock_result

        # Mock flush to set box.id
        async def mock_flush():
            pass

        inf_mock_db.flush = AsyncMock(side_effect=mock_flush)
        inf_mock_db.commit = AsyncMock()

        # We also need the box to have a proper id after flush
        added_objects = []
        original_add = inf_mock_db.add

        def capture_add(obj):
            added_objects.append(obj)
            obj.id = uuid.uuid4()
            obj.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        inf_mock_db.add = capture_add

        resp = await inf_client.post(
            "/api/inference/viewport-stream",
            json=self._make_request_body(),
        )
        assert resp.status_code == 200
        assert "complete" in resp.text

    @pytest.mark.asyncio
    @patch("app.routers.inference.get_slide_service")
    @patch("app.routers.inference.get_inference_engine")
    async def test_inference_exception(
        self, mock_engine_fn, mock_svc_fn,
        inf_client, inf_mock_db,
    ):
        """When inference raises an exception, should stream error event."""
        slide = make_slide_row()
        inf_mock_db.get.return_value = slide

        mock_svc = MagicMock()
        mock_svc.read_region_l0.side_effect = RuntimeError("OpenSlide crash")
        mock_svc_fn.return_value = mock_svc

        resp = await inf_client.post(
            "/api/inference/viewport-stream",
            json=self._make_request_body(),
        )
        assert resp.status_code == 200
        assert "error" in resp.text
        assert "Inference failed" in resp.text

    @pytest.mark.asyncio
    @patch("app.routers.inference.bulk_insert_nuclei_async", new_callable=AsyncMock)
    @patch("app.routers.inference.get_slide_service")
    @patch("app.routers.inference.get_inference_engine")
    async def test_inference_with_progress(
        self, mock_engine_fn, mock_svc_fn, mock_bulk_insert,
        inf_client, inf_mock_db,
    ):
        """Exercise progress_callback (line 167) and the while-loop (branch 190→187)."""
        import time
        slide = make_slide_row()
        inf_mock_db.get.return_value = slide

        mock_engine = MagicMock()
        from app.services.inference import InferenceResult, DetectedNucleus
        fake_nuc = DetectedNucleus(
            centroid_x=500, centroid_y=400,
            contour=np.array([[490, 390], [510, 390], [510, 410], [490, 410]]),
            cell_type=1, cell_type_name="Neoplastic",
            probability=0.95,
        )
        fake_result = InferenceResult(
            nuclei=[fake_nuc], tile_x=0, tile_y=0, tile_w=1000, tile_h=1000,
        )

        def slow_infer(**kwargs):
            """Simulate slow inference that calls progress_callback."""
            cb = kwargs.get("progress_callback")
            if cb:
                cb(1, 10, "Step 1")
            # Sleep long enough for the while-loop to iterate at least twice
            # (each iteration sleeps 0.3s).  The second iteration sees the
            # same progress value → exercises branch 190→187 (no-yield path).
            time.sleep(1.0)
            if cb:
                cb(10, 10, "Done")
            return fake_result

        mock_engine.infer_tile.side_effect = slow_infer
        mock_engine_fn.return_value = mock_engine

        mock_svc = MagicMock()
        mock_svc.read_region_l0.return_value = np.zeros((1000, 1000, 3), dtype=np.uint8)
        mock_svc_fn.return_value = mock_svc

        mock_bulk_insert.return_value = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        inf_mock_db.execute.return_value = mock_result
        inf_mock_db.flush = AsyncMock()
        inf_mock_db.commit = AsyncMock()

        def capture_add(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        inf_mock_db.add = capture_add

        resp = await inf_client.post(
            "/api/inference/viewport-stream",
            json=self._make_request_body(),
        )
        assert resp.status_code == 200
        assert "progress" in resp.text
        assert "complete" in resp.text