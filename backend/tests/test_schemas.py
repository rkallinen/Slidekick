"""
Tests for app.schemas.nucleus — Pydantic request/response schemas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.nucleus import (
    AnalysisBoxDetail,
    AnalysisBoxListResponse,
    AnalysisBoxOut,
    CellTypeCount,
    InferenceViewportRequest,
    NucleusBase,
    NucleusDetail,
    ROIStatsRequest,
    ROIStatsResponse,
    ScaleBarResponse,
    SlideOut,
    ViewportNucleiResponse,
    ViewportQuery,
)


# ═══════════════════════════════════════════════════════════════════
# SlideOut
# ═══════════════════════════════════════════════════════════════════
class TestSlideOut:
    def test_valid(self):
        s = SlideOut(
            id=uuid.uuid4(),
            filename="test.svs",
            mpp=0.25,
            width_px=10000,
            height_px=8000,
            created_at=datetime.now(timezone.utc),
        )
        assert s.filename == "test.svs"
        assert s.mpp == 0.25

    def test_from_attributes(self):
        """Confirm from_attributes model_config is set."""
        assert SlideOut.model_config.get("from_attributes") is True


# ═══════════════════════════════════════════════════════════════════
# NucleusBase / NucleusDetail
# ═══════════════════════════════════════════════════════════════════
class TestNucleusSchemas:
    def test_nucleus_base(self):
        nb = NucleusBase(
            id=1, x=100.5, y=200.3,
            cell_type=1, cell_type_name="Neoplastic",
            probability=0.95,
        )
        assert nb.x == 100.5
        assert nb.cell_type_name == "Neoplastic"

    def test_nucleus_detail_inherits(self):
        nd = NucleusDetail(
            id=1, x=10, y=20,
            cell_type=2, cell_type_name="Inflammatory",
            probability=0.8,
            area_um2=50.5,
            perimeter_um=28.0,
            contour=[[1, 2], [3, 4], [5, 6]],
        )
        assert nd.area_um2 == 50.5
        assert nd.contour == [[1, 2], [3, 4], [5, 6]]

    def test_nucleus_detail_defaults(self):
        nd = NucleusDetail(
            id=1, x=10, y=20,
            cell_type=0, cell_type_name="Background",
            probability=0.1,
        )
        assert nd.area_um2 is None
        assert nd.perimeter_um is None
        assert nd.contour is None


# ═══════════════════════════════════════════════════════════════════
# CellTypeCount
# ═══════════════════════════════════════════════════════════════════
class TestCellTypeCount:
    def test_valid(self):
        ct = CellTypeCount(
            cell_type=1, cell_type_name="Neoplastic",
            count=30, fraction=0.3,
        )
        assert ct.fraction == 0.3


# ═══════════════════════════════════════════════════════════════════
# AnalysisBox schemas
# ═══════════════════════════════════════════════════════════════════
class TestAnalysisBoxSchemas:
    def _make_box_out(self, **kw):
        defaults = dict(
            id=uuid.uuid4(),
            slide_id=uuid.uuid4(),
            label="Analysis 1",
            x_min=0.0, y_min=0.0, x_max=1000.0, y_max=1000.0,
            total_nuclei=100,
            area_mm2=0.0625,
            density_per_mm2=1600.0,
            neoplastic_ratio=0.3,
            cell_type_counts={"1": {"count": 30, "name": "Neoplastic"}},
            created_at=datetime.now(timezone.utc),
        )
        defaults.update(kw)
        return AnalysisBoxOut(**defaults)

    def test_analysis_box_out(self):
        b = self._make_box_out()
        assert b.total_nuclei == 100

    def test_analysis_box_detail(self):
        d = AnalysisBoxDetail(
            **self._make_box_out().model_dump(),
            cell_type_breakdown=[
                CellTypeCount(cell_type=1, cell_type_name="Neoplastic", count=30, fraction=0.3),
            ],
            shannon_h=0.6,
            inflammatory_index=0.2,
            immune_tumour_ratio=0.5,
            ne_epithelial_ratio=0.4,
            viability=0.95,
        )
        assert d.shannon_h == 0.6
        assert d.viability == 0.95

    def test_analysis_box_detail_defaults(self):
        d = AnalysisBoxDetail(**self._make_box_out().model_dump())
        assert d.cell_type_breakdown == []
        assert d.shannon_h == 0.0
        assert d.inflammatory_index == 0.0
        assert d.immune_tumour_ratio is None
        assert d.ne_epithelial_ratio is None
        assert d.viability == 0.0

    def test_analysis_box_list_response(self):
        box = self._make_box_out()
        resp = AnalysisBoxListResponse(
            slide_id=box.slide_id,
            boxes=[box],
        )
        assert len(resp.boxes) == 1


# ═══════════════════════════════════════════════════════════════════
# ViewportQuery
# ═══════════════════════════════════════════════════════════════════
class TestViewportQuery:
    def test_valid(self):
        vq = ViewportQuery(
            slide_id=uuid.uuid4(),
            x=100, y=200, width=300, height=400, level=0,
        )
        assert vq.level == 0

    def test_default_level(self):
        vq = ViewportQuery(
            slide_id=uuid.uuid4(),
            x=100, y=200, width=300, height=400,
        )
        assert vq.level == 0

    def test_negative_level_rejected(self):
        with pytest.raises(ValidationError):
            ViewportQuery(
                slide_id=uuid.uuid4(),
                x=100, y=200, width=300, height=400,
                level=-1,
            )

    def test_positive_level_accepted(self):
        vq = ViewportQuery(
            slide_id=uuid.uuid4(),
            x=0, y=0, width=100, height=100, level=5,
        )
        assert vq.level == 5


# ═══════════════════════════════════════════════════════════════════
# ViewportNucleiResponse
# ═══════════════════════════════════════════════════════════════════
class TestViewportNucleiResponse:
    def test_valid(self):
        resp = ViewportNucleiResponse(
            slide_id=uuid.uuid4(),
            bounds_l0={"x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100},
            nuclei=[],
        )
        assert resp.nuclei == []


# ═══════════════════════════════════════════════════════════════════
# InferenceViewportRequest
# ═══════════════════════════════════════════════════════════════════
class TestInferenceViewportRequest:
    def test_valid(self):
        req = InferenceViewportRequest(
            slide_id=uuid.uuid4(),
            x=0, y=0, width=512, height=512, level=0,
        )
        assert req.width == 512

    def test_default_level(self):
        req = InferenceViewportRequest(
            slide_id=uuid.uuid4(),
            x=0, y=0, width=100, height=100,
        )
        assert req.level == 0


# ═══════════════════════════════════════════════════════════════════
# ROI schemas
# ═══════════════════════════════════════════════════════════════════
class TestROISchemas:
    def test_roi_stats_request(self):
        req = ROIStatsRequest(
            slide_id=uuid.uuid4(),
            x_min=0, y_min=0, x_max=1000, y_max=1000,
        )
        assert req.x_max == 1000

    def test_roi_stats_response(self):
        resp = ROIStatsResponse(
            slide_id=uuid.uuid4(),
            total_nuclei=100,
            area_mm2=1.0,
            density_per_mm2=100.0,
            neoplastic_ratio=0.3,
            cell_type_breakdown=[],
            mpp=0.25,
            bounds_l0={"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
        )
        assert resp.density_per_mm2 == 100.0


# ═══════════════════════════════════════════════════════════════════
# ScaleBarResponse
# ═══════════════════════════════════════════════════════════════════
class TestScaleBarResponse:
    def test_valid(self):
        sb = ScaleBarResponse(
            target_um=100.0,
            pixels_at_level=400.0,
            level=0,
            mpp=0.25,
        )
        assert sb.pixels_at_level == 400.0
