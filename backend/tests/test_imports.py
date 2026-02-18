"""
Tests for package __init__ imports — verifies all public symbols are accessible.
"""
from __future__ import annotations


class TestModelsInit:
    def test_all_exports(self):
        from app.models import (
            Base,
            engine,
            async_session_factory,
            get_db,
            init_models,
            AnalysisBox,
            Nucleus,
            Slide,
        )
        assert Base is not None
        assert Slide is not None
        assert init_models is not None


class TestSchemasInit:
    def test_all_exports(self):
        from app.schemas import (
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
        assert SlideOut is not None


class TestServicesInit:
    def test_all_exports(self):
        from app.services import (
            NucleiStreamer,
            bulk_insert_nuclei_async,
            HoVerNetEngine,
            get_inference_engine,
            SlideService,
            get_slide_service,
            invalidate_slide_service,
            SpatialQueryService,
        )
        assert HoVerNetEngine is not None


class TestRoutersInit:
    def test_all_exports(self):
        from app.routers import boxes, inference, roi, slides
        assert boxes is not None
        assert slides is not None


class TestSpatialInit:
    def test_all_exports(self):
        from app.spatial import CoordinateTransformer, ViewportBounds
        assert CoordinateTransformer is not None
        assert ViewportBounds is not None


class TestAppInit:
    def test_app_package(self):
        import app
        assert app is not None
