"""
Tests for app.routers.boxes — Analysis box CRUD endpoints.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.boxes import router
from tests.conftest import SAMPLE_BOX_ID, SAMPLE_SLIDE_ID, make_box_row, make_slide_row


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
# GET /boxes/{slide_id}
# ═══════════════════════════════════════════════════════════════════
class TestListBoxes:
    @pytest.mark.asyncio
    async def test_list_boxes_slide_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/boxes/{SAMPLE_SLIDE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_boxes_empty(self, client, mock_db):
        mock_db.get.return_value = make_slide_row()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        resp = await client.get(f"/api/boxes/{SAMPLE_SLIDE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["boxes"] == []
        assert data["slide_id"] == str(SAMPLE_SLIDE_ID)

    @pytest.mark.asyncio
    async def test_list_boxes_with_data(self, client, mock_db):
        mock_db.get.return_value = make_slide_row()

        box = make_box_row()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [box]
        mock_db.execute.return_value = mock_result

        resp = await client.get(f"/api/boxes/{SAMPLE_SLIDE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["boxes"]) == 1


# ═══════════════════════════════════════════════════════════════════
# GET /boxes/detail/{box_id}
# ═══════════════════════════════════════════════════════════════════
class TestGetBoxDetail:
    @pytest.mark.asyncio
    async def test_box_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_box_detail_with_breakdown(self, client, mock_db):
        box = make_box_row(
            total_nuclei=100,
            cell_type_counts={
                "0": {"count": 5, "name": "Background"},
                "1": {"count": 30, "name": "Neoplastic"},
                "2": {"count": 20, "name": "Inflammatory"},
                "3": {"count": 15, "name": "Connective"},
                "4": {"count": 10, "name": "Dead"},
                "5": {"count": 20, "name": "Non-Neoplastic Epithelial"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["cell_type_breakdown"]) == 6
        assert data["total_nuclei"] == 100
        assert data["shannon_h"] > 0
        assert data["viability"] == 0.9  # (100 - 10) / 100
        assert data["inflammatory_index"] is not None
        assert data["neoplastic_ratio"] == 0.3

    @pytest.mark.asyncio
    async def test_box_detail_zero_nuclei(self, client, mock_db):
        box = make_box_row(total_nuclei=0, cell_type_counts={})
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shannon_h"] == 0.0
        assert data["viability"] == 0.0

    @pytest.mark.asyncio
    async def test_box_detail_no_epithelial(self, client, mock_db):
        """When epithelial count = 0 and neoplastic > 0, ne_epithelial_ratio should be None."""
        box = make_box_row(
            total_nuclei=50,
            cell_type_counts={
                "1": {"count": 30, "name": "Neoplastic"},
                "2": {"count": 20, "name": "Inflammatory"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ne_epithelial_ratio"] is None  # num>0, denom=0

    @pytest.mark.asyncio
    async def test_box_detail_no_neoplastic(self, client, mock_db):
        """When neoplastic=0 and inflammatory>0, immune_tumour_ratio should be None."""
        box = make_box_row(
            total_nuclei=50,
            cell_type_counts={
                "2": {"count": 50, "name": "Inflammatory"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["immune_tumour_ratio"] is None

    @pytest.mark.asyncio
    async def test_box_detail_both_zero_ratio(self, client, mock_db):
        """When both num=0 and denom=0, safe_ratio returns 0.0."""
        box = make_box_row(
            total_nuclei=50,
            cell_type_counts={
                "3": {"count": 50, "name": "Connective"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        # immune_tumour_ratio: num=0(inflammatory), denom=0(neoplastic) → 0.0
        assert data["immune_tumour_ratio"] == 0.0
        # ne_epithelial_ratio: num=0(neoplastic), denom=0(epithelial) → 0.0
        assert data["ne_epithelial_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_box_detail_cell_type_counts_plain_int(self, client, mock_db):
        """Handle cell_type_counts where value is a plain int, not dict."""
        box = make_box_row(
            total_nuclei=50,
            cell_type_counts={
                "1": 30,
                "2": 20,
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        # Should handle both dict and int formats
        assert len(data["cell_type_breakdown"]) == 2

    @pytest.mark.asyncio
    async def test_box_detail_all_cell_types_present(self, client, mock_db):
        """When all 6 cell types are present, count_of finds each one."""
        box = make_box_row(
            total_nuclei=120,
            cell_type_counts={
                "0": {"count": 10, "name": "Background"},
                "1": {"count": 25, "name": "Neoplastic"},
                "2": {"count": 20, "name": "Inflammatory"},
                "3": {"count": 25, "name": "Connective"},
                "4": {"count": 15, "name": "Dead"},
                "5": {"count": 25, "name": "Non-Neoplastic Epithelial"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["cell_type_breakdown"]) == 6
        # ne_epithelial_ratio = 25/25 = 1.0
        assert data["ne_epithelial_ratio"] == 1.0
        # immune_tumour_ratio = 20/25 = 0.8
        assert abs(data["immune_tumour_ratio"] - 0.8) < 1e-9

    @pytest.mark.asyncio
    async def test_box_detail_only_dead_cells(self, client, mock_db):
        """When only dead cells present, viability = 0."""
        box = make_box_row(
            total_nuclei=50,
            cell_type_counts={
                "1": {"count": 0, "name": "Neoplastic"},  # zero-count triggers branch 115→114
                "4": {"count": 50, "name": "Dead"},
            },
        )
        mock_db.get.return_value = box

        resp = await client.get(f"/api/boxes/detail/{SAMPLE_BOX_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["viability"] == 0.0
        # count_of(1) for neoplastic → 0 (loop finds it but count is 0)
        assert data["neoplastic_ratio"] is not None


# ═══════════════════════════════════════════════════════════════════
# DELETE /boxes/{box_id}
# ═══════════════════════════════════════════════════════════════════
class TestDeleteBox:
    @pytest.mark.asyncio
    async def test_delete_not_found(self, client, mock_db):
        mock_db.get.return_value = None
        resp = await client.delete(f"/api/boxes/{SAMPLE_BOX_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(self, client, mock_db):
        box = make_box_row()
        mock_db.get.return_value = box

        resp = await client.delete(f"/api/boxes/{SAMPLE_BOX_ID}")
        assert resp.status_code == 204
        mock_db.delete.assert_called_once_with(box)
        mock_db.commit.assert_awaited_once()
